import unittest

from openemux.i18n import (
    SUPPORTED_LOCALES,
    detect_system_locale,
    match_locale,
    normalize_locale,
    tr,
)


class I18nTests(unittest.TestCase):
    def test_unknown_locale_falls_back_to_english(self):
        # "settings.title" used to stand in here; it was retired with the
        # other 33 keys the Preferences refactor left unreachable (issue
        # #232), so this asserts against a key the app still shows.
        self.assertEqual(normalize_locale("unknown"), "en")
        self.assertEqual(tr("unknown", "prefs.game_window.title"),
                         "Play in an OpenEmux window")

    def test_missing_key_in_locale_uses_english(self):
        # This used to lean on German being incomplete. Every locale is
        # complete now (and a test enforces it), so the fallback is exercised
        # with a locale that genuinely lacks the key instead.
        from openemux.i18n import LOCALE_TRANSLATIONS, reset_translation_cache

        original = LOCALE_TRANSLATIONS["de"].pop("context.cover.remove")
        # The merged tables are memoized, so a catalog edited at runtime has
        # to say so (issue #231).
        reset_translation_cache()
        try:
            self.assertEqual(tr("de", "context.cover.remove"), "Remove cover image")
        finally:
            LOCALE_TRANSLATIONS["de"]["context.cover.remove"] = original
            reset_translation_cache()

    def test_a_translated_key_is_not_taken_from_english(self):
        self.assertEqual(tr("de", "context.cover.remove"), "Coverbild entfernen")

    def test_missing_key_in_english_returns_key(self):
        self.assertEqual(tr("en", "i18n.missing.key"), "i18n.missing.key")


class LocaleMatchingTests(unittest.TestCase):
    """Turning an OS locale string into one of the locales we ship."""

    def test_exact_matches(self):
        self.assertEqual(match_locale("pt_BR"), "pt_BR")
        self.assertEqual(match_locale("zh_CN"), "zh_CN")

    def test_encoding_and_modifiers_are_stripped(self):
        self.assertEqual(match_locale("pt_BR.UTF-8"), "pt_BR")
        self.assertEqual(match_locale("de_DE.UTF-8@euro"), "de")
        self.assertEqual(match_locale("pt-br"), "pt_BR")

    def test_region_falls_back_to_the_language(self):
        self.assertEqual(match_locale("es_ES"), "es")
        self.assertEqual(match_locale("fr_FR"), "fr")
        self.assertEqual(match_locale("fr_CA"), "fr")
        self.assertEqual(match_locale("en_GB"), "en")

    def test_language_without_a_regional_variant_uses_the_one_we_ship(self):
        """We ship no pt_PT or zh_TW, and Portuguese beats English for them."""
        self.assertEqual(match_locale("pt_PT"), "pt_BR")
        self.assertEqual(match_locale("zh_TW"), "zh_CN")

    def test_unsupported_and_neutral_locales_do_not_match(self):
        for value in ("ru_RU", "C", "POSIX", "", None, "1234"):
            with self.subTest(value=value):
                self.assertIsNone(match_locale(value))


class SystemLocaleDetectionTests(unittest.TestCase):
    def test_reads_the_standard_environment_variables(self):
        for name in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
            with self.subTest(name=name):
                self.assertEqual(detect_system_locale({name: "pt_BR.UTF-8"}), "pt_BR")

    def test_language_wins_over_lang(self):
        env = {"LANGUAGE": "fr_FR", "LANG": "de_DE.UTF-8"}
        self.assertEqual(detect_system_locale(env), "fr")

    def test_language_preference_list_is_walked_in_order(self):
        """LANGUAGE is a colon list; the first locale we ship wins."""
        env = {"LANGUAGE": "ru_RU:pt_PT:en_US"}
        self.assertEqual(detect_system_locale(env), "pt_BR")

    def test_unsupported_locale_falls_back_to_english(self):
        self.assertEqual(detect_system_locale({"LANG": "ru_RU.UTF-8"}), "en")
        self.assertEqual(detect_system_locale({"LANG": "C"}), "en")
        self.assertEqual(detect_system_locale({}), "en")

    def test_detection_only_ever_returns_a_supported_locale(self):
        for value in ("pt_BR", "pt_PT", "es_MX", "ja_JP", "zh_TW", "xx_YY"):
            with self.subTest(value=value):
                self.assertIn(detect_system_locale({"LANG": value}), SUPPORTED_LOCALES)


if __name__ == "__main__":
    unittest.main()


class ProgressLabelTests(unittest.TestCase):
    """The banner appends its own "(current/total)", so a progress label that
    embeds one too renders as "Syncing covers (3/40) (3/40)"."""

    PROGRESS_KEYS = ("status.covers.progress", "import.progress")

    def test_progress_labels_do_not_embed_their_own_counter(self):
        for locale in SUPPORTED_LOCALES:
            for key in self.PROGRESS_KEYS:
                text = tr(locale, key)
                for placeholder in ("{current}", "{total}", "{count}"):
                    self.assertNotIn(
                        placeholder,
                        text,
                        f"{locale}/{key} embeds {placeholder}; _refresh_banner already renders it",
                    )


class TranslationTableCacheTests(unittest.TestCase):
    """The merged tables are built once per locale (issue #231)."""

    def test_a_caller_cannot_edit_the_shared_table(self):
        from openemux.i18n import merged_translations

        table = merged_translations("de")
        table["settings.title"] = "clobbered"
        self.assertNotEqual(tr("de", "settings.title"), "clobbered")

    def test_the_merge_is_reused_across_lookups(self):
        from openemux.i18n import _merged_table

        first = _merged_table("pt_BR")
        second = _merged_table("pt_BR")
        self.assertIs(first, second)

    def test_resetting_rebuilds_it(self):
        from openemux.i18n import _merged_table, reset_translation_cache

        first = _merged_table("es")
        reset_translation_cache()
        self.assertIsNot(_merged_table("es"), first)


if __name__ == "__main__":
    unittest.main()

