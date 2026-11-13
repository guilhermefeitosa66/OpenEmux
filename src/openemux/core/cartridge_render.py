"""
Pre-rendered cartridge art: the cover baked into a console cartridge frame.

A frame is an SVG holding the cartridge art plus one object that marks where
the label goes, identified by ``id="label-clip"`` or (Inkscape's Object
Properties label) ``inkscape:label="label-clip"``. The compositor reads that
object's bounding box *and* its exact shape from the art itself, so adding a
console means dropping in one SVG - no coordinates are ever typed in code.

Authoring convention: the marker object must sit *below* the cartridge art in
z-order, and the art must be transparent over it. The compositor draws the
cover into the marker's shape and then paints the frame (with the marker
removed) on top, so the art's own window is what reveals the cover.

Widget-free on purpose: Rsvg/GdkPixbuf/cairo are drawing libraries, not GTK,
so this stays in core/ and is testable without a display.
"""

import hashlib
import logging
import os
import re
import sys
import threading
import xml.etree.ElementTree as ET
from pathlib import Path

import cairo
import gi

gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gio, GLib, GdkPixbuf

from openemux.core.paths import store_path

try:
    gi.require_version("Rsvg", "2.0")
    from gi.repository import Rsvg
except (ImportError, ValueError):  # typelib missing: SVG frames are unavailable
    Rsvg = None

logger = logging.getLogger(__name__)

# Bump whenever the frame art or the compositing logic changes so every cached
# composite is regenerated.
FRAME_CACHE_VERSION = 4

#: The shadow baked under the cartridge (issue 903): offset down, blur radius
#: and opacity in logical pixels, like the CSS drop-shadow it replaces
#: (``0 3px 6px rgba(0,0,0,0.45)``), and the transparent margin the composite
#: grows by on every side to hold it. All scaled with the composite.
SHADOW_OFFSET_Y = 3
SHADOW_BLUR = 6
SHADOW_ALPHA = 0.45
SHADOW_PAD = 8

# The name the frame author gives the label object, as an id or inkscape:label.
CLIP_MARKER = "label-clip"

# The authored shell: the bare <CONSOLE>.svg, not a -<color> variant.
DEFAULT_FRAME_COLOR = "default"

# Blank-sticker tone used where no cover art is available.
BLANK_LABEL_RGB = (0.87, 0.86, 0.83)

SVG_NS = "http://www.w3.org/2000/svg"
INKSCAPE_NS = "http://www.inkscape.org/namespaces/inkscape"

DEFAULT_CACHE_DIR = store_path("cartridge_cache")

# The shipped frame assets. They live under ui/ because that is where the app's
# image assets are kept, but this module is their only reader, so the lookup
# belongs here: a console is frame-capable iff its SVG exists, and dropping in
# one file is the whole opt-in. Anything that needs to know (the grid, and the
# post-import label sync) asks here instead of keeping a second list.
CARTRIDGE_ASSETS_DIR = Path(__file__).resolve().parent.parent / "ui" / "assets" / "images" / "cartridges"


class CartridgeFrameError(RuntimeError):
    """The frame SVG cannot be used as a cartridge frame."""


def rsvg_available() -> bool:
    """True when the librsvg introspection typelib is installed."""
    return Rsvg is not None


def frame_asset_for(console, assets_dir=None, color=None) -> Path | None:
    """The shipped frame SVG for a console, or None when none was authored.

    ``color`` picks a shell variant (``<CONSOLE>-<color>.svg``); the authored
    default is the bare ``<CONSOLE>.svg``. A color with no file falls back to
    the default shell, so a stale stored color never breaks rendering.

    Existence of the file is the whole test, deliberately: librsvg availability
    is a separate, recoverable concern (a user can install the typelib later),
    so callers that only need to know whether a console *has* a frame -- such as
    deciding whether a cartridge label is worth scraping -- are not gated on it.
    Rendering paths use `cartridge_frame(...)`, which does check.
    """
    directory = Path(assets_dir) if assets_dir is not None else CARTRIDGE_ASSETS_DIR
    if color and color != DEFAULT_FRAME_COLOR:
        variant = directory / f"{console}-{color}.svg"
        if variant.is_file():
            return variant
    candidate = directory / f"{console}.svg"
    return candidate if candidate.is_file() else None


