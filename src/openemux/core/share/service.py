"""The one object the share screen (#589) talks to.

``start()`` brings up the identity, the server and discovery, in that order --
discovery needs the server's real port to advertise it. ``stop()`` takes them
down in reverse. A failure halfway through ``start()`` stops whatever already
started before it re-raises, so nothing is ever left listening. The grace
period after the screen closes is the caller's: this only starts and stops.
"""

from openemux.core.share import availability
from openemux.core.share.discovery import Discovery
from openemux.core.share.identity import load_or_create
from openemux.core.share.protocol import ErrorCode, ShareError
from openemux.core.share.session import ShareServer


class ShareService:
    def __init__(self, config, share_dir=None, on_offer=None, on_cancel=None,
                 on_peers_changed=None, server_factory=ShareServer,
                 discovery_factory=Discovery):
        self.config = config
        self.share_dir = share_dir if share_dir is not None else config.store_path("share")
        self.on_offer = on_offer
        self.on_cancel = on_cancel
        self.on_peers_changed = on_peers_changed
        self.server_factory = server_factory
        self.discovery_factory = discovery_factory
        self.identity = None
        self.server = None
        self.discovery = None

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
        server = self.server_factory(self.identity, on_offer=self.on_offer, on_cancel=self.on_cancel)
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
        """Cancel an incoming offer; nothing to do once sharing has stopped."""
        if self.server is not None:
            self.server.cancel(offer_id)
