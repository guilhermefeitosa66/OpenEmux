"""The game wrapper as a widget: the headerbar, the volume control, the tick.

`tests/test_game_window.py` covers the wrapper's decisions against stand-ins,
which is what a headless run could reach. It leaves 344 of 429 statements
unexecuted -- everything from the constructor down: the headerbar buttons that
talk to RetroArch over UDP, the volume popover that walks the level in 0.5 dB
steps (issue #284), the tick that adopts the game, and the teardown that has
to detach the X window before GTK destroys the frame around it.

A real `GameWindow` is built here. The X side is a stand-in embedder -- there
is no RetroArch to adopt -- and the runtime manager is a recorder, so no
command ever leaves the process.
"""

import unittest
from unittest import mock

from tests.gtk_display import HAVE_DISPLAY, needs_display
from tests.window_harness import shared_application

if HAVE_DISPLAY:
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gdk, GLib, Graphene, Gtk

    Adw.init()

    from openemux.core import retroarch_log
    from openemux.core.retroarch_command import MAX_VOLUME_DB, MIN_VOLUME_DB
    from openemux.ui import game_window as game_window_module
    from openemux.ui.game_window import (
        FULLSCREEN_FALLBACK_KEY,
        GameWindow,
        _GameScreen,
        display_supports_embedding,
    )


class _Process:
    def __init__(self, exit_code=None, pid=4242):
        self._exit_code = exit_code
        self.pid = pid

    def poll(self):
        return self._exit_code


class _ConfigManager:
    def __init__(self, fullscreen_binding="f"):
        self.fullscreen_binding = fullscreen_binding

    def get_input_profile(self, _console):
        return {
            "devices": {
                "keyboard": {"bindings": {"fullscreen_toggle": self.fullscreen_binding}}
            }
        }


class _Runtime:
    """Records every command instead of putting it on the UDP socket."""

    def __init__(self, process=None, fullscreen_binding="f"):
        self.active_process = process
        self.config_manager = _ConfigManager(fullscreen_binding)
        self.commands = []
        self.command_result = True
        self.volume_db = 0.0
        self.muted = False
        self.volume_settling = False
        self.stopped = []
        # None means "behave like a real toggle"; a value forces the answer,
        # which is how a command that never left the socket is modelled.
        self.mute_result = None

    def send_command(self, name):
        self.commands.append(name)
        return self.command_result

    def set_master_volume_db(self, value):
        self.volume_db = max(MIN_VOLUME_DB, min(MAX_VOLUME_DB, value))
        return self.volume_db

    def toggle_mute(self):
        self.muted = not self.muted if self.mute_result is None else self.mute_result
        return self.muted

    def stop_active(self, block=False):
        self.stopped.append(block)


class _GameWindowCase(unittest.TestCase):
    frame_enabled = False
    exit_code = None

    def setUp(self):
        self.app = shared_application()
        self.process = _Process(exit_code=self.exit_code)
        self.runtime = _Runtime(process=self.process)
        self.embedder = mock.Mock()
        self.embedder.available = True
        self.embedder.pressed_grabbed_keycodes.return_value = set()
        self.embedder.is_child_of.return_value = True
        self.embedder.embed.return_value = True
        self.embedder.grab_key.return_value = 42
        self.embedder.find_game_window.return_value = 0x200
        patcher = mock.patch.object(
            game_window_module, "RetroArchWindowEmbedder", lambda: self.embedder
        )
        patcher.start()
        self.addCleanup(patcher.stop)

        self.closed = []
        self.embed_failures = []
        self.input_settings = []
        self.win = GameWindow(
            self.app,
            self.runtime,
            {"name": "Chrono Trigger", "console": "SFC", "path": "/tmp/ct.sfc"},
            frame_enabled=self.frame_enabled,
            on_closed=self.closed.append,
            on_open_input_settings=self.input_settings.append,
            on_embed_failed=self.embed_failures.append,
        )
        self.addCleanup(self.win.destroy)


