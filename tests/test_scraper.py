import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from openemux.core.scraper import (
    COVER_ART,
    LABEL_ART,
    find_local_art,
    find_local_cover,
    image_format,
    is_image,
    remove_local_art,
    remove_local_covers,
    save_local_art,
    save_local_cover,
)


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

    def test_label_art_is_stored_separately_from_cover_art(self):
        with TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            roms_dir = base / "roms"
            cover_src = base / "cover.png"
            cover_src.write_bytes(b"cover")
            label_src = base / "label.png"
            label_src.write_bytes(b"label")

            save_local_art(roms_dir, "GBA", "Golden Sun", cover_src, COVER_ART)
            save_local_art(roms_dir, "GBA", "Golden Sun", label_src, LABEL_ART)

            self.assertEqual(
                find_local_art(roms_dir, "GBA", "Golden Sun", COVER_ART).read_bytes(), b"cover"
            )
            self.assertEqual(
                find_local_art(roms_dir, "GBA", "Golden Sun", LABEL_ART).read_bytes(), b"label"
            )

            # Removing the label must leave the cover untouched.
            self.assertEqual(remove_local_art(roms_dir, "GBA", "Golden Sun", LABEL_ART), 1)
            self.assertIsNone(find_local_art(roms_dir, "GBA", "Golden Sun", LABEL_ART))
            self.assertIsNotNone(find_local_art(roms_dir, "GBA", "Golden Sun", COVER_ART))


class ImageSniffingTests(unittest.TestCase):
    """What counts as an image, and what is an error page (issue #213)."""

    PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 96
    JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 96
    WEBP = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00" * 96
    GIF = b"GIF89a" + b"\x00" * 96

    def test_it_names_each_supported_format(self):
        self.assertEqual(image_format(self.PNG), "png")
        self.assertEqual(image_format(self.JPEG), "jpg")
        self.assertEqual(image_format(self.WEBP), "webp")
        self.assertEqual(image_format(self.GIF), "gif")

    def test_an_html_error_page_is_not_an_image(self):
        self.assertIsNone(image_format(b"<html><body>Quota exceeded</body></html>" * 4))

    def test_a_plain_text_quota_message_is_not_an_image(self):
        # The documented ScreenScraper behaviour: a 200 with a text body.
        self.assertIsNone(image_format(b"Quota de telechargement depasse " * 4))

    def test_an_empty_body_is_not_an_image(self):
        self.assertIsNone(image_format(b""))
        self.assertIsNone(image_format(None))

    def test_a_signature_with_nothing_behind_it_is_not_an_image(self):
        # A download cut off after the first bytes: the magic number matches
        # and the file is still unusable.
        self.assertIsNone(image_format(b"\x89PNG\r\n\x1a\n"))

    def test_riff_that_is_not_webp_is_rejected(self):
        wav = b"RIFF" + b"\x00\x00\x00\x00" + b"WAVE" + b"\x00" * 96
        self.assertIsNone(image_format(wav))

    def test_is_image_agrees_with_image_format(self):
        self.assertTrue(is_image(self.PNG))
        self.assertFalse(is_image(b"not an image at all, just some words here"))


if __name__ == "__main__":
    unittest.main()
