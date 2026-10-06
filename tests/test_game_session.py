"""Everything about a game between the click and the exit toast.

`ui/game_session.py` sat at 24%: it is several responsibilities that only make
sense together -- launch, the relaunch dance, the input hot-apply and the
runtime poll -- and they run on timers against a live RetroArch, so nothing
here ever ran in the suite. (The wrapper window that used to be one of them
went with issue #469.)

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
        self.relaunched = []

    def launch(self, path, console, state_slot=None):
        self.launched.append((path, console, state_slot))
        return self.launch_result

    def is_running(self):
        return self.running

    def relaunch_active(self):
        return self.relaunch_result

    def relaunch_rom(self, rom):
        self.relaunched.append(rom)
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


@needs_display
class LaunchingTests(_SessionCase):
    def test_a_launch_records_the_play_and_says_it_is_running(self):
        rom = self.rom()
        self.session.launch(rom)
        self.assertEqual(self.runtime.launched[0][:2], (rom["path"], rom["console"]))
        self.assertEqual(self.win.play_history.play_count(rom["path"]), 1)
        self.assertIn(
            self.said("toast.running", name=rom["name"], console=rom["console"]),
            self.toasts,
        )

    def test_a_refused_launch_says_why_and_records_nothing(self):
        self.runtime.launch_result = (False, "toast.launch_busy")
        rom = self.rom()
        self.session.launch(rom)
        self.assertEqual(self.win.play_history.play_count(rom["path"]), 0)
        self.assertEqual(self.toasts, [self.said("toast.launch_busy")])

    def test_a_refused_launch_is_logged_as_well_as_toasted(self):
        # The toast is gone in five seconds; a bug report is built from the
        # log, and it must show what the user saw (issue #461).
        self.runtime.launch_result = (False, "toast.launch_busy")
        rom = self.rom()
        with self.assertLogs("openemux.ui.game_session", "ERROR") as logs:
            self.session.launch(rom)
        self.assertIn("toast.launch_busy", logs.output[-1])
        self.assertIn(rom["name"], logs.output[-1])

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
        self.assertEqual(self.runtime.relaunched, [self.runtime.active_rom])

    def test_a_relaunch_the_runtime_refuses_is_reported(self):
        self.runtime.relaunch_result = (None, "nothing is running")
        self.assertFalse(self.session.relaunch())
        self.assertEqual(self.toasts, ["nothing is running"])

    def test_a_refusal_with_no_reason_says_nothing(self):
        self.runtime.relaunch_result = (None, None)
        self.assertFalse(self.session.relaunch())
        self.assertEqual(self.toasts, [])

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


if __name__ == "__main__":
    unittest.main()
