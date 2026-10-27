"""The Share Nearby dialog, state by state (#589).

Searching, devices (and the incompatible ones), nothing found, unavailable,
What to Send, Connect by Address, waiting, progress, the result and the
receive-only mode -- on a real window, over the fake service.
"""

from pathlib import Path
from unittest import mock

from tests.gtk_display import HAVE_DISPLAY, needs_display
from tests.share_ui_fixtures import texts, FP, FakeClient, install, peer
from tests.window_harness import WindowCase

if HAVE_DISPLAY:
    from gi.repository import Adw, GdkPixbuf, Gtk

    from openemux.core.share.protocol import ErrorCode, ShareError
    from openemux.ui import share_dialog as dialog_module
    from openemux.ui.share_coordinator import STATE_FAILED, ShareCoordinator
    from openemux.ui.share_dialog import NOTHING_FOUND_SECONDS, ShareDialog


def tag(dialog):
    return dialog.nav.get_visible_page().get_tag()


def png():
    pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 4, 4)
    pixbuf.fill(0xFFFFFFFF)
    ok, data = pixbuf.save_to_bufferv("png", [], [])
    return bytes(data)


class _DialogCase(WindowCase):
    library = {"SFC": ["Chrono Trigger.sfc", "Super Metroid.sfc"], "FC": ["Metroid.nes"]}

    def setUp(self):
        super().setUp()
        self.share = install(self)

    def open(self, roms=None):
        roms = [self.rom()] if roms is None else roms
        dialog = self.share.open_send(roms) if roms else self.share.open_receive()
        self.addCleanup(lambda: dialog.emit("closed"))
        return dialog

    def peers(self, *found):
        self.service.peer_list = list(found)
        self.service.on_peers_changed()


