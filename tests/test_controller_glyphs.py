"""The button labels the hint bar draws per controller family (issue 914)."""

import unittest

from openemux.core import controller_glyphs as cg


class FamilyDetectionTests(unittest.TestCase):
    def test_the_pads_name_picks_the_family(self):
        self.assertEqual(cg.family_for_name("Microsoft Xbox Series X Controller"), cg.XBOX)
        self.assertEqual(cg.family_for_name("Sony Interactive Entertainment DualSense"), cg.PLAYSTATION)
        self.assertEqual(cg.family_for_name("Nintendo Switch Pro Controller"), cg.NINTENDO)
        self.assertEqual(cg.family_for_name("8BitDo SN30"), cg.GENERIC)
        self.assertEqual(cg.family_for_name(None), cg.GENERIC)

    def test_the_preference_wins_over_the_pad_unless_it_is_auto(self):
        self.assertEqual(cg.resolve_family(cg.NINTENDO, "Xbox"), cg.NINTENDO)
        self.assertEqual(cg.resolve_family(cg.AUTO, "Xbox"), cg.XBOX)
        self.assertEqual(cg.resolve_family("junk", "DualShock 4"), cg.PLAYSTATION)


class GlyphTableTests(unittest.TestCase):
    def test_each_family_names_its_south_button_as_confirm(self):
        self.assertEqual(cg.glyphs(cg.XBOX)["confirm"], "A")
        self.assertEqual(cg.glyphs(cg.NINTENDO)["confirm"], "B")
        self.assertEqual(cg.glyphs(cg.PLAYSTATION)["confirm"], "✕")
        self.assertEqual(cg.glyphs(cg.GENERIC)["context"], "X")
        self.assertEqual(cg.glyphs("unknown")["back"], "B")

    def test_the_swap_trades_confirm_and_back_in_the_labels_too(self):
        swapped = cg.glyphs(cg.XBOX, swap_confirm_cancel=True)
        self.assertEqual((swapped["confirm"], swapped["back"]), ("B", "A"))
        self.assertEqual(swapped["confirm_hold"], "B⏳")

    def test_the_other_labels_are_plain_text_the_keycap_frames(self):
        g = cg.glyphs(cg.PLAYSTATION)
        self.assertEqual(g["consoles"], "L1/R1")
        self.assertEqual(g["start"], "Options")
        self.assertEqual(g["menu"], "Share")
        # The Guide button, which Big Picture hangs on (issue 914).
        self.assertEqual(g["guide"], "PS")
        self.assertEqual(cg.glyphs(cg.NINTENDO)["guide"], "Home")
        self.assertEqual(cg.glyphs(cg.XBOX)["guide"], "Guide")
        self.assertNotIn("Ⓐ", "".join(g.values()))


if __name__ == "__main__":
    unittest.main()
