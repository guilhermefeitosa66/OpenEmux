"""The Incoming Games dialog (#589): consent, conflicts, space, progress, result."""

from pathlib import Path
from unittest import mock

from tests.gtk_display import HAVE_DISPLAY, needs_display
from tests.share_fixtures import PNG_BYTES
from tests.share_ui_fixtures import texts, install, offer
from tests.test_share_placement import game, item
from tests.window_harness import WindowCase

if HAVE_DISPLAY:
    from gi.repository import Adw

    from openemux.core.share.placement import ReceivePlan
    from openemux.core.share.protocol import ErrorCode, ShareError
    from openemux.ui.share_offer import IncomingOfferDialog

STATE = {"core": "Snes9x", "core_version": "1.62.3", "slot": 1}
ALIEN_STATE = {"core": "Bsnes", "core_version": "115", "slot": 2}


def tag(dialog):
    return dialog.nav.get_visible_page().get_tag()


def status(dialog):
    return dialog.nav.get_visible_page().get_child().get_content()


class _OfferCase(WindowCase):
    def setUp(self):
        super().setUp()
        self.share = install(self)
        self.share.open_screen(object())

    def receive(self, games, **kwargs):
        self.service.on_offer(offer(games, **kwargs))
        dialog = self.share.offer_dialog
        self.addCleanup(lambda: dialog.emit("closed"))
        return dialog


@needs_display
class TheOfferTests(_OfferCase):
    def test_who_what_how_big_and_the_code(self):
        dialog = self.receive([
            game([item("r", "rom", "New.sfc", b"x" * 1500), item("s", "state", "New.state1", b"s", state=STATE),
                  item("c", "cover", "New.png", PNG_BYTES)], title="New"),
        ], sender="Pixel <b>")
        shown = texts(dialog.root_page)
        self.assertIn("Pixel <b>", shown)
        self.assertIn("1 game", shown)
        self.assertIn("482 913", shown)
        self.assertIn("Accept only if Pixel <b> shows the same code.", shown)
        self.assertIn("Super Nintendo", shown.replace("Super Famicom", "Super Nintendo"))
        self.assertIn("Game, Cover, 1 state", shown)
        self.assertEqual(dialog.expires.get_label(), "Expires in 1:00")
        self.assertFalse(dialog.review_row.get_visible())
        self.assertTrue(dialog.accept_button.get_sensitive())
        self.assertFalse(dialog.incompatible_note.get_visible())

    def test_notes_for_skipped_states_and_unsupported_consoles(self):
        dialog = self.receive([
            game([item("r", "rom", "New.sfc"), item("a", "state", "New.state2", b"a", state=ALIEN_STATE),
                  item("b", "state", "New.state3", b"b", state={**ALIEN_STATE, "slot": 3})], title="New"),
            game([item("x", "rom", "Odd.bin")], game_id="g2", console="XX", title="Oddity"),
        ])
        self.assertEqual(
            dialog.incompatible_note.get_label(),
            "2 save states were made with a core you don't have and will be skipped.",
        )
        self.assertEqual(
            dialog.unsupported_notes[0].get_label(),
            "Oddity is for a console this device doesn't support and will be skipped.",
        )

    def test_the_countdown_and_the_expiry(self):
        dialog = self.receive([game([item("r", "rom", "New.sfc")])])
        self.now += 18
        self.timers.fire(1)
        self.assertEqual(dialog.expires.get_label(), "Expires in 0:42")
        self.now += 60
        with mock.patch.object(IncomingOfferDialog, "close") as close:
            self.timers.fire(1)
        close.assert_called_once_with()
        self.assertIn("The offer from Phone expired", self.toasts)
        self.assertTrue(dialog.answered)
        self.assertNotIn(("answer", dialog.offer.offer_id, False), self.service.calls)
        self.assertFalse(self.timers.has(1))

    def test_decline_and_close_both_decline_once(self):
        dialog = self.receive([game([item("r", "rom", "New.sfc")])])
        dialog.decline_button.emit("clicked")
        dialog.decline()
        dialog.emit("closed")
        answers = [call for call in self.service.calls if call[0] == "answer"]
        self.assertEqual(answers, [("answer", dialog.offer.offer_id, False)])
        self.assertIsNone(self.share.offer_dialog)

    def test_closing_unanswered_declines(self):
        dialog = self.receive([game([item("r", "rom", "New.sfc")])])
        dialog.emit("closed")
        self.assertIn(("answer", dialog.offer.offer_id, False), self.service.calls)
        self.assertFalse(self.timers.has(1))
        # A tick that was already queued does nothing once answered.
        self.assertFalse(dialog._tick())

    def test_a_sender_that_gives_up_first(self):
        dialog = self.receive([game([item("r", "rom", "New.sfc")])])
        self.service.on_cancel(dialog.offer.offer_id)
        self.assertEqual(status(dialog).get_title(), "Transfer Cancelled")
        self.assertIn("Nothing was saved on this device.", status(dialog).get_description())
        dialog.on_remote_cancel()


