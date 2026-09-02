"""Every store follows the config directory it was pointed at (issue #239).

`ConfigManager(config_file=...)` looked like it moved the whole of the app's
state, and did not: input profiles, shaders, per-ROM core overrides, cartridge
colours, core options, the RetroAchievements token and the play history each
derived `~/.openemux` for themselves. A manager pointed at a temporary
directory -- which is how every test and every development run points it --
still read and wrote the developer's real profile.

One function answers "where does the app keep its data" now, and the manager
hands every store a path under its own directory.
"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from openemux.core.config import ConfigManager
from openemux.core.paths import STORE_FILENAMES, default_config_dir, store_path


class TheOneAnswerTests(unittest.TestCase):
    def test_the_app_keeps_its_data_under_the_home_directory(self):
        directory = default_config_dir()
        self.assertEqual(directory.parent, Path.home())
        self.assertEqual(directory.name, ".openemux")

    def test_a_store_path_defaults_under_that_directory(self):
        self.assertEqual(store_path("config").parent, default_config_dir())

    def test_a_store_path_follows_the_directory_it_is_given(self):
        self.assertEqual(
            store_path("play_history", config_dir=Path("/elsewhere")),
            Path("/elsewhere/play_history.json"),
        )

    def test_an_unknown_store_raises_rather_than_inventing_a_path(self):
        # A typo that silently returned <dir>/None would write somewhere
        # nobody meant.
        with self.assertRaises(KeyError):
            store_path("playhistory")


class NothingLeaksIntoTheRealHomeTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.config = ConfigManager(config_file=self.root / "config.yaml")

    def tearDown(self):
        self._tmp.cleanup()

    def _under_root(self, path):
        return Path(path).resolve().is_relative_to(self.root.resolve())

    def test_the_manager_knows_its_own_directory(self):
        self.assertEqual(self.config.config_dir, self.root)

    def test_every_store_it_owns_sits_beside_its_config_file(self):
        stores = {
            "input profiles": self.config.input_profiles.input_dir,
            "shaders": self.config.shaders.config_file,
            "per-ROM cores": self.config.cores.config_file,
            "cartridge colours": self.config.cartridge_colors.config_file,
            "core options": self.config.core_options.config_file,
            "achievements": self.config.achievements.config_file,
            "play history": self.config.get_play_history_file(),
            "session": self.config.session.session_file,
        }
        for name, path in stores.items():
            with self.subTest(store=name):
                self.assertTrue(
                    self._under_root(path),
                    f"{name} is at {path}, outside the chosen config dir",
                )

    def test_writing_a_per_rom_core_override_stays_in_the_temporary_dir(self):
        self.config.set_rom_core("/roms/SFC/game.sfc", "snes9x_libretro.so")
        self.assertTrue((self.root / "cores.config").exists())
        self.assertEqual(
            self.config.get_rom_core_override("/roms/SFC/game.sfc"),
            "snes9x_libretro.so",
        )

    def test_two_managers_on_two_directories_do_not_see_each_other(self):
        with TemporaryDirectory() as other_tmp:
            other = ConfigManager(config_file=Path(other_tmp) / "config.yaml")
            self.config.set_rom_core("/roms/SFC/game.sfc", "snes9x_libretro.so")
            self.assertIsNone(other.get_rom_core_override("/roms/SFC/game.sfc"))

    def test_the_store_names_it_asks_for_are_all_known(self):
        for name in ("config", "input", "shaders", "cores", "play_history", "session"):
            with self.subTest(store=name):
                self.assertIn(name, STORE_FILENAMES)


if __name__ == "__main__":
    unittest.main()
