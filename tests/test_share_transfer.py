"""The transfer facade of ``ShareService`` and a real desktop-to-desktop run (#588)."""

import hashlib
import io
import os
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from openemux.core.config import ConfigManager
from openemux.core.cores import CoreCatalog
from openemux.core.share import send as send_module
from openemux.core.share.manifest import BuiltManifest, build_manifest
from openemux.core.share.protocol import ErrorCode, ShareError
from openemux.core.share.service import ShareService
from openemux.core.share.session import IncomingOffer, ShareServer
from tests.share_fixtures import (
    PNG_BYTES,
    FakeConfig,
    core_file,
    make_catalog,
    temp_library,
)
from tests.test_share_service import FakeDiscovery, FakeServer


class RecordingServer(FakeServer):
    def __init__(self, identity, answer_error=None, **kwargs):
        super().__init__(identity, **kwargs)
        self.answer_error = answer_error

    def answer(self, *args):
        if self.answer_error is not None:
            raise self.answer_error
        super().answer(*args)


def wait_for(predicate, timeout=10.0):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("timed out")
        time.sleep(0.01)


class ServiceFacadeTests(unittest.TestCase):
    def setUp(self):
        self.lib = temp_library(self)
        self.config = ConfigManager(config_file=self.lib.root / "home" / "config.yaml")
        self.config.set_roms_path(self.lib.roms)
        self.catalog = make_catalog(self.lib.root / "cores", {"snes9x": ("Snes9x", "1.62.3")})
        self.log = []
        self.answer_error = None

    def make(self, **kwargs):
        def server_factory(identity, **kw):
            self.server = RecordingServer(identity, answer_error=self.answer_error, log=self.log, **kw)
            return self.server

        def discovery_factory(identity, port, **kw):
            return FakeDiscovery(identity, port, log=self.log, **kw)

        kwargs.setdefault("catalog", self.catalog)
        service = ShareService(self.config, server_factory=server_factory,
                               discovery_factory=discovery_factory, **kwargs)
        service.start()
        self.addCleanup(service.stop)
        return service

    def offer(self, size=3):
        manifest = {"games": [{"id": "g1", "console": "SFC", "title": "Game", "items": [
            {"id": "r", "kind": "rom", "name": "Game.sfc", "size": size, "mtime": 1},
        ]}], "total_size": size, "file_count": 1}
        return IncomingOffer("offer1", {}, manifest, "123456")

    def test_prepare_receive_uses_the_library_paths(self):
        service = self.make()
        with mock.patch.object(service.config, "get_states_dir", return_value=self.lib.states):
            plan = service.prepare_receive(self.offer())
        self.assertEqual(plan.decisions()[0].target, self.lib.roms / "SFC" / "Game.sfc")

    def test_accept_answers_and_routes_the_uploads(self):
        service = self.make()
        plan = service.prepare_receive(self.offer(), states_dir=self.lib.states)
        done = []
        transfer = service.accept("offer1", plan, watchdog=False, on_done=done.append)
        self.assertEqual(self.server.calls, [("answer", "offer1", True, [{"id": "r", "action": "send"}])])
        offer = SimpleNamespace(offer_id="offer1")
        service._route_file(offer, "r", io.BytesIO(b"abc"), 3)
        self.assertEqual((self.lib.roms / "SFC" / "Game.sfc").read_bytes(), b"abc")
        self.assertEqual(done[0]["status"], "done")
        self.assertEqual(transfer.status, "done")
        with self.assertRaises(ShareError) as caught:
            service._route_file(offer, "r", None, 3)
        self.assertEqual(caught.exception.code, ErrorCode.BAD_REQUEST)

    def test_accept_refuses_without_space_and_answers_nothing(self):
        service = self.make()
        plan = service.prepare_receive(self.offer(), states_dir=self.lib.states)
        with mock.patch.object(type(plan), "space_check", return_value=[
            {"path": "/x", "needed": 9, "free": 1, "ok": False}, {"path": "/y", "needed": 1, "free": 9, "ok": True},
        ]):
            with self.assertRaises(ShareError) as caught:
                service.accept("offer1", plan)
        self.assertEqual(caught.exception.code, ErrorCode.TOO_LARGE)
        self.assertEqual(caught.exception.details, {"space": [{"path": "/x", "needed": 9, "free": 1, "ok": False}]})
        self.assertEqual(self.server.calls, [])

    def test_an_answer_that_fails_forgets_the_transfer(self):
        self.answer_error = ShareError(ErrorCode.EXPIRED)
        service = self.make()
        plan = service.prepare_receive(self.offer(), states_dir=self.lib.states)
        with self.assertRaises(ShareError):
            service.accept("offer1", plan)
        self.assertEqual(service._take_incoming(), [])

    def test_cancels_reach_the_transfer(self):
        cancels = []
        service = self.make()
        service.on_cancel = cancels.append
        plan = service.prepare_receive(self.offer(), states_dir=self.lib.states)
        done = []
        service.accept("offer1", plan, on_done=done.append)
        service._cancelled_by_sender("offer1")
        self.assertEqual((done[0]["status"], cancels), ("cancelled", ["offer1"]))
        service.accept("offer1", plan)
        service.cancel("offer1")
        self.assertIn(("cancel", "offer1"), self.server.calls)
        service.on_cancel = None
        service._cancelled_by_sender("unknown")

    def test_stop_cancels_what_is_still_receiving(self):
        service = self.make()
        plan = service.prepare_receive(self.offer(), states_dir=self.lib.states)
        transfer = service.accept("offer1", plan, watchdog=False)
        service.stop()
        self.assertEqual(transfer.status, "cancelled")
        service._aborted_here("offer1")

    def test_stopped_service_refuses_transfers(self):
        service = ShareService(self.config, catalog=self.catalog)
        for call in (lambda: service.send(None, None), lambda: service.accept("o", None)):
            with self.assertRaises(ShareError) as caught:
                call()
            self.assertEqual(caught.exception.code, ErrorCode.UNAVAILABLE)

    def test_send_starts_an_outgoing_transfer(self):
        clients = []

        class Client:
            def __init__(self, host, port, fp):
                clients.append((host, port, fp))

            def offer(self, sender, manifest):
                raise ShareError(ErrorCode.UNREACHABLE)

        done = threading.Event()
        service = self.make(client_factory=Client)
        peer = SimpleNamespace(addresses=("10.0.0.2",), port=53319, fp="ab" * 32)
        built = BuiltManifest({"games": [], "total_size": 0, "file_count": 0})
        with self.assertLogs(send_module.logger, "WARNING"):
            transfer = service.send(peer, built, on_done=lambda result: done.set())
            self.assertTrue(done.wait(5))
        self.assertEqual(clients, [("10.0.0.2", 53319, "ab" * 32)])
        self.assertEqual(transfer.result["error"], ErrorCode.UNREACHABLE)

    def test_the_default_catalog(self):
        service = ShareService(self.config)
        self.assertIsInstance(service.catalog, CoreCatalog)
        self.assertIs(service.catalog, service.catalog)


