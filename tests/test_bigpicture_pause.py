"""Big Picture during a game: the launch splash and the pause menu (issue 957)."""

# Builds real windows through tests.window_harness (via BigPictureCase): CI runs this
# module in the windowed process, with the other window tests.

import unittest
from pathlib import Path
from unittest import mock

from tests.bigpicture_harness import BigPictureCase
from tests.gtk_display import HAVE_DISPLAY, needs_display

if HAVE_DISPLAY:
    from gi.repository import Gdk, GdkPixbuf, GLib

    from openemux.core import pause_session
    from openemux.ui.bigpicture import pause_menu as pause_module
    from openemux.ui.bigpicture import splash as splash_module
    from openemux.ui.navigation import CTX_BP_PAUSE, CTX_DIALOG


class _Core:
    def __init__(self, filename, display_name):
        self.filename = filename
        self.display_name = display_name


class _Running:
    """A stand-in for a running RetroArch."""

    def poll(self):
        return None


@needs_display
class TheSplash(BigPictureCase):
    def setUp(self):
        super().setUp()
        submit = mock.patch.object(splash_module.cover_cache, "submit", side_effect=lambda fn, *a, **k: fn())
        submit.start()
        self.addCleanup(submit.stop)
        self.splash = self.shell.splash

    def test_starting_then_the_game_takes_the_screen(self):
        rom = self.rom("SFC")
        self.splash.show_starting(rom)
        self.pump()
        self.assertTrue(self.splash.shown)
        self.assertEqual(self.win.mode_stack.get_visible_child_name(), "bp-splash")
        self.assertTrue(self.splash.caption.get_visible())
        self.assertFalse(self.splash.buttons.get_visible())
        self.assertEqual(self.shell.context_for(None), "bp-page")
        self.assertEqual(self.shell.hints_for("bp-page", self.win.navigation.glyphs()), [])
        with mock.patch.object(self.win, "is_active", return_value=True):
            self.splash.wait_for_game()
        self.assertTrue(self.splash._timeout)
        self.assertTrue(self.splash._active_handler)
        # Still in front: nothing happens; behind the game: the splash goes.
        with mock.patch.object(self.win, "is_active", return_value=True):
            self.splash._on_active_changed()
        self.assertTrue(self.splash.shown)
        with mock.patch.object(self.win, "is_active", return_value=False):
            self.splash._on_active_changed()
        self.assertFalse(self.splash.shown)
        self.assertEqual(self.win.mode_stack.get_visible_child_name(), "big-picture")
        self.assertEqual(self.splash._timeout, 0)
        self.splash.close()  # already closed
        self.splash.wait_for_game()  # not shown: nothing to wait for

    def test_the_ceiling_and_a_window_already_behind(self):
        self.splash.show_starting(self.rom("SFC"))
        with mock.patch.object(self.win, "is_active", return_value=True):
            self.splash.wait_for_game()
        self.assertEqual(self.splash._on_timeout(), GLib.SOURCE_REMOVE)
        self.assertFalse(self.splash.shown)
        self.splash.show_starting(self.rom("SFC"))
        with mock.patch.object(self.win, "is_active", return_value=False):
            self.splash.wait_for_game()
            self.pump()
        self.assertFalse(self.splash.shown)

    def test_an_error_stays_with_the_log_a_button_away(self):
        self.splash.show_error("never shown")  # no game asked for: nothing
        self.assertFalse(self.splash.shown)
        self.splash.show_starting(self.rom("SFC"))
        self.splash.show_error("It closed straight away")
        self.pump()
        self.assertTrue(self.splash.shown)
        self.assertEqual(self.splash.error_label.get_label(), "It closed straight away")
        self.assertTrue(self.splash.buttons.get_visible())
        self.assertFalse(self.splash.caption.get_visible())
        hints = self.shell.hints_for("bp-page", self.win.navigation.glyphs())
        self.assertEqual(hints[1][1], self.said("big_picture.splash.close"))
        with mock.patch.object(self.win, "set_log_panel_visible") as log:
            self.splash.log_button.emit("clicked")
        log.assert_called_once_with(True)
        self.assertFalse(self.splash.shown)
        # B closes it too.
        self.splash.show_error("again")
        self.assertTrue(self.shell.handle_back())
        self.assertFalse(self.splash.shown)

    def test_the_art_and_the_core_name(self):
        rom = self.rom("SFC")
        covers = self.home.console_dir("SFC") / "covers"
        covers.mkdir(parents=True, exist_ok=True)
        pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 4, 4)
        pixbuf.savev(str(covers / f"{rom['name']}.png"), "png", [], [])
        with mock.patch.object(self.win.core_catalog, "cores_for_console", return_value=[_Core("s.so", "Snes9x")]):
            self.splash.show_starting(rom)
        self.pump()
        self.assertEqual(self.splash.caption.get_label(), self.said("big_picture.splash.starting", core="Snes9x"))
        self.assertIsNotNone(self.splash.picture.get_paintable())
        # An old load does not land on a newer game.
        self.assertEqual(self.splash._apply_art(self.splash._art_job - 1, pixbuf), GLib.SOURCE_REMOVE)
        with mock.patch.object(self.win.core_catalog, "cores_for_console", return_value=[]):
            self.splash.show_starting(rom)
        self.assertEqual(self.splash.caption.get_label(), self.said("big_picture.splash.starting_plain"))
        self.config.set_console_core_override("SFC", "b.so")
        with mock.patch.object(self.win.core_catalog, "display_name_for", return_value="bsnes"):
            self.assertEqual(splash_module.core_label(self.win, rom), "bsnes")
        self.splash.close()

    def test_leaving_the_mode_closes_it(self):
        self.splash.show_starting(self.rom("SFC"))
        self.leave()
        self.assertFalse(self.splash.shown)


