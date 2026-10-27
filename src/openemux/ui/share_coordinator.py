"""The one place the Share nearby screens meet the core (#589).

The window holds one :class:`ShareCoordinator`. It owns the ``ShareService``
and decides when this device is visible: from the moment a share screen opens
until :data:`GRACE_SECONDS` after the last one closes -- or after the transfer
running then ends. Nothing listens before the first screen opens, and quitting
stops it at once.

Every callback the core makes arrives on one of its threads; each goes
through ``dispatch`` (:func:`main_loop`) before it touches anything else, so no
widget is ever reached from a worker thread. Slow work -- starting the service
the first time (a certificate is made), hashing the games to send, asking an
address for its ``/info`` -- runs on ``run_async`` threads. Tests pass
synchronous versions of the three.

Only this module talks to the service API, so a change there stays here.
"""

import logging
import threading
import time

from gi.repository import Gio, GLib

from openemux.core.share import address as share_address
from openemux.core.share import availability
from openemux.core.share.discovery import local_ipv4_addresses
from openemux.core.share.display import PROBE_POLICIES, plural
from openemux.core.share.identity import default_device_name
from openemux.core.share.library_hooks import ManagerLibraryHooks
from openemux.core.share.manifest import build_manifest
from openemux.core.share.placement import ACTION_SEND
from openemux.core.share.protocol import ErrorCode, ShareError
from openemux.core.share.report import send_report
from openemux.core.share.selection import apply_selection
from openemux.core.share.service import ShareService
from openemux.core.share.session import ShareClient

logger = logging.getLogger(__name__)

#: How long this device stays visible after the last share screen closes.
GRACE_SECONDS = 30

STATE_STOPPED = "stopped"
STATE_STARTING = "starting"
STATE_RUNNING = "running"
STATE_FAILED = "failed"


def main_loop(func):
    """Run ``func`` on the main loop, at the default priority.

    Not ``GLib.idle_add``'s own idle priority: a spinner on screen keeps a
    redraw pending at a higher one on a slow display, and the share screens
    always show one while they wait -- so the devices found, the code and the
    answer never arrived (#589).
    """
    return GLib.idle_add(func, priority=GLib.PRIORITY_DEFAULT)


def _thread(target, *args):
    threading.Thread(target=target, args=args, name="share-ui", daemon=True).start()