class LoopbackTransferTests(unittest.TestCase):
    """Two real services on 127.0.0.1 by manual address: real TLS, no discovery."""

    CORES = {"mednafen_psx": ("Beetle PSX", "0.9.44.1"), "snes9x": ("Snes9x", "1.62.3")}

    def setUp(self):
        self.lib = temp_library(self)
        self.sender = self.side("alice")
        self.receiver = self.side("bob")

    def side(self, name):
        root = self.lib.root / name
        config = ConfigManager(config_file=root / "home" / "config.yaml")
        catalog = make_catalog(root / "cores", self.CORES)
        offers = []

        def server_factory(identity, **kwargs):
            kwargs["on_offer"] = offers.append
            return ShareServer(identity, host="127.0.0.1", port=0, **kwargs)

        def discovery_factory(identity, port, **kwargs):
            return FakeDiscovery(identity, port, log=[], **kwargs)

        service = ShareService(config, server_factory=server_factory, discovery_factory=discovery_factory,
                               catalog=catalog)
        service.start()
        self.addCleanup(service.stop)
        return SimpleNamespace(root=root, roms=root / "roms", states=root / "states", service=service,
                               catalog=catalog, offers=offers)

    def write(self, side, relative, data, mtime=1700000000):
        path = side.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        os.utime(path, (mtime, mtime))
        return path

    def library(self):
        a = self.sender
        self.write(a, "roms/PS/Quest (Track 1).bin", os.urandom(700_000))
        self.write(a, "roms/PS/Quest (Track 2).bin", os.urandom(30_000))
        cue = self.write(a, "roms/PS/Quest.cue",
                         b'FILE "Quest (Track 1).bin" BINARY\nFILE "Quest (Track 2).bin" BINARY\n')
        self.write(a, "roms/PS/Quest.srm", b"battery" * 100, mtime=1700000500)
        self.write(a, "states/PS/Quest.state1", b"compatible state", mtime=1700000600)
        self.write(a, "states/PS/Snes9x/Quest.state2", b"other core's state", mtime=1700000600)
        self.write(a, "states/PS/Unknown/Quest.state3", b"incompatible state", mtime=1700000600)
        self.write(a, "roms/PS/covers/Quest.png", PNG_BYTES)
        sfc = self.write(a, "roms/SFC/Plain.sfc", os.urandom(4096))
        return [{"name": "Quest", "path": str(cue), "console": "PS"},
                {"name": "Plain", "path": str(sfc), "console": "SFC"}]

    def run_transfer(self, roms):
        a, b = self.sender, self.receiver
        built = build_manifest(
            roms, roms_dir=a.roms, states_dir=a.states, catalog=a.catalog, config=FakeConfig(),
            resolve_core=lambda console, path: f"/x/{core_file('mednafen_psx')}" if console == "PS" else None,
        )
        received, sent = [], []
        accepted = threading.Event()

        def accept_when_offered():
            wait_for(lambda: len(b.offers) > len(self.handled))
            offer = b.offers[-1]
            self.handled.append(offer)
            plan = b.service.prepare_receive(offer, roms_dir=b.roms, states_dir=b.states)
            self.answers.append({e["id"]: e.get("reason", "send") for e in plan.answer_items()})
            b.service.accept(offer.offer_id, plan, on_done=received.append)
            accepted.set()

        threading.Thread(target=accept_when_offered, daemon=True).start()
        peer = SimpleNamespace(addresses=("127.0.0.1",), port=b.service.server.port,
                               fp=b.service.identity.fingerprint)
        a.service.send(peer, built, on_done=sent.append)
        wait_for(lambda: sent and (received or sent[0]["status"] != "done"), timeout=30)
        return built, sent[0], received[0] if received else None

    def name_of(self, built, item_id):
        return next(i["name"] for g in built.manifest["games"] for i in g["items"] if i["id"] == item_id)

    def digest(self, path):
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()

    def test_a_multi_file_game_arrives_complete(self):
        self.handled, self.answers = [], []
        roms = self.library()
        built, sent, received = self.run_transfer(roms)
        self.assertEqual((sent["status"], received["status"]), ("done", "done"))
        reasons = {self.name_of(built, k): v for k, v in self.answers[0].items()}
        self.assertEqual(reasons["Quest.state2"], "send")  # Snes9x is installed with that version
        self.assertEqual(reasons["Quest.state3"], "incompatible_state")
        self.assertNotIn(
            next(k for k, v in self.answers[0].items() if v == "incompatible_state"), sent["sent"]
        )
        a, b = self.sender, self.receiver
        expected = {
            "roms/PS/Quest/Quest.cue": "roms/PS/Quest.cue",
            "roms/PS/Quest/Quest (Track 1).bin": "roms/PS/Quest (Track 1).bin",
            "roms/PS/Quest/Quest (Track 2).bin": "roms/PS/Quest (Track 2).bin",
            "roms/PS/Quest/Quest.srm": "roms/PS/Quest.srm",
            "states/PS/Quest.state1": "states/PS/Quest.state1",
            "states/PS/Quest.state2": "states/PS/Snes9x/Quest.state2",
            "roms/PS/covers/Quest.png": "roms/PS/covers/Quest.png",
            "roms/SFC/Plain.sfc": "roms/SFC/Plain.sfc",
        }
        arrived = sorted(str(p.relative_to(b.root)) for p in b.root.rglob("*")
                         if p.is_file() and p.parts[len(b.root.parts)] in ("roms", "states"))
        self.assertEqual(arrived, sorted(expected))
        for there, here in expected.items():
            self.assertEqual(self.digest(b.root / there), self.digest(a.root / here), there)
        self.assertEqual(os.stat(b.root / "roms/PS/Quest/Quest.srm").st_mtime, 1700000500)

        # Again: the ROMs are already there, and the saves follow their dates.
        self.write(b, "roms/PS/Quest/Quest.srm", b"played more here", mtime=1800000000)
        self.write(a, "states/PS/Quest.state1", b"newer state there", mtime=1800000000)
        built, sent, received = self.run_transfer(roms)
        reasons = {self.name_of(built, k): v for k, v in self.answers[1].items()}
        self.assertEqual(reasons["Quest.cue"], "exists_skip")
        self.assertEqual(reasons["Plain.sfc"], "exists_skip")
        self.assertEqual(reasons["Quest.srm"], "exists_skip")
        self.assertEqual(reasons["Quest.state1"], "send")
        self.assertEqual(received["replaced"], [str(b.root / "states/PS/Quest.state1")])
        self.assertEqual((b.root / "roms/PS/Quest/Quest.srm").read_bytes(), b"played more here")
        self.assertEqual((b.root / "states/PS/Quest.state1").read_bytes(), b"newer state there")


if __name__ == "__main__":
    unittest.main()
