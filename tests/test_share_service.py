import socket
import stat
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from openemux.core.config import ConfigManager
from openemux.core.share import service as service_module
from openemux.core.share.discovery import BeaconTransport, Discovery
from openemux.core.share.protocol import BEACON_GROUP, ErrorCode, ShareError
from openemux.core.share.service import ShareService
from openemux.core.share.session import ShareClient, ShareServer
from tests.platform_marks import posix_only
from tests.test_share_session import assert_nothing_listens


class FakeServer:
    def __init__(self, identity, on_offer=None, on_cancel=None, error=None, log=None):
        self.identity, self.error, self.log = identity, error, log
        self.port = 4242
        self.calls = []

    def start(self):
        self.log.append("server.start")
        if self.error:
            raise self.error
        return self.port

    def stop(self):
        self.log.append("server.stop")

    def answer(self, *args):
        self.calls.append(("answer",) + args)

    def cancel(self, *args):
        self.calls.append(("cancel",) + args)


class FakeDiscovery:
    def __init__(self, identity, port, on_change=None, error=None, log=None):
        self.port, self.error, self.log = port, error, log

    def start(self):
        self.log.append("discovery.start")
        if self.error:
            raise self.error

    def stop(self):
        self.log.append("discovery.stop")

    def peers(self):
        return ["peer"]

    def transport_status(self):
        return {"beacon": "running"}


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = ConfigManager(config_file=Path(self.tmp.name) / "config.yaml")
        self.log = []

    def make(self, server_error=None, discovery_error=None):
        def server_factory(identity, **kwargs):
            self.server = FakeServer(identity, error=server_error, log=self.log, **kwargs)
            return self.server

        def discovery_factory(identity, port, **kwargs):
            return FakeDiscovery(identity, port, error=discovery_error, log=self.log, **kwargs)

        return ShareService(self.config, server_factory=server_factory, discovery_factory=discovery_factory)

    def test_start_and_stop_order(self):
        service = self.make()
        self.assertEqual(service.start(), 4242)
        self.assertEqual(service.start(), 4242)
        self.assertTrue(service.running)
        self.assertEqual(self.log, ["server.start", "discovery.start"])
        self.assertEqual(service.peers(), ["peer"])
        self.assertEqual(service.transport_status(), {"beacon": "running"})
        service.answer("o", True, [])
        service.cancel("o")
        self.assertEqual(self.server.calls, [("answer", "o", True, []), ("cancel", "o")])
        service.stop()
        service.stop()
        self.assertEqual(self.log[2:], ["discovery.stop", "server.stop"])
        self.assertFalse(service.running)
        self.assertEqual((service.peers(), service.transport_status()), ([], {}))
        with self.assertRaises(ShareError) as caught:
            service.answer("o", True)
        self.assertEqual(caught.exception.code, ErrorCode.UNAVAILABLE)
        service.cancel("o")
        self.assertEqual(len(self.server.calls), 2)

    def test_identity_lives_beside_the_config(self):
        self.config.set_share_device_name("Den")
        service = self.make()
        service.start()
        self.addCleanup(service.stop)
        self.assertEqual(service.identity.name, "Den")
        self.assertTrue((Path(self.tmp.name) / "share" / "key.pem").is_file())
        first = (service.identity.id, service.identity.fingerprint)
        service.stop()
        service.start()
        self.assertEqual((service.identity.id, service.identity.fingerprint), first)

    @posix_only("owner-only modes on the key and its directory; NTFS has no such bits")
    def test_identity_files_are_owner_only(self):
        service = self.make()
        service.start()
        self.addCleanup(service.stop)
        share_dir = Path(self.tmp.name) / "share"
        self.assertEqual(stat.S_IMODE(share_dir.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((share_dir / "key.pem").stat().st_mode), 0o600)

    def test_server_failure_leaves_nothing_running(self):
        service = self.make(server_error=OSError("no port"))
        with self.assertRaises(OSError):
            service.start()
        self.assertEqual(self.log, ["server.start", "server.stop"])
        self.assertFalse(service.running)

    def test_discovery_failure_stops_the_server(self):
        service = self.make(discovery_error=RuntimeError("boom"))
        with self.assertRaises(RuntimeError):
            service.start()
        self.assertEqual(self.log, ["server.start", "discovery.start", "discovery.stop", "server.stop"])
        self.assertFalse(service.running)

    def test_unavailable_without_cryptography(self):
        service = self.make()
        with mock.patch.object(service_module, "availability", return_value={"share": "unavailable:cryptography"}):
            with self.assertRaises(ShareError) as caught:
                service.start()
        self.assertEqual(caught.exception.code, ErrorCode.UNAVAILABLE)
        self.assertEqual(caught.exception.message, "unavailable:cryptography")
        self.assertEqual(self.log, [])

    def test_real_defaults(self):
        service = ShareService(self.config)
        self.assertIs(service.server_factory, ShareServer)
        self.assertIs(service.discovery_factory, Discovery)
        self.assertEqual(service.share_dir, Path(self.tmp.name) / "share")


def multicast_loopback_works(port):
    """Whether a datagram to the beacon group on 127.0.0.1 comes back here."""
    receiver = sender = None
    try:
        receiver = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        receiver.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        receiver.bind(("", port))
        receiver.setsockopt(
            socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP,
            socket.inet_aton(BEACON_GROUP) + socket.inet_aton("127.0.0.1"),
        )
        receiver.settimeout(1.0)
        sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sender.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton("127.0.0.1"))
        sender.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
        sender.sendto(b"probe", (BEACON_GROUP, port))
        return receiver.recvfrom(64)[0] == b"probe"
    except OSError:
        return False
    finally:
        for sock in (receiver, sender):
            if sock is not None:
                sock.close()


