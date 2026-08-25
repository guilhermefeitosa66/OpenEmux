import atexit
import logging
import threading
import time

from openemux.core import save_states
from openemux.core.retroarch_command import (
    RetroArchCommandClient,
    VolumePacer,
    clamp_volume_db,
    pick_free_udp_port,
)
from openemux.core.retroarch_launcher import RetroArchLauncher
from openemux.core.systems import resolve_system_id

#: How long the volume must sit still before it is written to config.yaml.
#: A drag emits a value every 0.5 dB and each write is a synchronous YAML
#: dump, so persisting per tick meant dozens of disk writes per drag.
VOLUME_PERSIST_DEBOUNCE = 0.75

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

logger = logging.getLogger(__name__)


class RuntimeManager:
    """
    Runtime strategy entrypoint.
    - retroarch_wrapper: launches RetroArch with libretro core + ROM.
    - integrated_core: reserved for future embedded core runtime.
    """

    def __init__(self, project_root, config_manager, sleep=time.sleep, dispatch=None):
        self.config_manager = config_manager
        # Injectable so the stop escalation is assertable without real time.
        self._sleep = sleep
        # How a background thread hands work back to the GTK main loop
        # (``GLib.idle_add``). The debounced volume write used to run on the
        # Timer thread and mutate the very config dict the main thread was
        # editing; routed through here it happens where every other config
        # write happens (issue #208). Without one -- tests, headless -- the
        # write stays on the calling thread, which is what it always did.
        self._dispatch = dispatch
        self.retroarch_launcher = RetroArchLauncher(project_root, config_manager)
        self.active_process = None
        self.active_rom = None
        # The live volume tracker (issue #69): RetroArch only steps relative
        # over UDP, so the absolute slider walks from this locally known level.
        # Seeded at launch from the same config value the launcher writes as
        # audio_volume, which is what keeps the tracker honest.
        self._volume_db = clamp_volume_db(self.config_manager.get_master_volume_db())
        self._command_client_cache = None
        # The port this launch's channel runs on. Resolved at launch so the
        # config's "0" (pick a free one) and the override RetroArch reads can
        # never disagree.
        self._network_cmd_port = None
        self._pacer = None
        self._persist_lock = threading.Lock()
        self._persist_timer = None
        self._pending_volume_db = None
        # A debounced write can still be in flight when the app quits; the
        # last level the user chose should not be the one that gets lost.
        atexit.register(self.flush_volume_db)
        self.muted = False

    # The level RetroArch is actually at, as far as delivered packets can
    # say. Stepping is paced over UDP now, so a walk takes a moment to
    # arrive and the tracker has to come from the pacer rather than being
    # optimistically set to the target (issue #125).
    @property
    def volume_settling(self):
        """Is the emulator's real level still walking toward the last target?

        RetroArch has no absolute set-volume command, so a drag becomes a
        walk of 0.5 dB steps paced at one per command-poll -- seconds, for a
        long drag. The UI asks this so it can say the level is still moving
        instead of showing a number the game has not reached (issue #284).
        """
        pacer = self._pacer
        return bool(pacer is not None and pacer.settling)

    @property
    def volume_db(self):
        if self._pacer is not None:
            return self._pacer.level
        return self._volume_db

    @volume_db.setter
    def volume_db(self, value):
        self._volume_db = clamp_volume_db(value)
        if self._pacer is not None:
            self._pacer.reset(self._volume_db)

    def launch(self, rom_path, console, state_slot=None):
        system_id = resolve_system_id(console)
        if self.is_running():
            return False, "A game is already running. Close it before launching another one."

        mode = self.config_manager.get_runtime_mode_for_console(system_id)

        if mode == "retroarch_wrapper":
            port = self._resolve_network_cmd_port()
            proc, error_msg = self.retroarch_launcher.launch_process(
                rom_path, system_id, state_slot=state_slot, network_cmd_port=port
            )
            if not proc:
                return False, error_msg
            self.active_process = proc
            self.active_rom = {"path": rom_path, "console": system_id}
            self._network_cmd_port = port
            self.volume_db = self.config_manager.get_master_volume_db()
            self.muted = False
            return True, None

        if mode == "integrated_core":
            return False, (
                "Integrated core runtime is not implemented yet. "
                "Use runtime.mode=retroarch_wrapper in config.yaml."
            )

        return False, f"Unsupported runtime mode: {mode}"

    def is_running(self):
        return bool(self.active_process and self.active_process.poll() is None)

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
        if not self.active_process:
            return False, "No active game process."

        proc = self.active_process
        if proc.poll() is not None:
            self._clear_active()
            return False, "No active game process."

        # Sent from here rather than the worker: it is a single datagram, and
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
        """The command client, reused so the pacer keeps one socket."""
        port = self._network_cmd_port
        if port is None:
            port = self._resolve_network_cmd_port()
        client = self._command_client_cache
        if client is None or client.port != port:
            if client is not None:
                client.close()
            client = RetroArchCommandClient(port)
            self._command_client_cache = client
            self._pacer = None
        return client

    def _volume_pacer(self):
        # Resolved first: a port change invalidates the pacer along with the
        # client it was holding.
        client = self._command_client()
        if self._pacer is None:
            self._pacer = VolumePacer(client, level=self._volume_db)
        return self._pacer

    def send_command(self, command):
        """One network command to the running game; False when none runs."""
        if not self.is_running():
            return False
        return self._command_client().send(command)

    def set_master_volume_db(self, target_db):
        """Aim the running game's volume at ``target_db`` and persist it.

        Non-blocking: the walk is handed to the pacer, which spreads the
        relative steps one per frame so RetroArch actually receives them.
        Repeated calls during a drag just move the goal.

        The persisted value updates even with no game running, so the slider
        also works as "the level the next launch starts at".
        """
        target = clamp_volume_db(target_db)
        if self.is_running():
            self._volume_pacer().set_target(target)
        else:
            self.volume_db = target
        self._persist_volume_db(target)
        return target

    def _persist_volume_db(self, target):
        """Write the level to config.yaml once the slider settles."""
        with self._persist_lock:
            self._pending_volume_db = target
            if self._persist_timer is not None:
                self._persist_timer.cancel()
            self._persist_timer = threading.Timer(
                VOLUME_PERSIST_DEBOUNCE, self._flush_volume_db_on_main_loop
            )
            self._persist_timer.daemon = True
            self._persist_timer.start()

    def _flush_volume_db_on_main_loop(self):
        """The debounce timer firing, from its own thread.

        Hands the write to the main loop when there is one so the config is
        only ever mutated from a single thread. ``flush_volume_db`` itself
        stays synchronous: atexit calls it after the loop has stopped, and a
        write posted to a dead main loop would simply never happen.
        """
        if self._dispatch is None:
            self.flush_volume_db()
            return

        def _write_once():
            self.flush_volume_db()
            # False is GLib.SOURCE_REMOVE: flush_volume_db returns True when
            # it wrote something, and handing that straight to idle_add would
            # keep the source alive and re-run it forever.
            return False

        self._dispatch(_write_once)

    def flush_volume_db(self):
        """Write any debounced volume level out now."""
        with self._persist_lock:
            pending = self._pending_volume_db
            self._pending_volume_db = None
            if self._persist_timer is not None:
                self._persist_timer.cancel()
                self._persist_timer = None
        if pending is None:
            return False
        self.config_manager.set_master_volume_db(pending)
        return True

    def toggle_mute(self):
        """Toggle RetroArch's mute; returns the new (locally tracked) state.

        Write-only: the vendored RetroArch answers ``GET_CONFIG_PARAM
        audio_mute_enable`` with "unsupported", so nothing can correct this
        tracker afterwards and a single dropped packet would leave the button
        inverted for the rest of the session. One retry -- a send only reports
        failure when the datagram never left, so re-sending cannot toggle
        twice (issue #284).
        """
        if not self.send_command("MUTE") and not self.send_command("MUTE"):
            return self.muted
        self.muted = not self.muted
        return self.muted

    # -- live input apply (issue #129) -------------------------------------
    # The UDP interface has no config-write or remap-reload verb (checked
    # against the vendored RetroArch 1.22: SAVE/LOAD_STATE_SLOT exist,
    # SET_CONFIG_PARAM does not), so "apply while running" is a relaunch that
    # carries the gameplay across: snapshot to a scratch slot, restart with
    # the regenerated override, load the snapshot back.

    def snapshot_active(self, slot=HOT_APPLY_STATE_SLOT):
        """Ask the running game to save a scratch state; a marker or ``None``.

        The command is fire-and-forget UDP, so the caller must poll
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
        """Load a specific slot's state into the running game, over UDP.

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
        process never re-reads it, and the UDP interface has no config-write
        or remap-reload verb. Terminating and launching again regenerates
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
        if not self.active_process:
            return None

        exit_code = self.active_process.poll()
        if exit_code is None:
            return None

        rom = self.active_rom
        self._clear_active()
        return {"exit_code": exit_code, "rom": rom}

    def _clear_active(self):
        if self.active_process and hasattr(self.active_process, "_openemux_log_handle"):
            try:
                self.active_process._openemux_log_handle.close()
            except Exception:
                pass
        self.active_process = None
        self.active_rom = None
