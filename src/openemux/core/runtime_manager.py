from openemux.core.retroarch_command import RetroArchCommandClient, volume_steps
from openemux.core.retroarch_launcher import RetroArchLauncher
from openemux.core.systems import resolve_system_id


class RuntimeManager:
    """
    Runtime strategy entrypoint.
    - retroarch_wrapper: launches RetroArch with libretro core + ROM.
    - integrated_core: reserved for future embedded core runtime.
    """

    def __init__(self, project_root, config_manager):
        self.config_manager = config_manager
        self.retroarch_launcher = RetroArchLauncher(project_root, config_manager)
        self.active_process = None
        self.active_rom = None
        # The live volume tracker (issue #69): RetroArch only steps relative
        # over UDP, so the absolute slider walks from this locally known level.
        # Seeded at launch from the same config value the launcher writes as
        # audio_volume, which is what keeps the tracker honest.
        self.volume_db = self.config_manager.get_master_volume_db()
        self.muted = False
        # The active save-state slot (issue #73): stepped over UDP, tracked
        # locally because RetroArch only exposes relative slot commands.
        self.state_slot = 0

    def launch(self, rom_path, console, state_slot=None):
        system_id = resolve_system_id(console)
        if self.is_running():
            return False, "A game is already running. Close it before launching another one."

        mode = self.config_manager.get_runtime_mode_for_console(system_id)

        if mode == "retroarch_wrapper":
            proc, error_msg = self.retroarch_launcher.launch_process(
                rom_path, system_id, state_slot=state_slot
            )
            if not proc:
                return False, error_msg
            self.active_process = proc
            self.active_rom = {"path": rom_path, "console": system_id}
            self.volume_db = self.config_manager.get_master_volume_db()
            self.muted = False
            self.state_slot = int(state_slot or 0)
            return True, None

        if mode == "integrated_core":
            return False, (
                "Integrated core runtime is not implemented yet. "
                "Use runtime.mode=retroarch_wrapper in config.yaml."
            )

        return False, f"Unsupported runtime mode: {mode}"

    def is_running(self):
        return bool(self.active_process and self.active_process.poll() is None)

    def stop_active(self):
        if not self.active_process:
            return False, "No active game process."

        if self.active_process.poll() is not None:
            self._clear_active()
            return False, "No active game process."

        try:
            self.active_process.terminate()
            return True, None
        except Exception as exc:
            return False, f"Failed to stop active game: {exc}"

    # -- live control (issue #69) ------------------------------------------
    def _command_client(self):
        return RetroArchCommandClient(self.config_manager.get_network_cmd_port())

    def send_command(self, command):
        """One network command to the running game; False when none runs."""
        if not self.is_running():
            return False
        return self._command_client().send(command)

    def set_master_volume_db(self, target_db):
        """Walk the running game's volume to ``target_db`` and persist it.

        The persisted value updates even with no game running, so the slider
        also works as "the level the next launch starts at".
        """
        from openemux.core.retroarch_command import clamp_volume_db

        target = clamp_volume_db(target_db)
        if self.is_running():
            command, count = volume_steps(self.volume_db, target)
            if command:
                self._command_client().send_repeated(command, count)
        self.volume_db = target
        self.config_manager.set_master_volume_db(target)
        return target

    def toggle_mute(self):
        """Toggle RetroArch's mute; returns the new (locally tracked) state."""
        if self.send_command("MUTE"):
            self.muted = not self.muted
        return self.muted

    # -- save states (issue #73) -------------------------------------------
    MAX_STATE_SLOT = 9

    def save_state(self):
        return self.send_command("SAVE_STATE")

    def load_state(self):
        return self.send_command("LOAD_STATE")

    def step_state_slot(self, delta):
        """Move the active slot by ±1, clamped to 0..MAX_STATE_SLOT.

        Returns the (locally tracked) slot after the move; unchanged when the
        clamp refuses or no game runs.
        """
        target = self.state_slot + int(delta)
        if not 0 <= target <= self.MAX_STATE_SLOT:
            return self.state_slot
        command = "STATE_SLOT_PLUS" if delta > 0 else "STATE_SLOT_MINUS"
        if self.send_command(command):
            self.state_slot = target
        return self.state_slot

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
