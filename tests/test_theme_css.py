"""A custom theme's generated stylesheet (issue 1011)."""

import unittest

from openemux.core.custom_themes import THEME_KEYS
from openemux.ui.theme_css import (
    APP_RULES,
    IMAGE_KEYS,
    LAYOUT_KEYS,
    NAMED_COLORS,
    SHAPE_KEYS,
    layout_metrics,
    stylesheet,
)


class StylesheetTests(unittest.TestCase):
    def test_no_values_no_css(self):
        self.assertEqual(stylesheet({}), "")
        self.assertEqual(stylesheet({}, css_variables=True), "")

    def test_every_key_has_somewhere_to_go(self):
        for spec in THEME_KEYS:
            self.assertTrue(
                spec.key in NAMED_COLORS or spec.key in APP_RULES or spec.key in SHAPE_KEYS
                or spec.key in LAYOUT_KEYS or spec.key in IMAGE_KEYS,
                spec.key,
            )

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



class ShapeRuleTests(unittest.TestCase):
    def test_nothing_changed_nothing_written(self):
        self.assertEqual(stylesheet({}, base="light"), "")

    def test_corner_radius(self):
        css = stylesheet({"corner_radius": 20})
        self.assertIn(".card, .boxed-list", css)
        self.assertIn("{ border-radius: 20px; }", css)
        self.assertIn("button, entry, .navigation-sidebar > row, .rom-row { border-radius: 10px; }", css)
        self.assertIn(".rom-cover, .rom-cover-backdrop { border-radius: 16px; }", css)
        self.assertIn(".rom-cover, .rom-cover-backdrop { border-radius: 0px; }",
                      stylesheet({"corner_radius": 2}))

    def test_border_width_uses_the_border_color_or_the_bases(self):
        self.assertIn("border: 2px solid #454545;", stylesheet({"border_width": 2}, base="dark"))
        self.assertIn("border: 2px solid #dcdcdc;", stylesheet({"border_width": 2}, base="light"))
        css = stylesheet({"border_width": 1, "border_color": "#ff0000"}, css_variables=True)
        self.assertIn("border: 1px solid #ff0000;", css)
        self.assertIn("@define-color borders #ff0000;", css)
        self.assertIn("--border-color: #ff0000;", css)
        self.assertIn("{ border: none; }", stylesheet({"border_width": 0}))

    def test_shadows(self):
        self.assertIn("box-shadow: 0 5px 14px rgba(0, 0, 0, 0.80);", stylesheet({"shadow_strength": 80}))
        self.assertIn("rgba(255, 0, 0, 0.35)", stylesheet({"shadow_color": "#ff0000"}))
        self.assertIn("{ box-shadow: none; }", stylesheet({"shadow_strength": 0}))

    def test_icons(self):
        css = stylesheet({"sidebar_icon_size": 24, "toolbar_icon_size": 20, "icon_color": "#00ff00"})
        self.assertIn(".navigation-sidebar image { -gtk-icon-size: 24px; }", css)
        self.assertIn("headerbar image { -gtk-icon-size: 20px; }", css)
        self.assertIn("headerbar image, .navigation-sidebar image { color: #00ff00; }", css)

    def test_typography(self):
        self.assertIn('window { font-family: "Noto Sans"; font-size: 120%; }',
                      stylesheet({"font_family": "Noto Sans", "font_scale": 120}))
        self.assertIn("window { font-size: 90%; }", stylesheet({"font_scale": 90}))
        self.assertEqual(stylesheet({"font_family": 'x"; } *{'}), "")

    def test_density(self):
        css = stylesheet({"density": 80})
        self.assertIn("min-height: 40px;", css)
        self.assertIn(".rom-card { padding: 6px; }", css)
        self.assertIn("headerbar { min-height: 38px; }", css)

    def test_layout_keys_are_not_css(self):
        values = {"grid_gap": 8, "card_scale": 150, "sidebar_width": 200}
        self.assertEqual(stylesheet(values), "")
        self.assertEqual(layout_metrics(values), values)
        self.assertEqual(layout_metrics({"grid_gap": 999, "card_scale": "x", "window_bg": "#000000"}),
                         {"grid_gap": 48})


class BackgroundRuleTests(unittest.TestCase):
    def test_each_fit(self):
        for fit, size, repeat in (("cover", "cover", "no-repeat"),
                                  ("contain", "contain", "no-repeat"),
                                  ("tile", "auto", "repeat"),
                                  ("bogus", "cover", "no-repeat")):
            css = stylesheet({}, backgrounds={"library": {"uri": "file:///c/a.png", "fit": fit}})
            self.assertIn(
                f'.library-area {{ background-image: url("file:///c/a.png"); background-size: {size}; '
                f"background-repeat: {repeat}; background-position: center; }}", css)

    def test_sidebar_area(self):
        css = stylesheet({}, backgrounds={"sidebar": {"uri": "file:///c/s.png", "fit": "cover"}})
        self.assertIn(".console-sidebar-pane { background-image", css)

    def test_unsafe_uris_are_dropped(self):
        for uri in ("http://x/a.png", 'file:///a".png', "file:///a).png", "file:///a\\b",
                    "file:///a\nb", ""):
            self.assertEqual(stylesheet({}, backgrounds={"library": {"uri": uri, "fit": "cover"}}), "", uri)
        self.assertEqual(stylesheet({}, backgrounds={"library": None}), "")


class ParseTests(unittest.TestCase):
    """Every rule must parse on the GTK the host runs: one error drops the provider."""

    def test_everything_parses(self):
        try:
            import gi
            gi.require_version("Gtk", "4.0")
            from gi.repository import Gtk
        except (ImportError, ValueError):  # pragma: no cover - a host without GTK 4
            self.skipTest("GTK 4 is not importable")
        values = {
            "window_bg": "#101010", "border_color": "#123456", "border_width": 2,
            "corner_radius": 20, "shadow_color": "#ff0000", "shadow_strength": 60,
            "sidebar_icon_size": 24, "toolbar_icon_size": 20, "icon_color": "#00ff00",
            "font_family": "Noto Sans", "font_scale": 120, "density": 80,
            "text_secondary": "#999999",
        }
        backgrounds = {"library": {"uri": "file:///tmp/a%20b.png", "fit": "tile"},
                       "sidebar": {"uri": "file:///tmp/s.png", "fit": "contain"}}
        for variables in (False, True):
            if variables:
                # libadwaita 1.6's variable syntax: only checked where GTK has it.
                if (Gtk.get_major_version(), Gtk.get_minor_version()) < (4, 16):
                    continue  # pragma: no cover - depends on the GTK of the run
            errors = []
            provider = Gtk.CssProvider()
            provider.connect("parsing-error", lambda _p, _s, error: errors.append(error.message))
            provider.load_from_string(stylesheet(values, css_variables=variables,
                                                 backgrounds=backgrounds))
            self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
