"""ROM digests: one read serves every stage that asks (issue #231)."""

import hashlib
import unittest
import zipfile
import zlib
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from openemux.core import hasher


class RomDigestsTests(unittest.TestCase):
    def setUp(self):
        hasher.forget_rom_digests()

    tearDown = setUp

    def _rom(self, tmp_dir, payload=b"rom-data"):
        path = Path(tmp_dir) / "game.bin"
        path.write_bytes(payload)
        return path

    def test_both_digests_come_from_one_read(self):
        with TemporaryDirectory() as tmp_dir:
            rom = self._rom(tmp_dir)
            reads = []
            real_open = open

            def spy(file, *args, **kwargs):
                if str(file) == str(rom):
                    reads.append(str(file))
                return real_open(file, *args, **kwargs)

            import builtins

            builtins.open = spy
            try:
                crc = hasher.compute_crc32(rom)
                md5 = hasher.compute_md5(rom)
            finally:
                builtins.open = real_open

            self.assertEqual(len(reads), 1, reads)
            self.assertEqual((crc, md5), hasher.rom_digests(rom))

    def test_the_digests_are_the_expected_ones(self):
        import hashlib
        import zlib

        with TemporaryDirectory() as tmp_dir:
            rom = self._rom(tmp_dir, b"hello world")
            crc, md5 = hasher.rom_digests(rom)
            self.assertEqual(crc, format(zlib.crc32(b"hello world") & 0xFFFFFFFF, "08X"))
            self.assertEqual(md5, hashlib.md5(b"hello world").hexdigest().upper())

    def test_a_rom_that_changed_is_read_again(self):
        with TemporaryDirectory() as tmp_dir:
            rom = self._rom(tmp_dir, b"first")
            before = hasher.rom_digests(rom)
            rom.write_bytes(b"second-and-longer")
            self.assertNotEqual(hasher.rom_digests(rom), before)

    def test_an_unreadable_rom_still_raises(self):
        with TemporaryDirectory() as tmp_dir:
            missing = Path(tmp_dir) / "gone.bin"
            with self.assertRaises(OSError):
                hasher.rom_digests(missing)


class RomIdentityTests(unittest.TestCase):
    """rom_identity: what a content lookup should see of a ROM (issue #506)."""

    ROM = b"game-boy-rom-bytes" * 10

    def setUp(self):
        hasher.forget_rom_digests()
        self._tmp = TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()
        hasher.forget_rom_digests()

    def _zip(self, entries, name="Tetris (World).zip"):
        path = self.tmp / name
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            for entry, data in entries.items():
                archive.writestr(entry, data)
        return path

    def _expected_digests(self, data):
        return (
            format(zlib.crc32(data) & 0xFFFFFFFF, "08X"),
            hashlib.md5(data).hexdigest().upper(),
        )

    def test_a_plain_rom_is_itself(self):
        rom = self.tmp / "Tetris (World).gb"
        rom.write_bytes(self.ROM)
        crc, md5 = self._expected_digests(self.ROM)
        self.assertEqual(
            hasher.rom_identity(rom, [".gb"]),
            hasher.RomIdentity("Tetris (World).gb", len(self.ROM), crc, md5),
        )

    def test_a_zipped_rom_is_the_rom_inside(self):
        archive = self._zip({"Tetris (World).gb": self.ROM})
        crc, md5 = self._expected_digests(self.ROM)
        identity = hasher.rom_identity(archive, [".gb"])
        self.assertEqual(
            identity, hasher.RomIdentity("Tetris (World).gb", len(self.ROM), crc, md5)
        )
        self.assertNotEqual(identity.size, archive.stat().st_size)

    def test_the_entry_name_drops_its_folder(self):
        archive = self._zip({"roms/Tetris (World).gb": self.ROM})
        self.assertEqual(hasher.rom_identity(archive, [".gb"]).file_name, "Tetris (World).gb")

    def test_a_large_entry_skips_the_md5(self):
        archive = self._zip({"Tetris (World).gb": self.ROM})
        with patch.object(hasher, "ARCHIVE_MD5_CAP_BYTES", 4):
            identity = hasher.rom_identity(archive, [".gb"])
        self.assertIsNone(identity.md5)
        self.assertEqual(identity.crc32, self._expected_digests(self.ROM)[0])

    def test_an_entry_that_cannot_be_decompressed_keeps_crc_and_size(self):
        archive = self._zip({"Tetris (World).gb": self.ROM})
        with patch.object(hasher.zipfile.ZipFile, "open", side_effect=zipfile.BadZipFile("bad")):
            identity = hasher.rom_identity(archive, [".gb"])
        self.assertIsNone(identity.md5)
        self.assertEqual(identity.size, len(self.ROM))

    def test_an_archive_without_a_rom_is_hashed_as_a_file(self):
        archive = self._zip({"readme.txt": b"hello"})
        crc, md5 = self._expected_digests(archive.read_bytes())
        identity = hasher.rom_identity(archive, [".gb"])
        self.assertEqual(identity, hasher.RomIdentity(archive.name, archive.stat().st_size, crc, md5))

    def test_a_corrupt_archive_is_hashed_as_a_file(self):
        archive = self.tmp / "broken.zip"
        archive.write_bytes(b"not a zip")
        identity = hasher.rom_identity(archive, [".gb"])
        self.assertEqual(identity.crc32, self._expected_digests(b"not a zip")[0])

    def test_a_missing_file_is_all_none_but_its_name(self):
        for name in ("gone.gb", "gone.zip"):
            self.assertEqual(
                hasher.rom_identity(self.tmp / name, [".gb"]),
                hasher.RomIdentity(name, None, None, None),
            )

    def test_an_archive_is_read_once_until_forgotten(self):
        archive = self._zip({"Tetris (World).gb": self.ROM})
        with patch.object(
            hasher.archives, "archive_rom_entry", wraps=hasher.archives.archive_rom_entry
        ) as entry_mock:
            hasher.rom_identity(archive, [".gb"])
            hasher.rom_identity(archive, [".gb"])
            self.assertEqual(entry_mock.call_count, 1)
            hasher.forget_rom_digests()
            hasher.rom_identity(archive, [".gb"])
            self.assertEqual(entry_mock.call_count, 2)


if __name__ == "__main__":
    unittest.main()
