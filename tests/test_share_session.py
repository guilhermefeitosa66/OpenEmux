import http.client
import io
import json
import socket
import ssl
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from openemux.core.share import session, verification
from openemux.core.share.identity import load_or_create
from openemux.core.share.protocol import ErrorCode, ShareError
from openemux.core.share.session import ShareClient, ShareServer


def manifest():
    return {
        "games": [{"id": "g1", "console": "FC", "title": "Game", "items": [
            {"id": "i1", "kind": "rom", "name": "Game.nes", "size": 4, "mtime": 1},
            {"id": "i2", "kind": "cover", "name": "Game.png", "size": 4, "mtime": 1},
        ]}],
        "total_size": 8, "file_count": 2,
    }


def assert_nothing_listens(case, port):
    """Connecting to ``port`` fails: refused on Linux, timed out on Windows."""
    with case.assertRaises(OSError):
        socket.create_connection(("127.0.0.1", port), timeout=2).close()


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class SessionTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        cls.sender = load_or_create(root / "sender", "Sender")
        cls.receiver = load_or_create(root / "receiver", "Receiver")
        cls.other = load_or_create(root / "other", "Other")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def serve(self, device=None, **kwargs):
        self.clock = Clock()
        self.offers, self.cancels = [], []
        server = ShareServer(
            device or self.receiver, clock=self.clock, on_offer=self.offers.append,
            on_cancel=self.cancels.append, host="127.0.0.1", port=0, **kwargs,
        )
        server.start()
        self.addCleanup(server.stop)
        return server

    def client(self, server, fp="pinned"):
        expected = server.identity.fingerprint if fp == "pinned" else fp
        return ShareClient("127.0.0.1", server.port, expected)

    def raw(self, server, method, path, body=b"", headers=None, version="1"):
        """A request the real client would never send; returns (status, json)."""
        conn = http.client.HTTPSConnection(
            "127.0.0.1", server.port, context=session.tls_client_context(), timeout=5
        )
        try:
            conn.putrequest(method, path)
            all_headers = {"Content-Length": str(len(body))}
            if version is not None:
                all_headers["OpenEmux-Share-Version"] = version
            all_headers.update(headers or {})
            for name, value in all_headers.items():
                conn.putheader(name, value)
            conn.endheaders(body)
            response = conn.getresponse()
            return response.status, json.loads(response.read() or b"null")
        finally:
            conn.close()

    def assertShareError(self, code, call, *args):
        with self.assertRaises(ShareError) as caught:
            call(*args)
        self.assertEqual(caught.exception.code, code)
        return caught.exception

    def committed(self, server, nonce=None):
        """An offer posted but not revealed: (offer_id, nonce_s, answer)."""
        nonce = nonce or verification.new_nonce()
        body = {"sender": self.sender.sender(), "commit": verification.commit(nonce), "manifest": manifest()}
        _, answer = self.client(server).request("POST", "/offer", body)
        return answer["offer_id"], nonce, answer

    def revealed(self, server):
        offer_id, _ = self.client(server).offer(self.sender.sender(), manifest())
        return offer_id


class InfoAndPinningTests(SessionTestCase):
    def test_info(self):
        server = self.serve()
        info = self.client(server).info()
        self.assertEqual((info["id"], info["name"], info["compatible"]), (self.receiver.id, "Receiver", True))

    def test_info_answers_without_a_version_header(self):
        server = self.serve()
        status, body = self.raw(server, "GET", "/info", version=None)
        self.assertEqual((status, body["v"]), (200, 1))

    def test_pinned_mismatch_is_refused_before_any_request(self):
        server = self.serve()
        client = self.client(server, fp=self.other.fingerprint)
        self.assertShareError(ErrorCode.FINGERPRINT_MISMATCH, client.info)
        self.assertEqual(server.request_count, 0)

    def test_trust_on_first_use(self):
        server = self.serve()
        client = self.client(server, fp=None)
        client.info()
        self.assertEqual(client.peer_fp, self.receiver.fingerprint)

    def test_unreachable(self):
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()
        self.assertShareError(ErrorCode.UNREACHABLE, ShareClient("127.0.0.1", port).info)

    def test_the_connection_is_closed_on_every_path(self):
        server = self.serve()
        HTTPS = http.client.HTTPSConnection
        with mock.patch.object(HTTPS, "close", autospec=True, side_effect=HTTPS.close) as close:
            self.client(server).info()
            self.assertShareError(ErrorCode.NOT_FOUND, self.client(server).request, "GET", "/nope")
            self.assertShareError(ErrorCode.FINGERPRINT_MISMATCH, self.client(server, self.other.fingerprint).info)
            with mock.patch.object(HTTPS, "getresponse", side_effect=ConnectionResetError("reset")):
                self.assertShareError(ErrorCode.UNREACHABLE, self.client(server).info)
        self.assertEqual(close.call_count, 4)


