from opemux.core.launcher import Launcher


class RuntimeManager:
    """
    Runtime strategy entrypoint.
    - external_wrapper: launches vendored/system emulators as subprocesses.
    - integrated_core: reserved for future embedded core runtime.
    """

    def __init__(self, project_root, config_manager):
        self.config_manager = config_manager
        self.external_launcher = Launcher(project_root, config_manager)
        self.active_process = None
        self.active_rom = None

    def launch(self, rom_path, console):
        if self.is_running():
            return False, "A game is already running. Close it before launching another one."

        mode = self.config_manager.get_runtime_mode()

        if mode == "external_wrapper":
            proc, error_msg = self.external_launcher.launch_process(rom_path, console)
            if not proc:
                return False, error_msg
            self.active_process = proc
            self.active_rom = {"path": rom_path, "console": console}
            return True, None

        if mode == "integrated_core":
            return False, (
                "Integrated core runtime is not implemented yet. "
                "Use runtime.mode=external_wrapper in config.yaml."
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
        self.active_process = None
        self.active_rom = None
