"""The user's own themes: whitelist, validation and storage (issue 1011)."""

import math
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import yaml

from openemux.core import custom_themes
from openemux.core.contrast import WCAG_AA, contrast_ratio
from openemux.core.custom_themes import (
    CONTRAST_PAIRS,
    FORMAT_VERSION,
    KEYS_BY_NAME,
    KIND_CHOICE,
    KIND_COLOR,
    KIND_FONT,
    KIND_IMAGE,
    KIND_NUMBER,
    SECTIONS,
    THEME_FILE,
    THEME_KEYS,
    Theme,
    ThemeError,
    ThemeKey,
    ThemeStore,
    clean_name,
    contrast_problems,
    keys_in_section,
    parse_theme,
    serialize,
    slugify,
    validate_value,
    validate_values,
    warnings_for,
)


class TableTests(unittest.TestCase):
    def test_every_key_is_in_a_known_section_and_unique(self):
        self.assertEqual(len(KEYS_BY_NAME), len(THEME_KEYS))
        for spec in THEME_KEYS:
            self.assertIn(spec.section, SECTIONS)
            self.assertIn(spec.kind, (KIND_COLOR, KIND_NUMBER, KIND_CHOICE, KIND_FONT, KIND_IMAGE))

    def test_each_section_has_rows(self):
        for section in SECTIONS:
            self.assertTrue(keys_in_section(section))

    def test_defaults_are_valid_values_on_both_bases(self):
        # A font or an image defaults to empty: none, which is no value at all.
        for spec in THEME_KEYS:
            for base in ("light", "dark"):
                if spec.kind in (KIND_FONT, KIND_IMAGE):
                    self.assertEqual(spec.default(base), "")
                    continue
                self.assertEqual(validate_value(spec, spec.default(base)), spec.default(base))

    def test_numbers_have_a_range_and_a_unit(self):
        for spec in THEME_KEYS:
            if spec.kind == KIND_NUMBER:
                self.assertLess(spec.minimum, spec.maximum, spec.key)
                self.assertIn(spec.unit, ("px", "%"), spec.key)

    def test_the_bases_text_pairs_pass_aa_except_libadwaitas_accent_button(self):
        # The defaults are the base's own look; its text passes AA. Its
        # accent button does not (white on #3584e4 is 3.7:1), which is why a
        # pair the theme did not change never warns.
        for base in ("light", "dark"):
            for fg, backgrounds in CONTRAST_PAIRS:
                if fg == "accent_button_fg":
                    continue
                for bg in backgrounds:
                    ratio = contrast_ratio(
                        KEYS_BY_NAME[fg].default(base), KEYS_BY_NAME[bg].default(base)
                    )
                    self.assertGreaterEqual(ratio, WCAG_AA, (base, fg, bg))

    def test_every_pair_names_known_keys(self):
        for fg, backgrounds in CONTRAST_PAIRS:
            self.assertIn(fg, KEYS_BY_NAME)
            for bg in backgrounds:
                self.assertIn(bg, KEYS_BY_NAME)


