"""Every locale carries every key, with the same placeholders (issue: drift).

English is the fallback layer, so a missing key never crashes -- it just
silently shows English. That is exactly why the other locales drifted to ~10%
coverage without anyone noticing: nothing was watching. These tests watch.
"""

import re
import unittest

from openemux.i18n import LOCALE_TRANSLATIONS, SUPPORTED_LOCALES, tr

_PLACEHOLDER = re.compile(r"\{(\w+)\}")


def _placeholders(text):
    return set(_PLACEHOLDER.findall(text))


class LocaleCompletenessTests(unittest.TestCase):
    def test_english_is_the_reference(self):
        self.assertIn("en", LOCALE_TRANSLATIONS)
        self.assertTrue(LOCALE_TRANSLATIONS["en"])

    def test_every_supported_locale_ships_a_table(self):
        for locale in SUPPORTED_LOCALES:
            self.assertIn(locale, LOCALE_TRANSLATIONS, locale)

    def test_no_locale_is_missing_a_key(self):
        english = set(LOCALE_TRANSLATIONS["en"])
        for locale, table in LOCALE_TRANSLATIONS.items():
            missing = sorted(english - set(table))
            self.assertEqual(
                missing,
                [],
                f"{locale} is missing {len(missing)} keys, e.g. {missing[:5]}",
            )

    def test_no_locale_invents_a_key(self):
        # A key not in English is either a typo or a leftover: it can never be
        # reached, since every lookup starts from an English key.
        english = set(LOCALE_TRANSLATIONS["en"])
        for locale, table in LOCALE_TRANSLATIONS.items():
            extra = sorted(set(table) - english)
            self.assertEqual(extra, [], f"{locale} has keys English does not: {extra[:5]}")


class PlaceholderParityTests(unittest.TestCase):
    """A translation that drops or renames a placeholder raises at runtime.

    ``tr()`` calls ``str.format(**kwargs)``, so an unknown name is a KeyError
    in the middle of drawing the UI -- and only in that language.
    """

    def test_placeholders_match_english(self):
        english = LOCALE_TRANSLATIONS["en"]
        for locale, table in LOCALE_TRANSLATIONS.items():
            if locale == "en":
                continue
            for key, text in table.items():
                if key not in english:
                    continue
                self.assertEqual(
                    _placeholders(text),
                    _placeholders(english[key]),
                    f"{locale}/{key}: placeholders differ from English",
                )

    def test_every_translation_formats_with_englishs_arguments(self):
        english = LOCALE_TRANSLATIONS["en"]
        for locale, table in LOCALE_TRANSLATIONS.items():
            for key, text in table.items():
                if key not in english:
                    continue
                args = {name: "x" for name in _placeholders(english[key])}
                try:
                    tr(locale, key, **args)
                except (KeyError, IndexError, ValueError) as exc:
                    self.fail(f"{locale}/{key} does not format: {exc}")


class TranslationQualityTests(unittest.TestCase):
    def test_nothing_is_left_empty(self):
        for locale, table in LOCALE_TRANSLATIONS.items():
            blank = sorted(k for k, v in table.items() if not str(v).strip())
            self.assertEqual(blank, [], f"{locale} has empty translations: {blank[:5]}")

    def test_the_product_name_is_never_translated(self):
        for locale, table in LOCALE_TRANSLATIONS.items():
            self.assertEqual(table.get("app.title"), "OpenEmux", locale)

    def test_no_bare_ampersand(self):
        """Adwaita row titles and descriptions are parsed as Pango markup.

        A bare "&" makes GTK reject the whole string -- the row silently
        renders empty. "Stick & Feedback" did exactly that until a real run
        printed the warning.
        """
        bare = re.compile(r"&(?!(amp|lt|gt|quot|apos|#\d+);)")
        for locale, table in LOCALE_TRANSLATIONS.items():
            offenders = sorted(k for k, v in table.items() if bare.search(v))
            self.assertEqual(offenders, [], f"{locale} has a bare '&' in: {offenders}")


if __name__ == "__main__":
    unittest.main()
