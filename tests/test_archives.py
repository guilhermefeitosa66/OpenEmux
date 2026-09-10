import os
import tempfile
import unittest
import unittest.mock
import warnings
import zipfile
from pathlib import Path

from openemux.core import archives as archives_module
from openemux.core.archives import (
    _safe_target,
    archive_rom_name,
    rename_archive_rom_entry,
    extract_archive,
    is_archive,
    loads_archives_natively,
)


def _zip(path, entries):
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return Path(path)


class ArchiveHelpersTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_is_archive(self):
        self.assertTrue(is_archive("game.zip"))
        self.assertTrue(is_archive("game.ZIP"))
        self.assertFalse(is_archive("game.sfc"))

    def test_memory_cores_load_archives_natively(self):
        for console in ("SFC", "FC", "GBA", "MD"):
            self.assertTrue(loads_archives_natively(console), console)

    def test_fullpath_cores_do_not(self):
        for console in ("PS", "PSP", "SATURN", "MCD", "PCECD", "GC"):
            self.assertFalse(loads_archives_natively(console), console)

    def test_single_rom_archive_uses_inner_name(self):
        path = _zip(self.tmp / "Aladdin.zip", {"Aladdin (USA).sfc": b"x"})
        self.assertEqual(archive_rom_name(path, (".sfc",)), "Aladdin (USA)")

    def test_multi_rom_archive_falls_back_to_archive_name(self):
        path = _zip(self.tmp / "Pack.zip", {"A.sfc": b"x", "B.sfc": b"y"})
        self.assertEqual(archive_rom_name(path, (".sfc",)), "Pack")

    def test_archive_without_matching_rom(self):
        path = _zip(self.tmp / "Docs.zip", {"readme.txt": b"x"})
        self.assertIsNone(archive_rom_name(path, (".sfc",)))

    def test_macos_junk_entries_are_ignored(self):
        path = _zip(
            self.tmp / "Aladdin.zip",
            {"__MACOSX/._Aladdin.sfc": b"junk", "Aladdin.sfc": b"x"},
        )
        self.assertEqual(archive_rom_name(path, (".sfc",)), "Aladdin")

    def test_corrupt_archive_is_survivable(self):
        path = self.tmp / "broken.zip"
        path.write_bytes(b"not a zip at all")
        self.assertIsNone(archive_rom_name(path, (".sfc",)))

    def test_extract_flattens_nested_folders(self):
        path = _zip(self.tmp / "Disc.zip", {"inner/Disc.cue": b"cue", "inner/Disc.bin": b"bin"})
        dest = self.tmp / "out"
        dest.mkdir()
        extracted = extract_archive(path, dest)
        self.assertEqual(sorted(p.name for p in extracted), ["Disc.bin", "Disc.cue"])
        # Flattened, so the .cue's bare-filename track references still resolve.
        self.assertTrue((dest / "Disc.cue").exists())
        self.assertFalse((dest / "inner").exists())

    def test_extract_rejects_zip_slip(self):
        path = self.tmp / "evil.zip"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("../../escaped.sfc", b"pwned")
        dest = self.tmp / "out"
        dest.mkdir()
        extract_archive(path, dest)
        self.assertFalse((self.tmp.parent / "escaped.sfc").exists())
        self.assertFalse((self.tmp / "escaped.sfc").exists())


