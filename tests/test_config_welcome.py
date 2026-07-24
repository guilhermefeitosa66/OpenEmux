import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from openemux.core.config import ConfigManager


class WelcomeStartupConfigTests(unittest.TestCase):
    def _manager(self, tmp_dir):
        return ConfigManager(config_file=Path(tmp_dir) / "config.yaml")

    def test_defaults_to_true(self):
        with TemporaryDirectory() as tmp_dir:
            manager = self._manager(tmp_dir)
            self.assertTrue(manager.get_show_welcome_on_startup())
            self.assertTrue(manager.get_ui_settings()["show_welcome_on_startup"])

    def test_set_false_persists(self):
        with TemporaryDirectory() as tmp_dir:
            cfg_path = Path(tmp_dir) / "config.yaml"
            manager = ConfigManager(config_file=cfg_path)
            manager.set_show_welcome_on_startup(False)

            reloaded = ConfigManager(config_file=cfg_path)
            self.assertFalse(reloaded.get_show_welcome_on_startup())
            self.assertFalse(reloaded.get_ui_settings()["show_welcome_on_startup"])

    def test_set_true_again(self):
        with TemporaryDirectory() as tmp_dir:
            cfg_path = Path(tmp_dir) / "config.yaml"
            manager = ConfigManager(config_file=cfg_path)
            manager.set_show_welcome_on_startup(False)
            manager.set_show_welcome_on_startup(True)

            reloaded = ConfigManager(config_file=cfg_path)
            self.assertTrue(reloaded.get_show_welcome_on_startup())


if __name__ == "__main__":
    unittest.main()
