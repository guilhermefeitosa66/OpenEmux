# Tools

Developer tooling that is not part of the shipped application code. Nothing
here is imported by the app, and nothing here ships in a package.

| Tool | What it is for | How to run it |
| --- | --- | --- |
| `generate_name_db.py` | Regenerates the game-name database the cover lookup reads | `make name-db` |
| `icon_browser.py` | Browse the symbolic icons the UI is allowed to use | `make icons` |
| `gen_cartridge_colors.py` | Generate the per-colour copies of every cartridge frame | see below |
| `selection_input_harness.py` | Drive the real grid with synthesized input on a nested X server | see below |
| `grid_virtualization_probe.py` | Assert the grid still builds only a screenful of cards | see below |

The last three exist because the unit suite cannot reach what they check:
without a display, constructing a GTK widget segfaults the interpreter
(`tests/gtk_display.py`), so nothing under `tests/` ever builds a `RomGrid`.
They run against [Xephyr], a nested X server, and each one exits `0` when
every check passes — which is what makes them usable from the regression test
book rather than only by hand.

[Xephyr]: https://www.freedesktop.org/wiki/Software/Xephyr/

## `generate_name_db.py` — the game-name database (issue #184)

Regenerates `src/openemux/data/games.db.zip`: the SQLite + FTS5 game-name
base consumed by the staged cover lookup (issue #175, stage 1 and stage 4)
and the manual cover-picker suggestions (issue #185).

```bash
make name-db                       # uses ../openemux-artwork
make name-db MIRROR=/path/mirror DATS=/path/dats
```

### Source of truth

A local checkout of [`openemux-artwork`](https://github.com/guilhermefeitosa66/openemux-artwork)
— the project's own mirror. Every row in the database corresponds to an
artwork file that actually exists there, the stored stems already carry the
libretro filename convention (`&*/:` etc. replaced with `_`), and a
regeneration needs nothing beyond `git pull` in the mirror — zero load on
libretro's infrastructure. The upstream thumbnail set changes rarely
(once in 2025), so regenerating 1–2× a year after a mirror sync is enough.

The first version of this base was built end-to-end by
[@mozertdev](https://github.com/mozertdev) (#188), who prototyped the whole
pipeline and settled the FTS5 approach; this generator reproduces it from
the mirror.

### Delivery

The zip ships **inside the package tree** (`src/openemux/data/`), so every
packaging path that ships `src/openemux` — AppImage, .deb/.rpm, Flatpak,
source checkout — carries it automatically (~2 MB). The app extracts it on
first use to `~/.openemux/artwork-index/games.db`
(`openemux.core.artwork_index`). This full cross-system shape supersedes
the per-system `index/<System>.db` delivery sketched in #175.

### Optional: CRC index (stage 1)

Passing `DATS=<dir>` — a directory of logiqx-XML DAT files named
`<Thumbnail System Name>.dat` (from
[libretro-database](https://github.com/libretro/libretro-database),
No-Intro/Redump) — adds the `crc_index` table, which lets stage 1 of the
lookup ladder resolve a renamed ROM by CRC32. Only entries whose name has
artwork in the mirror are kept. Without DATs the table is absent and the
app silently skips the hash stage.

## `games.db` schema

```sql
games(id INTEGER PRIMARY KEY, name TEXT, system TEXT)
games_fts    -- FTS5 over (name, system), content='games'
crc_index(crc32 TEXT, system TEXT, name TEXT)   -- optional
```

`name` is the artwork filename stem; `system` the libretro thumbnail
system name (e.g. `Nintendo - Super Nintendo Entertainment System`).

## `icon_browser.py` — pick an icon for the UI

A searchable grid of the symbolic icons, rendered through the app's own theme
and stylesheet, with the icon name under each one; clicking one copies its name
to the clipboard. The icons the view-mode segmented control uses today are
marked, so a candidate can be compared against what is already in the UI.

```bash
make icons                  # browse everything
make icons FILTER=view      # open on a filter
```

**Only Adwaita is listed, deliberately.** The developer's desktop usually has
extra icon themes installed (Papirus, Numix, Mint's XApp set) and the running
GTK theme happily offers all of them — but an icon from those renders as a
broken image on a stock GNOME system, inside the Flatpak's GNOME runtime, or on
any distro without that theme package. `adwaita-icon-theme` is what the
packages declare as a dependency, so Adwaita plus GTK's own built-ins is exactly
the safe set.

## `gen_cartridge_colors.py` — the coloured cartridge frames

Writes a `<CONSOLE>-<colour>.svg` beside every cartridge frame: the original
file plus a "Colorize" filter (Inkscape's *Filters > Color > Colorize* chain —
desaturate, flat colour, multiply, clip back to the art's alpha) applied to the
element labelled `frame`. The label-clip marker is never touched, and the
colours come from issue #79.

```bash
.venv/bin/python tools/gen_cartridge_colors.py          # every base frame
.venv/bin/python tools/gen_cartridge_colors.py MD SMS   # only these
```

It reads the SVGs through `Rsvg` to measure each shell, so it needs the
PyGObject stack — the project venv, not a bare `python3` (see the pyenv trap in
[`packaging/README.md`](../packaging/README.md)).

The chain carries one primitive Inkscape's does not: a linear luminance ramp
between the desaturate and the flood. `multiply` can only darken, so a black
shell (MD, SMS) multiplied by any colour stays black; the ramp normalises each
console's own plastic to the same light-grey band first — measured from the
embedded artwork — which is what makes one colour read the same across every
console.

## `selection_input_harness.py` — grid input, on a real display

Runs the production `RomGrid` inside a `ScrolledWindow` on a nested X server
and drives it with XTest-synthesized pointer and keyboard events. It is the
only thing in the repository that exercises the GTK gesture stack — claims,
propagation, item activation.

```bash
Xephyr :7 -screen 900x650 &
DISPLAY=:7 GDK_BACKEND=x11 PYTHONPATH=src .venv/bin/python tools/selection_input_harness.py
# HARNESS_CARDS=4 (default 12) picks the library size; 4 leaves empty page
# space so the click-on-empty and band-geometry checks run.
```

Covered here and nowhere else: selection by pointer (Ctrl-click, Shift-range,
click-to-clear, launch), selection by keyboard (Shift+arrow ranges and where
they re-root), the rubber band — including that it selects exactly the cards it
was drawn over rather than merely the right *number* of them — one card per ROM
on screen with no card bound to two games, filtering and the dropping of a
filtered-out selection, focus memory across leaving and re-entering the grid,
per-ROM artwork refresh finding the right ROM, and one context menu open at a
time (issue #275).

Those last checks exist because each behaviour *was* implemented against "one
live widget per ROM, forever, in a stable list" — the invariant virtualization
deleted (issue #219). This harness is the net that migration had to keep green.

## `grid_virtualization_probe.py` — does the grid still recycle cards?

Puts the production grid on a nested X server twice, once on a small library
and once on one ten times bigger, and asserts the two build the *same* number
of cards. The grid used to be a `Gtk.FlowBox` with one live widget per ROM:
opening "All consoles" on a few thousand games built tens of thousands of
widgets before the first frame and held a decoded texture per card for as long
as the page existed (issue #219).

```bash
Xephyr :9 -screen 900x650 &
DISPLAY=:9 GDK_BACKEND=x11 PYTHONPATH=src .venv/bin/python tools/grid_virtualization_probe.py
```

Exit code `0` and `RT-034 OK` on stdout when the grid virtualizes.