@needs_display
class TheGameSessionHooks(BigPictureCase):
    def test_a_launch_shows_the_splash_and_its_end_closes_it(self):
        session = self.win.game
        splash = self.shell.splash
        rom = self.rom("SFC")
        with mock.patch.object(splash, "show_starting") as starting, mock.patch.object(
            session, "_toast_now"
        ), mock.patch("openemux.ui.game_session._run_in_worker"):
            session._start(rom, {})
        starting.assert_called_once_with(rom)
        with mock.patch.object(splash, "wait_for_game") as wait, mock.patch.object(session, "_toast_now"):
            session._finish_start(rom, (True, None), None, False)
        wait.assert_called_once()
        self.win.runtime_manager.stop_active = mock.Mock()
        # Stopped while it came up: no window will take over, the splash goes.
        session._stop_requested = True
        with mock.patch.object(splash, "wait_for_game") as wait, mock.patch.object(
            splash, "close"
        ) as close, mock.patch.object(session, "_toast_now"):
            session._finish_start(rom, (True, None), None, False)
        wait.assert_not_called()
        close.assert_called_once()
        session._stop_requested = False
        # A launch with no splash of its own (a state) forgets the last game.
        splash.rom = rom
        with mock.patch.object(splash, "show_starting") as starting, mock.patch(
            "openemux.ui.game_session._run_in_worker"
        ):
            session._start(rom, {}, announce=False)
        starting.assert_not_called()
        self.assertIsNone(splash.rom)
        session._launching = None
        # Failed: the error goes on the splash, not in a toast.
        session._launch_task = self.win.tasks.begin("launch", "x")
        splash.shown = True
        with mock.patch.object(splash, "show_error") as error, mock.patch.object(session, "_toast_now") as toast:
            session._finish_start(rom, (False, "boom"), None, True)
        error.assert_called_once()
        toast.assert_not_called()
        splash.shown = False
        # Splash not showing: the toast, as on the desktop.
        session._launch_task = self.win.tasks.begin("launch", "x")
        with mock.patch.object(session, "_toast_now") as toast:
            session._finish_start(rom, (False, "boom"), None, True)
        toast.assert_called_once()
        # Cancelled by the user: the splash simply goes.
        session._launch_task = self.win.tasks.begin("launch", "x")
        session._stop_requested = True
        with mock.patch.object(splash, "close") as close:
            session._finish_start(rom, (False, None), None, True)
        close.assert_called_once()
        session._stop_requested = False
        # A failure with no message closes it too.
        session._launch_task = self.win.tasks.begin("launch", "x")
        with mock.patch.object(splash, "close") as close:
            session._finish_start(rom, (False, None), None, True)
        close.assert_called_once()

    def test_a_game_that_dies_at_once_says_why_on_the_splash(self):
        session = self.win.game
        splash = self.shell.splash
        splash.rom = self.rom("SFC")
        result = {"rom": self.rom("SFC"), "failure_reason": "no core", "ran_for": 0.5}
        with mock.patch.object(self.win.runtime_manager, "poll_active", return_value=result), mock.patch.object(
            splash, "show_error"
        ) as error, mock.patch.object(session, "_toast_now") as toast:
            session.poll()
        error.assert_called_once()
        toast.assert_not_called()
        splash.rom = None
        with mock.patch.object(self.win.runtime_manager, "poll_active", return_value=result), mock.patch.object(
            session, "_toast_now"
        ) as toast:
            session.poll()
        toast.assert_called_once()

    def test_a_game_that_ends_before_taking_the_screen_closes_the_splash(self):
        session = self.win.game
        splash = self.shell.splash
        result = {"rom": self.rom("SFC"), "ran_for": 3.0, "exit_code": 0}
        with mock.patch.object(splash_module.cover_cache, "submit"):
            splash.show_starting(self.rom("SFC"))
        self.assertTrue(splash.shown)
        with mock.patch.object(self.win.runtime_manager, "poll_active", return_value=result), mock.patch.object(
            session, "_toast_now"
        ):
            session.poll()
        self.assertFalse(splash.shown)
        # Already gone: nothing to close.
        with mock.patch.object(self.win.runtime_manager, "poll_active", return_value=result), mock.patch.object(
            session, "_toast_now"
        ), mock.patch.object(splash, "close") as close:
            session.poll()
        close.assert_not_called()

    def test_outside_the_mode_there_is_no_splash(self):
        self.leave()
        self.assertIsNone(self.win.game._splash())


