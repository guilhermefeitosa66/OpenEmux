"""RuntimeManager's live control of a running game (issues #69, #125)."""

import threading
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from openemux.core.retroarch_command import VOLUME_PACING_INTERVAL, VolumePacer
from openemux.core.runtime_manager import (
    HOT_APPLY_STATE_SLOT,
    STARTUP_FAILURE_SECONDS,
    RuntimeManager,
)


class _DummyConfig:
    """The smallest config surface RuntimeManager touches."""

    def __init__(self, base_dir, volume_db=0.0, port=55355):
        self.base_dir = Path(base_dir)
        self.master_volume_db = volume_db
        self.port = port
        self.volume_writes = []

    def get_master_volume_db(self):
        return self.master_volume_db

    def set_master_volume_db(self, value):
        self.master_volume_db = value
        self.volume_writes.append(value)

    def get_network_cmd_port(self):
        return self.port

    def get_runtime_mode_for_console(self, _console):
        return "retroarch_wrapper"

    def get_runtime_dir(self):
        return self.base_dir / "runtime"

    def get_console_states_dir(self, console):
        return self.base_dir / "states" / str(console)


class _FakeProcess:
    """A process that is alive until told otherwise.

    ``ignores`` names the steps it survives ("terminate"), which is how a
    game that has to be escalated on is written down.
    """

    def __init__(self, ignores=()):
        self.terminated = False
        self.killed = False
        self.exit_code = None
        self._ignores = set(ignores)

    def poll(self):
        return self.exit_code

    def terminate(self):
        self.terminated = True
        if "terminate" not in self._ignores:
            self.exit_code = 0

    def kill(self):
        self.killed = True
        self.exit_code = -9


class _FakeClient:
    """Records every datagram; can be told to start failing."""

    def __init__(self, fail_after=None, port=55355):
        self.port = port
        self.sent = []
        self.fail_after = fail_after

    def send(self, command):
        if self.fail_after is not None and len(self.sent) >= self.fail_after:
            return False
        self.sent.append(command)
        return True

    def close(self):
        pass


class _QuittingClient(_FakeClient):
    """A client whose QUIT the game actually honours."""

    def __init__(self, process, **kwargs):
        super().__init__(**kwargs)
        self.process = process

    def send(self, command):
        sent = super().send(command)
        if sent and command == "QUIT":
            self.process.exit_code = 0
        return sent


class _RecordingSleep:
    def __init__(self):
        self.calls = []

    def __call__(self, seconds):
        self.calls.append(seconds)


def _manager(tmp_dir, sleep=None, **config_kwargs):
    config = _DummyConfig(tmp_dir, **config_kwargs)
    return RuntimeManager(tmp_dir, config, sleep=sleep or _RecordingSleep()), config


