import threading
import unittest
import urllib.error
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from openemux.core import first_boot
from openemux.core.first_boot import FirstBootBootstrapper
from openemux.core.systems import curated_core_filenames


class _FakeConfigManager:
    def __init__(self, base_dir):
        self.base_dir = Path(base_dir)
        self.roms_path = self.base_dir / "roms"
        self.playlists_dir = self.base_dir / "playlists"
        self.runtime_dir = self.base_dir / "runtime"
        self.video_driver = "auto"
        self.state = {
            "status": "pending",
            "completed_steps": [],
            "failed_step": None,
            "retry_requested": False,
            "retry_count": 0,
        }
        self.config = {
            "setup": {"bootstrap": self.state},
            "runtime": {
                "retroarch": {
                    "updater": {
                        "mode": "buildbot_all_cores",
                        "enabled": False,
                        "cores_base_url": "",
                        "core_info_base_url": "",
                        "request_timeout_sec": 5,
                        "retries": 0,
                        "parallel_downloads": 1,
                    }
                }
            },
        }

    def get_roms_path(self):
        return self.roms_path

    def get_playlists_dir(self):
        return self.playlists_dir

    def get_runtime_dir(self):
        return self.runtime_dir

    def get_retroarch_updater_settings(self):
        return self.config["runtime"]["retroarch"]["updater"]

    def save_config(self, config=None):
        if config:
            self.config = config

    def ensure_rom_directories(self):
        self.roms_path.mkdir(parents=True, exist_ok=True)
        self.playlists_dir.mkdir(parents=True, exist_ok=True)
        self.runtime_dir.mkdir(parents=True, exist_ok=True)

    def ensure_input_profiles(self):
        # no-op for this unit test
        return None

    def bootstrap_needs_run(self):
        return self.state.get("status") in ("pending", "running") or self.state.get("retry_requested", False)

    def get_bootstrap_state(self):
        return self.state

    def start_bootstrap_run(self):
        self.state["status"] = "running"
        self.state["failed_step"] = None
        self.state["retry_requested"] = False

    def mark_bootstrap_step_completed(self, step_id):
        if step_id not in self.state["completed_steps"]:
            self.state["completed_steps"].append(step_id)

    def finish_bootstrap_success(self):
        self.state["status"] = "completed"
        self.state["failed_step"] = None
        self.state["retry_requested"] = False

    def get_retroarch_video_driver(self):
        return self.video_driver

    def deferred_assets_pending(self):
        return self.state.get("deferred_assets") == "pending"

    def mark_deferred_assets_pending(self):
        self.state["deferred_assets"] = "pending"

    def mark_deferred_assets_done(self):
        self.state["deferred_assets"] = "done"

    def finish_bootstrap_failure(self, step_id, error_message):
        self.state["status"] = "failed"
        self.state["failed_step"] = step_id
        self.state["last_error"] = str(error_message)
        self.state["retry_requested"] = False


class FirstBootBootstrapperTests(unittest.TestCase):
    def test_run_marks_bootstrap_completed(self):
        with TemporaryDirectory() as tmp_dir:
            cfg = _FakeConfigManager(tmp_dir)
            bootstrapper = FirstBootBootstrapper(cfg)
            events = []
            result = bootstrapper.run(on_event=lambda evt: events.append(evt["type"]))

        self.assertTrue(result["success"])
        self.assertEqual(cfg.state["status"], "completed")
        self.assertIn("openemux_config_files", cfg.state["completed_steps"])
        self.assertIn("retroarch_download_all_cores", cfg.state["completed_steps"])
        self.assertIn("bootstrap_completed", events)
        # The updater is off here, so nothing is owed for the background.
        self.assertFalse(cfg.deferred_assets_pending())

    def test_run_allows_download_failures_when_local_assets_exist(self):
        with TemporaryDirectory() as tmp_dir:
            cfg = _FakeConfigManager(tmp_dir)
            cfg.config["runtime"]["retroarch"]["updater"]["enabled"] = True
            bootstrapper = FirstBootBootstrapper(cfg)
            bootstrapper.updater.download_all = lambda on_progress=None, **_kwargs: {
                "total": 1,
                "downloaded": 0,
                "failed": 1,
                "failures": [{"artifact": "core", "error": "network"}],
            }
            bootstrapper.updater.download_shader_packs_if_missing = lambda on_progress=None, **_kwargs: {
                "total": 1,
                "downloaded": 0,
                "failed": 1,
                "failures": [{"artifact": "shader", "error": "network"}],
            }
            bootstrapper.updater.has_local_runtime_assets = lambda: True

            result = bootstrapper.run()

        self.assertTrue(result["success"])
        self.assertEqual(cfg.state["status"], "completed")


