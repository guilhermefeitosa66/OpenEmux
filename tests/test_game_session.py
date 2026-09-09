"""Everything about a game between the click and the exit toast.

`ui/game_session.py` sat at 24%: it is five responsibilities that only make
sense together -- launch, the wrapper window, the relaunch dance, the input
hot-apply and the runtime poll -- and all five run on timers against a live
RetroArch, so nothing here ever ran in the suite.

The runtime manager is a recorder, so no process is started. The timers are
driven by hand: `GLib.timeout_add` is replaced with a queue the test steps
through, which is what makes the relaunch dance (issue #129) assertable
instead of a five-second wait.
"""

import unittest
from unittest import mock

from tests.gtk_display import HAVE_DISPLAY, needs_display
from tests.window_harness import WindowCase

if HAVE_DISPLAY:
    from openemux.ui import game_session as session_module
    from openemux.ui.game_session import (
        RELAUNCH_MAX_POLLS,
        SNAPSHOT_MAX_POLLS,
    )


class _Runtime:
    """The runtime manager, reduced to what a session asks of it."""

    def __init__(self):
        self.launched = []
        self.launch_result = (True, None)
        self.running = False
        self.launch_notice = None
        self.active_rom = {"name": "Chrono Trigger", "console": "SFC"}
        self.relaunch_result = (self.active_rom, None)
        self.relaunch_rom_result = (True, None)
        self.snapshot = {"slot": 99}
        self.snapshot_is_ready = True
        self.loaded_slots = []
        self.discarded = []
        self.poll_result = None
        self.load_state_calls = 0

    def launch(self, path, console, state_slot=None):
        self.launched.append((path, console, state_slot))
        return self.launch_result

    def is_running(self):
        return self.running

    def relaunch_active(self):
        return self.relaunch_result

    def relaunch_rom(self, _rom):
        return self.relaunch_rom_result

    def snapshot_active(self):
        return self.snapshot

    def snapshot_ready(self, _marker):
        return self.snapshot_is_ready

    def load_state_slot(self, slot):
        self.loaded_slots.append(slot)

    def load_state(self):
        self.load_state_calls += 1

    def discard_snapshot(self, marker):
        self.discarded.append(marker)

    def poll_active(self):
        return self.poll_result


class _Timers:
    """Stands in for GLib's timers so a dance can be stepped through."""

    def __init__(self):
        self.pending = []

    def add(self, _interval, callback, *args):
        self.pending.append((callback, args))
        return len(self.pending)

    def step(self, times=1):
        """Fire the queued callbacks; a callback asking to repeat is requeued."""
        for _ in range(times):
            if not self.pending:
                return
            callback, args = self.pending.pop(0)
            if callback(*args):
                self.pending.append((callback, args))

    def drain(self, limit=200):
        while self.pending and limit:
            limit -= 1
            self.step()


class _SessionCase(WindowCase):
    def setUp(self):
        super().setUp()
        self.runtime = _Runtime()
        self.win.runtime_manager = self.runtime
        self.session = self.win.game
        self.timers = _Timers()
        for name in ("timeout_add", "timeout_add_seconds"):
            patcher = mock.patch.object(
                session_module.GLib, name, self.timers.add
            )
            patcher.start()
            self.addCleanup(patcher.stop)
        wrapper_patch = mock.patch.object(self.session, "open_wrapper")
        self.open_wrapper = wrapper_patch.start()
        self.addCleanup(wrapper_patch.stop)


@needs_display
class LaunchingTests(_SessionCase):
    def test_a_launch_records_the_play_and_wraps_the_game(self):
        rom = self.rom()
        self.session.launch(rom)
        self.assertEqual(self.runtime.launched[0][:2], (rom["path"], rom["console"]))
        self.assertEqual(self.win.play_history.play_count(rom["path"]), 1)
        self.open_wrapper.assert_called_once_with(rom)
        self.assertIn(
            self.said("toast.running", name=rom["name"], console=rom["console"]),
            self.toasts,
        )

    def test_a_refused_launch_says_why_and_wraps_nothing(self):
        self.runtime.launch_result = (False, "toast.launch_busy")
        self.session.launch(self.rom())
        self.open_wrapper.assert_not_called()
        self.assertEqual(self.toasts, [self.said("toast.launch_busy")])

    def test_a_launch_that_raises_is_reported_rather_than_swallowed(self):
        # Issue #226: a click handler is where an exception goes to die
        # quietly -- PyGObject prints the traceback and the button does
        # nothing.
        self.runtime.launch = mock.Mock(side_effect=RuntimeError("no core"))
        self.session.launch(self.rom())
        self.assertEqual(
            self.toasts, [self.said("toast.launch_failed", error="no core")]
        )

    def test_a_launch_that_worked_but_lost_a_shader_says_so_too(self):
        # Issue #366: the game runs and nothing looks wrong on screen.
        self.runtime.launch_notice = ("toast.shader.unavailable", {"shader": "crt"})
        self.session.launch(self.rom())
        self.assertIn(
            self.said("toast.shader.unavailable", shader="crt"), self.toasts
        )

    def test_a_launch_with_nothing_to_report_says_only_that_it_is_running(self):
        self.session.launch(self.rom())
        self.assertEqual(len(self.toasts), 1)


