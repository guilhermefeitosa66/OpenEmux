"""A Share nearby coordinator over a fake service, for the UI tests (#589).

The window is real (``WindowCase``); the service is not -- no socket, no
certificate -- except ``prepare_receive``, which runs the real placement over
the throwaway library. Threads, idle callbacks and timers are synchronous and
in the test's hands.
"""

from types import SimpleNamespace
from unittest import mock

from openemux.core.share.discovery import Peer
from openemux.core.share.placement import plan_receive
from openemux.core.share.protocol import ShareError
from openemux.core.share.session import IncomingOffer
from openemux.ui.share_coordinator import ShareCoordinator
from tests.share_fixtures import make_catalog

FP = "ab12" * 16


class FakeTimers:
    def __init__(self):
        self.pending = {}
        self.removed = []
        self._next = 0

    def add(self, seconds, callback):
        self._next += 1
        self.pending[self._next] = (seconds, callback)
        return self._next

    def remove(self, source_id):
        self.removed.append(source_id)
        self.pending.pop(source_id, None)

    def fire(self, seconds):
        """Run every timer of ``seconds``; repeating ones stay."""
        for source_id, (delay, callback) in list(self.pending.items()):
            if delay == seconds and source_id in self.pending:
                if not callback():
                    self.pending.pop(source_id, None)

    def has(self, seconds):
        return any(delay == seconds for delay, _ in self.pending.values())


class FakeTransfer:
    def __init__(self):
        self.cancelled = 0

    def cancel(self):
        self.cancelled += 1


class FakeDiscovery:
    def __init__(self):
        self.manual = []

    def add_manual(self, announcement, address):
        self.manual.append((announcement, address))


class FakeService:
    def __init__(self, config, catalog, on_offer=None, on_cancel=None, on_peers_changed=None):
        self.config = config
        self.catalog = catalog
        self.on_offer = on_offer
        self.on_cancel = on_cancel
        self.on_peers_changed = on_peers_changed
        self.server = None
        self.identity = None
        self.discovery = None
        self.calls = []
        self.peer_list = []
        self.start_error = None
        self.answer_error = None
        self.accept_error = None
        self.send_error = None
        self.sent = None
        self.accepted = None

    def start(self):
        self.calls.append("start")
        if self.start_error is not None:
            raise self.start_error
        self.server = SimpleNamespace(port=53319)
        self.identity = SimpleNamespace(name="QA Box", fingerprint=FP)
        self.discovery = FakeDiscovery()
        return 53319

    def stop(self):
        self.calls.append("stop")
        self.server = self.identity = self.discovery = None

    def peers(self):
        return list(self.peer_list)

    def send(self, peer, built, **callbacks):
        if self.send_error is not None:
            raise self.send_error
        self.sent = (peer, built, callbacks)
        self.outgoing = FakeTransfer()
        return self.outgoing

    def prepare_receive(self, offer, **kwargs):
        kwargs.setdefault("roms_dir", self.config.get_roms_path())
        kwargs.setdefault("states_dir", self.config.get_states_dir())
        kwargs.setdefault("catalog", self.catalog)
        return plan_receive(offer.manifest, **kwargs)

    def answer(self, offer_id, accepted, items=None):
        self.calls.append(("answer", offer_id, accepted))
        if self.answer_error is not None:
            raise self.answer_error

    def accept(self, offer_id, plan, hooks=None, **kwargs):
        if self.accept_error is not None:
            raise self.accept_error
        self.accepted = (offer_id, plan, hooks, kwargs)
        self.incoming = FakeTransfer()
        return self.incoming

    def cancel(self, offer_id):
        self.calls.append(("cancel", offer_id))


class FakeClient:
    """``ShareClient`` for Connect by Address: ``info`` answers or raises."""

    answers = {}

    def __init__(self, host, port, fp):
        self.host, self.port = host, port
        self.peer_fp = fp or FP

    def info(self):
        answer = self.answers.get(self.host)
        if isinstance(answer, ShareError):
            raise answer
        return answer


def peer(name="Phone", platform="phone", compatible=True, v=1, paths=("mdns", "beacon"), device_id=None):
    return Peer(
        device_id or (name.encode().hex() + "0" * 32)[:32], FP, name, platform, v, 1, 53319,
        ("192.168.1.30",), frozenset(paths), compatible,
    )


def offer(games, sender="Phone", code="482913", offer_id="o" * 22):
    manifest = {"games": games, "total_size": 0, "file_count": 0}
    return IncomingOffer(offer_id, {"name": sender, "id": "a" * 32, "pf": "phone", "fp": FP}, manifest, code)


def install(case, **kwargs):
    """A coordinator over a fake service on ``case.win``; returns it."""
    case.timers = FakeTimers()
    catalog = make_catalog(case.tmp / "cores", {"snes9x": ("Snes9x", "1.62.3")})
    services = []

    def factory(config, **callbacks):
        service = FakeService(config, catalog, **callbacks)
        services.append(service)
        return service

    options = dict(
        service_factory=factory,
        dispatch=lambda func: func(),
        timeout_add=case.timers.add,
        source_remove=case.timers.remove,
        run_async=lambda func, *args: func(*args),
        client_factory=FakeClient,
        addresses=lambda: ["192.168.1.20"],
        clock=lambda: case.now,
    )
    options.update(kwargs)
    case.now = 1000.0
    coordinator = ShareCoordinator(case.win, **options)
    case.win._share_coordinator = coordinator
    case.service = services[0]
    case.presented = []
    from gi.repository import Adw

    patcher = mock.patch.object(Adw.Dialog, "present", lambda dialog, *args: case.presented.append(dialog))
    patcher.start()
    case.addCleanup(patcher.stop)
    available = mock.patch.object(
        ShareCoordinator, "availability", lambda self: {"share": "ok", "mdns": "ok"}
    )
    available.start()
    case.addCleanup(available.stop)
    return coordinator


def texts(widget):
    """Every label under ``widget`` (row titles and subtitles included), in order."""
    from gi.repository import Gtk

    found = []

    def walk(node):
        if isinstance(node, Gtk.Label) and node.get_text():
            found.append(node.get_text())
        child = node.get_first_child()
        while child is not None:
            walk(child)
            child = child.get_next_sibling()

    walk(widget)
    return " | ".join(found)
