"""The GitHub Pages site, in every language the app speaks.

``docs/`` is generated from ``site/page.html`` and ``site/strings/`` by
``tools/build_site.py`` and committed, because Pages serves it as is. What
these tests hold: the published pages are exactly what the source builds,
every language has every string, and every page links to all the others.
The manual (``site/manual.html`` and ``site/manual/``) is held to the same,
and its UI labels to the app's own strings (issue #480).
"""

import html
import importlib
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


    def test_every_language_states_the_relationship_with_openemu(self):
        # The hero line and the credits say the same thing in every language,
        # and the credits point at the icon attribution.
        for locale in build_site.ORDER:
            strings = build_site.load_strings(locale)
            with self.subTest(locale=locale):
                self.assertIn('href="https://openemu.org/"', strings["hero.relation"])
                self.assertIn('href="#thanks"', strings["hero.relation"])
                self.assertIn('href="https://openemu.org/"', strings["thanks.lede"])
                self.assertIn("ATTRIBUTION.md", strings["thanks.lede"])


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


class TheNarrativeTests(unittest.TestCase):
    """The page tells the story of the issue 680 redesign, in order (issue 685)."""

    ORDER = ("top", "share", "consoles", "android", "cartridges", "install", "more", "thanks", "support")
    MOMENTS = ("share", "shots", "android")

    def test_every_page_follows_the_narrative_order(self):
        for locale in build_site.ORDER:
            ids = re.findall(r'<section[^>]* id="([a-z]+)"', build_site.render(locale))
            with self.subTest(locale=locale):
                self.assertEqual(tuple(ids), self.ORDER)

    def test_each_moment_is_a_short_headline_and_at_most_two_sentences(self):
        english = build_site.load_strings("en")
        for moment in self.MOMENTS:
            with self.subTest(moment=moment):
                headline = re.sub(r"<[^>]+>", "", english[f"{moment}.title"])
                self.assertTrue(2 <= len(headline.split()) <= 6, headline)
                lede = re.sub(r"<[^>]+>", "", english[f"{moment}.lede"])
                self.assertLessEqual(len(re.findall(r"[.!?](\s|$)", lede)), 2, lede)
        self.assertTrue(2 <= len(re.sub(r"<[^>]+>", " ", english["hero.title"]).split()) <= 6)
        for locale in build_site.ORDER:
            strings = build_site.load_strings(locale)
            for key in ("hero.title", "hero.lede") + tuple(
                    k for k in strings if k.split(".")[0] in self.MOMENTS and k.split(".")[1] in ("title", "lede")
                    or k.startswith("share.step_")):
                with self.subTest(locale=locale, key=key):
                    self.assertNotIn("!", strings[key])
                    self.assertNotIn("！", strings[key])

    def test_nothing_of_the_folded_sections_is_lost(self):
        # Features, philosophy and systems became the "Everything else" grid.
        for locale in build_site.ORDER:
            strings = build_site.load_strings(locale)
            more = re.search(r'<section id="more">(.*?)</section>', build_site.render(locale), re.S).group(1)
            with self.subTest(locale=locale):
                self.assertEqual(len(re.findall(r'<span class="chip">', more)), 31)
                for key in ("features.shelf", "features.first_boot", "features.controls", "features.shaders",
                            "features.native", "features.bios", "more.retroarch", "philosophy.lede",
                            "philosophy.own", "philosophy.piracy", "philosophy.history", "systems.lede",
                            "android.skins", "android.carts", "android.setup", "android.gamepad",
                            "android.themes", "android.languages", "android.achievements"):
                    self.assertIn(strings[key], more)

    def test_every_image_has_alt_text_in_every_language(self):
        english = build_site.render("en")
        for locale in build_site.ORDER:
            text = build_site.render(locale)
            # The logo beside the "OpenEmux" name in the header is decorative;
            # the wall's cartridges are built by the script and labelled as a whole.
            images = re.findall(r"<img\s[^>]*>", text.split("</header>", 1)[1])
            with self.subTest(locale=locale):
                self.assertGreater(len(images), 10)
                for tag in images:
                    if 'id="lightboxImg"' in tag:
                        continue
                    alt = re.search(r'alt="([^"]*)"', tag)
                    self.assertTrue(alt and alt.group(1).strip(), tag)
                    if locale != "en":
                        self.assertNotIn(tag, english, "alt text left in English")

    def test_the_promo_video_loads_only_on_demand(self):
        for locale in build_site.ORDER:
            text = build_site.render(locale)
            videos = re.findall(r"<video\s[^>]*>", text)
            with self.subTest(locale=locale):
                self.assertEqual(len(videos), 1)
                self.assertNotIn("autoplay", videos[0])
                self.assertIn('preload="none"', videos[0])
                self.assertNotRegex(videos[0], r'\ssrc=|\sposter=')
                hero = re.search(r'<section class="hero" id="top">(.*?)</section>', text, re.S).group(1)
                self.assertIn('id="watchVideo" href="', hero)
                self.assertIn("assets/openemux-promo.mp4", hero)