@needs_display
class TheWrapperIsBuiltAroundOneGameTests(_GameWindowCase):
    def test_the_window_is_titled_after_the_game(self):
        self.assertEqual(self.win.get_title(), "Chrono Trigger")

    def test_a_game_with_no_name_falls_back_to_its_filename(self):
        win = GameWindow(
            self.app,
            self.runtime,
            {"path": "/tmp/Super Metroid.sfc", "console": "SFC"},
            frame_enabled=False,
        )
        self.addCleanup(win.destroy)
        self.assertEqual(win.get_title(), "Super Metroid")

    def test_the_existing_windows_are_snapshotted_before_the_search(self):
        self.embedder.snapshot_existing.assert_called_once()

    def test_the_users_own_fullscreen_binding_is_the_one_taken_over(self):
        self.assertEqual(self.win._fullscreen_key, "f")

    def test_a_console_with_no_fullscreen_binding_takes_the_fallback(self):
        runtime = _Runtime(process=self.process, fullscreen_binding="")
        win = GameWindow(
            self.app, runtime, {"name": "x", "console": "SFC"}, frame_enabled=False
        )
        self.addCleanup(win.destroy)
        self.assertEqual(win._fullscreen_key, FULLSCREEN_FALLBACK_KEY)

    def test_the_starting_overlay_is_up_until_the_game_is_adopted(self):
        self.assertIsNotNone(self.win._starting)
        self.win._hide_starting_indicator()
        self.assertIsNone(self.win._starting)

    def test_hiding_the_overlay_twice_is_harmless(self):
        self.win._hide_starting_indicator()
        self.win._hide_starting_indicator()

    def test_mapping_the_window_starts_the_tick(self):
        with mock.patch.object(
            game_window_module.GLib, "timeout_add", return_value=7
        ) as timeout:
            self.win._on_map(None)
        timeout.assert_called_once()
        self.assertEqual(self.win._tick_id, 7)

    def test_a_second_map_does_not_start_a_second_tick(self):
        self.win._tick_id = 7
        with mock.patch.object(game_window_module.GLib, "timeout_add") as timeout:
            self.win._on_map(None)
        timeout.assert_not_called()


@needs_display
class WithTheCrtFrameTests(_GameWindowCase):
    frame_enabled = True

    def test_the_frame_texture_is_loaded_and_the_window_opens_taller(self):
        self.assertIsNotNone(self.win._screen._texture)

    def test_a_frame_asset_that_will_not_load_leaves_a_plain_black_screen(self):
        with mock.patch.object(
            Gdk.Texture,
            "new_from_filename",
            side_effect=GLib.Error("no such file"),
        ):
            self.assertIsNone(GameWindow._load_frame_texture())


@needs_display
class TheHeaderbarButtonsTests(_GameWindowCase):
    def test_pause_toggles_the_icon_and_the_tooltip(self):
        self.win._on_pause_clicked(None)
        self.assertEqual(self.runtime.commands, ["PAUSE_TOGGLE"])
        self.assertEqual(
            self.win._pause_button.get_icon_name(), "media-playback-start-symbolic"
        )
        self.win._on_pause_clicked(None)
        self.assertEqual(
            self.win._pause_button.get_icon_name(), "media-playback-pause-symbolic"
        )

    def test_a_pause_that_never_reached_the_game_leaves_the_button_alone(self):
        self.runtime.command_result = False
        self.win._on_pause_clicked(None)
        self.assertFalse(self.win._paused)
        self.assertEqual(
            self.win._pause_button.get_icon_name(), "media-playback-pause-symbolic"
        )

    def test_the_other_four_buttons_send_their_own_command(self):
        self.win._on_reset_clicked(None)
        self.win._on_save_state_clicked(None)
        self.win._on_load_state_clicked(None)
        self.win._on_menu_clicked(None)
        self.assertEqual(
            self.runtime.commands,
            ["RESET", "SAVE_STATE", "LOAD_STATE", "MENU_TOGGLE"],
        )

    def test_the_controller_button_asks_the_owner_to_open_preferences(self):
        self.win._on_input_settings_clicked(None)
        self.assertEqual(self.input_settings, [self.win])

    def test_a_wrapper_with_no_owner_for_that_button_does_nothing(self):
        win = GameWindow(
            self.app, self.runtime, {"name": "x", "console": "SFC"}, frame_enabled=False
        )
        self.addCleanup(win.destroy)
        win._on_input_settings_clicked(None)