class VersionTests(SessionTestCase):
    def test_unsupported_version_names_both(self):
        server = self.serve()
        with mock.patch.object(session, "PROTOCOL_VERSION", 2):
            error = self.assertShareError(
                ErrorCode.INCOMPATIBLE_VERSION, self.client(server).request, "POST", "/offer", {}
            )
        self.assertEqual(error.details["peer"], {"min": 2, "max": 2})
        self.assertEqual(error.details["supported"], {"min": 1, "max": 1})

    def test_missing_version(self):
        server = self.serve()
        status, body = self.raw(server, "POST", "/offer", b"{}", version=None)
        self.assertEqual((status, body["error"]), (400, "incompatible_version"))

    def test_client_refuses_an_incompatible_receiver(self):
        server = self.serve()
        info = dict(self.receiver.info(), v=5, vmin=5)
        with mock.patch.object(type(self.receiver), "info", return_value=info):
            error = self.assertShareError(ErrorCode.INCOMPATIBLE_VERSION, self.client(server).info)
        self.assertEqual(error.message, "version 1 vs 5")


class OfferTests(SessionTestCase):
    def test_both_ends_compute_the_same_code(self):
        server = self.serve()
        offer_id, code = self.client(server).offer(self.sender.sender(), manifest())
        [incoming] = self.offers
        self.assertEqual((incoming.offer_id, incoming.code), (offer_id, code))
        self.assertEqual(incoming.sender["fp"], self.sender.fingerprint)
        self.assertEqual(len(offer_id), 22)

    def test_another_certificate_gives_another_code(self):
        nonces = [b"\x01" * 32, b"\x02" * 32]
        codes = []
        for device in (self.receiver, self.other):
            server = self.serve(device)
            with mock.patch.object(verification, "new_nonce", side_effect=list(nonces)):
                _, code = self.client(server).offer(self.sender.sender(), manifest())
            self.assertEqual(self.offers[0].code, code)
            codes.append(code)
            server.stop()
        self.assertNotEqual(codes[0], codes[1])

    def test_bad_commit_discards_the_offer(self):
        server = self.serve()
        offer_id, _, _ = self.committed(server)
        client = self.client(server)
        self.assertShareError(
            ErrorCode.BAD_COMMIT, client.request, "POST", f"/offer/{offer_id}/reveal",
            {"nonce_s": verification.new_nonce().hex()},
        )
        self.assertShareError(ErrorCode.NOT_FOUND, client.poll, offer_id)
        self.assertEqual(self.offers, [])

    def test_reveal_errors(self):
        server = self.serve()
        offer_id, nonce, _ = self.committed(server)
        client = self.client(server)
        path = f"/offer/{offer_id}/reveal"
        self.assertShareError(ErrorCode.BAD_REQUEST, client.request, "POST", path, {"nonce_s": "x"})
        self.assertShareError(ErrorCode.BAD_REQUEST, client.request, "POST", path, [])
        self.assertShareError(ErrorCode.NOT_FOUND, client.request, "POST", "/offer/nope/reveal", {"nonce_s": nonce.hex()})
        self.assertEqual(client.poll(offer_id), {"status": "pending"})
        client.request("POST", path, {"nonce_s": nonce.hex()})
        self.assertShareError(ErrorCode.BAD_REQUEST, client.request, "POST", path, {"nonce_s": nonce.hex()})

    def test_one_pending_offer_at_a_time(self):
        server = self.serve()
        self.committed(server)
        self.assertShareError(ErrorCode.BUSY, self.committed, server)

    def test_expiry(self):
        server = self.serve()
        offer_id, nonce, answer = self.committed(server)
        self.assertEqual(answer["expires_in"], 60)
        self.clock.now += 61
        client = self.client(server)
        self.assertEqual(client.poll(offer_id), {"status": "expired"})
        self.assertShareError(
            ErrorCode.EXPIRED, client.request, "POST", f"/offer/{offer_id}/reveal", {"nonce_s": nonce.hex()}
        )
        self.assertShareError(ErrorCode.EXPIRED, server.answer, offer_id, True)
        self.committed(server)
        self.clock.now += 400
        self.assertShareError(ErrorCode.NOT_FOUND, client.poll, offer_id)

    def test_a_finished_offer_is_kept_from_when_it_finished(self):
        server = self.serve()
        client = self.client(server)
        offer_id = self.revealed(server)
        self.clock.now += 59
        server.answer(offer_id, False)
        self.clock.now += 290
        self.assertEqual(client.poll(offer_id), {"status": "declined"})
        self.clock.now += 20
        self.assertShareError(ErrorCode.NOT_FOUND, client.poll, offer_id)

    def test_accept_and_decline(self):
        server = self.serve()
        client = self.client(server)
        offer_id = self.revealed(server)
        self.assertEqual(client.poll(offer_id), {"status": "pending"})
        items = [{"id": "i1", "action": "send"}, {"id": "i2", "action": "skip", "reason": "user_unchecked"}]
        server.answer(offer_id, True, items)
        self.assertEqual(client.poll(offer_id), {"status": "accepted", "items": items})
        self.assertShareError(ErrorCode.BAD_REQUEST, server.answer, offer_id, False)
        self.assertShareError(ErrorCode.NOT_FOUND, server.answer, "nope", False)
        second = self.revealed(server)
        server.answer(second, False)
        self.assertEqual(client.poll(second), {"status": "declined"})

    def test_cancel_from_the_sender(self):
        server = self.serve()
        client = self.client(server)
        offer_id = self.revealed(server)
        client.cancel(offer_id)
        self.assertEqual(self.cancels, [offer_id])
        self.assertEqual(client.poll(offer_id), {"status": "cancelled"})
        self.assertShareError(ErrorCode.NOT_FOUND, client.cancel, "nope")

    def test_cancel_from_the_receiver(self):
        server = self.serve()
        client = self.client(server)
        offer_id = self.revealed(server)
        server.answer(offer_id, True, [{"id": "i1", "action": "send"}])
        server.cancel(offer_id)
        server.cancel("nope")
        self.assertEqual(client.poll(offer_id), {"status": "cancelled"})
        self.assertShareError(ErrorCode.CANCELLED, client.request, "PUT", f"/file/{offer_id}/i1", {})

    def test_cancel_leaves_a_closed_offer_alone(self):
        server = self.serve()
        client = self.client(server)
        offer_id = self.revealed(server)
        server.answer(offer_id, False)
        client.cancel(offer_id)
        server.cancel(offer_id)
        self.assertEqual(self.cancels, [])
        self.assertEqual(client.poll(offer_id), {"status": "declined"})
        expired, _, _ = self.committed(server)
        self.clock.now += 61
        client.cancel(expired)
        self.assertEqual((self.cancels, client.poll(expired)), ([], {"status": "expired"}))

    def test_cancel_without_a_listener(self):
        server = self.serve()
        server.on_cancel = None
        server.on_offer = None
        offer_id = self.revealed(server)
        self.client(server).cancel(offer_id)
        self.assertEqual(self.client(server).poll(offer_id)["status"], "cancelled")

    def test_malformed_offer(self):
        server = self.serve()
        self.assertShareError(ErrorCode.BAD_REQUEST, self.client(server).request, "POST", "/offer", {"x": 1})


