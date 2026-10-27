"""The Share nearby coordinator on a real window (#589).

Discoverable only while a share screen is open, plus 30 s; one transfer at a
time; every core callback reaches the window through ``dispatch``; and a
receive refreshes the library without a manual rescan.
"""

from unittest import mock

from openemux.core.share import address as share_address
from openemux.core.share.placement import ReceivePlan
from openemux.core.share.protocol import ErrorCode, ShareError
from openemux.ui import share_coordinator as coordinator_module
from openemux.ui.share_coordinator import (
    GRACE_SECONDS,
    STATE_FAILED,
    STATE_RUNNING,
    STATE_STARTING,
    STATE_STOPPED,
    ShareCoordinator,
)
from tests.gtk_display import needs_display
from tests.share_ui_fixtures import FP, FakeClient, install, offer, peer
from tests.test_share_placement import game, item
from tests.window_harness import WindowCase


class _Screen:
    def __init__(self):
        self.states = 0
        self.peers = 0

    def on_share_state(self):
        self.states += 1

    def on_peers_changed(self):
        self.peers += 1


@needs_display
class VisibilityTests(WindowCase):
    def setUp(self):
        super().setUp()
        self.share = install(self)

    def test_nothing_listens_until_a_screen_opens(self):
        self.assertEqual(self.service.calls, [])
        screen = _Screen()
        self.share.open_screen(screen)
        self.share.open_screen(screen)
        self.assertEqual(self.service.calls, ["start"])
        self.assertEqual(self.share.state, STATE_RUNNING)
        self.assertGreaterEqual(screen.states, 2)
        self.assertEqual(screen.peers, 1)

    def test_it_stops_thirty_seconds_after_the_last_screen_closes(self):
        first, second = _Screen(), _Screen()
        self.share.open_screen(first)
        self.share.open_screen(second)
        self.share.close_screen(first)
        self.assertFalse(self.timers.has(GRACE_SECONDS))
        self.share.close_screen(second)
        self.share.close_screen(second)
        self.assertTrue(self.timers.has(GRACE_SECONDS))
        self.timers.fire(GRACE_SECONDS)
        self.assertEqual(self.service.calls, ["start", "stop"])
        self.assertEqual(self.share.state, STATE_STOPPED)
        # Closed and stopped: nothing to wait for any more.
        self.share._maybe_start_grace()
        self.assertFalse(self.timers.has(GRACE_SECONDS))

    def test_reopening_within_the_grace_keeps_it_running(self):
        screen = _Screen()
        self.share.open_screen(screen)
        self.share.close_screen(screen)
        self.share.open_screen(screen)
        self.assertFalse(self.timers.has(GRACE_SECONDS))
        self.assertEqual(len(self.timers.removed), 1)
        self.assertEqual(self.service.calls, ["start"])

    def test_a_running_transfer_holds_the_grace_until_it_ends(self):
        screen = _Screen()
        self.share.open_screen(screen)
        self.share.transfer = object()
        self.share.close_screen(screen)
        self.assertFalse(self.timers.has(GRACE_SECONDS))
        self.share.transfer = None
        self.share._maybe_start_grace()
        self.assertTrue(self.timers.has(GRACE_SECONDS))
        # A grace that ends while a transfer runs again stops nothing.
        self.share.transfer = object()
        self.timers.fire(GRACE_SECONDS)
        self.assertEqual(self.service.calls, ["start"])

    def test_a_grace_ending_mid_start_stops_once_started(self):
        started = []
        share = install(self, run_async=lambda func, *args: started.append((func, args)))
        screen = _Screen()
        share.open_screen(screen)
        self.assertEqual(share.state, STATE_STARTING)
        share.close_screen(screen)
        self.timers.fire(GRACE_SECONDS)
        self.assertEqual(self.service.calls, [])
        func, args = started.pop(0)
        func(*args)
        self.assertEqual(share.state, STATE_STOPPED)
        stop, stop_args = started.pop(0)
        stop(*stop_args)
        self.assertEqual(self.service.calls, ["start", "stop"])

    def test_a_stop_queued_by_the_grace_skips_a_service_reopened_meanwhile(self):
        queued = []
        share = install(self, run_async=lambda func, *args: queued.append((func, args)))
        screen = _Screen()
        share.open_screen(screen)
        func, args = queued.pop(0)
        func(*args)
        share.close_screen(screen)
        self.timers.fire(GRACE_SECONDS)
        stop, stop_args = queued.pop(0)
        # Reopened before the stop thread ran: the stop must leave it running.
        share.open_screen(screen)
        stop(*stop_args)
        self.assertEqual(self.service.calls, ["start"])
        start, start_args = queued.pop(0)
        start(*start_args)
        self.assertEqual(share.state, STATE_RUNNING)

    def test_a_failed_start_is_reported(self):
        self.service.start_error = ShareError(ErrorCode.INTERNAL, "port")
        screen = _Screen()
        self.share.open_screen(screen)
        self.assertEqual((self.share.state, self.share.error), (STATE_FAILED, ErrorCode.INTERNAL))
        self.share.close_screen(screen)
        self.assertFalse(self.timers.has(GRACE_SECONDS))

    def test_a_crash_in_start_is_reported_as_internal(self):
        self.service.start_error = RuntimeError("boom")
        self.share.open_screen(_Screen())
        self.assertEqual(self.share.error, ErrorCode.INTERNAL)

    def test_without_the_dependencies_nothing_starts(self):
        with mock.patch.object(
            ShareCoordinator, "availability", lambda self: {"share": "unavailable:cryptography"}
        ):
            self.share.open_screen(_Screen())
        self.assertEqual((self.share.state, self.share.error), (STATE_FAILED, ErrorCode.UNAVAILABLE))
        self.assertEqual(self.service.calls, [])

    def test_shutdown_stops_at_once_and_cancels_the_transfer(self):
        self.share.open_screen(_Screen())
        transfer = mock.Mock()
        self.share.transfer = transfer
        self.share._grace = self.timers.add(GRACE_SECONDS, lambda: False)
        self.share.shutdown()
        transfer.cancel.assert_called_once_with()
        self.assertEqual(self.service.calls, ["start", "stop"])
        self.assertIsNone(self.share.transfer)

    def test_the_app_shuts_the_coordinator_down(self):
        from openemux.app import OpenEmuxApplication
        app = mock.Mock(main_window=self.win)
        self.share.open_screen(_Screen())
        with mock.patch("openemux.app.Adw.Application.do_shutdown"):
            OpenEmuxApplication.do_shutdown(app)
        self.assertEqual(self.service.calls, ["start", "stop"])

    def test_the_window_builds_one_coordinator_lazily(self):
        self.win._share_coordinator = None
        first = self.win.share
        self.assertIsInstance(first, ShareCoordinator)
        self.assertIs(self.win.share, first)
        self.assertFalse(first.service.running)


