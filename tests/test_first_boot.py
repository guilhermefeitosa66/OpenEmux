import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

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


if __name__ == "__main__":
    unittest.main()
