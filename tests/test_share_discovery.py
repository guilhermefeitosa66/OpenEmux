import socket
import sys
import threading
import time
import types
import unittest
from enum import Enum
from unittest import mock

from openemux.core.share import discovery, protocol
from openemux.core.share.discovery import (
    BeaconTransport,
    Discovery,
    MdnsTransport,
    PeerList,
    Transport,
)

ID_A, ID_B = "a" * 32, "b" * 32
FP_A, FP_B, FP_X = "1" * 64, "2" * 64, "3" * 64


def announcement(device_id=ID_B, fp=FP_B, name="B", v=1, vmin=1, port=4000):
    return {
        "id": device_id, "name": name, "platform": "desktop", "v": v, "vmin": vmin,
        "port": port, "fp": fp, "compatible": protocol.is_compatible(vmin, v),
    }


def wait_until(predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return predicate()


class FakeIdentity:
    def __init__(self, device_id, fp, name):
        self.id, self.fingerprint, self.name = device_id, fp, name

    def announcement(self, port):
        return {"id": self.id, "name": self.name, "platform": "desktop", "v": 1, "vmin": 1,
                "port": port, "fp": self.fingerprint}


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


class LocalAddressTests(unittest.TestCase):
    def test_without_ifaddr(self):
        with mock.patch.dict(sys.modules, {"ifaddr": None}):
            self.assertEqual(discovery.local_ipv4_addresses(), [])

    def test_ipv4_only_no_loopback_no_duplicates(self):
        ip = types.SimpleNamespace
        adapters = [
            ip(ips=[ip(ip="127.0.0.1"), ip(ip="192.168.1.2"), ip(ip=("fe80::1", 0, 2))]),
            ip(ips=[ip(ip="192.168.1.2"), ip(ip="10.0.0.3")]),
        ]
        fake = types.SimpleNamespace(get_adapters=lambda: adapters)
        with mock.patch.dict(sys.modules, {"ifaddr": fake}):
            self.assertEqual(discovery.local_ipv4_addresses(), ["192.168.1.2", "10.0.0.3"])


class PeerListTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.changes = 0
        self.peers = PeerList(ID_A, clock=self.clock, on_change=self.changed)

    def changed(self):
        self.changes += 1

    def test_own_id_is_ignored(self):
        self.peers.seen("beacon", announcement(ID_A, FP_A), "10.0.0.1")
        self.assertEqual(self.peers.peers(), [])
        self.assertEqual(self.changes, 0)

    def test_both_paths_merge_into_one_peer(self):
        self.peers.seen("mdns", announcement(), "fe80::2")
        self.peers.seen("beacon", announcement(), "10.0.0.2")
        self.peers.seen("mdns", announcement(), "10.0.0.2")
        [peer] = self.peers.peers()
        self.assertEqual(peer.paths, {"mdns", "beacon"})
        self.assertEqual(peer.addresses, ("10.0.0.2", "fe80::2"))
        self.assertEqual(peer.key, (ID_B, FP_B))

    def test_repeats_do_not_signal_a_change(self):
        self.peers.seen("beacon", announcement(), "10.0.0.2")
        self.peers.seen("beacon", announcement(), "10.0.0.2")
        self.peers.seen("beacon", announcement())
        self.assertEqual(self.changes, 1)
        self.peers.seen("beacon", announcement(name="Renamed"))
        self.assertEqual(self.changes, 2)
        self.assertEqual(self.peers.peers()[0].name, "Renamed")

    def test_same_id_other_certificate_is_a_second_entry(self):
        self.peers.seen("mdns", announcement())
        self.peers.seen("beacon", announcement(fp=FP_X))
        self.assertEqual(len(self.peers.peers()), 2)
        self.peers.gone("beacon", ID_B, FP_X)
        self.assertEqual([peer.fp for peer in self.peers.peers()], [FP_B])

    def test_gone_without_fingerprint_drops_the_path_everywhere(self):
        self.peers.seen("mdns", announcement())
        self.peers.seen("mdns", announcement(fp=FP_X))
        self.peers.gone("mdns", ID_B)
        self.assertEqual(self.peers.peers(), [])

    def test_gone_for_an_unknown_path_changes_nothing(self):
        self.peers.seen("mdns", announcement())
        self.changes = 0
        self.peers.gone("beacon", ID_B)
        self.peers.gone("mdns", "c" * 32)
        self.assertEqual(self.changes, 0)

    def test_beacon_expiry_and_merged_peer_staying(self):
        self.peers.seen("beacon", announcement())
        self.peers.seen("mdns", announcement(device_id="c" * 32, fp=FP_X, name="C"))
        self.peers.seen("beacon", announcement(device_id="c" * 32, fp=FP_X, name="C"))
        self.clock.now += protocol.PEER_EXPIRY
        self.peers.sweep()
        self.assertEqual(len(self.peers.peers()), 2)
        changes = self.changes
        self.peers.sweep(self.clock.now + 0.5)
        [peer] = self.peers.peers()
        self.assertEqual((peer.name, peer.paths), ("C", {"mdns"}))
        self.assertEqual(self.changes, changes + 1)
        self.peers.sweep(self.clock.now + 100)
        self.assertEqual(self.changes, changes + 1)

    def test_bye(self):
        self.peers.seen("beacon", announcement())
        self.peers.gone("beacon", ID_B, FP_B)
        self.assertEqual(self.peers.peers(), [])

    def test_incompatible_is_listed_and_flagged(self):
        self.peers.seen("beacon", announcement(v=9, vmin=8))
        [peer] = self.peers.peers()
        self.assertFalse(peer.compatible)
        self.assertEqual((peer.vmin, peer.v), (8, 9))

    def test_sorted_by_name(self):
        self.peers.seen("mdns", announcement(device_id="c" * 32, name="zeta"))
        self.peers.seen("mdns", announcement(name="Alpha"))
        self.assertEqual([peer.name for peer in self.peers.peers()], ["Alpha", "zeta"])

    def test_no_callback(self):
        quiet = PeerList(ID_A)
        quiet.seen("manual", announcement(), "10.0.0.9")
        self.assertEqual(quiet.peers()[0].paths, {"manual"})


class FakeSocket:
    def __init__(self, *args, fail=None, recv_error=None):
        self.args = args
        self.options = []
        self.sent = []
        self.inbox = []
        self.closed = False
        self.bound = None
        self.fail = fail or {}
        self.recv_error = recv_error
        self.lock = threading.Lock()

    def setsockopt(self, level, option, value):
        error = self.fail.get(option)
        if callable(error):
            error = error(value)
        if error is not None:
            raise error
        self.options.append((level, option, value))

    def bind(self, address):
        if "bind" in self.fail:
            raise self.fail["bind"]
        self.bound = address

    def settimeout(self, value):
        self.timeout = value

    def sendto(self, data, address):
        if "sendto" in self.fail:
            raise self.fail["sendto"]
        with self.lock:
            self.sent.append((data, address))

    def recvfrom(self, size):
        with self.lock:
            if self.inbox:
                return self.inbox.pop(0)
            error = self.recv_error
        if error is not None:
            self.recv_error = None
            raise error
        time.sleep(0.005)
        raise socket.timeout()

    def close(self):
        self.closed = True

    def kinds(self):
        with self.lock:
            return [protocol.parse_beacon(data)["type"] for data, _ in self.sent]


class BeaconTransportTests(unittest.TestCase):
    def make(self, interfaces=("10.0.0.1",), **socket_kwargs):
        self.sockets = []

        def factory(*args):
            sock = FakeSocket(*args, **socket_kwargs)
            self.sockets.append(sock)
            return sock

        transport = BeaconTransport(port=50000, interval=0.01, interfaces=interfaces, socket_factory=factory)
        self.seen, self.gone = [], []
        self.addCleanup(transport.stop)
        return transport

    def start(self, transport):
        transport.start(
            FakeIdentity(ID_A, FP_A, "A").announcement(4000),
            lambda *args: self.seen.append(args),
            lambda *args: self.gone.append(args),
        )
        return self.sockets[-1]

    def test_hello_receive_and_bye(self):
        transport = self.make(interfaces=("10.0.0.1", "10.0.0.2"))
        sock = self.start(transport)
        self.assertEqual(transport.status, "running")
        self.assertEqual(sock.bound, ("", 50000))
        self.assertTrue(wait_until(lambda: len(sock.kinds()) >= 4))
        hello = protocol.build_beacon("hello", announcement())
        bye = protocol.build_beacon("bye", announcement())
        with sock.lock:
            sock.inbox += [(b"junk", ("10.0.0.7", 1)), (hello, ("10.0.0.7", 1)), (bye, ("10.0.0.7", 1))]
        self.assertTrue(wait_until(lambda: self.gone))
        self.assertEqual(self.seen[0][0], "beacon")
        self.assertEqual(self.seen[0][2], "10.0.0.7")
        self.assertEqual(self.gone, [("beacon", ID_B, FP_B)])
        transport.stop()
        self.assertTrue(sock.closed)
        self.assertEqual(sock.kinds()[-2:], ["bye", "bye"])
        self.assertEqual(transport.status, "stopped")
        transport.stop()

    def test_a_failing_listener_does_not_end_the_beacon(self):
        transport = self.make()
        calls = []

        def on_seen(*args):
            calls.append(args)
            raise RuntimeError("listener bug")

        transport.start(FakeIdentity(ID_A, FP_A, "A").announcement(4000), on_seen, lambda *a: None)
        sock = self.sockets[-1]
        hello = protocol.build_beacon("hello", announcement())
        with self.assertLogs(discovery.logger, "ERROR"):
            with sock.lock:
                sock.inbox += [(hello, ("10.0.0.7", 1)), (hello, ("10.0.0.8", 1))]
            self.assertTrue(wait_until(lambda: len(calls) == 2))
        self.assertEqual(transport.status, "running")

    def test_bye_goes_out_after_the_last_hello(self):
        transport = self.make()
        sock = self.start(transport)
        self.assertTrue(wait_until(lambda: sock.kinds()))
        transport.stop()
        self.assertEqual(sock.kinds()[-1], "bye")
        self.assertNotIn("hello", sock.kinds()[sock.kinds().index("bye"):])

    def test_receive_error_marks_the_transport_failed(self):
        transport = self.make(recv_error=OSError("network down"))
        self.start(transport)
        self.assertTrue(wait_until(lambda: transport.status.startswith("failed:")))

    def test_receive_error_while_stopping_is_quiet(self):
        transport = self.make()
        sock = self.start(transport)
        transport._stop.set()
        sock.recv_error = OSError("closed")
        transport.stop()
        self.assertEqual(transport.status, "stopped")

    def test_send_errors_are_survived(self):
        transport = self.make(fail={"sendto": OSError("unreachable")})
        self.start(transport)
        with self.assertLogs(discovery.logger, "DEBUG") as logs:
            time.sleep(0.05)
        self.assertTrue(any("send" in line for line in logs.output))

    def test_one_interface_failing_to_join_is_skipped(self):
        bad = socket.inet_aton(protocol.BEACON_GROUP) + socket.inet_aton("10.0.0.9")
        transport = self.make(
            interfaces=("10.0.0.9", "10.0.0.1"),
            fail={socket.IP_ADD_MEMBERSHIP: lambda value: OSError() if value == bad else None},
        )
        self.start(transport)
        self.assertEqual(transport.status, "running")

    def test_no_interface_joined_closes_the_socket(self):
        transport = self.make(fail={socket.IP_ADD_MEMBERSHIP: OSError("no route")})
        with self.assertRaises(OSError):
            self.start(transport)
        self.assertTrue(self.sockets[0].closed)

    def test_bind_failure_closes_the_socket(self):
        transport = self.make(fail={"bind": OSError("in use")})
        with self.assertRaises(OSError):
            self.start(transport)
        self.assertTrue(self.sockets[0].closed)

    def test_default_interfaces(self):
        transport = self.make(interfaces=None)
        with mock.patch.object(discovery, "local_ipv4_addresses", return_value=[]):
            self.start(transport)
        self.assertEqual(transport._interfaces, ["0.0.0.0"])

    def test_without_reuseport(self):
        transport = self.make()
        with mock.patch("openemux.core.share.discovery.hasattr", return_value=False, create=True):
            sock = self.start(transport)
        self.assertNotIn(getattr(socket, "SO_REUSEPORT", None), [option for _, option, _ in sock.options])

    def test_base_transport_is_abstract(self):
        transport = Transport()
        with self.assertRaises(NotImplementedError):
            transport.start({}, None, None)
        with self.assertRaises(NotImplementedError):
            transport.stop()


class StateChange(Enum):
    Added = 1
    Removed = 2
    Updated = 3


class FakeZeroconfModule(types.ModuleType):
    def __init__(self, register_error=None, resolve=None):
        super().__init__("zeroconf")
        module = self
        self.register_error = register_error
        self.resolve = resolve
        self.instances = []
        self.ServiceStateChange = StateChange

        class ServiceInfo:
            def __init__(self, type_, name, addresses=None, port=None, properties=None, server=None):
                self.type, self.name, self.addresses = type_, name, addresses
                self.port, self.properties, self.server = port, properties, server

        class Zeroconf:
            def __init__(self):
                self.registered = []
                self.closed = False
                self.unregister_error = None
                module.instances.append(self)

            def register_service(self, info):
                if module.register_error:
                    raise module.register_error
                self.registered.append(info)

            def unregister_service(self, info):
                if self.unregister_error:
                    raise self.unregister_error
                self.registered.remove(info)

            def get_service_info(self, type_, name, timeout=None):
                return module.resolve(type_, name)

            def close(self):
                self.closed = True

        class ServiceBrowser:
            def __init__(self, zc, type_, handlers):
                self.zc, self.type, self.handlers = zc, type_, handlers
                self.cancelled = False
                module.browser = self

            def cancel(self):
                self.cancelled = True

        self.ServiceInfo, self.Zeroconf, self.ServiceBrowser = ServiceInfo, Zeroconf, ServiceBrowser


def resolved(properties, port=4000, addresses=("10.0.0.5",)):
    return types.SimpleNamespace(
        properties=properties, port=port, parsed_addresses=lambda: list(addresses)
    )


class MdnsTransportTests(unittest.TestCase):
    def start(self, module, name="A", addresses=("10.0.0.1",)):
        transport = MdnsTransport(addresses=addresses)
        self.seen, self.gone = [], []
        self.addCleanup(transport.stop)
        with mock.patch.dict(sys.modules, {"zeroconf": module}):
            transport.start(
                FakeIdentity(ID_A, FP_A, name).announcement(4000),
                lambda *args: self.seen.append(args),
                lambda *args: self.gone.append(args),
            )
        return transport

    def fire(self, module, name, change):
        zc = module.instances[-1]
        module.browser.handlers[0](zc, protocol.SERVICE_TYPE, name, change)

    def test_register_browse_resolve_remove(self):
        txt = protocol.build_txt(announcement())
        module = FakeZeroconfModule(resolve=lambda type_, name: resolved(txt, addresses=("10.0.0.5", "fe80::5")))
        transport = self.start(module)
        info = module.instances[0].registered[0]
        self.assertEqual(info.name, f"A ({ID_A[:6]}).{protocol.SERVICE_TYPE}")
        self.assertEqual(info.addresses, [socket.inet_aton("10.0.0.1")])
        self.assertEqual(info.properties["fp"], FP_A)
        self.assertEqual(transport.status, "running")
        self.fire(module, "B._openemux._tcp.local.", StateChange.Added)
        self.assertEqual([args[2] for args in self.seen], ["10.0.0.5", "fe80::5"])
        self.assertEqual(self.seen[0][1]["id"], ID_B)
        self.fire(module, "B._openemux._tcp.local.", StateChange.Removed)
        self.fire(module, "B._openemux._tcp.local.", StateChange.Removed)
        self.assertEqual(self.gone, [("mdns", ID_B, FP_B)])
        transport.stop()
        self.assertTrue(module.instances[0].closed)
        self.assertTrue(module.browser.cancelled)
        self.assertEqual(module.instances[0].registered, [])
        self.assertEqual(transport.status, "stopped")
        transport.stop()

    def test_unresolvable_or_foreign_records_are_skipped(self):
        answers = iter([None, resolved({b"id": b"x"}), RuntimeError("timeout")])

        def resolve(type_, name):
            answer = next(answers)
            if isinstance(answer, Exception):
                raise answer
            return answer

        module = FakeZeroconfModule(resolve=resolve)
        self.start(module)
        for _ in range(3):
            self.fire(module, "X._openemux._tcp.local.", StateChange.Added)
        self.assertEqual(self.seen, [])

    def test_an_update_to_another_identity_retires_the_old_one(self):
        first = protocol.build_txt(announcement())
        second = dict(first, fp="c" * 64)
        answers = iter([resolved(first), resolved(second), resolved(second), None])
        module = FakeZeroconfModule(resolve=lambda type_, name: next(answers))
        self.start(module)
        name = "B._openemux._tcp.local."
        self.fire(module, name, StateChange.Added)
        self.fire(module, name, StateChange.Updated)
        self.assertEqual(self.gone, [("mdns", ID_B, FP_B)])
        self.fire(module, name, StateChange.Updated)
        self.assertEqual(len(self.gone), 1)
        self.fire(module, name, StateChange.Updated)
        self.assertEqual(self.gone[-1], ("mdns", ID_B, "c" * 64))
        self.fire(module, name, StateChange.Removed)
        self.assertEqual(len(self.gone), 2)

    def test_record_without_addresses(self):
        txt = protocol.build_txt(announcement())
        module = FakeZeroconfModule(resolve=lambda type_, name: resolved(txt, addresses=()))
        self.start(module)
        self.fire(module, "B._openemux._tcp.local.", StateChange.Updated)
        self.assertIsNone(self.seen[0][2])

    def test_long_name_is_cut_to_63_bytes(self):
        module = FakeZeroconfModule()
        self.start(module, name="é" * 64)
        instance = module.instances[0].registered[0].name[: -len(protocol.SERVICE_TYPE) - 1]
        self.assertLessEqual(len(instance.encode("utf-8")), 63)

    def test_default_addresses(self):
        module = FakeZeroconfModule()
        with mock.patch.object(discovery, "local_ipv4_addresses", return_value=["10.9.9.9"]):
            self.start(module, addresses=None)
        self.assertEqual(module.instances[0].registered[0].addresses, [socket.inet_aton("10.9.9.9")])

    def test_registration_failure_closes_zeroconf(self):
        module = FakeZeroconfModule(register_error=OSError("no multicast"))
        with self.assertRaises(OSError):
            self.start(module)
        self.assertTrue(module.instances[0].closed)

    def test_missing_zeroconf(self):
        transport = MdnsTransport()
        with mock.patch.dict(sys.modules, {"zeroconf": None}):
            with self.assertRaises(ImportError):
                transport.start(announcement(ID_A, FP_A), None, None)
        self.assertEqual(transport.status, "unavailable:zeroconf")

    def test_stop_survives_a_failing_step(self):
        module = FakeZeroconfModule()
        transport = self.start(module)
        module.instances[0].unregister_error = OSError("gone")
        with self.assertLogs(discovery.logger, "DEBUG"):
            transport.stop()
        self.assertTrue(module.instances[0].closed)


class FakeTransport(Transport):
    def __init__(self, name, error=None, stop_error=None):
        super().__init__()
        self.name = name
        self.error = error
        self.stop_error = stop_error
        self.started = self.stopped = 0

    def start(self, announcement, on_seen, on_gone):
        self.started += 1
        if self.error is not None:
            if isinstance(self.error, ImportError):
                self.status = "unavailable:zeroconf"
            raise self.error
        self.status = "running"

    def stop(self):
        self.stopped += 1
        if self.stop_error is not None:
            raise self.stop_error
        self.status = "stopped"


class Bus:
    """A fake network: every transport on it hears every other one's path."""

    def __init__(self, path):
        self.path = path
        self.members = []

    def transport(self):
        bus = self

        class BusTransport(Transport):
            name = bus.path

            def start(self, announcement, on_seen, on_gone):
                self.announcement, self.on_seen, self.on_gone = announcement, on_seen, on_gone
                for other in bus.members:
                    other.on_seen(bus.path, dict(announcement, compatible=True), "127.0.0.1")
                    on_seen(bus.path, dict(other.announcement, compatible=True), "127.0.0.1")
                bus.members.append(self)
                self.status = "running"

            def stop(self):
                bus.members.remove(self)
                for other in bus.members:
                    other.on_gone(bus.path, self.announcement["id"], self.announcement["fp"])
                self.status = "stopped"

        return BusTransport()


class DiscoveryTests(unittest.TestCase):
    def pair(self, paths):
        buses = [Bus(path) for path in paths]
        a = Discovery(FakeIdentity(ID_A, FP_A, "A"), 4001, [bus.transport() for bus in buses], sweep_interval=60)
        b = Discovery(FakeIdentity(ID_B, FP_B, "B"), 4002, [bus.transport() for bus in buses], sweep_interval=60)
        a.start()
        b.start()
        self.addCleanup(a.stop)
        self.addCleanup(b.stop)
        return a, b

    def test_mdns_only_beacon_only_and_both(self):
        for paths in (["mdns"], ["beacon"], ["mdns", "beacon"]):
            with self.subTest(paths=paths):
                a, b = self.pair(paths)
                [peer_of_a] = a.peers()
                [peer_of_b] = b.peers()
                self.assertEqual((peer_of_a.name, peer_of_a.port), ("B", 4002))
                self.assertEqual((peer_of_b.name, peer_of_b.port), ("A", 4001))
                self.assertEqual(peer_of_a.paths, set(paths))
                b.stop()
                self.assertEqual(a.peers(), [])
                a.stop()

    def test_default_transports(self):
        disc = Discovery(FakeIdentity(ID_A, FP_A, "A"), 1)
        self.assertEqual([type(t) for t in disc.transports], [MdnsTransport, BeaconTransport])

    def test_a_failing_transport_leaves_the_other_running(self):
        mdns = FakeTransport("mdns", error=ImportError("zeroconf"))
        beacon = FakeTransport("beacon")
        broken = FakeTransport("other", error=OSError("boom"))
        disc = Discovery(FakeIdentity(ID_A, FP_A, "A"), 1, [mdns, beacon, broken], sweep_interval=60)
        disc.start()
        self.addCleanup(disc.stop)
        self.assertEqual(
            disc.transport_status(),
            {"mdns": "unavailable:zeroconf", "beacon": "running", "other": "failed:boom"},
        )

    def test_start_and_stop_are_idempotent(self):
        transport = FakeTransport("beacon", stop_error=OSError("late"))
        disc = Discovery(FakeIdentity(ID_A, FP_A, "A"), 1, [transport], sweep_interval=60)
        disc.start()
        disc.start()
        self.assertEqual(transport.started, 1)
        with self.assertLogs(discovery.logger, "DEBUG"):
            disc.stop()
        disc.stop()
        self.assertEqual(transport.stopped, 1)
        self.assertIsNone(disc._sweeper)

    def test_the_sweeper_expires_beacon_peers(self):
        clock = Clock()
        disc = Discovery(FakeIdentity(ID_A, FP_A, "A"), 1, [], clock=clock, sweep_interval=0.01)
        disc.peer_list.seen("beacon", announcement(), "10.0.0.2")
        disc.start()
        self.addCleanup(disc.stop)
        clock.now += 60
        self.assertTrue(wait_until(lambda: disc.peers() == []))

    def test_add_manual(self):
        disc = Discovery(FakeIdentity(ID_A, FP_A, "A"), 1, [])
        disc.add_manual(announcement(), "192.168.0.8")
        [peer] = disc.peers()
        self.assertEqual((peer.paths, peer.addresses), ({"manual"}, ("192.168.0.8",)))
        disc.remove_manual(ID_B)
        self.assertEqual(disc.peers(), [])


if __name__ == "__main__":
    unittest.main()