def has_frame(console, assets_dir=None) -> bool:
    """True when a cartridge frame was authored for this console."""
    return frame_asset_for(console, assets_dir) is not None


def consoles_with_frames(assets_dir=None) -> list[str]:
    """Console ids that have a frame, sorted, derived from the shipped assets.

    Only base frames count: a ``-<color>`` variant is a shell for a console
    already in the list, not a console of its own.
    """
    directory = Path(assets_dir) if assets_dir is not None else CARTRIDGE_ASSETS_DIR
    if not directory.is_dir():
        return []
    return sorted(
        path.stem
        for path in directory.glob("*.svg")
        if path.is_file() and "-" not in path.stem
    )


def frame_colors_for(console, assets_dir=None) -> list[str]:
    """Shell color ids available for a console, from the files on disk.

    Always starts with the default shell when the console has a frame at all;
    empty when it has none. Order is left to the caller (the menu sorts by the
    palette table), so this is plain sorted ids.
    """
    directory = Path(assets_dir) if assets_dir is not None else CARTRIDGE_ASSETS_DIR
    if not (directory / f"{console}.svg").is_file():
        return []
    prefix = f"{console}-"
    variants = sorted(
        path.stem[len(prefix):]
        for path in directory.glob(f"{prefix}*.svg")
        if path.is_file() and path.stem[len(prefix):]
    )
    return [DEFAULT_FRAME_COLOR] + variants


def cartridge_frame(console, assets_dir=None, color=None) -> Path | None:
    """The frame SVG for a console when it exists *and* can actually be used."""
    candidate = frame_asset_for(console, assets_dir, color=color)
    if candidate is None or not rsvg_available():
        return None
    return candidate if load_frame(candidate) else None


def _register_namespaces():
    ET.register_namespace("", SVG_NS)
    ET.register_namespace("svg", SVG_NS)
    ET.register_namespace("inkscape", INKSCAPE_NS)
    ET.register_namespace("sodipodi", "http://sodipodi.sourceforge.net/DTD/sodipodi-0.dtd")
    ET.register_namespace("xlink", "http://www.w3.org/1999/xlink")


def _find_clip_element(root):
    """Locate the label marker by id first, then by Inkscape label."""
    inkscape_label = f"{{{INKSCAPE_NS}}}label"
    by_label = None
    for parent in root.iter():
        for child in parent:
            if child.get("id") == CLIP_MARKER:
                return parent, child
            if by_label is None and child.get(inkscape_label) == CLIP_MARKER:
                by_label = (parent, child)
    if by_label:
        return by_label
    return None, None


def _handle_from_bytes(data: bytes):
    stream = Gio.MemoryInputStream.new_from_bytes(GLib.Bytes.new(data))
    return Rsvg.Handle.new_from_stream_sync(stream, None, Rsvg.HandleFlags.FLAGS_NONE, None)


def _rgb_pixel(rgb):
    """A GdkPixbuf fill value (0xRRGGBBAA) for a 0..1 RGB triple."""
    red, green, blue = (max(0, min(255, int(round(c * 255)))) for c in rgb)
    return (red << 24) | (green << 16) | (blue << 8) | 0xFF


