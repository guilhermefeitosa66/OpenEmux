"""Finding other OpenEmux devices: mDNS and a UDP multicast beacon.

Both run in parallel and feed one :class:`PeerList`, keyed by ``(id, fp)``:
a device seen by both is one entry tagged with both paths, and a beacon that
reuses a real device's id with another certificate is a second entry, never a
silent replacement. Either transport failing to start leaves the other
running -- that is what "beacon only" and "mDNS only" are.

Nothing here runs unless :meth:`Discovery.start` was called, and
:meth:`Discovery.stop` closes every socket and joins every thread.
"""

import logging
import socket
import threading
import time
from dataclasses import dataclass

from openemux.core.share.protocol import (
    BEACON_GROUP,
    BEACON_INTERVAL,
    BEACON_PORT,
    BEACON_TTL,
    PATH_BEACON,
    PATH_MANUAL,
    PATH_MDNS,
    PEER_EXPIRY,
    SERVICE_TYPE,
    build_beacon,
    build_txt,
    parse_beacon,
    parse_txt,
)

logger = logging.getLogger(__name__)

STATUS_IDLE = "idle"
STATUS_RUNNING = "running"
STATUS_STOPPED = "stopped"

#: The paths that expire on their own; mDNS has a removal, manual is the user's.
EXPIRING_PATHS = (PATH_BEACON,)
RECV_TIMEOUT = 0.5
JOIN_TIMEOUT = 2.0


@dataclass(frozen=True)
class Peer:
    id: str
    fp: str
    name: str
    platform: str
    v: int
    vmin: int
    port: int
    addresses: tuple
    paths: frozenset
    compatible: bool

    @property
    def key(self):
        return (self.id, self.fp)


def local_ipv4_addresses():
    """This machine's IPv4 addresses, loopback left out; ``[]`` if unknown.

    ``ifaddr`` comes with ``zeroconf``; without it the beacon goes out on the
    default interface only.
    """
    try:
        import ifaddr
    except ImportError:
        return []
    found = []
    for adapter in ifaddr.get_adapters():
        for ip in adapter.ips:
            if isinstance(ip.ip, str) and not ip.ip.startswith("127.") and ip.ip not in found:
                found.append(ip.ip)
    return found


def _ordered_addresses(addresses):
    """IPv4 first, then IPv6, each once."""
    unique = list(dict.fromkeys(addresses))
    return tuple([a for a in unique if ":" not in a] + [a for a in unique if ":" in a])


class PeerList:
    """The merged list of devices discovery found. Thread-safe."""

    def __init__(self, own_id, clock=time.monotonic, on_change=None):
        self.own_id = own_id
        self.clock = clock
        self.on_change = on_change
        self._lock = threading.Lock()
        self._entries = {}

    def seen(self, path, announcement, address=None):
        """Record ``announcement`` reached us by ``path`` (from ``address``)."""
        if announcement["id"] == self.own_id:
            return
        key = (announcement["id"], announcement["fp"])
        with self._lock:
            entry = self._entries.setdefault(key, {"seen": {}, "addresses": {}})
            changed = path not in entry["seen"] or entry.get("info") != announcement
            entry["info"] = dict(announcement)
            entry["seen"][path] = self.clock()
            if address:
                addresses = entry["addresses"].setdefault(path, [])
                if address not in addresses:
                    addresses.append(address)
                    changed = True
        if changed:
            self._changed()

    def gone(self, path, device_id, fp=None):
        """Forget ``path`` for the device; drop it once no path is left."""
        changed = False
        with self._lock:
            for key in list(self._entries):
                if key[0] == device_id and fp in (None, key[1]):
                    changed |= self._drop_path(key, path)
        if changed:
            self._changed()

    def sweep(self, now=None):
        """Expire the beacon paths that went quiet."""
        now = self.clock() if now is None else now
        changed = False
        with self._lock:
            for key, entry in list(self._entries.items()):
                for path in EXPIRING_PATHS:
                    seen = entry["seen"].get(path)
                    if seen is not None and now - seen > PEER_EXPIRY:
                        changed |= self._drop_path(key, path)
        if changed:
            self._changed()

    def _drop_path(self, key, path):
        entry = self._entries[key]
        if path not in entry["seen"]:
            return False
        del entry["seen"][path]
        entry["addresses"].pop(path, None)
        if not entry["seen"]:
            del self._entries[key]
        return True

    def peers(self):
        with self._lock:
            peers = [self._peer(entry) for entry in self._entries.values()]
        return sorted(peers, key=lambda peer: (peer.name.casefold(), peer.id))

    @staticmethod
    def _peer(entry):
        info = entry["info"]
        addresses = [a for found in entry["addresses"].values() for a in found]
        return Peer(
            info["id"], info["fp"], info["name"], info["platform"], info["v"], info["vmin"],
            info["port"], _ordered_addresses(addresses), frozenset(entry["seen"]),
            info["compatible"],
        )

    def _changed(self):
        if self.on_change is not None:
            self.on_change()