@needs_display
class LaunchingAtASaveStateTests(_SessionCase):
    def test_the_slot_is_seeded_and_the_state_loaded_once_the_game_is_up(self):
        rom = self.rom()
        self.session.launch_at_state(rom, 3)
        self.assertEqual(self.runtime.launched[0][2], 3)
        self.assertIn(
            self.said("states.toast.launching", name=rom["name"], slot=3), self.toasts
        )
        self.runtime.running = True
        self.timers.drain()
        self.assertEqual(self.runtime.load_state_calls, 1)

    def test_a_game_that_never_came_up_is_sent_no_state(self):
        self.session.launch_at_state(self.rom(), 3)
        self.runtime.running = False
        self.timers.drain()
        self.assertEqual(self.runtime.load_state_calls, 0)

    def test_a_refused_launch_says_why_and_loads_nothing(self):
        self.runtime.launch_result = (False, "toast.launch_busy")
        self.session.launch_at_state(self.rom(), 3)
        self.open_wrapper.assert_not_called()
        self.assertEqual(self.toasts, [self.said("toast.launch_busy")])

    def test_a_refused_launch_with_no_reason_says_nothing(self):
        self.runtime.launch_result = (False, None)
        self.session.launch_at_state(self.rom(), 3)
        self.assertEqual(self.toasts, [])


@needs_display
class TheRelaunchDanceTests(_SessionCase):
    """Issue #129: only a fresh process re-reads the runtime override."""

    def test_a_relaunch_waits_for_the_old_process_then_starts_the_new_one(self):
        self.runtime.running = True
        self.assertTrue(self.session.relaunch())
        self.assertIn(self.said("toast.relaunching"), self.toasts)
        self.assertTrue(self.session._relaunch_in_flight)
        self.timers.step()
        self.assertTrue(self.session._relaunch_in_flight)
        self.runtime.running = False
        self.timers.step()
        self.assertFalse(self.session._relaunch_in_flight)
        self.open_wrapper.assert_called_once()

    def test_a_relaunch_the_runtime_refuses_is_reported(self):
        self.runtime.relaunch_result = (None, "nothing is running")
        self.assertFalse(self.session.relaunch())
        self.assertEqual(self.toasts, ["nothing is running"])

    def test_a_refusal_with_no_reason_says_nothing(self):
        self.runtime.relaunch_result = (None, None)
        self.assertFalse(self.session.relaunch())
        self.assertEqual(self.toasts, [])

    def test_a_caller_that_already_explained_itself_is_not_announced(self):
        self.session.relaunch(announce=False)
        self.assertNotIn(self.said("toast.relaunching"), self.toasts)

    def test_a_game_that_will_not_stop_gives_up_and_says_so(self):
        # The budget has to outlast the stop escalation -- QUIT, SIGTERM,
        # SIGKILL -- or a RetroArch ignoring QUIT is declared un-relaunchable
        # while it is still being killed.
        self.runtime.running = True
        self.session.relaunch()
        self.timers.step(RELAUNCH_MAX_POLLS)
        self.assertIn(self.said("toast.relaunch_failed"), self.toasts)
        self.assertFalse(self.session._relaunch_in_flight)

    def test_a_relaunch_that_will_not_start_reports_the_error(self):
        self.runtime.relaunch_rom_result = (False, "core is gone")
        self.session.relaunch()
        self.timers.step()
        self.assertIn("core is gone", self.toasts)
        self.open_wrapper.assert_not_called()

    def test_a_carried_snapshot_is_loaded_back_and_then_thrown_away(self):
        marker = {"slot": 99}
        self.session.relaunch(resume_marker=marker)
        self.timers.step()
        self.runtime.running = True
        self.timers.step()
        self.assertEqual(self.runtime.loaded_slots, [99])
        self.timers.step()
        self.assertEqual(self.runtime.discarded, [marker])

    def test_a_snapshot_is_not_loaded_into_a_game_that_never_came_up(self):
        self.session.relaunch(resume_marker={"slot": 99})
        self.timers.step()
        self.runtime.running = False
        self.timers.drain()
        self.assertEqual(self.runtime.loaded_slots, [])


