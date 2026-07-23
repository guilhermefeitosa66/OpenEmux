import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from openemux.core.config import ConfigManager


class ScopeLayoutConfigTests(unittest.TestCase):
    def _manager(self, tmp_dir):
        return ConfigManager(config_file=Path(tmp_dir) / "config.yaml")

    def test_scope_without_override_follows_global(self):
        with TemporaryDirectory() as tmp_dir:
            manager = self._manager(tmp_dir)
            manager.set_view_mode("cover")
            resolved = manager.get_display_settings("SFC")
            self.assertEqual(resolved["view_mode"], "cover")
            self.assertFalse(manager.has_scope_override("SFC"))

    def test_scope_override_wins_and_persists(self):
        with TemporaryDirectory() as tmp_dir:
            cfg_path = Path(tmp_dir) / "config.yaml"
            manager = ConfigManager(config_file=cfg_path)
            manager.set_view_mode("cover")  # global
            manager.enable_scope_override("SFC")
            manager.set_scope_display("SFC", "view_mode", "cartridge")

            reloaded = ConfigManager(config_file=cfg_path)
            self.assertTrue(reloaded.has_scope_override("SFC"))
            self.assertEqual(reloaded.get_display_settings("SFC")["view_mode"], "cartridge")
            # Another console with no override still follows global.
            self.assertEqual(reloaded.get_display_settings("MD")["view_mode"], "cover")

    def test_clear_override_returns_to_global(self):
        with TemporaryDirectory() as tmp_dir:
            manager = self._manager(tmp_dir)
            manager.set_view_mode("list")
            manager.set_scope_display("__favorites__", "view_mode", "cover")
            self.assertEqual(manager.get_display_settings("__favorites__")["view_mode"], "cover")
            manager.clear_scope_override("__favorites__")
            self.assertFalse(manager.has_scope_override("__favorites__"))
            self.assertEqual(manager.get_display_settings("__favorites__")["view_mode"], "list")

    def test_changing_global_does_not_disturb_a_scoped_page(self):
        with TemporaryDirectory() as tmp_dir:
            manager = self._manager(tmp_dir)
            manager.set_scope_display("SFC", "view_mode", "list")
            manager.set_view_mode("cover")  # global changes
            self.assertEqual(manager.get_display_settings("SFC")["view_mode"], "list")
            self.assertEqual(manager.get_display_settings("MD")["view_mode"], "cover")

    def test_partial_override_leaves_other_keys_on_global(self):
        with TemporaryDirectory() as tmp_dir:
            manager = self._manager(tmp_dir)
            manager.set_sort_order("name_desc")  # global
            manager.set_scope_display("SFC", "view_mode", "cover")
            resolved = manager.get_display_settings("SFC")
            self.assertEqual(resolved["view_mode"], "cover")
            self.assertEqual(resolved["sort_order"], "name_desc")


if __name__ == "__main__":
    unittest.main()