def _pixbuf_to_surface(pixbuf, byteorder=None) -> cairo.ImageSurface:
    """GdkPixbuf -> cairo surface, straight from the pixels.

    Without Gdk (GTK) helpers, and -- since issue 902 -- without the PNG
    round trip that used to stand in for them: encoding the scaled label to
    PNG in memory and decoding it again was two of the three PNG passes on
    every first render of a cartridge. The pixel rows are repacked from the
    pixbuf's RGB into cairo's native-endian 32-bit RGB24 with slice
    assignments, which run at C speed. A cover with an alpha channel is
    flattened onto the blank-sticker tone first, which is what backs the
    label window anyway.
    """
    width, height = pixbuf.get_width(), pixbuf.get_height()
    if pixbuf.get_has_alpha():
        flat = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, width, height)
        flat.fill(_rgb_pixel(BLANK_LABEL_RGB))
        pixbuf.composite(
            flat, 0, 0, width, height, 0, 0, 1.0, 1.0, GdkPixbuf.InterpType.NEAREST, 255
        )
        pixbuf = flat
    rowstride = pixbuf.get_rowstride()
    pixels = pixbuf.get_pixels()
    row_bytes = width * 3
    if rowstride != row_bytes:
        pixels = b"".join(
            pixels[row * rowstride:row * rowstride + row_bytes] for row in range(height)
        )
    out = bytearray(width * height * 4)
    if (byteorder or sys.byteorder) == "little":
        out[0::4] = pixels[2::3]
        out[1::4] = pixels[1::3]
        out[2::4] = pixels[0::3]
    else:
        out[1::4] = pixels[0::3]
        out[2::4] = pixels[1::3]
        out[3::4] = pixels[2::3]
    return cairo.ImageSurface.create_for_data(out, cairo.FORMAT_RGB24, width, height, width * 4)