@needs_display
class ApplyingARemapMidGameTests(_SessionCase):
    def test_nothing_is_applied_while_no_game_is_running(self):
        self.runtime.running = False
        self.assertFalse(self.session.apply_input_changes())

    def test_a_core_that_cannot_save_states_is_not_relaunched(self):
        # Losing the game to apply a binding is worse than the binding
        # waiting for the next launch.
        self.runtime.running = True
        self.runtime.snapshot_active = lambda: None
        self.assertFalse(self.session.apply_input_changes())
        self.assertEqual(self.toasts, [self.said("toast.input_apply.no_state")])

    def test_the_snapshot_is_waited_for_and_then_carried_across(self):
        self.runtime.running = True
        self.runtime.snapshot_is_ready = False
        self.assertTrue(self.session.apply_input_changes())
        self.assertIn(self.said("toast.input_apply.saving"), self.toasts)
        self.timers.step()
        self.runtime.snapshot_is_ready = True
        with mock.patch.object(self.session, "relaunch") as relaunch:
            self.timers.step()
        relaunch.assert_called_once_with(resume_marker=self.runtime.snapshot)

    def test_a_game_that_quits_mid_apply_is_left_alone(self):
        self.runtime.running = True
        self.runtime.snapshot_is_ready = False
        self.session.apply_input_changes()
        self.runtime.running = False
        with mock.patch.object(self.session, "relaunch") as relaunch:
            self.timers.drain()
        relaunch.assert_not_called()

    def test_a_snapshot_that_never_lands_times_out_rather_than_relaunching(self):
        self.runtime.running = True
        self.runtime.snapshot_is_ready = False
        self.session.apply_input_changes()
        with mock.patch.object(self.session, "relaunch") as relaunch:
            self.timers.step(SNAPSHOT_MAX_POLLS)
        relaunch.assert_not_called()
        self.assertIn(self.said("toast.input_apply.no_state"), self.toasts)


@needs_display
class NoticingTheGameEndedTests(_SessionCase):
    def test_a_running_game_reports_nothing(self):
        self.assertTrue(self.session.poll())
        self.assertEqual(self.toasts, [])

    def test_a_finished_game_names_it_and_its_exit_code(self):
        self.runtime.poll_result = {
            "rom": {"path": "/roms/SFC/Chrono Trigger.sfc"},
            "exit_code": 0,
        }
        self.session.poll()
        self.assertIn(
            self.said("toast.finished", name="Chrono Trigger.sfc", code=0),
            self.toasts,
        )

    def test_a_game_that_never_started_says_what_the_log_said(self):
        # Issue #226: the exit code alone reads exactly like a clean quit.
        self.runtime.poll_result = {
            "rom": {"path": "/roms/SFC/x.sfc"},
            "exit_code": 1,
            "failure_reason": "core not found",
        }
        self.session.poll()
        self.assertIn(
            self.said("toast.launch_died", name="x.sfc", reason="core not found"),
            self.toasts,
        )

    def test_a_relaunch_stopping_the_game_is_not_announced_as_finished(self):
        # Issue #267: a relaunch stops the game on purpose.
        self.session._relaunch_in_flight = True
        self.runtime.poll_result = {"rom": {}, "exit_code": 0}
        self.assertTrue(self.session.poll())
        self.assertEqual(self.toasts, [])

    def test_a_result_with_no_rom_on_record_still_reports(self):
        self.runtime.poll_result = {"exit_code": 0}
        self.session.poll()
        self.assertIn(self.said("toast.finished", name="Game", code=0), self.toasts)


