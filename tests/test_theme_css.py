"""A custom theme's generated stylesheet (issue 1011)."""

import unittest

from openemux.core.custom_themes import THEME_KEYS
from openemux.ui.theme_css import APP_RULES, NAMED_COLORS, stylesheet


class StylesheetTests(unittest.TestCase):
    def test_no_values_no_css(self):
        self.assertEqual(stylesheet({}), "")
        self.assertEqual(stylesheet({}, css_variables=True), "")

    def test_every_key_has_somewhere_to_go(self):
        for spec in THEME_KEYS:
            self.assertTrue(spec.key in NAMED_COLORS or spec.key in APP_RULES, spec.key)

    def test_named_colors_are_overridden(self):
        css = stylesheet({"window_bg": "#112233", "accent_button_bg": "#ff7800"})
        self.assertIn("@define-color window_bg_color #112233;", css)
        self.assertIn("@define-color accent_bg_color #ff7800;", css)
        self.assertNotIn(":root", css)
        self.assertNotIn("card_bg_color", css)

    def test_libadwaita_variables_only_when_asked(self):
        css = stylesheet({"popover_bg": "#101010"}, css_variables=True)
        self.assertIn(":root {", css)
        self.assertIn("--popover-bg-color: #101010;", css)
        self.assertIn("--dialog-bg-color: #101010;", css)

    def test_app_rules_for_what_has_no_named_color(self):
        css = stylesheet({
            "library_bg": "#202020", "text_secondary": "#999999", "selection_bg": "#334455",
        }, css_variables=True)
        self.assertIn(".library-area { background-color: #202020; }", css)
        self.assertIn("row .subtitle { color: #999999; opacity: 1; }", css)
        self.assertIn(".navigation-sidebar > row:selected { background-color: #334455; }", css)
        # Rules are never inside :root, and no variables for app rules.
        self.assertFalse(any(line.startswith("  --library") for line in css.splitlines()))

    def test_only_validated_values_are_written(self):
        css = stylesheet({
            "card_bg": "red; } * { color: blue",
            "window_bg": 12,
            "not_a_key": "#000000",
            "accent": "ABC",
        })
        self.assertEqual(css, "@define-color accent_color #aabbcc;\n")


if __name__ == "__main__":
    unittest.main()
