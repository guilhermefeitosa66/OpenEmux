"""Language precedence: user choice, then the desktop locale, then English."""

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from openemux.core.config import ConfigManager

#: A clean environment plus one desktop language, so the host's own locale
#: cannot leak into the assertions.
def _env(**overrides):
    stripped = {k: "" for k in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG")}
    stripped.update(overrides)
    return stripped


class SystemLanguageOnFirstLaunchTests(unittest.TestCase):
    def _manager(self, tmp_dir, **env):
        with mock.patch.dict(os.environ, _env(**env), clear=False):
            return ConfigManager(config_file=Path(tmp_dir) / "config.yaml")

    def test_first_launch_follows_the_desktop_language(self):
        with TemporaryDirectory() as tmp_dir:
            manager = self._manager(tmp_dir, LANG="pt_BR.UTF-8")
            self.assertEqual(manager.get_locale(), "pt_BR")

    def test_unsupported_desktop_language_falls_back_to_english(self):
        with TemporaryDirectory() as tmp_dir:
            manager = self._manager(tmp_dir, LANG="ru_RU.UTF-8")
            self.assertEqual(manager.get_locale(), "en")

    def test_an_explicit_choice_survives_a_different_desktop_language(self):
        with TemporaryDirectory() as tmp_dir:
            cfg_path = Path(tmp_dir) / "config.yaml"
            with mock.patch.dict(os.environ, _env(LANG="pt_BR.UTF-8"), clear=False):
                manager = ConfigManager(config_file=cfg_path)
                manager.set_locale("ja")

            with mock.patch.dict(os.environ, _env(LANG="pt_BR.UTF-8"), clear=False):
                reopened = ConfigManager(config_file=cfg_path)
            self.assertEqual(reopened.get_locale(), "ja")

    def test_choosing_english_on_a_translated_desktop_sticks(self):
        """English is a choice like any other once it is made from the menu."""
        with TemporaryDirectory() as tmp_dir:
            cfg_path = Path(tmp_dir) / "config.yaml"
            with mock.patch.dict(os.environ, _env(LANG="pt_BR.UTF-8"), clear=False):
                ConfigManager(config_file=cfg_path).set_locale("en")
                reopened = ConfigManager(config_file=cfg_path)
            self.assertEqual(reopened.get_locale(), "en")

    def test_config_still_on_the_old_english_default_starts_following_the_desktop(self):
        """The reported bug: existing installs stayed English on a pt_BR system."""
        with TemporaryDirectory() as tmp_dir:
            cfg_path = Path(tmp_dir) / "config.yaml"
            cfg_path.write_text("locale: en\n", encoding="utf-8")
            with mock.patch.dict(os.environ, _env(LANG="pt_BR.UTF-8"), clear=False):
                manager = ConfigManager(config_file=cfg_path)
            self.assertEqual(manager.get_locale(), "pt_BR")

    def test_a_translated_config_from_before_the_flag_counts_as_a_choice(self):
        """Only the language menu could have written it, so it is not touched."""
        with TemporaryDirectory() as tmp_dir:
            cfg_path = Path(tmp_dir) / "config.yaml"
            cfg_path.write_text("locale: fr\n", encoding="utf-8")
            with mock.patch.dict(os.environ, _env(LANG="pt_BR.UTF-8"), clear=False):
                manager = ConfigManager(config_file=cfg_path)
            self.assertEqual(manager.get_locale(), "fr")


if __name__ == "__main__":
    unittest.main()
