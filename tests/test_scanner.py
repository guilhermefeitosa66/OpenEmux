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


if __name__ == "__main__":
    unittest.main()
