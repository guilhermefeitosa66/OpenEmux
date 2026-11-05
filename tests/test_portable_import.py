"""Importing an installed OpenEmux's data into a portable folder (issue #768).

Driven on Linux with the platform flag faked, like ``test_portable``: a fake
portable root with its marker, and a fake profile under a fake home.
"""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

import yaml

from openemux.core import paths, portable_import as pi
from openemux.core.config import ConfigManager
from tests.test_portable import _PortableCase


class _ImportCase(_PortableCase):
    def setUp(self):
        super().setUp()
        holder = TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.home = Path(holder.name).resolve()
        patcher = patch("pathlib.Path.home", return_value=self.home)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.profile = self.home / ".openemux"
        self.profile_roms = self.home / "games" / "roms"
        self.target = self.data / "openemux"
        self.target_roms = self.data / "roms"

    def make_profile(self, roms=False):
        """A profile with a library, settings, a save state and transient dirs."""
        rom = self.profile_roms / "SFC" / "game.sfc"
        outside = self.home / "elsewhere" / "MD" / "sonic.md"
        for path in (rom, outside):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"rom")
        (self.profile_roms / "covers" / "SFC").mkdir(parents=True)
        (self.profile_roms / "covers" / "SFC" / "game.png").write_bytes(b"png")
        self.profile.mkdir(parents=True)
        config = {
            "roms_path": str(self.profile_roms),
            "library": {"playlists_dir": str(self.profile / "playlists")},
            "covers": {"dir": str(self.profile_roms / "covers")},
            "runtime": {"retroarch": {"updater": {"core_dir": None}}},
            "ui": {"theme": "dark"},
        }
        (self.profile / "config.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
        playlists = self.profile / "playlists"
        playlists.mkdir()
        (playlists / "SFC.list").write_text(f"{rom}\n\n", encoding="utf-8")
        (playlists / "FAVORITES.list").write_text(f"{rom}\n{outside}\n", encoding="utf-8")
        (self.profile / "states" / "SFC").mkdir(parents=True)
        (self.profile / "states" / "SFC" / "game.state").write_bytes(b"state")
        (self.profile / "bios").mkdir()
        (self.profile / "runtime").mkdir()
        (self.profile / "runtime" / "openemux_startup.log").write_text("log")
        (self.profile / "cache" / "cartridges").mkdir(parents=True)
        (self.profile / "cores.config").write_text(
            yaml.safe_dump({"rom_overrides": {str(rom): "snes9x", str(outside): "gpgx"}})
        )
        (self.profile / "play_history.json").write_text(
            json.dumps({str(rom): {"play_count": 2}})
        )
        self.rom, self.outside = rom, outside
        return config

    def snapshot(self, folder):
        return {
            str(p.relative_to(folder)): p.read_bytes()
            for p in sorted(Path(folder).rglob("*"))
            if p.is_file()
        }


class DetectionTests(_ImportCase):
    def test_a_profile_with_a_config_is_importable(self):
        self.make_profile()
        self.assertEqual(pi.importable_profile(), self.profile)
        self.assertEqual(pi.profile_roms_folder(), self.profile_roms)

    def test_a_profile_without_config_yaml_is_not(self):
        self.profile.mkdir()
        self.assertIsNone(pi.importable_profile())
        self.assertIsNone(pi.profile_roms_folder())

    def test_nothing_is_importable_off_a_portable_install(self):
        self.make_profile()
        with patch.object(paths, "IS_WINDOWS", False):
            self.assertIsNone(pi.importable_profile())
            self.assertIsNone(pi.profile_roms_folder())
            self.assertIsNone(pi.plan_import())
            self.assertIsNone(pi.staging_dir())
            self.assertIsNone(pi.apply_pending_import())

    def test_the_offer_needs_a_profile_a_pending_first_boot_and_no_dismissal(self):
        manager = MagicMock()
        manager.bootstrap_needs_run.return_value = True
        manager.get_portable_import_dismissed.return_value = False
        self.assertFalse(pi.should_offer_on_first_start(manager))
        self.make_profile()
        self.assertTrue(pi.should_offer_on_first_start(manager))
        manager.get_portable_import_dismissed.return_value = True
        self.assertFalse(pi.should_offer_on_first_start(manager))
        manager.get_portable_import_dismissed.return_value = False
        manager.bootstrap_needs_run.return_value = False
        self.assertFalse(pi.should_offer_on_first_start(manager))


class PlanTests(_ImportCase):
    def test_the_plan_skips_transient_dirs_and_the_rom_folder_unless_asked(self):
        self.make_profile()
        plan = pi.plan_import()
        targets = {str(rel) for _src, rel in plan.files}
        self.assertIn("openemux/config.yaml", targets)
        self.assertIn("openemux/states/SFC/game.state", targets)
        self.assertFalse(any("runtime" in t or "cache" in t for t in targets))
        self.assertFalse(any(t.startswith("roms") for t in targets))
        self.assertIn(Path("openemux/bios"), plan.dirs)
        self.assertIsNone(plan.roms_source)
        self.assertEqual(plan.total_bytes, sum(src.stat().st_size for src, _ in plan.files))

    def test_the_rom_folder_comes_along_with_its_covers_when_asked(self):
        self.make_profile()
        plan = pi.plan_import(include_roms=True)
        targets = {str(rel) for _src, rel in plan.files}
        self.assertIn("roms/SFC/game.sfc", targets)
        self.assertIn("roms/covers/SFC/game.png", targets)
        self.assertEqual(plan.roms_source, self.profile_roms)

    def test_symlinks_are_neither_followed_nor_copied(self):
        self.make_profile()
        (self.profile / "link.cfg").symlink_to(self.outside)
        (self.profile / "linked").symlink_to(self.outside.parent, target_is_directory=True)
        (self.profile / "fifo").mkdir()
        targets = {str(rel) for _src, rel in pi.plan_import().files}
        self.assertNotIn("openemux/link.cfg", targets)
        self.assertFalse(any("linked" in t for t in targets))

    def test_folder_size_counts_regular_files(self):
        self.make_profile()
        self.assertEqual(pi.folder_size(self.profile_roms), 3 + 3)

    def test_not_enough_space_is_refused_with_the_numbers(self):
        self.make_profile()
        plan = pi.plan_import()
        usage = MagicMock(free=10)
        with patch.object(pi.shutil, "disk_usage", return_value=usage):
            with self.assertRaises(pi.PortableImportError) as caught:
                pi.run_import(plan)
        self.assertEqual(caught.exception.reason, "no_space")
        self.assertEqual(caught.exception.free, 10)
        self.assertEqual(caught.exception.needed, plan.total_bytes + pi.SPACE_MARGIN)
        self.assertFalse(pi.staging_dir().exists())


class RunImportTests(_ImportCase):
    def test_the_copy_is_staged_with_a_manifest_and_the_profile_is_untouched(self):
        self.make_profile()
        before = self.snapshot(self.home)
        progress = []
        pi.run_import(pi.plan_import(), lambda copied, total: progress.append((copied, total)))
        staging = pi.staging_dir()
        self.assertTrue((staging / pi.MANIFEST).is_file())
        manifest = json.loads((staging / pi.MANIFEST).read_text())
        self.assertEqual(manifest["config_source"], str(self.profile))
        self.assertIsNone(manifest["roms_source"])
        self.assertEqual(
            (staging / "openemux" / "states" / "SFC" / "game.state").read_bytes(), b"state"
        )
        self.assertTrue((staging / "openemux" / "bios").is_dir())
        self.assertEqual(progress[-1][0], progress[-1][1])
        self.assertEqual(self.snapshot(self.home), before)

    def test_a_rerun_replaces_an_older_staging(self):
        self.make_profile()
        stale = pi.staging_dir() / "stale"
        stale.mkdir(parents=True)
        pi.run_import(pi.plan_import())
        self.assertFalse(stale.exists())

    def test_a_failure_mid_copy_leaves_no_staging(self):
        self.make_profile()
        with patch.object(pi.shutil, "copy2", side_effect=OSError("disk full")):
            with self.assertRaises(pi.PortableImportError) as caught:
                pi.run_import(pi.plan_import())
        self.assertEqual(caught.exception.reason, "failed")
        self.assertIn("disk full", str(caught.exception))
        self.assertFalse(pi.staging_dir().exists())

    def test_a_failure_before_the_manifest_leaves_no_staging(self):
        self.make_profile()
        with patch.object(pi, "rewrite_paths", side_effect=ValueError("bad")):
            with self.assertRaises(pi.PortableImportError):
                pi.run_import(pi.plan_import())
        self.assertFalse(pi.staging_dir().exists())


class RewriteTests(_ImportCase):
    def staged(self, include_roms=False):
        self.make_profile()
        pi.run_import(pi.plan_import(include_roms))
        return pi.staging_dir() / "openemux"

    def test_paths_into_the_profile_become_relative_to_the_portable_folder(self):
        staged = self.staged()
        config = yaml.safe_load((staged / "config.yaml").read_text())
        self.assertEqual(config["library"]["playlists_dir"], "data/openemux/playlists")
        # The ROM folder was not copied: it is still where it was.
        self.assertEqual(config["roms_path"], str(self.profile_roms))
        self.assertEqual(config["covers"]["dir"], str(self.profile_roms / "covers"))
        self.assertIsNone(config["runtime"]["retroarch"]["updater"]["core_dir"])
        self.assertEqual(config["ui"]["theme"], "dark")
        favorites = (staged / "playlists" / "FAVORITES.list").read_text().split()
        self.assertEqual(favorites, [str(self.rom), str(self.outside)])

    def test_with_the_rom_folder_its_paths_move_too(self):
        staged = self.staged(include_roms=True)
        config = yaml.safe_load((staged / "config.yaml").read_text())
        self.assertEqual(config["roms_path"], "data/roms")
        self.assertEqual(config["covers"]["dir"], "data/roms/covers")
        self.assertEqual(
            (staged / "playlists" / "SFC.list").read_text(), "data/roms/SFC/game.sfc\n"
        )
        favorites = (staged / "playlists" / "FAVORITES.list").read_text().split()
        self.assertEqual(favorites, ["data/roms/SFC/game.sfc", str(self.outside)])
        cores = yaml.safe_load((staged / "cores.config").read_text())["rom_overrides"]
        self.assertEqual(
            cores, {"data/roms/SFC/game.sfc": "snes9x", str(self.outside): "gpgx"}
        )
        history = json.loads((staged / "play_history.json").read_text())
        self.assertEqual(history, {"data/roms/SFC/game.sfc": {"play_count": 2}})

    def test_the_imported_library_loads_after_the_swap(self):
        self.staged(include_roms=True)
        self.assertEqual(pi.apply_pending_import(), "applied")
        manager = ConfigManager(config_file=self.target / "config.yaml")
        self.assertEqual(Path(manager.get_roms_path()), self.target_roms)
        self.assertEqual(manager.get_playlists_dir(), self.target / "playlists")

    def test_remap_matches_whole_components_only(self):
        mapping = [(self.profile, self.target)]
        sibling = str(self.home / ".openemux2" / "x")
        self.assertEqual(pi.remap_path(sibling, mapping), sibling)
        self.assertEqual(pi.remap_path(str(self.home), mapping), str(self.home))
        self.assertEqual(pi.remap_path("relative/x", mapping), "relative/x")
        self.assertEqual(pi.remap_path("", mapping), "")
        self.assertIsNone(pi.remap_path(None, mapping))
        self.assertEqual(
            pi.remap_path(str(self.profile / "a"), mapping), "data/openemux/a"
        )

    def test_remap_ignores_case_on_windows_only(self):
        mapping = [(self.profile, self.target)]
        shouting = str(self.home / ".OPENEMUX" / "a")
        self.assertEqual(pi.remap_path(shouting, mapping), "data/openemux/a")
        with patch.object(paths, "IS_WINDOWS", False):
            self.assertEqual(pi.remap_path(shouting, mapping), shouting)

    def test_unreadable_or_odd_stores_are_left_as_they_are(self):
        folder = self.home / "odd"
        folder.mkdir()
        (folder / "config.yaml").write_text("[unclosed")
        (folder / "cores.config").write_text("- a list\n")
        (folder / "shaders.config").write_text(yaml.safe_dump({"rom_overrides": "x"}))
        (folder / "play_history.json").write_text("{not json")
        before = self.snapshot(folder)
        pi.rewrite_paths(folder, [(self.profile, self.target)])
        self.assertEqual(self.snapshot(folder), before)
        (folder / "play_history.json").write_text("[1]")
        pi.rewrite_paths(folder, [(self.profile, self.target)])
        self.assertEqual((folder / "play_history.json").read_text(), "[1]")

    def test_a_config_missing_a_section_keeps_the_rest(self):
        folder = self.home / "partial"
        folder.mkdir()
        (folder / "config.yaml").write_text(
            yaml.safe_dump({"library": "flat", "setup": "odd", "portable": "odd"})
        )
        pi.rewrite_paths(folder, [(self.profile, self.target)])
        self.assertEqual(
            yaml.safe_load((folder / "config.yaml").read_text()),
            {"library": "flat", "setup": "odd", "portable": {"import_offer_dismissed": True}},
        )

    def write_bootstrap(self, folder, bootstrap):
        folder.mkdir()
        (folder / "config.yaml").write_text(
            yaml.safe_dump({"setup": {"bootstrap": bootstrap}})
        )
        pi.rewrite_paths(folder, [(self.profile, self.target)])
        return yaml.safe_load((folder / "config.yaml").read_text())

    def test_the_first_boot_owes_the_retroarch_steps_again(self):
        # The zip's RetroArch ships with no cores: "done" would open a library
        # where nothing launches.
        config = self.write_bootstrap(
            self.home / "done",
            {
                "status": "done",
                "completed_steps": [
                    "openemux_config_files",
                    "retroarch_environment",
                    "retroarch_download_all_cores",
                ],
            },
        )
        bootstrap = config["setup"]["bootstrap"]
        self.assertEqual(bootstrap["status"], "pending")
        self.assertEqual(bootstrap["completed_steps"], ["openemux_config_files"])
        self.assertFalse(bootstrap["retry_requested"])
        # Pending again, but the copy never asks to import a second time.
        self.assertTrue(config["portable"]["import_offer_dismissed"])

    def test_a_bootstrap_with_no_step_list_is_still_reopened(self):
        config = self.write_bootstrap(self.home / "bare", {"status": "done"})
        self.assertEqual(config["setup"]["bootstrap"]["status"], "pending")
        self.assertNotIn("completed_steps", config["setup"]["bootstrap"])


class ApplyTests(_ImportCase):
    def stage(self, include_roms=False):
        self.make_profile()
        pi.run_import(pi.plan_import(include_roms))

    def test_nothing_staged_is_nothing_to_do(self):
        self.assertIsNone(pi.apply_pending_import())

    def test_the_staged_copy_replaces_the_folder_and_keeps_a_backup_once(self):
        self.target.mkdir(parents=True)
        (self.target / "config.yaml").write_text("old: true\n")
        self.target_roms.mkdir()
        self.stage(include_roms=True)
        self.assertEqual(pi.apply_pending_import(), "applied")
        self.assertFalse(pi.staging_dir().exists())
        self.assertIn("dark", (self.target / "config.yaml").read_text())
        self.assertTrue((self.target_roms / "SFC" / "game.sfc").is_file())
        backup = self.data / ("openemux" + pi.BACKUP_SUFFIX)
        self.assertEqual((backup / "config.yaml").read_text(), "old: true\n")
        self.assertTrue((self.data / ("roms" + pi.BACKUP_SUFFIX)).is_dir())
        self.assertTrue((self.target / pi.DONE_MARKER).is_file())
        # The next start: the import worked, the backups go.
        self.assertIsNone(pi.apply_pending_import())
        self.assertFalse(backup.exists())
        self.assertFalse((self.data / ("roms" + pi.BACKUP_SUFFIX)).exists())
        self.assertFalse((self.target / pi.DONE_MARKER).exists())

    def test_an_older_backup_is_replaced(self):
        old_backup = self.data / ("openemux" + pi.BACKUP_SUFFIX)
        old_backup.mkdir(parents=True)
        (old_backup / "older").write_text("x")
        self.target.mkdir(parents=True)
        self.stage()
        self.assertEqual(pi.apply_pending_import(), "applied")
        self.assertFalse((old_backup / "older").exists())

    def test_a_staging_without_manifest_is_thrown_away(self):
        self.target.mkdir(parents=True)
        (self.target / "config.yaml").write_text("old: true\n")
        self.stage()
        (pi.staging_dir() / pi.MANIFEST).unlink()
        self.assertEqual(pi.apply_pending_import(), "discarded")
        self.assertFalse(pi.staging_dir().exists())
        self.assertEqual((self.target / "config.yaml").read_text(), "old: true\n")

    def test_a_refused_rename_puts_everything_back_and_keeps_the_staging(self):
        self.target.mkdir(parents=True)
        (self.target / "config.yaml").write_text("old: true\n")
        self.target_roms.mkdir()
        (self.target_roms / "mine.sfc").write_text("x")
        self.stage(include_roms=True)
        real_rename = Path.rename
        staged_roms = pi.staging_dir() / "roms"

        def rename(path, target):
            if Path(path) == staged_roms and Path(target) == self.target_roms:
                raise PermissionError("in use")
            return real_rename(path, target)

        with patch.object(Path, "rename", rename):
            self.assertEqual(pi.apply_pending_import(), "failed")
        self.assertEqual((self.target / "config.yaml").read_text(), "old: true\n")
        self.assertTrue((self.target_roms / "mine.sfc").is_file())
        self.assertTrue((pi.staging_dir() / pi.MANIFEST).is_file())
        self.assertTrue((pi.staging_dir() / "openemux").is_dir())
        self.assertTrue(staged_roms.is_dir())
        self.assertFalse((self.data / ("openemux" + pi.BACKUP_SUFFIX)).exists())
        # Retried, and done, on the next start.
        self.assertEqual(pi.apply_pending_import(), "applied")

    def test_a_refused_second_rename_on_a_fresh_folder_undoes_the_first(self):
        self.stage(include_roms=True)
        real_rename = Path.rename
        staged_roms = pi.staging_dir() / "roms"

        def rename(path, target):
            if Path(path) == staged_roms:
                raise PermissionError("in use")
            return real_rename(path, target)

        with patch.object(Path, "rename", rename):
            self.assertEqual(pi.apply_pending_import(), "failed")
        self.assertFalse(self.target.exists())
        self.assertTrue((pi.staging_dir() / "openemux" / "config.yaml").is_file())

    def test_a_refused_first_rename_with_no_folder_yet_changes_nothing(self):
        self.stage()
        with patch.object(Path, "rename", side_effect=PermissionError("in use")):
            self.assertEqual(pi.apply_pending_import(), "failed")
        self.assertFalse(self.target.exists())
        self.assertTrue((pi.staging_dir() / pi.MANIFEST).is_file())


class ConfigFlagTests(unittest.TestCase):
    def test_the_dismissal_is_remembered_and_absent_by_default(self):
        with TemporaryDirectory() as tmp:
            config_file = Path(tmp) / "config.yaml"
            manager = ConfigManager(config_file=config_file)
            self.assertFalse(manager.get_portable_import_dismissed())
            self.assertNotIn("portable", yaml.safe_load(config_file.read_text()))
            manager.config["portable"] = "broken"
            self.assertFalse(manager.get_portable_import_dismissed())
            manager.set_portable_import_dismissed(True)
            again = ConfigManager(config_file=config_file)
            self.assertTrue(again.get_portable_import_dismissed())
            again.set_portable_import_dismissed(False)
            self.assertFalse(ConfigManager(config_file=config_file).get_portable_import_dismissed())


class ProfilePathTests(unittest.TestCase):
    def test_the_profile_paths_are_the_installer_defaults(self):
        with patch("pathlib.Path.home", return_value=Path("/h")), patch.object(
            paths, "is_running_in_flatpak", return_value=False
        ):
            self.assertEqual(paths.profile_config_dir(), Path("/h/.openemux"))
            self.assertEqual(paths.profile_roms_dir(), Path("/h/games/roms"))


if __name__ == "__main__":
    unittest.main()