@needs_display
class ConflictsAndSpaceTests(_OfferCase):
    def setUp(self):
        super().setUp()
        self.existing = self.home.add_rom("SFC", "Chrono Trigger.sfc", b"older rom")
        __import__("os").utime(self.existing, (1000, 1000))
        cover = Path(self.config.get_roms_path()) / "SFC" / "covers" / "Chrono Trigger.png"
        cover.parent.mkdir(parents=True, exist_ok=True)
        cover.write_bytes(PNG_BYTES)
        self.dialog = self.receive([
            game([item("r", "rom", "Chrono Trigger.sfc", b"newer rom", mtime=5000),
                  item("c", "cover", "Chrono Trigger.png", PNG_BYTES + b"!"),
                  item("a", "state", "Chrono Trigger.state2", b"a", state=ALIEN_STATE),
                  item("bad", "battery_save", "Other.srm", b"s")], title="Chrono Trigger"),
        ])

    def test_review_lists_each_conflict_with_its_choices(self):
        self.assertTrue(self.dialog.review_row.get_visible())
        self.assertEqual(self.dialog.review_row.get_title(), "Review 2 Conflicts")
        self.dialog.review_row.emit("activated")
        self.assertEqual(tag(self.dialog), "conflicts")
        rom = self.dialog.combo_rows["r"]
        self.assertEqual(rom.get_title(), "Chrono Trigger · Game")
        self.assertTrue(rom.get_subtitle().endswith("(newer)"))
        self.assertEqual(rom.get_model().get_n_items(), 4)
        self.assertEqual(rom.get_model().get_string(rom.get_selected()), "Keep Both")
        cover = self.dialog.combo_rows["c"]
        self.assertEqual(cover.get_model().get_n_items(), 2)
        self.assertEqual(cover.get_model().get_string(cover.get_selected()), "Skip")
        skipped = texts(self.dialog.nav.get_visible_page())
        self.assertIn("Made with Bsnes 115, which you don't have", skipped)
        self.assertIn("Can't be placed in your library", skipped)

    def test_a_choice_changes_the_plan(self):
        self.dialog._push_conflicts()
        rom = self.dialog.combo_rows["r"]
        rom.set_selected(3)
        self.assertEqual(self.dialog.overrides, {"r": "skip"})
        decision = {d.item_id: d for d in self.dialog.plan.decisions()}["r"]
        self.assertEqual(decision.action, "skip")
        # Reopened, the page shows the choice in force.
        self.dialog.nav.pop()
        self.assertIsNone(self.dialog.conflicts_space)
        self.dialog._push_conflicts()
        self.assertEqual(self.dialog.combo_rows["r"].get_selected(), 3)

    def test_not_enough_space_blocks_accept_on_both_pages(self):
        short = [{"path": "/home", "needed": 412_000_000, "free": 280_000_000, "ok": False}]
        with mock.patch.object(ReceivePlan, "space_check", return_value=short):
            self.dialog._push_conflicts()
        for widget in (self.dialog.space_error, self.dialog.conflicts_space):
            self.assertTrue(widget.get_visible())
            self.assertIn("These games need 412.0 MB in /home, and 280.0 MB is free.", widget.get_text())
            self.assertIn("Free up 199.1 MB", widget.get_text())
        self.assertFalse(self.dialog.accept_button.get_sensitive())