class ValidationTests(unittest.TestCase):
    NUMBER = ThemeKey("radius", "borders", "borders", KIND_NUMBER, 6, 8, 0, 24)

    def test_colors_are_normalized_hex(self):
        spec = KEYS_BY_NAME["card_bg"]
        self.assertEqual(validate_value(spec, "#ABCDEF"), "#abcdef")
        self.assertEqual(validate_value(spec, "fff"), "#ffffff")
        self.assertIsNone(validate_value(spec, "red"))
        self.assertIsNone(validate_value(spec, 0xFFFFFF))
        self.assertIsNone(validate_value(spec, None))

    def test_numbers_are_clamped_to_their_range(self):
        self.assertEqual(validate_value(self.NUMBER, 12), 12)
        self.assertEqual(validate_value(self.NUMBER, -3), 0)
        self.assertEqual(validate_value(self.NUMBER, 99.5), 24)

    def test_numbers_without_a_range_are_whole(self):
        spec = ThemeKey("scale", "typography", "text", KIND_NUMBER, 1, 1)
        self.assertEqual(validate_value(spec, 7.5), 8)
        self.assertEqual(validate_value(spec, 7), 7)

    def test_choices_are_exact(self):
        density = KEYS_BY_NAME["density"]
        self.assertEqual(density.choices, custom_themes.DENSITIES)
        self.assertEqual(validate_value(density, "compact"), "compact")
        self.assertIsNone(validate_value(density, "Compact"))
        self.assertIsNone(validate_value(density, 80))
        self.assertIsNone(validate_value(density, True))
        number = ThemeKey("n", "spacing", "spacing", KIND_CHOICE, 16, 16, choices=(16, 20))
        self.assertEqual(validate_value(number, 20), 20)
        self.assertIsNone(validate_value(number, 20.0))
        self.assertIsNone(validate_value(number, 18))
        fit = KEYS_BY_NAME["library_image_fit"]
        self.assertEqual(validate_value(fit, "tile"), "tile")
        self.assertIsNone(validate_value(fit, "stretch"))

    def test_fonts_cannot_leave_a_css_string(self):
        font = KEYS_BY_NAME["font_family"]
        self.assertEqual(validate_value(font, "Noto Sans CJK JP"), "Noto Sans CJK JP")
        self.assertEqual(validate_value(font, "Fira Code (Retina)"), "Fira Code (Retina)")
        for bad in ('Sans"; } * {', "Sans\\", " Sans", "Sans\n", "", "x" * 65, 12, None):
            self.assertIsNone(validate_value(font, bad), repr(bad))

    def test_images_are_names_in_the_images_folder(self):
        image = KEYS_BY_NAME["library_image"]
        for good in ("images/library.png", "images/bg-2.jpg", "images/a_b.jpeg", "images/x.webp"):
            self.assertEqual(validate_value(image, good), good)
        for bad in ("library.png", "images/../x.png", "/images/x.png", "images/a/b.png",
                    "images/X.png", "images/x.gif", "images/x.png\n", "images/.x.png",
                    "Images/x.png", "images\\x.png", 3):
            self.assertIsNone(validate_value(image, bad), repr(bad))
        # The bare file name, as it sits inside images/.
        self.assertTrue(custom_themes.IMAGE_FILE.fullmatch("library.png"))
        self.assertIsNone(custom_themes.IMAGE_FILE.fullmatch("images/library.png"))

    def test_fractions_keep_two_decimals_and_pixels_are_whole(self):
        shadow = KEYS_BY_NAME["shadow_strength"]
        self.assertTrue(shadow.fraction)
        self.assertEqual(shadow.step, 0.05)
        self.assertEqual(validate_value(shadow, 0.333), 0.33)
        self.assertEqual(validate_value(shadow, 1), 1.0)
        self.assertIsInstance(validate_value(shadow, 1), float)
        self.assertEqual(validate_value(shadow, 35), 1.0)
        self.assertEqual(validate_value(shadow, -1), 0.0)
        dim = KEYS_BY_NAME["library_image_dim"]
        self.assertEqual(validate_value(dim, 0.95), 0.9)
        self.assertEqual(KEYS_BY_NAME["icon_scale"].default("dark"), 1.0)
        self.assertEqual(validate_value(KEYS_BY_NAME["icon_scale"], 0.5), 0.75)
        radius = KEYS_BY_NAME["corner_radius"]
        self.assertFalse(radius.fraction)
        self.assertEqual(radius.step, 1)
        self.assertEqual(validate_value(radius, 8.0), 8)
        self.assertIsInstance(validate_value(radius, 8.0), int)
        self.assertEqual(validate_value(radius, 40), 28)
        # Only a number is a fraction, whatever its unit says.
        self.assertFalse(KEYS_BY_NAME["density"].fraction)

    def test_the_shared_ranges(self):
        expected = {
            "corner_radius": (0, 28, "px"), "border_width": (0, 4, "px"),
            "grid_gap": (0, 32, "px"), "library_image_blur": (0, 24, "px"),
            "sidebar_width": (200, 420, "px"), "shadow_strength": (0, 1, "%"),
            "icon_scale": (0.75, 1.5, "%"), "font_scale": (0.85, 1.3, "%"),
            "density_fine": (0.8, 1.2, "%"), "card_scale": (0.75, 1.5, "%"),
            "sidebar_image_dim": (0, 0.9, "%"),
        }
        for key, (low, high, unit) in expected.items():
            spec = KEYS_BY_NAME[key]
            self.assertEqual((spec.minimum, spec.maximum, spec.unit), (low, high, unit), key)
        self.assertEqual(KEYS_BY_NAME["shadow_strength"].light, 0.35)
        self.assertEqual(KEYS_BY_NAME["library_image_dim"].dark, 0.4)
        self.assertNotIn("sidebar_icon_size", KEYS_BY_NAME)
        self.assertNotIn("toolbar_icon_size", KEYS_BY_NAME)

    def test_numbers_of_the_wrong_type_are_dropped(self):
        for value in (True, "12", None, [], math.nan, math.inf):
            self.assertIsNone(validate_value(self.NUMBER, value), repr(value))

    def test_validate_values_keeps_only_whitelisted_good_values(self):
        with self.assertLogs("openemux.core.custom_themes", level="INFO") as logs:
            values = validate_values({
                "version": 1, "name": "x", "base": "dark",
                "card_bg": "#112233",
                "sidebar_bg": 12,
                "raw_css": "* { color: red }",
            })
        self.assertEqual(values, {"card_bg": "#112233"})
        self.assertTrue(any("raw_css" in line for line in logs.output))
        self.assertTrue(any("sidebar_bg" in line for line in logs.output))

    def test_validate_values_of_a_non_mapping_is_empty(self):
        self.assertEqual(validate_values(["card_bg"]), {})

    def test_clean_name(self):
        self.assertEqual(clean_name("  Mid \n night  "), "Mid night")
        self.assertEqual(len(clean_name("x" * 200)), custom_themes.MAX_NAME_LENGTH)
        self.assertEqual(clean_name(None), "")

    def test_slugify(self):
        self.assertEqual(slugify("Midnight Blue!"), "midnight-blue")
        self.assertEqual(slugify("Ação Café"), "acao-cafe")
        self.assertEqual(slugify("夜"), "theme")
        self.assertEqual(slugify(None), "theme")
        self.assertLessEqual(len(slugify("a b " * 40)), 40)
        self.assertFalse(slugify("a b " * 40).endswith("-"))


