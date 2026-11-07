"""Portable paths survive the folder moving (issue #767).

A USB stick gets whatever drive letter Windows hands it, so a portable install
stores every path inside its folder relative to it and resolves it against
wherever the folder is today. Driven on Linux with the platform flag faked, as
``test_portable`` drives the rest of the portable mode.
"""

import os
import shutil
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import yaml

from openemux.core import paths
from openemux.core.atomic_write import atomic_write_lines
from openemux.core.cartridge_colors import CartridgeColorStore
from openemux.core.collections import CollectionManager
from openemux.core.config import ConfigManager, loaded_config, stored_config
from openemux.core.cores import CoreConfigStore
from openemux.core.play_history import PlayHistory
from openemux.core.playlist_manager import PlaylistManager
from openemux.core.scanner import RomScanner
from openemux.core.shaders import ShaderConfigStore
from tests.test_portable import _PortableCase


class _MovableCase(_PortableCase):
    """A portable folder that can be moved to another place mid-test."""

    def setUp(self):
        super().setUp()
        self.roms = self.data / "roms"
        self.config_dir = self.data / "openemux"
        self.config_dir.mkdir(parents=True)

    def rom(self, console="SFC", name="game.sfc", root=None):
        path = (root or self.root) / paths.PORTABLE_DATA_DIR / "roms" / console / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"rom")
        return path

    def move(self):
        """Copy the folder elsewhere and drop the old one, like a new drive letter."""
        holder = TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        new_root = Path(holder.name).resolve() / "OpenEmux"
        shutil.copytree(self.root, new_root)
        shutil.rmtree(self.root)
        patcher = patch.dict(os.environ, {"OPENEMUX_PROJECT_ROOT": str(new_root)})
        patcher.start()
        self.addCleanup(patcher.stop)
        paths._portable_root_at.cache_clear()
        old_root, self.root = self.root, new_root
        self.data = new_root / paths.PORTABLE_DATA_DIR
        self.config_dir = self.data / "openemux"
        return old_root


class StoredFormTests(_MovableCase):
    def test_a_path_inside_the_folder_is_stored_relative_with_forward_slashes(self):
        rom = self.roms / "SFC" / "game.sfc"
        self.assertEqual(paths.to_stored_path(rom), "data/roms/SFC/game.sfc")
        self.assertEqual(paths.to_stored_path(str(rom)), "data/roms/SFC/game.sfc")

    def test_the_folder_itself_is_stored_as_a_dot(self):
        self.assertEqual(paths.to_stored_path(self.root), ".")
        self.assertEqual(paths.from_stored_path("."), str(self.root))

    def test_a_path_outside_the_folder_stays_absolute(self):
        with TemporaryDirectory() as other:
            rom = Path(other) / "SFC" / "game.sfc"
            self.assertEqual(paths.to_stored_path(rom), str(rom))
            self.assertEqual(paths.from_stored_path(str(rom)), str(rom))

    def test_a_path_that_climbs_out_of_the_folder_stays_absolute(self):
        sneaky = self.root / "data" / ".." / ".." / "elsewhere"
        self.assertEqual(paths.to_stored_path(sneaky), str(sneaky))

    def test_relative_and_empty_values_are_written_as_they_are(self):
        self.assertEqual(paths.to_stored_path("data/roms"), "data/roms")
        self.assertEqual(paths.to_stored_path(""), "")
        self.assertEqual(paths.from_stored_path(""), "")
        self.assertIsNone(paths.from_stored_path(None))

    def test_a_relative_value_resolves_against_the_folder(self):
        self.assertEqual(
            paths.from_stored_path("data/roms/SFC/game.sfc"),
            str(self.roms / "SFC" / "game.sfc"),
        )

    def test_an_absolute_value_inside_the_folder_is_kept(self):
        rom = str(self.roms / "SFC" / "game.sfc")
        self.assertEqual(paths.from_stored_path(rom), rom)

    def test_keys_go_to_their_stored_form(self):
        rom = self.roms / "SFC" / "game.sfc"
        self.assertEqual(
            paths.with_stored_keys({str(rom): 1, "/elsewhere/x.sfc": 2}),
            {"data/roms/SFC/game.sfc": 1, "/elsewhere/x.sfc": 2},
        )


