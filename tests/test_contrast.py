"""WCAG contrast math for the theme editor (issue 1011)."""

import unittest

from openemux.core.contrast import WCAG_AA, contrast_ratio, passes_aa, relative_luminance


class ContrastTests(unittest.TestCase):
    def test_black_and_white_are_the_extremes(self):
        self.assertAlmostEqual(relative_luminance("#000000"), 0.0)
        self.assertAlmostEqual(relative_luminance("#ffffff"), 1.0)
        self.assertAlmostEqual(contrast_ratio("#000000", "#ffffff"), 21.0)

    def test_a_color_against_itself_is_one(self):
        self.assertAlmostEqual(contrast_ratio("#3584e4", "#3584e4"), 1.0)

    def test_the_order_does_not_matter(self):
        self.assertAlmostEqual(
            contrast_ratio("#777777", "#ffffff"), contrast_ratio("#ffffff", "#777777")
        )

    def test_known_values_from_the_w3c_formula(self):
        # #777 on white is the classic "just fails AA" grey: 4.48:1.
        self.assertAlmostEqual(contrast_ratio("#777777", "#ffffff"), 4.48, places=2)
        # Dark channels take the linear branch of the sRGB curve.
        self.assertAlmostEqual(relative_luminance("#0a0a0a"), 0.003035, places=5)

    def test_aa_threshold(self):
        self.assertEqual(WCAG_AA, 4.5)
        self.assertFalse(passes_aa("#777777", "#ffffff"))
        self.assertTrue(passes_aa("#767676", "#ffffff"))


if __name__ == "__main__":
    unittest.main()
