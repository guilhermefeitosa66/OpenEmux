import logging
import threading
import time

from openemux.core import retroarch_log, save_states, window_title
from openemux.core.retroarch_command import (
    RetroArchCommandClient,
    StdinCommandClient,
    pick_free_udp_port,
    uses_stdin_channel,
)
from openemux.core.retroarch_launcher import RetroArchLauncher
from openemux.core.systems import resolve_system_id

#: The scratch slot that carries gameplay across an input-change relaunch
#: (issue #129). Far outside the 0-9 range the states UI manages, so the
#: snapshot never clobbers a state the user saved on purpose.
HOT_APPLY_STATE_SLOT = 100

#: The escalation a stop walks, and how long each step gets before the next
#: one. QUIT is the clean shutdown -- RetroArch flushes battery saves and
#: exits on its own -- so it is worth waiting for; SIGTERM is the polite
#: signal; SIGKILL is what a hung emulator gets. A game must never survive
#: the window that launched it, whichever step it takes.
QUIT_GRACE_SECONDS = 2.0
TERM_GRACE_SECONDS = 2.0
STOP_POLL_INTERVAL = 0.05

#: Under this many seconds, a nonzero exit is a launch that never got off the
#: ground rather than a game the user quit (issue #226).
STARTUP_FAILURE_SECONDS = 3.0

logger = logging.getLogger(__name__)


