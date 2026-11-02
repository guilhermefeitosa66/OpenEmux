"""The GitHub Pages site, in every language the app speaks.

``docs/`` is generated from ``site/page.html`` and ``site/strings/`` by
``tools/build_site.py`` and committed, because Pages serves it as is. What
these tests hold: the published pages are exactly what the source builds,
every language has every string, and every page links to all the others.
The manual (``site/manual.html`` and ``site/manual/``) is held to the same,
and its UI labels to the app's own strings (issue #480).
"""

import hashlib
import html
import importlib
import importlib.util
import io
import json
import re
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

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
        def alts(text):
            return re.findall(r'<img\s[^>]*\balt="([^"]+)"', text.split("</header>", 1)[1])

        english = set(alts(build_site.render("en")))
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
                        self.assertNotIn(alt.group(1), english, "alt text left in English")

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


def _has_pillow_codecs():
    try:
        from PIL import features
    except ImportError:
        return False
    return bool(features.check("avif") and features.check("webp"))


def _entry(width=1200, height=800, stem="shelf/a", widths=(640, 1200)):
    variants = []
    for w in widths:
        for ext in ("avif", "webp"):
            variants.append({"file": f"{stem}-{w}.{ext}", "width": w,
                             "height": round(height * w / width), "sha256": "x"})
    return {"sha256": "x", "width": width, "height": height, "variants": variants}


class TheImagePipelineTests(unittest.TestCase):
    """AVIF/WebP widths and the <picture> helper (issue #683)."""

    def test_widths_below_the_source_then_the_source_itself(self):
        self.assertEqual(build_site.plan_widths(1200), [640, 1200])
        self.assertEqual(build_site.plan_widths(2640), [640, 1280, 1920, 2640])
        self.assertEqual(build_site.plan_widths(4000), [640, 1280, 1920, 2560, 4000])
        self.assertEqual(build_site.plan_widths(500), [500])

    def test_variant_names_sit_next_to_the_source(self):
        self.assertEqual(build_site.variant_name("shelf/sfc.png", 640, "avif"), "shelf/sfc-640.avif")

    def test_an_opted_in_image_becomes_a_lazy_picture(self):
        manifest = {"shelf/a.png": _entry()}
        tag = '<img data-picture data-sizes="380px" src="../assets/shelf/a.png" alt="A" class="x" />'
        out = build_site.picture(tag, "../", manifest)
        self.assertTrue(out.startswith('<picture><source type="image/avif" '
                                       'srcset="../assets/shelf/a-640.avif 640w, ../assets/shelf/a-1200.avif 1200w" '
                                       'sizes="380px" />'))
        self.assertIn('<source type="image/webp" srcset="../assets/shelf/a-640.webp 640w, '
                      '../assets/shelf/a-1200.webp 1200w" sizes="380px" />', out)
        self.assertIn('<img src="../assets/shelf/a.png" alt="A" class="x" width="1200" height="800" '
                      'loading="lazy" decoding="async" data-full="../assets/shelf/a-1200.webp" /></picture>', out)
        self.assertNotIn("data-picture", out)
        self.assertNotIn("data-sizes", out)

    def test_an_eager_image_is_fetched_first_and_sizes_default_to_the_viewport(self):
        manifest = {"desktop/b.png": _entry(2640, 1756, "desktop/b", (640, 2640))}
        out = build_site.picture('<img data-picture="eager" src="assets/desktop/b.png" width="9" loading="lazy">',
                                 "", manifest)
        self.assertIn('sizes="100vw"', out)
        self.assertIn('fetchpriority="high"', out)
        self.assertNotIn("loading=", out)
        self.assertIn('width="2640" height="1756"', out)
        self.assertNotIn('width="9"', out)

    def test_attributes_with_digits_and_underscores_are_kept(self):
        manifest = {"shelf/a.png": _entry()}
        out = build_site.picture('<img data-picture src="assets/shelf/a.png" data-x1="y" a_b="c" />',
                                 "", manifest)
        self.assertIn('data-x1="y"', out)
        self.assertIn('a_b="c"', out)

    def test_an_image_without_widths_is_named(self):
        with self.assertRaisesRegex(KeyError, "assets/shelf/nope.png"):
            build_site.picture('<img data-picture src="assets/shelf/nope.png" />', "", {})

    def test_only_opted_in_images_are_rewritten(self):
        manifest = {"shelf/a.png": _entry()}
        text = '<img src="assets/logo.png" /> <img data-picture src="assets/shelf/a.png" alt="" />'
        out = build_site.apply_pictures(text, "", manifest)
        self.assertTrue(out.startswith('<img src="assets/logo.png" /> <picture>'))
        self.assertEqual(out.count("<picture>"), 1)

    def test_every_carousel_shot_is_a_picture_on_every_page(self):
        manifest = build_site.load_manifest()
        for locale in build_site.ORDER:
            text = build_site.render(locale)
            root = "" if locale == "en" else "../"
            for name in ("sfc", "gba", "n64", "md", "sms", "ps", "favorites"):
                with self.subTest(locale=locale, shot=name):
                    self.assertIn(f'<img src="{root}assets/shelf/{name}.png"', text)
                    self.assertRegex(text, rf'<picture><source type="image/avif" srcset="{re.escape(root)}'
                                           rf'assets/shelf/{name}-640\.avif 640w')
            self.assertNotIn("data-picture", text)
        for entry in manifest.values():
            for variant in entry["variants"]:
                self.assertTrue((build_site.ASSETS / variant["file"]).is_file(), variant["file"])

    def test_the_desktop_captures_are_high_resolution(self):
        manifest = build_site.load_manifest()
        names = ["grid-sfc"] + [f"cart-{c}" for c in ("sfc", "fc", "gba", "n64", "md", "ps")]
        for name in names:
            with self.subTest(capture=name):
                entry = manifest[f"desktop/{name}.png"]
                self.assertGreaterEqual(entry["width"], 2560)
                widths = {v["width"] for v in entry["variants"]}
                self.assertTrue({640, 1280, 1920, entry["width"]} <= widths)

    def test_the_android_and_share_captures_are_all_there(self):
        # Issue 684: the Android imagery and one capture per Share nearby step,
        # on both devices, each with its AVIF/WebP widths.
        manifest = build_site.load_manifest()
        names = (
            ["android/library-snes"]
            + [f"android/game-{c}-portrait" for c in ("snes", "gba", "n64", "megadrive", "ps", "nds")]
            + [f"android/game-{c}-landscape" for c in ("gba", "nds")]
            + [f"share/phone-{s}" for s in ("1-pick", "1-what", "2-code", "3-progress", "4-sent")]
            + [f"share/desktop-{s}" for s in ("1-ready", "2-offer", "3-progress", "4-received", "4-library")]
        )
        for name in names:
            with self.subTest(capture=name):
                entry = manifest[f"{name}.png"]
                self.assertGreaterEqual(min(entry["width"], entry["height"]), 1080)
                formats = {Path(v["file"]).suffix for v in entry["variants"]}
                self.assertEqual(formats, {".avif", ".webp"})

    def test_a_missing_manifest_is_empty(self):
        self.assertEqual(build_site.load_manifest(Path("/nonexistent/images.json")), {})


