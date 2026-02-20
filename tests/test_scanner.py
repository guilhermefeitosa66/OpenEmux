import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from opemux.core.scanner import RomScanner


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


if __name__ == "__main__":
    unittest.main()
