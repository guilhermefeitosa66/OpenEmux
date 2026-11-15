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
    from gi.repository import Gtk

    from openemux.ui import console_icons

FAKE = "NOT-A-CONSOLE"


@needs_display
class AConsoleWithNoArtworkTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(console_icons._TEXTURES.pop, FAKE, None)

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


if __name__ == "__main__":
    unittest.main()