class TheImageCheckTests(unittest.TestCase):
    """``--check`` on the images, against a scratch tree."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.assets = Path(tmp.name)
        (self.assets / "shelf").mkdir()
        (self.assets / "desktop").mkdir()
        self.source = self.assets / "shelf" / "a.png"
        self.source.write_bytes(b"png")
        self.variant = self.assets / "shelf" / "a-640.webp"
        self.variant.write_bytes(b"webp")
        sha = lambda b: hashlib.sha256(b).hexdigest()  # noqa: E731
        self.manifest = {"shelf/a.png": {"sha256": sha(b"png"), "width": 640, "height": 400, "variants": [
            {"file": "shelf/a-640.webp", "width": 640, "height": 400, "sha256": sha(b"webp")}]}}

    def check(self):
        return build_site.check_images(self.assets, self.manifest)

    def test_a_tree_that_matches_its_manifest_is_clean(self):
        self.assertEqual(self.check(), [])

    def test_a_changed_source_is_reported(self):
        self.source.write_bytes(b"png2")
        self.assertEqual(self.check(), ["shelf/a.png: changed since its widths were encoded"])

    def test_a_missing_or_edited_variant_is_reported(self):
        self.variant.write_bytes(b"other")
        self.assertEqual(self.check(), ["shelf/a-640.webp: changed since it was encoded"])
        self.variant.unlink()
        self.assertEqual(self.check(), ["shelf/a-640.webp: missing (variant of shelf/a.png)"])

    def test_a_new_source_without_widths_is_reported(self):
        (self.assets / "desktop" / "b.png").write_bytes(b"new")
        self.assertEqual(self.check(), ["desktop/b.png: no AVIF/WebP widths yet"])

    def test_an_entry_whose_source_is_gone_is_reported(self):
        self.manifest["shelf/gone.png"] = {"sha256": "x", "width": 1, "height": 1, "variants": []}
        self.assertEqual(self.check(), ["shelf/gone.png: in the manifest but gone"])

    def test_an_orphan_generated_file_is_reported(self):
        (self.assets / "shelf" / "old-1280.avif").write_bytes(b"x")
        (self.assets / "shelf" / "notes.txt").write_bytes(b"x")
        self.assertEqual(self.check(), ["shelf/old-1280.avif: generated file no source owns"])

    def test_check_fails_and_names_the_stale_images(self):
        out = io.StringIO()
        with mock.patch.object(build_site, "check_images", return_value=["shelf/a.png: changed"]), \
                redirect_stdout(out):
            self.assertEqual(build_site.main(["--check"]), 1)
        self.assertIn("run tools/build_site.py --images", out.getvalue())
        self.assertIn("shelf/a.png: changed", out.getvalue())

    # Mocks the encoder, so it runs where Pillow is absent too.
    def test_the_images_flag_encodes_then_writes_the_pages(self):
        out = io.StringIO()
        with mock.patch.object(build_site, "build_images", return_value=["desktop/a.png"]), \
                mock.patch.object(build_site, "pages", return_value={}), redirect_stdout(out):
            self.assertEqual(build_site.main(["--images"]), 0)
        self.assertIn("encoded docs/assets/desktop/a.png", out.getvalue())

    def test_images_without_pillow_says_what_to_install(self):
        with mock.patch.dict("sys.modules", {"PIL": None}):
            with self.assertRaisesRegex(SystemExit, "Pillow"):
                build_site.build_images(self.assets, self.assets / "images.json")


@unittest.skipUnless(_has_pillow_codecs(), "Pillow with AVIF and WebP is a dev-only dependency")
class TheImageEncoderTests(unittest.TestCase):
    def setUp(self):
        from PIL import Image

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.assets = Path(tmp.name) / "assets"
        (self.assets / "shelf").mkdir(parents=True)
        (self.assets / "desktop").mkdir()
        self.manifest_path = Path(tmp.name) / "images.json"
        Image.new("RGBA", (1500, 750), (40, 20, 90, 255)).save(self.assets / "desktop" / "a.png")

    def test_every_width_in_both_formats_and_a_manifest_the_check_accepts(self):
        self.assertEqual(build_site.build_images(self.assets, self.manifest_path), ["desktop/a.png"])
        manifest = json.loads(self.manifest_path.read_text())
        entry = manifest["desktop/a.png"]
        self.assertEqual((entry["width"], entry["height"]), (1500, 750))
        self.assertEqual([(v["file"], v["width"], v["height"]) for v in entry["variants"]], [
            ("desktop/a-640.avif", 640, 320), ("desktop/a-640.webp", 640, 320),
            ("desktop/a-1280.avif", 1280, 640), ("desktop/a-1280.webp", 1280, 640),
            ("desktop/a-1500.avif", 1500, 750), ("desktop/a-1500.webp", 1500, 750)])
        from PIL import Image
        with Image.open(self.assets / "desktop" / "a-640.avif") as image:
            self.assertEqual((image.format, image.size), ("AVIF", (640, 320)))
        self.assertEqual(build_site.check_images(self.assets, manifest), [])

    def test_a_second_run_encodes_nothing_and_a_removed_source_takes_its_widths(self):
        build_site.build_images(self.assets, self.manifest_path)
        stamp = (self.assets / "desktop" / "a-640.avif").stat().st_mtime_ns
        self.assertEqual(build_site.build_images(self.assets, self.manifest_path), [])
        self.assertEqual((self.assets / "desktop" / "a-640.avif").stat().st_mtime_ns, stamp)
        (self.assets / "desktop" / "a.png").unlink()
        self.assertEqual(build_site.build_images(self.assets, self.manifest_path), [])
        self.assertEqual(sorted(p.name for p in (self.assets / "desktop").iterdir()), [])
        self.assertEqual(json.loads(self.manifest_path.read_text()), {})

    def test_a_source_retaken_at_another_size_drops_the_widths_it_lost(self):
        from PIL import Image

        build_site.build_images(self.assets, self.manifest_path)
        Image.new("RGB", (1000, 500), (1, 2, 3)).save(self.assets / "desktop" / "a.png")
        self.assertEqual(build_site.build_images(self.assets, self.manifest_path), ["desktop/a.png"])
        self.assertEqual(sorted(p.name for p in (self.assets / "desktop").iterdir()), [
            "a-1000.avif", "a-1000.webp", "a-640.avif", "a-640.webp", "a.png"])
        manifest = json.loads(self.manifest_path.read_text())
        self.assertEqual(build_site.check_images(self.assets, manifest), [])

    def test_a_deleted_variant_is_encoded_again(self):
        build_site.build_images(self.assets, self.manifest_path)
        (self.assets / "desktop" / "a-1280.webp").unlink()
        self.assertEqual(build_site.build_images(self.assets, self.manifest_path), ["desktop/a.png"])
        self.assertTrue((self.assets / "desktop" / "a-1280.webp").is_file())


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