@needs_display
class TheVolumeControlTests(_GameWindowCase):
    """Issue #284: RetroArch has no absolute set-volume, so a drag is a walk."""

    def test_dragging_the_slider_walks_the_game_to_that_level(self):
        self.win._volume_scale.set_value(-20.0)
        self.assertEqual(self.runtime.volume_db, -20.0)

    def test_a_value_just_off_unity_snaps_onto_it(self):
        self.win._volume_scale.set_value(-0.5)
        self.assertEqual(self.win._volume_scale.get_value(), 0.0)

    def test_the_icon_follows_how_loud_the_game_actually_is(self):
        self.win._volume_scale.set_value(-20.0)
        self.assertEqual(
            self.win._volume_btn.get_icon_name(), "audio-volume-medium-symbolic"
        )
        self.win._volume_scale.set_value(-35.0)
        self.assertEqual(
            self.win._volume_btn.get_icon_name(), "audio-volume-low-symbolic"
        )

    def test_reaching_the_slider_floor_reads_as_off(self):
        self.win._volume_scale.set_value(MIN_VOLUME_DB)
        self.assertTrue(self.win._mute_button.get_active())
        self.assertTrue(self.win._auto_muted)

    def test_coming_back_up_releases_the_mute_the_slider_engaged(self):
        self.win._volume_scale.set_value(MIN_VOLUME_DB)
        self.win._volume_scale.set_value(-10.0)
        self.assertFalse(self.win._mute_button.get_active())
        self.assertFalse(self.win._auto_muted)

    def test_a_manual_mute_is_not_released_by_the_slider(self):
        self.win._mute_button.set_active(True)
        self.win._volume_scale.set_value(-10.0)
        self.assertTrue(self.win._mute_button.get_active())

    def test_seeding_the_slider_never_sends_a_command(self):
        before = list(self.runtime.commands)
        self.win._volume_seed_guard = True
        self.win._volume_scale.set_value(-15.0)
        self.win._volume_seed_guard = False
        self.assertEqual(self.runtime.commands, before)

    def test_muting_swaps_the_icon(self):
        self.win._mute_button.set_active(True)
        self.assertEqual(
            self.win._volume_btn.get_icon_name(), "audio-volume-muted-symbolic"
        )

    def test_unmuting_restores_the_level_icon(self):
        self.win._mute_button.set_active(True)
        self.win._mute_button.set_active(False)
        self.assertEqual(
            self.win._volume_btn.get_icon_name(), "audio-volume-high-symbolic"
        )

    def test_a_mute_that_never_reached_the_game_puts_the_button_back(self):
        # The game went away mid-toggle; the control has to stay honest.
        self.runtime.mute_result = False
        self.win._mute_button.set_active(True)
        self.assertFalse(self.win._mute_button.get_active())

    def test_the_guard_stops_the_toggle_handler_re_entering_itself(self):
        self.win._mute_guard = True
        before = self.runtime.muted
        self.win._on_mute_toggled(self.win._mute_button)
        self.assertEqual(self.runtime.muted, before)

    def test_opening_the_popover_re_reads_the_level_and_the_mute(self):
        # Both may have moved through the library's control or a hotkey.
        self.runtime.volume_db = -8.0
        self.runtime.muted = True
        self.win._on_volume_popover_shown(None)
        self.assertEqual(self.win._volume_scale.get_value(), -8.0)
        self.assertTrue(self.win._mute_button.get_active())

    def test_opening_it_mid_walk_starts_reporting_the_real_level(self):
        self.runtime.volume_settling = True
        with mock.patch.object(
            game_window_module.GLib, "timeout_add", return_value=9
        ) as timeout:
            self.win._on_volume_popover_shown(None)
        timeout.assert_called_once()

    def test_the_walk_watch_is_started_only_once(self):
        self.win._volume_watch_id = 9
        with mock.patch.object(game_window_module.GLib, "timeout_add") as timeout:
            self.win._watch_volume_walk()
        timeout.assert_not_called()

    def test_a_walk_still_in_flight_says_where_the_game_is(self):
        self.runtime.volume_settling = True
        self.runtime.volume_db = -6.0
        self.assertTrue(self.win._on_volume_walk_tick())
        self.assertTrue(self.win._volume_status.get_visible())
        self.assertIn("-6.0 dB", self.win._volume_status.get_text())

    def test_a_settled_walk_syncs_the_slider_and_stops_the_watch(self):
        self.win._volume_watch_id = 9
        self.runtime.volume_settling = False
        self.runtime.volume_db = -13.5
        self.assertFalse(self.win._on_volume_walk_tick())
        self.assertEqual(self.win._volume_scale.get_value(), -13.5)
        self.assertFalse(self.win._volume_status.get_visible())
        self.assertIsNone(self.win._volume_watch_id)

    def test_a_wrapper_being_closed_stops_watching(self):
        self.win._closing = True
        self.win._volume_watch_id = 9
        self.assertFalse(self.win._on_volume_walk_tick())
        self.assertIsNone(self.win._volume_watch_id)

    def test_the_reading_matches_the_sliders_own_format(self):
        self.assertEqual(self.win._volume_reading(0.0), "100%  +0.0 dB")


