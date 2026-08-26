import unittest
import urllib.error
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from openemux.core.first_boot import FirstBootBootstrapper


class _FakeConfigManager:
    def __init__(self, base_dir):
        self.base_dir = Path(base_dir)
        self.roms_path = self.base_dir / "roms"
        self.playlists_dir = self.base_dir / "playlists"
        self.runtime_dir = self.base_dir / "runtime"
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

    def test_run_allows_download_failures_when_local_assets_exist(self):
        with TemporaryDirectory() as tmp_dir:
            cfg = _FakeConfigManager(tmp_dir)
            cfg.config["runtime"]["retroarch"]["updater"]["enabled"] = True
            bootstrapper = FirstBootBootstrapper(cfg)
            bootstrapper.updater.download_all = lambda on_progress=None: {
                "total": 1,
                "downloaded": 0,
                "failed": 1,
                "failures": [{"artifact": "core", "error": "network"}],
            }
            bootstrapper.updater.download_shader_packs_if_missing = lambda on_progress=None: {
                "total": 1,
                "downloaded": 0,
                "failed": 1,
                "failures": [{"artifact": "shader", "error": "network"}],
            }
            bootstrapper.updater.has_local_runtime_assets = lambda: True

            result = bootstrapper.run()

        self.assertTrue(result["success"])
        self.assertEqual(cfg.state["status"], "completed")


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
                "openemux.core.retroarch_buildbot_updater.urllib.request.urlopen",
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
                "openemux.core.retroarch_buildbot_updater.urllib.request.urlopen",
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
                lambda on_progress=None: {"total": 0, "downloaded": 0, "failed": 0, "failures": []}
            )
            with patch(
                "openemux.core.retroarch_buildbot_updater.urllib.request.urlopen",
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
