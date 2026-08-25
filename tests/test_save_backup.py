"""Exporting and restoring saves (issue #293).

Save states live in OpenEmux's own tree; battery saves live next to the ROM,
because RetroArch's savefile_directory is left at its default. Both have to
come along, and an archive is untrusted input on the way back in.
"""

import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

from openemux.core import save_backup


class _Library:
    """A throwaway library with one SFC ROM, a state and a battery save."""

    def __init__(self, root):
        self.root = Path(root)
        self.roms = self.root / "roms"
        self.states = self.root / "states"
        (self.roms / "SFC").mkdir(parents=True)
        (self.states / "SFC").mkdir(parents=True)
        (self.roms / "SFC" / "Game.sfc").write_bytes(b"rom")
        (self.roms / "SFC" / "Game.srm").write_bytes(b"battery")
        (self.states / "SFC" / "Game.state").write_bytes(b"state0")


class BatterySaveDetectionTests(unittest.TestCase):
    def test_a_save_beside_the_rom_is_found(self):
        with TemporaryDirectory() as tmp_dir:
            lib = _Library(tmp_dir)
            found = save_backup.collect_battery_saves(lib.roms)
            self.assertEqual([p.name for p in found["SFC"]], ["Game.srm"])

    def test_the_rom_itself_is_not_a_save(self):
        with TemporaryDirectory() as tmp_dir:
            lib = _Library(tmp_dir)
            self.assertFalse(save_backup.is_battery_save(lib.roms / "SFC" / "Game.sfc", "SFC"))

    def test_artwork_is_not_a_save(self):
        with TemporaryDirectory() as tmp_dir:
            lib = _Library(tmp_dir)
            cover = lib.roms / "SFC" / "Game.png"
            cover.write_bytes(b"png")
            self.assertFalse(save_backup.is_battery_save(cover, "SFC"))

    def test_a_multi_dotted_core_file_is_a_save(self):
        with TemporaryDirectory() as tmp_dir:
            lib = _Library(tmp_dir)
            odd = lib.roms / "SFC" / "Game.data.szsnes"
            odd.write_bytes(b"whatever the core invented")
            self.assertTrue(save_backup.is_battery_save(odd, "SFC"))


class ExportTests(unittest.TestCase):
    def test_states_and_battery_saves_both_travel(self):
        with TemporaryDirectory() as tmp_dir:
            lib = _Library(tmp_dir)
            dest = lib.root / "backup.zip"
            summary = save_backup.export_saves(dest, lib.states, lib.roms)
            self.assertEqual((summary["states"], summary["saves"]), (1, 1))
            with zipfile.ZipFile(dest) as archive:
                names = set(archive.namelist())
            self.assertIn("states/SFC/Game.state", names)
            self.assertIn("saves/SFC/Game.srm", names)
            self.assertIn(save_backup.MANIFEST_NAME, names)

    def test_per_core_state_subdirectories_keep_their_shape(self):
        with TemporaryDirectory() as tmp_dir:
            lib = _Library(tmp_dir)
            nested = lib.states / "SFC" / "Snes9x"
            nested.mkdir()
            (nested / "Game.state1").write_bytes(b"slot1")
            dest = lib.root / "backup.zip"
            save_backup.export_saves(dest, lib.states, lib.roms)
            with zipfile.ZipFile(dest) as archive:
                self.assertIn("states/SFC/Snes9x/Game.state1", archive.namelist())

    def test_no_half_written_archive_is_left_behind(self):
        with TemporaryDirectory() as tmp_dir:
            lib = _Library(tmp_dir)
            dest = lib.root / "backup.zip"
            save_backup.export_saves(dest, lib.states, lib.roms)
            leftovers = [p.name for p in dest.parent.iterdir() if p.name.startswith(".")]
            self.assertEqual(leftovers, [])


