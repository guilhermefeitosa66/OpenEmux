"""The fictional gameplay frames (issue #553): tools/demo_gameplay.py.

Loaded by file path -- tools/ is not a package. Checked for what the site's
images and the promo video depend on: native sizes, both DS screens, a clip
that actually moves, sharp enlargement, and byte-stable output.
"""

import contextlib
import importlib.util
import io
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from openemux.core.cartridge_render import rsvg_available

_TOOL = Path(__file__).parent.parent / "tools" / "demo_gameplay.py"
_spec = importlib.util.spec_from_file_location("demo_gameplay", _TOOL)
demo_gameplay = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(demo_gameplay)
demo_library = demo_gameplay.demo_library

from gi.repository import GdkPixbuf  # noqa: E402  (versioned by demo_library)


def _pixbuf(png):
    loader = GdkPixbuf.PixbufLoader.new_with_type("png")
    loader.write(png)
    loader.close()
    return loader.get_pixbuf()


class CatalogueTests(unittest.TestCase):
    def test_every_title_is_in_the_demo_catalogue(self):
        for console, title in demo_gameplay.GAMEPLAY.items():
            self.assertIn(title, demo_library.TITLES[console], console)

    def test_every_console_has_a_native_size(self):
        self.assertEqual(set(demo_gameplay.GAMEPLAY), set(demo_gameplay.NATIVE))

    def test_the_ds_frame_holds_both_screens(self):
        w, h = demo_gameplay.NATIVE["NDS"]
        self.assertEqual(demo_gameplay.size("NDS"), (w, 2 * h))
        self.assertEqual(demo_gameplay.size("GBA"), demo_gameplay.NATIVE["GBA"])


class ViewTests(unittest.TestCase):
    def test_a_still_frame_is_the_framed_view(self):
        self.assertEqual(demo_gameplay.view("SFC", 0, 1), demo_gameplay.view("SFC", 0, 1))

    def test_a_clip_pans_and_stays_inside_the_scene(self):
        for console in demo_gameplay.GAMEPLAY:
            views = [demo_gameplay.view(console, step, 5) for step in range(5)]
            self.assertNotEqual(views[0], views[-1], console)
            for x, y, w, h in views:
                self.assertGreaterEqual(x, -1e-9)
                self.assertGreaterEqual(y, -1e-9)
                self.assertLessEqual(x + w, demo_library.SCENE_W + 1e-9)
                self.assertLessEqual(y + h, demo_library.SCENE_H + 1e-9)

    def test_a_tall_framing_pans_sideways(self):
        tall = (20, 0, 60, demo_library.SCENE_H)
        with mock.patch.object(demo_library, "crop_view", return_value=tall):
            first, last = demo_gameplay.view("GBA", 0, 3), demo_gameplay.view("GBA", 2, 3)
        self.assertEqual((first[1], last[1]), (0, 0))
        self.assertLess(first[0], last[0])

    def test_the_view_has_the_screen_shape_under_the_hud(self):
        w, h = demo_gameplay.NATIVE["MD"]
        _, _, vw, vh = demo_gameplay.view("MD", 0, 1)
        self.assertAlmostEqual(vw / vh, w / (h - demo_gameplay.HUD_H))


class SvgTests(unittest.TestCase):
    def test_unknown_console_is_refused(self):
        with self.assertRaises(KeyError):
            demo_gameplay.frame_svg("SNES")

    def test_the_hud_counts_up_through_a_clip(self):
        self.assertNotEqual(demo_gameplay.hud("GBA", 0, 240), demo_gameplay.hud("GBA", 3, 240))

    def test_pixel_consoles_draw_on_the_native_cell(self):
        svg = demo_gameplay.frame_svg("GB")
        self.assertIn('shape-rendering="crispEdges"', svg)
        self.assertIn(f'height="{demo_gameplay.PIXEL_CELL}"', svg)

    def test_the_ds_menu_follows_the_genre(self):
        self.assertEqual(demo_library.GENRE[demo_gameplay.GAMEPLAY["NDS"]], "rpg")
        rpg = demo_gameplay.ds_menu(192)
        with mock.patch.dict(demo_gameplay.GAMEPLAY, {"NDS": "Brain Math Trainer"}):
            other = demo_gameplay.ds_menu(192)
        self.assertNotEqual(rpg, other)


@unittest.skipUnless(rsvg_available(), "librsvg typelib not installed")
class RenderTests(unittest.TestCase):
    def test_each_frame_is_the_native_size(self):
        for console in demo_gameplay.GAMEPLAY:
            pixbuf = _pixbuf(demo_gameplay.render(console))
            self.assertEqual((pixbuf.get_width(), pixbuf.get_height()),
                             demo_gameplay.size(console), console)

    def test_scale_enlarges_without_smoothing(self):
        small = _pixbuf(demo_gameplay.render("GB"))
        big = _pixbuf(demo_gameplay.render("GB", scale=3))
        self.assertEqual(big.get_width(), small.get_width() * 3)
        sp, bp = small.get_pixels(), big.get_pixels()
        sr, br, n = small.get_rowstride(), big.get_rowstride(), small.get_n_channels()
        for x, y in [(0, 0), (40, 70), (159, 143)]:
            self.assertEqual(sp[y * sr + x * n:y * sr + x * n + 3],
                             bp[(3 * y + 2) * br + (3 * x + 2) * n:(3 * y + 2) * br + (3 * x + 2) * n + 3])

    def test_rendering_is_byte_stable(self):
        self.assertEqual(demo_gameplay.render("SFC"), demo_gameplay.render("SFC"))

    def test_clip_frames_differ(self):
        self.assertNotEqual(demo_gameplay.render("MD", 0, 3), demo_gameplay.render("MD", 2, 3))


@unittest.skipUnless(rsvg_available(), "librsvg typelib not installed")
class CliTests(unittest.TestCase):
    def test_writes_one_file_per_console(self):
        with TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(demo_gameplay.main([tmp, "--console", "GB", "--console", "NDS"]), 0)
            names = sorted(p.name for p in Path(tmp).iterdir())
        self.assertEqual(names, ["gb-island-hero-quest.png", "nds-dual-screen-dragon.png"])
        self.assertEqual(len(out.getvalue().splitlines()), 2)

    def test_frames_are_numbered(self):
        with TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            demo_gameplay.main([tmp, "--console", "GBA", "--frames", "2", "--scale", "2"])
            names = sorted(p.name for p in Path(tmp).iterdir())
        self.assertEqual(names, ["gba-cosmic-fox-pilot-00.png", "gba-cosmic-fox-pilot-01.png"])

    def test_every_console_by_default(self):
        with TemporaryDirectory() as tmp:
            written = demo_gameplay.write(tmp)
        self.assertEqual(len(written), len(demo_gameplay.GAMEPLAY))

    def test_bad_counts_are_refused(self):
        with TemporaryDirectory() as tmp, contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                demo_gameplay.main([tmp, "--scale", "0"])


if __name__ == "__main__":
    unittest.main()
