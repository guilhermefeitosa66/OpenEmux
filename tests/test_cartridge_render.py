import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from openemux.core import cartridge_render
from openemux.core.cartridge_render import (
    CartridgeFrame,
    CartridgeFrameError,
    load_frame,
    render_cartridge,
    rsvg_available,
)

FRAME = (
    Path(__file__).resolve().parents[1]
    / "src" / "openemux" / "ui" / "assets" / "images" / "cartridges" / "GB.svg"
)

# A frame whose label object is a rotated rect named only by inkscape:label,
# so both the label lookup and non-axis-aligned shapes are exercised.
FIXTURE_SVG = """<?xml version="1.0"?>
<svg xmlns="http://www.w3.org/2000/svg"
     xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"
     width="100" height="50" viewBox="0 0 100 50">
  <rect id="marker" inkscape:label="label-clip" x="20" y="10" width="40" height="20"
        transform="rotate(10 40 20)" fill="#00ff00"/>
  <rect id="art" x="0" y="40" width="100" height="10" fill="#112233"/>
</svg>
"""


def _write_cover(path, size=(64, 64), color=(255, 0, 0)):
    """Minimal solid-colour PNG, written with the same stack the app uses."""
    import gi

    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf

    pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, *size)
    r, g, b = color
    pixbuf.fill((r << 24) | (g << 16) | (b << 8) | 0xFF)
    pixbuf.savev(str(path), "png", [], [])
    return path


@unittest.skipUnless(rsvg_available(), "librsvg typelib (gir1.2-rsvg-2.0) not installed")
class CartridgeFrameTests(unittest.TestCase):
    def test_ships_frame_exposes_intrinsic_size_and_clip(self):
        frame = CartridgeFrame(FRAME)
        self.assertEqual((frame.width, frame.height), (177.0, 200.0))
        self.assertEqual(frame.size_for_width(200), (200, 226))

    def test_label_object_found_by_inkscape_label(self):
        with TemporaryDirectory() as tmp:
            svg = Path(tmp) / "X.svg"
            svg.write_text(FIXTURE_SVG)
            frame = CartridgeFrame(svg)
            self.assertEqual(frame.clip_id, "marker")

    def test_label_bbox_scales_with_output_size(self):
        with TemporaryDirectory() as tmp:
            svg = Path(tmp) / "X.svg"
            svg.write_text(FIXTURE_SVG)
            frame = CartridgeFrame(svg)
            x1, y1, w1, h1 = frame._label_bbox(100, 50)
            x2, y2, w2, h2 = frame._label_bbox(200, 100)
            self.assertAlmostEqual(w2, w1 * 2, places=3)
            self.assertAlmostEqual(x2, x1 * 2, places=3)
            # Rotated, so the bbox is wider than the rect's own 40x20.
            self.assertGreater(w1, 40)

    def test_missing_marker_is_rejected(self):
        with TemporaryDirectory() as tmp:
            svg = Path(tmp) / "X.svg"
            svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"/>')
            with self.assertRaises(CartridgeFrameError):
                CartridgeFrame(svg)

    def test_cover_lands_inside_the_label_and_never_outside(self):
        with TemporaryDirectory() as tmp:
            cover = _write_cover(Path(tmp) / "c.png", color=(255, 0, 0))
            frame = CartridgeFrame(FRAME)
            surface = frame.render(str(cover), width=177)
            self.assertEqual((surface.get_width(), surface.get_height()), (177, 200))

            data = surface.get_data()
            stride = surface.get_stride()

            def pixel(x, y):
                offset = y * stride + x * 4
                b, g, r, a = data[offset:offset + 4]
                return r, g, b, a

            bx, by, bw, bh = frame._label_bbox(177, 200)
            centre = pixel(int(bx + bw / 2), int(by + bh / 2))
            self.assertGreater(centre[0], 200)  # red cover shows through
            self.assertLess(centre[1], 60)
            # A point well outside the label is cartridge art, not cover.
            self.assertLess(pixel(int(bx + bw / 2), 5)[0] - pixel(int(bx + bw / 2), 5)[2], 40)


@unittest.skipUnless(rsvg_available(), "librsvg typelib (gir1.2-rsvg-2.0) not installed")
class CartridgeCacheTests(unittest.TestCase):
    def test_cold_render_then_cache_hit(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            cover = _write_cover(base / "c.png")
            first = render_cartridge(str(cover), FRAME, "GB", "Game", 100, cache_dir=base / "cache")
            self.assertIsNotNone(first)
            self.assertTrue(first.exists())
            stamp = first.stat().st_mtime_ns
            second = render_cartridge(str(cover), FRAME, "GB", "Game", 100, cache_dir=base / "cache")
            self.assertEqual(first, second)
            self.assertEqual(stamp, second.stat().st_mtime_ns)

    def test_replacing_the_cover_invalidates_the_composite(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            cover = _write_cover(base / "c.png", color=(255, 0, 0))
            first = render_cartridge(str(cover), FRAME, "GB", "Game", 100, cache_dir=base / "cache")
            _write_cover(cover, size=(32, 32), color=(0, 0, 255))
            second = render_cartridge(str(cover), FRAME, "GB", "Game", 100, cache_dir=base / "cache")
            self.assertNotEqual(first, second)
            self.assertFalse(first.exists())  # stale composite is dropped
            self.assertTrue(second.exists())

    def test_blank_cartridge_without_cover(self):
        with TemporaryDirectory() as tmp:
            out = render_cartridge(None, FRAME, "GB", "Game", 100, cache_dir=Path(tmp))
            self.assertIsNotNone(out)
            self.assertTrue(out.exists())

    def test_unusable_frame_degrades_to_none(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            svg = base / "Broken.svg"
            svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"/>')
            self.assertIsNone(load_frame(svg))
            self.assertIsNone(load_frame(base / "does-not-exist.svg"))
            self.assertIsNone(render_cartridge(None, svg, "GB", "Game", cache_dir=base / "cache"))


class RsvgUnavailableTests(unittest.TestCase):
    def test_frame_creation_reports_missing_typelib(self):
        original = cartridge_render.Rsvg
        cartridge_render.Rsvg = None
        cartridge_render._FRAMES.clear()
        try:
            self.assertFalse(cartridge_render.rsvg_available())
            with self.assertRaises(CartridgeFrameError):
                CartridgeFrame(FRAME)
            self.assertIsNone(load_frame(FRAME))
        finally:
            cartridge_render.Rsvg = original
            cartridge_render._FRAMES.clear()


if __name__ == "__main__":
    unittest.main()