class VolumePacerTests(unittest.TestCase):
    """Issue #125: the steps have to be paced or RetroArch drops them.

    RetroArch drains its command socket once per frame. A 20 dB drag is 40
    relative steps; fired back to back they land in a single frame window,
    overrun the receive buffer and are discarded. MUTE is one packet in one
    frame, which is exactly why mute worked and the slider did not.
    """

    def _walk(self, client, start, target, sleep=None):
        sleep = sleep or _RecordingSleep()
        pacer = VolumePacer(client, level=start, sleep=sleep)
        pacer.set_target(target)
        pacer.join(5)
        return pacer, sleep

    def test_a_twenty_db_drag_emits_one_packet_per_step(self):
        client = _FakeClient()
        pacer, sleep = self._walk(client, 0.0, -20.0)
        self.assertEqual(len(client.sent), 40)
        self.assertEqual(set(client.sent), {"VOLUME_DOWN"})
        self.assertEqual(pacer.level, -20.0)

    def test_every_packet_is_spaced_by_the_frame_interval(self):
        client = _FakeClient()
        _pacer, sleep = self._walk(client, 0.0, -5.0)
        self.assertEqual(len(client.sent), 10)
        # One sleep between packets; the last one needs no trailing wait.
        self.assertEqual(len(sleep.calls), 10)
        self.assertEqual(set(sleep.calls), {VOLUME_PACING_INTERVAL})

    def test_walking_up_emits_volume_up(self):
        client = _FakeClient()
        pacer, _sleep = self._walk(client, -10.0, -8.0)
        self.assertEqual(client.sent, ["VOLUME_UP"] * 4)
        self.assertEqual(pacer.level, -8.0)

    def test_dropped_packets_do_not_drift_the_tracker(self):
        # The tracker may only advance by what actually left the socket;
        # assuming otherwise put it permanently out of sync with RetroArch.
        client = _FakeClient(fail_after=6)
        pacer, _sleep = self._walk(client, 0.0, -20.0)
        self.assertEqual(len(client.sent), 6)
        self.assertEqual(pacer.level, -3.0)

    def test_repeated_targets_coalesce_into_one_walk(self):
        # A drag emits a value every 0.5 dB. Each must move the goal, not
        # start its own burst, or the bursts overlap and fight each other.
        client = _FakeClient()
        sleep = _RecordingSleep()
        pacer = VolumePacer(client, level=0.0, sleep=sleep)
        for target in (-1.0, -2.0, -3.0, -10.0):
            pacer.set_target(target)
        pacer.join(5)
        self.assertEqual(pacer.level, -10.0)
        # Never more than the direct walk: no step is sent twice.
        self.assertLessEqual(len(client.sent), 20)
        self.assertEqual(set(client.sent), {"VOLUME_DOWN"})

    def test_no_packets_when_already_at_the_target(self):
        client = _FakeClient()
        pacer, _sleep = self._walk(client, -6.0, -6.0)
        self.assertEqual(client.sent, [])

    def test_reset_reseeds_without_sending(self):
        client = _FakeClient()
        pacer = VolumePacer(client, level=0.0, sleep=_RecordingSleep())
        pacer.reset(-12.0)
        self.assertEqual(pacer.level, -12.0)
        self.assertEqual(client.sent, [])

    def test_targets_are_clamped(self):
        client = _FakeClient()
        pacer, _sleep = self._walk(client, 0.0, -999.0)
        self.assertEqual(pacer.level, -40.0)


class MasterVolumeTests(unittest.TestCase):
    def _running_manager(self, tmp_dir, client, **kwargs):
        manager, config = _manager(tmp_dir, **kwargs)
        manager.active_process = _FakeProcess()
        manager.active_rom = {"path": "/roms/x.sfc", "console": "SFC"}
        manager._command_client_cache = client
        manager._pacer = VolumePacer(
            client, level=manager.volume_db, sleep=_RecordingSleep()
        )
        return manager, config

    def test_a_drag_reaches_the_target_through_the_pacer(self):
        with TemporaryDirectory() as tmp_dir:
            client = _FakeClient()
            manager, _config = self._running_manager(tmp_dir, client)
            manager.set_master_volume_db(-12.0)
            manager._pacer.join(5)
            self.assertEqual(len(client.sent), 24)
            self.assertEqual(manager.volume_db, -12.0)

    def test_the_tracker_reflects_what_landed_not_what_was_asked(self):
        with TemporaryDirectory() as tmp_dir:
            client = _FakeClient(fail_after=4)
            manager, _config = self._running_manager(tmp_dir, client)
            manager.set_master_volume_db(-20.0)
            manager._pacer.join(5)
            self.assertEqual(manager.volume_db, -2.0)

    def test_with_no_game_running_nothing_is_sent(self):
        with TemporaryDirectory() as tmp_dir:
            manager, config = _manager(tmp_dir)
            client = _FakeClient()
            manager._command_client_cache = client
            self.assertEqual(manager.set_master_volume_db(-8.0), -8.0)
            self.assertEqual(client.sent, [])
            # It still persists: the slider doubles as "the level the next
            # launch starts at".
            manager.flush_volume_db()
            self.assertEqual(config.master_volume_db, -8.0)

    def test_the_level_is_persisted_once_the_slider_settles(self):
        with TemporaryDirectory() as tmp_dir:
            manager, config = _manager(tmp_dir)
            for level in (-1.0, -2.0, -3.0, -4.0):
                manager.set_master_volume_db(level)
            # Debounced: a drag is dozens of values and each write is a
            # synchronous YAML dump.
            self.assertEqual(config.volume_writes, [])
            manager.flush_volume_db()
            self.assertEqual(config.volume_writes, [-4.0])

    def test_flushing_twice_writes_once(self):
        with TemporaryDirectory() as tmp_dir:
            manager, config = _manager(tmp_dir)
            manager.set_master_volume_db(-5.0)
            self.assertTrue(manager.flush_volume_db())
            self.assertFalse(manager.flush_volume_db())
            self.assertEqual(config.volume_writes, [-5.0])

    def test_setting_volume_db_reseeds_the_pacer(self):
        with TemporaryDirectory() as tmp_dir:
            client = _FakeClient()
            manager, _config = self._running_manager(tmp_dir, client)
            manager.volume_db = -15.0
            self.assertEqual(manager.volume_db, -15.0)
            self.assertEqual(client.sent, [])