@needs_display
class TheTickTests(_GameWindowCase):
    def test_a_closing_wrapper_stops_ticking(self):
        self.win._closing = True
        self.assertFalse(self.win._tick())
        self.assertIsNone(self.win._tick_id)

    def test_a_game_still_running_keeps_the_tick_alive(self):
        with mock.patch.object(self.win, "_try_embed", return_value=True):
            self.assertTrue(self.win._tick())

    def test_a_game_that_ended_closes_the_wrapper(self):
        self.win._proc = _Process(exit_code=0)
        self.runtime.active_process = self.win._proc
        with mock.patch.object(self.win, "_close_and_destroy") as close:
            self.assertFalse(self.win._tick())
        close.assert_called_once()

    def test_a_wrapper_with_no_process_at_all_closes_too(self):
        self.win._proc = None
        with mock.patch.object(self.win, "_close_and_destroy") as close:
            self.assertFalse(self.win._tick())
        close.assert_called_once()

    def test_a_relaunched_game_is_followed_rather_than_abandoned(self):
        # Issue #248: a launch retried unpacked must not read as a failed
        # embed for the rest of the session.
        self.win._proc = _Process(exit_code=1)
        self.runtime.active_process = _Process(exit_code=None)
        self.assertTrue(self.win._tick())
        self.assertIs(self.win._proc, self.runtime.active_process)

    def test_an_embed_that_gave_up_takes_the_tick_down_with_it(self):
        with mock.patch.object(self.win, "_try_embed", return_value=False):
            self.assertFalse(self.win._tick())
        self.assertIsNone(self.win._tick_id)

    def test_an_adopted_game_is_kept_in_place_and_kept_focused(self):
        self.win._child_xid = 0x200
        with mock.patch.object(self.win, "_sync_geometry"), mock.patch.object(
            self.win, "_reassert_embed"
        ):
            self.assertTrue(self.win._tick())
        self.embedder.ensure_focus.assert_called_once()

    def test_the_grabbed_fullscreen_key_toggles_fullscreen(self):
        self.win._child_xid = 0x200
        self.win._fullscreen_keycode = 42
        self.embedder.pressed_grabbed_keycodes.return_value = {42}
        with mock.patch.object(self.win, "_sync_geometry"), mock.patch.object(
            self.win, "_reassert_embed"
        ), mock.patch.object(self.win, "_toggle_fullscreen") as toggle:
            self.win._tick()
        toggle.assert_called_once()


