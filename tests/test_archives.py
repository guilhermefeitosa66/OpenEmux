import tempfile
import unittest
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


if __name__ == "__main__":
    unittest.main()