class CommandDispatchTests(unittest.TestCase):
    def test_commands_are_refused_with_no_game_running(self):
        with TemporaryDirectory() as tmp_dir:
            manager, _config = _manager(tmp_dir)
            client = _FakeClient()
            manager._command_client_cache = client
            self.assertFalse(manager.send_command("RESET"))
            self.assertEqual(client.sent, [])

    def test_commands_reach_a_running_game(self):
        with TemporaryDirectory() as tmp_dir:
            manager, _config = _manager(tmp_dir)
            client = _FakeClient()
            manager._command_client_cache = client
            manager.active_process = _FakeProcess()
            self.assertTrue(manager.send_command("LOAD_STATE"))
            self.assertEqual(client.sent, ["LOAD_STATE"])

    def test_relaunch_stops_the_game_and_hands_back_the_rom(self):
        # Issue #129: bindings reach RetroArch only through the
        # --appendconfig file written at spawn, so only a fresh process
        # picks up a remap. RESET (#130) keeps the process and cannot.
        with TemporaryDirectory() as tmp_dir:
            manager, _config = _manager(tmp_dir)
            process = _FakeProcess()
            client = _QuittingClient(process)
            manager._command_client_cache = client
            manager.active_process = process
            manager.active_rom = {"path": "/roms/x.sfc", "console": "SFC"}

            rom, error = manager.relaunch_active()
            self.assertIsNone(error)
            # The clean shutdown first: it flushes battery saves, and a game
            # that honours it never reaches the signals.
            self.assertEqual(client.sent, ["QUIT"])
            self.assertIsNotNone(process.poll())
            self.assertFalse(process.terminated)
            # Captured before the teardown: _clear_active wipes active_rom.
            self.assertEqual(rom, {"path": "/roms/x.sfc", "console": "SFC"})

    def test_relaunch_is_a_no_op_with_no_game_running(self):
        with TemporaryDirectory() as tmp_dir:
            manager, _config = _manager(tmp_dir)
            rom, error = manager.relaunch_active()
            self.assertIsNone(rom)
            self.assertTrue(error)

    def test_relaunch_rom_launches_the_same_rom_again(self):
        with TemporaryDirectory() as tmp_dir:
            manager, _config = _manager(tmp_dir)
            launched = {}

            def _fake_launch(rom_path, console, state_slot=None, network_cmd_port=None):
                launched["args"] = (rom_path, console)
                launched["port"] = network_cmd_port
                return _FakeProcess(), None

            manager.retroarch_launcher.launch_process = _fake_launch
            success, error = manager.relaunch_rom(
                {"path": "/roms/x.sfc", "console": "SFC"}
            )
            self.assertTrue(success, error)
            self.assertEqual(launched["args"], ("/roms/x.sfc", "SFC"))
            # The launch owns the port; RetroArch and the client must agree.
            self.assertTrue(launched["port"] > 0)

    def test_relaunch_rom_refuses_without_a_rom(self):
        with TemporaryDirectory() as tmp_dir:
            manager, _config = _manager(tmp_dir)
            success, error = manager.relaunch_rom(None)
            self.assertFalse(success)
            self.assertTrue(error)

    def test_load_state_slot_targets_the_given_slot(self):
        with TemporaryDirectory() as tmp_dir:
            manager, _config = _manager(tmp_dir)
            client = _FakeClient()
            manager._command_client_cache = client
            manager.active_process = _FakeProcess()
            self.assertTrue(manager.load_state_slot(HOT_APPLY_STATE_SLOT))
            self.assertEqual(client.sent, ["LOAD_STATE_SLOT 100"])

    def test_the_client_is_reused_across_commands(self):
        with TemporaryDirectory() as tmp_dir:
            manager, _config = _manager(tmp_dir)
            self.assertIs(manager._command_client(), manager._command_client())

    def test_a_port_change_replaces_the_client_and_the_pacer(self):
        with TemporaryDirectory() as tmp_dir:
            manager, config = _manager(tmp_dir)
            first = manager._command_client()
            manager._pacer = VolumePacer(first, sleep=_RecordingSleep())
            config.port = 55400
            second = manager._command_client()
            self.assertIsNot(first, second)
            self.assertIsNone(manager._pacer)


