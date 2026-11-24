"""A theme's background images: taken in, and prepared for the screen (issue 1012).

A picture the person picks (or one inside an imported theme file) is never
used where it is. ``import_image`` checks it -- a known picture signature,
a size on disk and in pixels that a background can sensibly have -- decodes
it, scales it down to at most :data:`MAX_SIDE` pixels on its long side and
writes it as a PNG into the theme's own folder. A file that fails any of
that raises :class:`ThemeImageError`, and nothing is written.

What the window paints is not that file but a *processed* copy: flattened
onto the area's own color, blurred, then dimmed into that color, so text over
it stays readable. Rendering it is the slow part, so it happens once per
change, on a worker thread (``render``), into a cache file whose name is a
hash of everything that went into it (``processed_path``). The average color
of the result feeds the editor's contrast check.

Widget-free, like ``cover_cache``: GdkPixbuf only, so it runs off the main
thread and in the host test run.
"""

import hashlib
import logging
import os
from pathlib import Path

import gi

gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf, GLib

from openemux.core.cartridge_colors import hex_to_rgb, parse_hex

logger = logging.getLogger(__name__)

#: The largest picture file taken in (bytes on disk).
MAX_FILE_BYTES = 40 * 1024 * 1024
#: The largest picture taken in, in pixels on either side, checked from the
#: file's header before anything is decoded.
MAX_PIXELS_SIDE = 8192
#: The long side of the stored copy (the shared format's 2048 px): wider
#: only costs memory.
MAX_SIDE = 2048
#: Processed backgrounds kept in the cache; older ones are removed.
CACHE_KEEP = 24

#: File signatures of the formats a theme may carry.
_SIGNATURES = (
    ("png", lambda head: head.startswith(b"\x89PNG\r\n\x1a\n")),
    ("jpeg", lambda head: head.startswith(b"\xff\xd8\xff")),
    ("webp", lambda head: head[:4] == b"RIFF" and head[8:12] == b"WEBP"),
)


class ThemeImageError(ValueError):
    """A picture that cannot become a theme background."""


def sniff(path):
    """``png``, ``jpeg`` or ``webp`` from the file's first bytes, else None."""
    try:
        with open(path, "rb") as handle:
            head = handle.read(16)
    except OSError:
        return None
    for name, test in _SIGNATURES:
        if test(head):
            return name
    return None


def _check(path):
    path = Path(path)
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise ThemeImageError(f"unreadable: {exc}") from exc
    if not path.is_file():
        raise ThemeImageError("not a file")
    if size > MAX_FILE_BYTES:
        raise ThemeImageError(f"too large: {size} bytes")
    if sniff(path) is None:
        raise ThemeImageError("not a PNG, JPEG or WebP picture")
    info = GdkPixbuf.Pixbuf.get_file_info(str(path))
    if info is None or info[0] is None:
        raise ThemeImageError("no loader for this picture")
    _format, width, height = info
    if width <= 0 or height <= 0 or max(width, height) > MAX_PIXELS_SIDE:
        raise ThemeImageError(f"bad size {width}x{height}")
    return width, height


def import_image(source, destination):
    """Check ``source`` and write it to ``destination`` as a PNG.

    Raises :class:`ThemeImageError` (nothing written) when it is not a
    picture a theme can use.
    """
    width, height = _check(source)
    destination = Path(destination)
    temp = destination.with_name(f".{destination.name}.tmp")
    try:
        if max(width, height) > MAX_SIDE:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(source), MAX_SIDE, MAX_SIDE, True)
        else:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file(str(source))
        pixbuf = pixbuf.apply_embedded_orientation() or pixbuf
        pixbuf.savev(str(temp), "png", [], [])
        os.replace(temp, destination)
    except GLib.Error as exc:
        temp.unlink(missing_ok=True)
        raise ThemeImageError(f"cannot decode: {exc.message}") from exc
    except OSError:
        temp.unlink(missing_ok=True)
        raise
    return destination


