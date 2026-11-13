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
    from openemux.core.systems import get_system_display_name
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

        self.stopped = 0
        self.checked_bios = None

    def launch(self, path, console, state_slot=None, resume=True, check_bios=True):
        self.launched.append((path, console, state_slot))
        self.resumed = resume
        self.checked_bios = check_bios
        return self.launch_result

    def stop_active(self, block=False):
        self.stopped += 1
        return True, None

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


class _Worker:
    """Stands in for the launch worker: runs at once, or when the test says.

    Only the session's own seam is replaced -- patching ``threading.Thread``
    itself would also catch the cover pool's workers, which then run their
    loop inline and wait forever on an empty queue.
    """

    deferred = None  # a list while a test wants to step the worker itself

    @classmethod
    def run(cls, target):
        if cls.deferred is not None:
            cls.deferred.append(target)
        else:
            target()


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
            self.said(
                "toast.running",
                name=rom["name"],
                console=get_system_display_name(rom["console"]),
            ),
            self.toasts,
        )

    def test_a_launch_resumes_unless_told_to_start_fresh(self):
        # Issue 910: "Start fresh" is the one launch that skips the auto state.
        rom = self.rom()
        self.session.launch(rom)
        self.assertTrue(self.runtime.resumed)
        self.session.launch(rom, resume=False)
        self.assertFalse(self.runtime.resumed)

    def test_a_launch_flushes_a_setting_still_waiting_for_its_write(self):
        # Issue 905: a session that ends with the app would lose the last
        # half second of settings otherwise.
        self.config.set_zoom(1.5)
        self.assertTrue(self.config.has_pending_save())
        self.session.launch(self.rom())
        self.assertFalse(self.config.has_pending_save())

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
class TheWorkerSeamTests(unittest.TestCase):
    def test_the_real_seam_runs_the_target_on_another_thread(self):
        import threading

        done = threading.Event()
        names = []

        def _target():
            names.append(threading.current_thread().name)
            done.set()

        with mock.patch.object(session_module, "_run_in_worker", wraps=session_module._run_in_worker):
            session_module._run_in_worker(_target)
        self.assertTrue(done.wait(5))
        self.assertEqual(names, ["openemux-launch"])


@needs_display
class TheStartingStateTests(_SessionCase):
    """Issue 904: the click answers at once; the process comes up on a worker."""

    def test_the_card_starts_and_the_banner_offers_stop_until_the_process_is_up(self):
        rom = self.rom()
        self.defer_worker()
        with mock.patch.object(self.win, "set_rom_launching") as launching:
            self.session.launch(rom)
            self.assertEqual(launching.call_args_list, [mock.call(rom, True)])
            self.assertEqual(self.runtime.launched, [])
            self.assertEqual(len(self.win.tasks), 1)
            self.assertEqual(
                self.win.tasks.banner.get_title(), self.said("banner.starting", name=rom["name"])
            )
            self.assertEqual(self.win.tasks.banner.get_button_label(), self.said("banner.stop"))
            self.run_worker()
            self.assertEqual(launching.call_args_list[-1], mock.call(rom, False))
        self.assertEqual(self.runtime.launched[0][:2], (rom["path"], rom["console"]))
        self.assertEqual(
            self.win.tasks.banner.get_title(), self.said("banner.playing", name=rom["name"])
        )

    def test_a_second_click_while_one_is_starting_is_ignored(self):
        rom = self.rom()
        self.defer_worker()
        self.session.launch(rom)
        self.session.launch(rom)
        self.session.launch_at_state(rom, 2)
        self.run_worker()
        self.assertEqual(len(self.runtime.launched), 1)

    def test_stop_pressed_while_starting_stops_the_game_once_it_is_up(self):
        self.defer_worker()
        self.session.launch(self.rom())
        self.win.tasks.banner.emit("button-clicked")
        self.assertEqual(self.runtime.stopped, 0)
        self.run_worker()
        self.assertEqual(self.runtime.stopped, 1)

    def test_stop_on_a_running_game_quits_it(self):
        self.session.launch(self.rom())
        self.session.stop()
        self.assertEqual(self.runtime.stopped, 1)

    def test_a_failed_launch_clears_the_card_and_the_banner(self):
        self.runtime.launch_result = (False, "toast.launch_busy")
        rom = self.rom()
        with mock.patch.object(self.win, "set_rom_launching") as launching:
            self.session.launch(rom)
        self.assertEqual(launching.call_args_list[-1], mock.call(rom, False))
        self.assertEqual(len(self.win.tasks), 0)

    def test_the_banner_goes_when_the_game_ends(self):
        rom = self.rom()
        self.session.launch(rom)
        self.assertEqual(len(self.win.tasks), 1)
        self.runtime.poll_result = {"rom": rom, "exit_code": 0, "ran_for": 70.0}
        self.session.poll()
        self.assertEqual(len(self.win.tasks), 0)

    def test_the_real_card_shows_the_state(self):
        grid = self.show_with_cards("SFC")
        entry = grid.entries()[0]
        card = grid.card_for(entry)
        self.defer_worker()
        self.session.launch(entry.rom)
        self.assertTrue(card.launching)
        self.run_worker()
        self.assertFalse(card.launching)
        self.assertFalse(grid.set_rom_launching({"path": "/nowhere.sfc"}, True))