class FileTests(SessionTestCase):
    def accepted(self, server):
        offer_id = self.revealed(server)
        server.answer(offer_id, True, [{"id": "i1", "action": "send"}, {"id": "i2", "action": "skip"}, "junk"])
        return offer_id

    def test_not_implemented_yet(self):
        server = self.serve()
        offer_id = self.accepted(server)
        self.assertShareError(ErrorCode.NOT_IMPLEMENTED, self.client(server).request, "PUT", f"/file/{offer_id}/i1", {})

    def test_only_items_accepted_for_upload(self):
        server = self.serve()
        client = self.client(server)
        offer_id = self.revealed(server)
        self.assertShareError(ErrorCode.BAD_REQUEST, client.request, "PUT", f"/file/{offer_id}/i1", {})
        server.answer(offer_id, True, [{"id": "i1", "action": "send"}, {"id": "i2", "action": "skip"}])
        self.assertShareError(ErrorCode.BAD_REQUEST, client.request, "PUT", f"/file/{offer_id}/i2", {})

    def test_declined(self):
        server = self.serve()
        offer_id = self.revealed(server)
        server.answer(offer_id, False)
        self.assertShareError(ErrorCode.DECLINED, self.client(server).request, "PUT", f"/file/{offer_id}/i1", {})

    def test_handler_hook(self):
        server = self.serve()
        calls = []
        server.file_handler = lambda offer, item_id, body, length: calls.append((offer.offer_id, item_id))
        offer_id = self.accepted(server)
        status, body = self.client(server).request("PUT", f"/file/{offer_id}/i1", {})
        self.assertEqual((status, body, calls), (204, None, [(offer_id, "i1")]))

    def test_an_upload_keeps_an_accepted_offer(self):
        server = self.serve()
        server.file_handler = lambda offer, item_id, body, length: None
        client = self.client(server)
        offer_id = self.accepted(server)
        for _ in range(3):
            self.clock.now += 250
            self.assertEqual(client.request("PUT", f"/file/{offer_id}/i1", {})[0], 204)
        self.clock.now += 301
        self.assertShareError(ErrorCode.NOT_FOUND, client.poll, offer_id)

    def test_a_crashing_handler_is_internal(self):
        server = self.serve()
        server.file_handler = mock.Mock(side_effect=RuntimeError("bug"))
        offer_id = self.accepted(server)
        with self.assertLogs(session.logger, "ERROR"):
            self.assertShareError(ErrorCode.INTERNAL, self.client(server).request, "PUT", f"/file/{offer_id}/i1", {})