class StopActiveTests(unittest.TestCase):
    """A stop has to end the game, whatever the emulator does about it.

    The reported failure: closing the game window sent QUIT (which RetroArch
    ignored, having answered the first quit with "press again") and then a
    SIGTERM that never crossed the Flatpak sandbox boundary. The window went
    away, the game played on, and only a process manager could end it. Every
    step below therefore has to escalate to the next one.
    """

    def _running(self, tmp_dir, process, client=None):
        manager, _config = _manager(tmp_dir)
        manager.active_process = process
        manager.active_rom = {"path": "/roms/x.sfc", "console": "SFC"}
        manager._command_client_cache = client or _FakeClient()
        return manager

    def test_a_game_that_honours_quit_is_never_signalled(self):
        with TemporaryDirectory() as tmp_dir:
            process = _FakeProcess()
            client = _QuittingClient(process)
            manager = self._running(tmp_dir, process, client)

            success, error = manager.stop_active(block=True)

            self.assertTrue(success, error)
            self.assertEqual(client.sent, ["QUIT"])
            self.assertFalse(process.terminated)
            self.assertFalse(process.killed)

    def test_a_game_that_ignores_quit_is_terminated(self):
        with TemporaryDirectory() as tmp_dir:
            process = _FakeProcess()
            client = _FakeClient()
            manager = self._running(tmp_dir, process, client)

            manager.stop_active(block=True)

            self.assertEqual(client.sent, ["QUIT"])
            self.assertTrue(process.terminated)
            self.assertFalse(process.killed)
            self.assertIsNotNone(process.poll())

    def test_a_game_that_ignores_the_signal_too_is_killed(self):
        with TemporaryDirectory() as tmp_dir:
            process = _FakeProcess(ignores=("terminate",))
            manager = self._running(tmp_dir, process)

            manager.stop_active(block=True)

            self.assertTrue(process.terminated)
            self.assertTrue(process.killed)
            self.assertIsNotNone(process.poll())

    def test_a_stop_runs_on_its_own_thread_unless_asked_to_block(self):
        # The window that asks for the stop must not freeze while an
        # unresponsive game is escalated on.
        with TemporaryDirectory() as tmp_dir:
            process = _FakeProcess(ignores=("terminate",))
            manager = self._running(tmp_dir, process)
            started = threading.Event()
            original = manager._escalate_stop

            def _watched(proc):
                started.set()
                return original(proc)

            manager._escalate_stop = _watched
            success, error = manager.stop_active()

            self.assertTrue(success, error)
            self.assertTrue(started.wait(5))
            for _ in range(100):
                if process.killed:
                    break
                time.sleep(0.01)
            self.assertTrue(process.killed)

    def test_stopping_with_no_game_running_reports_it(self):
        with TemporaryDirectory() as tmp_dir:
            manager, _config = _manager(tmp_dir)
            success, error = manager.stop_active()
            self.assertFalse(success)
            self.assertTrue(error)

    def test_a_process_that_already_exited_is_cleared(self):
        with TemporaryDirectory() as tmp_dir:
            process = _FakeProcess()
            process.exit_code = 0
            manager = self._running(tmp_dir, process)

            success, _error = manager.stop_active()

            self.assertFalse(success)
            self.assertIsNone(manager.active_process)


