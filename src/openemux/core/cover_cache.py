"""Cover decoding: off the main thread, on a bounded pool, with an LRU.

Three separate problems used to make a big library saturate one core while
the UI stuttered (issue #128):

1. **The decode ran on the GTK main thread.** The old worker did nothing but
   a handful of ``stat()`` calls and handed the real cost -- JPEG/PNG decode
   plus a rescale -- back through ``GLib.idle_add``, serialised on the one
   thread that cannot afford it.
2. **One OS thread per ROM, unbounded.** ``Gtk.FlowBox`` does not
   virtualize, so every card on the page is built eagerly; a 500-ROM console
   spawned 500 threads to run 500 ``stat()`` calls.
3. **Nothing was cached**, and a zoom, sort or view-mode change rebuilds the
   whole grid, re-decoding every cover from scratch.

Widget-free on purpose, exactly like ``cartridge_render``: GdkPixbuf is a
drawing library, not GTK, so this stays in core/ and is testable without a
display. Converting the pixbuf into a texture and handing it to a widget is
the caller's job and the only part that must run on the main loop.
"""

import logging
import os
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import gi

gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GLib, GdkPixbuf

logger = logging.getLogger(__name__)

#: Bump when the decode itself changes so stale entries are not reused.
COVER_CACHE_VERSION = 1

#: Entry bound for the LRU. Covers are already downscaled to their target
#: size, so a few hundred is a modest amount of memory and comfortably more
#: than one screenful across a couple of zoom levels.
MAX_CACHED_COVERS = 256

#: One worker per core. The point is to *bound* the pool: the old code span
#: one OS thread per ROM, which is what pinned a core on a big library.
MAX_WORKERS = max(2, os.cpu_count() or 2)

_pool = None
_pool_lock = threading.Lock()

_cache = OrderedDict()
_cache_lock = threading.Lock()


def pool():
    """The process-wide decode pool, created on first use."""
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = ThreadPoolExecutor(
                max_workers=MAX_WORKERS, thread_name_prefix="openemux-cover"
            )
        return _pool


def submit(fn, *args, **kwargs):
    """Run ``fn`` on the shared decode pool. Returns a Future."""
    return pool().submit(fn, *args, **kwargs)


def _cache_key(path, target_w, target_h):
    """Content-addressed, so replacing a cover invalidates it by itself.

    The same self-invalidating shape ``cartridge_render`` uses: mtime and
    size are part of the key, so there is no explicit invalidation hook to
    forget to call when artwork changes on disk.
    """
    try:
        stat = Path(path).stat()
    except OSError:
        return None
    return (
        COVER_CACHE_VERSION,
        str(path),
        stat.st_mtime_ns,
        stat.st_size,
        target_w,
        target_h,
    )


def _cache_get(key):
    if key is None:
        return None
    with _cache_lock:
        if key not in _cache:
            return None
        _cache.move_to_end(key)
        return _cache[key]


def _cache_put(key, pixbuf):
    if key is None or pixbuf is None:
        return
    with _cache_lock:
        _cache[key] = pixbuf
        _cache.move_to_end(key)
        while len(_cache) > MAX_CACHED_COVERS:
            _cache.popitem(last=False)


def cache_clear():
    with _cache_lock:
        _cache.clear()


def cache_size():
    with _cache_lock:
        return len(_cache)


def load_cover(path, target_w=None, target_h=None):
    """Decode ``path``, scaled to fit ``target_w`` x ``target_h``.

    Safe to call from a worker thread -- that is the entire point. Pass no
    target size to decode at full resolution, which is what a cartridge
    composite wants (it is already the card's shape, and the full-resolution
    art is what keeps it sharp on HiDPI).

    Returns ``None`` rather than raising: a cover can be missing, truncated
    or not an image at all, and none of those should take down a card.
    """
    if not path:
        return None
    key = _cache_key(path, target_w, target_h)
    if key is None:
        # Not on disk at all. That is the ordinary "no artwork" case, which
        # the placeholder already expresses -- no need to log it.
        return None
    cached = _cache_get(key)
    if cached is not None:
        return cached

    try:
        if target_w and target_h:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(
                str(path), target_w, target_h, True
            )
        else:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file(str(path))
    except (GLib.Error, OSError) as exc:
        # Logged rather than swallowed: a corrupt cover used to be
        # indistinguishable from a missing one.
        logger.warning("cover decode failed: path=%s error=%s", path, exc)
        return None

    _cache_put(key, pixbuf)
    return pixbuf
