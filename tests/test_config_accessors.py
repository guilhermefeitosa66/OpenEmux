"""The `ConfigManager` accessors the rest of the suite never happened to ask for.

`config.py` is covered by a `test_config_<concern>.py` family, and between them
they left 79 statements: a dozen plain getters nothing had needed, the
normalising each setter does on the way in, and -- the substantial part -- the
one-time library migration that renames the pre-1.0 console directories and the
tree move underneath it.

Everything runs against a throwaway config directory; nothing here reads or
writes the developer's own `~/.openemux`.
"""

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from openemux.core import config as config_module
from openemux.core.config import (
    DEFAULT_UPDATE_TIMEOUT,
    MIGRATION_VERSION,
    ConfigManager,
    normalize_artwork_providers,
)
from openemux.core.systems import LEGACY_ID_MAP, SYSTEM_IDS
from tests.platform_marks import posix_only


class _ConfigCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.config = ConfigManager(self.tmp / "config.yaml")


class NormalisingWhatWasStoredTests(unittest.TestCase):
    def test_a_provider_entry_that_is_not_a_mapping_is_dropped(self):
        # A hand-edited config, or one from a version that stored strings.
        providers = normalize_artwork_providers(["screenscraper", {"id": "libretro"}])
        self.assertTrue(all(isinstance(entry, dict) for entry in providers))
        self.assertIn("libretro", [entry["id"] for entry in providers])


class LoadingAConfigDocumentTests(_ConfigCase):
    """What a hand-edited or older config document is turned into."""

    def _reload(self, document):
        import yaml

        path = self.tmp / "hand-edited.yaml"
        path.write_text(yaml.safe_dump(document), encoding="utf-8")
        return ConfigManager(path).config

    def test_a_console_list_with_nothing_the_app_knows_falls_back_to_all(self):
        loaded = self._reload({"consoles": ["NOT-A-CONSOLE"]})
        self.assertEqual(loaded["consoles"], list(SYSTEM_IDS))

    def test_a_console_list_is_resolved_to_the_canonical_ids(self):
        loaded = self._reload({"consoles": ["SNES"]})
        self.assertEqual(loaded["consoles"], ["SFC"])

    def test_a_completed_step_list_of_the_wrong_shape_is_reset(self):
        loaded = self._reload(
            {"setup": {"bootstrap": {"completed_steps": "not a list"}}}
        )
        self.assertEqual(loaded["setup"]["bootstrap"]["completed_steps"], [])


class WhereTheArtworkLivesTests(_ConfigCase):
    def test_covers_follow_the_rom_library_by_default(self):
        self.assertEqual(self.config.get_covers_dir(), self.config.get_roms_path())

    def test_a_covers_directory_of_its_own_is_honoured(self):
        self.config.config.setdefault("covers", {})["dir"] = "/somewhere/covers"
        self.assertEqual(self.config.get_covers_dir(), Path("/somewhere/covers"))

    def test_the_cover_source_is_normalised_on_the_way_in(self):
        self.config.set_cover_sync_setting("cover_source", "NONSENSE")
        self.assertEqual(
            self.config.get_cover_sync_settings()["cover_source"],
            config_module.DEFAULT_COVER_SOURCE,
        )

    def test_the_artwork_type_is_normalised_on_the_way_in(self):
        self.config.set_cover_sync_setting("cover_art_type", "NONSENSE")
        self.assertEqual(
            self.config.get_cover_sync_settings()["cover_art_type"],
            config_module.DEFAULT_COVER_ART_TYPE,
        )

    def test_any_other_setting_is_stored_as_it_arrives(self):
        self.config.set_cover_sync_setting("screenscraper_user", "player1")
        self.assertEqual(
            self.config.get_cover_sync_settings()["screenscraper_user"], "player1"
        )


class TheUpdateSettingsTests(_ConfigCase):
    def test_a_timeout_that_is_not_a_number_falls_back_to_the_default(self):
        self.config.config.setdefault("updates", {})["timeout_seconds"] = "soon"
        self.assertEqual(
            self.config.get_update_settings()["timeout_seconds"], DEFAULT_UPDATE_TIMEOUT
        )

    def test_a_timeout_the_user_set_is_used(self):
        self.config.config.setdefault("updates", {})["timeout_seconds"] = 30
        self.assertEqual(self.config.get_update_settings()["timeout_seconds"], 30)


