import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from openemux.core.config import ConfigManager


class ConfigBootstrapDefaultsTests(unittest.TestCase):
    def test_bootstrap_defaults_are_present(self):
        with TemporaryDirectory() as tmp_dir:
            cfg_path = Path(tmp_dir) / "config.yaml"
            manager = ConfigManager(config_file=cfg_path)
            state = manager.get_bootstrap_state()
            updater = manager.get_retroarch_updater_settings()

        self.assertEqual(state.get("status"), "pending")
        self.assertEqual(state.get("version"), 1)
        self.assertIn("completed_steps", state)
        self.assertTrue(updater["enabled"])
        self.assertEqual(updater["mode"], "buildbot_all_cores")
        self.assertIn("cores_base_url", updater)

    def test_bootstrap_need_run_transitions(self):
        with TemporaryDirectory() as tmp_dir:
            cfg_path = Path(tmp_dir) / "config.yaml"
            manager = ConfigManager(config_file=cfg_path)
            self.assertTrue(manager.bootstrap_needs_run())

            manager.start_bootstrap_run()
            self.assertTrue(manager.bootstrap_needs_run())

            manager.finish_bootstrap_success()
            self.assertFalse(manager.bootstrap_needs_run())

            manager.request_bootstrap_retry()
            self.assertTrue(manager.bootstrap_needs_run())

    def test_locale_setter_normalizes_invalid_values(self):
        with TemporaryDirectory() as tmp_dir:
            cfg_path = Path(tmp_dir) / "config.yaml"
            manager = ConfigManager(config_file=cfg_path)

            manager.set_locale("de")
            self.assertEqual(manager.get_locale(), "de")

            manager.set_locale("invalid-locale")
            self.assertEqual(manager.get_locale(), "en")


if __name__ == "__main__":
    unittest.main()