class RuntimeManager:
    """
    Runtime strategy entrypoint.
    - retroarch_wrapper: launches RetroArch with libretro core + ROM.
    - integrated_core: reserved for future embedded core runtime.
    """

    def __init__(self, project_root, config_manager, sleep=time.sleep, clock=time.monotonic):
        self.config_manager = config_manager
        # Injectable so the stop escalation is assertable without real time.
        self._sleep = sleep
        self._clock = clock
        # When the running game started, so a poll can tell "the user quit"
        # from "it never came up" (issue #226).
        self._launched_at = None
        self.retroarch_launcher = RetroArchLauncher(project_root, config_manager)
        self.active_process = None
        self.active_rom = None
        # Something the last successful launch has to tell the user -- today
        # only "this console's shader has no preset your video driver can
        # load" (issue #366). A (key, kwargs) pair for tr(), or None.
        self.launch_notice = None
        self._command_client_cache = None
        # The port this launch's channel runs on, on Windows -- elsewhere the
        # channel is the game's stdin and there is no port (None). Resolved at
        # launch so the config's "0" (pick a free one) and the override
        # RetroArch reads can never disagree.
        self._network_cmd_port = None
        # The last launch as it would have to be repeated, and whether the
        # unpacked retry has already been spent on it (issue #248).
        self._launch_request = None
        self._fuse_retry_done = False

    def launch(self, rom_path, console, state_slot=None, force_extract=False):
        """Start a game. ``force_extract`` is the FUSE retry, not a user option.

        See :meth:`_retry_unpacked`: when the AppImage runtime cannot mount
        itself the same launch is repeated unpacked, and that repeat comes
        back through here (issue #248).
        """
        system_id = resolve_system_id(console)
        if self.is_running():
            # A translation key, not a sentence. Core has no locale and no
            # business having one; the UI runs whatever comes back through
            # tr(), which is the identity for anything that is not a key --
            # so the launcher's own free-text failures still pass through
            # unchanged (issue #232).
            return False, "toast.launch.already_running"

        mode = self.config_manager.get_runtime_mode_for_console(system_id)

        if mode == "retroarch_wrapper":
            # A port only where the channel is UDP; a stdin launch has none.
            port = None if uses_stdin_channel() else self._resolve_network_cmd_port()
            proc, error_msg = self.retroarch_launcher.launch_process(
                rom_path, system_id, state_slot=state_slot, network_cmd_port=port,
                force_extract=force_extract,
            )
            if not proc:
                return False, error_msg
            # A launch that started but has something to say. Not an error --
            # the game is up -- so it cannot travel in the error slot; the UI
            # reads it after a successful launch (issue #366).
            self.launch_notice = getattr(
                self.retroarch_launcher, "last_shader_notice", None
            )
            self.active_process = proc
            self.active_rom = {"path": rom_path, "console": system_id}
            # RetroArch's own window is what the user sees: name the game in
            # its title instead of the core's version hash (issue #469).
            window_title.start(
                proc, rom_path, getattr(self.retroarch_launcher, "last_core_path", None)
            )
            # What a retry has to repeat, and whether one is still owed. A
            # fresh launch re-arms it; the retry itself does not, so a game
            # that cannot start gets exactly one second attempt.
            self._launch_request = {
                "path": rom_path,
                "console": system_id,
                "state_slot": state_slot,
            }
            self._fuse_retry_done = force_extract
            self._launched_at = self._clock()
            self._network_cmd_port = port
            return True, None

        if mode == "integrated_core":
            return False, (
                "Integrated core runtime is not implemented yet. "
                "Use runtime.mode=retroarch_wrapper in config.yaml."
            )

        return False, f"Unsupported runtime mode: {mode}"

    def is_running(self):
        """Is a game up right now?

        The attribute is read **once**. It used to be read twice, and the
        gamepad reader thread calls this several times a second while the main
        thread's one-second poll clears it at game exit: a clear landing
        between the two reads raised ``AttributeError: 'NoneType' object has
        no attribute 'poll'`` on the reader thread, which ended it -- gamepad
        navigation silently stopped working for the rest of the session, every
        time the race hit (issue #223). Same shape in ``poll_active`` and
        ``stop_active`` below, for the same reason.
        """
        proc = self.active_process
        return bool(proc and proc.poll() is None)

    def stop_active(self, block=False):
        """Quit the running game, escalating until the process is really gone.

        Three steps, each given a grace period: the network QUIT (RetroArch
        shuts itself down and flushes battery saves), SIGTERM, then SIGKILL.
        Anything less left games running behind a closed window -- a QUIT that
        RetroArch answers only on the second press, or a SIGTERM that stops at
        a sandbox boundary, is a stop button that does nothing, and the user
        is left hearing a game they cannot see.

        ``block=True`` runs the escalation on the calling thread, which is
        what the app's own shutdown needs: a daemon thread dies with the
        process and would leave the game behind on the way out. Everywhere
        else it walks on its own thread so a closing window is not held up.
        """
        proc = self.active_process
        if not proc:
            return False, "No active game process."

        if proc.poll() is not None:
            self._clear_active()
            return False, "No active game process."

        # Sent from here rather than the worker: it is a single command, and
        # a game that honours it is gone before the first grace period is up.
        self.send_command("QUIT")
        if block:
            self._escalate_stop(proc)
        else:
            threading.Thread(
                target=self._escalate_stop,
                args=(proc,),
                name="openemux-stop-game",
                daemon=True,
            ).start()
        return True, None

    def _escalate_stop(self, proc):
        """SIGTERM then SIGKILL, each only if the game is still there."""
        if self._wait_for_exit(proc, QUIT_GRACE_SECONDS):
            return True
        logger.info("game ignored QUIT; terminating the process")
        self.retroarch_launcher.terminate_process(proc)
        if self._wait_for_exit(proc, TERM_GRACE_SECONDS):
            return True
        logger.warning("game ignored SIGTERM; killing the process")
        self.retroarch_launcher.kill_process(proc)
        return self._wait_for_exit(proc, TERM_GRACE_SECONDS)

    def _wait_for_exit(self, proc, timeout):
        """Poll until the process is gone or ``timeout`` seconds have passed.

        Polling rather than ``proc.wait()`` so the manager keeps working with
        anything that answers ``poll()``, and so the wait is injectable.
        """
        waited = 0.0
        while waited < timeout:
            if proc.poll() is not None:
                return True
            self._sleep(STOP_POLL_INTERVAL)
            waited += STOP_POLL_INTERVAL
        return proc.poll() is not None

    # -- live control (issue #69) ------------------------------------------
    def _resolve_network_cmd_port(self):
        """The port this launch will use: the pinned one, or a free one.

        RetroArch binds its command socket with the reuse flags set, so a
        standalone RetroArch on the default 55355 binds it too and the kernel
        picks which of the two hears each datagram. A port of our own is the
        only way our commands are guaranteed to reach our own game (#227).
        """
        configured = int(self.config_manager.get_network_cmd_port())
        if configured > 0:
            return configured
        return pick_free_udp_port()

    def _command_client(self):
        """The running game's command client, reused while the game runs.

        The process decides the channel: a game launched with a stdin pipe --
        every launch outside Windows -- is spoken to through that pipe, and
        only one without falls back to a UDP port. A cached client for some
        other game's pipe, or another port, is replaced.
        """
        client = self._command_client_cache
        stream = getattr(self.active_process, "stdin", None)
        if stream is not None:
            if client is not None and getattr(client, "stream", None) is stream:
                return client
            replacement = StdinCommandClient(stream)
        else:
            port = self._network_cmd_port
            if port is None:
                port = self._resolve_network_cmd_port()
            if client is not None and getattr(client, "port", None) == port:
                return client
            replacement = RetroArchCommandClient(port)
        if client is not None:
            client.close()
        self._command_client_cache = replacement
        return replacement

    def send_command(self, command):
        """One command to the running game; False when none runs."""
        if not self.is_running():
            return False
        return self._command_client().send(command)

    # -- live input apply (issue #129) -------------------------------------
    # The command interface has no config-write or remap-reload verb (checked
    # against the vendored RetroArch 1.22: SAVE/LOAD_STATE_SLOT exist,
    # SET_CONFIG_PARAM does not), so "apply while running" is a relaunch that
    # carries the gameplay across: snapshot to a scratch slot, restart with
    # the regenerated override, load the snapshot back.

    def snapshot_active(self, slot=HOT_APPLY_STATE_SLOT):
        """Ask the running game to save a scratch state; a marker or ``None``.

        The command is fire-and-forget, so the caller must poll
        ``snapshot_ready(marker)`` to learn whether RetroArch actually wrote
        the file -- a core without save-state support never will, and that
        must not turn into a relaunch that silently loses the game.
        """
        if not self.is_running():
            return None
        rom = dict(self.active_rom or {})
        states_dir = self.config_manager.get_console_states_dir(rom.get("console"))
        existing = self._scratch_state(states_dir, rom.get("path"), slot)
        if not self.send_command(f"SAVE_STATE_SLOT {int(slot)}"):
            return None
        return {
            "rom": rom,
            "states_dir": states_dir,
            "slot": int(slot),
            # A leftover scratch file from an earlier apply must not read as
            # "saved": ready means newer than whatever was there beforehand.
            "baseline_mtime": existing.mtime if existing else None,
        }

    @staticmethod
    def _scratch_state(states_dir, rom_path, slot):
        for state in save_states.list_states(states_dir, rom_path):
            if state.slot == int(slot):
                return state
        return None

    def snapshot_ready(self, marker):
        """True once the scratch state from ``snapshot_active`` is on disk."""
        if not marker:
            return False
        state = self._scratch_state(
            marker["states_dir"], marker["rom"].get("path"), marker["slot"]
        )
        if state is None:
            return False
        baseline = marker.get("baseline_mtime")
        return baseline is None or state.mtime > baseline

    def discard_snapshot(self, marker):
        """Delete the scratch state once it has been loaded back."""
        if not marker:
            return False
        state = self._scratch_state(
            marker["states_dir"], marker["rom"].get("path"), marker["slot"]
        )
        if state is None:
            return False
        return save_states.delete_state(state)

    def load_state_slot(self, slot):
        """Load a specific slot's state into the running game.

        Unlike seeding ``state_slot`` at launch, this leaves the save/load
        hotkeys on the configured slot -- a quick-save right after an apply
        must not land on the scratch slot.
        """
        return self.send_command(f"LOAD_STATE_SLOT {int(slot)}")

    def relaunch_rom(self, rom):
        """Launch ``rom`` again -- the second half of a relaunch.

        Split out because ``launch()`` refuses while a process is alive, so
        the caller has to wait for the exit before this can run and the UI
        must not block the main loop doing it (issue #129).
        """
        if not rom:
            return False, "No game to relaunch."
        return self.launch(rom.get("path"), rom.get("console"))

    def relaunch_active(self):
        """Stop the running game and start the same ROM again.

        Deliberately distinct from the ``reset_game`` hotkey, which is a soft
        reset that keeps the same process: bindings reach RetroArch only
        through the --appendconfig file written at spawn, the
        process never re-reads it, and the command interface has no
        config-write or remap-reload verb. Terminating and launching again regenerates
        that override, which is the only thing that applies a remap (#129).

        Returns ``(rom, error)``: the ROM to relaunch once the process is
        gone, so the caller can poll for the exit rather than blocking.
        """
        if not self.is_running():
            return None, "No active game process."
        # Captured first: _clear_active wipes it as soon as the process goes.
        rom = dict(self.active_rom or {})
        success, error = self.stop_active()
        if not success:
            return None, error
        return rom, None

    # -- save states (issue #73) -------------------------------------------
    def load_state(self):
        """Load the active slot's state -- used right after a launch seeded
        with state_slot ("load this save" from the context menu). In-game
        save/load lives on RetroArch's own hotkeys, not in this UI."""
        return self.send_command("LOAD_STATE")

    def poll_active(self):
        """Has the game ended? ``None`` while it runs, a result once it has.

        A game that exits within a couple of seconds with a nonzero code never
        got as far as running -- a missing library, a core that would not load.
        The only account of it is the launch log, and the app used to answer
        "finished (exit code 1)", which is what a clean quit looks like too
        (issue #226). When it looks like that, the reason comes back with the
        result so the caller can show it instead.
        """
        proc = self.active_process
        if not proc:
            return None

        exit_code = proc.poll()
        if exit_code is None:
            return None

        rom = self.active_rom
        log_path = getattr(proc, "_openemux_log_path", None)
        ran_for = self._clock() - (self._launched_at or self._clock())
        self._clear_active()

        result = {
            "exit_code": exit_code,
            "rom": rom,
            "ran_for": ran_for,
            "log_path": log_path,
        }
        if self._died_on_startup(exit_code, ran_for):
            # An AppImage that could not mount itself never reached
            # RetroArch, so this is not a game that failed -- it is a launch
            # that has not happened yet. Unpacking needs no FUSE at all, so
            # try that once before telling the user anything (issue #248).
            if self._retry_unpacked(log_path):
                return None
            reason = retroarch_log.read_failure_reason(log_path)
            result["failure_reason"] = reason
            logger.warning(
                "game died on startup: exit_code=%s ran_for=%.2fs reason=%s log=%s",
                exit_code,
                ran_for,
                reason,
                log_path,
            )
        return result

    def _retry_unpacked(self, log_path):
        """Relaunch the game that just died, unpacked instead of FUSE-mounted.

        True when a retry actually started, and then the caller must report
        nothing: from the user's side the game is simply still coming up.
        False for everything else -- a non-AppImage RetroArch, a death the
        log does not blame on FUSE, or a retry already spent (issue #248).
        """
        if self._fuse_retry_done:
            return False
        request = self._launch_request
        if not request:
            return False
        if not self.retroarch_launcher.launches_an_appimage():
            return False
        if not retroarch_log.read_is_fuse_failure(log_path):
            return False
        logger.warning(
            "the RetroArch AppImage could not mount itself; retrying unpacked: log=%s",
            log_path,
        )
        started, error = self.launch(
            request["path"],
            request["console"],
            state_slot=request.get("state_slot"),
            force_extract=True,
        )
        if not started:
            logger.warning("unpacked retry did not start: %s", error)
        return bool(started)

    @staticmethod
    def _died_on_startup(exit_code, ran_for):
        """A nonzero exit this soon is a launch that never started."""
        return bool(exit_code) and ran_for < STARTUP_FAILURE_SECONDS

    def _clear_active(self):
        proc = self.active_process
        if proc is not None and hasattr(proc, "_openemux_log_handle"):
            try:
                proc._openemux_log_handle.close()
            except Exception:
                pass
        # The command channel talked to the game that just ended, and the next
        # launch brings a pipe or a port of its own (issue #227), so the cached
        # client is already destined for replacement. Closing it here means
        # neither our end of the pipe nor the UDP socket outlives the game it
        # was for -- the socket is what made the suite report an unclosed
        # socket after its summary, from the QUIT that stop_active sends
        # (issue #244).
        client = self._command_client_cache
        if client is not None:
            try:
                client.close()
            except Exception:
                pass
            self._command_client_cache = None
        self.active_process = None
        self.active_rom = None
