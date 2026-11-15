"""The console icon a sidebar row shows, and what happens when it is missing.

`ui/console_icons.py` loads OpenEmu's console PNGs once and caches the misses
too, so a console that ships no artwork does not re-stat the assets directory
on every card bind. What was never covered is the other side of that: the
console with no file at all, and the file that is there but will not decode --
both of which have to end as a themed icon rather than as a blank row.
"""

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.gtk_display import HAVE_DISPLAY, needs_display

if HAVE_DISPLAY:
    import gi

    gi.require_version("Gtk", "4.0")
    from gi.repository import Gdk, GLib, Gtk

    from openemux.ui import console_icons

FAKE = "NOT-A-CONSOLE"


@needs_display
class AConsoleWithNoArtworkTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(console_icons._TEXTURES.pop, FAKE, None)
        self.addCleanup(console_icons._SMALL_TEXTURES.pop, FAKE, None)

    def test_a_console_that_names_no_file_has_no_texture(self):
        self.assertIsNone(console_icons.console_texture(FAKE))

    def test_a_file_the_build_did_not_ship_is_not_looked_for_twice(self):
        with mock.patch.dict(
            console_icons.CONSOLE_ICON_FILES, {FAKE: "not-shipped@2x.png"}, clear=False
        ):
            self.assertIsNone(console_icons.console_texture(FAKE))
        self.assertIn(FAKE, console_icons._TEXTURES)

    def test_its_row_falls_back_to_the_themed_icon(self):
        image = console_icons.console_icon(FAKE)
        self.assertIsInstance(image, Gtk.Image)
        self.assertEqual(image.get_icon_name(), "applications-games-symbolic")


@needs_display
class AnIconThatWillNotDecodeTests(unittest.TestCase):
    """A truncated or replaced PNG must not take the sidebar down with it."""

    def setUp(self):
        self.addCleanup(console_icons._TEXTURES.pop, FAKE, None)
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.broken = self.tmp / "broken.png"
        self.broken.write_bytes(b"not a png at all")

    def test_the_console_ends_up_with_no_texture(self):
        with mock.patch.dict(
            console_icons.CONSOLE_ICON_FILES, {FAKE: "broken.png"}, clear=False
        ), mock.patch.object(
            console_icons, "asset_path", lambda _category, _name: self.broken
        ):
            with self.assertLogs("openemux.ui.console_icons", level="INFO"):
                self.assertIsNone(console_icons.console_texture(FAKE))