class TheLibraryLayoutSettingsTests(_ConfigCase):
    def test_the_sort_order_is_normalised_on_the_way_out(self):
        self.config.config.setdefault("ui", {})["sort_order"] = "nonsense"
        self.assertEqual(
            self.config.get_sort_order(), config_module.normalize_sort_order(None)
        )

    def test_a_scope_override_of_the_wrong_shape_is_ignored(self):
        self.config.config.setdefault("ui", {})["scope_overrides"] = {"SFC": "nonsense"}
        self.assertEqual(self.config.get_scope_overrides(), {})

    def test_a_display_key_the_app_does_not_know_is_never_stored(self):
        self.config.set_scope_display("SFC", "not-a-key", "value")
        self.assertEqual(self.config.get_scope_overrides(), {})

    def test_the_first_open_scan_is_on_unless_it_was_turned_off(self):
        self.assertTrue(self.config.auto_scan_on_first_open())
        self.config.config.setdefault("library", {})["auto_scan_on_first_open"] = False
        self.assertFalse(self.config.auto_scan_on_first_open())

    def test_the_playlists_and_input_directories_are_reported(self):
        self.assertTrue(str(self.config.get_playlists_dir()))
        self.assertTrue(str(self.config.get_input_dir()))


class TheRuntimeSettingsTests(_ConfigCase):
    def test_the_default_backend_is_the_retroarch_wrapper(self):
        self.assertEqual(self.config.get_runtime_mode(), "retroarch_wrapper")

    def test_a_console_falls_back_to_the_global_backend(self):
        self.assertEqual(
            self.config.get_runtime_mode_for_console("SFC"), "retroarch_wrapper"
        )

    def test_a_console_with_a_backend_of_its_own_uses_it(self):
        runtime = self.config.config.setdefault("runtime", {})
        runtime["console_backend"] = {"SFC": "embedded"}
        self.assertEqual(self.config.get_runtime_mode_for_console("SNES"), "embedded")

    def test_the_master_volume_is_clamped_to_the_range_retroarch_accepts(self):
        self.config.set_master_volume_db(9999)
        self.assertLess(self.config.get_master_volume_db(), 9999)

    def test_the_extra_retroarch_flags_default_to_none_at_all(self):
        self.assertEqual(self.config.get_retroarch_extra_flags(), [])

    def test_the_audio_and_video_drivers_are_reported_raw(self):
        retroarch = self.config.config.setdefault("runtime", {}).setdefault(
            "retroarch", {}
        )
        retroarch["audio_driver"] = "pulse"
        retroarch["video_driver"] = "gl"
        self.assertEqual(self.config.get_retroarch_audio_driver(), "pulse")
        self.assertEqual(self.config.get_retroarch_video_driver(), "gl")

    def test_a_core_override_for_a_console_the_app_does_not_know_is_refused(self):
        self.config.set_console_core_override("NOT-A-CONSOLE", "x_libretro.so")
        cores = self.config.config["runtime"]["retroarch"]["cores"]
        self.assertNotIn("NOT-A-CONSOLE", cores)

    def test_the_import_mode_is_reported(self):
        self.assertTrue(self.config.get_import_mode())

    def test_a_console_with_no_controls_profile_reports_an_empty_one(self):
        self.assertEqual(self.config.get_controls_profile("SFC"), {})


class TheDelegatedStoresTests(_ConfigCase):
    def test_the_shader_store_is_reachable_through_the_manager(self):
        self.assertEqual(
            self.config.get_shaders_config_file(), self.config.shaders.config_file
        )
        self.assertTrue(isinstance(self.config.get_shader_settings(), dict))

    def test_a_roms_effective_shader_comes_from_the_shader_store(self):
        self.config.set_shader_for_console("SFC", "crt")
        self.assertEqual(self.config.get_shader_for_rom("/roms/a.sfc", "SFC"), "crt")

    def test_a_console_cartridge_colour_round_trips(self):
        self.config.set_cartridge_color_for_console("SFC", "black")
        self.assertEqual(self.config.get_cartridge_color_for_console("SFC"), "black")