@needs_display
class TheRootTests(_DialogCase):
    def test_send_mode_lists_what_and_where(self):
        dialog = self.open()
        self.assertEqual(dialog.get_title(), "Share Nearby")
        self.assertEqual(dialog.root_page.window_title.get_subtitle(), dialog.t(
            "share.subtitle.one", size=dialog_module.format_size(len(b"rom"), dialog.t)))
        self.assertEqual(dialog.what_row.get_subtitle(), "Chrono Trigger · 1 file")
        self.assertTrue(dialog.what_row.get_activatable())
        self.assertTrue(dialog.spinner.get_spinning())
        self.assertEqual(dialog.visible_row.get_title(), "Visible as “QA Box”")
        self.assertEqual(dialog.stack.get_visible_child_name(), "main")

    def test_many_titles_are_summed_up(self):
        roms = [self.rom("SFC", 0), self.rom("SFC", 1), self.rom("FC", 0)]
        with mock.patch.object(dialog_module, "SUMMARY_TITLES", 2):
            dialog = self.open(roms)
        self.assertEqual(dialog.what_row.get_subtitle(), "Chrono Trigger, Super Metroid and 1 more · 3 files")

    def test_devices_compatible_and_not(self):
        dialog = self.open()
        self.peers(peer("Phone"), peer("Old Tab", platform="tablet", compatible=False, v=0))
        rows = {row.get_title(): row for row in dialog._peer_rows}
        self.assertEqual(rows["Phone"].get_subtitle(), "Phone · found by mDNS and beacon")
        self.assertTrue(rows["Phone"].get_sensitive())
        self.assertFalse(rows["Old Tab"].get_sensitive())
        self.assertEqual(
            rows["Old Tab"].get_subtitle(), "Update OpenEmux on this device · version 0, this one speaks 1"
        )
        # Rebuilt, not appended, on the next change.
        self.peers(peer("Phone"))
        self.assertEqual(len(dialog._peer_rows), 1)

    def test_nothing_found_after_the_timeout_and_back_when_a_device_appears(self):
        dialog = self.open()
        self.assertTrue(self.timers.has(NOTHING_FOUND_SECONDS))
        self.timers.fire(NOTHING_FOUND_SECONDS)
        self.assertEqual(dialog.stack.get_visible_child_name(), "empty")
        self.assertIn("TCP 53319 and UDP 53318", texts(dialog.empty))
        self.peers(peer())
        self.assertEqual(dialog.stack.get_visible_child_name(), "main")
        self.assertFalse(dialog.nothing_found)

    def test_devices_known_before_it_opened_are_listed(self):
        # The service kept running from an earlier screen: those devices
        # will not be announced as a change again.
        self.share.open_send([self.rom()]).emit("closed")
        self.service.peer_list = [peer("Phone")]
        dialog = self.open()
        self.assertEqual(self.service.calls.count("start"), 1)
        self.assertEqual([row.get_title() for row in dialog._peer_rows], ["Phone"])
        self.assertEqual(dialog.stack.get_visible_child_name(), "main")

    def test_a_device_before_the_timeout_stops_it(self):
        self.open()
        self.peers(peer())
        self.assertFalse(self.timers.has(NOTHING_FOUND_SECONDS))

    def test_unavailable_names_the_missing_component(self):
        with mock.patch.object(
            ShareCoordinator, "availability", lambda self: {"share": "unavailable:cryptography"}
        ):
            dialog = self.open()
            dialog.on_peers_changed()
        self.assertEqual(dialog.stack.get_visible_child_name(), "unavailable")
        self.assertIn("(cryptography)", dialog.unavailable.get_description())

    def test_a_service_that_failed_to_start(self):
        self.service.start_error = ShareError(ErrorCode.INTERNAL, "port")
        dialog = self.open()
        self.assertEqual(self.share.state, STATE_FAILED)
        self.assertEqual(dialog.unavailable.get_description(), dialog.t("share.unavailable.failed"))

    def test_receive_mode_has_no_send_sections(self):
        dialog = self.open(roms=[])
        self.assertEqual(dialog.get_title(), "Receive Games")
        self.assertEqual(dialog.mode, "receive")
        self.assertIn("“QA Box”", dialog.ready.get_description())
        dialog.on_peers_changed()
        self.assertFalse(self.timers.has(NOTHING_FOUND_SECONDS))

    def test_closing_releases_the_screen_and_the_timer(self):
        dialog = self.share.open_send([self.rom()])
        dialog.emit("closed")
        self.assertIsNone(self.share.share_dialog)
        self.assertFalse(self.timers.has(NOTHING_FOUND_SECONDS))


