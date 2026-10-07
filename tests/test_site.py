"""The GitHub Pages site, in every language the app speaks.

``docs/`` is generated from ``site/page.html`` and ``site/strings/`` by
``tools/build_site.py`` and committed, because Pages serves it as is. What
these tests hold: the published pages are exactly what the source builds,
every language has every string, and every page links to all the others.
"""

import importlib.util
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

spec = importlib.util.spec_from_file_location("build_site", REPO / "tools" / "build_site.py")
build_site = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_site)

from openemux.i18n import LANGUAGE_META  # noqa: E402


class TheLanguagesTests(unittest.TestCase):
    def test_the_site_speaks_exactly_what_the_app_speaks(self):
        self.assertEqual(sorted(build_site.ORDER), sorted(LANGUAGE_META))

    def test_every_language_has_every_string_and_no_other(self):
        english = build_site.load_strings("en")
        for locale in build_site.ORDER:
            with self.subTest(locale=locale):
                self.assertEqual(list(build_site.load_strings(locale)), list(english))

    def test_no_string_is_left_empty(self):
        for locale in build_site.ORDER:
            for key, value in build_site.load_strings(locale).items():
                with self.subTest(locale=locale, key=key):
                    self.assertTrue(value.strip())

    def test_the_markup_survives_translation(self):
        # Links, sources, classes and code are the same in every language;
        # only the text, alt and aria-label differ.
        def skeleton(value):
            value = re.sub(r'(alt|aria-label|content)="[^"]*"', r'\1=""', value)
            return re.findall(r"<[^>]+>|&[a-z]+;", value)

        english = build_site.load_strings("en")
        for locale in build_site.ORDER:
            strings = build_site.load_strings(locale)
            for key in english:
                with self.subTest(locale=locale, key=key):
                    self.assertEqual(skeleton(strings[key]), skeleton(english[key]))


class ThePublishedPagesTests(unittest.TestCase):
    def test_docs_is_what_the_source_builds(self):
        # A template or string edit that was not rebuilt would ship half a
        # change; run tools/build_site.py.
        for path, text in build_site.pages().items():
            with self.subTest(page=str(path.relative_to(REPO))):
                self.assertTrue(path.exists())
                self.assertEqual(path.read_text(encoding="utf-8"), text)

    def test_no_placeholder_survives(self):
        for path, text in build_site.pages().items():
            with self.subTest(page=str(path.relative_to(REPO))):
                self.assertNotIn("{{", text)

    def test_each_page_names_its_own_language(self):
        for locale in build_site.ORDER:
            text = build_site.render(locale)
            with self.subTest(locale=locale):
                self.assertIn(f'<html lang="{build_site.html_lang(locale)}"', text)
                self.assertIn('aria-current="page"', text)

    def test_only_the_root_page_picks_a_language_by_itself(self):
        self.assertIn("data-lang-auto", build_site.render("en"))
        self.assertNotIn("data-lang-auto", build_site.render("pt_BR"))

    def test_every_page_offers_every_language_under_its_own_name(self):
        for locale in build_site.ORDER:
            text = build_site.render(locale)
            for other in build_site.ORDER:
                with self.subTest(page=locale, offers=other):
                    self.assertIn(LANGUAGE_META[other]["native_name"], text)
                    self.assertIn(f'hreflang="{build_site.html_lang(other)}"', text)

    def test_a_translated_page_reaches_the_shared_assets(self):
        text = build_site.render("ja")
        self.assertIn('src="../assets/logo.png"', text)
        self.assertIn('src="../lang.js"', text)
        self.assertNotIn('src="assets/', text)


class TheBuildScriptTests(unittest.TestCase):
    def test_check_passes_on_a_fresh_build(self):
        self.assertEqual(build_site.main(["--check"]), 0)

    def test_a_missing_string_names_the_language_and_key(self):
        with self.assertRaisesRegex(KeyError, "fr: no string for"):
            build_site.render("fr", template="{{nope}}", strings={"lang.label": "Langue"})

    def test_slugs_and_tags(self):
        self.assertEqual(build_site.slug("en"), "")
        self.assertEqual(build_site.slug("zh_CN"), "zh-cn")
        self.assertEqual(build_site.html_lang("pt_BR"), "pt-BR")
        self.assertTrue(build_site.page_url("ta").endswith("/OpenEmux/ta/"))


if __name__ == "__main__":
    unittest.main()