class ResumingAnInterruptedBootstrapTests(unittest.TestCase):
    """The steps are resumable: a crash mid-run must not redo the downloads."""

    def test_a_step_already_done_is_reported_as_skipped_and_not_rerun(self):
        with TemporaryDirectory() as tmp_dir:
            cfg = _FakeConfigManager(tmp_dir)
            cfg.state["completed_steps"] = ["openemux_config_files"]
            bootstrapper = FirstBootBootstrapper(cfg)
            ran = []
            bootstrapper._step_config_files = lambda on_event=None: ran.append(1)
            events = []

            bootstrapper.run(on_event=events.append)

        self.assertEqual(ran, [])
        skipped = [evt for evt in events if evt["type"] == "step_skipped"]
        self.assertEqual([evt["step_id"] for evt in skipped], ["openemux_config_files"])

    def test_a_step_that_raises_ends_the_run_and_names_the_step(self):
        with TemporaryDirectory() as tmp_dir:
            cfg = _FakeConfigManager(tmp_dir)
            bootstrapper = FirstBootBootstrapper(cfg)

            def _boom(on_event=None):
                raise RuntimeError("disk full")

            bootstrapper._step_directories = _boom
            events = []

            result = bootstrapper.run(on_event=events.append)

        self.assertFalse(result["success"])
        failed = [evt for evt in events if evt["type"] == "bootstrap_failed"]
        self.assertEqual(failed[0]["step_id"], "openemux_directories")


class TheCoreDownloadStepTests(unittest.TestCase):
    def test_inside_a_flatpak_the_cores_are_left_to_retroarchs_own_updater(self):
        # Downloading binaries into the sandbox is exactly what the Flatpak
        # rules forbid, and RetroArch's own Flatpak already manages them.
        with TemporaryDirectory() as tmp_dir:
            bootstrapper = FirstBootBootstrapper(_FakeConfigManager(tmp_dir))
            with patch(
                "openemux.core.first_boot.is_running_in_flatpak", return_value=True
            ):
                self.assertEqual(
                    bootstrapper._step_retroarch_cores()["skipped"], "flatpak"
                )

    def test_the_download_progress_is_passed_on_to_the_caller(self):
        with TemporaryDirectory() as tmp_dir:
            bootstrapper = FirstBootBootstrapper(_FakeConfigManager(tmp_dir))
            bootstrapper.updater.download_all = (
                lambda on_progress=None, **_kwargs: on_progress({"type": "core"}) or {"failures": []}
            )
            bootstrapper.updater.download_shader_packs_if_missing = (
                lambda on_progress=None, **_kwargs: {"failures": []}
            )
            seen = []
            with patch(
                "openemux.core.first_boot.is_running_in_flatpak", return_value=False
            ):
                bootstrapper._step_retroarch_cores(on_event=seen.append)
        self.assertEqual(seen, [{"type": "core"}])


def _clean(**extra):
    summary = {"total": 0, "downloaded": 0, "failed": 0, "failures": []}
    summary.update(extra)
    return summary


class _RecordingUpdater:
    """Stands in for the updater's download methods and records the calls."""

    def __init__(self, updater, cores=None, shaders=None, info=None):
        self.calls = {}
        self._cores = cores or _clean()
        self._shaders = shaders or _clean()
        self._info = info or _clean()
        updater.download_all = self._record("download_all", lambda: self._cores)
        updater.download_shader_packs_if_missing = self._record("shaders", lambda: self._shaders)
        updater.install_core_info = self._record("core_info", lambda: self._info)

    def _record(self, name, result):
        def _call(**kwargs):
            self.calls[name] = kwargs
            return result()

        return _call