@needs_display
class AcceptTests(_OfferCase):
    def setUp(self):
        super().setUp()
        self.dialog = self.receive([game([item("r", "rom", "New Game.sfc", b"new")], title="New Game")])

    def test_accept_progress_and_received(self):
        self.dialog.accept_button.emit("clicked")
        self.assertEqual(tag(self.dialog), "progress")
        self.assertFalse(self.dialog.get_can_close())
        self.assertIs(self.dialog.get_focus(), self.dialog.progress.cancel_button)
        self.assertFalse(self.dialog.finished)
        self.assertFalse(self.timers.has(1))
        kwargs = self.service.accepted[3]
        kwargs["on_progress"]({"name": "New Game.sfc", "done_bytes": 1, "total_bytes": 3,
                               "files_done": 0, "file_count": 1})
        self.assertEqual(self.dialog.progress.files.get_label(), "File 1 of 1")
        with mock.patch.object(self.win, "_rescan_single_console"):
            kwargs["on_done"]({"status": "done", "placed": ["x"], "replaced": ["y"], "skipped": []})
        page = status(self.dialog)
        self.assertEqual(page.get_title(), "1 Game Received")
        # Focus on the page's button, and a page that can pop (one that
        # cannot makes the navigation view eat Escape): Escape closes it.
        self.assertIs(self.dialog.get_focus(), self.dialog.result.close_button)
        self.assertTrue(self.dialog.result.get_can_pop())
        self.assertEqual(self.dialog.nav.get_navigation_stack().get_n_items(), 1)
        self.assertTrue(self.dialog.finished)
        self.assertIn("From Phone. They're in your library now.\n1 file replaced", page.get_description())
        with mock.patch.object(self.win.sidebar, "select") as select, \
                mock.patch.object(IncomingOfferDialog, "close") as close:
            _first_button(page).emit("clicked")
        select.assert_called_once_with("SFC")
        close.assert_called_once_with()
        self.dialog.accept()
        self.assertEqual(self.service.accepted[0], self.dialog.offer.offer_id)

    def test_space_gone_since_the_plan(self):
        short = [{"path": "/home", "needed": 10, "free": 0, "ok": False}]
        self.service.accept_error = ShareError(ErrorCode.TOO_LARGE, "full", {"space": short})
        self.dialog.accept()
        self.assertTrue(self.dialog.space_error.get_visible())
        self.assertFalse(self.dialog.answered)
        self.service.accept_error = ShareError(ErrorCode.TOO_LARGE, "full")
        with mock.patch.object(ReceivePlan, "space_check", return_value=short):
            self.dialog.accept()
        self.assertFalse(self.dialog.accept_button.get_sensitive())

    def test_an_offer_gone_meanwhile_fails(self):
        self.service.accept_error = ShareError(ErrorCode.NOT_FOUND, "gone")
        self.dialog.accept()
        self.assertEqual(status(self.dialog).get_title(), "Transfer Failed")
        self.assertIsNone(_first_button(status(self.dialog)).get_next_sibling())

    def test_cancel_while_receiving(self):
        self.dialog.accept()
        self.dialog.progress.cancel_button.emit("clicked")
        self.assertIn(("cancel", self.dialog.offer.offer_id), self.service.calls)
        presented = []
        with mock.patch.object(Adw.AlertDialog, "present", lambda alert, *a: presented.append(alert)):
            self.dialog.emit("close-attempt")
        presented[0].emit("response", "cancel")
        self.assertEqual(len([c for c in self.service.calls if c[0] == "cancel"]), 2)
        self.dialog.on_receive_done({"status": "cancelled"})
        self.assertEqual(status(self.dialog).get_title(), "Transfer Cancelled")
        self.dialog._cancel()

    def test_progress_before_the_page_is_ignored(self):
        self.dialog.on_receive_progress({})


