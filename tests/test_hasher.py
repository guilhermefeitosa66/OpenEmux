"""ROM digests: one read serves every stage that asks (issue #231)."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

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


if __name__ == "__main__":
    unittest.main()
