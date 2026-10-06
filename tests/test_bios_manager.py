import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from openemux.core.bios_catalog import get_required_for_core
from openemux.core.bios_manager import (
    _entry_label,
    find_missing_required_for_core,
    scan_console_bios_status,
)


class _DummyConfig:
    def __init__(self, roms_path):
        self.roms_path = Path(roms_path)

    def get_console_bios_dir(self, console):
        return self.roms_path / console / "bios"


class BiosManagerTests(unittest.TestCase):
    def test_scan_console_status_reports_present_and_missing(self):
        with TemporaryDirectory() as tmp_dir:
            cfg = _DummyConfig(tmp_dir)
            bios_dir = cfg.get_console_bios_dir("PS")
            bios_dir.mkdir(parents=True, exist_ok=True)
            (bios_dir / "scph5501.bin").write_bytes(b"bios")

            status = scan_console_bios_status(cfg, "PS")

        self.assertTrue(status["has_entries"])
        required_entries = status["required"]
        self.assertTrue(any(entry["present"] for entry in required_entries))

    def test_missing_required_for_core_handles_any_of(self):
        with TemporaryDirectory() as tmp_dir:
            cfg = _DummyConfig(tmp_dir)
            bios_dir = cfg.get_console_bios_dir("PS")
            bios_dir.mkdir(parents=True, exist_ok=True)

            missing = find_missing_required_for_core(cfg, "PS", "mednafen_psx_libretro.so")
            self.assertTrue(missing)

            (bios_dir / "scph5501.bin").write_bytes(b"bios")
            missing_after = find_missing_required_for_core(cfg, "PS", "mednafen_psx_libretro.so")
            self.assertEqual(missing_after, [])

    def test_required_mapping_exists_for_known_core(self):
        required = get_required_for_core("SATURN", "kronos_libretro.so")
        self.assertTrue(required)


class HowARequirementIsLabelledTests(unittest.TestCase):
    """The label is what the BIOS page shows for one requirement."""

    def test_a_single_file_is_named_by_its_filename(self):
        self.assertEqual(_entry_label({"file": "scph5501.bin"}), "scph5501.bin")

    def test_a_choice_of_files_is_spelled_as_alternatives(self):
        self.assertEqual(
            _entry_label({"any_of": ["bios7.bin", "biosnds7.rom"]}),
            "bios7.bin | biosnds7.rom",
        )

    def test_an_entry_that_names_nothing_has_no_label(self):
        self.assertEqual(_entry_label({}), "")
        self.assertEqual(_entry_label({"any_of": []}), "")


if __name__ == "__main__":
    unittest.main()