@needs_display
class NotReceivedTests(_OfferCase):
    """The games a receive did not add, by title and reason (#614)."""

    def finish(self, games):
        dialog = self.receive(games)
        dialog.accept()
        with mock.patch.object(self.win, "_rescan_single_console"):
            self.service.accepted[3]["on_done"]({"status": "done", "placed": [], "replaced": [], "skipped": []})
        return dialog

    def test_some_received_lists_the_others(self):
        self.home.add_rom("SFC", "Same.sfc", b"same")
        dialog = self.finish([
            game([item("n", "rom", "New Game.sfc", b"new")], game_id="g1", title="New Game"),
            game([item("s", "rom", "Same.sfc", b"same")], game_id="g2", title="Same"),
            game([item("x", "rom", "Alien.bin", b"x")], game_id="g3", console="XX", title="<b>Alien</b> &"),
        ])
        page = status(dialog)
        self.assertEqual(page.get_title(), "1 of 3 Games Received")
        self.assertEqual(page.get_icon_name(), "dialog-warning-symbolic")
        self.assertEqual(page.get_description(), "From Phone. They're in your library now.")
        group = dialog.result.missing_group
        self.assertEqual(group.get_title(), "Not Received")
        rows = action_rows(group)
        self.assertEqual([row.get_title() for row in rows], ["Same", "<b>Alien</b> &"])
        self.assertFalse(rows[1].get_use_markup())
        self.assertTrue(rows[0].get_subtitle().endswith(" · Already in your library"))
        self.assertTrue(rows[1].get_subtitle().endswith(" · This console isn't supported on this device"))
        # Something arrived: "Show in Library" is there, the focus on Close.
        self.assertEqual(_first_button(page).get_label(), "Show in Library")
        self.assertIs(dialog.get_focus(), dialog.result.close_button)

    def test_none_received(self):
        self.home.add_rom("SFC", "Same.sfc", b"same")
        dialog = self.finish([game([item("s", "rom", "Same.sfc", b"same")], title="Same")])
        page = status(dialog)
        self.assertEqual(page.get_title(), "No Games Received")
        self.assertEqual(page.get_description(), "Nothing from Phone was added to your library.")
        self.assertEqual(dialog.result.missing_group.get_title(), "Not Received")
        self.assertIs(_first_button(page), dialog.result.close_button)

    def test_everything_received_lists_nothing(self):
        dialog = self.finish([game([item("n", "rom", "New Game.sfc", b"new")], title="New Game")])
        self.assertEqual(status(dialog).get_icon_name(), "emblem-ok-symbolic")
        self.assertIsNone(dialog.result.missing_group)


@needs_display
class BiosOfferTests(_OfferCase):
    """BIOS in an incoming offer (issue 677)."""

    def disk(self, *bios):
        return [game([item("r", "rom", "Disk.fds", b"disk")] + list(bios), console="FDS", title="Disk")]

    def test_the_offer_says_bios_and_the_result_names_them(self):
        dialog = self.receive(self.disk(item("b", "bios", "disksys.rom", b"fds")))
        self.assertIn("Game, BIOS", texts(dialog.root_page))
        dialog.accept()
        with mock.patch.object(self.win, "_rescan_single_console"):
            self.service.accepted[3]["on_done"]({"status": "done", "placed": [], "replaced": [], "skipped": []})
        self.assertIn("\nBIOS files added: disksys.rom", status(dialog).get_description())

    def test_a_different_bios_is_a_conflict_kept_by_default(self):
        bios = self.home.console_dir("FDS") / "bios" / "disksys.rom"
        bios.parent.mkdir()
        bios.write_bytes(b"mine")
        dialog = self.receive(self.disk(item("b", "bios", "disksys.rom", b"theirs"),
                                        item("x", "bios", "notes.txt", b"no")))
        dialog._push_conflicts()
        row = dialog.combo_rows["b"]
        self.assertEqual(row.get_title(), "Disk · BIOS disksys.rom")
        self.assertEqual(row.get_model().get_n_items(), 2)
        self.assertEqual(row.get_model().get_string(row.get_selected()), "Skip")
        self.assertIn("Disk · BIOS notes.txt", texts(dialog.nav.get_visible_page()))


def action_rows(widget):
    """Every ``Adw.ActionRow`` under ``widget``, in order."""
    found = []
    child = widget.get_first_child()
    while child is not None:
        if isinstance(child, Adw.ActionRow):
            found.append(child)
        else:
            found.extend(action_rows(child))
        child = child.get_next_sibling()
    return found


def _first_button(status_page):
    # The buttons come last, under the list of games not received.
    return status_page.get_child().get_last_child().get_first_child()


