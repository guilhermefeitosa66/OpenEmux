# Phase 10: Cartridge Pre-Render

**Goal:** Replace the runtime cartridge compositing (cover behind a frame PNG, positioned by hand-tuned rectangles) with a single **pre-rendered image** per ROM — the cover art already composited into the cartridge frame — so the grid just loads one flat picture.

## Motivation

Two concrete problems drive this phase.

**Problem 1 — no more hand-tuned coordinates.** The current cartridge look positions the cover with `CARTRIDGE_COVER_FRAMES[console] = (x, y, w, h)` magic numbers, eyeballed per console. Adding a frame means measuring pixels by hand. The goal is a **dynamic, automatic** placement: the frame PNG itself declares where the label goes (a pure-green window, or a transparent alpha window), and the code *detects* that region — the author never types a coordinate.

**Problem 2 — cheap to display many ROMs.** Today the composition (cover into `Gtk.Fixed` at the label rect, frame PNG stacked on top via `Gtk.Overlay`) is rebuilt live for **every card**, so a large library pays overlay + Fixed + per-card layout cost on every grid rebuild. Pre-rendering composes the frame+cover **once**, caches the result to disk, and the grid then draws a single flat `Gtk.Picture` per ROM — same cost as a plain cover, no overlay tree.

Current live-compositing pain, for reference:

- the cover goes into a `Gtk.Fixed` at `CARTRIDGE_COVER_FRAMES[console]` coords `(x, y, w, h)`;
- the frame PNG is stacked on top via `Gtk.Overlay`, showing the cover through its transparent window;
- per-console magic numbers live in `CARTRIDGE_COVER_FRAMES` and `CARTRIDGE_ITEM_SIZES`;
- only axis-aligned rectangular windows are supported (angled labels like SFC/MD are hard);
- everything is redone on every rebuild of the grid.

Pre-rendering + auto-detected label windows solves both: compose **once** off a self-describing frame PNG, cache to disk, and render a normal `Gtk.Picture`.

## Approach

1. A per-console **frame descriptor** declares the frame PNG plus where/how the label art sits inside it.
2. A **compositor** (Cairo) draws the cover into the label window and stamps the frame on top, producing one PNG.
3. Results are **cached on disk**, keyed on cover + frame version, and regenerated only when inputs change.
4. The grid, when the cartridge look is on, resolves the cached composite and shows it with no overlay/Fixed math.

### 1. Self-describing frame — the label window comes from the source art (Problem 1)

**The label region is read from the frame art, never typed by hand.** Recommended format: an **SVG** that already contains the cartridge art plus one **named container object** (the Inkscape "clip" object), identified by a known `id` (e.g. `id="label-clip"`). The compositor asks librsvg for that object's geometry/shape and drops the cover into it. Adding a console = drop in one SVG. No coordinates, no per-console dict entry.

Pipeline (via `Rsvg` + Cairo, runs once per frame; geometry cached):

1. `handle = Rsvg.Handle.new_from_file(svg)`; output size = frame intrinsic size × target scale.
2. `handle.get_geometry_for_layer("#label-clip", viewport)` → label bbox `(x, y, w, h)` in output space (drives cover scaling/positioning). No hand coordinates.
3. `handle.render_layer(cr, "#label-clip", viewport)` onto an alpha surface → a **mask** in the object's *exact* shape (rounded, angled, non-rectangular — all free).
4. Draw the cover scaled to cover the label bbox, `cr.mask(shape_surface)` → cover clipped to the object.
5. Render the frame on top with the container hidden (`display:none` on that node, or authored with no fill) → the cartridge art, label window revealing the cover.

Why SVG over a raster window:

- **Vectorial → crisp at any size/DPI**; the composite can be rasterised at whatever pixel size the grid (or a detail view) needs.
- **Arbitrary clip shape** including rotation and rounded corners, which the old axis-aligned overlay could not do.
- **No chroma-key fringe** — the mask is a proper alpha shape, not a colour match.
- You are drawing the container object anyway, so authoring cost is unchanged.

