import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from openemux.core.scraper import find_local_cover, remove_local_covers, save_local_cover


class ScraperTests(unittest.TestCase):
    def test_save_local_cover_replaces_previous_extension(self):
        with TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            roms_dir = base / "roms"
            (roms_dir / "GBA" / "covers").mkdir(parents=True, exist_ok=True)
            source_png = base / "new.png"
            source_png.write_bytes(b"png")
            source_jpeg = base / "new.jpeg"
            source_jpeg.write_bytes(b"jpeg")

            save_local_cover(roms_dir, "GBA", "Golden Sun", source_png)
            save_local_cover(roms_dir, "GBA", "Golden Sun", source_jpeg)

            self.assertFalse((roms_dir / "GBA" / "covers" / "Golden Sun.png").exists())
            self.assertTrue((roms_dir / "GBA" / "covers" / "Golden Sun.jpeg").exists())
            self.assertTrue(find_local_cover(roms_dir, "GBA", "Golden Sun"))

    def test_remove_local_covers_removes_all_supported_extensions(self):
        with TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            covers_dir = base / "roms" / "PS" / "covers"
            covers_dir.mkdir(parents=True, exist_ok=True)
            for ext in ("png", "jpg", "jpeg", "webp"):
                (covers_dir / f"Game.{ext}").write_bytes(b"x")

            removed = remove_local_covers(base / "roms", "PS", "Game")

            self.assertEqual(removed, 4)
            self.assertIsNone(find_local_cover(base / "roms", "PS", "Game"))


if __name__ == "__main__":
    unittest.main()