class ThemeModelTests(unittest.TestCase):
    def test_effective_falls_back_to_the_base(self):
        theme = Theme("t", "T", "dark", {"card_bg": "#101010"})
        self.assertEqual(theme.effective("card_bg"), "#101010")
        self.assertEqual(theme.effective("window_bg"), KEYS_BY_NAME["window_bg"].dark)
        self.assertTrue(theme.is_changed("card_bg"))
        self.assertFalse(theme.is_changed("window_bg"))
        self.assertEqual(len(theme.effective_values()), len(THEME_KEYS))

    def test_copy_does_not_share_values(self):
        theme = Theme("t", "T", "light", {"card_bg": "#101010"})
        other = theme.copy(name="U")
        other.values["card_bg"] = "#202020"
        self.assertEqual(theme.values["card_bg"], "#101010")
        self.assertEqual(other.name, "U")

    def test_icons_need_3_to_1_and_text_4_5_to_1(self):
        self.assertEqual(custom_themes.needed_contrast("icon_color"), custom_themes.NON_TEXT_CONTRAST)
        self.assertEqual(custom_themes.needed_contrast("text_primary"), WCAG_AA)
        # #808080 on the dark header bar and sidebar (#303030) is about 3.3:1.
        gray = "#808080"
        ratio = contrast_ratio(gray, KEYS_BY_NAME["headerbar_bg"].dark)
        self.assertTrue(3 <= ratio < WCAG_AA, ratio)
        self.assertEqual(contrast_problems(Theme("t", "T", "dark", {"icon_color": gray})), [])
        problems = contrast_problems(Theme("t", "T", "dark", {"text_primary": gray}))
        self.assertIn(("text_primary", "headerbar_bg"), [(fg, bg) for fg, bg, _r in problems])
        dark = contrast_problems(Theme("t", "T", "dark", {"icon_color": "#444444"}))
        self.assertEqual({fg for fg, _bg, _r in dark}, {"icon_color"})

    def test_the_sidebar_text_is_not_checked_on_the_selection(self):
        # The stylesheet makes the selected row's text readable instead.
        theme = Theme("t", "T", "dark", {"selection_bg": "#ffffff"})
        self.assertEqual(contrast_problems(theme), [])

    def test_unchanged_pairs_never_warn(self):
        self.assertEqual(contrast_problems(Theme("t", "T", "light")), [])
        self.assertEqual(contrast_problems(Theme("t", "T", "dark")), [])

    def test_a_changed_text_color_too_close_to_its_surface_warns(self):
        theme = Theme("t", "T", "light", {"text_secondary": "#c8c8c8"})
        problems = contrast_problems(theme)
        self.assertTrue(problems)
        self.assertTrue(all(fg == "text_secondary" for fg, _bg, _r in problems))
        ratios = [ratio for _fg, _bg, ratio in problems]
        self.assertEqual(ratios, sorted(ratios))
        found = warnings_for(theme, "text_secondary")
        self.assertIn("library_bg", [other for other, _ratio in found])

    def test_a_changed_surface_warns_on_both_sides(self):
        theme = Theme("t", "T", "dark", {"library_bg": "#d0d0d0"})
        self.assertIn("text_primary", [other for other, _r in warnings_for(theme, "library_bg")])
        self.assertIn("library_bg", [other for other, _r in warnings_for(theme, "text_primary")])
        self.assertEqual(warnings_for(theme, "accent_button_bg"), [])