@needs_display
class ThePauseMenu(BigPictureCase):
    def setUp(self):
        super().setUp()
        self.sent = []
        runtime = self.win.runtime_manager
        self.rom_ = self.rom("SFC")
        runtime.active_process = _Running()
        runtime.active_rom = {"path": self.rom_["path"], "console": "SFC"}
        runtime._launched_at = None
        self.addCleanup(setattr, runtime, "active_process", None)
        send = mock.patch.object(runtime, "send_command", side_effect=lambda cmd: self.sent.append(cmd) or True)
        send.start()
        self.addCleanup(send.stop)
        present = mock.patch.object(pause_module.PauseMenuWindow, "present")
        present.start()
        self.addCleanup(present.stop)
        fullscreen = mock.patch.object(pause_module.PauseMenuWindow, "fullscreen")
        fullscreen.start()
        self.addCleanup(fullscreen.stop)

    def open(self):
        self.assertTrue(self.win.open_pause_menu())
        self.pump()
        menu = self.win.pause_menu
        self.addCleanup(menu.close_menu)
        return menu

    def test_the_gesture_opens_it_over_the_paused_game(self):
        self.win.navigation.on_gamepad_action("pause_menu")
        self.pump()
        menu = self.win.pause_menu
        self.addCleanup(menu.close_menu)
        self.assertTrue(self.win.pause_menu_open)
        self.assertEqual(self.sent, [pause_session.PAUSE])
        self.assertEqual(menu.title_label.get_label(), self.rom_["name"])
        self.assertIn(self.said("big_picture.pause.playing_for", minutes=0), menu.meta_label.get_label())
        self.assertFalse(menu.hardcore_tag.get_visible())
        self.assertEqual(self.win.navigation.current_context(), CTX_BP_PAUSE)
        self.assertTrue(menu.has_css_class("big-picture"))
        # Already open: asked again, nothing more.
        self.assertFalse(self.win.open_pause_menu())
        hints = menu.hints(self.win.navigation.glyphs(), self.win.t)
        self.assertEqual(hints[-1][1], self.said("big_picture.pause.back_to_game"))

    def test_continue_resumes_and_gives_the_screen_back(self):
        menu = self.open()
        menu.continue_tile.emit("clicked")
        self.assertFalse(self.win.pause_menu_open)
        self.assertEqual(self.sent, [pause_session.PAUSE, pause_session.PAUSE])
        # Escape is B: back to the game; any other key is left alone.
        self.open()
        self.assertFalse(menu._on_key(None, Gdk.KEY_a, 0, 0))
        self.assertTrue(self.win.pause_menu_open)
        self.assertTrue(menu._on_key(None, Gdk.KEY_Escape, 0, 0))
        self.assertFalse(self.win.pause_menu_open)
        # The same game: the same session, its toggles kept.
        session = menu.session
        self.open()
        self.assertIs(menu.session, session)
        menu.close_button.emit("clicked")
        self.assertFalse(self.win.pause_menu_open)
        # Closed by the compositor: Continue too.
        self.open()
        self.assertTrue(menu._on_close_request())
        self.assertFalse(self.win.pause_menu_open)

    def test_a_game_that_does_not_take_the_pause_stays_without_a_menu(self):
        with mock.patch.object(self.win.runtime_manager, "send_command", return_value=False):
            self.assertFalse(self.win.open_pause_menu())
        self.assertFalse(self.win.pause_menu_open)

    def test_save_load_and_the_slot(self):
        menu = self.open()
        self.assertFalse(menu.load_tile.get_sensitive())  # slot 0 is empty
        self.assertEqual(menu.save_tile.count_label.get_label(), self.said("big_picture.pause.slot_empty", slot=0))
        self.assertTrue(menu.step_slot(1))
        self.assertEqual(menu.session.slot, 1)
        self.assertEqual(menu.slot_label.get_label(), self.said("details.states.slot", slot=1))
        self.assertTrue(menu.slot_scale.step(-5))  # past the end: stays
        self.assertEqual(menu.session.slot, 1)
        menu.save_tile.emit("clicked")
        self.assertIn("SAVE_STATE_SLOT 1", self.sent)
        self.assertEqual(menu.note_label.get_label(), self.said("big_picture.pause.saved", slot=1))
        states = Path(self.config.get_console_states_dir("SFC"))
        states.mkdir(parents=True, exist_ok=True)
        (states / f"{Path(self.rom_['path']).stem}.state1").write_text("x")
        menu._sync_slot()
        self.assertTrue(menu.load_tile.get_sensitive())
        self.assertEqual(menu.load_tile.count_label.get_label(), self.said("big_picture.pause.slot_used", slot=1))
        menu.load_tile.emit("clicked")
        self.assertIn("LOAD_STATE_SLOT 1", self.sent)
        self.assertFalse(self.win.pause_menu_open)
        # The navigator's shoulders step the slot.
        self.open()
        self.win.navigation._cmd_bp_pause_slot(1)
        self.assertEqual(menu.session.slot, 2)
        menu._on_slot_changed(3)
        self.assertEqual(menu.session.slot, 3)
        menu.session = None
        menu._on_slot_changed(4)  # no session: nothing
        menu._sync_slot()  # a settle timer after the game: nothing

    def test_see_all_lists_the_states_and_a_loads_one(self):
        menu = self.open()
        self.assertTrue(menu.show_states())
        self.assertEqual(menu.stack.get_visible_child_name(), "states")
        self.assertTrue(menu.states_empty.get_visible())
        self.assertTrue(menu.handle_back())
        self.assertEqual(menu.stack.get_visible_child_name(), "main")
        states = Path(self.config.get_console_states_dir("SFC"))
        states.mkdir(parents=True, exist_ok=True)
        (states / f"{Path(self.rom_['path']).stem}.state5").write_text("x")
        menu.see_all_button.emit("clicked")
        self.assertEqual(len(menu.state_rows), 1)
        menu.show_states()  # rebuilt over its rows
        self.assertEqual(len(menu.state_rows), 1)
        menu.state_rows[0].emit("clicked")
        self.assertIn("LOAD_STATE_SLOT 5", self.sent)
        self.assertFalse(self.win.pause_menu_open)
        # B on the main page goes back to the game.
        self.open()
        self.win.navigation._cmd_bp_pause_back()
        self.assertFalse(self.win.pause_menu_open)
        self.open()
        self.win.navigation._cmd_bp_pause_close()
        self.assertFalse(self.win.pause_menu_open)

    def test_the_toggles_the_screenshot_and_retroarchs_menu(self):
        menu = self.open()
        menu.fast_tile.emit("clicked")
        self.assertTrue(menu.fast_tile.has_css_class("bp-on"))
        menu.fast_tile.emit("clicked")
        self.assertFalse(menu.fast_tile.has_css_class("bp-on"))
        menu.slow_tile.emit("clicked")
        menu.audio_tile.emit("clicked")
        self.assertTrue(menu.audio_tile.has_css_class("bp-on"))
        menu.shot_tile.emit("clicked")
        self.assertEqual(menu.note_label.get_label(), self.said("big_picture.pause.screenshot_taken"))
        self.assertIn(pause_session.SLOW_MOTION, self.sent)
        menu.menu_tile.emit("clicked")
        self.assertEqual(self.sent[-1], pause_session.MENU)
        self.assertFalse(self.win.pause_menu_open)

    def test_restart_and_quit_ask_first(self):
        menu = self.open()
        dialogs = []
        with mock.patch.object(pause_module.Adw.AlertDialog, "present", lambda dialog, parent: dialogs.append(dialog)):
            menu.restart_tile.emit("clicked")
            dialogs[-1].emit("response", "cancel")
            self.assertNotIn(pause_session.RESET, self.sent)
            menu.restart_tile.emit("clicked")
            dialogs[-1].emit("response", "confirm")
            self.assertIn(pause_session.RESET, self.sent)
            self.assertFalse(self.win.pause_menu_open)
            self.open()
            menu.quit_tile.emit("clicked")
            dialogs[-1].emit("response", "confirm")
        self.assertEqual(self.sent[-1], pause_session.QUIT)
        self.assertFalse(self.win.pause_menu_open)

    def test_hardcore_turns_the_speed_tiles_off(self):
        store = self.config.achievements
        with mock.patch.object(store, "is_signed_in", return_value=True), mock.patch.object(
            store, "get_enabled", return_value=True
        ), mock.patch.object(store, "get_hardcore", return_value=True):
            menu = self.open()
        self.assertTrue(menu.hardcore_tag.get_visible())
        self.assertFalse(menu.fast_tile.get_sensitive())
        self.assertFalse(menu.slow_tile.get_sensitive())

    def test_the_watchdog_falls_back_to_retroarchs_menu(self):
        menu = self.open()
        self.assertTrue(menu._watchdog)
        menu._arm_watchdog()  # re-armed, not doubled
        with mock.patch.object(menu, "is_active", return_value=True):
            self.assertEqual(menu._on_watchdog(), GLib.SOURCE_REMOVE)
        self.assertTrue(self.win.pause_menu_open)
        menu._watchdog = 0
        with mock.patch.object(menu, "is_active", return_value=False):
            menu._on_watchdog()
        self.assertFalse(self.win.pause_menu_open)
        self.assertEqual(self.sent[-1], pause_session.MENU)
        menu.session = None
        self.win.pause_menu_open = True
        with mock.patch.object(menu, "is_active", return_value=False):
            menu._on_watchdog()
        self.assertFalse(self.win.pause_menu_open)

    def test_the_game_ending_closes_it_and_a_new_game_gets_a_new_session(self):
        menu = self.open()
        session = menu.session
        self.win.on_game_ended(self.rom_)
        self.assertFalse(self.win.pause_menu_open)
        self.win.runtime_manager.active_process = _Running()
        self.win.runtime_manager._launched_at = 5.0
        self.open()
        self.assertIsNot(menu.session, session)
        self.assertEqual(menu.session.started_at, 5.0)
        menu.resume()
        menu.session = None
        self.assertTrue(menu.resume())  # nothing to unpause

    def test_nothing_opens_outside_a_game_or_the_mode(self):
        runtime = self.win.runtime_manager
        runtime.active_rom = {}
        self.assertFalse(self.win.open_pause_menu())
        runtime.active_process = None
        self.assertFalse(self.win.open_pause_menu())
        self.leave()
        self.assertFalse(self.win.open_pause_menu())

    def test_a_confirmation_inside_it_is_a_dialog_for_the_pad(self):
        menu = self.open()
        dialog = menu._ask("Sure?", "Yes", lambda: None)
        self.pump()
        try:
            self.assertEqual(self.win.navigation.current_context() in (CTX_DIALOG, CTX_BP_PAUSE), True)
        finally:
            dialog.force_close()

    def test_the_navigator_steers_the_menu_window(self):
        menu = self.open()
        self.assertIs(self.win.navigation._focus_root(), menu)
        menu.close_menu()
        self.assertIs(self.win.navigation._focus_root(), self.win)


if __name__ == "__main__":
    unittest.main()