@needs_display
class WhenTheGameDiesBeforeShowingAWindowTests(_GameWindowCase):
    def test_a_crash_marks_embedding_unavailable_for_the_session(self):
        # Without this the next launch repeats it identically.
        with mock.patch.object(
            game_window_module.game_window_support, "mark_embed_unavailable"
        ) as mark:
            self.win._note_death_before_embed(1)
        mark.assert_called_once()

    def test_a_clean_quit_from_the_retroarch_menu_says_nothing_about_embedding(self):
        with mock.patch.object(
            game_window_module.game_window_support, "mark_embed_unavailable"
        ) as mark:
            self.win._note_death_before_embed(0)
            self.win._note_death_before_embed(None)
        mark.assert_not_called()

    def test_a_game_that_was_already_adopted_is_not_blamed(self):
        self.win._child_xid = 0x200
        with mock.patch.object(
            game_window_module.game_window_support, "mark_embed_unavailable"
        ) as mark:
            self.win._note_death_before_embed(1)
        mark.assert_not_called()


@needs_display
class AdoptingTheGameTests(_GameWindowCase):
    def setUp(self):
        super().setUp()
        rect_patch = mock.patch.object(
            self.win, "_surface_rect", return_value=(10, 20, 300, 200)
        )
        rect_patch.start()
        self.addCleanup(rect_patch.stop)
        xid_patch = mock.patch.object(self.win, "_surface_xid", return_value=0x100)
        xid_patch.start()
        self.addCleanup(xid_patch.stop)

    def test_a_found_window_is_reparented_focused_and_the_key_grabbed(self):
        self.assertTrue(self.win._try_embed())
        self.assertEqual(self.win._child_xid, 0x200)
        self.embedder.focus.assert_called_once_with(0x200)
        self.embedder.grab_key.assert_called_once_with(
            0x100, "f", FULLSCREEN_FALLBACK_KEY
        )
        self.assertIsNone(self.win._starting)

    def test_a_machine_without_python_xlib_hands_the_game_back_at_once(self):
        self.embedder.available = False
        self.assertFalse(self.win._try_embed())
        self.assertEqual(self.embed_failures, ["python-xlib is unavailable"])

    def test_a_retroarch_that_is_not_an_x_client_is_not_waited_out(self):
        # Twenty seconds of black for a window that will never appear.
        with mock.patch.object(
            self.win, "_probe_retroarch_log", return_value=retroarch_log.NOT_X11
        ):
            self.assertFalse(self.win._try_embed())
        self.assertEqual(self.embed_failures, ["RetroArch is not an X11 client"])

    def test_a_window_that_never_appears_is_given_up_on(self):
        with mock.patch.object(
            self.win, "_probe_retroarch_log", return_value=retroarch_log.UNKNOWN
        ), mock.patch.object(
            game_window_module.retroarch_log, "should_abandon", return_value=True
        ):
            self.assertFalse(self.win._try_embed())
        self.assertEqual(self.embed_failures, ["RetroArch window not found in time"])

    def test_a_surface_that_is_not_ready_yet_is_tried_again_next_tick(self):
        with mock.patch.object(self.win, "_surface_xid", return_value=None):
            self.assertTrue(self.win._try_embed())
        self.assertIsNone(self.win._child_xid)

    def test_a_game_window_not_found_yet_is_tried_again_next_tick(self):
        self.embedder.find_game_window.return_value = None
        self.assertTrue(self.win._try_embed())
        self.assertIsNone(self.win._child_xid)

    def test_a_window_not_laid_out_yet_is_tried_again_next_tick(self):
        with mock.patch.object(self.win, "_surface_rect", return_value=None):
            self.assertTrue(self.win._try_embed())
        self.assertIsNone(self.win._child_xid)

    def test_a_reparent_that_fails_hands_the_game_back(self):
        self.embedder.embed.return_value = False
        self.assertFalse(self.win._try_embed())
        self.assertEqual(self.embed_failures, ["reparenting failed"])


