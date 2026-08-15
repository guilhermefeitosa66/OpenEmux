"""The interface theme setting (issue #198)."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from openemux.core.config import ConfigManager
from openemux.core.theme import (
    DEFAULT_THEME,
    THEME_DARK,
    THEME_LIGHT,
    THEME_SYSTEM,
    THEMES,
    normalize_theme,
    toggled_theme,
)


class NormalizeThemeTests(unittest.TestCase):
    def test_every_known_theme_survives(self):
        for theme in THEMES:
            self.assertEqual(normalize_theme(theme), theme)

    def test_case_and_padding_are_forgiven(self):
        self.assertEqual(normalize_theme("  DARK "), THEME_DARK)

    def test_anything_else_is_the_default(self):
        # A hand-edited config, or one written by a future version.
        for value in ("solarized", "", None, 3, [], "system-ish"):
            self.assertEqual(normalize_theme(value), DEFAULT_THEME, repr(value))

    def test_the_default_follows_the_desktop(self):
        self.assertEqual(DEFAULT_THEME, THEME_SYSTEM)


class ToggledThemeTests(unittest.TestCase):
    def test_dark_offers_light_and_back(self):
        self.assertEqual(toggled_theme(True), THEME_LIGHT)
        self.assertEqual(toggled_theme(False), THEME_DARK)


class ThemeConfigTests(unittest.TestCase):
    def _manager(self, tmp_dir):
        return ConfigManager(config_file=Path(tmp_dir) / "config.yaml")

    def test_defaults_to_system(self):
        with TemporaryDirectory() as tmp_dir:
            self.assertEqual(self._manager(tmp_dir).get_ui_settings()["theme"], THEME_SYSTEM)

    def test_round_trips(self):
        with TemporaryDirectory() as tmp_dir:
            cfg_path = Path(tmp_dir) / "config.yaml"
            ConfigManager(config_file=cfg_path).set_theme(THEME_DARK)

            reloaded = ConfigManager(config_file=cfg_path)
            self.assertEqual(reloaded.get_ui_settings()["theme"], THEME_DARK)

    def test_an_unknown_stored_value_reads_back_as_the_default(self):
        with TemporaryDirectory() as tmp_dir:
            cfg_path = Path(tmp_dir) / "config.yaml"
            manager = ConfigManager(config_file=cfg_path)
            manager.config["ui"]["theme"] = "midnight"
            self.assertEqual(manager.get_ui_settings()["theme"], THEME_SYSTEM)

    def test_setting_an_unknown_value_stores_the_default(self):
        with TemporaryDirectory() as tmp_dir:
            manager = self._manager(tmp_dir)
            self.assertEqual(manager.set_theme("midnight"), THEME_SYSTEM)


if __name__ == "__main__":
    unittest.main()