class ShareCoordinator:
    def __init__(self, window, service_factory=ShareService, dispatch=main_loop,
                 timeout_add=GLib.timeout_add_seconds, source_remove=GLib.source_remove,
                 run_async=_thread, client_factory=ShareClient, addresses=local_ipv4_addresses,
                 clock=time.monotonic):
        self.win = window
        self.config = window.config_manager
        self.service = service_factory(
            self.config,
            on_offer=lambda offer: self._dispatch(self._on_offer, offer),
            on_cancel=lambda offer_id: self._dispatch(self._on_remote_cancel, offer_id),
            on_peers_changed=lambda: self._dispatch(self._on_peers_changed),
        )
        self._idle_add = dispatch
        #: The timers and the clock, for the dialogs too.
        self.timeout_add = timeout_add
        self.source_remove = source_remove
        self.clock = clock
        self._run_async = run_async
        #: Serializes ``service.start``/``stop``: a stop queued by the grace
        #: period must not land after a start a reopened screen asked for.
        self._lifecycle = threading.Lock()
        self._client_factory = client_factory
        self._addresses = addresses
        self.state = STATE_STOPPED
        self.error = None
        self._screens = []
        self._grace = None
        self._stop_when_started = False
        #: The transfer running, outgoing or incoming; one at a time.
        self.transfer = None
        self.share_dialog = None
        self.offer_dialog = None

    # -- threads ---------------------------------------------------------

    def _dispatch(self, func, *args):
        def run():
            func(*args)
            return False

        self._idle_add(run)

    # -- visibility ------------------------------------------------------

    def availability(self):
        return availability()

    @property
    def busy(self):
        return self.transfer is not None

    def open_screen(self, screen):
        """A share screen opened: start (or keep) listening."""
        if screen not in self._screens:
            self._screens.append(screen)
        self._cancel_grace()
        self._stop_when_started = False
        if self.state in (STATE_STOPPED, STATE_FAILED):
            self._start()

    def close_screen(self, screen):
        if screen in self._screens:
            self._screens.remove(screen)
        if self.share_dialog is screen:
            self.share_dialog = None
        self._maybe_start_grace()

    def _start(self):
        if self.availability()["share"] != "ok":
            self.state, self.error = STATE_FAILED, ErrorCode.UNAVAILABLE
            return
        self.state, self.error = STATE_STARTING, None
        self._notify("on_share_state")
        self._run_async(self._start_worker)

    def _start_worker(self):
        try:
            with self._lifecycle:
                self.service.start()
        except Exception as exc:
            logger.warning("share: could not start: %s", exc)
            code = exc.code if isinstance(exc, ShareError) else ErrorCode.INTERNAL
            self._dispatch(self._started, code)
            return
        self._dispatch(self._started, None)

    def _started(self, error):
        if error is not None:
            self.state, self.error = STATE_FAILED, error
        else:
            self.state = STATE_RUNNING
        if self._stop_when_started:
            self._stop_when_started = False
            self._grace_over()
            return
        self._notify("on_share_state")
        self._notify("on_peers_changed")

    def _maybe_start_grace(self):
        if self._screens or self.busy or self.offer_dialog is not None or self._grace is not None:
            return
        if self.state in (STATE_STOPPED, STATE_FAILED):
            return
        self._grace = self.timeout_add(GRACE_SECONDS, self._on_grace)

    def _cancel_grace(self):
        if self._grace is not None:
            self.source_remove(self._grace)
            self._grace = None

    def _on_grace(self):
        self._grace = None
        if self.state == STATE_STARTING:
            # Stopping under a start that has not finished would leave it running.
            self._stop_when_started = True
            return False
        self._grace_over()
        return False

    def _grace_over(self):
        if self._screens or self.busy or self.offer_dialog is not None:
            return
        self.state = STATE_STOPPED
        self._run_async(self._stop_worker)

    def _stop_worker(self):
        with self._lifecycle:
            # A screen that opened since asked for a start: leave it running.
            if self.state == STATE_STOPPED:
                self.service.stop()

    def shutdown(self):
        """The app is quitting: stop listening now, and end any transfer."""
        self._cancel_grace()
        if self.transfer is not None:
            self.transfer.cancel()
            self.transfer = None
        self.state = STATE_STOPPED
        self.service.stop()

    def _notify(self, method, *args):
        for screen in list(self._screens):
            handler = getattr(screen, method, None)
            if handler is not None:
                handler(*args)

    # -- what the screens read -------------------------------------------

    def peers(self):
        return self.service.peers()

    @property
    def identity(self):
        return self.service.identity

    def device_name(self):
        identity = self.service.identity
        if identity is not None:
            return identity.name
        return self.config.get_share_device_name() or default_device_name()

    def address(self):
        """``(host, port, fp, uri)`` of this device, or ``None`` before it listens."""
        server, identity = self.service.server, self.service.identity
        if server is None or identity is None:
            return None
        host = next(iter(self._addresses()), "127.0.0.1")
        port = server.port
        return host, port, identity.fingerprint, share_address.build(host, port, identity.fingerprint)

    def _on_peers_changed(self):
        self._notify("on_peers_changed")

    # -- connect by address ----------------------------------------------

    def connect_address(self, text, on_done):
        """Reach a device the user typed in; ``on_done(error_code, host)``.

        The device appears among the peers (path "manual") on success.
        """
        try:
            parsed = share_address.parse(text)
        except ShareError as exc:
            on_done(exc.code, None)
            return
        self._run_async(self._connect_worker, parsed, on_done)

    def _connect_worker(self, parsed, on_done):
        client = self._client_factory(parsed.host, parsed.port, parsed.fp)
        try:
            info = client.info()
        except ShareError as exc:
            self._dispatch(on_done, exc.code, parsed.host)
            return
        announcement = {
            "id": info["id"], "name": info["name"], "platform": info["platform"],
            "v": info["v"], "vmin": info["vmin"], "port": parsed.port, "fp": client.peer_fp,
            "compatible": info["compatible"],
        }
        self._dispatch(self._add_manual, announcement, parsed.host, on_done)

    def _add_manual(self, announcement, host, on_done):
        discovery = self.service.discovery
        if discovery is None:
            on_done(ErrorCode.UNAVAILABLE, host)
            return
        discovery.add_manual(announcement, host)
        on_done(None, host)

    # -- sending ---------------------------------------------------------

    def _build(self, roms, **kwargs):
        win = self.win
        return build_manifest(
            roms, roms_dir=self.config.get_roms_path(), states_dir=self.config.get_states_dir(),
            catalog=win.core_catalog,
            resolve_core=win.runtime_manager.retroarch_launcher.resolve_core_path,
            config=self.config, playlists=win.playlist_manager, **kwargs,
        )

    def inventory(self, roms, on_done):
        """What ``roms`` would send, without hashing anything; ``on_done(built)``."""
        def worker():
            try:
                built = self._build(roms, hash_limit=-1)
            except Exception:
                logger.exception("share: listing the games failed")
                built = None
            self._dispatch(on_done, built)

        self._run_async(worker)

    def send(self, peer, roms, unchecked, listener):
        """Offer ``roms`` (less ``unchecked``) to ``peer``.

        ``listener`` gets ``on_send_code(code)``, ``on_send_progress(p)`` and
        ``on_send_done(result, report)``, on the main loop -- ``report`` the
        games delivered, ``None`` when nothing was offered. Returns the transfer, which
        ``cancel()`` stops at any point -- while hashing too.
        """
        transfer = _Outgoing(self, peer, listener)
        self.transfer = transfer
        self._cancel_grace()
        self._run_async(self._send_worker, transfer, roms, unchecked)
        return transfer

    def _send_worker(self, transfer, roms, unchecked):
        try:
            built = apply_selection(self._build(roms, cancel=transfer.cancelled), unchecked)
            if transfer.cancelled.is_set():
                raise ShareError(ErrorCode.CANCELLED, "cancelled")
            transfer.core = self.service.send(
                transfer.peer, built,
                on_code=lambda code: self._dispatch(transfer.code, code),
                on_progress=lambda progress: self._dispatch(transfer.progress, progress),
                # Counted here, on the worker: the real build is the one
                # that says which games were offered, and which were dropped.
                on_done=lambda result: self._dispatch(
                    self._send_done, transfer, result, send_report(built, result)),
            )
            if transfer.cancelled.is_set():
                # Cancelled while the send was starting, when there was no
                # core transfer yet for cancel() to reach.
                transfer.core.cancel()
        except ShareError as exc:
            status = exc.code if exc.code == ErrorCode.CANCELLED else "failed"
            result = {"status": status, "sent": [], "skipped": [], "error": exc.code}
            self._dispatch(self._send_done, transfer, result, None)
        except Exception:
            logger.exception("share: preparing the send failed")
            result = {"status": "failed", "sent": [], "skipped": [], "error": ErrorCode.INTERNAL}
            self._dispatch(self._send_done, transfer, result, None)

    def _send_done(self, transfer, result, report):
        if self.transfer is transfer:
            self.transfer = None
        transfer.done(result, report)
        self._maybe_start_grace()

    def open_send(self, roms):
        """The share dialog for ``roms``; the open one again when there is one."""
        from openemux.ui.share_dialog import ShareDialog
        if self.share_dialog is not None:
            self.share_dialog.present(self.win)
            return self.share_dialog
        self.share_dialog = ShareDialog(self, roms)
        self.share_dialog.present(self.win)
        return self.share_dialog

    def open_receive(self):
        return self.open_send(None)

    # -- receiving -------------------------------------------------------

    def _on_offer(self, offer):
        if self.offer_dialog is not None and self.offer_dialog.finished and not self.busy:
            # A result page left open is not an offer in progress: the new
            # one replaces it rather than being declined unseen.
            finished, self.offer_dialog = self.offer_dialog, None
            finished.force_close()
        if self.busy or self.offer_dialog is not None:
            # One transfer at a time; the core already refuses a second
            # pending offer, this covers one arriving while sending.
            self.decline(offer.offer_id)
            return
        from openemux.ui.share_offer import IncomingOfferDialog
        # The grace period must not stop the service under an open offer.
        self._cancel_grace()
        self.offer_dialog = IncomingOfferDialog(self, offer)
        self.offer_dialog.present(self.win)
        if not self.win.is_active():
            self._notify_offer(offer)

    def _notify_offer(self, offer):
        app = self.win.get_application()
        if app is None:
            return
        notification = Gio.Notification.new(self.win.t("share.offer.title"))
        notification.set_body(self.win.t("share.offer.notification", device=offer.sender.get("name", "")))
        app.send_notification("share-offer", notification)

    def offer_closed(self, dialog):
        if self.offer_dialog is dialog:
            self.offer_dialog = None
        app = self.win.get_application()
        # A finished dialog replaced by a new offer closes after it: the
        # notification is the new offer's by then.
        if app is not None and self.offer_dialog is None:
            app.withdraw_notification("share-offer")
        self._maybe_start_grace()

    def _on_remote_cancel(self, offer_id):
        dialog = self.offer_dialog
        if dialog is not None and dialog.offer.offer_id == offer_id:
            dialog.on_remote_cancel()

    def plan(self, offer, overrides=None):
        """What accepting ``offer`` would do, with the user's per-item choices."""
        return self.service.prepare_receive(offer, overrides=dict(overrides or {}))

    def probe(self, offer):
        """The plan that names every file a conflict would replace."""
        return self.service.prepare_receive(offer, policies=PROBE_POLICIES)

    def decline(self, offer_id):
        try:
            self.service.answer(offer_id, False)
        except ShareError as exc:
            # Already expired or cancelled: nothing left to decline.
            logger.debug("share: decline of %s not delivered: %s", offer_id, exc.code)

    def accept(self, offer, plan, listener):
        """Receive ``offer`` as ``plan`` says.

        Raises ``ShareError`` -- ``too_large`` when the space ran out since the
        plan was made. ``listener`` gets ``on_receive_progress`` and
        ``on_receive_done``.
        """
        transfer = _Incoming(self, offer, plan, listener)
        hooks = ManagerLibraryHooks(self.win.playlist_manager, self.config)
        shader_ids = [shader_id for shader_id, _label in self.win.shader_catalog.get_options(show_all=True)]
        # Registered first: a transfer with nothing to upload ends inside accept().
        self.transfer = transfer
        self._cancel_grace()
        try:
            transfer.core = self.service.accept(
                offer.offer_id, plan, hooks,
                shader_ids=shader_ids,
                on_progress=lambda progress: self._dispatch(listener.on_receive_progress, progress),
                on_done=lambda result: self._dispatch(self._receive_done, transfer, result),
            )
        except ShareError:
            self.transfer = None
            raise
        return transfer

    def _receive_done(self, transfer, result):
        if self.transfer is transfer:
            self.transfer = None
        if result.get("status") == "done":
            self._refresh_library(transfer.plan)
        transfer.listener.on_receive_done(result)
        self._maybe_start_grace()

    def _refresh_library(self, plan):
        consoles = sorted({
            game.console for game in plan.games
            if any(decision.action == ACTION_SEND for decision in game.decisions)
        })
        if len(consoles) == 1:
            self.win._rescan_single_console(consoles[0])
        elif consoles:
            self.win._rescan_all_consoles()

    def cancel_incoming(self, offer_id):
        self.service.cancel(offer_id)

    def result_counts(self, result):
        """The files a finished receive replaced, as text, or ``""``.

        What was skipped is no file count: the result page lists the games
        that did not arrive, by title.
        """
        count = len(result.get("replaced") or ())
        if not count:
            return ""
        return plural(self.win.t, count, "share.result.replaced.one", "share.result.replaced.many")


class _Outgoing:
    """A send, from hashing the games to the end of the upload."""

    def __init__(self, coordinator, peer, listener):
        self.coordinator = coordinator
        self.peer = peer
        self.listener = listener
        self.cancelled = threading.Event()
        self.core = None

    def cancel(self):
        self.cancelled.set()
        if self.core is not None:
            self.core.cancel()

    def code(self, code):
        self.listener.on_send_code(code)

    def progress(self, progress):
        self.listener.on_send_progress(progress)

    def done(self, result, report):
        self.listener.on_send_done(result, report)


class _Incoming:
    def __init__(self, coordinator, offer, plan, listener):
        self.coordinator = coordinator
        self.offer = offer
        self.plan = plan
        self.listener = listener
        self.core = None

    def cancel(self):
        self.coordinator.cancel_incoming(self.offer.offer_id)
