"""Send a built manifest to one receiver: offer, wait for the answer, upload.

:class:`OutgoingTransfer` runs on a worker thread (``run()``). It offers the
manifest, hands the verification code to the caller, polls until the
receiver's user decides, then uploads every item the receiver asked for, in
manifest order, re-checking each source first. ``cancel()`` stops it from any
thread: the upload in progress is cut and the receiver is told.
"""

import logging
import threading

from openemux.core.share.protocol import ErrorCode, ShareError
from openemux.core.share.session import (
    STATUS_ACCEPTED,
    STATUS_CANCELLED,
    STATUS_DECLINED,
    STATUS_EXPIRED,
    STATUS_PENDING,
)

logger = logging.getLogger(__name__)

RESULT_DONE = "done"
RESULT_FAILED = "failed"
POLL_INTERVAL = 1.0
_FINAL = (STATUS_DECLINED, STATUS_EXPIRED, STATUS_CANCELLED)


class _LocalCancel(Exception):
    pass


class OutgoingTransfer:
    """One offer on its way out.

    ``on_code(code)`` gets the verification code once the offer is revealed;
    ``on_progress({item_id, name, bytes, size, done_bytes, total_bytes,
    files_done, file_count})`` follows each chunk; ``on_done({status, sent,
    skipped, error?})`` ends it, ``status`` being ``done``, ``declined``,
    ``expired``, ``cancelled`` or ``failed``.
    """

    def __init__(self, client, sender, built, *, on_code=None, on_progress=None, on_done=None,
                 poll_interval=POLL_INTERVAL):
        self.client = client
        self.sender = sender
        self.built = built
        self.on_code = on_code
        self.on_progress = on_progress
        self.on_done = on_done
        self.poll_interval = poll_interval
        self.offer_id = None
        self.result = None
        self._cancel = threading.Event()
        self._items = {
            item["id"]: item
            for game in built.manifest["games"] for item in game["items"]
        }

    def cancel(self):
        self._cancel.set()

    def start(self):
        thread = threading.Thread(target=self.run, name="share-send", daemon=True)
        thread.start()
        return thread

    def run(self):
        sent, skipped = [], []
        try:
            self._check_cancel()
            self.offer_id, code = self.client.offer(self.sender, self.built.manifest)
            if self.on_code is not None:
                self.on_code(code)
            answer = self._wait_for_answer()
            if answer["status"] != STATUS_ACCEPTED:
                return self._done(answer["status"], sent, skipped)
            to_send = self._accepted(answer.get("items"), skipped)
            self._upload(to_send, sent)
            return self._done(RESULT_DONE, sent, skipped)
        except _LocalCancel:
            self._tell_receiver()
            return self._done(STATUS_CANCELLED, sent, skipped)
        except ShareError as exc:
            if exc.code == ErrorCode.CANCELLED:
                return self._done(STATUS_CANCELLED, sent, skipped)
            if exc.code in (ErrorCode.DECLINED, ErrorCode.EXPIRED):
                return self._done(exc.code, sent, skipped)
            logger.warning("share send %s failed: %s (%s)", self.offer_id, exc.code, exc.message)
            if exc.code == ErrorCode.UNREACHABLE and self._receiver_cancelled():
                return self._done(STATUS_CANCELLED, sent, skipped)
            self._tell_receiver()
            return self._done(RESULT_FAILED, sent, skipped, error=exc.code)

    def _check_cancel(self):
        if self._cancel.is_set():
            raise _LocalCancel()

    def _wait_for_answer(self):
        while True:
            self._check_cancel()
            answer = self.client.poll(self.offer_id)
            if answer["status"] == STATUS_ACCEPTED or answer["status"] in _FINAL:
                return answer
            if answer["status"] != STATUS_PENDING:
                raise ShareError(ErrorCode.BAD_REQUEST, "unknown offer status")
            self._cancel.wait(self.poll_interval)

    def _accepted(self, items, skipped):
        """The items to upload, in manifest order; records the skipped ones."""
        wanted = set()
        for entry in items if isinstance(items, list) else []:
            if not isinstance(entry, dict) or entry.get("id") not in self._items:
                continue
            if entry.get("action") == "send":
                wanted.add(entry["id"])
            else:
                skipped.append({"item_id": entry["id"], "reason": entry.get("reason")})
        answered = wanted | {entry["item_id"] for entry in skipped}
        skipped.extend(
            {"item_id": item_id, "reason": None} for item_id in self._items if item_id not in answered
        )
        return [item for item_id, item in self._items.items() if item_id in wanted]

    def _upload(self, to_send, sent):
        total = sum(item["size"] for item in to_send)
        done = [0]
        for item in to_send:
            self._check_cancel()
            source = self.built.sources[item["id"]]
            # The mtime too: a battery save keeps its size when it is written,
            # and a changed one would only fail the receiver's sha256 check.
            try:
                stat = source.stat()
                changed = stat.st_size != item["size"] or int(stat.st_mtime) != item["mtime"]
            except OSError:
                changed = True
            if changed:
                raise ShareError(ErrorCode.SOURCE_CHANGED, f"{source} changed since it was offered")
            progress = [0]

            def on_chunk(n, item=item, progress=progress):
                self._check_cancel()
                progress[0] += n
                done[0] += n
                self._report(item, progress[0], done[0], total, len(sent), len(to_send))

            self.client.put_file(self.offer_id, item["id"], source, item["size"], on_chunk)
            sent.append(item["id"])
            self._report(item, item["size"], done[0], total, len(sent), len(to_send))

    def _report(self, item, current, done, total, files_done, file_count):
        if self.on_progress is not None:
            self.on_progress({
                "item_id": item["id"], "name": item["name"], "bytes": current, "size": item["size"],
                "done_bytes": done, "total_bytes": total, "files_done": files_done, "file_count": file_count,
            })

    def _receiver_cancelled(self):
        """After a cut connection: did the receiver cancel? Asked once."""
        if self.offer_id is None:
            return False
        try:
            return self.client.poll(self.offer_id).get("status") == STATUS_CANCELLED
        except ShareError:
            return False

    def _tell_receiver(self):
        if self.offer_id is None:
            return
        try:
            self.client.cancel(self.offer_id)
        except ShareError as exc:
            logger.debug("share send %s: cancel not delivered: %s", self.offer_id, exc.code)

    def _done(self, status, sent, skipped, error=None):
        self.result = {"status": status, "sent": list(sent), "skipped": list(skipped)}
        if error is not None:
            self.result["error"] = error
        if self.on_done is not None:
            self.on_done(self.result)
        return self.result