class TheBootstrapLedgerTests(_ConfigCase):
    def test_a_completed_step_is_recorded_once(self):
        self.config.mark_bootstrap_step_completed("playlists_seed")
        self.config.mark_bootstrap_step_completed("playlists_seed")
        self.assertEqual(
            self.config.get_bootstrap_state()["completed_steps"], ["playlists_seed"]
        )


@posix_only("directory permissions decide whether the layout can be created")
class CreatingTheLibraryLayoutTests(_ConfigCase):
    def test_a_migration_that_cannot_run_is_reported_not_raised(self):
        with mock.patch.object(
            ConfigManager,
            "_run_library_migration_if_needed",
            side_effect=OSError("read-only"),
        ):
            failed = self.config.ensure_rom_directories()
        self.assertIn(self.config.get_roms_path(), failed)

    def test_input_profiles_that_cannot_be_seeded_are_reported_not_raised(self):
        with mock.patch.object(
            ConfigManager, "ensure_input_profiles", side_effect=OSError("read-only")
        ):
            self.config.ensure_rom_directories()

    def test_an_unwritable_library_is_named_in_the_log(self):
        with mock.patch.object(
            config_module, "_try_mkdir", side_effect=lambda path, failed: failed.append(path)
        ):
            with self.assertLogs("openemux.core.config", level="WARNING"):
                failed = self.config.ensure_rom_directories()
        self.assertTrue(failed)


@posix_only("the pre-1.0 library layout this renames")
class TheLegacyLibraryMigrationTests(_ConfigCase):
    """One-time, and it keeps a copy of everything it touches."""

    def setUp(self):
        super().setUp()
        self.roms = self.tmp / "roms"
        self.playlists = self.tmp / "playlists"
        self.playlists.mkdir(parents=True)
        self.config.config["roms_path"] = str(self.roms)
        self.config.config.setdefault("library", {})["playlists_dir"] = str(
            self.playlists
        )
        self.old_id, self.new_id = next(iter(LEGACY_ID_MAP.items()))
        self.old_id = self.old_id.lower()

    def migrate(self):
        self.config._run_library_migration_if_needed(self.roms)

    def test_a_library_already_migrated_is_left_alone(self):
        self.config.config["library"]["migration"] = {"version": MIGRATION_VERSION}
        (self.playlists / f"{self.old_id}.list").write_text("x", encoding="utf-8")
        self.migrate()
        self.assertTrue((self.playlists / f"{self.old_id}.list").exists())
        self.assertFalse((self.playlists / f"{self.new_id}.list").exists())

    def test_an_old_playlist_is_copied_to_the_new_id_and_backed_up(self):
        (self.playlists / f"{self.old_id}.list").write_text("game", encoding="utf-8")
        self.migrate()
        self.assertTrue((self.playlists / f"{self.new_id}.list").exists())
        backups = list(self.playlists.glob("_migration_backup_*"))
        self.assertEqual(len(backups), 1)
        self.assertTrue((backups[0] / f"{self.old_id}.list").exists())

    def test_a_new_playlist_that_already_exists_is_not_overwritten(self):
        (self.playlists / f"{self.old_id}.list").write_text("old", encoding="utf-8")
        (self.playlists / f"{self.new_id}.list").write_text("new", encoding="utf-8")
        self.migrate()
        self.assertEqual(
            (self.playlists / f"{self.new_id}.list").read_text(encoding="utf-8"), "new"
        )

    def test_the_roms_move_to_the_new_console_directory(self):
        old_dir = self.roms / self.old_id
        (old_dir / "covers").mkdir(parents=True)
        (old_dir / "bios").mkdir(parents=True)
        (old_dir / "Game.rom").write_bytes(b"rom")
        (old_dir / "covers" / "Game.png").write_bytes(b"png")
        (old_dir / "bios" / "bios.bin").write_bytes(b"bios")
        self.migrate()
        new_dir = self.roms / self.new_id
        self.assertTrue((new_dir / "Game.rom").is_file())
        self.assertTrue((new_dir / "covers" / "Game.png").is_file())
        self.assertTrue((new_dir / "bios" / "bios.bin").is_file())
        self.assertFalse(old_dir.exists())

    def test_covers_kept_in_the_old_shared_folder_move_too(self):
        legacy = self.roms / "covers" / self.old_id
        legacy.mkdir(parents=True)
        (legacy / "Game.png").write_bytes(b"png")
        self.migrate()
        self.assertTrue(
            (self.roms / self.new_id / "covers" / "Game.png").is_file()
        )

    def test_the_migration_records_that_it_ran(self):
        self.migrate()
        self.assertEqual(
            self.config.config["library"]["migration"]["version"], MIGRATION_VERSION
        )


