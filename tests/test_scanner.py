import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

from openemux.core.scanner import RomScanner


def _make_zip(path, entries):
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in entries:
            archive.writestr(name, data)


class ScannerTests(unittest.TestCase):
    def test_scan_console_ignores_covers_and_bios_subfolders(self):
        with TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            (base / "FC").mkdir(parents=True, exist_ok=True)
            (base / "FC" / "Super Mario Bros.nes").write_bytes(b"rom-data")
            (base / "FC" / "covers").mkdir(parents=True, exist_ok=True)
            (base / "FC" / "covers" / "Super Mario Bros.nes").write_bytes(b"not-a-rom")
            (base / "FC" / "bios").mkdir(parents=True, exist_ok=True)
            (base / "FC" / "bios" / "bios.nes").write_bytes(b"not-a-rom")

            scanner = RomScanner(base)
            roms = scanner.scan_console("FC")

        self.assertEqual(len(roms), 1)
        self.assertEqual(roms[0]["console"], "FC")
        self.assertEqual(roms[0]["name"], "Super Mario Bros")

    def test_scan_console_resolves_legacy_alias(self):
        with TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            (base / "SFC").mkdir(parents=True, exist_ok=True)
            (base / "SFC" / "Chrono Trigger.sfc").write_bytes(b"rom-data")

            scanner = RomScanner(base)
            roms = scanner.scan_console("snes")

        self.assertEqual(len(roms), 1)
        self.assertEqual(roms[0]["console"], "SFC")
        self.assertEqual(roms[0]["name"], "Chrono Trigger")

    def test_scan_console_hides_bin_referenced_by_cue(self):
        with TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            ps_dir = base / "PS"
            ps_dir.mkdir(parents=True, exist_ok=True)
            (ps_dir / "Metal Gear.cue").write_text(
                'FILE "Metal Gear (Track 1).bin" BINARY\n'
                '  TRACK 01 MODE2/2352\n',
                encoding="utf-8",
            )
            (ps_dir / "Metal Gear (Track 1).bin").write_bytes(b"track")

            scanner = RomScanner(base)
            roms = scanner.scan_console("PS")

        self.assertEqual([rom["path"] for rom in roms], [str(ps_dir / "Metal Gear.cue")])

    def test_scan_console_keeps_unreferenced_bin(self):
        with TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            ps_dir = base / "PS"
            ps_dir.mkdir(parents=True, exist_ok=True)
            (ps_dir / "Game.cue").write_text('FILE "Track.bin" BINARY\n', encoding="utf-8")
            (ps_dir / "Track.bin").write_bytes(b"track")
            (ps_dir / "Standalone.bin").write_bytes(b"standalone")

            scanner = RomScanner(base)
            roms = scanner.scan_console("PS")

        paths = {rom["path"] for rom in roms}
        self.assertIn(str(ps_dir / "Game.cue"), paths)
        self.assertIn(str(ps_dir / "Standalone.bin"), paths)
        self.assertNotIn(str(ps_dir / "Track.bin"), paths)


class ArchiveScannerTests(unittest.TestCase):
    def test_zip_with_single_matching_rom_uses_inner_name(self):
        with TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            fc_dir = base / "FC"
            fc_dir.mkdir(parents=True, exist_ok=True)
            archive = fc_dir / "smb-usa.zip"
            _make_zip(archive, [("Super Mario Bros.nes", b"rom-data")])

            roms = RomScanner(base).scan_console("FC")

        self.assertEqual(len(roms), 1)
        self.assertEqual(roms[0]["name"], "Super Mario Bros")
        self.assertEqual(roms[0]["path"], str(archive))
        self.assertEqual(roms[0]["console"], "FC")
        self.assertIsNotNone(roms[0]["rom_id"])

    def test_zip_without_matching_rom_is_skipped(self):
        with TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            fc_dir = base / "FC"
            fc_dir.mkdir(parents=True, exist_ok=True)
            _make_zip(fc_dir / "manual.zip", [("readme.txt", b"hello"), ("scan.png", b"img")])

            roms = RomScanner(base).scan_console("FC")

        self.assertEqual(roms, [])

    def test_corrupt_zip_is_skipped_without_raising(self):
        with TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            fc_dir = base / "FC"
            fc_dir.mkdir(parents=True, exist_ok=True)
            (fc_dir / "broken.zip").write_bytes(b"definitely not a zip file")
            (fc_dir / "Metroid.nes").write_bytes(b"rom-data")

            roms = RomScanner(base).scan_console("FC")

        self.assertEqual([rom["name"] for rom in roms], ["Metroid"])

    def test_zip_with_multiple_roms_falls_back_to_archive_name(self):
        with TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            fc_dir = base / "FC"
            fc_dir.mkdir(parents=True, exist_ok=True)
            archive = fc_dir / "Multicart Collection.zip"
            _make_zip(archive, [("Game A.nes", b"a"), ("Game B.nes", b"b"), ("notes.txt", b"c")])

            roms = RomScanner(base).scan_console("FC")

        self.assertEqual(len(roms), 1)
        self.assertEqual(roms[0]["name"], "Multicart Collection")
        self.assertEqual(roms[0]["path"], str(archive))

    def test_zip_ignores_macos_resource_fork_entries(self):
        with TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            fc_dir = base / "FC"
            fc_dir.mkdir(parents=True, exist_ok=True)
            _make_zip(
                fc_dir / "kirby.zip",
                [("Kirby's Adventure.nes", b"rom"), ("__MACOSX/._Kirby's Adventure.nes", b"junk")],
            )

            roms = RomScanner(base).scan_console("FC")

        self.assertEqual([rom["name"] for rom in roms], ["Kirby's Adventure"])

    def test_zip_is_ignored_for_disc_based_systems(self):
        with TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            ps_dir = base / "PS"
            ps_dir.mkdir(parents=True, exist_ok=True)
            _make_zip(ps_dir / "Final Fantasy VII.zip", [("Final Fantasy VII.cue", b"cue")])

            roms = RomScanner(base).scan_console("PS")

        self.assertEqual(roms, [])


if __name__ == "__main__":
    unittest.main()