class NotPortableTests(unittest.TestCase):
    """The installer and Linux: the helpers change nothing at all."""

    def setUp(self):
        patcher = patch.object(paths, "IS_WINDOWS", False)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_paths_are_written_and_read_exactly_as_before(self):
        rom = Path("/roms/SFC/a.sfc")
        self.assertEqual(paths.to_stored_path(rom), str(rom))
        self.assertEqual(paths.from_stored_path("relative/a.sfc"), "relative/a.sfc")
        self.assertEqual(paths.with_stored_keys({"/roms/a.sfc": 1}), {"/roms/a.sfc": 1})

    def test_list_files_are_byte_for_byte_what_they_were(self):
        lines = ["/roms/SFC/b.sfc", "/roms/SFC/bad\udcffname.sfc"]
        with TemporaryDirectory() as tmp:
            before, after = Path(tmp) / "before.list", Path(tmp) / "after.list"
            atomic_write_lines(before, lines, errors=paths.PATH_ERRORS)
            paths.write_path_lines(after, lines)
            self.assertEqual(before.read_bytes(), after.read_bytes())
            self.assertEqual(paths.read_path_lines(after), lines)

    def test_a_fresh_config_yaml_is_byte_for_byte_what_it_was(self):
        with TemporaryDirectory() as tmp:
            manager = ConfigManager(Path(tmp) / "config.yaml")
            self.assertEqual(stored_config(manager.config), manager.config)
            self.assertEqual(loaded_config(manager.config), manager.config)
            self.assertEqual(
                yaml.safe_load((Path(tmp) / "config.yaml").read_text(encoding="utf-8")),
                manager.config,
            )


class RelocationTests(_MovableCase):
    """Absolute paths written before this change, by the first portable release."""

    def test_a_path_in_a_folder_that_is_gone_moves_to_the_current_one(self):
        rom = self.rom()
        old_root = self.move()
        moved = self.data / "roms" / "SFC" / "game.sfc"
        self.assertEqual(paths.from_stored_path(str(rom)), str(moved))
        self.assertTrue(str(rom).startswith(str(old_root)))

    def test_the_old_folder_still_there_is_left_alone(self):
        with TemporaryDirectory() as other:
            old = Path(other) / "data" / "roms" / "SFC" / "game.sfc"
            old.parent.mkdir(parents=True)
            self.rom()
            self.assertEqual(paths.from_stored_path(str(old)), str(old))

    def test_a_copy_made_with_the_original_still_plugged_in_follows_the_copy(self):
        with TemporaryDirectory() as other:
            original = Path(other) / "OpenEmux"
            old = original / "data" / "roms" / "SFC" / "game.sfc"
            old.parent.mkdir(parents=True)
            old.write_bytes(b"rom")
            (original / paths.PORTABLE_MARKER).write_text("portable\n", encoding="utf-8")
            rom = self.rom()
            self.assertEqual(paths.from_stored_path(str(old)), str(rom))

    def test_a_file_missing_from_the_current_folder_stays_where_it_was(self):
        stale = str(self.root.parent / "gone-drive" / "OpenEmux" / "data" / "roms" / "nothing.sfc")
        self.assertEqual(paths.from_stored_path(stale), stale)

    def test_a_path_with_no_data_folder_is_never_relocated(self):
        elsewhere = str(self.root.parent / "mnt" / "roms" / "a.sfc")
        with patch.object(Path, "exists") as exists:
            self.assertEqual(paths.from_stored_path(elsewhere), elsewhere)
        exists.assert_not_called()


class ListFileTests(_MovableCase):
    def test_lines_are_stored_relative_and_read_back_absolute(self):
        list_file = self.config_dir / "SFC.list"
        inside = str(self.roms / "SFC" / "a.sfc")
        outside = str(self.root.parent / "mnt" / "roms" / "SFC" / "b.sfc")
        paths.write_path_lines(list_file, [inside, outside])
        self.assertEqual(
            list_file.read_text(encoding="utf-8"), f"data/roms/SFC/a.sfc\n{outside}\n"
        )
        list_file.write_text(list_file.read_text(encoding="utf-8") + "\n  \n", encoding="utf-8")
        self.assertEqual(paths.read_path_lines(list_file), [inside, outside])


class ConfigYamlTests(_MovableCase):
    def manager(self):
        return ConfigManager(self.config_dir / "config.yaml")

    def raw(self):
        return yaml.safe_load((self.config_dir / "config.yaml").read_text(encoding="utf-8"))

    def test_paths_inside_the_folder_are_stored_relative(self):
        manager = self.manager()
        manager.set_roms_path(self.roms)
        manager.config["library"]["playlists_dir"] = str(self.config_dir / "playlists")
        manager.config["covers"]["dir"] = str(self.data / "covers")
        manager.save_config()
        raw = self.raw()
        self.assertEqual(raw["roms_path"], "data/roms")
        self.assertEqual(raw["library"]["playlists_dir"], "data/openemux/playlists")
        self.assertEqual(raw["covers"]["dir"], "data/covers")
        self.assertIsNone(raw["runtime"]["retroarch"]["updater"]["core_dir"])
        self.assertEqual(manager.get_roms_path(), self.roms)

    def test_the_settings_follow_the_folder_to_its_new_place(self):
        manager = self.manager()
        manager.set_roms_path(self.roms)
        manager.config["runtime"]["retroarch"]["updater"]["core_dir"] = str(self.data / "cores")
        manager.save_config()
        self.move()
        manager = self.manager()
        self.assertEqual(manager.get_roms_path(), self.data / "roms")
        self.assertEqual(
            manager.config["runtime"]["retroarch"]["updater"]["core_dir"], str(self.data / "cores")
        )

    def test_a_clean_start_does_not_rewrite_the_file(self):
        self.manager().set_roms_path(self.roms)
        with patch.object(ConfigManager, "save_config") as save:
            self.manager()
        save.assert_not_called()

    def test_a_config_from_the_first_portable_release_is_relocated_and_rewritten(self):
        self.manager().set_roms_path(self.roms)
        self.roms.mkdir(parents=True)
        old_root = self.move()
        path = self.config_dir / "config.yaml"
        raw = self.raw()
        raw["roms_path"] = str(old_root / "data" / "roms")
        path.write_text(yaml.safe_dump(raw), encoding="utf-8")
        manager = self.manager()
        self.assertEqual(manager.get_roms_path(), self.data / "roms")
        self.assertEqual(self.raw()["roms_path"], "data/roms")

    def test_a_section_that_is_not_a_mapping_is_left_alone(self):
        self.assertEqual(stored_config({"library": "oops"}), {"library": "oops"})
        self.assertEqual(stored_config({"roms_path": None}), {"roms_path": None})