def _app_strings(locale):
    return importlib.import_module(f"openemux.i18n.locales.{locale}").TRANSLATIONS


def _label(text):
    """A UI label as the manual quotes it: no mnemonic, no submenu arrow,
    "(…)" for a placeholder, no trailing ellipsis or colon."""
    text = html.unescape(text).replace("_", "").replace("▸", "")
    text = re.sub(r"[(（]\{\w+\}[)）]", "(…)", text).replace("（…）", "(…)")
    return re.sub(r"[…:：.]+$", "", text.strip()).strip()


class TheManualTests(unittest.TestCase):
    """The manual in every language (issue #480)."""

    def test_every_language_has_every_string_and_no_other(self):
        english = build_site.load_manual_strings("en")
        for locale in build_site.ORDER:
            strings = build_site.load_manual_strings(locale)
            with self.subTest(locale=locale):
                self.assertEqual(list(strings), list(english))
                self.assertTrue(all(value.strip() for value in strings.values()))

    def test_the_markup_survives_translation(self):
        def skeleton(value):
            value = re.sub(r'(alt|aria-label|content)="[^"]*"', r'\1=""', value)
            return re.findall(r"<[^>]+>|&[a-z]+;", value)

        english = build_site.load_manual_strings("en")
        for locale in build_site.ORDER:
            strings = build_site.load_manual_strings(locale)
            for key in english:
                with self.subTest(locale=locale, key=key):
                    self.assertEqual(skeleton(strings[key]), skeleton(english[key]))

    def test_ui_labels_are_the_apps_own_strings(self):
        # The manual names buttons and settings; a fresh translation would
        # name one the reader cannot find. Every quoted label the app has a
        # string for must be that string in each language.
        english_app = _app_strings("en")
        by_label = {}
        for key, value in english_app.items():
            if isinstance(value, str):
                by_label.setdefault(_label(value), []).append(key)
        english = build_site.load_manual_strings("en")
        span = re.compile(r'class="ui">([^<]*)<')
        checked = 0
        for locale in build_site.ORDER[1:]:
            app = _app_strings(locale)
            strings = build_site.load_manual_strings(locale)
            for key, value in english.items():
                for en_label, label in zip(span.findall(value), span.findall(strings[key])):
                    app_keys = by_label.get(_label(en_label))
                    if not app_keys:
                        continue
                    checked += 1
                    # A label can be several app strings ("Sync covers" is a
                    # button and a menu item); any of their translations will do.
                    with self.subTest(locale=locale, key=key, label=en_label):
                        self.assertIn(_label(label), {_label(app[k]) for k in app_keys if k in app})
        self.assertGreater(checked, 500)

    def test_each_language_gets_its_own_page(self):
        for locale in build_site.ORDER:
            text = build_site.render_manual(locale)
            with self.subTest(locale=locale):
                self.assertIn(f'<html lang="{build_site.html_lang(locale)}"', text)
                self.assertIn(f'href="{build_site.page_url(locale, "manual/")}"', text)
                for other in build_site.ORDER:
                    self.assertIn(
                        f'hreflang="{build_site.html_lang(other)}" '
                        f'href="{build_site.page_url(other, "manual/")}"', text)

    def test_the_picker_leads_to_the_manual_in_each_language(self):
        text = build_site.render_manual("pt_BR")
        self.assertIn('href="../../manual/" hreflang="en"', text)
        self.assertIn('href="../../ja/manual/" hreflang="ja"', text)
        self.assertIn('aria-current="page"', text)
        self.assertIn('href="../manual/" hreflang="en"', build_site.render_manual("en"))

    def test_a_translated_manual_reaches_the_shared_assets_and_screenshots(self):
        text = build_site.render_manual("ja")
        self.assertIn('src="../../assets/logo.png"', text)
        self.assertIn('src="../../manual/img/overview.webp"', text)
        for source in re.findall(r'src="([^"]+)"', build_site.render_manual("en")):
            if source.startswith("http"):
                continue
            with self.subTest(source=source):
                self.assertTrue((build_site.DOCS / "manual" / source).resolve().is_file())

    def test_the_site_links_each_language_to_its_own_manual(self):
        self.assertIn('href="manual/"', build_site.render("de"))
        self.assertNotIn("(auf Englisch)", build_site.render("de"))

    def test_a_missing_manual_string_names_the_language_and_key(self):
        with self.assertRaisesRegex(KeyError, "fr: no manual string for"):
            build_site.render_manual("fr", template="{{nope-1}}", strings={})


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
        self.assertTrue(build_site.page_url("ta", "manual/").endswith("/OpenEmux/ta/manual/"))
        self.assertEqual(build_site.manual_output_path("en"), build_site.DOCS / "manual" / "index.html")
        self.assertEqual(build_site.manual_output_path("zh_CN"),
                         build_site.DOCS / "zh-cn" / "manual" / "index.html")


if __name__ == "__main__":
    unittest.main()
