"""Carry out an accepted :class:`placement.ReceivePlan`, file by file.

Every upload is staged as a hidden temporary file in its target's own
directory and checked (length, sha256, image header for art). Nothing appears
in the library until the last file has arrived: then everything is committed
at once, in the plan's order, each existing file it replaces moved aside
first. A commit that fails halfway is rolled back -- what was placed is
removed and what was moved aside comes back -- and a cancel from either side,
a broken connection, a bad hash, a full disk or a sender that goes quiet
discard everything staged. Either way the library is left as it was.

The library itself (favorites, per-game core, shader and colour) is reached
only through a :class:`LibraryHooks` the caller passes in, so this module never
holds a manager.
"""

import errno
import hashlib
import logging
import os
import threading
import time
from pathlib import Path

from openemux.core.atomic_write import stage_stream
from openemux.core.cartridge_colors import color_name_key
from openemux.core.scraper import is_image_file
from openemux.core.share.placement import ROM_EXISTING, ROM_PLACED
from openemux.core.share.protocol import (
    IDLE_TIMEOUT,
    KIND_COVER,
    KIND_LABEL,
    ErrorCode,
    ShareError,
)

logger = logging.getLogger(__name__)

STATUS_RECEIVING = "receiving"
STATUS_DONE = "done"
STATUS_FAILED = "failed"
STATUS_CANCELLED = "cancelled"

READ_CHUNK = 256 * 1024
#: Progress callbacks per second, at most, besides the last one of each file.
PROGRESS_RATE = 10
#: Temporary files older than this, left by a crash of the app, are removed
#: from the directories a transfer is about to write.
STALE_TEMP_SECONDS = 3600
WATCHDOG_INTERVAL = 1.0


class LibraryHooks:
    """How a finished transfer reaches the library; each a no-op here.

    #589 builds one from ``PlaylistManager`` and ``ConfigManager``. Paths
    are the placed ROM's.
    """

    def set_favorite(self, rom_path):
        pass

    def set_cartridge_color(self, rom_path, console, color_id):
        pass

    def set_core(self, rom_path, core_filename):
        pass

    def set_shader(self, rom_path, console, shader_id):
        pass


class _Cancelled(Exception):
    pass


