import os
import tempfile
from unittest import mock
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

from openemux.core.rom_importer import (
    collect_ambiguous_extensions,
    detect_console,
    import_roms,
)
from openemux.core.scanner import RomScanner


class DetectConsoleTests(unittest.TestCase):
    def test_unambiguous_extensions_return_single_candidate(self):
        self.assertEqual(detect_console("Zelda.sfc"), ["SFC"])
        self.assertEqual(detect_console("Mario.nes"), ["FC"])
        self.assertEqual(detect_console("Metroid.gba"), ["GBA"])

    def test_extension_matching_is_case_insensitive(self):
        self.assertEqual(detect_console("Zelda.SFC"), ["SFC"])

    def test_ambiguous_extension_returns_ordered_candidates(self):
        candidates = detect_console("Game.bin")
        self.assertGreater(len(candidates), 1)
        self.assertEqual(candidates[0], "MD")
        self.assertIn("PS", candidates)

        iso = detect_console("Game.iso")
        self.assertEqual(iso[0], "PS")
        self.assertIn("GC", iso)

    def test_unknown_extension_returns_empty(self):
        self.assertEqual(detect_console("notes.txt"), [])
        self.assertEqual(detect_console("no_extension"), [])


class ImportRomsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.src = self.root / "src"
        self.src.mkdir()
        self.roms = self.root / "roms"

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, relative, data=b"rom-data"):
        path = self.src / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def test_copies_file_into_console_folder(self):
        rom = self._write("Zelda.sfc")
        result = import_roms([rom], self.roms)

        dest = self.roms / "SFC" / "Zelda.sfc"
        self.assertTrue(dest.exists())
        self.assertEqual(result["imported"], [str(dest)])
        self.assertEqual(result["skipped"], [])
        self.assertEqual(result["unknown"], [])
        self.assertEqual(result["errors"], [])
        # Copy by default: the source stays put.
        self.assertTrue(rom.exists())

    def test_move_removes_source(self):
        rom = self._write("Zelda.sfc")
        import_roms([rom], self.roms, move=True)
        self.assertFalse(rom.exists())
        self.assertTrue((self.roms / "SFC" / "Zelda.sfc").exists())

    def test_directory_is_walked_recursively(self):
        self._write("a/Zelda.sfc")
        self._write("a/b/Mario.nes")
        self._write("a/b/readme.txt")

        result = import_roms([self.src], self.roms)

        self.assertTrue((self.roms / "SFC" / "Zelda.sfc").exists())
        self.assertTrue((self.roms / "FC" / "Mario.nes").exists())
        self.assertEqual(len(result["imported"]), 2)
        # Non-ROM files inside a directory are filtered out, not reported.
        self.assertEqual(result["unknown"], [])

    def test_identical_duplicate_is_skipped(self):
        rom = self._write("Zelda.sfc", b"same")
        import_roms([rom], self.roms)
        result = import_roms([rom], self.roms)

        self.assertEqual(result["imported"], [])
        self.assertEqual(result["skipped"], [str(self.roms / "SFC" / "Zelda.sfc")])
        self.assertFalse((self.roms / "SFC" / "Zelda (2).sfc").exists())

    def test_different_duplicate_is_renamed(self):
        first = self._write("Zelda.sfc", b"version-one")
        import_roms([first], self.roms)

        other_dir = self.root / "other"
        other_dir.mkdir()
        second = other_dir / "Zelda.sfc"
        second.write_bytes(b"version-two")

        result = import_roms([second], self.roms)

        renamed = self.roms / "SFC" / "Zelda (2).sfc"
        self.assertTrue(renamed.exists())
        self.assertEqual(renamed.read_bytes(), b"version-two")
        self.assertEqual(result["imported"], [str(renamed)])

    def test_unknown_file_is_reported(self):
        note = self._write("notes.txt")
        result = import_roms([note], self.roms)

        self.assertEqual(result["imported"], [])
        self.assertEqual(result["unknown"], [str(note)])

    def test_zip_is_imported_as_is_routed_by_inner_content(self):
        archive = self.src / "Zelda.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("Zelda.sfc", "rom-data")

        result = import_roms([archive], self.roms)

        dest = self.roms / "SFC" / "Zelda.zip"
        self.assertTrue(dest.exists())
        self.assertEqual(result["imported"], [str(dest)])
        # Imported as-is: still a valid zip, not extracted.
        self.assertTrue(zipfile.is_zipfile(dest))
        self.assertFalse((self.roms / "SFC" / "Zelda.sfc").exists())

    def test_zip_without_roms_is_unknown(self):
        archive = self.src / "docs.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("readme.txt", "hello")

        result = import_roms([archive], self.roms)

        self.assertEqual(result["imported"], [])
        self.assertEqual(result["unknown"], [str(archive)])

    def test_console_override_wins_over_detection(self):
        rom = self._write("Sonic.bin")
        result = import_roms([rom], self.roms, console_overrides={".bin": "PS"})

        self.assertTrue((self.roms / "PS" / "Sonic.bin").exists())
        self.assertEqual(len(result["imported"]), 1)

    def test_progress_callback_reports_every_file(self):
        self._write("Zelda.sfc")
        self._write("Mario.nes")
        events = []

        import_roms([self.src], self.roms, on_progress=events.append)

        self.assertEqual(len(events), 2)
        self.assertEqual(events[-1]["current"], 2)
        self.assertEqual(events[-1]["total"], 2)
        self.assertEqual({e["status"] for e in events}, {"imported"})

    def test_collect_ambiguous_extensions(self):
        self._write("Sonic.bin")
        self._write("Zelda.sfc")

        ambiguous = collect_ambiguous_extensions([self.src])

        self.assertIn(".bin", ambiguous)
        self.assertNotIn(".sfc", ambiguous)
        self.assertGreater(len(ambiguous[".bin"]), 1)


