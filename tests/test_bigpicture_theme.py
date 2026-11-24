"""Big Picture's stylesheet under a custom theme (issue 1012).

``bigpicture/theme.py`` imports no GTK, so all of this runs without a
display; the one check that GTK accepts the sheet runs GTK in a child
process with no display at all, so nothing here ever reaches a screen.
"""

import hashlib
import json
import os
import subprocess
import sys
import unittest

from openemux.core.contrast import contrast_ratio
from openemux.core.custom_themes import THEME_KEYS
from openemux.ui.bigpicture import theme

#: ``stylesheet(scale)`` before issue 1012, frozen: a sheet with no theme
#: must stay byte for byte what it was.
FROZEN = {
    0.6: "f452ea4e830cb6ce5d372c55a81a7c450945e549afa640fbeaf7098893f9f0f9",
    1.0: "ec49dbeebda35bef56d745ea550269d849f682fd3f35c6f865f7ce15d72a466d",
    1.333: "ac3e1ba4014e369ca75207f598d9a347b21bcbc14e9d43e89c9c6718ae3f4c11",
    2.2: "482b2f3d5ce998bd31119e016da171628cdcae3879e8ea65671e9b7c1180bc60",
}

FOCUS = theme.FOCUS_MIN_CONTRAST
AA = theme.TEXT_MIN_CONTRAST


def defaults(base):
    return {spec.key: spec.default(base) for spec in THEME_KEYS}


def adversarial():
    """Themes that would be unreadable on a couch as they are."""
    cases = []
    for base in ("light", "dark"):
        accent_is_bg = defaults(base)
        accent_is_bg["accent_button_bg"] = accent_is_bg["library_bg"]
        accent_is_bg["accent"] = accent_is_bg["library_bg"]
        cases.append((f"accent == background ({base})", base, accent_is_bg))

        accent_is_card = defaults(base)
        accent_is_card["accent_button_bg"] = accent_is_card["card_bg"]
        cases.append((f"accent button == card ({base})", base, accent_is_card))

    white = defaults("light")
    for key in ("library_bg", "card_bg", "popover_bg", "sidebar_bg",
                "text_primary", "text_secondary", "accent_button_fg"):
        white[key] = "#ffffff"
    cases.append(("white text on white surfaces", "light", white))

    black = defaults("dark")
    for key in ("library_bg", "card_bg", "text_primary", "text_secondary",
                "accent_button_bg", "accent"):
        black[key] = "#000000"
    cases.append(("all black", "dark", black))

    split = defaults("dark")
    split.update(library_bg="#000000", card_bg="#505050", accent_button_bg="#808080",
                 text_primary="#808080", text_secondary="#808080",
                 accent_button_fg="#7f7f7f")
    cases.append(("black background, grey cards, grey everything", "dark", split))

    yellow = defaults("light")
    yellow.update(accent_button_bg="#f6d32d", accent_button_fg="#000000")
    cases.append(("dark ink on a light accent", "light", yellow))
    return cases


class UnchangedTest(unittest.TestCase):
    def test_no_theme_is_byte_for_byte_the_old_sheet(self):
        for scale, digest in FROZEN.items():
            with self.subTest(scale=scale):
                css = theme.stylesheet(scale)
                self.assertEqual(hashlib.sha256(css.encode()).hexdigest(), digest)
                self.assertEqual(css, theme.stylesheet(scale, None, None, None))

    def test_the_default_palette_is_the_old_constants(self):
        self.assertEqual(theme.DEFAULT_PALETTE["accent"], theme.ACCENT)
        self.assertEqual(theme.DEFAULT_PALETTE["focus_fill"], theme.FOCUS_FILL)
        for key, value in theme.PALETTE.items():
            self.assertEqual(theme.DEFAULT_PALETTE[key], value)

    def test_passing_the_default_palette_only_adds_the_theme_rules(self):
        plain = theme.stylesheet(1.0)
        themed = theme.stylesheet(1.0, palette=dict(theme.DEFAULT_PALETTE))
        self.assertTrue(themed.startswith(plain))
        self.assertEqual(themed[len(plain):], theme.themed_rules(theme.DEFAULT_PALETTE))

    def test_a_partial_palette_falls_back_to_the_default_per_key(self):
        css = theme.stylesheet(1.0, palette={"bg": "#010203"})
        self.assertIn("background-color: #010203;", css)
        self.assertIn(theme.FOCUS_FILL, css)

    def test_the_shelf_colors_stay(self):
        palette = theme.palette_for(defaults("light"), "light")
        css = theme.stylesheet(1.0, palette=palette)
        self.assertIn(theme.shelf_rules(), css)
        self.assertIn(".big-picture .bp-shelf-card.bp-shelf-fc { background-color: #7A2E2E; }", css)