Per-console data collapses to the filename (`assets/images/cartridges/<ID>.svg`), resolved by convention — so `CARTRIDGE_COVER_FRAMES` and `CARTRIDGE_ITEM_SIZES` are **deleted outright**.

**Fallback formats (no new dependency):** if a frame is only available as a raster PNG, the same compositor accepts a window marked by a **transparent alpha region** (bbox + mask from the alpha channel) or a **pure-green window** (`#00FF00`, `GdkPixbuf.add_alpha(True, 0, 255, 0)`). Green requires hard, non-anti-aliased edges to avoid a fringe. SVG is the standard; these exist so a PNG-only frame still works.

**Dependency:** SVG rendering needs the librsvg GObject-introspection typelib (`gir1.2-rsvg-2.0` on Debian/Ubuntu; `librsvg2`/`librsvg2-tools` provides it on Fedora). The runtime `.so` (`librsvg2-2`) is already present on this machine — only the typelib binding is missing; add it to `make bootstrap` system deps and to the `.deb`/`.rpm` packaging. The Flatpak GNOME runtime already ships Rsvg, so Flathub needs no change.

### 2. Compositor

New helper (`core/cartridge_render.py`), pure Cairo/GdkPixbuf, no widgets:

```
render_cartridge(cover_path, frame_file, target_size) -> cairo.Surface   # rasterise + cache as PNG
```