class HotApplyTests(unittest.TestCase):
    """Issue #129: a remap reaches a running game via a state-carrying
    relaunch -- snapshot to a scratch slot, confirm the file landed, relaunch,
    load it back. The confirmation is what keeps a core without save-state
    support from turning the apply into a relaunch that loses the game."""

    def _running_manager(self, tmp_dir):
        manager, config = _manager(tmp_dir)
        client = _FakeClient()
        manager._command_client_cache = client
        manager.active_process = _FakeProcess()
        manager.active_rom = {"path": "/roms/Super Game.sfc", "console": "SFC"}
        return manager, config, client

    def _write_scratch(self, config, mtime=None):
        states_dir = config.get_console_states_dir("SFC")
        states_dir.mkdir(parents=True, exist_ok=True)
        state = states_dir / f"Super Game.state{HOT_APPLY_STATE_SLOT}"
        state.write_bytes(b"fake state")
        if mtime is not None:
            import os

            os.utime(state, (mtime, mtime))
        return state

    def test_snapshot_sends_the_scratch_slot_save(self):
        with TemporaryDirectory() as tmp_dir:
            manager, _config, client = self._running_manager(tmp_dir)
            marker = manager.snapshot_active()
            self.assertIsNotNone(marker)
            self.assertEqual(client.sent, ["SAVE_STATE_SLOT 100"])
            self.assertEqual(marker["slot"], HOT_APPLY_STATE_SLOT)
            self.assertEqual(marker["rom"]["console"], "SFC")

    def test_snapshot_refuses_with_no_game_running(self):
        with TemporaryDirectory() as tmp_dir:
            manager, _config = _manager(tmp_dir)
            client = _FakeClient()
            manager._command_client_cache = client
            self.assertIsNone(manager.snapshot_active())
            self.assertEqual(client.sent, [])

    def test_ready_only_once_the_state_file_lands(self):
        with TemporaryDirectory() as tmp_dir:
            manager, config, _client = self._running_manager(tmp_dir)
            marker = manager.snapshot_active()
            # UDP went out but RetroArch has written nothing yet.
            self.assertFalse(manager.snapshot_ready(marker))
            self._write_scratch(config)
            self.assertTrue(manager.snapshot_ready(marker))

    def test_a_leftover_scratch_state_does_not_read_as_saved(self):
        # A previous apply's file sitting on disk must not confirm this one:
        # relaunching on it would resume yesterday's game, losing today's.
        with TemporaryDirectory() as tmp_dir:
            manager, config, _client = self._running_manager(tmp_dir)
            stale = self._write_scratch(config, mtime=1000.0)
            marker = manager.snapshot_active()
            self.assertFalse(manager.snapshot_ready(marker))
            # RetroArch rewrites the slot: newer mtime, now it counts.
            import os

            os.utime(stale, (2000.0, 2000.0))
            self.assertTrue(manager.snapshot_ready(marker))

    def test_discard_removes_the_scratch_state(self):
        with TemporaryDirectory() as tmp_dir:
            manager, config, _client = self._running_manager(tmp_dir)
            marker = manager.snapshot_active()
            state = self._write_scratch(config)
            self.assertTrue(manager.discard_snapshot(marker))
            self.assertFalse(state.exists())
            self.assertFalse(manager.discard_snapshot(marker))

    def test_snapshot_reports_failure_when_the_packet_does_not_leave(self):
        with TemporaryDirectory() as tmp_dir:
            manager, _config, client = self._running_manager(tmp_dir)
            client.fail_after = 0
            self.assertIsNone(manager.snapshot_active())


class MuteAndSettlingTests(unittest.TestCase):
    """The write-only half of the audio controls (issue #284)."""

    def test_a_mute_that_never_left_does_not_flip_the_state(self):
        with TemporaryDirectory() as tmp_dir:
            manager, _config = _manager(tmp_dir)
            manager.active_process = _FakeProcess()

            dead = _FakeClient(fail_after=0)
            manager._command_client_cache = dead
            attempts = []
            dead.send = lambda command: (attempts.append(command), False)[1]

            self.assertFalse(manager.toggle_mute())
            # Tried twice before believing it: a send only reports failure
            # when the datagram never left, so a retry cannot toggle twice.
            self.assertEqual(attempts, ["MUTE", "MUTE"])

    def test_a_mute_that_landed_flips_the_state(self):
        with TemporaryDirectory() as tmp_dir:
            manager, _config = _manager(tmp_dir)
            manager.active_process = _FakeProcess()
            manager._command_client_cache = _FakeClient()
            self.assertTrue(manager.toggle_mute())
            self.assertFalse(manager.toggle_mute())

    def test_settling_is_false_without_a_pacer(self):
        with TemporaryDirectory() as tmp_dir:
            manager, _config = _manager(tmp_dir)
            self.assertFalse(manager.volume_settling)


