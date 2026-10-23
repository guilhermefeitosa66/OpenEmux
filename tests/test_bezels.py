"""The bezel beside a 4:3 game (issue #507), the part that is not the overlay.

Which consoles get one, checking and storing a custom image, and the box the
bezel is drawn in. Writing it into the bar's pages is ``overlay_bar``'s, and
tested in ``test_overlay_bar.py``.
"""

import shutil
import struct
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest import mock

from openemux.core import bezels, overlay_bar
from openemux.core.systems import SYSTEM_IDS


def png_bytes(width, height):
    """A minimal valid PNG header, enough for ``validate_png``."""
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    chunk = struct.pack(">I", len(ihdr)) + b"IHDR" + ihdr
    chunk += struct.pack(">I", zlib.crc32(b"IHDR" + ihdr))
    return b"\x89PNG\r\n\x1a\n" + chunk


class _TmpCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def write(self, name, data):
        path = self.tmp / name
        path.write_bytes(data)
        return path


class TheConsolesOfferedABezelTests(unittest.TestCase):
    def test_every_bezel_console_is_a_known_one(self):
        self.assertLessEqual(bezels.BEZEL_CONSOLES, set(SYSTEM_IDS))

    def test_handhelds_and_the_vectrex_get_none(self):
        for console in ("GB", "GBC", "GBA", "GG", "NGP", "NDS", "PSP", "VB", "WS", "LYNX",
                        "VECTREX"):
            self.assertNotIn(console, bezels.BEZEL_CONSOLES)

    def test_an_unknown_mode_is_none(self):
        self.assertEqual(bezels.normalize_mode("fancy"), bezels.NONE)
        self.assertEqual(bezels.normalize_mode(None), bezels.NONE)
        self.assertEqual(bezels.normalize_mode("simple"), bezels.SIMPLE)


class TheBuiltInBezelTests(unittest.TestCase):
    def test_the_simple_bezel_ships_as_a_16_9_png(self):
        path = bezels.BUILTIN[bezels.SIMPLE]
        self.assertTrue(path.is_file(), path)
        self.assertIsNone(bezels.validate_png(path))
        width, height = struct.unpack(">II", path.read_bytes()[16:24])
        self.assertEqual((width, height), (1920, 1080))

    def test_its_centre_is_see_through_and_its_corner_is_not(self):
        try:
            import gi

            gi.require_version("GdkPixbuf", "2.0")
            from gi.repository import GdkPixbuf
        except (ImportError, ValueError):  # pragma: no cover - a venv without PyGObject
            self.skipTest("GdkPixbuf not available")
        pixbuf = GdkPixbuf.Pixbuf.new_from_file(str(bezels.BUILTIN[bezels.SIMPLE]))
        pixels, stride = pixbuf.get_pixels(), pixbuf.get_rowstride()

        def alpha(x, y):
            return pixels[y * stride + x * 4 + 3]

        self.assertEqual(alpha(960, 540), 0)
        self.assertEqual(alpha(0, 0), 255)


class ValidatingAnImageTests(_TmpCase):
    def test_a_large_enough_png_is_accepted(self):
        self.assertIsNone(bezels.validate_png(self.write("ok.png", png_bytes(1920, 1080))))

    def test_a_file_that_is_not_a_png_is_refused(self):
        self.assertEqual(bezels.validate_png(self.write("a.png", b"\xff\xd8\xff\xe0" * 10)),
                         "not_png")

    def test_a_truncated_header_is_not_a_png(self):
        self.assertEqual(bezels.validate_png(self.write("a.png", png_bytes(1920, 1080)[:20])),
                         "not_png")

    def test_a_png_whose_first_chunk_is_not_its_header_is_refused(self):
        data = bytearray(png_bytes(1920, 1080))
        data[12:16] = b"IDAT"
        self.assertEqual(bezels.validate_png(self.write("a.png", bytes(data))), "not_png")

    def test_a_tiny_png_is_too_small(self):
        self.assertEqual(bezels.validate_png(self.write("a.png", png_bytes(160, 120))),
                         "too_small")
        self.assertEqual(bezels.validate_png(self.write("b.png", png_bytes(1920, 100))),
                         "too_small")

    def test_a_file_over_the_cap_is_refused(self):
        path = self.write("big.png", png_bytes(1920, 1080))
        with mock.patch.object(bezels, "MAX_BYTES", 10):
            self.assertEqual(bezels.validate_png(path), "unreadable")

    def test_a_missing_file_is_unreadable(self):
        self.assertEqual(bezels.validate_png(self.tmp / "nope.png"), "unreadable")


