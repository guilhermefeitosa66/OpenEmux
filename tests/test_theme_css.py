"""A custom theme's generated stylesheet (issue 1011)."""

import unittest

from openemux.core.contrast import WCAG_AA, contrast_ratio
from openemux.core.custom_themes import THEME_KEYS, readable_on
from openemux.ui.theme_css import (
    APP_RULES,
    BIG_PICTURE_KEYS,
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
                or spec.key in LAYOUT_KEYS or spec.key in IMAGE_KEYS
                or spec.key in BIG_PICTURE_KEYS,
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
        # The strength is a fraction (0.8), written as the shadow's alpha.
        self.assertIn("box-shadow: 0 5px 13px rgba(0, 0, 0, 0.80);", stylesheet({"shadow_strength": 0.8}))
        # Only the color changed: the base's 0.35.
        self.assertIn("box-shadow: 0 3px 8px rgba(255, 0, 0, 0.35);",
                      stylesheet({"shadow_color": "#ff0000"}))
        self.assertIn("{ box-shadow: none; }", stylesheet({"shadow_strength": 0}))
        # Out of range is clamped before it is written.
        self.assertIn("rgba(0, 0, 0, 1.00)", stylesheet({"shadow_strength": 80}))

    def test_icons(self):
        css = stylesheet({"icon_scale": 1.5, "icon_color": "#00ff00"})
        self.assertIn("headerbar image, .navigation-sidebar image { -gtk-icon-size: 24px; }", css)
        self.assertIn("headerbar image, .navigation-sidebar image { color: #00ff00; }", css)
        self.assertIn("-gtk-icon-size: 12px;", stylesheet({"icon_scale": 0.75}))
        self.assertIn("-gtk-icon-size: 18px;", stylesheet({"icon_scale": 1.1}))
        self.assertNotIn("-gtk-icon-size", stylesheet({"icon_color": "#00ff00"}))

    def test_typography(self):
        self.assertIn('window { font-family: "Noto Sans"; font-size: 120%; }',
                      stylesheet({"font_family": "Noto Sans", "font_scale": 1.2}))
        self.assertIn("window { font-size: 90%; }", stylesheet({"font_scale": 0.9}))
        self.assertIn("window { font-size: 130%; }", stylesheet({"font_scale": 120}))
        self.assertEqual(stylesheet({"font_family": 'x"; } *{'}), "")

    def test_density_choice(self):
        css = stylesheet({"density": "compact"})
        # 0.85 of libadwaita's sizes.
        self.assertIn(".boxed-list > row, list.boxed-list > row { min-height: 42px; }", css)
        self.assertIn(".rom-card { padding: 7px; }", css)
        self.assertIn("headerbar { min-height: 40px; }", css)
        roomy = stylesheet({"density": "comfortable"})
        self.assertIn("headerbar { min-height: 54px; }", roomy)
        self.assertIn("headerbar { min-height: 47px; }", stylesheet({"density": "default"}))
        self.assertEqual(stylesheet({"density": 80}), "")

    def test_density_fine_multiplies_the_choice(self):
        # Only the fine factor changed: on the base's "default".
        css = stylesheet({"density_fine": 0.8})
        self.assertIn(".boxed-list > row, list.boxed-list > row { min-height: 40px; }", css)
        self.assertIn(".rom-card { padding: 6px; }", css)
        self.assertIn("headerbar { min-height: 38px; }", css)
        both = stylesheet({"density": "comfortable", "density_fine": 1.2})
        # 47 * 1.15 * 1.2 = 64.9
        self.assertIn("headerbar { min-height: 65px; }", both)

    def test_layout_keys_are_not_css(self):
        values = {"grid_gap": 8, "card_scale": 1.5, "sidebar_width": 200}
        self.assertEqual(stylesheet(values), "")
        self.assertEqual(layout_metrics(values), values)
        self.assertEqual(layout_metrics({"grid_gap": 999, "card_scale": "x", "window_bg": "#000000"}),
                         {"grid_gap": 32})
        self.assertEqual(layout_metrics({"card_scale": 1.234}), {"card_scale": 1.23})


class SelectedRowTests(unittest.TestCase):
    RULE = ".navigation-sidebar > row:selected, .navigation-sidebar > row:selected label"

    def _color(self, css):
        for line in css.splitlines():
            if line.startswith(self.RULE):
                return line.split("color: ", 1)[1].split(";", 1)[0]
        return None

    def test_not_written_when_neither_key_changed(self):
        self.assertIsNone(self._color(stylesheet({"window_bg": "#101010"})))
        self.assertIsNone(self._color(stylesheet({"sidebar_bg": "#101010"}, base="light")))

    def test_a_readable_text_is_kept_as_picked(self):
        css = stylesheet({"sidebar_text_primary": "#ffffff", "selection_bg": "#202020"})
        self.assertEqual(self._color(css), "#ffffff")

    def test_text_is_taken_until_it_reads_on_the_selection(self):
        # White sidebar text on a light selection: pushed toward black.
        css = stylesheet({"sidebar_text_primary": "#ffffff", "selection_bg": "#e0e0e0"})
        color = self._color(css)
        self.assertIsNotNone(color)
        self.assertGreaterEqual(contrast_ratio(color, "#e0e0e0"), WCAG_AA)
        self.assertEqual(color, readable_on("#ffffff", "#e0e0e0"))

    def test_one_key_changed_uses_the_base_for_the_other(self):
        # Only the selection: the dark base's own sidebar text (#ffffff).
        css = stylesheet({"selection_bg": "#f0f0f0"}, base="dark")
        self.assertEqual(self._color(css), readable_on("#ffffff", "#f0f0f0"))
        # Only the text: on the light base's selection (#d6d6d6).
        css = stylesheet({"sidebar_text_primary": "#eeeeee"}, base="light")
        color = self._color(css)
        self.assertGreaterEqual(contrast_ratio(color, "#d6d6d6"), WCAG_AA)


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
            "corner_radius": 20, "shadow_color": "#ff0000", "shadow_strength": 0.6,
            "icon_scale": 1.25, "icon_color": "#00ff00",
            "font_family": "Noto Sans", "font_scale": 1.2, "density": "compact",
            "density_fine": 0.9, "text_secondary": "#999999",
            "sidebar_text_primary": "#eeeeee", "selection_bg": "#334455",
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