@needs_display
class KeepingTheGameAdoptedTests(_GameWindowCase):
    def setUp(self):
        super().setUp()
        self.win._child_xid = 0x200
        self.win._parent_xid = 0x100
        xid_patch = mock.patch.object(self.win, "_surface_xid", return_value=0x100)
        xid_patch.start()
        self.addCleanup(xid_patch.stop)
        rect_patch = mock.patch.object(
            self.win, "_surface_rect", return_value=(10, 20, 300, 200)
        )
        rect_patch.start()
        self.addCleanup(rect_patch.stop)

    def _check(self, times=1):
        for _ in range(times * game_window_module.PARENT_CHECK_INTERVAL_TICKS):
            self.win._reassert_embed()

    def test_the_check_only_runs_every_few_ticks(self):
        self.win._reassert_embed()
        self.embedder.is_child_of.assert_not_called()

    def test_a_game_still_in_our_frame_is_left_alone(self):
        self._check()
        self.embedder.embed.assert_not_called()

    def test_a_game_that_left_our_frame_is_re_adopted(self):
        self.embedder.is_child_of.return_value = False
        self.win._fullscreen_keycode = None
        self._check()
        self.embedder.embed.assert_called_once()
        self.embedder.grab_key.assert_called_once()

    def test_a_re_adoption_does_not_grab_the_key_twice(self):
        self.embedder.is_child_of.return_value = False
        self.win._fullscreen_keycode = 42
        self._check()
        self.embedder.grab_key.assert_not_called()

    def test_a_question_that_cannot_be_asked_is_not_acted_on(self):
        # None means the window is typically already gone; re-parenting on
        # that would fight the game's own teardown.
        self.embedder.is_child_of.return_value = None
        self._check()
        self.embedder.embed.assert_not_called()

    def test_a_surface_that_has_gone_is_not_acted_on_either(self):
        with mock.patch.object(self.win, "_surface_xid", return_value=None):
            self._check()
        self.embedder.embed.assert_not_called()

    def test_a_window_with_no_geometry_is_not_acted_on_either(self):
        self.embedder.is_child_of.return_value = False
        with mock.patch.object(self.win, "_surface_rect", return_value=None):
            self._check()
        self.embedder.embed.assert_not_called()

    def test_the_game_is_moved_when_the_wrapper_is_resized(self):
        self.embedder.move_resize.return_value = True
        self.win._last_rect = None
        self.win._sync_geometry()
        self.embedder.move_resize.assert_called_once_with(0x200, 10, 20, 300, 200)
        self.assertEqual(self.win._last_rect, (10, 20, 300, 200))

    def test_a_geometry_that_did_not_change_costs_no_x_round_trip(self):
        self.win._last_rect = (10, 20, 300, 200)
        self.win._sync_geometry()
        self.embedder.move_resize.assert_not_called()

    def test_a_wrapper_with_no_geometry_moves_nothing(self):
        with mock.patch.object(self.win, "_surface_rect", return_value=None):
            self.win._sync_geometry()
        self.embedder.move_resize.assert_not_called()


@needs_display
class TheLogProbeTests(_GameWindowCase):
    def test_the_log_is_only_read_every_few_ticks(self):
        self.win._ticks_waited = 1
        with mock.patch.object(
            game_window_module.retroarch_log, "read_verdict"
        ) as read:
            self.win._probe_retroarch_log()
        read.assert_not_called()

    def test_a_definite_answer_is_never_asked_for_twice(self):
        self.win._log_verdict = retroarch_log.NOT_X11
        with mock.patch.object(
            game_window_module.retroarch_log, "read_verdict"
        ) as read:
            self.assertEqual(self.win._probe_retroarch_log(), retroarch_log.NOT_X11)
        read.assert_not_called()

    def test_the_log_is_read_on_the_probe_tick(self):
        self.win._ticks_waited = game_window_module.LOG_PROBE_INTERVAL_TICKS
        with mock.patch.object(
            game_window_module.retroarch_log,
            "read_verdict",
            return_value=retroarch_log.NOT_X11,
        ) as read:
            self.assertEqual(self.win._probe_retroarch_log(), retroarch_log.NOT_X11)
        read.assert_called_once()