@needs_display
class TheWrapperWindowTests(WindowCase):
    """Opening, closing and giving up on the window around the game."""

    def setUp(self):
        super().setUp()
        self.session = self.win.game
        self.runtime = _Runtime()
        self.win.runtime_manager = self.runtime
        self.built = []
        patcher = mock.patch(
            "openemux.ui.game_window.GameWindow", self._build_window
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        embed_patch = mock.patch(
            "openemux.ui.game_window.display_supports_embedding", return_value=True
        )
        embed_patch.start()
        self.addCleanup(embed_patch.stop)
        active_patch = mock.patch.object(
            session_module.game_window_support, "game_window_active", return_value=True
        )
        active_patch.start()
        self.addCleanup(active_patch.stop)

    def _build_window(self, **kwargs):
        window = mock.Mock()
        window.kwargs = kwargs
        self.built.append(window)
        return window

    def test_a_launch_opens_a_wrapper_around_the_game(self):
        rom = self.rom()
        self.session.open_wrapper(rom)
        self.assertEqual(len(self.built), 1)
        self.assertIs(self.session.window, self.built[0])
        self.built[0].present.assert_called_once()

    def test_a_second_launch_replaces_the_wrapper_rather_than_stacking_one(self):
        self.session.open_wrapper(self.rom())
        first = self.built[0]
        self.session.open_wrapper(self.rom())
        first.close.assert_called_once()
        self.assertIs(self.session.window, self.built[1])

    def test_a_session_that_cannot_embed_says_so_once_and_opens_nothing(self):
        # Issue #212: a user on such a session would otherwise be told off
        # every time they start a game.
        with mock.patch.object(
            session_module.game_window_support, "game_window_active", return_value=False
        ):
            self.session.open_wrapper(self.rom())
            self.session.open_wrapper(self.rom())
        self.assertEqual(self.built, [])
        self.assertEqual(
            self.toasts.count(self.said("toast.game_window.unavailable")), 1
        )

    def test_a_user_who_turned_the_wrapper_off_is_not_told_anything(self):
        self.config.set_game_window_enabled(False)
        with mock.patch.object(
            session_module.game_window_support, "game_window_active", return_value=False
        ):
            self.session.open_wrapper(self.rom())
        self.assertEqual(self.toasts, [])

    def test_a_display_that_turns_out_not_to_be_x11_publishes_that_verdict(self):
        # Publishing it is what stops the launcher writing the embed
        # overrides for the next launch (issue #212).
        with mock.patch(
            "openemux.ui.game_window.display_supports_embedding", return_value=False
        ), mock.patch.object(
            session_module.game_window_support, "set_display_embeddable"
        ) as publish:
            self.session.open_wrapper(self.rom())
        publish.assert_called_once_with(False)
        self.assertEqual(self.built, [])

    def test_the_wrapper_reporting_itself_closed_clears_the_handle(self):
        self.session.open_wrapper(self.rom())
        self.session._on_closed(self.built[0])
        self.assertIsNone(self.session.window)

    def test_another_wrappers_close_does_not_clear_the_current_one(self):
        self.session.open_wrapper(self.rom())
        self.session._on_closed(mock.Mock())
        self.assertIsNotNone(self.session.window)

    def test_closing_the_app_takes_the_wrapper_down_synchronously(self):
        self.session.open_wrapper(self.rom())
        window = self.built[0]
        self.session.close_now()
        window.close_now.assert_called_once_with(block=True)
        self.assertIsNone(self.session.window)

    def test_closing_with_no_wrapper_up_is_harmless(self):
        self.session.close_now()

    def test_a_closed_wrapper_is_destroyed_rather_than_left_hidden(self):
        window = mock.Mock()
        with mock.patch.object(session_module.GLib, "idle_add") as idle_add:
            self.assertFalse(self.session._on_close_request(window))
        idle_add.assert_called_once_with(window.destroy)

    def test_the_controller_button_brings_the_library_forward_first(self):
        # The game window keeps handing X focus to the emulator, which would
        # fight a dialog shown on top of it.
        with mock.patch.object(self.win, "present") as present, mock.patch.object(
            self.win, "_open_preferences"
        ) as prefs:
            self.session._open_input_settings(None)
        present.assert_called_once()
        prefs.assert_called_once_with(page="input")


@needs_display
class WhenTheEmbedFailsTests(WindowCase):
    """Issue #267: the game is running with its decorations already stripped."""

    def setUp(self):
        super().setUp()
        self.session = self.win.game
        self.runtime = _Runtime()
        self.win.runtime_manager = self.runtime
        reason_patch = mock.patch.object(
            session_module.game_window_support,
            "embed_unavailable_reason",
            return_value=None,
        )
        reason_patch.start()
        self.addCleanup(reason_patch.stop)
        mark_patch = mock.patch.object(
            session_module.game_window_support, "mark_embed_unavailable"
        )
        self.mark = mark_patch.start()
        self.addCleanup(mark_patch.stop)

    def test_the_failure_is_latched_and_the_game_put_back_in_a_window(self):
        self.runtime.running = True
        with mock.patch.object(self.session, "relaunch") as relaunch:
            self.session._on_embed_failed("reparenting failed")
        self.mark.assert_called_once_with("reparenting failed")
        relaunch.assert_called_once_with(announce=False)
        self.assertIn(self.said("toast.game_window.standalone"), self.toasts)

    def test_a_failure_already_latched_cannot_loop(self):
        with mock.patch.object(
            session_module.game_window_support,
            "embed_unavailable_reason",
            return_value="already",
        ), mock.patch.object(self.session, "relaunch") as relaunch:
            self.session._on_embed_failed("again")
        relaunch.assert_not_called()
        self.mark.assert_not_called()

    def test_a_game_that_died_with_the_wrapper_is_not_relaunched(self):
        self.runtime.running = False
        with mock.patch.object(self.session, "relaunch") as relaunch:
            self.session._on_embed_failed("reparenting failed")
        relaunch.assert_not_called()
        self.assertEqual(self.toasts, [])

    def test_the_unavailable_notice_is_not_said_twice_over_this_one(self):
        self.runtime.running = True
        with mock.patch.object(self.session, "relaunch"):
            self.session._on_embed_failed("reparenting failed")
        self.assertTrue(self.session._notice_shown)


if __name__ == "__main__":
    unittest.main()