def image_size(path):
    """(width, height) of a stored image, or None."""
    info = GdkPixbuf.Pixbuf.get_file_info(str(path))
    if info is None or info[0] is None:
        return None
    return info[1], info[2]


def _solid(color, width, height):
    r, g, b = hex_to_rgb(color)
    pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, width, height)
    pixbuf.fill((r << 24) | (g << 16) | (b << 8) | 0xFF)
    return pixbuf


def _blur(pixbuf, radius):
    """A soft blur: down to a fraction of the size and back up, twice.

    Not a true Gaussian, but smooth at background scale and a fraction of
    the cost, with no dependency beyond GdkPixbuf.
    """
    width, height = pixbuf.get_width(), pixbuf.get_height()
    for factor in (1 + radius / 2, 1 + radius / 4):
        small = pixbuf.scale_simple(
            max(1, int(width / factor)), max(1, int(height / factor)),
            GdkPixbuf.InterpType.BILINEAR,
        )
        pixbuf = small.scale_simple(width, height, GdkPixbuf.InterpType.BILINEAR)
    return pixbuf


def processed_path(source, dim, blur, surface, cache_dir):
    """Where the processed copy of ``source`` with these settings lives.

    The name hashes the source's identity (path, size, change time) and the
    settings, so a changed picture or setting is a new file, never a stale
    one.
    """
    source = Path(source)
    try:
        stat = source.stat()
        identity = f"{source.resolve()}|{stat.st_size}|{stat.st_mtime_ns}"
    except OSError:
        identity = str(source)
    key = f"{identity}|{int(dim)}|{int(blur)}|{parse_hex(surface) or surface}"
    digest = hashlib.sha1(key.encode("utf-8", "surrogateescape"), usedforsecurity=False).hexdigest()[:20]
    return Path(cache_dir) / f"{digest}.png"


def render(source, dim, blur, surface, cache_dir):
    """Make (or reuse) the processed copy; returns its path, or None on failure."""
    target = processed_path(source, dim, blur, surface, cache_dir)
    if target.is_file():
        return target
    surface = parse_hex(surface) or "#000000"
    try:
        image = GdkPixbuf.Pixbuf.new_from_file(str(source))
        width, height = image.get_width(), image.get_height()
        # Flattened onto the area's color: a transparent picture shows the
        # theme's surface through it, as it would on screen.
        flat = _solid(surface, width, height)
        image.composite(flat, 0, 0, width, height, 0, 0, 1, 1,
                        GdkPixbuf.InterpType.NEAREST, 255)
        if blur > 0:
            flat = _blur(flat, blur)
        if dim > 0:
            veil = _solid(surface, width, height)
            veil.composite(flat, 0, 0, width, height, 0, 0, 1, 1,
                           GdkPixbuf.InterpType.NEAREST, int(round(255 * dim / 100)))
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_name(f".{target.name}.tmp")
        flat.savev(str(temp), "png", [], [])
        os.replace(temp, target)
    except (GLib.Error, OSError) as exc:
        logger.warning("Could not prepare background %s: %s", source, exc)
        return None
    _prune(target.parent, keep=target)
    return target


def _prune(cache_dir, keep):
    try:
        files = sorted(
            (entry for entry in Path(cache_dir).glob("*.png") if entry != keep),
            key=lambda entry: entry.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        return
    for old in files[CACHE_KEEP - 1:]:
        old.unlink(missing_ok=True)


def average_color(path):
    """The mean color of a picture, as ``#rrggbb``; None if it cannot be read."""
    try:
        pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(path), 16, 16, False)
    except GLib.Error:
        return None
    pixels = pixbuf.get_pixels()
    channels = pixbuf.get_n_channels()
    stride = pixbuf.get_rowstride()
    totals = [0, 0, 0]
    count = 0
    for y in range(pixbuf.get_height()):
        row = y * stride
        for x in range(pixbuf.get_width()):
            offset = row + x * channels
            for index in range(3):
                totals[index] += pixels[offset + index]
            count += 1
    return "#" + "".join(f"{round(total / count):02x}" for total in totals)