@needs_display
class FullscreenTests(_GameWindowCase):
    def test_the_hotkey_hides_the_headerbar_and_shows_it_again(self):
        with mock.patch.object(self.win, "is_fullscreen", return_value=False):
            self.win._toggle_fullscreen()
        self.assertFalse(self.win._toolbar.get_reveal_top_bars())
        self.win._fullscreen_toggled_at = 0
        with mock.patch.object(self.win, "is_fullscreen", return_value=True):
            self.win._toggle_fullscreen()
        self.assertTrue(self.win._toolbar.get_reveal_top_bars())

    def test_a_held_key_does_not_flip_fullscreen_on_every_repeat(self):
        # X auto-repeat turns a held key into a stream of presses.
        with mock.patch.object(self.win, "is_fullscreen", return_value=False):
            self.win._toggle_fullscreen()
            with mock.patch.object(self.win, "fullscreen") as fullscreen:
                self.win._toggle_fullscreen()
        fullscreen.assert_not_called()


@needs_display
class TheSurfaceGeometryTests(_GameWindowCase):
    def test_a_window_with_no_surface_has_no_xid_and_no_rect(self):
        with mock.patch.object(self.win, "get_surface", return_value=None):
            self.assertIsNone(self.win._surface_xid())
            self.assertIsNone(self.win._surface_rect())

    def test_a_surface_that_is_not_x11_cannot_be_embedded_into(self):
        surface = mock.Mock(spec=[])
        with mock.patch.object(self.win, "get_surface", return_value=surface):
            self.assertIsNone(self.win._surface_xid())

    def test_an_x11_surface_reports_its_xid(self):
        surface = mock.Mock()
        surface.get_xid.return_value = 0x123
        with mock.patch.object(self.win, "get_surface", return_value=surface):
            self.assertEqual(self.win._surface_xid(), 0x123)

    def test_a_screen_with_no_area_yet_has_no_rect(self):
        surface = mock.Mock()
        with mock.patch.object(
            self.win, "get_surface", return_value=surface
        ), mock.patch.object(
            self.win._screen, "screen_rect", return_value=(0, 0, 0, 0)
        ):
            self.assertIsNone(self.win._surface_rect())

    def test_a_point_that_cannot_be_translated_yields_no_rect(self):
        surface = mock.Mock()
        with mock.patch.object(
            self.win, "get_surface", return_value=surface
        ), mock.patch.object(
            self.win._screen, "screen_rect", return_value=(0, 0, 100, 80)
        ), mock.patch.object(
            self.win._screen, "compute_point", return_value=(False, None)
        ):
            self.assertIsNone(self.win._surface_rect())

    def test_the_rect_is_in_device_pixels_relative_to_the_toplevel(self):
        surface = mock.Mock()
        surface.get_scale_factor.return_value = 2
        point = Graphene.Point().init(5.0, 7.0)
        with mock.patch.object(
            self.win, "get_surface", return_value=surface
        ), mock.patch.object(
            self.win._screen, "screen_rect", return_value=(0, 0, 100, 80)
        ), mock.patch.object(
            self.win._screen, "compute_point", return_value=(True, point)
        ), mock.patch.object(
            self.win, "get_surface_transform", return_value=(1.0, 2.0)
        ):
            self.assertEqual(self.win._surface_rect(), (12, 18, 200, 160))