class PaletteForTest(unittest.TestCase):
    def assert_floors(self, p):
        bg, surface = p["bg"], p["surface"]
        for key in ("focus_fill", "focus_selected"):
            for under in (bg, surface):
                self.assertGreaterEqual(contrast_ratio(p[key], under), FOCUS, key)
            self.assertGreaterEqual(contrast_ratio(p["on_focus"], p[key]), AA, key)
        self.assertGreaterEqual(contrast_ratio(p["on_accent"], p["focus_accent"]), AA)
        self.assertGreaterEqual(contrast_ratio(p["accent_text"], bg), AA)
        for key in ("text", "muted", "danger"):
            for under in (bg, surface):
                self.assertGreaterEqual(contrast_ratio(p[key], under), AA, key)
        self.assertGreaterEqual(contrast_ratio(p["accent_on_soft"], p["accent_soft"]), AA)
        self.assertGreaterEqual(contrast_ratio(p["chip_current_fg"], p["chip_current_bg"]), AA)
        self.assertGreaterEqual(contrast_ratio(p["star"], surface), theme.ICON_MIN_CONTRAST)
        for key in ("game_text", "game_muted"):
            self.assertGreaterEqual(contrast_ratio(p[key], p["game_bg"]), AA, key)

    def test_every_key_the_default_has(self):
        for base in ("light", "dark"):
            p = theme.palette_for(defaults(base), base)
            self.assertEqual(set(p), set(theme.DEFAULT_PALETTE))

    def test_the_dark_defaults(self):
        values = defaults("dark")
        p = theme.palette_for(values, "dark")
        self.assertEqual(p["bg"], values["library_bg"])
        self.assertEqual(p["surface"], values["card_bg"])
        self.assertEqual(p["surface2"], values["popover_bg"])
        self.assertEqual(p["sheet"], values["sidebar_bg"])
        self.assertEqual(p["border"], values["border_color"])
        self.assertEqual(p["divider"], values["border_color"])
        self.assertEqual(p["text"], values["text_primary"])
        self.assertEqual(p["muted"], values["text_secondary"])
        self.assertEqual(p["accent"], values["accent_button_bg"])
        self.assertEqual(p["on_accent"], values["accent_button_fg"])
        self.assertEqual(p["accent_text"], values["accent"])
        self.assertEqual(p["game_bg"], theme.PALETTE["game_bg"])
        self.assertEqual(p["scrim"], "rgba(30, 30, 30, 0.72)")
        self.assertEqual(p["on_focus"], "#ffffff")
        self.assertEqual(p["focus_wash"], "rgba(255, 255, 255, 0.22)")
        self.assertEqual(p["danger"], theme.DANGER.lower())
        self.assertEqual(p["star"], theme.STAR.lower())
        # Brighter on dark, the focused accent deeper.
        self.assertEqual(p["accent_bright"], "#5396e8")
        self.assertEqual(p["focus_accent"], "#2863ab")
        self.assert_floors(p)

    def test_the_light_defaults(self):
        values = defaults("light")
        p = theme.palette_for(values, "light")
        self.assertEqual(p["bg"], "#ffffff")
        self.assertEqual(p["text"], values["text_primary"])
        self.assertEqual(p["on_accent"], "#ffffff")
        self.assertEqual(p["scrim"], "rgba(255, 255, 255, 0.72)")
        # The theme's dark text is not read on the game's black: the default is.
        self.assertEqual(p["game_text"], theme.PALETTE["text"])
        self.assertEqual(p["game_muted"], theme.PALETTE["muted"])
        self.assertEqual(p["accent_bright"], "#2d70c2")
        self.assert_floors(p)

    def test_adversarial_themes_still_read_from_the_couch(self):
        for name, base, values in adversarial():
            with self.subTest(name):
                self.assert_floors(theme.palette_for(values, base))

    def test_the_selected_tone_falls_back_to_the_fill(self):
        # A grey accent on a black background with white cards: no nudge of
        # the selected tone keeps the ink readable and stays apart.
        fill, selected, ink = theme.focus_tones("#808080", "#000000", "#ffffff", "#808080")
        for tone in (fill, selected):
            self.assertGreaterEqual(contrast_ratio(tone, "#000000"), FOCUS)
            self.assertGreaterEqual(contrast_ratio(tone, "#ffffff"), FOCUS)
            self.assertGreaterEqual(contrast_ratio(ink, tone), AA)