class CartridgeFrame:
    """One parsed frame SVG, reusable across every ROM of a console."""

    def __init__(self, path):
        if Rsvg is None:
            raise CartridgeFrameError("librsvg typelib (gir1.2-rsvg-2.0) is not installed")
        self.path = Path(path)
        data = self.path.read_bytes()

        _register_namespaces()
        # frames are SVG assets shipped with the app, not user input
        root = ET.fromstring(data)  # nosec B314
        parent, clip = _find_clip_element(root)
        if clip is None:
            raise CartridgeFrameError(
                f"{self.path.name} has no object named '{CLIP_MARKER}'"
            )
        self.clip_id = clip.get("id")
        if not self.clip_id:
            raise CartridgeFrameError(f"{self.path.name}: '{CLIP_MARKER}' object has no id")

        # Two handles off the same source: the original (used only to measure
        # and stencil the label object) and a copy with the marker removed,
        # which is the cartridge art that gets painted over the cover.
        self._full = _handle_from_bytes(data)
        parent.remove(clip)
        self._frame = _handle_from_bytes(ET.tostring(root, encoding="utf-8"))

        # librsvg handles are not thread-safe: rendering the same handle from
        # two grid worker threads aborts the process with a Rust BorrowMutError
        # panic, so every use of them is serialised here. Since issue 902 the
        # handles are only used to rasterize the frame and the label stencil
        # once per size; the per-ROM composition reads those surfaces.
        self._lock = threading.Lock()
        # Label geometry, stencil and the rasterized frame per output size,
        # computed once instead of once per ROM (they only depend on the
        # frame and the size); the baked shadow likewise.
        self._label_cache = {}
        self._shadow_cache = {}

        ok, width, height = self._full.get_intrinsic_size_in_pixels()
        if not ok or width <= 0 or height <= 0:
            raise CartridgeFrameError(f"{self.path.name} has no intrinsic size")
        self.width = width
        self.height = height

    @property
    def aspect(self) -> float:
        """width / height of the cartridge silhouette."""
        return self.width / self.height

    def size_for_width(self, width: int) -> tuple[int, int]:
        return int(width), max(1, int(round(width * self.height / self.width)))

    def composite_size(self, width: int, scale=1) -> tuple[int, int]:
        """The pixel size :meth:`render` produces: the cartridge plus the shadow margin."""
        out_w, out_h = self.size_for_width(int(round(width * scale)))
        pad = shadow_pad(scale)
        return out_w + 2 * pad, out_h + 2 * pad

    def _label_bbox(self, out_w, out_h):
        """Label box in output pixels.

        Measured against the *intrinsic* viewport and scaled here: librsvg
        reports this geometry in user units regardless of the viewport passed
        in, so doing the scaling ourselves keeps it correct at any size.
        """
        ok, ink, _logical = self._full.get_geometry_for_layer(
            f"#{self.clip_id}", self._viewport(self.width, self.height)
        )
        if not ok:
            raise CartridgeFrameError(f"{self.path.name}: cannot measure '#{self.clip_id}'")
        sx = out_w / self.width
        sy = out_h / self.height
        return ink.x * sx, ink.y * sy, ink.width * sx, ink.height * sy

    @staticmethod
    def _viewport(width, height):
        viewport = Rsvg.Rectangle()
        viewport.x = 0
        viewport.y = 0
        viewport.width = width
        viewport.height = height
        return viewport

    def _rasterized(self, out_w, out_h):
        """Label box, label stencil and the frame itself, as surfaces.

        Rendered through librsvg once per size and kept; the per-ROM render
        only composites them. Only the latest size is kept: a grid shows one
        size at a time, and holding a full-size surface per size ever
        rendered would be a leak on every zoom step.
        """
        cached = self._label_cache.get((out_w, out_h))
        if cached is not None:
            return cached
        with self._lock:
            cached = self._label_cache.get((out_w, out_h))
            if cached is not None:
                return cached
            mask = cairo.ImageSurface(cairo.FORMAT_ARGB32, out_w, out_h)
            cr = cairo.Context(mask)
            self._full.render_layer(cr, f"#{self.clip_id}", self._viewport(out_w, out_h))
            mask.flush()
            frame = cairo.ImageSurface(cairo.FORMAT_ARGB32, out_w, out_h)
            cr = cairo.Context(frame)
            self._frame.render_document(cr, self._viewport(out_w, out_h))
            frame.flush()
            entry = (self._label_bbox(out_w, out_h), mask, frame)
            self._label_cache = {(out_w, out_h): entry}
            return entry

    def _shadow(self, out_w, out_h, scale):
        """The cartridge's shadow, as a surface the composite's size.

        The silhouette (the frame's alpha plus the label window) is drawn in
        black, blurred by drawing it a quarter size and back up with bilinear
        filtering -- twice, which is close enough to a gaussian for a six
        pixel radius -- and faded to SHADOW_ALPHA. Rendered once per size
        with the frame and reused for every ROM (issue 903): the CSS
        drop-shadow it replaces was a software blur of every card on every
        scroll frame under the cairo renderer.
        """
        cached = self._shadow_cache.get((out_w, out_h))
        if cached is not None:
            return cached
        (_bbox, mask, frame) = self._rasterized(out_w, out_h)
        pad = shadow_pad(scale)
        width, height = out_w + 2 * pad, out_h + 2 * pad
        silhouette = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
        cr = cairo.Context(silhouette)
        cr.set_source_rgb(0, 0, 0)
        cr.mask_surface(mask, pad, pad)
        cr.mask_surface(frame, pad, pad)
        silhouette.flush()
        # Down twice, up twice: each pass is a cheap box blur in cairo.
        blurred = silhouette
        for factor in (0.5, 0.5):
            blurred = _scaled_copy(blurred, factor, cairo.FILTER_GOOD)
        for _ in range(2):
            blurred = _scaled_copy(blurred, 2.0, cairo.FILTER_BILINEAR)
        shadow = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
        cr = cairo.Context(shadow)
        cr.set_source_surface(blurred, 0, 0)
        cr.get_source().set_filter(cairo.FILTER_BILINEAR)
        cr.paint_with_alpha(SHADOW_ALPHA)
        shadow.flush()
        self._shadow_cache = {(out_w, out_h): shadow}
        return shadow

    def render(self, cover_path=None, width=200, scale=1) -> cairo.ImageSurface:
        """Compose `cover_path` into the frame and return the finished surface.

        With no cover the frame renders as a blank cartridge, which keeps a
        shelf of un-scraped ROMs looking like cartridges instead of icons.

        The cover's decode and rescale -- the expensive part -- run outside
        the frame lock, so the pool composes several cartridges at once; only
        the few cairo operations that read the shared stencil and frame
        surfaces are serialised (issue 902).
        """
        out_w, out_h = self.size_for_width(int(round(width * scale)))
        (bx, by, bw, bh), mask, frame = self._rasterized(out_w, out_h)
        cover = self._scaled_cover(cover_path, bw, bh) if cover_path else None
        with self._lock:
            shadow = self._shadow(out_w, out_h, scale)
        pad = shadow_pad(scale)

        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, out_w + 2 * pad, out_h + 2 * pad)
        cr = cairo.Context(surface)
        with self._lock:
            # The shadow first, under everything, offset downwards.
            cr.set_source_surface(shadow, 0, SHADOW_OFFSET_Y * scale)
            cr.paint()
            cr.translate(pad, pad)
            # The label shape is filled with a blank-sticker tone first: it is
            # what a cover-less cartridge shows, and it backs any anti-aliased
            # edge so the window never lets the page background through.
            cr.set_source_rgb(*BLANK_LABEL_RGB)
            cr.mask_surface(mask, 0, 0)
            if cover is not None:
                cover_surface, dx, dy = cover
                cr.set_source_surface(cover_surface, bx + dx, by + dy)
                cr.get_source().set_filter(cairo.FILTER_GOOD)
                cr.mask_surface(mask, 0, 0)
            cr.set_source_surface(frame, 0, 0)
            cr.paint()
        surface.flush()
        return surface

    @staticmethod
    def _scaled_cover(cover_path, box_w, box_h):
        """Scale the cover to *cover* the label box (crop-to-fill, centred).

        Decoded straight at the size it is drawn, rather than in full and
        then rescaled: a 512x720 cover going into a 100-pixel sticker is
        read at a tenth of the pixels (issue 902).
        """
        try:
            full_w, full_h = _image_size(cover_path)
        except (GLib.Error, OSError):
            logger.warning("cartridge: unreadable cover %s", cover_path)
            return None
        if full_w <= 0 or full_h <= 0:
            return None
        factor = max(box_w / full_w, box_h / full_h)
        dst_w = max(1, int(round(full_w * factor)))
        dst_h = max(1, int(round(full_h * factor)))
        try:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(
                str(cover_path), dst_w, dst_h, False
            )
        except GLib.Error:
            logger.warning("cartridge: unreadable cover %s", cover_path)
            return None
        return _pixbuf_to_surface(pixbuf), (box_w - dst_w) / 2, (box_h - dst_h) / 2