class ImportingACustomImageTests(_TmpCase):
    def test_the_image_is_copied_under_the_console_name(self):
        source = self.write("My Frame.png", png_bytes(1920, 1080))
        stored = bezels.import_custom("PS", source, self.tmp / "bezels")
        self.assertEqual(stored, self.tmp / "bezels" / "PS.png")
        self.assertEqual(stored.read_bytes(), source.read_bytes())

    def test_an_alias_is_stored_under_the_canonical_id(self):
        source = self.write("a.png", png_bytes(1920, 1080))
        self.assertEqual(bezels.import_custom("SNES", source, self.tmp).name, "SFC.png")

    def test_a_new_image_replaces_the_old_one(self):
        bezels.import_custom("PS", self.write("a.png", png_bytes(1920, 1080)), self.tmp / "b")
        second = self.write("c.png", png_bytes(1280, 720))
        stored = bezels.import_custom("PS", second, self.tmp / "b")
        self.assertEqual(stored.read_bytes(), second.read_bytes())

    def test_a_failed_copy_leaves_no_temporary_file_and_raises(self):
        target = self.tmp / "bezels"
        with self.assertRaises(OSError):
            bezels.import_custom("PS", self.tmp / "missing.png", target)
        self.assertEqual(list(target.iterdir()), [])

    def test_a_temporary_file_that_cannot_be_removed_still_raises(self):
        target = self.tmp / "bezels"
        with mock.patch.object(bezels.os, "unlink", side_effect=OSError("busy")):
            with self.assertRaises(OSError):
                bezels.import_custom("PS", self.tmp / "missing.png", target)


class ResolvingTheImageTests(_TmpCase):
    def settings(self, **overrides):
        return {"console_overrides": overrides, "custom_names": {}, "custom_dir": self.tmp}

    def test_a_handheld_never_gets_one(self):
        self.assertIsNone(bezels.resolve_image("GBA", self.settings(GBA="simple")))

    def test_none_is_none(self):
        self.assertIsNone(bezels.resolve_image("MD", self.settings()))

    def test_simple_is_the_built_in_image(self):
        self.assertEqual(bezels.resolve_image("MD", self.settings(MD="simple")),
                         bezels.BUILTIN[bezels.SIMPLE])

    def test_custom_is_the_imported_image(self):
        stored = self.write("PS.png", png_bytes(1920, 1080))
        self.assertEqual(bezels.resolve_image("PS", self.settings(PS="custom")), stored)

    def test_a_missing_custom_image_warns_once_and_gives_none(self):
        bezels._warned_missing.clear()
        settings = self.settings(PS="custom")
        with self.assertLogs("openemux.core.bezels", level="WARNING") as logs:
            self.assertIsNone(bezels.resolve_image("PS", settings))
            self.assertIsNone(bezels.resolve_image("PS", settings))
        self.assertEqual(len(logs.records), 1)
        # Back again, it is used, and a later loss is reported anew.
        self.write("PS.png", png_bytes(1920, 1080))
        self.assertIsNotNone(bezels.resolve_image("PS", settings))
        self.assertNotIn(self.tmp / "PS.png", bezels._warned_missing)


class TheBezelsBoxTests(unittest.TestCase):
    def test_full_size_it_is_the_16_9_box_around_the_4_3_one(self):
        self.assertEqual(bezels.bezel_desc_geometry(), (0.5, 0.5, 2.0 / 3.0, 0.5))

    def test_with_the_margin_it_shrinks_about_the_top_centre(self):
        s = 1.0 - overlay_bar.MARGIN
        cx, cy, hw, hh = bezels.bezel_desc_geometry(overlay_bar.MARGIN)
        self.assertEqual(cx, 0.5)
        self.assertAlmostEqual(cy - hh, 0.0)  # its top stays on the window's
        self.assertAlmostEqual(hh * 2, s)
        self.assertAlmostEqual(hw, (2.0 / 3.0) * s)


if __name__ == "__main__":
    unittest.main()