class HelpersTest(unittest.TestCase):
    def test_nudge_takes_the_smallest_move(self):
        self.assertEqual(theme.nudge("#808080", lambda c: True, "#123456"), "#808080")
        moved = theme.nudge("#808080", lambda c: contrast_ratio(c, "#808080") >= 2, None)
        self.assertGreaterEqual(contrast_ratio(moved, "#808080"), 2)

    def test_nudge_falls_back_when_nothing_works(self):
        self.assertEqual(theme.nudge("#808080", lambda c: False, "#123456"), "#123456")

    def test_best_end(self):
        self.assertEqual(theme.best_end(("#ffffff",)), "#000000")
        self.assertEqual(theme.best_end(("#000000",)), "#ffffff")

    def test_readable_on_all_falls_back_to_the_best_end(self):
        # Nothing reads at 21:1 on two different backgrounds.
        self.assertEqual(theme.readable_on_all("#808080", ("#000000", "#101010"), 21), "#ffffff")

    def test_readable_or(self):
        self.assertEqual(theme.readable_or("#ffffff", "#000000", "#123456"), "#ffffff")
        self.assertEqual(theme.readable_or("#111111", "#000000", "#123456"), "#123456")

    def test_rgba(self):
        self.assertEqual(theme.rgba("#0a0b0c", 0.5), "rgba(10, 11, 12, 0.5)")


class FontTest(unittest.TestCase):
    def test_a_safe_family(self):
        css = theme.stylesheet(1.0, font_family="Noto Sans")
        self.assertIn('font-family: "Noto Sans";', css)
        self.assertIn(".bp-pause-window {", css)
        self.assertTrue(css.startswith(theme.stylesheet(1.0)))

    def test_unsafe_families_are_ignored(self):
        for family in ('Evil"; } * { color: red', "a{b}", "", "x" * 65, 12, ["Sans"]):
            with self.subTest(family=family):
                self.assertEqual(theme.font_rule(family), "")
                self.assertEqual(theme.stylesheet(1.0, font_family=family), theme.stylesheet(1.0))


class BackgroundTest(unittest.TestCase):
    URI = "file:///home/someone/.openemux/themes/x/images/library.png"

    def test_each_fit(self):
        for fit, size, repeat in (("cover", "cover", "no-repeat"),
                                  ("contain", "contain", "no-repeat"),
                                  ("tile", "auto", "repeat")):
            with self.subTest(fit=fit):
                css = theme.stylesheet(1.0, background={"uri": self.URI, "fit": fit})
                self.assertIn(f'background-image: url("{self.URI}");', css)
                self.assertIn(f"background-size: {size};", css)
                self.assertIn(f"background-repeat: {repeat};", css)
                self.assertIn("background-position: center;", css)
                self.assertIn(".big-picture .bp-content navigation-view-page", css)
                # The shell keeps its color under the image.
                self.assertIn(".big-picture .bp-shell,\n.big-picture .bp-content {\n", css)

    def test_an_unknown_fit_is_cover(self):
        css = theme.background_rules({"uri": self.URI, "fit": "stretch"})
        self.assertIn("background-size: cover;", css)

    def test_rejected(self):
        for background in (
            "file:///a.png",
            {"fit": "cover"},
            {"uri": 7, "fit": "cover"},
            {"uri": "https://example.com/a.png", "fit": "cover"},
            {"uri": "/home/a.png", "fit": "cover"},
            {"uri": 'file:///a".png', "fit": "cover"},
            {"uri": "file:///a\\.png", "fit": "cover"},
            {"uri": "file:///a).png", "fit": "cover"},
            {"uri": "file:///a\n.png", "fit": "cover"},
            {"uri": "file:///a\r.png", "fit": "cover"},
        ):
            with self.subTest(background=background):
                self.assertEqual(theme.background_rules(background), "")
                self.assertEqual(theme.stylesheet(1.0, background=background), theme.stylesheet(1.0))