@needs_display
class TheSmallArtTests(unittest.TestCase):
    """The 1x (16-px) art Big Picture's chips draw below 1080p (issue 962)."""

    def setUp(self):
        self.addCleanup(console_icons._SMALL_TEXTURES.pop, FAKE, None)
        self.addCleanup(console_icons._SMALL_TEXTURES.pop, "SFC", None)

    def test_a_shipped_console_has_it_at_half_the_size(self):
        console_icons._SMALL_TEXTURES.pop("SFC", None)
        texture = console_icons.console_texture_1x("SFC")
        self.assertEqual(texture.get_width(), 16)
        self.assertIs(console_icons.console_texture_1x("SFC"), texture)  # cached

    def test_no_file_or_a_missing_one_is_none(self):
        self.assertIsNone(console_icons.console_texture_1x(FAKE))
        console_icons._SMALL_TEXTURES.pop(FAKE)
        with mock.patch.dict(console_icons.CONSOLE_ICON_FILES, {FAKE: "not-shipped@2x.png"}, clear=False):
            self.assertIsNone(console_icons.console_texture_1x(FAKE))

    def test_one_that_will_not_decode_is_none(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        broken = tmp / "broken.png"
        broken.write_bytes(b"not a png at all")
        with mock.patch.dict(console_icons.CONSOLE_ICON_FILES, {FAKE: "broken@2x.png"}, clear=False), \
                mock.patch.object(console_icons, "asset_path", lambda _category, _name: broken):
            with self.assertLogs("openemux.ui.console_icons", level="INFO"):
                self.assertIsNone(console_icons.console_texture_1x(FAKE))

    def test_the_views_have_a_glyph_and_consoles_none(self):
        from openemux.ui.scopes import ALL_CONSOLES_ID, FAVORITES_ID, RECENT_ID

        self.assertEqual(console_icons.scope_icon_name(ALL_CONSOLES_ID), "view-grid-symbolic")
        self.assertEqual(console_icons.scope_icon_name(FAVORITES_ID), "starred-symbolic")
        self.assertEqual(console_icons.scope_icon_name(RECENT_ID), "document-open-recent-symbolic")
        self.assertIsNone(console_icons.scope_icon_name("SFC"))
        favorites = console_icons.console_icon(FAVORITES_ID)
        self.assertTrue(favorites.has_css_class("favorites-sidebar-icon"))
        self.assertFalse(console_icons.console_icon(ALL_CONSOLES_ID).has_css_class("favorites-sidebar-icon"))


def _texture(pixels, width, height):
    """A straight-alpha RGBA texture from a flat list of (r, g, b, a)."""
    data = GLib.Bytes.new(bytes(channel for pixel in pixels for channel in pixel))
    return Gdk.MemoryTexture.new(width, height, Gdk.MemoryFormat.R8G8B8A8, data, width * 4)


def _pixels(texture):
    downloader = Gdk.TextureDownloader.new(texture)
    downloader.set_format(Gdk.MemoryFormat.R8G8B8A8)
    data, stride = downloader.download_bytes()
    raw = data.get_data()

    def at(x, y):
        start = y * stride + x * 4
        return tuple(raw[start:start + 4])

    return at


@needs_display
class ThePixelArtGeometryTests(unittest.TestCase):
    """Whole multiples counted in physical pixels (issue 966)."""

    def test_the_row_slot_takes_the_art_drawn_for_it_1_to_1(self):
        # Scale 1: the hand-drawn 16-px art, as is.
        self.assertEqual(console_icons.pick_pixel_art(16, 16, [32, 16], 1), (1, 0, 0, 16, True))
        # Scale 2: 32 physical pixels, so the 32-px art, as is (16 logical).
        self.assertEqual(console_icons.pick_pixel_art(16, 16, [32, 16], 2), (0, 0.0, 0.0, 16.0, True))

    def test_a_hidpi_slot_is_measured_in_physical_pixels(self):
        # 40 logical = 80 physical: the 32-px art at 2x, 64 physical = 32 logical,
        # centred 8 physical (4 logical) in.
        self.assertEqual(console_icons.pixel_icon_geometry(40, 40, 32, 2), (4.0, 4.0, 32.0, True))
        # Too small even at scale 2: the slot's size, smooth.
        self.assertEqual(console_icons.pixel_icon_geometry(10, 10, 32, 2), (0.0, 0.0, 10.0, False))

    def test_a_scale_below_one_counts_as_one(self):
        self.assertEqual(console_icons.pixel_icon_geometry(40, 40, 32, 0), (4, 4, 32, True))

    def test_the_seam_is_an_eighth_of_the_cell_and_never_nothing(self):
        self.assertEqual(console_icons.soft_grid_seam(4), 1)
        self.assertEqual(console_icons.soft_grid_seam(8), 1)
        self.assertEqual(console_icons.soft_grid_seam(12), 2)
        self.assertEqual(console_icons.soft_grid_seam(16), 2)
        self.assertEqual(console_icons.soft_grid_seam(20), 3)


@needs_display
class TheSoftGridTests(unittest.TestCase):
    """The POC's variant D: seams on opaque pixels only, in their colour at 80%."""

    def setUp(self):
        self.addCleanup(console_icons._GRIDDED.clear)
        # An opaque orange, a fully transparent pixel, a half-transparent white.
        self.art = _texture([(200, 100, 50, 255), (9, 9, 9, 0), (255, 255, 255, 128)], 3, 1)

    def test_every_opaque_pixel_gets_a_right_and_bottom_seam(self):
        gridded = console_icons.soft_grid_texture(self.art, 4)
        self.assertEqual((gridded.get_width(), gridded.get_height()), (12, 4))
        at = _pixels(gridded)
        # The cell itself: the pixel's colour.
        self.assertEqual(at(0, 0), (200, 100, 50, 255))
        self.assertEqual(at(2, 2), (200, 100, 50, 255))
        # Its right column and bottom row: the colour at 80%, the alpha kept.
        self.assertEqual(at(3, 0), (160, 80, 40, 255))
        self.assertEqual(at(0, 3), (160, 80, 40, 255))
        self.assertEqual(at(3, 3), (160, 80, 40, 255))
        # Half-transparent: the seam keeps its alpha too.
        self.assertEqual(at(8, 0), (255, 255, 255, 128))
        self.assertEqual(at(11, 1), (204, 204, 204, 128))

    def test_a_transparent_pixel_gets_nothing(self):
        at = _pixels(console_icons.soft_grid_texture(self.art, 4))
        for x in range(4, 8):
            for y in range(4):
                self.assertEqual(at(x, y), (0, 0, 0, 0))

    def test_a_wider_cell_gets_a_wider_seam(self):
        at = _pixels(console_icons.soft_grid_texture(self.art, 12))
        self.assertEqual(at(9, 0), (200, 100, 50, 255))
        self.assertEqual(at(10, 0), (160, 80, 40, 255))
        self.assertEqual(at(0, 9), (200, 100, 50, 255))
        self.assertEqual(at(0, 10), (160, 80, 40, 255))

    def test_it_is_built_once_per_art_and_cell(self):
        first = console_icons.soft_grid_texture(self.art, 4)
        self.assertIs(console_icons.soft_grid_texture(self.art, 4), first)
        self.assertIsNot(console_icons.soft_grid_texture(self.art, 5), first)


@needs_display
class TheRendererTests(unittest.TestCase):
    """``ConsolePixelArt`` draws crisp, with the grid from 4x up."""

    def setUp(self):
        self.addCleanup(console_icons._GRIDDED.clear)
        self.big = _texture([(255, 0, 0, 255)] * 32 * 32, 32, 32)
        self.small = _texture([(255, 0, 0, 255)] * 16 * 16, 16, 16)

    def _draw(self, art, width, height, scale=1):
        snapshot = Gtk.Snapshot()
        with mock.patch.object(art, "get_width", return_value=width), \
                mock.patch.object(art, "get_height", return_value=height), \
                mock.patch.object(art, "get_scale_factor", return_value=scale), \
                mock.patch.object(console_icons, "soft_grid_texture",
                                  wraps=console_icons.soft_grid_texture) as grid:
            art.do_snapshot(snapshot)
        return snapshot.to_node(), grid

    def test_a_missing_size_is_left_out(self):
        self.assertEqual(console_icons.ConsolePixelArt([self.big, None]).textures, [self.big])

    def test_below_4x_it_is_plain_nearest_neighbour(self):
        art = console_icons.ConsolePixelArt([self.big, self.small])
        node, grid = self._draw(art, 16, 16)
        self.assertEqual(node.get_bounds().get_width(), 16)
        grid.assert_not_called()
        node, grid = self._draw(art, 96, 96)  # the 32-px art at 3x
        self.assertEqual(node.get_bounds().get_width(), 96)
        grid.assert_not_called()

    def test_from_4x_it_draws_the_soft_grid_1_to_1(self):
        art = console_icons.ConsolePixelArt([self.big, self.small])
        node, grid = self._draw(art, 132, 132)  # the shelf's old 132-px box: 4x, centred
        grid.assert_called_once_with(self.big, 4)
        bounds = node.get_bounds()
        self.assertEqual((bounds.get_x(), bounds.get_width()), (2, 128))

    def test_hidpi_reaches_4x_at_half_the_logical_size(self):
        art = console_icons.ConsolePixelArt([self.big, self.small])
        node, grid = self._draw(art, 64, 64, scale=2)
        grid.assert_called_once_with(self.big, 4)
        self.assertEqual(node.get_bounds().get_width(), 64)

    def test_a_slot_smaller_than_every_art_is_drawn_smooth(self):
        art = console_icons.ConsolePixelArt([self.big, self.small])
        node, grid = self._draw(art, 10, 10)
        self.assertEqual(node.get_bounds().get_width(), 10)
        grid.assert_not_called()

    def test_no_room_draws_nothing(self):
        node, _grid = self._draw(console_icons.ConsolePixelArt([self.big]), 0, 0)
        self.assertIsNone(node)


@needs_display
class TheRowIconTests(unittest.TestCase):
    """Sidebar, preferences and dropdowns: 16 px, both art sizes (issue 966)."""

    def test_a_console_with_art_gets_the_renderer_at_16_px(self):
        icon = console_icons.console_icon("GB")
        self.assertIsInstance(icon, console_icons.ConsolePixelArt)
        self.assertEqual(icon.get_size_request(), (16, 16))
        self.assertEqual(sorted(t.get_width() for t in icon.textures), [16, 32])


if __name__ == "__main__":
    unittest.main()
