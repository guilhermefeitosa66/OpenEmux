"""The one object the share screen (#589) talks to.

``start()`` brings up the identity, the server and discovery, in that order --
discovery needs the server's real port to advertise it. ``stop()`` takes them
down in reverse. A failure halfway through ``start()`` stops whatever already
started before it re-raises, so nothing is ever left listening. The grace
period after the screen closes is the caller's: this only starts and stops.

The transfers go through it too (#588): ``send()`` starts an
:class:`OutgoingTransfer` to a peer, ``prepare_receive()`` decides what an
incoming offer would do, and ``accept()`` answers it and receives the files.
"""

import threading

from openemux.core.cores import CoreCatalog
from openemux.core.paths import get_project_root
from openemux.core.share import availability
from openemux.core.share.discovery import Discovery
from openemux.core.share.identity import load_or_create
from openemux.core.share.placement import plan_receive
from openemux.core.share.protocol import ErrorCode, ShareError
from openemux.core.share.receive import IncomingTransfer
from openemux.core.share.send import OutgoingTransfer
from openemux.core.share.session import ShareClient, ShareServer


class ShareService:
    def __init__(self, config, share_dir=None, on_offer=None, on_cancel=None,
                 on_peers_changed=None, server_factory=ShareServer,
                 discovery_factory=Discovery, client_factory=ShareClient, catalog=None):
        self.config = config
        self.share_dir = share_dir if share_dir is not None else config.store_path("share")
        self.on_offer = on_offer
        self.on_cancel = on_cancel
        self.on_peers_changed = on_peers_changed
        self.server_factory = server_factory
        self.discovery_factory = discovery_factory
        self.client_factory = client_factory
        self._catalog = catalog
        self.identity = None
        self.server = None
        self.discovery = None
        self._incoming = {}
        self._incoming_lock = threading.Lock()

    @property
    def catalog(self):
        if self._catalog is None:
            self._catalog = CoreCatalog(project_root=get_project_root())
        return self._catalog

    @property
    def running(self):
        return self.server is not None

    def start(self):
        """Start sharing; returns the port the server listens on."""
        if self.server is not None:
            return self.server.port
        state = availability()["share"]
        if state != "ok":
            raise ShareError(ErrorCode.UNAVAILABLE, state)
        self.identity = load_or_create(self.share_dir, self.config.get_share_device_name())
        server = self.server_factory(self.identity, on_offer=self.on_offer, on_cancel=self._cancelled_by_sender)
        server.file_handler = self._route_file
        discovery = None
        try:
            port = server.start()
            discovery = self.discovery_factory(self.identity, port, on_change=self.on_peers_changed)
            discovery.start()
        except Exception:
            if discovery is not None:
                discovery.stop()
            server.stop()
            raise
        self.server = server
        self.discovery = discovery
        return port

    def stop(self):
        if self.server is None:
            return
        for transfer in self._take_incoming():
            transfer.cancel()
        discovery, server = self.discovery, self.server
        self.discovery = self.server = None
        try:
            discovery.stop()
        finally:
            server.stop()

    def peers(self):
        return self.discovery.peers() if self.discovery is not None else []

    def transport_status(self):
        return self.discovery.transport_status() if self.discovery is not None else {}

    def answer(self, offer_id, accepted, items=None):
        """The user's decision; ``unavailable`` once sharing has stopped."""
        if self.server is None:
            raise ShareError(ErrorCode.UNAVAILABLE, "sharing is stopped")
        self.server.answer(offer_id, accepted, items)

    def cancel(self, offer_id):
        """Cancel an incoming offer (and its transfer); nothing to do once sharing has stopped."""
        for transfer in self._take_incoming(offer_id):
            transfer.cancel()
        if self.server is not None:
            self.server.cancel(offer_id)

    # -- transfers (#588) ------------------------------------------------

    def send(self, peer, built, **callbacks):
        """Offer ``built`` (a ``manifest.BuiltManifest``) to ``peer`` on a worker thread.

        ``callbacks`` are :class:`OutgoingTransfer`'s ``on_code``,
        ``on_progress`` and ``on_done``. Returns the started transfer.
        """
        if self.identity is None:
            raise ShareError(ErrorCode.UNAVAILABLE, "sharing is stopped")
        client = self.client_factory(peer.addresses[0], peer.port, peer.fp)
        transfer = OutgoingTransfer(client, self.identity.sender(), built, **callbacks)
        transfer.start()
        return transfer

    def prepare_receive(self, offer, **kwargs):
        """What accepting ``offer`` (an ``IncomingOffer``) would do; nothing is written.

        ``kwargs`` go to :func:`placement.plan_receive` -- ``policies``,
        ``overrides`` and ``unchecked`` from the user's choices.
        """
        kwargs.setdefault("roms_dir", self.config.get_roms_path())
        kwargs.setdefault("states_dir", self.config.get_states_dir())
        kwargs.setdefault("catalog", self.catalog)
        return plan_receive(offer.manifest, **kwargs)

    def accept(self, offer_id, plan, hooks=None, watchdog=True, **kwargs):
        """Check the space, answer the offer and start receiving it.

        Refuses with ``too_large`` -- answering nothing -- when a filesystem
        lacks room; the error's ``details["space"]`` lists the ones short.
        ``kwargs`` go to :class:`IncomingTransfer` (``on_progress``,
        ``on_done``, ``shader_ids``).
        """
        if self.server is None:
            raise ShareError(ErrorCode.UNAVAILABLE, "sharing is stopped")
        checks = plan.space_check()
        if not plan.ok_to_accept(checks):
            short = [check for check in checks if not check["ok"]]
            raise ShareError(ErrorCode.TOO_LARGE, "not enough free space", {"space": short})
        on_done = kwargs.pop("on_done", None)

        def done(result):
            self._take_incoming(offer_id)
            if on_done is not None:
                on_done(result)

        transfer = IncomingTransfer(
            offer_id, plan, catalog=self.catalog, hooks=hooks, on_done=done,
            on_abort=self._aborted_here, **kwargs,
        )
        with self._incoming_lock:
            self._incoming[offer_id] = transfer
        try:
            self.server.answer(offer_id, True, plan.answer_items())
        except ShareError:
            self._take_incoming(offer_id)
            raise
        if watchdog:
            transfer.start_watchdog()
        transfer.start()
        return transfer

    def _take_incoming(self, offer_id=None):
        """Forget one incoming transfer (or all of them); returns what was forgotten."""
        with self._incoming_lock:
            if offer_id is None:
                taken, self._incoming = list(self._incoming.values()), {}
                return taken
            transfer = self._incoming.pop(offer_id, None)
        return [transfer] if transfer is not None else []

    def _route_file(self, offer, item_id, body, length):
        with self._incoming_lock:
            transfer = self._incoming.get(offer.offer_id)
        if transfer is None:
            raise ShareError(ErrorCode.BAD_REQUEST, "no transfer for this offer")
        transfer.handle_put(item_id, body, length)

    def _aborted_here(self, offer_id):
        """This side ended a transfer: the sender learns it as a cancelled offer."""
        server = self.server
        if server is not None:
            server.cancel(offer_id)

    def _cancelled_by_sender(self, offer_id):
        for transfer in self._take_incoming(offer_id):
            transfer.on_remote_cancel()
        if self.on_cancel is not None:
            self.on_cancel(offer_id)