@posix_only("moving a directory tree between two paths")
class MovingATreeTests(_ConfigCase):
    def setUp(self):
        super().setUp()
        self.src = self.tmp / "src"
        self.dst = self.tmp / "dst"

    def move(self, **kwargs):
        self.config._move_tree_contents(self.src, self.dst, **kwargs)

    def test_a_source_that_is_not_there_moves_nothing(self):
        self.move()
        self.assertFalse(self.dst.exists())

    def test_a_source_that_is_a_file_moves_nothing(self):
        self.src.write_bytes(b"x")
        self.move()
        self.assertFalse(self.dst.exists())

    def test_every_entry_is_moved_across(self):
        self.src.mkdir()
        (self.src / "a.rom").write_bytes(b"a")
        (self.src / "sub").mkdir()
        (self.src / "sub" / "b.rom").write_bytes(b"b")
        self.move()
        self.assertTrue((self.dst / "a.rom").is_file())
        self.assertTrue((self.dst / "sub" / "b.rom").is_file())

    def test_a_skipped_directory_stays_where_it_is(self):
        self.src.mkdir()
        (self.src / "covers").mkdir()
        (self.src / "covers" / "a.png").write_bytes(b"a")
        self.move(skip_dirs={"covers"})
        self.assertFalse((self.dst / "covers").exists())
        self.assertTrue((self.src / "covers" / "a.png").is_file())

    def test_a_file_that_is_already_there_is_never_overwritten(self):
        self.src.mkdir()
        self.dst.mkdir()
        (self.src / "a.rom").write_bytes(b"old")
        (self.dst / "a.rom").write_bytes(b"new")
        self.move()
        self.assertEqual((self.dst / "a.rom").read_bytes(), b"new")

    def test_a_directory_that_is_already_there_is_merged_into(self):
        self.src.mkdir()
        self.dst.mkdir()
        (self.src / "sub").mkdir()
        (self.src / "sub" / "a.rom").write_bytes(b"a")
        (self.dst / "sub").mkdir()
        self.move()
        self.assertTrue((self.dst / "sub" / "a.rom").is_file())
        self.assertFalse((self.src / "sub").exists())


@posix_only("removing an emptied directory tree")
class RemovingAnEmptiedTreeTests(_ConfigCase):
    def test_a_path_that_is_not_there_is_nothing_to_remove(self):
        self.config._remove_empty_tree(self.tmp / "gone")

    def test_a_file_is_never_removed_as_a_tree(self):
        path = self.tmp / "a.rom"
        path.write_bytes(b"x")
        self.config._remove_empty_tree(path)
        self.assertTrue(path.exists())

    def test_an_empty_tree_is_removed_from_the_leaves_up(self):
        deep = self.tmp / "a" / "b" / "c"
        deep.mkdir(parents=True)
        self.config._remove_empty_tree(self.tmp / "a")
        self.assertFalse((self.tmp / "a").exists())

    def test_a_tree_that_still_holds_something_is_kept(self):
        deep = self.tmp / "a" / "b"
        deep.mkdir(parents=True)
        (deep / "keep.rom").write_bytes(b"x")
        self.config._remove_empty_tree(self.tmp / "a")
        self.assertTrue((deep / "keep.rom").is_file())


if __name__ == "__main__":
    unittest.main()