def shadow_pad(scale=1):
    """The transparent margin around a composite, in pixels at ``scale``."""
    return int(round(SHADOW_PAD * max(1, scale)))


def _scaled_copy(surface, factor, filter_mode):
    """``surface`` drawn at ``factor`` of its size, with cairo's ``filter_mode``."""
    width = max(1, int(round(surface.get_width() * factor)))
    height = max(1, int(round(surface.get_height() * factor)))
    copy = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    cr = cairo.Context(copy)
    cr.scale(width / surface.get_width(), height / surface.get_height())
    cr.set_source_surface(surface, 0, 0)
    cr.get_source().set_filter(filter_mode)
    cr.paint()
    copy.flush()
    return copy


def _image_size(path):
    """The pixel size of an image file, from its header alone."""
    fmt, width, height = GdkPixbuf.Pixbuf.get_file_info(str(path))
    if fmt is None:
        raise GLib.Error("not an image")
    return width, height


# ---------------------------------------------------------------------------
# Frame lookup + on-disk cache
# ---------------------------------------------------------------------------

_FRAMES = {}
_FRAMES_LOCK = threading.Lock()


def load_frame(frame_path) -> CartridgeFrame | None:
    """Parse a frame once and keep it; returns None when it cannot be used.

    Grid cards are filled from several worker threads, so the parse is done
    under a lock: one frame, one set of Rsvg handles, shared by every card.
    """
    path = Path(frame_path)
    try:
        key = (str(path), path.stat().st_mtime_ns)
    except OSError:
        return None
    with _FRAMES_LOCK:
        cached = _FRAMES.get(str(path))
        if cached is not None and cached[0] == key:
            return cached[1]
        try:
            frame = CartridgeFrame(path)
        except (CartridgeFrameError, GLib.Error, ET.ParseError) as exc:
            logger.warning("cartridge: unusable frame %s: %s", path, exc)
            _FRAMES[str(path)] = (key, None)
            return None
        _FRAMES[str(path)] = (key, frame)
        return frame


def _cache_key(cover_path, frame_path, width, scale) -> str:
    parts = [str(FRAME_CACHE_VERSION), str(width), str(scale)]
    for path in (frame_path, cover_path):
        if path is None:
            parts.append("-")
            continue
        stat = Path(path).stat()
        parts.append(f"{path}:{stat.st_mtime_ns}:{stat.st_size}")
    # Cache-file naming only: a fast digest of paths/mtimes, never a security check.
    digest = hashlib.sha1("|".join(parts).encode("utf-8"), usedforsecurity=False)
    return digest.hexdigest()[:12]