class RomKeyedStoreTests(_MovableCase):
    def test_per_game_cores_shaders_and_colors_follow_the_folder(self):
        rom = self.rom()
        cores = CoreConfigStore(self.config_dir / "cores.config")
        shaders = ShaderConfigStore(self.config_dir / "shaders.config")
        colors = CartridgeColorStore(self.config_dir / "cartridge_colors.config")
        saved = cores.set_rom_core(rom, "snes9x_libretro.so")
        self.assertEqual(saved["rom_overrides"], {str(rom): "snes9x_libretro.so"})
        shaders.set_rom_shader(rom, "SFC", "crt_easymode")
        colors.set_rom_color(rom, "SFC", "black")
        for name in ("cores.config", "shaders.config", "cartridge_colors.config"):
            raw = yaml.safe_load((self.config_dir / name).read_text(encoding="utf-8"))
            self.assertEqual(list(raw["rom_overrides"]), ["data/roms/SFC/game.sfc"], name)

        self.move()
        moved = self.data / "roms" / "SFC" / "game.sfc"
        self.assertEqual(
            CoreConfigStore(self.config_dir / "cores.config").get_rom_core(moved),
            "snes9x_libretro.so",
        )
        self.assertEqual(
            ShaderConfigStore(self.config_dir / "shaders.config").get_rom_shader(moved),
            "crt_easymode",
        )
        self.assertEqual(
            CartridgeColorStore(self.config_dir / "cartridge_colors.config").get_rom_color(moved),
            "black",
        )

    def test_play_history_follows_the_folder(self):
        rom = self.rom()
        history = PlayHistory(self.config_dir / "play_history.json", clock=lambda: 100.0)
        history.record_launch(rom)
        raw = (self.config_dir / "play_history.json").read_text(encoding="utf-8")
        self.assertIn('"data/roms/SFC/game.sfc"', raw)
        self.move()
        history = PlayHistory(self.config_dir / "play_history.json")
        moved = self.data / "roms" / "SFC" / "game.sfc"
        self.assertEqual(history.last_played(moved), 100.0)
        self.assertEqual(history.play_count(moved), 1)


class LibraryListTests(_MovableCase):
    """Console playlists, favorites and collections."""

    def manager(self):
        config = ConfigManager(self.config_dir / "config.yaml")
        config.set_roms_path(self.data / "roms")
        config.config["library"]["playlists_dir"] = str(self.config_dir / "playlists")
        return PlaylistManager(config, RomScanner(self.data / "roms"))

    def test_the_library_favorites_and_collections_survive_a_move(self):
        rom = self.rom()
        manager = self.manager()
        manager.scan_and_rebuild_playlist("SFC")
        [entry] = manager.load_playlist("SFC")
        self.assertTrue(manager.toggle_favorite(entry))
        collections = CollectionManager(
            self.config_dir / "playlists" / "collections", manager.entries_for_paths
        )
        slug = collections.create("Best")
        collections.add(slug, [rom])
        playlists = self.config_dir / "playlists"
        for list_file in (
            playlists / "SFC.list",
            manager.get_favorites_playlist_path(),
            playlists / "collections" / f"{slug}.list",
        ):
            self.assertEqual(
                list_file.read_text(encoding="utf-8"), "data/roms/SFC/game.sfc\n", list_file
            )

        self.move()
        moved = str(self.data / "roms" / "SFC" / "game.sfc")
        manager = self.manager()
        self.assertEqual([e["path"] for e in manager.load_playlist("SFC")], [moved])
        self.assertTrue(manager.is_favorite(moved))
        self.assertEqual([e["path"] for e in manager.load_favorites_playlist()], [moved])
        collections = CollectionManager(
            self.config_dir / "playlists" / "collections", manager.entries_for_paths
        )
        self.assertTrue(collections.contains(slug, moved))
        self.assertEqual([e["path"] for e in collections.load_entries(slug)], [moved])


if __name__ == "__main__":
    unittest.main()