class ParseTests(unittest.TestCase):
    def test_a_good_file(self):
        theme = parse_theme(
            {"version": 1, "name": " Night ", "base": "dark", "card_bg": "#123456"}, "night"
        )
        self.assertEqual((theme.id, theme.name, theme.base), ("night", "Night", "dark"))
        self.assertEqual(theme.values, {"card_bg": "#123456"})

    def test_a_missing_version_or_name_is_forgiven(self):
        theme = parse_theme({"base": "light"}, "plain")
        self.assertEqual(theme.name, "plain")

    def test_a_newer_version_loads_what_it_knows(self):
        theme = parse_theme({"version": 9, "base": "light", "future_key": 3}, "f")
        self.assertEqual(theme.values, {})

    def test_unusable_files_raise(self):
        for data in (None, [], "text", {"base": "blue"}, {"version": "1", "base": "dark"},
                     {"version": 0, "base": "dark"}, {"version": True, "base": "dark"}):
            with self.assertRaises(ThemeError, msg=repr(data)):
                parse_theme(data, "x")

    def test_serialize_writes_only_changed_values_in_table_order(self):
        theme = Theme("t", "T", "light", {"accent": "#ff0000", "window_bg": "#000000"})
        data = serialize(theme)
        self.assertEqual(list(data), ["version", "name", "base", "window_bg", "accent"])
        self.assertEqual(data["version"], FORMAT_VERSION)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name) / "themes"
        self.store = ThemeStore(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def test_an_absent_folder_lists_nothing(self):
        self.assertEqual(self.store.list(), [])

    def test_create_writes_a_readable_file(self):
        theme = self.store.create("Midnight", "dark", {"card_bg": "#2F3549", "bogus": 1})
        self.assertEqual(theme.id, "midnight")
        data = yaml.safe_load((self.root / "midnight" / THEME_FILE).read_text())
        self.assertEqual(data, {"version": 1, "name": "Midnight", "base": "dark",
                                "card_bg": "#2f3549"})
        self.assertEqual(self.store.get("midnight"), theme)
        self.assertFalse(any(p.name.endswith(".tmp") for p in (self.root / "midnight").iterdir()))

    def test_create_rejects_an_empty_name_or_a_bad_base(self):
        with self.assertRaises(ValueError):
            self.store.create("   ", "dark")
        with self.assertRaises(ValueError):
            self.store.create("x", "blue")

    def test_ids_never_clash_nor_take_a_built_in_name(self):
        first = self.store.create("Night", "dark")
        second = self.store.create("Night", "light")
        self.assertEqual((first.id, second.id), ("night", "night-2"))
        self.assertEqual(self.store.create("Dark", "dark").id, "dark-2")

    def test_list_sorts_by_name_and_skips_what_is_not_a_theme(self):
        self.store.create("beta", "dark")
        self.store.create("Alpha", "light")
        (self.root / "Not An Id").mkdir()
        (self.root / "stray.txt").write_text("x")
        broken = self.root / "broken"
        broken.mkdir()
        (broken / THEME_FILE).write_text("version: [1\n")
        empty = self.root / "empty"
        empty.mkdir()
        with self.assertLogs("openemux.core.custom_themes", level="WARNING"):
            names = [theme.name for theme in self.store.list()]
        self.assertEqual(names, ["Alpha", "beta"])

    def test_a_hand_broken_file_never_raises(self):
        folder = self.root / "hand"
        folder.mkdir(parents=True)
        for text in ("::: not yaml", "- a list\n", "base: purple\n", "\xff",
                     "base: dark\ncard_bg: 12\nwho: knows\n"):
            (folder / THEME_FILE).write_bytes(text.encode("latin-1"))
            with self.assertLogs("openemux.core.custom_themes", level="INFO"):
                theme = self.store.get("hand")
            if theme is not None:
                self.assertEqual(theme.values, {})

    def test_get_with_a_bad_id_is_none(self):
        self.assertIsNone(self.store.get("../etc"))
        self.assertIsNone(self.store.get("dark"))

    def test_paths_never_leave_the_folder(self):
        with self.assertRaises(ValueError):
            self.store.delete("../x")
        with self.assertRaises(ValueError):
            self.store.save(Theme("../x", "x", "dark"))

    def test_save_replaces_the_file(self):
        theme = self.store.create("Paper", "light")
        theme.values["accent"] = "#ff7800"
        self.store.save(theme)
        self.assertEqual(self.store.get("paper").values, {"accent": "#ff7800"})

    def test_a_failed_save_leaves_no_temp_file(self):
        theme = self.store.create("Paper", "light")
        with mock.patch.object(custom_themes.os, "replace", side_effect=OSError("full")):
            with self.assertRaises(OSError):
                self.store.save(theme)
        self.assertEqual(sorted(p.name for p in (self.root / "paper").iterdir()), [THEME_FILE])

    def test_duplicate_copies_base_and_values_under_a_new_id(self):
        self.store.create("Night", "dark", {"card_bg": "#101010"})
        copy = self.store.duplicate("night", "Night (copy)")
        self.assertEqual((copy.id, copy.base, copy.values),
                         ("night-copy", "dark", {"card_bg": "#101010"}))
        with self.assertRaises(KeyError):
            self.store.duplicate("gone", "x")

    def test_rename_keeps_the_id(self):
        self.store.create("Night", "dark")
        renamed = self.store.rename("night", "  Late  night ")
        self.assertEqual((renamed.id, renamed.name), ("night", "Late night"))
        self.assertEqual(self.store.get("night").name, "Late night")
        with self.assertRaises(ValueError):
            self.store.rename("night", " ")
        with self.assertRaises(KeyError):
            self.store.rename("gone", "x")

    def test_delete_removes_the_folder_and_tolerates_a_missing_one(self):
        self.store.create("Night", "dark")
        self.store.delete("night")
        self.assertFalse((self.root / "night").exists())
        self.store.delete("night")

    def test_an_unreadable_root_lists_nothing(self):
        with mock.patch.object(Path, "iterdir", side_effect=PermissionError):
            self.assertEqual(self.store.list(), [])


if __name__ == "__main__":
    unittest.main()
