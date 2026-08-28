"""Cover decoding: off the main thread, on a bounded pool, with an LRU.

Three separate problems used to make a big library saturate one core while
the UI stuttered (issue #128):

1. **The decode ran on the GTK main thread.** The old worker did nothing but
   a handful of ``stat()`` calls and handed the real cost -- JPEG/PNG decode
   plus a rescale -- back through ``GLib.idle_add``, serialised on the one
   thread that cannot afford it.
2. **One OS thread per ROM, unbounded.** The grid did not virtualize back
   then, so every card on the page was built eagerly; a 500-ROM console
   spawned 500 threads to run 500 ``stat()`` calls. It does virtualize now
   (issue #219), which bounds the *callers* too.
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

#: Memory bound for the LRU, in bytes. Counting *entries* was the wrong unit:
#: the rationale was that covers are downscaled to their target size, which is
#: not true of the cartridge branch -- it decodes the composite at full
#: resolution on purpose, roughly 1.8 MB an entry at zoom 2.0, so a 256-entry
#: cap permitted several hundred megabytes (issue #219). A pixbuf knows how
#: many bytes it occupies, so the bound is stated in the unit that matters.
#:
#: 128 MiB holds well over a screenful of cards at any zoom, which is what
#: makes a sort, a zoom or a page switch cheap -- the reason the cache exists.
MAX_CACHE_BYTES = 128 * 1024 * 1024

#: One worker per core. The point is to *bound* the pool: the old code span
#: one OS thread per ROM, which is what pinned a core on a big library.
MAX_WORKERS = max(2, os.cpu_count() or 2)

_pool = None
_pool_lock = threading.Lock()

_cache = OrderedDict()
_cache_bytes = 0
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


def _pixbuf_bytes(pixbuf):
    """How much memory this pixbuf holds, as GdkPixbuf itself reports it."""
    try:
        return int(pixbuf.get_byte_length())
    except (AttributeError, TypeError):  # pragma: no cover - defensive
        return pixbuf.get_rowstride() * pixbuf.get_height()


def _cache_put(key, pixbuf):
    if key is None or pixbuf is None:
        return
    global _cache_bytes
    size = _pixbuf_bytes(pixbuf)
    with _cache_lock:
        previous = _cache.pop(key, None)
        if previous is not None:
            _cache_bytes -= _pixbuf_bytes(previous)
        _cache[key] = pixbuf
        _cache_bytes += size
        # Never down to empty: one entry larger than the whole budget is still
        # worth keeping while it is the one being looked at.
        while _cache_bytes > MAX_CACHE_BYTES and len(_cache) > 1:
            _evicted_key, evicted = _cache.popitem(last=False)
            _cache_bytes -= _pixbuf_bytes(evicted)


def cache_clear():
    global _cache_bytes
    with _cache_lock:
        _cache.clear()
        _cache_bytes = 0


def cache_size():
    with _cache_lock:
        return len(_cache)


def cache_bytes():
    """How much memory the cached covers hold right now."""
    with _cache_lock:
        return _cache_bytes


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