class ImportTests(unittest.TestCase):
    def _backup(self, lib):
        dest = lib.root / "backup.zip"
        save_backup.export_saves(dest, lib.states, lib.roms)
        return dest

    def test_a_restore_onto_an_empty_machine_brings_everything_back(self):
        with TemporaryDirectory() as tmp_dir:
            lib = _Library(tmp_dir)
            backup = self._backup(lib)
            (lib.states / "SFC" / "Game.state").unlink()
            (lib.roms / "SFC" / "Game.srm").unlink()

            result = save_backup.import_saves(backup, lib.states, lib.roms)

            self.assertEqual(result["restored"], 2)
            self.assertEqual(result["errors"], [])
            self.assertTrue((lib.states / "SFC" / "Game.state").exists())
            self.assertTrue((lib.roms / "SFC" / "Game.srm").exists())

    def test_skip_leaves_what_is_already_there(self):
        with TemporaryDirectory() as tmp_dir:
            lib = _Library(tmp_dir)
            backup = self._backup(lib)
            (lib.states / "SFC" / "Game.state").write_bytes(b"played since")

            result = save_backup.import_saves(
                backup, lib.states, lib.roms, on_collision=save_backup.ON_COLLISION_SKIP
            )

            self.assertEqual(result["restored"], 0)
            self.assertEqual(
                (lib.states / "SFC" / "Game.state").read_bytes(), b"played since"
            )

    def test_overwrite_takes_the_archive(self):
        with TemporaryDirectory() as tmp_dir:
            lib = _Library(tmp_dir)
            backup = self._backup(lib)
            (lib.states / "SFC" / "Game.state").write_bytes(b"played since")

            save_backup.import_saves(
                backup, lib.states, lib.roms, on_collision=save_backup.ON_COLLISION_OVERWRITE
            )

            self.assertEqual((lib.states / "SFC" / "Game.state").read_bytes(), b"state0")

    def test_newest_keeps_a_local_file_saved_after_the_backup(self):
        import os
        import time

        with TemporaryDirectory() as tmp_dir:
            lib = _Library(tmp_dir)
            backup = self._backup(lib)
            local = lib.states / "SFC" / "Game.state"
            local.write_bytes(b"played since")
            future = time.time() + 3600
            os.utime(local, (future, future))

            result = save_backup.import_saves(backup, lib.states, lib.roms)

            self.assertEqual(result["restored"], 0)
            self.assertEqual(local.read_bytes(), b"played since")

    def test_something_that_is_not_our_archive_is_refused(self):
        with TemporaryDirectory() as tmp_dir:
            lib = _Library(tmp_dir)
            stranger = lib.root / "stranger.zip"
            with zipfile.ZipFile(stranger, "w") as archive:
                archive.writestr("states/SFC/Game.state", "x")

            result = save_backup.import_saves(stranger, lib.states, lib.roms)

            self.assertEqual(result["restored"], 0)
            self.assertTrue(result["errors"])

    def test_a_member_climbing_out_of_its_directory_is_refused(self):
        with TemporaryDirectory() as tmp_dir:
            lib = _Library(tmp_dir)
            evil = lib.root / "evil.zip"
            with zipfile.ZipFile(evil, "w") as archive:
                archive.writestr("states/SFC/../../../../pwned", "x")
                archive.writestr(save_backup.MANIFEST_NAME, '{"version": 1}')

            result = save_backup.import_saves(evil, lib.states, lib.roms)

            self.assertEqual(result["restored"], 0)
            self.assertFalse((lib.root.parent / "pwned").exists())

    def test_an_unknown_console_is_refused(self):
        with TemporaryDirectory() as tmp_dir:
            lib = _Library(tmp_dir)
            odd = lib.root / "odd.zip"
            with zipfile.ZipFile(odd, "w") as archive:
                archive.writestr("states/NOTACONSOLE/Game.state", "x")
                archive.writestr(save_backup.MANIFEST_NAME, '{"version": 1}')

            result = save_backup.import_saves(odd, lib.states, lib.roms)

            self.assertEqual(result["restored"], 0)
            self.assertEqual(result["skipped"], 1)


if __name__ == "__main__":
    unittest.main()