class ExtractIntegrityTests(unittest.TestCase):
    """A multi-disc archive keeps every disc, and no partial file survives."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.dest = self.tmp / "out"
        self.dest.mkdir()

    def test_a_multi_disc_archive_keeps_both_discs(self):
        path = _zip(
            self.tmp / "FF7.zip",
            {
                "Disc 1/track01.bin": b"disc-one-data",
                "Disc 1/FF7.cue": b'FILE "track01.bin" BINARY',
                "Disc 2/track01.bin": b"disc-two-data",
                "Disc 2/FF7.cue": b'FILE "track01.bin" BINARY',
            },
        )

        extracted = extract_archive(path, self.dest)

        self.assertEqual(len(extracted), 4)
        self.assertEqual(
            (self.dest / "Disc 1" / "track01.bin").read_bytes(), b"disc-one-data"
        )
        self.assertEqual(
            (self.dest / "Disc 2" / "track01.bin").read_bytes(), b"disc-two-data"
        )
        # Each cue still sits beside its own tracks, which is what makes its
        # bare-filename references resolve.
        self.assertTrue((self.dest / "Disc 1" / "FF7.cue").exists())
        self.assertTrue((self.dest / "Disc 2" / "FF7.cue").exists())

    def test_a_single_disc_archive_is_still_flattened(self):
        path = _zip(
            self.tmp / "Disc.zip",
            {"inner/Disc.cue": b"cue", "inner/Disc.bin": b"bin"},
        )

        extract_archive(path, self.dest)

        self.assertTrue((self.dest / "Disc.cue").exists())
        self.assertFalse((self.dest / "inner").exists())

    def test_colliding_entries_at_the_archive_root_get_distinct_names(self):
        path = self.tmp / "twice.zip"
        with warnings.catch_warnings():
            # A zip really can carry the same name twice; that is the point.
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("track01.bin", b"first")
                archive.writestr("track01.bin", b"second")

        extracted = extract_archive(path, self.dest)

        self.assertEqual(len(extracted), 2)
        self.assertEqual({p.read_bytes() for p in extracted}, {b"first", b"second"})
        self.assertEqual(len({p.name for p in extracted}), 2)

    def test_no_entry_is_reported_as_extracted_without_its_own_file(self):
        # The reported failure: the second Disc 2 entry was appended to the
        # result while only the first was ever written.
        path = _zip(
            self.tmp / "FF7.zip",
            {"Disc 1/track01.bin": b"one", "Disc 2/track01.bin": b"two"},
        )

        extracted = extract_archive(path, self.dest)

        self.assertEqual(len(extracted), len(set(extracted)))
        for target in extracted:
            self.assertTrue(target.exists())

    def test_re_importing_the_same_archive_skips_the_files_already_there(self):
        path = _zip(self.tmp / "Disc.zip", {"Disc.bin": b"bin", "Disc.cue": b"cue"})

        first = extract_archive(path, self.dest)
        second = extract_archive(path, self.dest)

        self.assertEqual(sorted(first), sorted(second))
        self.assertEqual(sorted(p.name for p in self.dest.iterdir()), ["Disc.bin", "Disc.cue"])

    def test_a_truncated_file_from_an_older_import_is_repaired(self):
        path = _zip(self.tmp / "Disc.zip", {"Disc.bin": b"complete-rom-data"})
        (self.dest / "Disc.bin").write_bytes(b"complete-rom")  # cut short

        extract_archive(path, self.dest)

        self.assertEqual((self.dest / "Disc.bin").read_bytes(), b"complete-rom-data")
        self.assertEqual([p.name for p in self.dest.iterdir()], ["Disc.bin"])

    def test_somebody_elses_file_of_the_same_name_is_never_overwritten(self):
        path = _zip(self.tmp / "Disc.zip", {"track01.bin": b"archive-data"})
        (self.dest / "track01.bin").write_bytes(b"a totally different game")

        extracted = extract_archive(path, self.dest)

        self.assertEqual(
            (self.dest / "track01.bin").read_bytes(), b"a totally different game"
        )
        self.assertEqual(extracted[0].read_bytes(), b"archive-data")
        self.assertEqual(extracted[0].name, "track01 (2).bin")

    def test_an_interrupted_extraction_leaves_nothing_at_the_final_path(self):
        path = _zip(self.tmp / "Disc.zip", {"Disc.bin": b"x" * 4096})

        real_replace = os.replace

        def _fail_once(src, dst):
            raise OSError("disk full")

        with unittest.mock.patch("openemux.core.atomic_write.os.replace", _fail_once):
            extracted = extract_archive(path, self.dest)

        self.assertEqual(extracted, [])
        self.assertEqual(list(self.dest.iterdir()), [])
        self.assertFalse((self.dest / "Disc.bin").exists())
        self.assertIs(os.replace, real_replace)


class RenamingTheGameInsideAnArchiveTests(unittest.TestCase):
    """Issue #134: the entry carries the title, so a rename has to reach it."""

    def _archive(self, tmp_dir, entries):
        path = Path(tmp_dir) / "Game.zip"
        _zip(path, entries)
        return path

    def test_an_entry_that_already_has_the_name_is_left_alone(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            archive = self._archive(tmp_dir, {"Kirby.gb": b"rom"})
            self.assertFalse(rename_archive_rom_entry(archive, "Kirby", [".gb"]))

    def test_the_directory_entries_are_not_copied_across(self):
        # A zip carries its folders as entries of their own; the rewrite
        # writes files, and the renamed ROM lands at the archive root.
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "Game.zip"
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("roms/", b"")
                archive.writestr("roms/Kirby.gb", b"rom")

            self.assertTrue(rename_archive_rom_entry(path, "Kirby DX", [".gb"]))

            with zipfile.ZipFile(path) as archive:
                self.assertEqual(archive.namelist(), ["Kirby DX.gb"])

    def test_a_rewrite_that_fails_leaves_the_original_archive_alone(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            archive = self._archive(tmp_dir, {"Kirby.gb": b"rom"})
            before = archive.read_bytes()
            with unittest.mock.patch.object(
                Path, "replace", side_effect=OSError("read-only")
            ):
                with self.assertRaises(OSError):
                    rename_archive_rom_entry(archive, "Kirby DX", [".gb"])
            self.assertEqual(archive.read_bytes(), before)
            self.assertFalse((Path(tmp_dir) / "Game.zip.renaming").exists())


class WhatTheExtractorRefusesTests(unittest.TestCase):
    def test_an_entry_that_climbs_out_of_the_folder_is_refused(self):
        # Zip-slip. The flattening upstream already drops the directory
        # part, so this is the guard behind it rather than in front.
        with tempfile.TemporaryDirectory() as tmp_dir:
            dest = Path(tmp_dir) / "dest"
            dest.mkdir()
            with self.assertLogs("openemux.core.archives", level="WARNING"):
                self.assertIsNone(_safe_target(dest, "../escaped.gb"))
            self.assertEqual(
                _safe_target(dest, "Kirby.gb"), (dest / "Kirby.gb").resolve()
            )

    def test_an_entry_that_cannot_be_placed_is_skipped_by_the_extractor(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            archive = base / "Game.zip"
            _zip(archive, {"escaped.gb": b"rom", "Kirby.gb": b"rom"})
            dest = base / "dest"
            dest.mkdir()
            real = archives_module._safe_target

            def _refuse(dest_dir, member_name):
                return None if member_name == "escaped.gb" else real(dest_dir, member_name)

            with unittest.mock.patch.object(
                archives_module, "_safe_target", _refuse
            ):
                extracted = extract_archive(archive, dest)

            self.assertEqual([path.name for path in extracted], ["Kirby.gb"])

    def test_a_third_copy_of_a_name_gets_a_third_target(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            archive = base / "Game.zip"
            with warnings.catch_warnings():
                # A zip really can carry the same path three times.
                warnings.simplefilter("ignore", UserWarning)
                with zipfile.ZipFile(archive, "w") as zipped:
                    for _ in range(3):
                        zipped.writestr("track01.bin", b"data")
            dest = base / "dest"
            dest.mkdir()

            names = [path.name for path in extract_archive(archive, dest)]

        self.assertEqual(names, ["track01.bin", "track01 (2).bin", "track01 (3).bin"])

    def test_a_third_file_already_at_that_name_gets_a_third_target(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            archive = base / "Game.zip"
            _zip(archive, {"track01.bin": b"data"})
            dest = base / "dest"
            dest.mkdir()
            (dest / "track01.bin").write_bytes(b"somebody else's")
            (dest / "track01 (2).bin").write_bytes(b"and another")

            extracted = extract_archive(archive, dest)

        self.assertEqual([path.name for path in extracted], ["track01 (3).bin"])


class WhatIsAlreadyAtTheTargetTests(unittest.TestCase):
    def _setup(self, tmp_dir, existing):
        base = Path(tmp_dir)
        archive = base / "Game.zip"
        _zip(archive, {"Kirby.gb": b"the whole rom"})
        dest = base / "dest"
        dest.mkdir()
        if existing is not None:
            (dest / "Kirby.gb").write_bytes(existing)
        return archive, dest

    def test_a_half_written_file_from_a_cut_short_extraction_is_repaired(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            archive, dest = self._setup(tmp_dir, b"the whole")
            extracted = extract_archive(archive, dest)
            self.assertEqual([path.name for path in extracted], ["Kirby.gb"])
            self.assertEqual((dest / "Kirby.gb").read_bytes(), b"the whole rom")

    def test_a_file_that_starts_differently_is_somebody_elses(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            archive, dest = self._setup(tmp_dir, b"not the ro")
            extracted = extract_archive(archive, dest)
            self.assertEqual([path.name for path in extracted], ["Kirby (2).gb"])

    def test_a_file_that_vanishes_between_the_check_and_the_stat_is_rewritten(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            archive, dest = self._setup(tmp_dir, b"whatever")
            with unittest.mock.patch.object(
                Path, "stat", side_effect=OSError("gone")
            ):
                extracted = extract_archive(archive, dest)
            self.assertEqual([path.name for path in extracted], ["Kirby (2).gb"])


if __name__ == "__main__":
    unittest.main()