@needs_display
class WhatToSendTests(_DialogCase):
    def setUp(self):
        super().setUp()
        sfc = self.home.console_dir("SFC")
        (sfc / "Chrono Trigger.srm").write_bytes(b"save")
        state_dir = Path(self.config.get_states_dir()) / "SFC"
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "Chrono Trigger.state1").write_bytes(b"s1")
        self.playlist_favorite = self.win.playlist_manager.toggle_favorite(self.rom())
        odd = {"name": "Odd", "path": str(self.tmp / "Odd.bin"), "console": "XX"}
        self.dialog = self.open([self.rom(), self.rom("FC", 0), odd])
        self.dialog._push_what()
        self.key = self.rom()["path"]

    def test_each_game_lists_its_groups(self):
        parent, children = self.dialog._game_checks[self.key]
        self.assertEqual(list(children), ["game", "battery", "states", "details"])
        self.assertTrue(parent.get_active())
        self.assertEqual(children["states"][0].get_subtitle(),
                         "1 state · sent only if the other device has the same core")
        self.assertTrue(children["battery"][0].get_subtitle().startswith("Saved "))
        self.assertEqual(children["details"][0].get_subtitle(), "Favorite, cartridge color, core and shader")
        self.assertEqual(tag(self.dialog), "what")

    def test_unchecking_a_group_mixes_the_parent_and_shrinks_the_total(self):
        before = self.dialog.total_label.get_label()
        parent, children = self.dialog._game_checks[self.key]
        children["battery"][1].set_active(False)
        self.assertTrue(parent.get_inconsistent())
        self.assertIn((self.key, "battery"), self.dialog.unchecked)
        self.assertNotEqual(self.dialog.total_label.get_label(), before)
        children["battery"][1].set_active(True)
        self.assertFalse(parent.get_inconsistent())

    def test_the_parent_toggles_the_whole_game(self):
        parent, children = self.dialog._game_checks[self.key]
        parent.set_active(False)
        self.assertIn((self.key, "game"), self.dialog.unchecked)
        self.assertFalse(children["battery"][0].get_sensitive())
        self.assertTrue(children["game"][0].get_sensitive())
        parent.set_active(True)
        self.assertEqual(self.dialog.unchecked, set())

    def test_nothing_selected_disables_the_devices(self):
        self.peers(peer())
        for key, (parent, _children) in self.dialog._game_checks.items():
            parent.set_active(False)
        row = self.dialog._peer_rows[0]
        self.assertFalse(row.get_sensitive())
        self.assertEqual(row.get_tooltip_text(), "Choose something to send")
        self.assertEqual(self.dialog.what_row.get_subtitle(), "0 files")

    def test_excluded_games_are_listed_with_the_reason(self):
        self.assertIn("Can't be sent: this console isn't supported for sharing", texts(self.dialog.what_page))

    def test_done_pops_back_and_forgets_the_page(self):
        self.dialog.nav.pop()
        self.assertEqual(tag(self.dialog), "root")
        self.assertIsNone(self.dialog.what_page)

    def test_group_details(self):
        detail = self.dialog._group_detail
        self.assertEqual(detail("game", {"name": "A.cue", "count": 3, "size": 2000}), "3 files · 2 kB")
        self.assertEqual(detail("game", {"name": "A.sfc", "count": 1, "size": 5}), "A.sfc · 5 B")
        self.assertEqual(detail("cover", {"name": "A.png", "count": 1, "size": 1000}), "1 kB")

    def test_a_failed_inventory_leaves_nothing_to_send(self):
        self.dialog._on_inventory(None)
        self.assertEqual(self.dialog.what_row.get_subtitle(), "0 files")


