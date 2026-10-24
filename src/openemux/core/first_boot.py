import logging
from dataclasses import dataclass

from openemux import __version__
from openemux.core.cores import core_search_dirs
from openemux.core.paths import get_project_root, is_running_in_flatpak
from openemux.core.platform import CORE_SUFFIX
from openemux.core.playlist_manager import PlaylistManager
from openemux.core.retroarch_buildbot_updater import (
    SHADER_PACKS,
    RetroArchBuildbotUpdater,
    shader_pack_for,
)
from openemux.core.scanner import RomScanner
from openemux.core.systems import SYSTEM_IDS, curated_core_filenames

logger = logging.getLogger(__name__)


@dataclass
class BootstrapStep:
    step_id: str
    label_key: str
    handler: callable


def _first_failure_reason(*summaries):
    """The first real reason out of the download summaries, for the message.

    "Something failed" is not an error a user can act on; "URLError: Network
    is unreachable" is (issue #211).
    """
    for summary in summaries:
        for failure in summary.get("failures") or []:
            artifact = failure.get("artifact") or "?"
            error = failure.get("error") or "unknown error"
            return f"{artifact}: {error}"
    return "no details reported"


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
            BootstrapStep("openemux_config_files", "bootstrap.step.config", self._step_config_files),
            BootstrapStep("openemux_directories", "bootstrap.step.directories", self._step_directories),
            BootstrapStep("input_profiles_seed", "bootstrap.step.input_profiles", self._step_input_profiles),
            BootstrapStep("playlists_seed", "bootstrap.step.playlists", self._step_playlists),
            BootstrapStep("retroarch_environment", "bootstrap.step.retroarch_env", self._step_retroarch_env),
            # The id predates issue #442 and no longer means "all": it is kept
            # because it is persisted in every config's completed_steps.
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
        """Download what makes every console playable, and owe the rest.

        This step holds the first-boot window open, and it used to fetch every
        core the buildbot lists and both shader packs: 240 requests and 747
        MiB, of which the app names 35 cores (issue #442). It now waits for
        those, for the core info files and for the one shader pack the video
        driver reads, and records the remainder as owed for
        ``download_deferred_assets`` to fetch once the window is up.
        """
        if is_running_in_flatpak():
            # Cores are managed by the RetroArch Flatpak's own updater; OpenEmux
            # must not download binaries into its sandbox.
            return {"skipped": "flatpak", "cores": {}, "shaders": {}, "warning": None}

        def _progress(evt):
            if on_event:
                on_event(evt)

        primary_pack = self._primary_shader_pack()
        cores_summary = self.updater.download_all(
            on_progress=_progress, only=curated_core_filenames()
        )
        info_summary = self.updater.install_core_info(on_progress=_progress)
        shaders_summary = self.updater.download_shader_packs_if_missing(
            on_progress=_progress, packs=[primary_pack] if primary_pack else []
        )
        total_failures = int(cores_summary.get("failed", 0)) + int(shaders_summary.get("failed", 0))
        if total_failures > 0 and not self.updater.has_local_runtime_assets():
            raise RuntimeError(
                "RetroArch asset update failed and no local bundled assets were found. "
                "Connect to the internet or provide local cores/shaders. "
                f"({_first_failure_reason(cores_summary, shaders_summary)})"
            )

        warning = None
        if total_failures > 0:
            warning = (
                "RetroArch update had failures, continuing with local bundled assets."
            )
            logger.warning(
                "first boot fell back to the bundled assets: %s",
                _first_failure_reason(cores_summary, shaders_summary),
            )
        if info_summary.get("failed"):
            # Not counted above: without the .info files the pickers name
            # cores after their filenames, which is how it always was.
            logger.warning(
                "first boot continues without core info: %s",
                _first_failure_reason(info_summary),
            )
        if self.updater.settings.get("enabled", True):
            self.config_manager.mark_deferred_assets_pending()
        return {
            "cores": cores_summary,
            "core_info": info_summary,
            "shaders": shaders_summary,
            "warning": warning,
        }

    def _primary_shader_pack(self):
        return shader_pack_for(self.config_manager.get_retroarch_video_driver())

    def download_deferred_assets(self, on_progress=None, cancel_event=None):
        """Fetch what the first boot left for later: the other cores and shaders.

        Run from a background thread once the main window is up. The debt is
        cleared only by a sweep that finished clean; a failure or a
        cancellation leaves it owed, and the next launch tries again. Never
        raises, for the same reason ``download_all`` does not.
        """
        primary_pack = self._primary_shader_pack()
        cores_summary = self.updater.download_all(
            on_progress=on_progress,
            skip=curated_core_filenames(),
            cancel_event=cancel_event,
        )
        cancelled = bool(cancel_event is not None and cancel_event.is_set())
        if cancelled:
            shaders_summary = {"total": 0, "downloaded": 0, "failed": 0, "failures": []}
        else:
            shaders_summary = self.updater.download_shader_packs_if_missing(
                on_progress=on_progress,
                packs=[pack for pack in SHADER_PACKS.values() if pack != primary_pack],
            )
        failed = int(cores_summary.get("failed", 0)) + int(shaders_summary.get("failed", 0))
        cancelled = cancelled or bool(cores_summary.get("cancelled"))
        if not failed and not cancelled:
            self.config_manager.mark_deferred_assets_done()
        else:
            logger.warning(
                "deferred asset download left owed: failed=%d cancelled=%s first=%s",
                failed,
                cancelled,
                _first_failure_reason(cores_summary, shaders_summary),
            )
        return {
            "cores": cores_summary,
            "shaders": shaders_summary,
            "failed": failed,
            "cancelled": cancelled,
        }

    def missing_curated_cores(self, ignore_unavailable=True):
        """The cores some console names that no searched directory holds.

        A completed first boot is not proof the cores are still there: the
        Windows zip keeps them inside the app folder, so replacing that folder
        with a new release drops every one while the config still says the
        step is done (issue #512). Looked up through the same directories the
        launcher resolves Automatic through, so a core it could run -- bundled,
        from the distribution or from the user's own RetroArch -- is never
        missing. ``ignore_unavailable`` leaves out the names this version
        already learned the buildbot does not build for this machine.
        """
        if is_running_in_flatpak():
            return []
        dirs = core_search_dirs(get_project_root())
        missing = [
            name
            for name in curated_core_filenames()
            if not any((directory / name).exists() for directory in dirs)
        ]
        if ignore_unavailable:
            stored = self.config_manager.get_unavailable_cores()
            if stored["version"] == __version__:
                unavailable = set(stored["names"])
                missing = [name for name in missing if name not in unavailable]
        return missing

    def repair_missing_cores(self, on_progress=None, cancel_event=None, manual=False, on_missing=None):
        """Download the curated cores that went missing, and nothing else.

        The bootstrap stays completed and no setting is touched. When the
        download folder came back with no core at all, the rest are owed again
        so the deferred sweep refetches them. ``manual`` re-checks the names
        remembered as unavailable. ``on_missing`` is told the missing names
        before any download starts, so a caller can show progress only when
        there is something to fetch. Never raises.
        """
        summary = {
            "missing": [],
            "downloaded": 0,
            "failed": 0,
            "failures": [],
            "cancelled": False,
            "disabled": False,
            "unlisted": [],
        }
        try:
            missing = self.missing_curated_cores(ignore_unavailable=not manual)
            summary["missing"] = missing
            if not missing:
                return summary
            if not self.updater.settings.get("enabled", True):
                summary["disabled"] = True
                return summary
            if on_missing:
                on_missing(missing)
            core_dir = self.updater.core_dir
            had_cores = core_dir.is_dir() and any(core_dir.glob("*_libretro" + CORE_SUFFIX))
            cores_summary = self.updater.download_all(
                on_progress=on_progress, only=missing, cancel_event=cancel_event
            )
            summary["downloaded"] = int(cores_summary.get("downloaded", 0))
            summary["failed"] = int(cores_summary.get("failed", 0))
            summary["failures"] = list(cores_summary.get("failures") or [])
            summary["cancelled"] = bool(
                cores_summary.get("cancelled")
                or (cancel_event is not None and cancel_event.is_set())
            )
            summary["unlisted"] = list(cores_summary.get("unlisted") or [])
            if summary["downloaded"]:
                # The .info files lived in the same folder that was wiped.
                self.updater.install_core_info()
            if not summary["failed"]:
                # Only a listing that answered says what is not built here.
                # The start-up check never asked about the names it already
                # knew, so it keeps them; the manual check asked about all.
                unavailable = set(summary["unlisted"])
                stored = self.config_manager.get_unavailable_cores()
                if not manual and stored["version"] == __version__:
                    unavailable.update(stored["names"])
                self.config_manager.set_unavailable_cores(__version__, unavailable)
            if not had_cores:
                self.config_manager.mark_deferred_assets_pending()
        except Exception as exc:
            logger.exception("core repair crashed")
            summary["failed"] = max(1, summary["failed"])
            summary["failures"] = [{"artifact": "repair", "error": str(exc)}]
        logger.info(
            "core repair finished: missing=%d downloaded=%d failed=%d cancelled=%s",
            len(summary["missing"]),
            summary["downloaded"],
            summary["failed"],
            summary["cancelled"],
        )
        return summary
