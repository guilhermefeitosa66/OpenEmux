"""The Big Picture shelf's console colors and short names (issue 957)."""

import re
import unittest

from openemux.core import big_picture_shelf as shelf
from openemux.core.systems import SYSTEM_IDS


class TheShelfTables(unittest.TestCase):
    def test_every_console_has_a_color_and_a_short_name(self):
        self.assertEqual(set(shelf.SHELF_COLORS), set(SYSTEM_IDS))
        self.assertEqual(set(shelf.SHORT_NAMES), set(SYSTEM_IDS))
        for color in shelf.SHELF_COLORS.values():
            self.assertRegex(color, r"^#[0-9A-F]{6}$")

    def test_the_android_values_are_kept(self):
        # A few spot checks against Console.kt: NES red, GBA indigo, SNES "SNES".
        self.assertEqual(shelf.shelf_color("FC"), "#7A2E2E")
        self.assertEqual(shelf.shelf_color("GBA"), "#3B3486")
        self.assertEqual(shelf.short_name("SFC"), "SNES")
        self.assertEqual(shelf.short_name("PS"), "PS1")

    def test_an_unknown_console_falls_back(self):
        self.assertEqual(shelf.shelf_color("NOPE"), shelf.FALLBACK_COLOR)
        self.assertEqual(shelf.shelf_color(None), shelf.FALLBACK_COLOR)
        self.assertEqual(shelf.short_name("nope"), "NOPE")
        self.assertEqual(shelf.short_name(None), "")

    def test_the_css_class_is_a_safe_name(self):
        self.assertEqual(shelf.css_class("FC"), "bp-shelf-fc")
        self.assertEqual(shelf.css_class("SG1000"), "bp-shelf-sg1000")
        self.assertEqual(shelf.css_class(""), "bp-shelf-none")
        for console in SYSTEM_IDS:
            self.assertTrue(re.fullmatch(r"bp-shelf-[a-z0-9]+", shelf.css_class(console)))

    def test_full_name(self):
        self.assertEqual(shelf.full_name("FC", "Nintendo (NES)"), "NES - Nintendo (NES)")


if __name__ == "__main__":
    unittest.main()