class ScaleTest(unittest.TestCase):
    def test_scale_for(self):
        self.assertEqual(theme.scale_for(1080), 1.0)
        self.assertEqual(theme.scale_for("tall"), 1.0)
        self.assertEqual(theme.scale_for(-5), 1.0)
        self.assertEqual(theme.scale_for(1080, 150), 1.5)


class FontScaleTest(unittest.TestCase):
    def test_bounds(self):
        # A factor, as the shared format stores font_scale (1.1 is 110%).
        self.assertEqual(theme.font_scale_factor(0.85), 1.0)
        self.assertEqual(theme.font_scale_factor(1.0), 1.0)
        self.assertEqual(theme.font_scale_factor(1.2), 1.2)
        self.assertEqual(theme.font_scale_factor(1.5), 1.5)
        self.assertEqual(theme.font_scale_factor(4), 1.5)
        self.assertEqual(theme.font_scale_factor("1.3"), 1.3)
        self.assertEqual(theme.font_scale_factor(None), 1.0)
        self.assertEqual(theme.font_scale_factor("big"), 1.0)


def themed_sheets():
    sheets = []
    for name, base, values in [("light", "light", defaults("light")),
                               ("dark", "dark", defaults("dark")), *adversarial()]:
        sheets.append(theme.stylesheet(
            1.333,
            palette=theme.palette_for(values, base),
            font_family="DejaVu Sans",
            background={"uri": "file:///tmp/bg.png", "fit": "tile"},
        ))
    return sheets


class GeneratedCssTest(unittest.TestCase):
    def test_balanced_and_no_python_left(self):
        for css in themed_sheets():
            self.assertEqual(css.count("{"), css.count("}"))
            depth = 0
            for ch in css:
                depth += {"{": 1, "}": -1}.get(ch, 0)
                self.assertIn(depth, (0, 1))
            for leftover in ("{'", "'}", "p[", "None", "<function", "{{", "}}"):
                self.assertNotIn(leftover, css)

    def test_gtk_parses_it(self):
        # GTK in a child process, with no display to open: CssProvider parses
        # without one, and nothing reaches the developer's screen.
        env = {k: v for k, v in os.environ.items() if k not in ("DISPLAY", "WAYLAND_DISPLAY")}
        script = (
            "import json, sys\n"
            "import gi\n"
            "try:\n"
            "    gi.require_version('Gtk', '4.0')\n"
            "    from gi.repository import Gtk\n"
            "except (ImportError, ValueError):\n"
            "    print('SKIP'); sys.exit(0)\n"
            "errors = []\n"
            "for css in json.load(sys.stdin):\n"
            "    provider = Gtk.CssProvider()\n"
            "    provider.connect('parsing-error', lambda p, s, e: errors.append(e.message))\n"
            "    provider.load_from_string(css)\n"
            "print(json.dumps(errors))\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", script], input=json.dumps(themed_sheets()),
            capture_output=True, text=True, env=env, timeout=60,
        )
        if result.stdout.strip() in ("SKIP", "") or result.returncode != 0:
            self.skipTest(f"GTK 4 is not importable here: {result.stderr[-300:]}")
        self.assertEqual(json.loads(result.stdout.strip().splitlines()[-1]), [])


if __name__ == "__main__":
    unittest.main()


class ConsoleListTests(unittest.TestCase):
    """Issue 1012, maintainer's Android test: the console list follows a theme."""

    def test_no_color_no_rule(self):
        from openemux.ui.bigpicture import theme as bp
        self.assertEqual(bp.console_list_rules(None, bp.DEFAULT_PALETTE), "")
        self.assertEqual(bp.console_list_rules("red; }", bp.DEFAULT_PALETTE), "")

    def test_every_card_takes_the_color_with_the_themes_ink(self):
        from openemux.ui.bigpicture import theme as bp
        palette = dict(bp.DEFAULT_PALETTE, text="#111111", muted="#222222")
        css = bp.stylesheet(1.0, palette=palette, console_list="#ABCDEF")
        rule_at = css.index(".big-picture .bp-content .bp-shelf-card,")
        self.assertGreater(rule_at, css.index(".bp-shelf-card.bp-shelf-all {"))
        self.assertIn("background-color: #abcdef;", css[rule_at:])
        self.assertIn("color: #111111;", css[rule_at:])
        self.assertIn("color: #222222;", css[rule_at:])