class CommandPortTests(unittest.TestCase):
    """Each launch owns its command port (issue #227)."""

    def test_a_pinned_port_is_honoured(self):
        with TemporaryDirectory() as tmp_dir:
            manager, config = _manager(tmp_dir)
            config.port = 54321
            self.assertEqual(manager._resolve_network_cmd_port(), 54321)

    def test_zero_means_pick_a_free_one(self):
        with TemporaryDirectory() as tmp_dir:
            manager, config = _manager(tmp_dir)
            config.port = 0
            port = manager._resolve_network_cmd_port()
            self.assertGreater(port, 0)
            self.assertNotEqual(port, 0)

    def test_the_client_talks_to_the_port_the_launch_chose(self):
        # Not to whatever the config says now: the running RetroArch was told
        # one number, and the client has to keep using it.
        with TemporaryDirectory() as tmp_dir:
            manager, config = _manager(tmp_dir)
            config.port = 0
            manager._network_cmd_port = 51234
            self.assertEqual(manager._command_client().port, 51234)


class _Clock:
    """A monotonic clock the test moves by hand."""

    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class StartupFailureTests(unittest.TestCase):
    """A game that never came up must not read as a game the user quit (#226)."""

    def _running(self, tmp_dir, clock, log_path=None):
        config = _DummyConfig(tmp_dir)
        manager = RuntimeManager(tmp_dir, config, sleep=_RecordingSleep(), clock=clock)
        proc = _FakeProcess()
        if log_path is not None:
            proc._openemux_log_path = str(log_path)
        manager.active_process = proc
        manager.active_rom = {"path": "/roms/PS/game.chd", "console": "PS"}
        manager._launched_at = clock()
        return manager, proc

    def test_a_game_still_running_reports_nothing(self):
        with TemporaryDirectory() as tmp_dir:
            clock = _Clock()
            manager, _ = self._running(tmp_dir, clock)
            self.assertIsNone(manager.poll_active())

    def test_an_instant_nonzero_exit_carries_the_reason_from_the_log(self):
        with TemporaryDirectory() as tmp_dir:
            log_path = Path(tmp_dir) / "launch.log"
            log_path.write_text(
                "[INFO] starting\ndlopen(): error loading libfuse.so.2\n", encoding="utf-8"
            )
            clock = _Clock()
            manager, proc = self._running(tmp_dir, clock, log_path=log_path)

            clock.advance(0.4)
            proc.exit_code = 1
            result = manager.poll_active()

        self.assertEqual(result["exit_code"], 1)
        self.assertIn("libfuse2", result["failure_reason"])

    def test_a_long_session_that_ends_badly_is_not_a_startup_failure(self):
        # A game the user played for an hour and that crashed on the way out
        # is not a launch that failed; the finished toast is the right one.
        with TemporaryDirectory() as tmp_dir:
            log_path = Path(tmp_dir) / "launch.log"
            log_path.write_text("[ERROR] something late\n", encoding="utf-8")
            clock = _Clock()
            manager, proc = self._running(tmp_dir, clock, log_path=log_path)

            clock.advance(3600.0)
            proc.exit_code = 1
            result = manager.poll_active()

        self.assertIsNone(result.get("failure_reason"))

    def test_a_clean_instant_exit_is_not_a_failure(self):
        with TemporaryDirectory() as tmp_dir:
            clock = _Clock()
            manager, proc = self._running(tmp_dir, clock)
            clock.advance(0.2)
            proc.exit_code = 0
            result = manager.poll_active()

        self.assertIsNone(result.get("failure_reason"))

    def test_a_startup_failure_with_an_unreadable_log_still_reports_the_exit(self):
        with TemporaryDirectory() as tmp_dir:
            clock = _Clock()
            manager, proc = self._running(tmp_dir, clock, log_path=Path(tmp_dir) / "gone.log")
            clock.advance(0.1)
            proc.exit_code = 127
            result = manager.poll_active()

        self.assertEqual(result["exit_code"], 127)
        self.assertIsNone(result["failure_reason"])

    def test_the_threshold_is_what_separates_the_two(self):
        self.assertTrue(RuntimeManager._died_on_startup(1, 0.5))
        self.assertFalse(RuntimeManager._died_on_startup(0, 0.5))
        self.assertFalse(RuntimeManager._died_on_startup(1, STARTUP_FAILURE_SECONDS + 0.1))


if __name__ == "__main__":
    unittest.main()
