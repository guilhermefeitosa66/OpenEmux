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

    def launch(self, rom_path, console):
        mode = self.config_manager.get_runtime_mode()

        if mode == "external_wrapper":
            return self.external_launcher.launch(rom_path, console)

        if mode == "integrated_core":
            return False, (
                "Integrated core runtime is not implemented yet. "
                "Use runtime.mode=external_wrapper in config.yaml."
            )

        return False, f"Unsupported runtime mode: {mode}"