if __name__ == "__main__":
    unittest.main()


class ArchiveExtractionTests(unittest.TestCase):
    """Cores flagged needs_fullpath cannot read a ROM out of a zip, so importing
    an archive for one of those systems must unpack it rather than copy it."""

    def test_zip_is_kept_intact_for_memory_loading_cores(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            src = base / "Aladdin.zip"
            with zipfile.ZipFile(src, "w") as archive:
                archive.writestr("Aladdin (USA).sfc", b"rom-data")

            result = import_roms([str(src)], base / "roms")

            self.assertEqual([Path(p).name for p in result["imported"]], ["Aladdin.zip"])
            self.assertTrue((base / "roms" / "SFC" / "Aladdin.zip").exists())

    def test_zip_is_extracted_for_fullpath_cores(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            src = base / "Disc.zip"
            with zipfile.ZipFile(src, "w") as archive:
                archive.writestr("Disc.cue", b'FILE "Disc.bin" BINARY\n')
                archive.writestr("Disc.bin", b"track-data")

            result = import_roms([str(src)], base / "roms", console_overrides={".zip": "PS"})

            target = base / "roms" / "PS"
            self.assertFalse((target / "Disc.zip").exists())
            self.assertTrue((target / "Disc.cue").exists())
            self.assertTrue((target / "Disc.bin").exists())
            self.assertEqual(len(result["imported"]), 2)

    def test_zip_with_nothing_playable_is_reported_unknown(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            src = base / "Docs.zip"
            with zipfile.ZipFile(src, "w") as archive:
                archive.writestr("readme.txt", b"x")

            result = import_roms([str(src)], base / "roms")
            self.assertEqual(result["imported"], [])
            self.assertEqual([Path(p).name for p in result["unknown"]], ["Docs.zip"])


class ForcedConsoleTests(unittest.TestCase):
    """The UI offers an explicit console picker when there is no console context
    (the All / Favorites views), and that choice must win over detection."""

    def test_forced_console_overrides_extension_detection(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            src = base / "hack.sfc"
            src.write_bytes(b"rom-data")

            result = import_roms([str(src)], base / "roms", forced_console="FC")

            self.assertTrue((base / "roms" / "FC" / "hack.sfc").exists())
            self.assertFalse((base / "roms" / "SFC").exists())
            self.assertEqual(len(result["imported"]), 1)

    def test_forced_console_still_extracts_for_fullpath_cores(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            src = base / "Disc.zip"
            with zipfile.ZipFile(src, "w") as archive:
                archive.writestr("Disc.cue", b'FILE "Disc.bin" BINARY\n')
                archive.writestr("Disc.bin", b"track")

            import_roms([str(src)], base / "roms", forced_console="SATURN")

            self.assertTrue((base / "roms" / "SATURN" / "Disc.cue").exists())
            self.assertFalse((base / "roms" / "SATURN" / "Disc.zip").exists())


class LinkImportTests(unittest.TestCase):
    """Importing as a link, for a collection that must not be duplicated (#298)."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        base = Path(self._tmp.name)
        self.roms = base / "roms"
        self.source_dir = base / "elsewhere"
        self.source_dir.mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def _rom(self, name="Game.sfc", payload=b"rom-data"):
        path = self.source_dir / name
        path.write_bytes(payload)
        return path

    def test_the_library_entry_is_a_link_to_the_original(self):
        rom = self._rom()
        result = import_roms([rom], self.roms, mode="link")
        dest = Path(result["imported"][0])
        self.assertTrue(dest.is_symlink())
        self.assertEqual(dest.resolve(), rom.resolve())
        self.assertTrue(rom.exists(), "the original must stay where it was")

    def test_the_scanner_finds_a_linked_rom(self):
        # A symlinked *file* is an ordinary file to the scanner; a symlinked
        # directory is a different question, and #228's.
        rom = self._rom()
        import_roms([rom], self.roms, mode="link")
        found = RomScanner(self.roms).scan_console("SFC")
        self.assertEqual([entry["name"] for entry in found], ["Game"])

    def test_the_link_is_absolute(self):
        # A relative link would break the moment either side moved.
        rom = self._rom()
        result = import_roms([rom], self.roms, mode="link")
        self.assertTrue(Path(os.readlink(result["imported"][0])).is_absolute())

    def test_copy_is_still_the_default(self):
        rom = self._rom()
        result = import_roms([rom], self.roms)
        self.assertFalse(Path(result["imported"][0]).is_symlink())

    def test_an_unknown_mode_falls_back_to_copying(self):
        rom = self._rom()
        result = import_roms([rom], self.roms, mode="teleport")
        self.assertFalse(Path(result["imported"][0]).is_symlink())

    def test_an_archive_a_core_reads_natively_is_linked_whole(self):
        # For those consoles the zip *is* the content, so the link points at
        # it exactly as it would at a bare ROM.
        archive = self.source_dir / "game.zip"
        with zipfile.ZipFile(archive, "w") as handle:
            handle.writestr("Game.nes", b"rom-data")
        result = import_roms([archive], self.roms, mode="link")
        dest = Path(result["imported"][0])
        self.assertTrue(dest.is_symlink())
        self.assertEqual(dest.resolve(), archive.resolve())

    def test_an_archive_a_core_cannot_read_is_still_extracted(self):
        # There is nothing for a link to point at once the core needs real
        # files, so link mode extracts like copy mode does.
        archive = self.source_dir / "disc.zip"
        with zipfile.ZipFile(archive, "w") as handle:
            handle.writestr("Disc.iso", b"disc-data")
        result = import_roms([archive], self.roms, mode="link", forced_console="PS")
        dest = Path(result["imported"][0])
        self.assertTrue(dest.exists())
        self.assertFalse(dest.is_symlink())
        self.assertEqual(result["extracted"], [str(archive)])


class LinkFallbackTests(unittest.TestCase):
    """What link mode does where a symlink cannot be created.

    Windows refuses ``CreateSymbolicLinkW`` to an unprivileged process unless
    Developer Mode is on, so most Windows users hit this path -- and before
    issue #118 it surfaced as a bare OSError and a failed import. The failures
    are simulated rather than provoked, so this runs on every platform,
    including the Linux machine where symlinks always work and the fallback
    would otherwise never be executed.
    """

    def setUp(self):
        self._tmp = TemporaryDirectory()
        base = Path(self._tmp.name)
        self.source = base / "Game.sfc"
        self.source.write_bytes(b"rom-data")
        self.roms = base / "roms"

    def tearDown(self):
        self._tmp.cleanup()

    def _import(self):
        result = import_roms([self.source], self.roms, mode="link", forced_console="SFC")
        self.assertEqual(result["errors"], [])
        return Path(result["imported"][0])

    def test_falls_back_to_a_hard_link(self):
        with mock.patch.object(Path, "symlink_to", side_effect=OSError("no privilege")):
            dest = self._import()

        self.assertTrue(dest.exists())
        self.assertFalse(dest.is_symlink())
        self.assertEqual(dest.read_bytes(), b"rom-data")
        # A hard link is the same inode, which is what makes it "not a copy".
        self.assertEqual(dest.stat().st_ino, self.source.stat().st_ino)

    def test_falls_back_to_a_copy_across_volumes(self):
        # os.link fails with EXDEV when the library is on another drive, which
        # is exactly where someone puts a ROM collection too big to duplicate.
        with mock.patch.object(Path, "symlink_to", side_effect=OSError("no privilege")):
            with mock.patch("openemux.core.rom_importer.os.link", side_effect=OSError("EXDEV")):
                dest = self._import()

        self.assertTrue(dest.exists())
        self.assertFalse(dest.is_symlink())
        self.assertEqual(dest.read_bytes(), b"rom-data")
        self.assertNotEqual(dest.stat().st_ino, self.source.stat().st_ino)

    def test_the_import_still_succeeds_rather_than_erroring(self):
        # The regression this guards: an unprivileged Windows user choosing
        # "link" used to get an import that failed outright.
        with mock.patch.object(Path, "symlink_to", side_effect=OSError("no privilege")):
            with mock.patch("openemux.core.rom_importer.os.link", side_effect=OSError("EXDEV")):
                result = import_roms(
                    [self.source], self.roms, mode="link", forced_console="SFC"
                )
        self.assertEqual(result["errors"], [])
        self.assertEqual(len(result["imported"]), 1)


if __name__ == "__main__":
    unittest.main()