class Transport:
    """One discovery path. ``start`` raises when the path cannot run."""

    name = ""

    def __init__(self):
        self.status = STATUS_IDLE

    def start(self, announcement, on_seen, on_gone):
        raise NotImplementedError

    def stop(self):
        raise NotImplementedError


class BeaconTransport(Transport):
    """The UDP multicast beacon: a ``hello`` every 2 s, a ``bye`` on stop."""

    name = PATH_BEACON

    def __init__(self, group=BEACON_GROUP, port=BEACON_PORT, interval=BEACON_INTERVAL,
                 interfaces=None, socket_factory=socket.socket):
        super().__init__()
        self.group = group
        self.port = port
        self.interval = interval
        self.interfaces = interfaces
        self.socket_factory = socket_factory
        self._sock = None
        self._stop = threading.Event()
        self._threads = []
        self._announcement = None

    def start(self, announcement, on_seen, on_gone):
        self._announcement = announcement
        interfaces = list(self.interfaces) if self.interfaces is not None else local_ipv4_addresses()
        self._interfaces = interfaces or ["0.0.0.0"]
        self._sock = self._open_socket()
        self._stop.clear()
        self._threads = [
            threading.Thread(target=self._send_loop, name="share-beacon-send", daemon=True),
            threading.Thread(
                target=self._recv_loop, args=(on_seen, on_gone), name="share-beacon-recv", daemon=True
            ),
        ]
        self.status = STATUS_RUNNING
        for thread in self._threads:
            thread.start()

    def _open_socket(self):
        sock = self.socket_factory(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if hasattr(socket, "SO_REUSEPORT"):
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            sock.bind(("", self.port))
            joined = 0
            for interface in self._interfaces:
                membership = socket.inet_aton(self.group) + socket.inet_aton(interface)
                try:
                    sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, membership)
                    joined += 1
                except OSError as exc:
                    logger.debug("Beacon cannot join %s on %s: %s", self.group, interface, exc)
            if not joined:
                raise OSError(f"could not join {self.group} on any interface")
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, BEACON_TTL)
            sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
            sock.settimeout(RECV_TIMEOUT)
        except Exception:
            sock.close()
            raise
        return sock

    def _send(self, kind):
        datagram = build_beacon(kind, self._announcement)
        for interface in self._interfaces:
            try:
                self._sock.setsockopt(
                    socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(interface)
                )
                self._sock.sendto(datagram, (self.group, self.port))
            except OSError as exc:
                logger.debug("Beacon send on %s failed: %s", interface, exc)

    def _send_loop(self):
        while not self._stop.is_set():
            self._send("hello")
            self._stop.wait(self.interval)

    def _recv_loop(self, on_seen, on_gone):
        while not self._stop.is_set():
            try:
                data, source = self._sock.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError as exc:
                if not self._stop.is_set():
                    logger.debug("Beacon receive failed: %s", exc)
                    self.status = f"failed:{exc}"
                return
            beacon = parse_beacon(data)
            if beacon is None:
                continue
            if beacon.pop("type") == "bye":
                on_gone(PATH_BEACON, beacon["id"], beacon["fp"])
            else:
                on_seen(PATH_BEACON, beacon, source[0])

    def stop(self):
        if self._sock is None:
            return
        self._stop.set()
        self._send("bye")
        for thread in self._threads:
            thread.join(JOIN_TIMEOUT)
        self._sock.close()
        self._sock = None
        self._threads = []
        self.status = STATUS_STOPPED


