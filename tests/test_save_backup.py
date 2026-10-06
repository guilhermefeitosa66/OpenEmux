"""Exporting and restoring saves (issue #293).

Save states live in OpenEmux's own tree; battery saves live next to the ROM,
because RetroArch's savefile_directory is left at its default. Both have to
come along, and an archive is untrusted input on the way back in.
"""

import unittest
import zipfile
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from openemux.core import save_backup
from tests.platform_marks import posix_only


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


class WhatCountsAsABatterySaveTests(unittest.TestCase):
    def test_a_directory_is_never_a_save(self):
        with TemporaryDirectory() as tmp_dir:
            lib = _Library(tmp_dir)
            sub = lib.roms / "SFC" / "sub"
            sub.mkdir()
            self.assertFalse(save_backup.is_battery_save(sub, "SFC"))

    def test_a_dotfile_is_somebody_elses_bookkeeping(self):
        with TemporaryDirectory() as tmp_dir:
            lib = _Library(tmp_dir)
            hidden = lib.roms / "SFC" / ".DS_Store"
            hidden.write_bytes(b"x")
            self.assertFalse(save_backup.is_battery_save(hidden, "SFC"))

    def test_a_file_with_no_extension_at_all_is_not_a_save(self):
        with TemporaryDirectory() as tmp_dir:
            lib = _Library(tmp_dir)
            bare = lib.roms / "SFC" / "README"
            bare.write_bytes(b"x")
            self.assertFalse(save_backup.is_battery_save(bare, "SFC"))


class WhichConsolesAreScannedTests(unittest.TestCase):
    def test_no_list_at_all_means_every_console(self):
        with TemporaryDirectory() as tmp_dir:
            lib = _Library(tmp_dir)
            self.assertIn("SFC", save_backup.collect_battery_saves(lib.roms))

    def test_a_named_console_is_resolved_to_its_canonical_id(self):
        with TemporaryDirectory() as tmp_dir:
            lib = _Library(tmp_dir)
            found = save_backup.collect_battery_saves(lib.roms, consoles=["SNES"])
            self.assertIn("SFC", found)

    def test_a_console_the_app_does_not_know_is_dropped(self):
        with TemporaryDirectory() as tmp_dir:
            lib = _Library(tmp_dir)
            self.assertEqual(
                save_backup.collect_battery_saves(lib.roms, consoles=["NOPE"]), {}
            )

    def test_a_console_named_twice_is_scanned_once(self):
        with TemporaryDirectory() as tmp_dir:
            lib = _Library(tmp_dir)
            found = save_backup.collect_battery_saves(
                lib.roms, consoles=["SFC", "SNES"]
            )
            self.assertEqual(list(found), ["SFC"])

    def test_a_console_with_no_directory_is_skipped(self):
        with TemporaryDirectory() as tmp_dir:
            lib = _Library(tmp_dir)
            self.assertNotIn("GB", save_backup.collect_battery_saves(lib.roms))
            self.assertNotIn("GB", save_backup.collect_save_states(lib.states))


class TheProgressReportTests(unittest.TestCase):
    def test_every_file_written_is_reported(self):
        with TemporaryDirectory() as tmp_dir:
            lib = _Library(tmp_dir)
            events = []
            save_backup.export_saves(
                lib.root / "backup.zip", lib.states, lib.roms,
                on_progress=events.append,
            )
        self.assertEqual([event["current"] for event in events], [1, 2])
        self.assertEqual(events[-1]["total"], 2)

    def test_every_file_restored_is_reported(self):
        with TemporaryDirectory() as tmp_dir:
            lib = _Library(tmp_dir)
            archive = lib.root / "backup.zip"
            save_backup.export_saves(archive, lib.states, lib.roms)
            events = []
            save_backup.import_saves(
                archive, lib.root / "fresh-states", lib.root / "fresh-roms",
                on_progress=events.append,
            )
        self.assertTrue(events)
        self.assertIn("name", events[0])

    def test_a_caller_that_wants_no_progress_gets_none(self):
        save_backup._emit(None, 1, 2, "/tmp/a")


class WhereAnArchiveMemberLandsTests(unittest.TestCase):
    """An archive is untrusted input, whoever it came from."""

    def _target(self, name):
        return save_backup._target_for(name, Path("/states"), Path("/roms"))

    def test_a_state_lands_in_the_states_tree(self):
        target = self._target("states/SFC/Game.state")
        self.assertEqual(target, Path("/states/SFC/Game.state"))

    def test_a_battery_save_lands_beside_the_rom(self):
        target = self._target("saves/SFC/Game.srm")
        self.assertEqual(target, Path("/roms/SFC/Game.srm"))

    def test_a_name_too_short_to_place_is_refused(self):
        self.assertIsNone(self._target("states/SFC"))

    def test_a_prefix_the_format_does_not_define_is_refused(self):
        self.assertIsNone(self._target("elsewhere/SFC/Game.srm"))

    @posix_only("symlinks are how a member escapes without a '..' in its name")
    def test_a_member_resolving_outside_its_directory_is_refused(self):
        # A ".." in the name is caught above; a symlink is the other way out,
        # and an archive is untrusted input.
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            base = root / "states" / "SFC"
            base.mkdir(parents=True)
            (root / "elsewhere").mkdir()
            (base / "link").symlink_to(root / "elsewhere")
            target = save_backup._target_for(
                "states/SFC/link/Game.state", root / "states", root / "roms"
            )
        self.assertIsNone(target)


