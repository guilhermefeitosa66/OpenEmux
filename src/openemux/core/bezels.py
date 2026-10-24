"""Decorative bezels beside 4:3 games on a wide window (issue #507).

A 4:3 game on a 16:9 window leaves a black bar on each side. A bezel fills
them: a 16:9 picture with a transparent 4:3 hole the game shows through.

RetroArch shows a single input overlay, and the in-game bar already owns it
(``overlay_bar``), so the bezel is not an overlay of its own: it is one more
image on every page of the bar's, drawn first so the bar's buttons stay on
top (``overlay_bar.write_bezel_overlay``). This module is the part that does
not touch the overlay: which consoles get one, what the user picked, the
built-in art, and checking and storing a custom image.

The choice is per console and is one of :data:`BEZEL_MODES`: nothing, the
built-in "Simple" frame (``scripts/build_bezels.py``), or an image the user
picked, copied into OpenEmux's own folder so a Flatpak RetroArch can read it
and moving the original does not break it.

Every image is kept within :data:`MAX_DECODED`. RetroArch decodes an overlay
image once per descriptor that names it, and keeps every copy (no release up
to 1.22 shares them), so the bezel is held once for each of the bar's 64
pages: a 1920x1080 picture would cost about half a gigabyte. A custom image
over the cap is scaled down as it is imported.
"""

import logging
import os
import struct
from pathlib import Path

from openemux.core.atomic_write import atomic_write_bytes, atomic_write_stream
from openemux.core.systems import resolve_system_id

logger = logging.getLogger(__name__)

NONE, SIMPLE, CUSTOM = "none", "simple", "custom"
BEZEL_MODES = (NONE, SIMPLE, CUSTOM)

#: The consoles whose cores draw a 4:3 picture, the only shape the bezel's
#: hole fits. Handhelds (GB, GBC, GBA, GG, NGP, NDS, PSP, VB, WS, LYNX) fill a
#: screen of their own shape, and the Vectrex is portrait: a 4:3 hole would
#: cover part of the game or leave a gap, so they are not offered one.
BEZEL_CONSOLES = frozenset({
    "A2600", "A5200", "A7800", "CV", "FDS", "FC", "INTV", "N64", "GC", "O2",
    "SG1000", "S32X", "MCD", "MD", "SMS", "SATURN", "PS", "SFC", "PCE", "PCECD",
})

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
BUILTIN = {SIMPLE: DATA_DIR / "bezels" / "simple.png"}

#: Limits on a picked image: a picture smaller than this is not worth
#: stretching over a screen, and a bigger file only slows the import.
#: ``MAX_SIZE`` bounds what the import decodes: a few compressed megabytes
#: can describe a picture of gigabytes once unpacked.
MIN_SIZE = (320, 180)
MAX_SIZE = (3840, 2160)
MAX_BYTES = 16 * 1024 * 1024

#: The biggest picture handed to RetroArch, which holds it once per page of
#: the bar: 960x540 is about 2 MB decoded, 130 MB over the 64 pages. Half of
#: a 1080p screen, so a bezel pack's usual 1920x1080 art halves cleanly.
MAX_DECODED = (960, 540)

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

#: Missing custom images already reported, so a console launched over and
#: over logs its warning once.
_warned_missing = set()


def normalize_mode(value):
    """A stored mode, or :data:`NONE` for anything this does not know."""
    return value if value in BEZEL_MODES else NONE


def validate_png(path):
    """``None`` when ``path`` is a usable bezel, otherwise an error key.

    ``"unreadable"`` (also a file or a picture over the caps), ``"not_png"``
    or ``"too_small"``. Only the signature and the IHDR header are read,
    with ``struct``: the picture is decoded later, by :func:`import_custom`
    when it has to be scaled, and by RetroArch at launch.
    """
    try:
        if os.path.getsize(path) > MAX_BYTES:
            return "unreadable"
        with open(path, "rb") as handle:
            head = handle.read(24)
    except OSError:
        return "unreadable"
    size = _png_size(head)
    if size is None:
        return "not_png"
    width, height = size
    if width < MIN_SIZE[0] or height < MIN_SIZE[1]:
        return "too_small"
    if width > MAX_SIZE[0] or height > MAX_SIZE[1]:
        return "unreadable"
    return None