class IncomingTransfer:
    """One accepted offer being received.

    ``handle_put`` runs on the server's request threads, one per upload;
    everything shared is under one lock. ``on_progress`` and ``on_done`` are
    called from those threads (or the watchdog's) -- the UI marshals them.
    """

    def __init__(self, offer_id, plan, *, catalog, hooks=None, shader_ids=None, on_progress=None,
                 on_done=None, on_abort=None, clock=time.monotonic):
        self.offer_id = offer_id
        self.plan = plan
        self.catalog = catalog
        self.hooks = hooks or LibraryHooks()
        self.shader_ids = set(shader_ids) if shader_ids is not None else None
        self.on_progress = on_progress
        self.on_done = on_done
        #: Told when this side ends the transfer (cancel, a failure, the idle
        #: timeout), so the server can stop the offer for the sender too.
        self.on_abort = on_abort
        self.clock = clock
        self.status = STATUS_RECEIVING
        self.result = None
        self._sends = {d.item_id: d for d in plan.to_send()}
        self._staged = {}
        self._uploading = set()
        #: Folders made for this transfer, in creation order (a dict for its order).
        self._created_dirs = {}
        self._done_bytes = 0
        self._total_bytes = sum(d.size for d in self._sends.values())
        self._last_activity = clock()
        self._last_progress = None
        self._lock = threading.Lock()
        self._watchdog = None
        self._sweep_stale_temps()

    # -- start-up --------------------------------------------------------

    def _target_dirs(self):
        return sorted({d.target.parent for d in self._sends.values()})

    def _sweep_stale_temps(self):
        cutoff = time.time() - STALE_TEMP_SECONDS
        for directory in self._target_dirs():
            if not directory.is_dir():
                continue
            for entry in directory.iterdir():
                if not (entry.name.startswith(".") and entry.name.endswith(".tmp")):
                    continue
                try:
                    if entry.is_file() and entry.stat().st_mtime < cutoff:
                        entry.unlink()
                except OSError as exc:
                    logger.debug("share receive: stale temp left: %s (%s)", entry, exc)

    def start(self):
        """Finish at once when nothing is to be sent; otherwise wait for uploads."""
        with self._lock:
            committing = self.status == STATUS_RECEIVING and not self._sends
            if committing:
                self._commit()
        if committing:
            self._after_commit()

    def start_watchdog(self, interval=WATCHDOG_INTERVAL):
        """Check the idle timeout every ``interval`` seconds until the transfer ends."""
        stop = threading.Event()

        def run():
            while not stop.wait(interval):
                if self.sweep(self.clock()):
                    return

        self._watchdog = stop
        threading.Thread(target=run, name="share-receive-watchdog", daemon=True).start()

    # -- uploads ---------------------------------------------------------

    def handle_put(self, item_id, body, length):
        """Stage one upload; the last one commits the whole transfer.

        Raises :class:`ShareError` for the sender: ``bad_request`` for an
        upload this plan does not expect (the transfer goes on), and the
        transfer's own failure once it has been aborted.
        """
        with self._lock:
            self._check_live()
            decision = self._sends.get(item_id)
            if decision is None or item_id in self._staged or item_id in self._uploading:
                raise ShareError(ErrorCode.BAD_REQUEST, "item is not expected")
            if length != decision.size:
                raise ShareError(ErrorCode.BAD_REQUEST, "Content-Length differs from the offered size")
            self._uploading.add(item_id)
            self._last_activity = self.clock()
            self._note_dirs(decision.target.parent)
        digest = hashlib.sha256()
        received = [0]

        def on_chunk(n):
            with self._lock:
                if self.status != STATUS_RECEIVING:
                    raise _Cancelled()
                self._last_activity = self.clock()
                self._done_bytes += n
            received[0] += n
            self._progress(decision, received[0], final=False)

        try:
            staged = stage_stream(
                decision.target, _Hashing(body, digest), READ_CHUNK, on_chunk=on_chunk
            )
        except _Cancelled:
            # The temp file is gone by now; so can the folders made for it.
            self._upload_ended(item_id)
            raise self._closed_error() from None
        except OSError as exc:
            self._upload_ended(item_id)
            if exc.errno == errno.ENOSPC:
                raise self._abort(ErrorCode.NO_SPACE, "disk full") from exc
            if isinstance(exc, (TimeoutError, ConnectionError)):
                raise self._abort(ErrorCode.UNREACHABLE, "upload interrupted") from exc
            raise self._abort(ErrorCode.INTERNAL, str(exc)) from exc
        problem = self._check(decision, staged, digest)
        with self._lock:
            self._uploading.discard(item_id)
            if self.status != STATUS_RECEIVING:
                staged.discard()
                self._remove_created_dirs()
                raise self._closed_error()
            self._staged[item_id] = staged
        if problem is not None:
            raise self._abort(ErrorCode.BAD_REQUEST, problem)
        self._progress(decision, staged.size, final=True)
        with self._lock:
            committing = self.status == STATUS_RECEIVING and len(self._staged) == len(self._sends)
            if committing:
                self._commit()
        if committing:
            self._after_commit()
            if self.status == STATUS_FAILED:
                raise ShareError(ErrorCode.INTERNAL, "commit failed")

    @staticmethod
    def _check(decision, staged, digest):
        if staged.size != decision.size:
            return "short upload"
        if decision.sha256 and digest.hexdigest() != decision.sha256:
            return "sha256 mismatch"
        if decision.kind in (KIND_COVER, KIND_LABEL) and not is_image_file(staged.tmp_path):
            return "art is not an image"
        return None

    def _upload_ended(self, item_id):
        with self._lock:
            self._uploading.discard(item_id)
            if self.status != STATUS_RECEIVING:
                self._remove_created_dirs()

    def _check_live(self):
        if self.status != STATUS_RECEIVING:
            raise self._closed_error()

    @staticmethod
    def _closed_error():
        # Whatever ended it, for the sender this offer is over.
        return ShareError(ErrorCode.CANCELLED, "transfer ended")

    def _note_dirs(self, directory):
        """Remember the directories a stage will create, to remove them on abort."""
        missing = []
        while not directory.exists():
            missing.append(directory)
            directory = directory.parent
        for path in reversed(missing):
            self._created_dirs.setdefault(path)

    def _progress(self, decision, done, final):
        if self.on_progress is None:
            return
        now = self.clock()
        if not final and self._last_progress is not None and now - self._last_progress < 1 / PROGRESS_RATE:
            return
        self._last_progress = now
        with self._lock:
            files_done = len(self._staged)
            done_bytes = self._done_bytes
        self.on_progress({
            "item_id": decision.item_id, "name": decision.name, "kind": decision.kind,
            "bytes": done, "size": decision.size, "done_bytes": done_bytes,
            "total_bytes": self._total_bytes, "files_done": files_done, "file_count": len(self._sends),
        })

    # -- ending ----------------------------------------------------------

    def cancel(self):
        """The receiver's user cancelled; idempotent."""
        self._end(STATUS_CANCELLED, ErrorCode.CANCELLED, notify=True)

    def on_remote_cancel(self):
        """The sender cancelled, or the server expired the offer; idempotent."""
        self._end(STATUS_CANCELLED, ErrorCode.CANCELLED, notify=False)

    def sweep(self, now):
        """Abort after :data:`IDLE_TIMEOUT` without data; ``True`` once the transfer is over."""
        with self._lock:
            if self.status != STATUS_RECEIVING:
                return True
            idle = now - self._last_activity > IDLE_TIMEOUT
        if idle:
            self._end(STATUS_FAILED, ErrorCode.IDLE_TIMEOUT, notify=True)
            return True
        return False

    def _abort(self, code, message):
        logger.warning("share receive %s aborted: %s (%s)", self.offer_id, code, message)
        self._end(STATUS_FAILED, code, notify=True)
        return ShareError(code, message)

    def _end(self, status, code, notify):
        with self._lock:
            if self.status != STATUS_RECEIVING:
                return
            self._discard_all()
            self._finish(status, error=code)
        if notify and self.on_abort is not None:
            self.on_abort(self.offer_id)
        self._report()

    def _discard_all(self):
        for staged in self._staged.values():
            staged.discard()
        self._staged.clear()
        self._remove_created_dirs()

    def _remove_created_dirs(self):
        for directory in reversed(self._created_dirs):
            try:
                directory.rmdir()
            except OSError:
                # Not empty (an upload still finishing will discard into it) or gone.
                pass

    def _finish(self, status, placed=(), replaced=(), error=None):
        self.status = status
        skipped = [
            {"item_id": d.item_id, "reason": d.reason}
            for d in self.plan.decisions() if d.item_id not in self._sends
        ]
        self.result = {"status": status, "placed": [str(p) for p in placed],
                       "replaced": [str(p) for p in replaced], "skipped": skipped}
        if error is not None:
            self.result["error"] = error
        if self._watchdog is not None:
            self._watchdog.set()

    def _report(self):
        if self.on_done is not None:
            self.on_done(self.result)

    def _commit(self):
        """Place every staged file at once; called with the lock held."""
        committed, aside = [], []
        try:
            for decision in self.plan.to_send():
                if decision.replaces is not None and os.path.lexists(decision.replaces):
                    moved = decision.replaces.with_name(
                        f".{decision.replaces.name}.share-old-{self.offer_id}"
                    )
                    os.replace(decision.replaces, moved)
                    aside.append((moved, decision.replaces))
                self._staged[decision.item_id].commit(replace=False)
                committed.append(decision.target)
                os.utime(decision.target, (decision.mtime, decision.mtime))
        except OSError as exc:
            logger.warning("share receive %s: commit failed, rolling back: %s", self.offer_id, exc)
            self._rollback(committed, aside)
            self._finish(STATUS_FAILED, error=ErrorCode.INTERNAL)
            return
        for moved, _ in aside:
            try:
                moved.unlink()
            except OSError as exc:
                logger.warning("share receive: replaced file kept at %s (%s)", moved, exc)
        self._apply_metadata()
        self._finish(
            STATUS_DONE, placed=committed,
            replaced=[original for _, original in aside],
        )

    def _after_commit(self):
        """Tell the caller how the commit went, outside the lock."""
        if self.status == STATUS_FAILED and self.on_abort is not None:
            self.on_abort(self.offer_id)
        self._report()

    def _rollback(self, committed, aside):
        for target in reversed(committed):
            try:
                target.unlink()
            except OSError as exc:
                logger.error("share receive: could not remove %s on rollback (%s)", target, exc)
        for moved, original in reversed(aside):
            try:
                os.replace(moved, original)
            except OSError as exc:
                logger.error("share receive: %s left at %s on rollback (%s)", original, moved, exc)
        self._discard_all()

    def _apply_metadata(self):
        for game in self.plan.games:
            metadata = game.metadata
            if game.rom_path is None or game.rom_status not in ROM_PLACED + (ROM_EXISTING,):
                continue
            path = Path(game.rom_path)
            try:
                if metadata.get("favorite") is True:
                    self.hooks.set_favorite(path)
                if game.rom_status not in ROM_PLACED:
                    continue
                self._apply_overrides(game, path, metadata)
            except Exception:
                logger.exception("share receive: metadata for %s not applied", path)

    def _apply_overrides(self, game, path, metadata):
        color = metadata.get("cartridge_color")
        if isinstance(color, str) and color_name_key(color) is not None:
            self.hooks.set_cartridge_color(path, game.console, color)
        core_name = metadata.get("core")
        core = self.catalog.find_by_name(core_name) if isinstance(core_name, str) else None
        if core is not None:
            self.hooks.set_core(path, core.filename)
        shader = metadata.get("shader")
        if isinstance(shader, str) and self.shader_ids is not None and shader in self.shader_ids:
            self.hooks.set_shader(path, game.console, shader)


class _Hashing:
    """A reader that feeds a digest with everything read through it."""

    def __init__(self, source, digest):
        self.source = source
        self.digest = digest

    def read(self, size=-1):
        chunk = self.source.read(size)
        self.digest.update(chunk)
        return chunk