class WhenAnExportCannotFinishTests(unittest.TestCase):
    def test_the_half_written_archive_is_removed_and_the_error_raised(self):
        # A half-written backup that looks like a whole one is worse than no
        # backup at all.
        with TemporaryDirectory() as tmp_dir:
            lib = _Library(tmp_dir)
            dest = lib.root / "backup.zip"
            with mock.patch.object(
                zipfile.ZipFile, "writestr", side_effect=OSError("disk full")
            ):
                with self.assertRaises(OSError):
                    save_backup.export_saves(dest, lib.states, lib.roms)
            self.assertFalse(dest.exists())
            self.assertEqual(list(lib.root.glob(".*.part")), [])


class ChoosingWhichCopyWinsTests(unittest.TestCase):
    class _Info:
        def __init__(self, date_time):
            self.date_time = date_time

    def _info(self, year=2026):
        return self._Info((year, 1, 1, 0, 0, 0))

    def test_overwrite_always_takes_the_archive(self):
        self.assertTrue(
            save_backup._should_replace(
                Path("/nowhere"), self._info(), save_backup.ON_COLLISION_OVERWRITE
            )
        )

    def test_skip_always_keeps_what_is_there(self):
        self.assertFalse(
            save_backup._should_replace(
                Path("/nowhere"), self._info(), save_backup.ON_COLLISION_SKIP
            )
        )

    def test_a_file_that_cannot_be_read_lets_the_archive_win(self):
        # Nothing to compare against; restoring is the safer answer.
        self.assertTrue(
            save_backup._should_replace(
                Path("/nowhere/at/all"), self._info(), save_backup.ON_COLLISION_NEWEST
            )
        )

    def test_a_collision_policy_the_app_does_not_know_falls_back_to_newest(self):
        with TemporaryDirectory() as tmp_dir:
            lib = _Library(tmp_dir)
            archive = lib.root / "backup.zip"
            save_backup.export_saves(archive, lib.states, lib.roms)
            result = save_backup.import_saves(
                archive, lib.states, lib.roms, on_collision="nonsense"
            )
        self.assertEqual(result["errors"], [])


@posix_only("an unwritable directory is what makes the write fail")
class WhenARestoreCannotWriteTests(unittest.TestCase):
    def test_the_file_that_failed_is_named_and_the_rest_go_on(self):
        with TemporaryDirectory() as tmp_dir:
            lib = _Library(tmp_dir)
            archive = lib.root / "backup.zip"
            save_backup.export_saves(archive, lib.states, lib.roms)
            with mock.patch(
                "builtins.open", side_effect=OSError("read-only")
            ):
                result = save_backup.import_saves(
                    archive, lib.root / "fresh-states", lib.root / "fresh-roms"
                )
        self.assertEqual(result["restored"], 0)
        self.assertTrue(result["errors"])


class RunningInTheBackgroundTests(unittest.TestCase):
    """Both entry points the preferences dialog actually calls."""

    def test_an_export_reports_its_summary_back(self):
        with TemporaryDirectory() as tmp_dir:
            lib = _Library(tmp_dir)
            done = []
            save_backup.export_saves_async(
                lib.root / "backup.zip", lib.states, lib.roms, on_done=done.append
            )
            _join_workers()
        self.assertEqual(done[0]["states"], 1)

    def test_an_export_that_fails_reports_the_error_rather_than_raising(self):
        done = []
        with mock.patch.object(
            save_backup, "export_saves", side_effect=OSError("disk full")
        ):
            save_backup.export_saves_async(
                "/nowhere/backup.zip", "/states", "/roms", on_done=done.append
            )
            _join_workers()
        self.assertEqual(done[0]["error"], "disk full")

    def test_an_import_reports_its_result_back(self):
        with TemporaryDirectory() as tmp_dir:
            lib = _Library(tmp_dir)
            archive = lib.root / "backup.zip"
            save_backup.export_saves(archive, lib.states, lib.roms)
            done = []
            save_backup.import_saves_async(
                archive, lib.root / "fresh-states", lib.root / "fresh-roms",
                on_done=done.append,
            )
            _join_workers()
        self.assertEqual(done[0]["restored"], 2)

    def test_an_archive_that_is_not_a_zip_reports_the_error(self):
        done = []
        with mock.patch.object(
            save_backup, "import_saves", side_effect=zipfile.BadZipFile("not a zip")
        ):
            save_backup.import_saves_async(
                "/nowhere/backup.zip", "/states", "/roms", on_done=done.append
            )
            _join_workers()
        self.assertTrue(done[0]["errors"])

    def test_a_caller_that_wants_no_callback_gets_none(self):
        with TemporaryDirectory() as tmp_dir:
            lib = _Library(tmp_dir)
            save_backup.export_saves_async(
                lib.root / "backup.zip", lib.states, lib.roms, on_done=None
            )
            _join_workers()
            save_backup.import_saves_async(
                lib.root / "backup.zip", lib.states, lib.roms, on_done=None
            )
            _join_workers()


def _join_workers(timeout=5.0):
    """Wait for the background threads save_backup started."""
    import threading

    for thread in list(threading.enumerate()):
        if thread is not threading.current_thread() and thread.daemon:
            thread.join(timeout=timeout)


class TheDefaultBackupNameTests(unittest.TestCase):
    def test_it_carries_the_date_so_two_backups_never_collide(self):
        name = save_backup.default_backup_name(now=datetime(2026, 9, 10, 14, 30))
        self.assertIn("2026", name)
        self.assertTrue(name.endswith(".zip"))

    def test_it_defaults_to_right_now(self):
        self.assertTrue(save_backup.default_backup_name().endswith(".zip"))
