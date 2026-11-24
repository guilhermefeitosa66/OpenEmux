"""The theme editor's drawn preview (issue 1011)."""

import unittest

import cairo

from tests.gtk_display import HAVE_DISPLAY, needs_display

if HAVE_DISPLAY:
    from openemux.core.custom_themes import Theme
    from openemux.ui.theme_preview import (
        NARROW_PREVIEW_HEIGHT,
        PREVIEW_HEIGHT,
        ThemePreview,
        draw_preview,
    )

LABELS = {
    "title": "Super Nintendo",
    "consoles": ["Super Nintendo", "Game Boy Advance", "Mega Drive"],
    "favorites": "Favorites",
    "games": ["Star Pilot", "Cave Run", "Puzzle Tower"],
    "console": "SNES",
    "played": "Last played yesterday",
    "play": "Play",
}


def _pixel(surface, x, y):
    surface.flush()
    data = surface.get_data()
    offset = y * surface.get_stride() + x * 4
    b, g, r = data[offset], data[offset + 1], data[offset + 2]
    return f"#{r:02x}{g:02x}{b:02x}"


@needs_display
class DrawPreviewTests(unittest.TestCase):
    def colors(self, **changes):
        return Theme("t", "T", "dark", changes).effective_values()

    def draw(self, width, height, colors):
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
        draw_preview(cairo.Context(surface), width, height, colors, LABELS)
        return surface

    def test_wide_shows_sidebar_library_and_details(self):
        surface = self.draw(
            640, 300, self.colors(sidebar_bg="#ff0000", library_bg="#00ff00",
                                  details_bg="#0000ff", headerbar_bg="#123456"),
        )
        self.assertEqual(_pixel(surface, 5, 250), "#ff0000")
        self.assertEqual(_pixel(surface, 300, 290), "#00ff00")
        self.assertEqual(_pixel(surface, 600, 290), "#0000ff")
        self.assertEqual(_pixel(surface, 300, 3), "#123456")

    def test_narrow_drops_the_details_pane(self):
        surface = self.draw(380, 170, self.colors(details_bg="#0000ff", library_bg="#00ff00"))
        self.assertEqual(_pixel(surface, 370, 160), "#00ff00")


@needs_display
class ThemePreviewWidgetTests(unittest.TestCase):
    def test_it_repaints_with_new_colors(self):
        colors = Theme("t", "T", "light").effective_values()
        preview = ThemePreview(LABELS, colors)
        self.assertEqual(preview.get_content_height(), PREVIEW_HEIGHT)
        self.assertGreater(PREVIEW_HEIGHT, NARROW_PREVIEW_HEIGHT)
        changed = dict(colors, library_bg="#00ff00")
        preview.set_colors(changed)
        self.assertIs(preview.colors, changed)
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 640, 300)
        preview._draw(None, cairo.Context(surface), 640, 300)
        self.assertEqual(_pixel(surface, 300, 290), "#00ff00")
        # The rounded corner is clipped away.
        self.assertEqual(surface.get_data()[3], 0)


if __name__ == "__main__":
    unittest.main()
