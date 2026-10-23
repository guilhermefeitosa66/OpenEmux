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
"""

import logging
import os
import shutil
import struct
import tempfile
from pathlib import Path

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

#: Limits on a custom image: a picture smaller than this is not worth
#: stretching over a screen, and a bigger file only slows the first frame.
MIN_SIZE = (320, 180)
MAX_BYTES = 16 * 1024 * 1024

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

#: Missing custom images already reported, so a console launched over and
#: over logs its warning once.
_warned_missing = set()


def normalize_mode(value):
    """A stored mode, or :data:`NONE` for anything this does not know."""
    return value if value in BEZEL_MODES else NONE


def validate_png(path):
    """``None`` when ``path`` is a usable bezel, otherwise an error key.

    ``"unreadable"``, ``"not_png"`` or ``"too_small"``. Only the signature
    and the IHDR header are read, with ``struct``: the core does not load
    GTK, and the image itself is RetroArch's to decode.
    """
    try:
        if os.path.getsize(path) > MAX_BYTES:
            return "unreadable"
        with open(path, "rb") as handle:
            head = handle.read(24)
    except OSError:
        return "unreadable"
    if len(head) < 24 or head[:8] != _PNG_SIGNATURE or head[12:16] != b"IHDR":
        return "not_png"
    width, height = struct.unpack(">II", head[16:24])
    if width < MIN_SIZE[0] or height < MIN_SIZE[1]:
        return "too_small"
    return None


def custom_path(console, target_dir):
    """Where a console's custom image is kept."""
    return Path(target_dir) / f"{resolve_system_id(console)}.png"


def import_custom(console, source_path, target_dir):
    """Copy ``source_path`` in as the console's custom bezel; return its path.

    Written beside its final name and moved over it, so a copy that fails
    halfway leaves the previous image, not half of a new one. Raises
    ``OSError`` when it cannot be done.
    """
    target = custom_path(console, target_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as out, open(source_path, "rb") as src:
            shutil.copyfileobj(src, out)
        os.replace(temp, target)
    except OSError:
        try:
            os.unlink(temp)
        except OSError:
            pass
        raise
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
    if image.is_file():
        _warned_missing.discard(image)
        return image
    if image not in _warned_missing:
        _warned_missing.add(image)
        logger.warning("bezel: custom image for %s is missing (%s); launching without one",
                       console, image)
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