#: What a composite's name carries after the ROM name: the 12-hex cache key
#: and the extension. Matching the ROM name as a bare prefix was enough for a
#: ROM called "Dr" to match -- and delete -- "Dr. Mario.<key>.png"
#: (issue #234). Self-healing, since the composite is re-rendered, but it made
#: one ROM's rename quietly re-render another's art.
_CACHE_SUFFIX_RE = re.compile(r"^\.[0-9a-f]{12}\.png$")


def _is_composite_of(entry: Path, stem: str):
    """Whether ``entry`` is a cached composite for exactly ``stem``."""
    name = entry.name
    if not name.startswith(stem):
        return False
    return bool(_CACHE_SUFFIX_RE.match(name[len(stem):]))


def _move_into_place(tmp: Path, target: Path):
    # On Windows, replacing a file that another thread is replacing at the same
    # moment fails with "Access is denied" (WinError 5) instead of one of them
    # winning, as rename(2) does. The two composites are the same bytes, so a
    # target that exists after the failure is the one to use.
    try:
        tmp.replace(target)
    except OSError:
        if not target.exists():
            raise
        try:
            tmp.unlink()
        except OSError:
            pass


def drop_cached(console, rom_name, cache_dir=None):
    """Delete a ROM's composites, for when the ROM is renamed or removed.

    Not needed for correctness -- the cache key covers content changes -- but a
    deleted or renamed ROM would otherwise leave its composite behind forever.
    """
    directory = Path(cache_dir or DEFAULT_CACHE_DIR) / console
    if not directory.is_dir():
        return 0
    dropped = 0
    for entry in directory.iterdir():
        if not _is_composite_of(entry, rom_name):
            continue
        try:
            entry.unlink()
            dropped += 1
        except OSError:
            continue
    return dropped


def render_cartridge(
    cover_path,
    frame_path,
    console,
    rom_name,
    width=200,
    scale=1,
    cache_dir=DEFAULT_CACHE_DIR,
) -> Path | None:
    """Return the path of the composite for a ROM, rendering it if needed.

    The cache is keyed on the cover and frame mtime/size plus the output size
    and `FRAME_CACHE_VERSION`, so a replaced cover or new art invalidates
    itself with no explicit hook. Returns None when the frame is unusable.
    """
    frame = load_frame(frame_path)
    if frame is None:
        return None

    try:
        key = _cache_key(cover_path, frame_path, width, scale)
    except OSError:
        return None

    stem = rom_name if cover_path else "_blank"
    directory = Path(cache_dir) / console
    target = directory / f"{stem}.{key}.png"
    if target.exists():
        return target
    # One PNG write per composite, the one that lands in the disk cache; the
    # in-memory encode the label used to go through is gone (issue 902), and
    # so is the sweep of the directory after every write that threw the
    # other zoom levels' composites away -- the key carries the width and
    # the scale, so each size keeps its own file and a zoom round-trip
    # renders nothing twice. housekeeping prunes the cache by age and size.

    try:
        surface = frame.render(cover_path, width=width, scale=scale)
        directory.mkdir(parents=True, exist_ok=True)
        # Cards render in parallel and two of them can target the same file
        # (every cover-less ROM shares the blank composite), so the temporary
        # name is per-thread: a shared one gets renamed away under the others.
        tmp = target.with_name(f"{target.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        surface.write_to_png(str(tmp))
        _move_into_place(tmp, target)
    except Exception as exc:
        # Deliberately broad. This runs on the cover-fetch worker thread, and
        # the caller treats None as "no cartridge, fall back to the plain
        # cover". An escaping exception kills that callback instead, so the
        # card is left showing its placeholder -- no cartridge *and* no cover.
        # That is how a missing gi-cairo bridge (KeyError: could not find
        # foreign type Context) emptied the whole grid rather than degrading it.
        logger.warning(
            "cartridge: render failed for %s/%s: %s: %s",
            console, rom_name, type(exc).__name__, exc,
        )
        return None
    return target
