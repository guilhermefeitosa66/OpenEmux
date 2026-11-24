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
    KIND_COLOR,
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
            self.assertEqual(spec.kind, KIND_COLOR)

    def test_each_section_has_rows(self):
        for section in SECTIONS:
            self.assertTrue(keys_in_section(section))

    def test_defaults_are_valid_colors_on_both_bases(self):
        for spec in THEME_KEYS:
            for base in ("light", "dark"):
                self.assertEqual(validate_value(spec, spec.default(base)), spec.default(base))

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

    def test_numbers_without_a_range_pass_through(self):
        spec = ThemeKey("scale", "typography", "text", KIND_NUMBER, 1, 1)
        self.assertEqual(validate_value(spec, 7.5), 7.5)

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