def _png_size(head):
    """``(width, height)`` from a PNG's first 24 bytes, or ``None``."""
    if len(head) < 24 or head[:8] != _PNG_SIGNATURE or head[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", head[16:24])


def _fits(path):
    """Whether the PNG at ``path`` is within :data:`MAX_DECODED`."""
    with open(path, "rb") as handle:
        size = _png_size(handle.read(24))
    return size is not None and size[0] <= MAX_DECODED[0] and size[1] <= MAX_DECODED[1]


def custom_path(console, target_dir):
    """Where a console's custom image is kept."""
    return Path(target_dir) / f"{resolve_system_id(console)}.png"


def import_custom(console, source_path, target_dir):
    """Copy ``source_path`` in as the console's custom bezel; return its path.

    A picture over :data:`MAX_DECODED` is scaled down to fit, keeping its
    shape; one within it is copied as it is. Written atomically, so a copy
    that fails halfway leaves the previous image, not half of a new one.
    Raises ``OSError`` when it cannot be done, a picture GdkPixbuf cannot
    decode included.
    """
    # Imported here, not at the top: ``config`` and ``overlay_bar`` import
    # this module, and nothing else they do needs the GTK stack.
    import gi

    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GLib, GdkPixbuf

    target = custom_path(console, target_dir)
    fits = _fits(source_path)
    try:
        # Decoded in full even when it is copied as it is: validate_png only
        # read the header, and a truncated or corrupt file past it would be
        # stored, selected, and then drawn by RetroArch as nothing. Not
        # new_from_file_at_size: GdkPixbuf 2.42 (Ubuntu 24.04) returns a
        # scaled picture of a truncated file with no error, the missing rows
        # filled in opaque grey over the hole.
        pixbuf = GdkPixbuf.Pixbuf.new_from_file(str(source_path))
        if not fits:
            width, height = pixbuf.get_width(), pixbuf.get_height()
            scale = min(MAX_DECODED[0] / width, MAX_DECODED[1] / height)
            pixbuf = pixbuf.scale_simple(max(1, round(width * scale)),
                                         max(1, round(height * scale)),
                                         GdkPixbuf.InterpType.BILINEAR)
            _ok, data = pixbuf.save_to_bufferv("png", [], [])
    except GLib.Error as exc:
        raise OSError(f"cannot decode {source_path}: {exc.message}") from exc
    if fits:
        with open(source_path, "rb") as src:
            atomic_write_stream(target, src)
    else:
        atomic_write_bytes(target, data)
    return target


def resolve_image(console, settings):
    """The image to frame ``console``'s games with, or ``None`` for none.

    ``settings`` is ``ConfigManager.get_bezel_settings()``. A custom image
    that has gone missing is a warning, not a failed launch: the game starts
    without a bezel.
    """
    console = resolve_system_id(console)
    if console not in BEZEL_CONSOLES:
        return None
    mode = normalize_mode(settings.get("console_overrides", {}).get(console, NONE))
    if mode == NONE:
        return None
    if mode == SIMPLE:
        return BUILTIN[SIMPLE]
    image = custom_path(console, settings["custom_dir"])
    try:
        fits = _fits(image)
    except OSError:
        problem = "is missing"
    else:
        if fits:
            _warned_missing.discard(image)
            return image
        # Only the import writes there, and it scales: a file put there by
        # hand would cost RetroArch its size 64 times over.
        problem = "is not a PNG within %dx%d" % MAX_DECODED
    if image not in _warned_missing:
        _warned_missing.add(image)
        logger.warning("bezel: custom image for %s %s (%s); launching without one",
                       console, problem, image)
    return None


def bezel_desc_geometry(margin=0.0):
    """The bezel's ``(cx, cy, half_w, half_h)`` in the bar's 4:3 overlay box.

    The bar is laid out on a 4:3 box auto-scaled to the window's height, the
    same box the game is drawn in, so a 16:9 bezel around it is 4/3 of its
    width: half-width 2/3. While the bar is shown on its opaque strip, the
    margin pass shrinks the game by ``1 - margin`` about the top centre
    (``overlay_bar.MARGIN``), and the bezel shrinks with it so its hole still
    fits the game. ``margin`` 0 is the full-size game.
    """
    s = 1.0 - margin
    return 0.5, 0.5 * s, (2.0 / 3.0) * s, 0.5 * s
