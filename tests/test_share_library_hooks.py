"""The library hooks a received game reaches the managers through (#589)."""

import unittest
from pathlib import Path
from unittest import mock

from openemux.core.share.library_hooks import ManagerLibraryHooks


class ManagerLibraryHooksTests(unittest.TestCase):
    def setUp(self):
        self.playlists = mock.Mock()
        self.config = mock.Mock()
        self.hooks = ManagerLibraryHooks(self.playlists, self.config)
        self.path = Path("/roms/SFC/Game.sfc")

    def test_a_favorite_is_added(self):
        self.playlists.is_favorite.return_value = False
        self.hooks.set_favorite(self.path)
        self.playlists.toggle_favorite.assert_called_once_with({"path": "/roms/SFC/Game.sfc"})

    def test_a_favorite_already_there_is_never_toggled_off(self):
        self.playlists.is_favorite.return_value = True
        self.hooks.set_favorite(self.path)
        self.playlists.toggle_favorite.assert_not_called()

    def test_overrides_pass_through(self):
        self.hooks.set_cartridge_color(self.path, "SFC", "red")
        self.hooks.set_core(self.path, "snes9x_libretro.so")
        self.hooks.set_shader(self.path, "SFC", "crt")
        self.config.set_rom_cartridge_color.assert_called_once_with("/roms/SFC/Game.sfc", "SFC", "red")
        self.config.set_rom_core.assert_called_once_with("/roms/SFC/Game.sfc", "snes9x_libretro.so")
        self.config.set_rom_shader.assert_called_once_with("/roms/SFC/Game.sfc", "SFC", "crt")


if __name__ == "__main__":
    unittest.main()