@needs_display
class AvailabilityTests(WindowCase):
    def test_availability_is_the_core_one(self):
        share = ShareCoordinator(self.win, service_factory=mock.Mock())
        with mock.patch.object(coordinator_module, "availability", return_value={"share": "x"}):
            self.assertEqual(share.availability(), {"share": "x"})


@needs_display
class ReadingTests(WindowCase):
    def setUp(self):
        super().setUp()
        self.share = install(self)

    def test_identity_name_and_address(self):
        self.assertIsNone(self.share.address())
        self.assertIsNone(self.share.identity)
        self.config.set_share_device_name("Den")
        self.assertEqual(self.share.device_name(), "Den")
        self.share.open_screen(_Screen())
        self.assertEqual(self.share.device_name(), "QA Box")
        host, port, fp, uri = self.share.address()
        self.assertEqual((host, port, fp), ("192.168.1.20", 53319, FP))
        self.assertEqual(share_address.parse(uri), share_address.Address("192.168.1.20", 53319, FP))
        self.assertIs(self.share.identity, self.service.identity)

    def test_no_lan_address_falls_back_to_loopback(self):
        share = install(self, addresses=lambda: [])
        share.open_screen(_Screen())
        self.assertEqual(share.address()[0], "127.0.0.1")

    def test_peers_changed_reaches_every_screen(self):
        screen = _Screen()
        self.share.open_screen(screen)
        self.service.peer_list = [peer()]
        before = screen.peers
        self.service.on_peers_changed()
        self.assertEqual(screen.peers, before + 1)
        self.assertEqual(self.share.peers(), [peer()])
        # A screen without the handler is skipped.
        self.share.open_screen(object())
        self.service.on_peers_changed()