class MdnsTransport(Transport):
    """DNS-SD over mDNS via ``zeroconf``: register ourselves, browse the rest."""

    name = PATH_MDNS

    def __init__(self, addresses=None, resolve_timeout_ms=3000):
        super().__init__()
        self.addresses = addresses
        self.resolve_timeout_ms = resolve_timeout_ms
        self._zc = None
        self._info = None
        self._browser = None
        self._names = {}
        self._lock = threading.Lock()

    def start(self, announcement, on_seen, on_gone):
        try:
            import zeroconf
        except ImportError:
            self.status = "unavailable:zeroconf"
            raise
        self._on_seen = on_seen
        self._on_gone = on_gone
        addresses = self.addresses if self.addresses is not None else local_ipv4_addresses()
        instance = f"{announcement['name']} ({announcement['id'][:6]})".encode("utf-8")[:63]
        instance = instance.decode("utf-8", "ignore")
        self._info = zeroconf.ServiceInfo(
            SERVICE_TYPE,
            f"{instance}.{SERVICE_TYPE}",
            addresses=[socket.inet_aton(address) for address in addresses],
            port=announcement["port"],
            properties=build_txt(announcement),
            server=f"openemux-{announcement['id'][:12]}.local.",
        )
        zc = zeroconf.Zeroconf()
        try:
            zc.register_service(self._info)
            self._zc = zc
            self._browser = zeroconf.ServiceBrowser(zc, SERVICE_TYPE, handlers=[self._on_change])
        except Exception:
            self._zc = None
            zc.close()
            raise
        self._state_change = zeroconf.ServiceStateChange
        self.status = STATUS_RUNNING

    def _on_change(self, zeroconf, service_type, name, state_change):
        if state_change is self._state_change.Removed:
            with self._lock:
                key = self._names.pop(name, None)
            if key is not None:
                self._on_gone(PATH_MDNS, *key)
            return
        try:
            info = zeroconf.get_service_info(service_type, name, timeout=self.resolve_timeout_ms)
        except Exception as exc:
            logger.debug("mDNS could not resolve %s: %s", name, exc)
            return
        announcement = parse_txt(info.properties, info.port) if info is not None else None
        if announcement is None:
            return
        with self._lock:
            self._names[name] = (announcement["id"], announcement["fp"])
        addresses = info.parsed_addresses() or [None]
        for address in addresses:
            self._on_seen(PATH_MDNS, announcement, address)

    def stop(self):
        if self._zc is None:
            return
        zc, self._zc = self._zc, None
        for step in (self._browser.cancel, lambda: zc.unregister_service(self._info), zc.close):
            try:
                step()
            except Exception as exc:
                logger.debug("mDNS stop step failed: %s", exc)
        self._browser = None
        self.status = STATUS_STOPPED


class Discovery:
    """The transports and the peer list, started and stopped together."""

    def __init__(self, identity, port, transports=None, clock=time.monotonic, on_change=None,
                 sweep_interval=1.0):
        self.identity = identity
        self.port = port
        self.transports = transports if transports is not None else [MdnsTransport(), BeaconTransport()]
        self.peer_list = PeerList(identity.id, clock=clock, on_change=on_change)
        self.sweep_interval = sweep_interval
        self._stop = threading.Event()
        self._sweeper = None

    def start(self):
        if self._sweeper is not None:
            return
        announcement = self.identity.announcement(self.port)
        for transport in self.transports:
            try:
                transport.start(announcement, self.peer_list.seen, self.peer_list.gone)
            except Exception as exc:
                if not transport.status.startswith("unavailable:"):
                    transport.status = f"failed:{exc}"
                logger.info("Share discovery: %s not started (%s)", transport.name, transport.status)
        self._stop.clear()
        self._sweeper = threading.Thread(target=self._sweep_loop, name="share-sweep", daemon=True)
        self._sweeper.start()

    def _sweep_loop(self):
        while not self._stop.wait(self.sweep_interval):
            self.peer_list.sweep()

    def stop(self):
        if self._sweeper is None:
            return
        self._stop.set()
        self._sweeper.join(JOIN_TIMEOUT)
        self._sweeper = None
        for transport in self.transports:
            try:
                transport.stop()
            except Exception as exc:
                logger.debug("Share discovery: stopping %s failed: %s", transport.name, exc)

    def peers(self):
        return self.peer_list.peers()

    def add_manual(self, announcement, address):
        """A device the user typed in (its ``/info`` already fetched)."""
        self.peer_list.seen(PATH_MANUAL, announcement, address)

    def remove_manual(self, device_id):
        self.peer_list.gone(PATH_MANUAL, device_id)

    def transport_status(self):
        return {transport.name: transport.status for transport in self.transports}
