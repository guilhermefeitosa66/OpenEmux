"""The ``runtime.game_window`` setting and its pre-GTK reader (issue #199)."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import yaml

from openemux.core.config import ConfigManager, read_game_window_setting


class GameWindowConfigTests(unittest.TestCase):
    def test_defaults_to_on(self):
        with TemporaryDirectory() as tmp_dir:
            manager = ConfigManager(config_file=Path(tmp_dir) / "config.yaml")
            self.assertTrue(manager.get_game_window_enabled())

    def test_turning_it_off_persists(self):
        with TemporaryDirectory() as tmp_dir:
            cfg_path = Path(tmp_dir) / "config.yaml"
            ConfigManager(config_file=cfg_path).set_game_window_enabled(False)

            self.assertFalse(ConfigManager(config_file=cfg_path).get_game_window_enabled())

    def test_an_existing_config_gains_the_default(self):
        # Every config written before #199 says nothing about the game window,
        # and those users should get it.
        with TemporaryDirectory() as tmp_dir:
            cfg_path = Path(tmp_dir) / "config.yaml"
            cfg_path.write_text(
                yaml.safe_dump({"runtime": {"master_volume_db": -3.0}}), encoding="utf-8"
            )
            manager = ConfigManager(config_file=cfg_path)
            self.assertTrue(manager.get_game_window_enabled())
            self.assertEqual(manager.get_master_volume_db(), -3.0)


class ReadGameWindowSettingTests(unittest.TestCase):
    """``main.py`` reads the file directly, before GTK and before a manager."""

    def test_reads_a_stored_false(self):
        with TemporaryDirectory() as tmp_dir:
            cfg_path = Path(tmp_dir) / "config.yaml"
            ConfigManager(config_file=cfg_path).set_game_window_enabled(False)
            self.assertFalse(read_game_window_setting(cfg_path))

    def test_missing_file_means_the_default(self):
        with TemporaryDirectory() as tmp_dir:
            self.assertTrue(read_game_window_setting(Path(tmp_dir) / "nope.yaml"))

    def test_unreadable_config_means_the_default(self):
        # A broken config must not cost the user the game window -- and must
        # not raise this early, where nothing is set up to report it.
        with TemporaryDirectory() as tmp_dir:
            cfg_path = Path(tmp_dir) / "config.yaml"
            cfg_path.write_text("{ this is: not: yaml", encoding="utf-8")
            self.assertTrue(read_game_window_setting(cfg_path))

    def test_creates_nothing(self):
        # The config dir may still be mid-migration at this point; reading it
        # must not stamp a file into place.
        with TemporaryDirectory() as tmp_dir:
            cfg_path = Path(tmp_dir) / "config.yaml"
            read_game_window_setting(cfg_path)
            self.assertFalse(cfg_path.exists())


if __name__ == "__main__":
    unittest.main()