@needs_display
class ConnectByAddressTests(_DialogCase):
    def setUp(self):
        super().setUp()
        self.dialog = self.open()
        FakeClient.answers = {
            "10.0.0.9": {"id": "c" * 32, "name": "Laptop", "platform": "desktop", "v": 1, "vmin": 1,
                         "compatible": True},
            "10.0.0.8": ShareError(ErrorCode.UNREACHABLE, "no route"),
            "10.0.0.7": ShareError(ErrorCode.FINGERPRINT_MISMATCH, "other cert"),
            "10.0.0.6": ShareError(ErrorCode.INCOMPATIBLE_VERSION, "v9"),
            "10.0.0.5": ShareError(ErrorCode.BUSY, "busy"),
        }
        self.addCleanup(setattr, FakeClient, "answers", {})

    def test_this_device_shows_its_address_and_qr(self):
        with mock.patch.object(dialog_module.qr, "png_bytes", return_value=png()):
            self.dialog._push_address()
        self.assertEqual(self.dialog.host_row.get_subtitle(), "192.168.1.20:53319")
        self.assertEqual(self.dialog.fp_row.get_subtitle(), " ".join(["ab12"] * 16))
        self.assertEqual(self.dialog.fp_row.get_tooltip_text(), FP)
        self.assertTrue(self.dialog.qr_picture.get_visible())
        self.assertIsNotNone(self.dialog.qr_picture.get_paintable())

    def test_without_segno_the_qr_hides_and_the_text_stays(self):
        with mock.patch.object(dialog_module.qr, "png_bytes", return_value=None):
            self.dialog._push_address()
        self.assertFalse(self.dialog.qr_picture.get_visible())
        self.assertEqual(self.dialog.host_row.get_subtitle(), "192.168.1.20:53319")

    def test_copy_puts_the_full_uri_on_the_clipboard(self):
        self.dialog._push_address()
        toasts = []
        with mock.patch.object(self.dialog.toasts, "add_toast", lambda toast: toasts.append(toast.get_title())), \
                mock.patch.object(Gtk.Widget, "get_clipboard") as clipboard:
            self.dialog._copy_address()
        clipboard.return_value.set.assert_called_once_with(self.share.address()[3])
        self.assertEqual(toasts, ["Address copied"])

    def test_before_the_service_listens_there_is_no_address(self):
        self.service.server = None
        self.dialog._push_address()
        self.assertEqual(self.dialog.host_row.get_subtitle(), "…")
        self.assertFalse(self.dialog.copy_button.get_sensitive())
        self.dialog._copy_address()

    def connect(self, text):
        self.dialog.address_entry.set_text(text)
        self.dialog.address_entry.emit("apply")
        return self.dialog.address_error.get_label() if self.dialog.address_error.get_visible() else None

    def test_errors_show_under_the_entry(self):
        self.dialog._push_address()
        self.assertEqual(self.connect("abc def"), "That doesn't look like an address.")
        self.assertEqual(
            self.connect("10.0.0.8"),
            "Couldn't reach 10.0.0.8. Check the address and that Share Nearby is open there.",
        )
        self.assertEqual(self.connect("10.0.0.7"), "That device answered with a different fingerprint.")
        self.assertIn("can't talk to this one", self.connect("10.0.0.6"))
        self.assertEqual(self.connect("10.0.0.5"), self.dialog.t("share.error.generic"))
        self.assertTrue(self.dialog.address_entry.get_sensitive())
        self.assertTrue(self.dialog.address_entry.get_editable())

    def test_the_entry_keeps_the_focus_while_connecting(self):
        # Insensitive, it would drop the focus and the next keys would reach
        # the library behind the dialog.
        self.dialog._push_address()
        seen = []
        with mock.patch.object(self.share, "connect_address", lambda text, on_done: seen.append((
                self.dialog.address_entry.get_sensitive(), self.dialog.address_entry.get_editable()))):
            self.dialog.address_entry.emit("apply")
            # A second Enter while the first is still out does nothing.
            self.dialog.address_entry.emit("apply")
        self.assertEqual(seen, [(True, False)])

    def test_success_adds_the_device_and_goes_back(self):
        self.dialog._push_address()
        self.assertIsNone(self.connect("10.0.0.9"))
        self.assertEqual(tag(self.dialog), "root")
        self.assertEqual(self.service.discovery.manual[0][1], "10.0.0.9")
        self.assertEqual(self.dialog.address_entry.get_text(), "")

    def test_an_answer_after_the_page_closed_is_dropped(self):
        self.dialog._push_address()
        self.dialog.nav.pop()
        self.assertIsNone(self.dialog.address_page)
        self.dialog._on_address_connected(None, "10.0.0.9")

    def test_the_empty_state_button_opens_the_page(self):
        self.timers.fire(NOTHING_FOUND_SECONDS)
        self.dialog._push_address()
        self.assertEqual(tag(self.dialog), "address")
        self.dialog.on_share_state()


