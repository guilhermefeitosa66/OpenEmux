import unittest

from openemux.i18n import SUPPORTED_LOCALES, normalize_locale, tr


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
