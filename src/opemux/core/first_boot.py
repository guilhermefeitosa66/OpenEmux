import logging
from dataclasses import dataclass

from opemux.core.paths import is_running_in_flatpak
from opemux.core.playlist_manager import PlaylistManager
from opemux.core.retroarch_buildbot_updater import RetroArchBuildbotUpdater
from opemux.core.scanner import RomScanner
from opemux.core.systems import SYSTEM_IDS

logger = logging.getLogger(__name__)


@dataclass
class BootstrapStep:
    step_id: str
    label_key: str
    handler: callable


class FirstBootBootstrapper:
    def __init__(self, config_manager):
        self.config_manager = config_manager
        self.scanner = RomScanner(self.config_manager.get_roms_path())
        self.playlist_manager = PlaylistManager(self.config_manager, self.scanner)
        self.updater = RetroArchBuildbotUpdater(self.config_manager)

    def needs_bootstrap(self):
        return self.config_manager.bootstrap_needs_run()

    def run(self, on_event=None):
        steps = [
            BootstrapStep("opemux_config_files", "bootstrap.step.config", self._step_config_files),
            BootstrapStep("opemux_directories", "bootstrap.step.directories", self._step_directories),
            BootstrapStep("input_profiles_seed", "bootstrap.step.input_profiles", self._step_input_profiles),
            BootstrapStep("playlists_seed", "bootstrap.step.playlists", self._step_playlists),
            BootstrapStep("retroarch_environment", "bootstrap.step.retroarch_env", self._step_retroarch_env),
            BootstrapStep("retroarch_download_all_cores", "bootstrap.step.retroarch_cores", self._step_retroarch_cores),
        ]
        total_steps = len(steps)
        state = self.config_manager.get_bootstrap_state()
        completed_steps = set(state.get("completed_steps", []))

        self.config_manager.start_bootstrap_run()
        if on_event:
            on_event({"type": "bootstrap_started", "total_steps": total_steps})

        for index, step in enumerate(steps, start=1):
            if step.step_id in completed_steps:
                if on_event:
                    on_event(
                        {
                            "type": "step_skipped",
                            "step_id": step.step_id,
                            "label_key": step.label_key,
                            "index": index,
                            "total_steps": total_steps,
                        }
                    )
                continue

            if on_event:
                on_event(
                    {
                        "type": "step_started",
                        "step_id": step.step_id,
                        "label_key": step.label_key,
                        "index": index,
                        "total_steps": total_steps,
                    }
                )
            try:
                detail = step.handler(on_event=on_event)
                self.config_manager.mark_bootstrap_step_completed(step.step_id)
                if on_event:
                    on_event(
                        {
                            "type": "step_completed",
                            "step_id": step.step_id,
                            "label_key": step.label_key,
                            "index": index,
                            "total_steps": total_steps,
                            "detail": detail,
                        }
                    )
            except Exception as exc:
                self.config_manager.finish_bootstrap_failure(step.step_id, str(exc))
                logger.exception("first boot step failed: step=%s", step.step_id)
                if on_event:
                    on_event(
                        {
                            "type": "bootstrap_failed",
                            "step_id": step.step_id,
                            "label_key": step.label_key,
                            "error": str(exc),
                            "index": index,
                            "total_steps": total_steps,
                        }
                    )
                return {
                    "success": False,
                    "failed_step": step.step_id,
                    "error": str(exc),
                }

        self.config_manager.finish_bootstrap_success()
        if on_event:
            on_event({"type": "bootstrap_completed", "total_steps": total_steps})
        return {"success": True}

    def _step_config_files(self, on_event=None):
        # Persist merged defaults, including setup metadata.
        self.config_manager.save_config()
        config_path = getattr(self.config_manager, "config_file", None)
        return {"config": str(config_path) if config_path else "managed"}

    def _step_directories(self, on_event=None):
        self.config_manager.ensure_rom_directories()
        return {"roms_path": str(self.config_manager.get_roms_path())}

    def _step_input_profiles(self, on_event=None):
        self.config_manager.ensure_input_profiles()
        return {"total_consoles": len(SYSTEM_IDS)}

    def _step_playlists(self, on_event=None):
        created = 0
        for index, console in enumerate(SYSTEM_IDS, start=1):
            if on_event:
                on_event(
                    {
                        "type": "step_progress",
                        "step_id": "playlists_seed",
                        "current": index,
                        "total": len(SYSTEM_IDS),
                        "message": console,
                    }
                )
            if self.playlist_manager.ensure_playlist(console):
                created += 1
        return {"created": created, "total_consoles": len(SYSTEM_IDS)}

    def _step_retroarch_env(self, on_event=None):
        return self.updater.ensure_environment()

    def _step_retroarch_cores(self, on_event=None):
        if is_running_in_flatpak():
            # Cores are managed by the RetroArch Flatpak's own updater; Opemux
            # must not download binaries into its sandbox.
            return {"skipped": "flatpak", "cores": {}, "shaders": {}, "warning": None}

        def _progress(evt):
            if on_event:
                on_event(evt)

        cores_summary = self.updater.download_all(on_progress=_progress)
        shaders_summary = self.updater.download_shader_packs_if_missing(on_progress=_progress)
        total_failures = int(cores_summary.get("failed", 0)) + int(shaders_summary.get("failed", 0))
        if total_failures > 0 and not self.updater.has_local_runtime_assets():
            raise RuntimeError(
                "RetroArch asset update failed and no local bundled assets were found. "
                "Connect to the internet or provide local cores/shaders."
            )

        warning = None
        if total_failures > 0:
            warning = (
                "RetroArch update had failures, continuing with local bundled assets."
            )
        return {
            "cores": cores_summary,
            "shaders": shaders_summary,
            "warning": warning,
        }