class TheFirstBootWaitsForThePlayableSetTests(unittest.TestCase):
    """Only what makes every console playable holds the window (issue #442)."""

    def _step(self, tmp_dir, video_driver="gl", **outcomes):
        cfg = _FakeConfigManager(tmp_dir)
        cfg.config["runtime"]["retroarch"]["updater"]["enabled"] = True
        cfg.video_driver = video_driver
        bootstrapper = FirstBootBootstrapper(cfg)
        recorder = _RecordingUpdater(bootstrapper.updater, **outcomes)
        with patch("openemux.core.first_boot.is_running_in_flatpak", return_value=False):
            detail = bootstrapper._step_retroarch_cores()
        return cfg, recorder, detail

    def test_it_fetches_the_curated_cores_only(self):
        with TemporaryDirectory() as tmp_dir:
            _, recorder, _ = self._step(tmp_dir)
        self.assertEqual(recorder.calls["download_all"]["only"], curated_core_filenames())
        self.assertNotIn("skip", recorder.calls["download_all"])

    def test_it_fetches_the_shader_pack_the_driver_reads(self):
        for driver, pack in (("gl", "shaders_glsl"), ("vulkan", "shaders_slang")):
            with self.subTest(driver=driver), TemporaryDirectory() as tmp_dir:
                _, recorder, _ = self._step(tmp_dir, video_driver=driver)
                self.assertEqual(recorder.calls["shaders"]["packs"], [pack])

    def test_a_driver_with_no_shaders_waits_for_no_pack(self):
        with TemporaryDirectory() as tmp_dir:
            _, recorder, _ = self._step(tmp_dir, video_driver="sdl2")
        self.assertEqual(recorder.calls["shaders"]["packs"], [])

    def test_it_installs_the_core_info_files(self):
        with TemporaryDirectory() as tmp_dir:
            _, recorder, detail = self._step(tmp_dir)
        self.assertIn("core_info", recorder.calls)
        self.assertIn("core_info", detail)

    def test_the_rest_is_recorded_as_owed(self):
        with TemporaryDirectory() as tmp_dir:
            cfg, _, _ = self._step(tmp_dir)
        self.assertTrue(cfg.deferred_assets_pending())

    def test_missing_core_info_does_not_fail_the_step(self):
        info = _clean(failed=1, failures=[{"artifact": "core_info", "error": "404"}])
        with TemporaryDirectory() as tmp_dir:
            with self.assertLogs("openemux.core.first_boot", "WARNING") as logs:
                _, _, detail = self._step(tmp_dir, info=info)
        self.assertIsNone(detail["warning"])
        self.assertIn("core_info: 404", "\n".join(logs.output))

    def test_inside_a_flatpak_nothing_is_owed(self):
        with TemporaryDirectory() as tmp_dir:
            cfg = _FakeConfigManager(tmp_dir)
            bootstrapper = FirstBootBootstrapper(cfg)
            with patch("openemux.core.first_boot.is_running_in_flatpak", return_value=True):
                bootstrapper._step_retroarch_cores()
        self.assertFalse(cfg.deferred_assets_pending())


class TheDeferredDownloadTests(unittest.TestCase):
    """The cores and shaders the first boot left for the background (#442)."""

    def _run(self, tmp_dir, cancel_event=None, video_driver="gl", **outcomes):
        cfg = _FakeConfigManager(tmp_dir)
        cfg.video_driver = video_driver
        cfg.mark_deferred_assets_pending()
        bootstrapper = FirstBootBootstrapper(cfg)
        recorder = _RecordingUpdater(bootstrapper.updater, **outcomes)
        result = bootstrapper.download_deferred_assets(cancel_event=cancel_event)
        return cfg, recorder, result

    def test_it_fetches_every_core_but_the_curated_ones(self):
        with TemporaryDirectory() as tmp_dir:
            _, recorder, _ = self._run(tmp_dir)
        self.assertEqual(recorder.calls["download_all"]["skip"], curated_core_filenames())
        self.assertNotIn("only", recorder.calls["download_all"])

    def test_it_fetches_the_other_shader_pack(self):
        for driver, packs in (
            ("gl", ["shaders_slang"]),
            ("vulkan", ["shaders_glsl"]),
            ("sdl2", ["shaders_glsl", "shaders_slang"]),
        ):
            with self.subTest(driver=driver), TemporaryDirectory() as tmp_dir:
                _, recorder, _ = self._run(tmp_dir, video_driver=driver)
                self.assertEqual(recorder.calls["shaders"]["packs"], packs)

    def test_a_clean_sweep_pays_the_debt(self):
        with TemporaryDirectory() as tmp_dir:
            cfg, _, result = self._run(tmp_dir)
        self.assertFalse(cfg.deferred_assets_pending())
        self.assertEqual((result["failed"], result["cancelled"]), (0, False))

    def test_a_failure_leaves_it_owed_for_the_next_launch(self):
        cores = _clean(failed=1, failures=[{"artifact": "x.zip", "error": "reset"}])
        with TemporaryDirectory() as tmp_dir:
            with self.assertLogs("openemux.core.first_boot", "WARNING"):
                cfg, _, result = self._run(tmp_dir, cores=cores)
        self.assertTrue(cfg.deferred_assets_pending())
        self.assertEqual(result["failed"], 1)

    def test_a_cancelled_sweep_leaves_it_owed_and_skips_the_shaders(self):
        cancel = threading.Event()
        cancel.set()
        with TemporaryDirectory() as tmp_dir:
            with self.assertLogs("openemux.core.first_boot", "WARNING"):
                cfg, recorder, result = self._run(
                    tmp_dir, cancel_event=cancel, cores=_clean(cancelled=4)
                )
        self.assertTrue(cfg.deferred_assets_pending())
        self.assertTrue(result["cancelled"])
        self.assertIs(recorder.calls["download_all"]["cancel_event"], cancel)
        self.assertNotIn("shaders", recorder.calls)

    def test_cores_cancelled_without_the_event_still_count(self):
        with TemporaryDirectory() as tmp_dir:
            with self.assertLogs("openemux.core.first_boot", "WARNING"):
                cfg, _, result = self._run(tmp_dir, cores=_clean(cancelled=1))
        self.assertTrue(result["cancelled"])
        self.assertTrue(cfg.deferred_assets_pending())