@needs_display
class ConnectByAddressTests(WindowCase):
    def setUp(self):
        super().setUp()
        self.share = install(self)
        self.share.open_screen(_Screen())
        self.answers = []
        FakeClient.answers = {
            "10.0.0.9": {"id": "c" * 32, "name": "Laptop", "platform": "desktop", "v": 1, "vmin": 1,
                         "compatible": True},
            "10.0.0.8": ShareError(ErrorCode.UNREACHABLE, "no route"),
        }
        self.addCleanup(setattr, FakeClient, "answers", {})

    def connect(self, text):
        self.share.connect_address(text, lambda error, host: self.answers.append((error, host)))
        return self.answers[-1]

    def test_a_reachable_device_joins_the_peers(self):
        self.assertEqual(self.connect("10.0.0.9:53400"), (None, "10.0.0.9"))
        announcement, host = self.service.discovery.manual[0]
        self.assertEqual(host, "10.0.0.9")
        self.assertEqual((announcement["port"], announcement["fp"], announcement["name"]), (53400, FP, "Laptop"))

    def test_errors_come_back_with_their_code(self):
        self.assertEqual(self.connect("not an address"), (ErrorCode.BAD_REQUEST, None))
        self.assertEqual(self.connect("10.0.0.8"), (ErrorCode.UNREACHABLE, "10.0.0.8"))

    def test_a_service_stopped_meanwhile_is_unavailable(self):
        self.service.discovery = None
        self.assertEqual(self.connect("10.0.0.9"), (ErrorCode.UNAVAILABLE, "10.0.0.9"))


class _Listener:
    def __init__(self):
        self.codes, self.progress, self.done = [], [], []

    def on_send_code(self, code):
        self.codes.append(code)

    def on_send_progress(self, progress):
        self.progress.append(progress)

    def on_send_done(self, result):
        self.done.append(result)

    def on_receive_progress(self, progress):
        self.progress.append(progress)

    def on_receive_done(self, result):
        self.done.append(result)


@needs_display
class SendTests(WindowCase):
    def setUp(self):
        super().setUp()
        self.share = install(self)
        self.share.open_screen(_Screen())
        self.listener = _Listener()

    def test_inventory_lists_without_hashing(self):
        got = []
        self.share.inventory([self.rom()], got.append)
        game = got[0].manifest["games"][0]
        self.assertNotIn("sha256", game["items"][0])

    def test_a_failed_inventory_hands_back_none(self):
        got = []
        with mock.patch.object(coordinator_module, "build_manifest", side_effect=OSError("gone")):
            self.share.inventory([self.rom()], got.append)
        self.assertEqual(got, [None])

    def test_send_hashes_drops_the_unchecked_and_relays_the_callbacks(self):
        rom = self.rom()
        transfer = self.share.send(peer(), [rom], {(rom["path"], "details")}, self.listener)
        self.assertTrue(self.share.busy)
        target, built, callbacks = self.service.sent
        self.assertEqual(target, peer())
        self.assertIn("sha256", built.manifest["games"][0]["items"][0])
        callbacks["on_code"]("482913")
        callbacks["on_progress"]({"done_bytes": 1})
        self.assertEqual(self.listener.codes, ["482913"])
        self.assertEqual(self.listener.progress, [{"done_bytes": 1}])
        transfer.cancel()
        self.assertEqual(self.service.outgoing.cancelled, 1)
        callbacks["on_done"]({"status": "cancelled"})
        self.assertEqual(self.listener.done, [{"status": "cancelled"}])
        self.assertFalse(self.share.busy)

    def test_a_cancel_while_hashing_never_offers(self):
        rom = self.rom()

        def build(*args, cancel=None, **kwargs):
            cancel.set()
            return real_build(*args, cancel=None, **kwargs)

        real_build = coordinator_module.build_manifest
        with mock.patch.object(coordinator_module, "build_manifest", build):
            self.share.send(peer(), [rom], set(), self.listener)
        self.assertIsNone(self.service.sent)
        self.assertEqual(self.listener.done[0]["status"], ErrorCode.CANCELLED)

    def test_a_cancel_while_the_send_starts_reaches_the_core_transfer(self):
        real_send = self.service.send
        holder = {}

        def send(peer, built, **callbacks):
            holder["transfer"].cancel()
            return real_send(peer, built, **callbacks)

        with mock.patch.object(self.service, "send", send):
            holder["transfer"] = transfer = coordinator_module._Outgoing(self.share, peer(), self.listener)
            self.share._send_worker(transfer, [self.rom()], set())
        self.assertEqual(self.service.outgoing.cancelled, 1)

    def test_a_failed_send_ends_with_its_code(self):
        self.service.send_error = ShareError(ErrorCode.UNAVAILABLE, "stopped")
        self.share.send(peer(), [self.rom()], set(), self.listener)
        self.assertEqual(self.listener.done[0], {"status": "failed", "sent": [], "skipped": [],
                                                 "error": ErrorCode.UNAVAILABLE})

    def test_a_crash_while_preparing_is_internal(self):
        with mock.patch.object(coordinator_module, "build_manifest", side_effect=RuntimeError):
            self.share.send(peer(), [self.rom()], set(), self.listener)
        self.assertEqual(self.listener.done[0]["error"], ErrorCode.INTERNAL)

    def test_a_late_result_of_an_old_send_leaves_the_current_one(self):
        first = self.share.send(peer(), [self.rom()], set(), self.listener)
        callbacks = self.service.sent[2]
        second = self.share.send(peer(), [self.rom()], set(), _Listener())
        callbacks["on_done"]({"status": "done"})
        self.assertIs(self.share.transfer, second)
        self.assertIsNot(first, second)

    def test_open_send_re_presents_the_open_dialog(self):
        first = self.share.open_send([self.rom()])
        self.assertIs(self.share.open_send([self.rom()]), first)
        self.assertEqual(self.presented, [first, first])
        self.share.close_screen(first)
        self.assertIsNone(self.share.share_dialog)


