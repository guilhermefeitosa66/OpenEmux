"""Importing BIOS files into one console, matched by name (issue 667)."""

import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from openemux.core import bios_importer
from openemux.core.bios_importer import (
    REASON_ERROR,
    REASON_OTHER_CONSOLE,
    REASON_UNKNOWN,
    console_bios_names,
    consoles_expecting,
    import_bios_files,
    import_bios_files_async,
)
from openemux.core.bios_manager import find_missing_required_for_core, scan_console_bios_status
from openemux.core.config import ConfigManager


class _Case(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.config = ConfigManager(self.tmp / "config.yaml")
        self.config.set_roms_path(str(self.tmp / "roms"))
        self.picked = self.tmp / "picked"
        self.picked.mkdir()

    def file(self, name, content=b"bios"):
        path = self.picked / name
        path.write_bytes(content)
        return path

    def bios_dir(self, console):
        return self.config.get_console_bios_dir(console)


class TheNamesComeFromTheCatalogTests(unittest.TestCase):
    def test_every_any_of_name_and_the_optional_ones_are_listed(self):
        names = console_bios_names("MCD")
        for name in ("bios_CD_U.bin", "bios_CD_E.bin", "bios_CD_J.bin", "bios_MD.bin"):
            self.assertIn(name, names)

    def test_a_name_listed_twice_is_listed_once(self):
        names = console_bios_names("SATURN")
        self.assertEqual(len(names), len(set(names)))
        self.assertIn("sega_101.bin", names)

    def test_an_alias_resolves_to_the_console(self):
        self.assertEqual(console_bios_names("mcd"), console_bios_names("MCD"))

    def test_the_owner_of_a_name_is_found_whatever_its_case(self):
        self.assertEqual(consoles_expecting("LYNXBOOT.IMG"), ["LYNX"])
        self.assertEqual(consoles_expecting("readme.txt"), [])


class ImportingIntoAConsoleTests(_Case):
    def test_a_matching_file_is_copied_and_the_original_stays(self):
        source = self.file("lynxboot.img", b"lynx")
        summary = import_bios_files([source], self.config, "LYNX")
        self.assertEqual(summary["console"], "LYNX")
        self.assertEqual(
            summary["imported"],
            [{"source": str(source), "name": "lynxboot.img", "replaced": False}],
        )
        self.assertEqual(summary["rejected"], [])
        self.assertEqual((self.bios_dir("LYNX") / "lynxboot.img").read_bytes(), b"lynx")
        self.assertTrue(source.exists())

    def test_a_name_in_another_case_is_saved_under_the_catalog_spelling(self):
        import_bios_files([self.file("SCPH5501.BIN")], self.config, "PS")
        self.assertEqual(
            [p.name for p in self.bios_dir("PS").iterdir()], ["scph5501.bin"]
        )

    def test_each_regional_name_of_an_any_of_entry_is_accepted(self):
        paths = [self.file(n) for n in ("bios_CD_U.bin", "bios_CD_E.bin", "bios_CD_J.bin")]
        summary = import_bios_files(paths, self.config, "MCD")
        self.assertEqual(len(summary["imported"]), 3)

    def test_a_name_no_console_expects_is_rejected_and_nothing_is_written(self):
        summary = import_bios_files([self.file("readme.txt")], self.config, "PS")
        self.assertEqual(summary["imported"], [])
        rejected = summary["rejected"][0]
        self.assertEqual(rejected["reason"], REASON_UNKNOWN)
        self.assertEqual(rejected["consoles"], [])
        self.assertFalse(self.bios_dir("PS").exists())

    def test_another_consoles_bios_is_rejected_and_names_its_console(self):
        summary = import_bios_files([self.file("lynxboot.img")], self.config, "PS")
        rejected = summary["rejected"][0]
        self.assertEqual(rejected["reason"], REASON_OTHER_CONSOLE)
        self.assertEqual(rejected["consoles"], ["LYNX"])
        self.assertFalse((self.bios_dir("LYNX") / "lynxboot.img").exists())

    def test_a_different_file_already_there_is_replaced_and_said_so(self):
        self.bios_dir("LYNX").mkdir(parents=True)
        (self.bios_dir("LYNX") / "lynxboot.img").write_bytes(b"old")
        summary = import_bios_files([self.file("lynxboot.img", b"new")], self.config, "LYNX")
        self.assertTrue(summary["imported"][0]["replaced"])
        self.assertEqual((self.bios_dir("LYNX") / "lynxboot.img").read_bytes(), b"new")

    def test_the_same_file_already_there_is_not_rewritten(self):
        self.bios_dir("LYNX").mkdir(parents=True)
        (self.bios_dir("LYNX") / "lynxboot.img").write_bytes(b"same")
        with mock.patch.object(bios_importer, "atomic_write_stream") as write:
            summary = import_bios_files([self.file("lynxboot.img", b"same")], self.config, "LYNX")
        write.assert_not_called()
        self.assertFalse(summary["imported"][0]["replaced"])

    def test_one_bad_file_never_stops_the_batch(self):
        paths = [
            self.picked / "exec.bin",          # missing: error
            self.file("foo.bin"),              # unknown
            self.file("grom.bin"),             # good
        ]
        summary = import_bios_files(paths, self.config, "INTV")
        self.assertEqual([e["name"] for e in summary["imported"]], ["grom.bin"])
        reasons = {e["name"]: e["reason"] for e in summary["rejected"]}
        self.assertEqual(reasons, {"exec.bin": REASON_ERROR, "foo.bin": REASON_UNKNOWN})
        error = [e for e in summary["rejected"] if e["reason"] == REASON_ERROR][0]["error"]
        self.assertTrue(error)

    def test_a_folder_with_a_bios_name_is_an_error_not_a_crash(self):
        folder = self.picked / "lynxboot.img"
        folder.mkdir()
        summary = import_bios_files([folder], self.config, "LYNX")
        self.assertEqual(summary["rejected"][0]["reason"], REASON_ERROR)

    def test_a_write_failure_is_reported_with_the_os_message(self):
        source = self.file("lynxboot.img")
        with mock.patch.object(
            bios_importer, "atomic_write_stream", side_effect=PermissionError(13, "Permission denied")
        ):
            summary = import_bios_files([source], self.config, "LYNX")
        self.assertEqual(summary["rejected"][0]["error"], "Permission denied")

    def test_an_error_with_no_strerror_falls_back_to_its_text(self):
        source = self.file("lynxboot.img")
        with mock.patch.object(bios_importer, "atomic_write_stream", side_effect=OSError("disk full")):
            summary = import_bios_files([source], self.config, "LYNX")
        self.assertEqual(summary["rejected"][0]["error"], "disk full")

    def test_the_launch_check_sees_the_import_with_the_same_config(self):
        core = "mednafen_psx_libretro.so"
        self.assertTrue(find_missing_required_for_core(self.config, "PS", core))
        import_bios_files([self.file("scph5501.bin")], self.config, "PS")
        self.assertEqual(find_missing_required_for_core(self.config, "PS", core), [])
        status = scan_console_bios_status(self.config, "PS")
        self.assertTrue(any(e["present"] for e in status["required"]))


class TheAsyncWrapperTests(_Case):
    def test_it_hands_the_summary_to_on_done(self):
        done = threading.Event()
        got = []

        def on_done(summary):
            got.append(summary)
            done.set()

        import_bios_files_async([self.file("lynxboot.img")], self.config, "LYNX", on_done)
        self.assertTrue(done.wait(5))
        self.assertEqual(got[0]["imported"][0]["name"], "lynxboot.img")


if __name__ == "__main__":
    unittest.main()
