import os
import threading
import unittest
from pathlib import Path

from openemux.core.share import send
from openemux.core.share.manifest import BuiltManifest
from openemux.core.share.protocol import ErrorCode, ShareError
from openemux.core.share.send import OutgoingTransfer
from tests.share_fixtures import temp_library


class FakeClient:
    def __init__(self, answers, put_error=None, cancel_error=None):
        self.answers = list(answers)
        self.put_error = put_error
        self.cancel_error = cancel_error
        self.calls = []

    def offer(self, sender, manifest):
        self.calls.append(("offer",))
        return "offer1", "123456"

    def poll(self, offer_id):
        self.calls.append(("poll",))
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    def put_file(self, offer_id, item_id, path, size, on_chunk):
        self.calls.append(("put", item_id))
        if callable(self.put_error):
            self.put_error(item_id, on_chunk)
        elif self.put_error is not None:
            raise self.put_error
        for _ in range(2):
            on_chunk(size // 2)

    def cancel(self, offer_id):
        self.calls.append(("cancel",))
        if self.cancel_error is not None:
            raise self.cancel_error


ACCEPTED = {"status": "accepted", "items": [
    {"id": "i1", "action": "send"},
    {"id": "i2", "action": "skip", "reason": "exists_skip"},
    {"id": "i3", "action": "send"},
    {"id": "zz", "action": "send"},
    "junk",
]}


class SendTestCase(unittest.TestCase):
    def setUp(self):
        self.lib = temp_library(self)
        sources = {}
        items = []
        for n in (1, 2, 3, 4):
            path = self.lib.file(f"roms/SFC/f{n}.bin", b"x" * 10)
            sources[f"i{n}"] = path
            items.append({"id": f"i{n}", "kind": "rom", "name": path.name, "size": 10, "mtime": 1})
        manifest = {"games": [{"id": "g1", "console": "SFC", "title": "G", "items": items}],
                    "total_size": 40, "file_count": 4}
        self.built = BuiltManifest(manifest, sources)
        self.codes, self.progress, self.done = [], [], []

    def transfer(self, client):
        return OutgoingTransfer(
            client, {"id": "s"}, self.built, on_code=self.codes.append,
            on_progress=self.progress.append, on_done=self.done.append, poll_interval=0,
        )


class FlowTests(SendTestCase):
    def test_accepted_uploads_only_the_send_items_in_order(self):
        client = FakeClient([{"status": "pending"}, ACCEPTED])
        result = self.transfer(client).run()
        self.assertEqual(self.codes, ["123456"])
        self.assertEqual([c for c in client.calls if c[0] == "put"], [("put", "i1"), ("put", "i3")])
        self.assertEqual(result, {"status": "done", "sent": ["i1", "i3"], "skipped": [
            {"item_id": "i2", "reason": "exists_skip"}, {"item_id": "i4", "reason": None},
        ]})
        self.assertEqual(self.done, [result])
        self.assertEqual(self.progress[-1], {
            "item_id": "i3", "name": "f3.bin", "bytes": 10, "size": 10, "done_bytes": 20,
            "total_bytes": 20, "files_done": 2, "file_count": 2,
        })

    def test_final_answers_other_than_accepted(self):
        for status in ("declined", "expired", "cancelled"):
            self.assertEqual(self.transfer(FakeClient([{"status": status}])).run()["status"], status)

    def test_an_accepted_answer_without_items(self):
        result = self.transfer(FakeClient([{"status": "accepted"}])).run()
        self.assertEqual((result["sent"], len(result["skipped"])), ([], 4))

    def test_an_unknown_status_fails(self):
        client = FakeClient([{"status": "odd"}])
        result = self.transfer(client).run()
        self.assertEqual((result["status"], result["error"]), ("failed", ErrorCode.BAD_REQUEST))
        self.assertIn(("cancel",), client.calls)

    def test_offer_errors(self):
        for code, status in ((ErrorCode.DECLINED, "declined"), (ErrorCode.EXPIRED, "expired"),
                             (ErrorCode.CANCELLED, "cancelled")):
            client = FakeClient([ShareError(code)])
            self.assertEqual(self.transfer(client).run()["status"], status)

    def test_a_client_error_is_reported(self):
        client = FakeClient([ACCEPTED], put_error=ShareError(ErrorCode.INTERNAL, "boom"),
                            cancel_error=ShareError(ErrorCode.UNREACHABLE))
        with self.assertLogs(send.logger, "WARNING"):
            result = self.transfer(client).run()
        self.assertEqual((result["status"], result["error"]), ("failed", ErrorCode.INTERNAL))

    def test_an_unreachable_offer_has_nothing_to_cancel(self):
        class Unreachable(FakeClient):
            def offer(self, sender, manifest):
                raise ShareError(ErrorCode.UNREACHABLE)

        client = Unreachable([])
        with self.assertLogs(send.logger, "WARNING"):
            result = self.transfer(client).run()
        self.assertEqual((result["status"], client.calls), ("failed", []))

    def test_a_cut_connection_after_the_receiver_cancelled(self):
        client = FakeClient([ACCEPTED, {"status": "cancelled"}], put_error=ShareError(ErrorCode.UNREACHABLE))
        with self.assertLogs(send.logger, "WARNING"):
            self.assertEqual(self.transfer(client).run()["status"], "cancelled")
        client = FakeClient([ACCEPTED, ShareError(ErrorCode.UNREACHABLE)],
                            put_error=ShareError(ErrorCode.UNREACHABLE))
        with self.assertLogs(send.logger, "WARNING"):
            self.assertEqual(self.transfer(client).run()["status"], "failed")

    def test_the_receiver_cancels_with_a_410(self):
        client = FakeClient([ACCEPTED], put_error=ShareError(ErrorCode.CANCELLED))
        self.assertEqual(self.transfer(client).run()["status"], "cancelled")


class CancelTests(SendTestCase):
    def test_cancel_before_anything(self):
        transfer = self.transfer(FakeClient([]))
        transfer.cancel()
        self.assertEqual(transfer.run()["status"], "cancelled")
        self.assertEqual(transfer.client.calls, [])

    def test_cancel_mid_upload_tells_the_receiver(self):
        transfer = None

        def put_error(item_id, on_chunk):
            transfer.cancel()
            on_chunk(5)

        client = FakeClient([ACCEPTED], put_error=put_error)
        transfer = self.transfer(client)
        self.assertEqual(transfer.run()["status"], "cancelled")
        self.assertEqual(client.calls[-1], ("cancel",))

    def test_cancel_while_waiting_for_the_answer(self):
        client = FakeClient([{"status": "pending"}] * 1000)
        transfer = OutgoingTransfer(client, {}, self.built, poll_interval=30)
        thread = transfer.start()
        while ("poll",) not in client.calls:
            threading.Event().wait(0.01)
        transfer.cancel()
        thread.join(5)
        self.assertEqual(transfer.result["status"], "cancelled")


class SourceTests(SendTestCase):
    def test_a_source_that_changed_or_vanished(self):
        for change in (lambda p: p.write_bytes(b"short"), lambda p: p.unlink()):
            self.setUp()
            change(Path(self.built.sources["i3"]))
            client = FakeClient([ACCEPTED])
            with self.assertLogs(send.logger, "WARNING"):
                result = self.transfer(client).run()
            self.assertEqual((result["status"], result["error"], result["sent"]),
                             ("failed", ErrorCode.SOURCE_CHANGED, ["i1"]))
            self.assertEqual(client.calls[-1], ("cancel",))

    def test_without_callbacks(self):
        transfer = OutgoingTransfer(FakeClient([ACCEPTED]), {}, self.built, poll_interval=0)
        self.assertEqual(transfer.run()["status"], "done")


if __name__ == "__main__":
    unittest.main()
