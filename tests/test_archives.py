import os
import tempfile
import unittest
import unittest.mock
import warnings
import zipfile
from pathlib import Path

from openemux.core.archives import (
    archive_rom_name,
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


if __name__ == "__main__":
    unittest.main()