@needs_display
class ACoreFetchedOnLaunchTests(_SessionCase):
    """Issue 909: a console whose core never arrived gets it when a game is launched."""

    def test_the_core_is_prepared_before_the_launch(self):
        rom = self.rom()
        self.session.launch(rom)
        self.assertEqual(self.core_calls[0][0], rom["console"])
        self.assertEqual(self.runtime.launched[0][:2], (rom["path"], rom["console"]))

    def test_the_download_progress_shows_on_the_banner(self):
        rom = self.rom()
        self.defer_worker()
        self.session.launch(rom)
        self.run_worker()
        _console, on_progress, _event = self.core_calls[0]
        on_progress({"current": 1, "total": 3})
        self.assertEqual(
            self.win.tasks.banner.get_title(),
            self.said("banner.preparing", console=get_system_display_name(rom["console"])) + " (1/3)",
        )

    def test_a_failed_download_says_so_and_launches_nothing(self):
        self.core_state = "failed"
        rom = self.rom()
        self.session.launch(rom)
        self.assertEqual(self.runtime.launched, [])
        self.assertIn(
            self.said("toast.core_download_failed", console=get_system_display_name(rom["console"])),
            self.toasts,
        )
        self.assertEqual(len(self.win.tasks), 0)

    def test_stop_while_the_core_downloads_cancels_quietly(self):
        rom = self.rom()
        self.defer_worker()
        self.session.launch(rom)
        self.win.tasks.banner.emit("button-clicked")
        self.assertTrue(self.session._cancel_event.is_set())
        self.core_state = "cancelled"
        self.run_worker()
        self.assertEqual(self.runtime.launched, [])
        self.assertEqual(self.toasts, [])
        self.assertEqual(len(self.win.tasks), 0)
        self.assertIsNone(self.session._launching)


