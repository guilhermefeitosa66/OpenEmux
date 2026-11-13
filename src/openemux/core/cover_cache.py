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

import heapq
import itertools
import logging
import os
import threading
from collections import OrderedDict
from concurrent.futures import TimeoutError as FutureTimeoutError
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

#: Job priorities, lowest number first. A card that is on screen promotes its
#: fetch to URGENT (issue 899); everything else queues in arrival order.
PRIORITY_URGENT = 0
PRIORITY_NORMAL = 1

_pool = None
_pool_lock = threading.Lock()

_cache = OrderedDict()
_cache_bytes = 0
_cache_lock = threading.Lock()


class Job:
    """One unit of work on the pool: a Future that can jump the queue.

    ``promote()`` re-queues a job that has not started yet at the front. The
    old FIFO executor could not do that: after a zoom, the hundreds of fetches
    queued for cards that no longer existed ran before the fetches of the
    cards actually on screen, which showed placeholders for seconds (issue
    899). ``cancel()`` drops a job that has not started; a running one is
    left to finish.
    """

    __slots__ = ("fn", "args", "kwargs", "_pool", "_state", "_lock", "_done", "_result", "_exception")

    PENDING, RUNNING, FINISHED, CANCELLED = range(4)

    def __init__(self, fn, args, kwargs, pool=None):
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        #: The pool the job was submitted to: a promotion re-queues it there,
        #: not on the shared pool, which a private pool's job used to land on.
        self._pool = pool
        self._state = self.PENDING
        self._lock = threading.Lock()
        self._done = threading.Event()
        self._result = None
        self._exception = None

    def _claim(self):
        """Mark the job running, once. False when another entry already did."""
        with self._lock:
            if self._state != self.PENDING:
                return False
            self._state = self.RUNNING
            return True

    def _run(self):
        try:
            self._result = self.fn(*self.args, **self.kwargs)
        except BaseException as exc:  # noqa: BLE001 - surfaced through result()
            self._exception = exc
            logger.exception("cover pool: job failed")
        finally:
            with self._lock:
                self._state = self.FINISHED
            self._done.set()

    def cancel(self):
        """Drop the job if it has not started. Returns whether it was dropped."""
        with self._lock:
            if self._state != self.PENDING:
                return False
            self._state = self.CANCELLED
        self._done.set()
        return True

    def promote(self):
        """Move a pending job to the front of its pool's queue."""
        if self._state != self.PENDING:
            return False
        return (self._pool or pool()).requeue(self, PRIORITY_URGENT)

    def done(self):
        return self._done.is_set()

    def cancelled(self):
        return self._state == self.CANCELLED

    def result(self, timeout=None):
        """Wait for the job; re-raises what it raised."""
        if not self._done.wait(timeout):
            raise FutureTimeoutError()
        if self._exception is not None:
            raise self._exception
        return self._result


class DecodePool:
    """A bounded pool of workers over a priority queue."""

    def __init__(self, max_workers, thread_name_prefix="openemux-cover"):
        self.max_workers = max(1, int(max_workers))
        self._prefix = thread_name_prefix
        self._heap = []
        self._sequence = itertools.count()
        self._condition = threading.Condition()
        self._threads = []
        self._shutdown = False

    def submit(self, fn, *args, priority=PRIORITY_NORMAL, **kwargs):
        job = Job(fn, args, kwargs, pool=self)
        self.requeue(job, priority)
        return job

    def requeue(self, job, priority):
        """Put ``job`` on the queue at ``priority``; the first pop claims it."""
        with self._condition:
            if self._shutdown:
                return False
            heapq.heappush(self._heap, (priority, next(self._sequence), job))
            self._ensure_worker()
            self._condition.notify()
        return True

    def _ensure_worker(self):
        """Start a worker when every one is busy and the cap allows another."""
        if len(self._threads) >= self.max_workers:
            return
        idle = sum(1 for thread in self._threads if getattr(thread, "idle", False))
        if idle > 0:
            return
        thread = threading.Thread(
            target=self._work,
            name=f"{self._prefix}-{len(self._threads)}",
            daemon=True,
        )
        thread.idle = False
        self._threads.append(thread)
        thread.start()

    def _work(self):
        thread = threading.current_thread()
        while True:
            with self._condition:
                while not self._heap and not self._shutdown:
                    thread.idle = True
                    self._condition.wait()
                thread.idle = False
                if not self._heap:
                    return
                _priority, _seq, job = heapq.heappop(self._heap)
            if job._claim():
                job._run()

    def pending(self):
        """How many queue entries are waiting (promotions count twice)."""
        with self._condition:
            return len(self._heap)

    def shutdown(self, wait=True):
        """Stop taking work; with ``wait``, finish what is queued first."""
        with self._condition:
            if not wait:
                self._heap.clear()
            self._shutdown = True
            self._condition.notify_all()
        if wait:
            for thread in list(self._threads):
                thread.join()


def pool():
    """The process-wide decode pool, created on first use."""
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = DecodePool(MAX_WORKERS)
        return _pool


def submit(fn, *args, priority=PRIORITY_NORMAL, **kwargs):
    """Run ``fn`` on the shared decode pool. Returns a :class:`Job`."""
    return pool().submit(fn, *args, priority=priority, **kwargs)


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


def cache_key(path, target_w=None, target_h=None):
    """The key :func:`load_cover` would file ``path`` under, or None.

    A caller that keeps it can hand it back to ``load_cover`` and skip the
    stat on every later bind of the same card (issue 907).
    """
    return _cache_key(path, target_w, target_h)


def load_cover(path, target_w=None, target_h=None, key=None):
    """Decode ``path``, scaled to fit ``target_w`` x ``target_h``.

    Safe to call from a worker thread -- that is the entire point. Pass no
    target size to decode at full resolution, which is what a cartridge
    composite wants (it is already the card's shape, and the full-resolution
    art is what keeps it sharp on HiDPI).

    ``key`` is a key from :func:`cache_key` remembered from an earlier load:
    with it, a hit costs a dictionary lookup and no syscall at all. The
    caller owns its freshness -- the card drops it whenever the artwork is
    changed through the app -- so a cover replaced *behind* the app's back is
    seen on the next page build rather than on the next bind.

    Returns ``None`` rather than raising: a cover can be missing, truncated
    or not an image at all, and none of those should take down a card.
    """
    if not path:
        return None
    if key is None:
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
