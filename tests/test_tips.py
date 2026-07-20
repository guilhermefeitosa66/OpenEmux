import random
import unittest

from openemux.core.input_actions import DEFAULT_KEYBOARD_BINDINGS
from openemux.core.tips import (
    TIP_KEYS,
    format_key_label,
    pick_next_tip,
    render_tip,
    tip_key_labels,
)
from openemux.i18n import LOCALE_TRANSLATIONS, SUPPORTED_LOCALES, tr


class TipCatalogTests(unittest.TestCase):
    def test_tip_list_is_not_empty(self):
        self.assertGreaterEqual(len(TIP_KEYS), 6)
        self.assertEqual(len(TIP_KEYS), len(set(TIP_KEYS)))

    def test_every_tip_is_translated_in_every_locale(self):
        for locale in SUPPORTED_LOCALES:
            catalog = LOCALE_TRANSLATIONS[locale]
            for key in TIP_KEYS:
                self.assertIn(key, catalog, f"{locale} is missing {key}")
                text = catalog[key]
                self.assertTrue(text.strip(), f"{locale}/{key} is empty")
                self.assertNotEqual(text, key, f"{locale}/{key} falls back to the raw key")

    def test_translations_are_not_english_copies(self):
        english = LOCALE_TRANSLATIONS["en"]
        for locale in SUPPORTED_LOCALES:
            if locale == "en":
                continue
            for key in TIP_KEYS:
                self.assertNotEqual(
                    LOCALE_TRANSLATIONS[locale][key],
                    english[key],
                    f"{locale}/{key} is an untranslated English placeholder",
                )

    def test_tips_render_in_every_locale_and_stay_short(self):
        for locale in SUPPORTED_LOCALES:
            for key in TIP_KEYS:
                text = render_tip(lambda k, **kw: tr(locale, k, **kw), key)
                self.assertNotIn("{", text, f"{locale}/{key} has an unresolved placeholder")
                self.assertLessEqual(len(text), 70, f"{locale}/{key} is too long: {text!r}")


class KeyLabelTests(unittest.TestCase):
    def test_labels_follow_the_shipped_defaults(self):
        labels = tip_key_labels()
        self.assertEqual(labels["save_key"], format_key_label(DEFAULT_KEYBOARD_BINDINGS["save_state"]))
        self.assertEqual(labels["hotkey"], format_key_label(DEFAULT_KEYBOARD_BINDINGS["enable_hotkey"]))

    def test_format_key_label(self):
        self.assertEqual(format_key_label("f2"), "F2")
        self.assertEqual(format_key_label("right shift"), "Right Shift")
        self.assertEqual(format_key_label("z"), "Z")
        self.assertEqual(format_key_label(""), "")
        self.assertEqual(format_key_label(None), "")


class PickNextTipTests(unittest.TestCase):
    def test_empty_list_returns_none(self):
        self.assertIsNone(pick_next_tip([]))

    def test_single_tip_repeats(self):
        self.assertEqual(pick_next_tip(["a"], current="a"), "a")

    def test_never_repeats_consecutively(self):
        rng = random.Random(1234)
        current = None
        for _ in range(500):
            nxt = pick_next_tip(TIP_KEYS, current, rng=rng)
            self.assertIn(nxt, TIP_KEYS)
            self.assertNotEqual(nxt, current)
            current = nxt

    def test_eventually_visits_every_tip(self):
        rng = random.Random(7)
        current = None
        seen = set()
        for _ in range(2000):
            current = pick_next_tip(TIP_KEYS, current, rng=rng)
            seen.add(current)
        self.assertEqual(seen, set(TIP_KEYS))


if __name__ == "__main__":
    unittest.main()