class FileUploadTests(SessionTestCase):
    """``ShareClient.put_file`` against the real server (issue #588)."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "Game.nes"
        self.data = bytes(range(256)) * 2048  # two chunks of 256 KiB
        self.path.write_bytes(self.data)

    def accepted(self, server):
        offer_id = self.revealed(server)
        server.answer(offer_id, True, [{"id": "i1", "action": "send"}])
        return offer_id

    def receiving(self, server, read_size=65536):
        received = []

        def handler(offer, item_id, body, length):
            chunks = []
            while True:
                chunk = body.read(read_size)
                if not chunk:
                    break
                chunks.append(chunk)
            received.append((item_id, length, b"".join(chunks), body.read()))

        server.file_handler = handler
        return received

    def test_the_file_arrives_whole_in_chunks(self):
        server = self.serve()
        received = self.receiving(server)
        offer_id = self.accepted(server)
        chunks = []
        self.client(server).put_file(offer_id, "i1", self.path, len(self.data), chunks.append)
        self.assertEqual(received, [("i1", len(self.data), self.data, b"")])
        self.assertEqual(chunks, [session.FILE_CHUNK_BYTES] * 2)

    def test_a_reader_never_reads_past_the_length(self):
        server = self.serve()
        received = self.receiving(server, read_size=-1)
        offer_id = self.accepted(server)
        self.client(server).put_file(offer_id, "i1", self.path, 10)
        self.assertEqual(received[0][2], self.data[:10])

    def test_an_error_answer(self):
        server = self.serve()
        offer_id = self.accepted(server)
        err = self.assertShareError(ErrorCode.NOT_IMPLEMENTED, self.client(server).put_file,
                                    offer_id, "i1", self.path, 4)
        self.assertEqual(err.message, "file transfer is not implemented")

    def test_an_error_answer_without_a_body(self):
        server = self.serve()
        offer_id = self.accepted(server)
        with mock.patch.object(session.json, "loads", side_effect=ValueError("bad")):
            self.assertShareError(ErrorCode.INTERNAL, self.client(server).put_file, offer_id, "i1", self.path, 4)

    def test_a_file_shorter_or_missing_is_source_changed(self):
        server = self.serve()
        offer_id = self.accepted(server)
        client = self.client(server)
        self.assertShareError(ErrorCode.SOURCE_CHANGED, client.put_file, offer_id, "i1", self.path,
                              len(self.data) + 1)
        self.assertShareError(ErrorCode.SOURCE_CHANGED, client.put_file, offer_id, "i1",
                              self.path.with_name("gone"), 4)

    def test_a_cut_connection_is_unreachable(self):
        server = self.serve()
        offer_id = self.accepted(server)
        with mock.patch.object(http.client.HTTPSConnection, "send", side_effect=BrokenPipeError("cut")):
            self.assertShareError(ErrorCode.UNREACHABLE, self.client(server).put_file, offer_id, "i1",
                                  self.path, 4)

    def test_a_missing_content_length(self):
        server = self.serve()
        server.file_handler = mock.Mock()
        offer_id = self.accepted(server)
        status, body = self.raw(server, "PUT", f"/file/{offer_id}/i1", headers={"Content-Length": "x"})
        self.assertEqual((status, body["error"]), (400, ErrorCode.BAD_REQUEST))
        server.file_handler.assert_not_called()


class RequestLimitTests(SessionTestCase):
    def test_oversized_body(self):
        server = self.serve()
        status, body = self.raw(server, "POST", "/offer", b" " * (1024 * 1024 + 1))
        self.assertEqual((status, body["error"]), (413, "too_large"))

    def test_body_too_large_to_drain_is_left_unread(self):
        server = self.serve()
        status, body = self.raw(server, "POST", "/offer", b"", headers={"Content-Length": str(5 * 1024 * 1024)})
        self.assertEqual((status, body["error"]), (413, "too_large"))

    def test_bad_content_length(self):
        server = self.serve()
        status, body = self.raw(server, "POST", "/offer", b"", headers={"Content-Length": "abc"})
        self.assertEqual((status, body["error"]), (400, "bad_request"))

    def test_non_ascii_content_length(self):
        server = self.serve()
        status, body = self.raw(server, "POST", "/offer", b"", headers={"Content-Length": "\u00b2"})
        self.assertEqual((status, body["error"]), (400, "bad_request"))

    def test_non_ascii_version_header(self):
        server = self.serve()
        status, body = self.raw(server, "POST", "/offer", b"", version="\u00b2")
        self.assertEqual((status, body["error"]), (400, "incompatible_version"))

    def test_deeply_nested_body_is_bad_request(self):
        server = self.serve()
        status, body = self.raw(server, "POST", "/offer", b"[" * 200000)
        self.assertEqual((status, body["error"]), (400, "bad_request"))

    def test_not_json(self):
        server = self.serve()
        status, body = self.raw(server, "POST", "/offer", b"\xff{")
        self.assertEqual((status, body["error"]), (400, "bad_request"))

    def test_truncated_body_is_drained_as_far_as_it_goes(self):
        handler = session._Handler.__new__(session._Handler)
        handler.headers = {"Content-Length": "10"}
        handler.rfile = io.BytesIO(b"abc")
        handler._body_read = False
        handler._discard_body()
        self.assertTrue(handler.close_connection)
        self.assertEqual(handler.rfile.read(), b"")

    def test_unknown_route(self):
        server = self.serve()
        client = self.client(server)
        self.assertShareError(ErrorCode.NOT_FOUND, client.request, "GET", "/nope?x=1")
        self.assertShareError(ErrorCode.NOT_FOUND, client.request, "PUT", "/file/x/y/z", {})

    def test_query_string_is_ignored(self):
        server = self.serve()
        self.assertEqual(self.client(server).request("GET", "/info?x=1")[0], 200)


class ClientParsingTests(SessionTestCase):
    def client_answering(self, *answers):
        client = ShareClient("127.0.0.1", 1, "f" * 64)
        client.info = mock.Mock()
        client.request = mock.Mock(side_effect=list(answers))
        return client

    def test_malformed_offer_answer(self):
        good_nonce = "0" * 64
        for answer in (
            None, {"offer_id": 1}, {"offer_id": "x", "nonce_r": "zz"},
            {"offer_id": "x", "nonce_r": good_nonce},
            {"offer_id": "a" * 21 + "\n", "nonce_r": good_nonce},
            {"offer_id": "a" * 20 + "/x", "nonce_r": good_nonce},
        ):
            with self.subTest(answer=answer):
                client = self.client_answering((201, answer))
                self.assertShareError(ErrorCode.BAD_REQUEST, client.offer, self.sender.sender(), manifest())

    def test_malformed_poll_answer(self):
        for answer in (None, {"status": 5}):
            with self.subTest(answer=answer):
                client = self.client_answering((200, answer))
                self.assertShareError(ErrorCode.BAD_REQUEST, client.poll, "x")

    def test_error_answer_that_is_not_json(self):
        class Reply:
            status = 502

            def read(self, size):
                return b"<html>bad gateway</html>"

        conn = mock.Mock()
        conn.getresponse.return_value = Reply()
        client = ShareClient("127.0.0.1", 1)
        client._connect = mock.Mock(return_value=conn)
        self.assertShareError(ErrorCode.INTERNAL, client.request, "GET", "/info")
        conn.close.assert_called_once()

    def test_empty_success_answer(self):
        class Reply:
            status = 204

            def read(self, size):
                return b""

        conn = mock.Mock()
        conn.getresponse.return_value = Reply()
        client = ShareClient("127.0.0.1", 1)
        client._connect = mock.Mock(return_value=conn)
        self.assertEqual(client.request("POST", "/cancel/x"), (204, None))


class LifecycleTests(SessionTestCase):
    def test_nothing_listens_after_stop(self):
        server = self.serve()
        port = server.port
        self.assertTrue(server.listening)
        self.assertEqual(server.start(), port)
        server.stop()
        server.stop()
        self.assertFalse(server.listening)
        assert_nothing_listens(self, port)

    def test_busy_preferred_port_falls_back(self):
        blocker = socket.socket()
        blocker.bind(("127.0.0.1", 0))
        blocker.listen()
        self.addCleanup(blocker.close)
        busy = blocker.getsockname()[1]
        server = ShareServer(self.receiver, host="127.0.0.1", port=busy)
        self.addCleanup(server.stop)
        self.assertNotEqual(server.start(), busy)
        self.assertEqual(server.preferred_port, busy)

    def test_a_failed_handshake_is_dropped_quietly(self):
        server = self.serve()
        with self.assertLogs(session.logger, "DEBUG") as logs:
            with socket.create_connection(("127.0.0.1", server.port)) as plain:
                plain.sendall(b"GET /info HTTP/1.1\r\n\r\n")
                try:
                    plain.recv(1024)
                except ConnectionResetError:
                    pass
            self.assertTrue(server.listening)
            self.client(server).info()
        self.assertTrue(any("dropped" in line for line in logs.output))

    def test_tls_below_1_3_is_refused(self):
        server = self.serve()
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        context.maximum_version = ssl.TLSVersion.TLSv1_2
        with socket.create_connection(("127.0.0.1", server.port)) as plain:
            with self.assertRaises((ssl.SSLError, ConnectionError)):
                context.wrap_socket(plain).close()


if __name__ == "__main__":
    unittest.main()