Steps (SVG path; the raster fallbacks differ only in how the window is detected):
1. Load the frame (`Rsvg.Handle` for SVG) at the target output size → defines the surface.
2. Resolve the label window from the named container object — bbox for positioning, alpha shape for masking. Cache the geometry/mask per frame so it runs once, not per ROM.
3. Draw the cover scaled to **cover** the label bbox (crop-to-fill, matching today's `ContentFit.COVER`), `cr.mask()`ed to the object's shape (rotation/rounded corners come from the shape itself).
4. Render the frame on top (container hidden) so the cartridge art frames the cover.
5. Rasterise and write PNG to the cache path.

Because step 1 renders from the vector source, `target_size` is free to choose — the same helper feeds a 200px grid thumbnail or a large detail view without re-authoring anything.

### 3. Cache

- Location: `<roms>/covers/<console>/.cartridge/<rom_name>.png` (co-located with covers, hidden dir so it is skipped by the scanner/sync globs — verify the scanner ignores dotdirs, else use `~/.openemux/cache/cartridge/<console>/`).
- Key / invalidation: regenerate when the source cover's mtime/size changes, or when a global `FRAME_CACHE_VERSION` constant bumps (frame art or compositor logic changed). Store the key in the filename or a sidecar; simplest is `mtime` compare against the source cover.
- Lifecycle hooks: invalidate/delete on `save_local_cover` / `remove_local_covers` (a cover swap must drop the stale composite). Clearing the cache dir must be safe — it is fully regenerable.

### 4. Grid integration

- `grid.py` keeps deciding *whether* the cartridge look is active (`render_cartridge_overlay` + a frame exists for the console + not `mixed_consoles`), but stops owning the geometry.
- When active, `RomItem` requests the composite via the existing async `fetch_cover` path, extended so that on a cartridge console it returns the **pre-rendered** path (rendering lazily on the worker thread if the cache is cold) instead of the raw cover.
- The card then shows one plain `Gtk.Picture` sized to the frame's aspect. Delete `cover_frame`, `_cover_host`/`Gtk.Fixed`, `cartridge_overlay` overlay wiring, `CARTRIDGE_COVER_FRAMES`, `CARTRIDGE_ITEM_SIZES`, and the `_cover_target_size/_position` frame branches.
- Card outer size still comes from the frame proportions (`FIXED_ITEM_WIDTH` × proportional height), computed once from the frame's intrinsic size.

**Pre-render vs. direct render.** The grid uses the **cached raster** (Problem 2 — many cards must be cheap; a flat `Gtk.Picture` from a PNG is the lightest option, and the SVG is rendered at most once per cover). The *same* `render_cartridge` helper can also render **on demand** with no cache — appropriate for a single large detail/hero view, or as a fallback when the cache dir is unwritable. One SVG source, both display modes.

### 5. No-cover fallback

Today a missing cover shows the icon placeholder. Options, cheapest first:
- keep the current icon placeholder (no frame) when there is no cover; or
- render a **blank cartridge** (the frame SVG with the container empty) so the shelf still reads as cartridges. Recommend the blank-cartridge render — it is the same helper with no cover drawn into the window, and is more consistent visually.

## Edge cases / risks

- **HiDPI:** render from the vector source at `scale × target_size` (or 2× and tag the paintable scale) — SVG makes crisp HiDPI trivial, unlike a fixed raster.
- **Green fringe:** only a concern for the raster green-key *fallback*; the SVG path renders a proper alpha mask and has no fringe. Prefer SVG; if green must be used, author hard (non-AA) edges.
- **Angled/rounded labels:** the payoff — SFC/MD/etc. sit at the real cartridge angle because the clip follows the container object's shape; validate each frame visually.
- **Cache staleness:** the invalidation hooks are the sharp edge — a cover replaced while the app is open must not keep the old cartridge. Cover the `save`/`remove` paths in tests.
- **Missing Rsvg typelib:** if `gir1.2-rsvg-2.0` is absent, SVG frames can't render — detect at startup and either fall back to the icon placeholder for those consoles or surface a clear bootstrap error. Raster (alpha/green) frames still work without it.
- **Disk usage:** one extra PNG per ROM-with-cover on cartridge consoles; hidden cache dir, regenerable, cleared by a "rebuild cartridge cache" maintenance action (nice-to-have).

## Dependencies

- **librsvg introspection typelib** (`gir1.2-rsvg-2.0` Debian/Ubuntu; the `librsvg2` gir on Fedora). Runtime `.so` `librsvg2-2` is already installed here; only the typelib is missing. Add to `make bootstrap` system deps and to the `.deb`/`.rpm` recipes. Flatpak GNOME runtime already provides it — no Flathub change.
- **pycairo** for the compositing surface (already pulled in transitively by PyGObject; confirm it's importable as `cairo`).

## Migration & cleanup

- Delete `CARTRIDGE_COVER_FRAMES` and `CARTRIDGE_ITEM_SIZES` from `grid.py`; the label geometry now comes from the frame source, not code.
- Re-author the existing 3 frames (FC/SFC/GBA) as SVGs with a named container object so they feed the compositor; the remaining cartridge consoles are tracked separately (memory: cartridge-frames-pending). **New frames become drop-in: one SVG, zero code.**
- Remove the now-dead overlay/Fixed code once the pre-render path is the only one.

## Testing

- `core/cartridge_render.py`: composite is deterministic — assert output size == target, that the label region contains cover pixels (not transparent), and that pixels outside the container shape are frame art, not cover.
- Container detection: `get_geometry_for_layer` bbox matches a known fixture SVG; the shape mask clips a rotated/rounded container correctly.
- Cache: cold render creates the file; second call is a hit (no rewrite); changing the cover mtime forces a re-render; `remove` deletes the composite.
- Gracefully degrade when Rsvg is unavailable (fixture without the typelib → fallback path, no crash).
- Keep tests widget-free (compositor lives in `core/`), consistent with the UI/core split. (Rsvg via `gi` is core-safe; it is not a GTK-widget import.)

## Open questions

1. ~~Cache under `<roms>/covers/.../.cartridge/` vs `~/.openemux/cache/`?~~ **Settled:** `~/.openemux/cache/cartridges/<console>/`, so the ROM tree is never touched and the scanner/sync globs need no changes.
2. ~~Container-object convention: `id` vs `inkscape:label`?~~ **Settled:** both. The compositor looks for `id="label-clip"` first and falls back to any element whose `inkscape:label` is `label-clip`, resolving it to that element's real `id` for `get_geometry_for_layer`/`render_layer`. The author just names the object in Inkscape's Object Properties — no XML editing.
3. Eager pre-render during cover sync vs purely lazy on first display — POC is lazy (rendered on the existing `fetch_cover` worker thread).
4. Accept raster (alpha/green) frames as a permanent fallback, or SVG-only once all frames are re-authored? Still open; the legacy PNG overlay path is untouched so far.

## POC findings (GB)

- **`get_geometry_for_layer` ignores the viewport scale.** With librsvg 2.58 it returns the layer box in *user units* whatever viewport is passed, so the bbox came back at 1× while `render_layer` correctly drew at the requested size. The compositor now measures against the intrinsic viewport and scales the box itself — correct either way, no version sniffing.
- **Z-order is part of the authoring contract.** The marker object must sit *below* the cartridge art, and the art must be transparent over it: the compositor paints the cover first (masked to the marker's shape) and then the frame with the marker removed, so the art's own window is what reveals the cover.
- **The frame is stripped, not hidden.** Two `Rsvg.Handle`s are built from the same source — the original (used only to measure and stencil the marker) and a copy with the marker element removed via ElementTree. Rendering the full document over the cover would repaint the marker's fill on top of it.
- **Blank label tone.** The label shape is filled with a neutral sticker colour before the cover is drawn: it *is* the no-cover cartridge, and it backs the anti-aliased edge so the window never lets the page background through.
- **Cover → cairo surface without Gdk.** GdkPixbuf loads/scales (crop-to-fill) and the result goes through `save_to_bufferv("png")` into `ImageSurface.create_from_png`, keeping the compositor free of any GTK import.
- **Cache key instead of invalidation hooks.** The filename carries a hash of cover mtime/size + frame mtime + output size + `FRAME_CACHE_VERSION`, and siblings of the same ROM are dropped on write. A replaced or removed cover invalidates itself, so `save_local_cover`/`remove_local_covers` need no extra wiring.
- **`Gtk.Picture` measures as its texture.** It reports the paintable's pixel size as the *natural* size and `set_size_request` only raises the minimum, so the 2× composite made every card twice as large. `CartridgePicture` overrides `do_measure` to report the card size while GTK still draws from the full-resolution texture.
- **librsvg handles are not thread-safe.** Grid cards are filled from several worker threads; sharing one `Rsvg.Handle` across them aborts the *whole process* with a Rust `BorrowMutError` panic (`fatal runtime error`, core dump). Every use of the handles is serialised behind a per-frame lock, and the label geometry/stencil is memoised per output size so the lock is held briefly. Cover-less ROMs also raced on one shared `.tmp` name; the temporary file is now per-thread.

## Status

- **Done.** `core/cartridge_render.py` (compositor + disk cache) plus the grid path that shows one flat `CartridgePicture`. `gir1.2-rsvg-2.0` added to `make install-sys-deps`, the `.deb` deps and the AppImage recipe.
- **Nine SVG frames:** FC, GB, GBC, GBA, N64, NDS, MD, SMS, SFC. The three PNG frames were re-authored, so the runtime overlay is gone: `CARTRIDGE_COVER_FRAMES`, `CARTRIDGE_ITEM_SIZES`, the shared texture cache, the `Gtk.Fixed` cover host and the cartridge `Gtk.Overlay` were all deleted. The *Migration & cleanup* section above is complete.
- Open question 4 answered by deletion: **SVG-only**. There is no raster-frame path left.
- Not yet done: eager pre-render during cover sync, a "rebuild cartridge cache" maintenance action, and validating on a HiDPI display (frames render at 2× and are handed to GTK as a `Gdk.Texture`).
- Consoles with a narrow label (SFC, SMS, GBA) crop box art hard, since the cover is fitted crop-to-fill into a wide, short window. That is what `LABEL_ART` (ScreenScraper's `support-2D` cartridge scans) is for — the card already prefers it over the box art.