@needs_display
class TearingDownTests(_GameWindowCase):
    def test_closing_detaches_the_game_before_the_frame_is_destroyed(self):
        # X destroys children with their parent, and RetroArch aborts on
        # losing its window instead of exiting cleanly.
        self.win._child_xid = 0x200
        self.win._do_cleanup()
        self.embedder.release.assert_called_once_with(0x200)
        self.assertIsNone(self.win._child_xid)
        self.embedder.close.assert_called_once()

    def test_closing_stops_the_game_and_tells_the_owner(self):
        self.win._do_cleanup()
        self.assertEqual(self.runtime.stopped, [False])
        self.assertEqual(self.closed, [self.win])

    def test_a_blocking_close_waits_for_the_game_to_be_gone(self):
        self.win.close_now(block=True)
        self.assertEqual(self.runtime.stopped, [True])

    def test_cleanup_runs_once_however_many_paths_reach_it(self):
        self.win._do_cleanup()
        self.win._do_cleanup()
        self.assertEqual(len(self.closed), 1)

    def test_the_running_timers_are_taken_down(self):
        self.win._tick_id = 7
        self.win._volume_watch_id = 9
        with mock.patch.object(game_window_module.GLib, "source_remove") as remove:
            self.win._do_cleanup()
        self.assertEqual(remove.call_count, 2)

    def test_a_game_that_already_exited_is_not_stopped_again(self):
        self.win._proc = _Process(exit_code=0)
        self.win._do_cleanup()
        self.assertEqual(self.runtime.stopped, [])

    def test_a_standalone_fallback_leaves_the_game_to_its_owner(self):
        # Stopping it here would race the owner's own relaunch: two stop
        # escalations against one process.
        self.win._standalone_fallback = True
        self.win._child_xid = 0x200
        self.win._do_cleanup()
        self.embedder.release.assert_called_once_with(0x200)
        self.assertEqual(self.runtime.stopped, [])
        self.assertEqual(self.closed, [self.win])

    def test_the_owner_is_told_exactly_once(self):
        self.win._notify_closed()
        self.win._notify_closed()
        self.assertEqual(len(self.closed), 1)

    def test_the_x_button_tears_down_without_vetoing_the_close(self):
        self.assertFalse(self.win._on_close_request(self.win))
        self.assertTrue(self.win._closing)

    def test_a_wrapper_that_gave_up_reports_why_and_closes_itself(self):
        self.win._fall_back_to_standalone("no reason at all")
        self.assertTrue(self.win._standalone_fallback)
        self.assertEqual(self.embed_failures, ["no reason at all"])

    def test_a_second_failure_cannot_report_twice(self):
        self.win._fall_back_to_standalone("first")
        self.win._standalone_fallback = False
        self.win._closing = False
        self.win._fall_back_to_standalone("second")
        self.assertEqual(self.embed_failures, ["first"])


@needs_display
class TheGameScreenWidgetTests(unittest.TestCase):
    def test_it_asks_for_a_size_in_both_directions(self):
        screen = _GameScreen(None)
        self.assertEqual(
            screen.do_measure(Gtk.Orientation.HORIZONTAL, -1), (320, 900, -1, -1)
        )
        self.assertEqual(
            screen.do_measure(Gtk.Orientation.VERTICAL, -1), (240, 860, -1, -1)
        )

    def test_a_plain_screen_paints_black_and_nothing_else(self):
        screen = _GameScreen(None)
        snapshot = Gtk.Snapshot()
        screen.do_snapshot(snapshot)

    def test_a_framed_screen_paints_the_artwork_over_the_black(self):
        texture = GameWindow._load_frame_texture()
        if texture is None:
            self.skipTest("the CRT frame asset is not readable here")
        screen = _GameScreen(texture)
        snapshot = Gtk.Snapshot()
        with mock.patch.object(screen, "get_width", return_value=800), (
            mock.patch.object(screen, "get_height", return_value=600)
        ):
            screen.do_snapshot(snapshot)

    def test_the_game_rect_follows_whether_there_is_a_frame(self):
        plain = _GameScreen(None)
        with mock.patch.object(plain, "get_width", return_value=800), (
            mock.patch.object(plain, "get_height", return_value=600)
        ):
            self.assertEqual(plain.screen_rect(), (0, 0, 800, 600))


@needs_display
class DisplayBackendTests(unittest.TestCase):
    def test_an_x11_display_can_host_an_embed(self):
        display = mock.Mock()
        type(display).__name__ = "X11Display"
        with mock.patch.object(Gdk.Display, "get_default", return_value=display):
            self.assertTrue(display_supports_embedding())

    def test_a_wayland_display_can_never_host_one(self):
        # Embedding is XReparentWindow underneath.
        class WaylandDisplay:
            pass

        with mock.patch.object(
            Gdk.Display, "get_default", return_value=WaylandDisplay()
        ):
            self.assertFalse(display_supports_embedding())

    def test_no_display_at_all_cannot_host_one(self):
        with mock.patch.object(Gdk.Display, "get_default", return_value=None):
            self.assertFalse(display_supports_embedding())


if __name__ == "__main__":
    unittest.main()