@needs_display
class ReceiveTests(WindowCase):
    def setUp(self):
        super().setUp()
        self.share = install(self)
        self.share.open_screen(_Screen())
        self.listener = _Listener()
        self.offer = offer([game([item("r", "rom", "New Game.sfc", b"new rom")], title="New Game")])

    def test_an_offer_presents_the_dialog_and_notifies_when_away(self):
        app = mock.Mock()
        with mock.patch.object(self.win, "is_active", return_value=False), \
                mock.patch.object(self.win, "get_application", return_value=app):
            self.service.on_offer(self.offer)
            dialog = self.share.offer_dialog
            self.assertIs(self.presented[-1], dialog)
            app.send_notification.assert_called_once()
            self.assertEqual(app.send_notification.call_args.args[0], "share-offer")
            self.share.offer_closed(dialog)
        app.withdraw_notification.assert_called_once_with("share-offer")
        self.assertIsNone(self.share.offer_dialog)

    def test_no_notification_while_the_window_is_in_front_or_without_an_app(self):
        with mock.patch.object(self.win, "is_active", return_value=True):
            self.service.on_offer(self.offer)
        self.share.offer_dialog = None
        with mock.patch.object(self.win, "is_active", return_value=False), \
                mock.patch.object(self.win, "get_application", return_value=None):
            self.service.on_offer(self.offer)
            self.share.offer_closed(self.share.offer_dialog)

    def test_an_open_offer_holds_the_service_through_the_grace(self):
        for screen in list(self.share._screens):
            self.share.close_screen(screen)
        self.assertTrue(self.timers.has(GRACE_SECONDS))
        self.service.on_offer(self.offer)
        self.assertFalse(self.timers.has(GRACE_SECONDS))
        self.share._maybe_start_grace()
        self.assertFalse(self.timers.has(GRACE_SECONDS))
        self.share._grace_over()
        self.assertNotIn("stop", self.service.calls)
        self.share.offer_closed(self.share.offer_dialog)
        self.assertTrue(self.timers.has(GRACE_SECONDS))

    def test_an_offer_while_busy_is_declined(self):
        self.share.transfer = object()
        self.service.on_offer(self.offer)
        self.assertIsNone(self.share.offer_dialog)
        self.assertIn(("answer", self.offer.offer_id, False), self.service.calls)

    def test_an_offer_over_a_finished_one_replaces_it(self):
        self.service.on_offer(self.offer)
        first = self.share.offer_dialog
        first.result = object()
        with mock.patch.object(first, "force_close") as force_close:
            self.service.on_offer(self.offer)
        force_close.assert_called_once_with()
        self.assertIsNot(self.share.offer_dialog, first)
        self.assertIs(self.presented[-1], self.share.offer_dialog)
        self.assertNotIn(("answer", self.offer.offer_id, False), self.service.calls)

    def test_a_replaced_dialog_closing_late_keeps_the_new_notification(self):
        self.service.on_offer(self.offer)
        first = self.share.offer_dialog
        first.result = object()
        app = mock.Mock()
        with mock.patch.object(first, "force_close"), \
                mock.patch.object(self.win, "get_application", return_value=app):
            self.service.on_offer(self.offer)
            self.share.offer_closed(first)
        app.withdraw_notification.assert_not_called()
        self.assertIsNotNone(self.share.offer_dialog)

    def test_an_offer_over_one_still_open_is_declined(self):
        self.service.on_offer(self.offer)
        first = self.share.offer_dialog
        self.service.on_offer(self.offer)
        self.assertIs(self.share.offer_dialog, first)
        self.assertIn(("answer", self.offer.offer_id, False), self.service.calls)

    def test_a_decline_after_expiry_is_quiet(self):
        self.service.answer_error = ShareError(ErrorCode.NOT_FOUND, "gone")
        self.share.decline("x")

    def test_remote_cancel_reaches_only_the_dialog_of_that_offer(self):
        dialog = mock.Mock(offer=self.offer)
        self.share.offer_dialog = dialog
        self.service.on_cancel("other")
        dialog.on_remote_cancel.assert_not_called()
        self.service.on_cancel(self.offer.offer_id)
        dialog.on_remote_cancel.assert_called_once_with()
        self.share.offer_dialog = None
        self.service.on_cancel(self.offer.offer_id)

    def test_accept_wires_hooks_and_shaders_then_refreshes_one_console(self):
        plan = self.share.plan(self.offer)
        transfer = self.share.accept(self.offer, plan, self.listener)
        offer_id, used_plan, hooks, kwargs = self.service.accepted
        self.assertIs(used_plan, plan)
        self.assertIs(hooks.playlists, self.win.playlist_manager)
        self.assertIn("shader_ids", kwargs)
        kwargs["on_progress"]({"done_bytes": 3})
        self.assertEqual(self.listener.progress, [{"done_bytes": 3}])
        transfer.cancel()
        self.assertIn(("cancel", offer_id), self.service.calls)
        with mock.patch.object(self.win, "_rescan_single_console") as single:
            kwargs["on_done"]({"status": "done", "placed": [], "replaced": [], "skipped": []})
        single.assert_called_once_with("SFC")
        self.assertFalse(self.share.busy)
        self.assertEqual(self.listener.done[0]["status"], "done")

    def test_a_refused_accept_leaves_nothing_running(self):
        self.service.accept_error = ShareError(ErrorCode.TOO_LARGE, "full")
        with self.assertRaises(ShareError):
            self.share.accept(self.offer, self.share.plan(self.offer), self.listener)
        self.assertFalse(self.share.busy)

    def test_a_receive_over_several_consoles_rescans_the_library(self):
        two = offer([
            game([item("a", "rom", "A.sfc", b"a")], title="A"),
            game([item("b", "rom", "B.nes", b"b")], game_id="g2", console="FC", title="B"),
        ])
        self.share.accept(two, self.share.plan(two), self.listener)
        with mock.patch.object(self.win, "_rescan_all_consoles") as everything:
            self.service.accepted[3]["on_done"]({"status": "done"})
        everything.assert_called_once_with()

    def test_a_failed_or_empty_receive_rescans_nothing(self):
        self.share.accept(self.offer, self.share.plan(self.offer), self.listener)
        on_done = self.service.accepted[3]["on_done"]
        self.share.transfer = None
        with mock.patch.object(self.win, "_rescan_single_console") as single:
            on_done({"status": "failed"})
            self.share._refresh_library(ReceivePlan([]))
        single.assert_not_called()

    def test_plans_and_counts(self):
        self.assertEqual(len(self.share.probe(self.offer).decisions()), 1)
        self.assertEqual(self.share.result_counts({}), "")
        self.assertEqual(
            self.share.result_counts({"replaced": ["a"], "skipped": [{}, {}]}),
            "1 file replaced · 2 files skipped",
        )