@needs_display
class SendingTests(_DialogCase):
    def setUp(self):
        super().setUp()
        self.dialog = self.open()
        self.peers(peer("Phone"))

    def start(self):
        self.dialog._peer_rows[0].emit("activated")
        return self.service.sent[2]

    def test_waiting_then_code_then_progress_then_sent(self):
        callbacks = self.start()
        self.assertEqual(tag(self.dialog), "waiting")
        self.assertFalse(self.dialog.get_can_close())
        self.assertIs(self.dialog.get_focus(), self.dialog.waiting.cancel_button)
        # A page that cannot pop makes the navigation view eat Escape.
        self.assertTrue(self.dialog.waiting.page.get_can_pop())
        self.assertEqual(self.dialog.waiting.title.get_label(), "Preparing the games…")
        callbacks["on_code"]("482913")
        self.assertEqual(self.dialog.waiting.title.get_label(), "Waiting for Phone to accept…")
        self.assertEqual(self.dialog.waiting.code.get_label(), "482 913")
        callbacks["on_progress"]({"name": "Chrono Trigger.sfc", "done_bytes": 500_000, "total_bytes": 1_000_000,
                                  "files_done": 0, "file_count": 2})
        self.assertEqual(tag(self.dialog), "progress")
        progress = self.dialog.progress
        self.assertIs(self.dialog.get_focus(), progress.cancel_button)
        self.assertTrue(progress.page.get_can_pop())
        self.assertAlmostEqual(progress.bar.get_fraction(), 0.5)
        self.assertEqual(progress.bytes.get_label(), "500 kB of 1.0 MB")
        self.assertEqual(progress.files.get_label(), "File 1 of 2")
        callbacks["on_progress"]({"name": "x", "done_bytes": 0, "total_bytes": 0, "files_done": 2, "file_count": 2})
        self.assertEqual(progress.bar.get_fraction(), 0.0)
        self.assertEqual(progress.files.get_label(), "File 2 of 2")
        callbacks["on_done"]({"status": "done", "sent": ["g1i1"], "skipped": []})
        self.assertEqual(tag(self.dialog), "result")
        self.assertTrue(self.dialog.get_can_close())
        self.assertIs(self.dialog.get_focus(), self.dialog.result.close_button)
        self.assertTrue(self.dialog.result.get_can_pop())
        self.assertEqual(self.dialog.nav.get_navigation_stack().get_n_items(), 1)
        self.assertEqual(_status(self.dialog).get_title(), "1 Game Sent")
        self.assertEqual(_status(self.dialog).get_description(), "Phone has them now.")

    def test_each_failure_has_its_title(self):
        self.start()
        for result, title in (
            ({"status": "declined"}, "Offer Declined"),
            ({"status": "expired"}, "Offer Expired"),
            ({"status": "cancelled"}, "Transfer Cancelled"),
            ({"status": "failed", "error": "unreachable"}, "Can't Connect"),
            ({"status": "failed", "error": "source_changed"}, "Transfer Failed"),
        ):
            with self.subTest(result=result):
                self.dialog.on_send_done(result)
                self.assertEqual(_status(self.dialog).get_title(), title)

    def test_cancel_buttons_cancel_the_transfer(self):
        callbacks = self.start()
        self.dialog.waiting.cancel_button.emit("clicked")
        self.assertEqual(self.service.outgoing.cancelled, 1)
        callbacks["on_progress"]({"name": "x", "done_bytes": 1, "total_bytes": 2, "files_done": 0, "file_count": 1})
        self.dialog.progress.cancel_button.emit("clicked")
        self.assertEqual(self.service.outgoing.cancelled, 2)

    def test_closing_while_sending_asks_first(self):
        self.start()
        presented = []
        with mock.patch.object(Adw.AlertDialog, "present", lambda alert, *a: presented.append(alert)):
            self.dialog.emit("close-attempt")
        alert = presented[0]
        alert.emit("response", "keep")
        self.assertEqual(self.service.outgoing.cancelled, 0)
        alert.emit("response", "cancel")
        self.assertEqual(self.service.outgoing.cancelled, 1)
        self.assertTrue(self.dialog.get_can_close())

    def test_nothing_starts_while_busy(self):
        self.share.transfer = object()
        self.dialog._peer_rows[0].emit("activated")
        self.assertIsNone(self.service.sent)
        self.dialog._cancel()
        self.dialog.waiting = None
        self.dialog.on_send_code("1")

    def test_the_result_close_button_closes(self):
        self.start()
        with mock.patch.object(ShareDialog, "close") as close:
            self.dialog.on_send_done({"status": "done"})
            self.dialog.result.close_button.emit("clicked")
        close.assert_called_once_with()


def _status(dialog):
    toolbar = dialog.nav.get_visible_page().get_child()
    return toolbar.get_content()
