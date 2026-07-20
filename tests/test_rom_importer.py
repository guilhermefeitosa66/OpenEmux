import tempfile
import unittest
import zipfile
from pathlib import Path

from openemux.core.rom_importer import (
    collect_ambiguous_extensions,
    detect_console,
    import_roms,
)


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