class WhatTheFailureMessageSaysTests(unittest.TestCase):
    def test_a_failure_with_no_details_at_all_still_says_something(self):
        # "Something failed" is not actionable, but neither is an empty string.
        self.assertEqual(
            first_boot._first_failure_reason({"failures": []}, {}),
            "no details reported",
        )


class OfflineFirstBootTests(unittest.TestCase):
    """Installing offline from a package that bundles cores must still work."""

    def _bootstrapper(self, tmp_dir):
        cfg = _FakeConfigManager(tmp_dir)
        cfg.config["runtime"]["retroarch"]["updater"]["enabled"] = True
        cfg.config["runtime"]["retroarch"]["updater"]["cores_base_url"] = (
            "https://example.invalid/buildbot/"
        )
        return cfg, FirstBootBootstrapper(cfg)

    def test_offline_falls_back_to_the_bundled_cores(self):
        with TemporaryDirectory() as tmp_dir:
            cfg, bootstrapper = self._bootstrapper(tmp_dir)
            bootstrapper.updater.has_local_runtime_assets = lambda: True
            with patch(
                "urllib.request.urlopen",
                side_effect=urllib.error.URLError("Network is unreachable"),
            ):
                result = bootstrapper.run()

        self.assertTrue(result["success"])
        self.assertEqual(cfg.state["status"], "completed")
        self.assertIn("retroarch_download_all_cores", cfg.state["completed_steps"])

    def test_offline_without_bundled_cores_fails_with_the_real_reason(self):
        with TemporaryDirectory() as tmp_dir:
            cfg, bootstrapper = self._bootstrapper(tmp_dir)
            bootstrapper.updater.has_local_runtime_assets = lambda: False
            with patch(
                "urllib.request.urlopen",
                side_effect=urllib.error.URLError("Network is unreachable"),
            ):
                result = bootstrapper.run()

        self.assertFalse(result["success"])
        self.assertEqual(result["failed_step"], "retroarch_download_all_cores")
        self.assertIn("unreachable", result["error"])
        # Not recorded as done, so a retry actually retries it.
        self.assertNotIn("retroarch_download_all_cores", cfg.state["completed_steps"])

    def test_an_empty_listing_does_not_complete_the_step(self):
        with TemporaryDirectory() as tmp_dir:
            cfg, bootstrapper = self._bootstrapper(tmp_dir)
            bootstrapper.updater.has_local_runtime_assets = lambda: False
            bootstrapper.updater.download_shader_packs_if_missing = (
                lambda on_progress=None, **_kwargs: {"total": 0, "downloaded": 0, "failed": 0, "failures": []}
            )
            with patch(
                "urllib.request.urlopen",
                return_value=_FakeListing(b"<html>the layout changed</html>"),
            ):
                result = bootstrapper.run()

        self.assertFalse(result["success"])
        self.assertNotIn("retroarch_download_all_cores", cfg.state["completed_steps"])
        self.assertIn("listing", result["error"])


class _FakeListing:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self.payload


if __name__ == "__main__":
    unittest.main()
