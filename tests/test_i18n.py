import unittest

from opemux.i18n import normalize_locale, tr


class I18nTests(unittest.TestCase):
    def test_unknown_locale_falls_back_to_english(self):
        self.assertEqual(normalize_locale("unknown"), "en")
        self.assertEqual(tr("unknown", "settings.title"), "Settings")

    def test_missing_key_in_locale_uses_english(self):
        # de locale is partial by design in this phase.
        self.assertEqual(tr("de", "context.cover.remove"), "Remove cover image")

    def test_missing_key_in_english_returns_key(self):
        self.assertEqual(tr("en", "i18n.missing.key"), "i18n.missing.key")


if __name__ == "__main__":
    unittest.main()