class LoopbackIntegrationTests(unittest.TestCase):
    """Two real services on 127.0.0.1: real beacon, real TLS, no mDNS."""

    PORT = 53398

    def setUp(self):
        if not multicast_loopback_works(self.PORT):
            self.skipTest("multicast on the loopback interface is not available here")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def service(self, name):
        root = Path(self.tmp.name) / name
        config = ConfigManager(config_file=root / "config.yaml")
        config.set_share_device_name(name)
        offers = []

        def server_factory(identity, **kwargs):
            kwargs["on_offer"] = offers.append
            return ShareServer(identity, host="127.0.0.1", port=0, **kwargs)

        def discovery_factory(identity, port, **kwargs):
            beacon = BeaconTransport(port=self.PORT, interval=0.2, interfaces=["127.0.0.1"])
            return Discovery(identity, port, transports=[beacon], **kwargs)

        service = ShareService(config, server_factory=server_factory, discovery_factory=discovery_factory)
        service.offers = offers
        service.start()
        self.addCleanup(service.stop)
        return service

    def wait_for_peer(self, service, name, timeout=5.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            found = [peer for peer in service.peers() if peer.name == name]
            if found:
                return found[0]
            time.sleep(0.05)
        self.fail(f"{name} never appeared")

    def test_discover_and_handshake(self):
        alice, bob = self.service("Alice"), self.service("Bob")
        peer = self.wait_for_peer(alice, "Bob")
        self.assertEqual(peer.paths, {"beacon"})
        self.assertEqual(peer.fp, bob.identity.fingerprint)
        self.wait_for_peer(bob, "Alice")
        client = ShareClient(peer.addresses[0], peer.port, peer.fp)
        manifest = {"games": [], "total_size": 0, "file_count": 0}
        offer_id, code = client.offer(alice.identity.sender(), manifest)
        self.assertEqual([(o.offer_id, o.code) for o in bob.offers], [(offer_id, code)])
        port = bob.server.port
        bob.stop()
        assert_nothing_listens(self, port)
        deadline = time.monotonic() + 3
        while alice.peers() and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertEqual(alice.peers(), [])


if __name__ == "__main__":
    unittest.main()
