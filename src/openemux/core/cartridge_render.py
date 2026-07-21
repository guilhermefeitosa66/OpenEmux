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
import threading
import xml.etree.ElementTree as ET
from pathlib import Path

import cairo
import gi

gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gio, GLib, GdkPixbuf

try:
    gi.require_version("Rsvg", "2.0")
    from gi.repository import Rsvg
except (ImportError, ValueError):  # typelib missing: SVG frames are unavailable
    Rsvg = None

logger = logging.getLogger(__name__)

# Bump whenever the frame art or the compositing logic changes so every cached
# composite is regenerated.
FRAME_CACHE_VERSION = 1

# The name the frame author gives the label object, as an id or inkscape:label.
CLIP_MARKER = "label-clip"

# Blank-sticker tone used where no cover art is available.
BLANK_LABEL_RGB = (0.87, 0.86, 0.83)

SVG_NS = "http://www.w3.org/2000/svg"
INKSCAPE_NS = "http://www.inkscape.org/namespaces/inkscape"

DEFAULT_CACHE_DIR = Path.home() / ".openemux" / "cache" / "cartridges"


class CartridgeFrameError(RuntimeError):
    """The frame SVG cannot be used as a cartridge frame."""


def rsvg_available() -> bool:
    """True when the librsvg introspection typelib is installed."""
    return Rsvg is not None


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


def _pixbuf_to_surface(pixbuf) -> cairo.ImageSurface:
    """GdkPixbuf -> cairo surface without pulling in Gdk (GTK) helpers."""
    ok, buffer = pixbuf.save_to_bufferv("png", [], [])
    if not ok:
        raise CartridgeFrameError("could not convert cover to a cairo surface")
    return cairo.ImageSurface.create_from_png(_BytesReader(buffer))


class _BytesReader:
    """Minimal read()-only file object for cairo's PNG loader."""

    def __init__(self, data):
        self._data = bytes(data)
        self._pos = 0

    def read(self, size=-1):
        if size is None or size < 0:
            size = len(self._data) - self._pos
        chunk = self._data[self._pos:self._pos + size]
        self._pos += len(chunk)
        return chunk


class CartridgeFrame:
    """One parsed frame SVG, reusable across every ROM of a console."""

    def __init__(self, path):
        if Rsvg is None:
            raise CartridgeFrameError("librsvg typelib (gir1.2-rsvg-2.0) is not installed")
        self.path = Path(path)
        data = self.path.read_bytes()

        _register_namespaces()
        root = ET.fromstring(data)
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
        # panic, so every use of them is serialised here.
        self._lock = threading.Lock()
        # Label geometry and stencil per output size, computed once instead of
        # once per ROM (they only depend on the frame and the size).
        self._label_cache = {}

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

    def _label(self, out_w, out_h):
        """Label box plus the stencil whose alpha *is* the clip shape."""
        cached = self._label_cache.get((out_w, out_h))
        if cached is not None:
            return cached
        mask = cairo.ImageSurface(cairo.FORMAT_ARGB32, out_w, out_h)
        cr = cairo.Context(mask)
        self._full.render_layer(cr, f"#{self.clip_id}", self._viewport(out_w, out_h))
        mask.flush()
        entry = (self._label_bbox(out_w, out_h), mask)
        # A grid shows one size at a time; keeping only the latest avoids
        # holding a full-size surface per size ever rendered.
        self._label_cache = {(out_w, out_h): entry}
        return entry

    def render(self, cover_path=None, width=200, scale=1) -> cairo.ImageSurface:
        """Compose `cover_path` into the frame and return the finished surface.

        With no cover the frame renders as a blank cartridge, which keeps a
        shelf of un-scraped ROMs looking like cartridges instead of icons.
        """
        out_w, out_h = self.size_for_width(int(round(width * scale)))
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, out_w, out_h)
        cr = cairo.Context(surface)

        with self._lock:
            (bx, by, bw, bh), mask = self._label(out_w, out_h)

            # The label shape is filled with a blank-sticker tone first: it is
            # what a cover-less cartridge shows, and it backs any anti-aliased
            # edge so the window never lets the page background through.
            cr.set_source_rgb(*BLANK_LABEL_RGB)
            cr.mask_surface(mask, 0, 0)

            if cover_path:
                cover = self._scaled_cover(cover_path, bw, bh)
                if cover is not None:
                    cover_surface, dx, dy = cover
                    cr.set_source_surface(cover_surface, bx + dx, by + dy)
                    cr.get_source().set_filter(cairo.FILTER_GOOD)
                    cr.mask_surface(mask, 0, 0)

            self._frame.render_document(cr, self._viewport(out_w, out_h))
        surface.flush()
        return surface

    @staticmethod
    def _scaled_cover(cover_path, box_w, box_h):
        """Scale the cover to *cover* the label box (crop-to-fill, centred)."""
        try:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file(str(cover_path))
        except GLib.Error:
            logger.warning("cartridge: unreadable cover %s", cover_path)
            return None
        src_w, src_h = pixbuf.get_width(), pixbuf.get_height()
        if src_w <= 0 or src_h <= 0:
            return None
        factor = max(box_w / src_w, box_h / src_h)
        dst_w = max(1, int(round(src_w * factor)))
        dst_h = max(1, int(round(src_h * factor)))
        if (dst_w, dst_h) != (src_w, src_h):
            pixbuf = pixbuf.scale_simple(dst_w, dst_h, GdkPixbuf.InterpType.BILINEAR)
        return _pixbuf_to_surface(pixbuf), (box_w - dst_w) / 2, (box_h - dst_h) / 2


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
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:12]


def _drop_stale(directory: Path, stem: str, keep: Path):
    prefix = f"{stem}."
    for entry in directory.iterdir():
        if entry == keep or not entry.name.startswith(prefix) or entry.suffix != ".png":
            continue
        try:
            entry.unlink()
        except OSError:
            continue


def drop_cached(console, rom_name, cache_dir=None):
    """Delete a ROM's composites, for when the ROM is renamed or removed.

    Not needed for correctness -- the cache key covers content changes -- but a
    deleted or renamed ROM would otherwise leave its composite behind forever.
    """
    directory = Path(cache_dir or DEFAULT_CACHE_DIR) / console
    if not directory.is_dir():
        return 0
    dropped = 0
    prefix = f"{rom_name}."
    for entry in directory.iterdir():
        if entry.suffix != ".png" or not entry.name.startswith(prefix):
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

    try:
        surface = frame.render(cover_path, width=width, scale=scale)
        directory.mkdir(parents=True, exist_ok=True)
        # Cards render in parallel and two of them can target the same file
        # (every cover-less ROM shares the blank composite), so the temporary
        # name is per-thread: a shared one gets renamed away under the others.
        tmp = target.with_name(f"{target.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        surface.write_to_png(str(tmp))
        tmp.replace(target)
    except (CartridgeFrameError, GLib.Error, OSError, cairo.Error) as exc:
        logger.warning("cartridge: render failed for %s/%s: %s", console, rom_name, exc)
        return None

    _drop_stale(directory, stem, target)
    return target