@needs_display
class TheBiosDialogTests(_SessionCase):
    """Issue 904: the missing files by name, and the page that takes them."""

    def _ask(self, rom):
        self.missing_bios = ["scph5501.bin", "scph5502.bin"]
        with self.caught_dialog() as caught:
            self.session.launch(rom)
        self.assertEqual(self.runtime.launched, [])
        self.assertEqual(len(caught), 1)
        return caught[0]

    def test_the_dialog_names_the_files_and_the_console(self):
        rom = self.rom()
        dialog = self._ask(rom)
        self.assertEqual(
            dialog.get_heading(),
            self.said("bios.dialog.heading", console=get_system_display_name(rom["console"])),
        )
        self.assertIn("scph5501.bin, scph5502.bin", dialog.get_body())

    def test_open_takes_the_user_to_the_console_on_the_bios_page(self):
        rom = self.rom()
        dialog = self._ask(rom)
        with mock.patch.object(self.win, "open_bios_settings") as open_bios:
            dialog.emit("response", "open")
        open_bios.assert_called_once_with(rom["console"])
        self.assertEqual(self.runtime.launched, [])

    def test_launch_anyway_skips_the_check_at_the_launcher(self):
        rom = self.rom()
        dialog = self._ask(rom)
        dialog.emit("response", "launch")
        self.assertEqual(self.runtime.launched[0][:2], (rom["path"], rom["console"]))
        self.assertFalse(self.runtime.checked_bios)

    def test_cancel_launches_nothing(self):
        dialog = self._ask(self.rom())
        dialog.emit("response", "cancel")
        self.assertEqual(self.runtime.launched, [])

    def test_a_console_with_its_files_gets_no_dialog(self):
        with self.caught_dialog() as caught:
            self.session.launch(self.rom())
        self.assertEqual(caught, [])
        self.assertTrue(self.runtime.checked_bios)


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

    def test_a_finished_game_says_what_was_played_and_for_how_long(self):
        # Issue 904: the game's title and the time, not the file and the code.
        self.runtime.poll_result = {
            "rom": {"path": "/roms/SFC/Chrono Trigger.sfc"},
            "exit_code": 0,
            "ran_for": 80 * 60,
        }
        self.session.poll()
        self.assertIn(
            self.said(
                "toast.played",
                name="Chrono Trigger",
                time=self.said("duration.hours", hours=1, minutes=20),
            ),
            self.toasts,
        )

    def test_the_title_comes_from_the_index_when_the_game_is_in_it(self):
        rom = self.rom()
        self.runtime.poll_result = {"rom": rom, "exit_code": 0, "ran_for": 12 * 60}
        self.session.poll()
        self.assertIn(
            self.said(
                "toast.played", name=rom["name"], time=self.said("duration.minutes", minutes=12)
            ),
            self.toasts,
        )

    def test_a_nonzero_exit_code_is_named_with_the_log_one_click_away(self):
        shown = []
        self.runtime.poll_result = {
            "rom": {"path": "/roms/SFC/x.sfc"}, "exit_code": 139, "ran_for": 5.0
        }
        with mock.patch.object(self.win.toast_overlay, "add_toast", shown.append):
            self.session.poll()
        toast = shown[-1]
        self.assertEqual(
            toast.get_title(),
            self.said(
                "toast.played.code", name="x", time=self.said("duration.under_minute"), code=139
            ),
        )
        self.assertEqual(toast.get_button_label(), self.said("toast.show_log"))
        with mock.patch.object(self.win, "set_log_panel_visible") as show_log:
            toast.emit("button-clicked")
        show_log.assert_called_once_with(True)

    def test_a_launch_that_died_offers_the_log_too(self):
        shown = []
        self.runtime.poll_result = {
            "rom": {"path": "/roms/SFC/x.sfc"}, "exit_code": 1, "failure_reason": "core not found"
        }
        with mock.patch.object(self.win.toast_overlay, "add_toast", shown.append):
            self.session.poll()
        self.assertEqual(shown[-1].get_button_label(), self.said("toast.show_log"))

    def test_the_duration_is_worded_by_its_size(self):
        self.assertEqual(self.session._duration_text(None), self.said("duration.under_minute"))
        self.assertEqual(
            self.session._duration_text(12 * 60), self.said("duration.minutes", minutes=12)
        )
        self.assertEqual(
            self.session._duration_text(80 * 60), self.said("duration.hours", hours=1, minutes=20)
        )

    def test_a_finished_game_adds_its_time_and_tells_the_window(self):
        # Issue 910: the session's length goes on the play time, and the
        # library re-reads what it shows about the game.
        rom = self.rom()
        self.runtime.poll_result = {"rom": rom, "exit_code": 0, "ran_for": 125.0}
        with mock.patch.object(self.win, "on_game_ended") as ended:
            self.session.poll()
        self.assertEqual(self.win.play_history.play_seconds(rom["path"]), 125.0)
        ended.assert_called_once_with(rom)

    def test_a_game_that_never_started_adds_no_time(self):
        rom = self.rom()
        self.runtime.poll_result = {
            "rom": rom, "exit_code": 1, "failure_reason": "core not found", "ran_for": 0.5
        }
        with mock.patch.object(self.win, "on_game_ended"):
            self.session.poll()
        self.assertEqual(self.win.play_history.play_seconds(rom["path"]), 0.0)

    def test_a_game_that_never_started_says_what_the_log_said(self):
        # Issue #226: the exit code alone reads exactly like a clean quit.
        self.runtime.poll_result = {
            "rom": {"path": "/roms/SFC/x.sfc"},
            "exit_code": 1,
            "failure_reason": "core not found",
        }
        self.session.poll()
        # The game's title, not the file (issue 904): the stem when the index
        # has no name for it.
        self.assertIn(
            self.said("toast.launch_died", name="x", reason="core not found"),
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
        self.assertIn(
            self.said("toast.played", name="Game", time=self.said("duration.under_minute")),
            self.toasts,
        )


if __name__ == "__main__":
    unittest.main()
