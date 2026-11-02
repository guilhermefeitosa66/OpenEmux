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
        self.assertIn('src="../assets/logo-128.png"', text)
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
                    or k.startswith("share.cap")):
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
                hero = re.search(r'<section class="hero" id="top"[^>]*>(.*?)</section>', text, re.S).group(1)
                self.assertIn('id="watchVideo" href="', hero)
                self.assertIn("assets/openemux-promo.mp4", hero)


def _png_size(path):
    """A PNG's (width, height), from its IHDR chunk."""
    import struct

    with open(path, "rb") as f:
        head = f.read(24)
    assert head[:8] == b"\x89PNG\r\n\x1a\n", path
    return struct.unpack(">II", head[16:24])


def _css(text):
    return re.search(r"<style>(.*?)</style>", text, re.S).group(1)


def _blocks(css, opener):
    """The bodies of every ``opener { ... }`` block in ``css`` (braces balanced)."""
    out, start = [], 0
    while True:
        i = css.find(opener, start)
        if i < 0:
            return out
        j = css.index("{", i)
        depth, k = 1, j + 1
        while depth:
            depth += {"{": 1, "}": -1}.get(css[k], 0)
            k += 1
        out.append(css[j + 1:k - 1])
        start = k


class TheOpeningStageTests(unittest.TestCase):
    """The opening as a scroll stage: the desktop, then the phone (issue 686)."""

    FIRST_SCREEN_BUDGET = 600 * 1024
    PAGE_BUDGET = 6 * 1024 * 1024

    def setUp(self):
        self.en = (REPO / "docs" / "index.html").read_text(encoding="utf-8")
        self.css = _css(self.en)

    def test_the_opening_is_a_stage_with_the_desktop_and_the_phone(self):
        for locale in build_site.ORDER:
            text = build_site.render(locale)
            hero = re.search(r'<section class="hero" id="top" data-stage>(.*?)</section>', text, re.S)
            with self.subTest(locale=locale):
                self.assertIsNotNone(hero)
                hero = hero.group(1)
                self.assertIn('class="stage-sticky"', hero)
                layers = re.findall(r'<div class="(device-[a-z]+)" data-stage-layer>\s*<picture>(.*?)</picture>',
                                    hero, re.S)
                self.assertEqual([name for name, _ in layers], ["device-desktop", "device-phone"])
                self.assertIn("assets/desktop/grid-sfc.png", layers[0][1])
                self.assertIn("assets/android/library-snes.png", layers[1][1])
                for _, pic in layers:
                    self.assertIn('fetchpriority="high"', pic)

    def test_the_frames_are_css_only(self):
        # The desktop capture is the app's own window (header bar and window
        # buttons included): no second, fake title bar around it.
        hero = re.search(r'<section class="hero".*?</section>', self.en, re.S).group(0)
        self.assertNotIn("window-bar", hero)
        self.assertNotIn("window-bar", self.css)

    def test_the_phone_screen_is_centred_with_concentric_corners(self):
        phone = _blocks(self.css, ".device-phone {")[0]
        self.assertIn("padding: var(--bezel)", phone)
        self.assertIn("border-radius: var(--phone-r)", phone)
        self.assertIn("border: 1px solid", phone)
        screen = _blocks(self.css, ".device-phone img {")[-1]
        self.assertIn("border-radius: calc(var(--phone-r) - var(--bezel) - 1px)", screen)

    def test_only_transform_and_opacity_animate(self):
        frames = re.findall(r"@keyframes (stage-[a-z-]+)", self.css)
        self.assertEqual(sorted(frames), ["stage-desktop-in", "stage-phone-in"])
        for name in frames:
            body = _blocks(self.css, f"@keyframes {name}")[0]
            props = set(re.findall(r"([a-z-]+)\s*:", body))
            with self.subTest(keyframes=name):
                self.assertLessEqual(props, {"transform", "opacity", "animation-timing-function"})

    def test_motion_only_with_a_driver_and_never_under_reduced_motion(self):
        # Without a driver the CSS is the final composition: the tall height
        # and the sticky box appear only inside the motion query, under the
        # CSS driver's @supports or the script's .stage-js.
        outside = self.css
        for block in _blocks(self.css, "@media (prefers-reduced-motion: no-preference) and (max-width: 899px) and (min-height: 560px),") + _blocks(
                self.css, "@media (max-width: 899px) and (prefers-reduced-motion: no-preference)"):
            outside = outside.replace(block, "")
        self.assertNotIn("var(--stage-len", outside)
        self.assertNotIn("position: sticky;\n      top: var(--nav-h)", outside)
        motion = _blocks(self.css, "@media (prefers-reduced-motion: no-preference) and (max-width: 899px) and (min-height: 560px),")[0]
        self.assertIn("@supports (animation-timeline: view())", motion)
        self.assertIn(".stage-js [data-stage-layer]", motion)
        self.assertIn("animation-play-state: paused", motion)
        self.assertIn("calc(var(--p, 0) * -1s)", motion)
        # The script's query is the stylesheet's, so both drivers agree on when to move.
        self.assertIn('"(prefers-reduced-motion: no-preference) and (max-width: 899px) and (min-height: 560px), " +\n'
                      '        "(prefers-reduced-motion: no-preference) and (min-height: 640px)"', self.en)
        self.assertIn("(prefers-reduced-motion: no-preference) and (min-height: 640px) {", self.css)

    def test_scrolling_is_never_taken_over(self):
        self.assertNotIn("scroll-snap", self.css)
        engine = re.search(r"<!-- Scroll stages: the fallback driver.*?</script>", self.en, re.S).group(0)
        for needle in ("wheel", "touchmove", "touchstart", "keydown", "preventDefault", "scrollTo(",
                       "scrollBy(", "scrollIntoView"):
            with self.subTest(needle=needle):
                self.assertNotIn(needle, engine)
        self.assertIn('addEventListener("scroll", function () { if (motion.matches) request(); }, '
                      '{ passive: true })', engine)

    def test_the_first_screen_image_is_preloaded(self):
        head = self.en.split("</head>")[0]
        links = re.findall(r'<link rel="preload" as="image" type="image/avif" imagesrcset="([^"]*)" '
                           r'imagesizes="([^"]*)" fetchpriority="high" />', head)
        self.assertEqual(len(links), 1)
        source = re.search(r'<source type="image/avif" srcset="([^"]*)" sizes="([^"]*)" />', self.en)
        self.assertEqual(links[0], source.groups())
        self.assertIn("desktop/grid-sfc-", links[0][0])

    def test_the_link_preview_is_the_opening(self):
        self.assertIn('<meta property="og:image" content="https://guilhermefeitosa66.github.io/OpenEmux/'
                      'assets/og-opening.png" />', self.en)
        self.assertEqual(_png_size(REPO / "docs" / "assets" / "og-opening.png"), (1200, 630))
        self.assertIn('<meta property="og:image:width" content="1200" />', self.en)

    def test_the_header_logo_is_the_small_one(self):
        self.assertIn('href="assets/logo-128.png"', self.en)
        self.assertIn('<img src="assets/logo-128.png" width="30" height="30"', self.en)
        self.assertNotIn('"assets/logo.png"', self.en)
        self.assertEqual(_png_size(REPO / "docs" / "assets" / "logo-128.png"), (128, 128))

    def _weight(self, first_screen):
        docs = REPO / "docs"
        manifest = build_site.load_manifest()
        text = self.en
        total = len(text.encode("utf-8")) + (docs / "lang.js").stat().st_size
        pictures = re.findall(r"<picture><source.*?</picture>", text, re.S)
        if first_screen:
            pictures = [p for p in pictures if 'fetchpriority="high"' in p]
            plain = ["assets/logo-128.png"]
        else:
            # Every <img> outside a <picture>, the video's poster excluded.
            rest = re.sub(r"<picture><source.*?</picture>", "", text, flags=re.S)
            plain = sorted(set(re.findall(r'<img[^>]*\ssrc="(assets/[^"]+)"', rest)))
            total += sum(f.stat().st_size for f in (docs / "assets" / "carts").glob("*.webp"))
        total += sum((docs / p).stat().st_size for p in plain)
        for pic in pictures:
            source = re.search(r'<img src="assets/([^"]+)"', pic).group(1)
            largest = max((v for v in manifest[source]["variants"] if v["file"].endswith(".avif")),
                          key=lambda v: v["width"])
            total += (docs / "assets" / largest["file"]).stat().st_size
        return total

    def test_the_first_screen_fits_its_budget(self):
        self.assertLessEqual(self._weight(first_screen=True), self.FIRST_SCREEN_BUDGET)

    def test_the_whole_page_fits_its_budget(self):
        self.assertLessEqual(self._weight(first_screen=False), self.PAGE_BUDGET)

    def test_the_visitors_system_comes_first_among_the_downloads(self):
        cta = re.search(r'<div class="cta" id="downloads">(.*?)</div>', self.en, re.S).group(1)
        self.assertEqual(re.findall(r'data-os="([a-z]+)"', cta), ["linux", "windows", "android"])
        self.assertIn("/Android/i.test(ua)", self.en)
        self.assertIn("box.insertBefore(mine, box.firstChild)", self.en)


@unittest.skipUnless(importlib.util.find_spec("PIL"), "Pillow is a dev-only dependency")
class TheShareSequenceTests(unittest.TestCase):
    """Share nearby as a scroll stage: one transfer on both screens (issue 687)."""

    PHONE = ["phone-1-pick", "phone-2-code", "phone-3-progress", "phone-4-sent"]
    WINDOW = ["desktop-1-ready", "desktop-2-offer", "desktop-3-progress", "desktop-4-received", "desktop-4-library"]
    STAGE_MEDIA = "@media (prefers-reduced-motion: no-preference) and (min-height: 640px)"

    def setUp(self):
        self.en = (REPO / "docs" / "index.html").read_text(encoding="utf-8")
        self.css = _css(self.en)

    def _section(self, text):
        found = re.search(r'<section class="moment share" id="share" data-stage>(.*?)</section>', text, re.S)
        self.assertIsNotNone(found)
        return found.group(1)

    def test_one_stage_with_four_steps_of_real_captures_in_order(self):
        for locale in build_site.ORDER:
            share = self._section(build_site.render(locale))
            with self.subTest(locale=locale):
                self.assertEqual(share.count('class="stage-sticky share-stage"'), 1)
                self.assertEqual(share.count('<li class="share-step">'), 4)
                phones = re.findall(r'<div class="share-phone[^"]*"[^>]*>\s*<picture>.*?assets/share/([a-z0-9-]+)\.png',
                                    share, re.S)
                self.assertEqual(phones, self.PHONE)
                windows = re.findall(r'<img [^>]*\bsrc="[^"]*assets/share/(desktop-[a-z0-9-]+)\.png"', share)
                self.assertEqual(windows, self.WINDOW)
                images = re.findall(r"<img\s[^>]*>", share)
                self.assertEqual(len(images), 9)
                for tag in images:
                    self.assertIn('loading="lazy"', tag)
                    self.assertNotIn("fetchpriority", tag)
                self.assertEqual(share.count("<picture>"), 9)

    def test_the_second_step_shows_the_same_code_on_both_screens(self):
        for locale in build_site.ORDER:
            strings = build_site.load_strings(locale)
            with self.subTest(locale=locale):
                self.assertIn("506 807", strings["share.alt_phone2"])
                self.assertIn("506 807", strings["share.alt_desk2"])

    def test_four_captions_a_headline_and_one_sentence_each(self):
        english = build_site.load_strings("en")
        for locale in build_site.ORDER:
            strings = build_site.load_strings(locale)
            self.assertFalse([k for k in strings if k.startswith("share.step_")])
            for n in range(1, 5):
                key = f"share.cap{n}"
                with self.subTest(locale=locale, key=key):
                    parts = re.fullmatch(r"<h3>([^<]+)</h3>\s*<p>([^<]+)</p>", strings[key])
                    self.assertIsNotNone(parts, strings[key])
                    for part in parts.groups():
                        self.assertLessEqual(len(re.findall(r"[.!?。！？](\s|$)", part)), 1, part)
                    self.assertNotIn("!", strings[key])
                    if locale != "en":
                        self.assertNotEqual(strings[key], english[key])
            self.assertTrue(strings["share.steps_label"].strip())

    def test_the_captions_are_an_ordered_list_never_hidden(self):
        share = self._section(self.en)
        self.assertIn('<ol class="share-seq" aria-label="How it works">', share)
        self.assertNotIn("aria-live", share)
        self.assertNotIn("display: none", "".join(_blocks(self.css, ".share-cap")))
        self.assertIn('<div class="share-meter" aria-hidden="true">', share)

    def test_only_transform_and_opacity_animate_and_every_name_has_its_keyframes(self):
        frames = re.findall(r"@keyframes (share-[a-z0-9-]+)", self.css)
        self.assertEqual(len(frames), 13)
        for name in frames:
            body = _blocks(self.css, f"@keyframes {name} ")[0]
            with self.subTest(keyframes=name):
                self.assertLessEqual(set(re.findall(r"([a-z-]+)\s*:", body)), {"transform", "opacity"})
                self.assertIn(f".{name} {{ animation-name: {name} }}", self.css)
                self.assertRegex(self._section(self.en), rf'class="[^"]*\b{name}\b[^"]*" data-stage-layer')

    def test_without_a_driver_it_is_a_strip_of_cards(self):
        # The stage layout lives only under the motion query, for both
        # drivers; outside it the list is a grid of four cards.
        inside = "".join(_blocks(self.css, self.STAGE_MEDIA + " {")
                         + _blocks(self.css, self.STAGE_MEDIA + " and (max-width: 899px) {"))
        self.assertIn("@supports (animation-timeline: view())", inside)
        outside = self.css
        for block in _blocks(self.css, self.STAGE_MEDIA + " {") + _blocks(
                self.css, self.STAGE_MEDIA + " and (max-width: 899px) {"):
            outside = outside.replace(block, "")
        for driver in ("#share[data-stage] .share", "#share.stage-js .share"):
            with self.subTest(driver=driver):
                self.assertIn(driver + "-step {", inside)
                self.assertIn(driver + "-shots {", inside)
                self.assertNotIn(driver, outside)
        self.assertIn("grid-template-columns: repeat(4, minmax(0, 1fr))", _blocks(self.css, ".share-seq {")[0])
        # Too short for the window, the phone and the caption: the cards, still.
        short = _blocks(self.css, "@media (max-height: 639px) {")[0]
        self.assertIn("#share [data-stage-layer] {\n        animation: none", short)
        self.assertIn("min-height: 0", short)
        self.assertNotIn("prefers-reduced-motion: reduce", inside)

    def test_the_phone_screen_is_centred_with_concentric_corners(self):
        body = _blocks(self.css, ".share-phone {")[0]
        for rule in ("padding: var(--bezel)", "box-sizing: border-box", "border-radius: var(--phone-r)",
                     "border: 1px solid"):
            self.assertIn(rule, body)
        screen = _blocks(self.css, ".share-phone img {")[0]
        self.assertIn("border-radius: calc(var(--phone-r) - var(--bezel) - 1px)", screen)
        # Every layout changes the sizes only, never the construction.
        for block in _blocks(self.css, "share-phone {")[1:]:
            with self.subTest(block=block):
                self.assertNotRegex(block, r"(padding|border-radius|border|box-sizing)\s*:")

    def test_the_window_is_the_capture_itself(self):
        share = self._section(self.en)
        self.assertNotIn("window-bar", share)
        self.assertNotIn(".share-window::before", self.css)
        self.assertNotIn(".share-window::after", self.css)

    def test_scrolling_is_never_taken_over(self):
        self.assertNotIn("scroll-snap", self.css)
        # The engine's one driver moves it: no script of its own.
        scripts = "".join(re.findall(r"<script>(.*?)</script>", self.en, re.S))
        for needle in ("share", "wheel", "touchmove"):
            self.assertNotIn(needle, scripts)


class TheSiteArtTests(unittest.TestCase):
    """tools/site_art.py: the link preview and the small logo (issue 686)."""

    def setUp(self):
        spec = importlib.util.spec_from_file_location("site_art", REPO / "tools" / "site_art.py")
        self.art = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.art)

    def test_both_images_at_their_sizes(self):
        with tempfile.TemporaryDirectory() as out:
            with redirect_stdout(io.StringIO()) as printed:
                self.assertEqual(self.art.main(["--out", out]), 0)
            self.assertIn("og-opening.png", printed.getvalue())
            self.assertEqual(_png_size(Path(out) / "og-opening.png"), (1200, 630))
            self.assertEqual(_png_size(Path(out) / "logo-128.png"), (128, 128))

    def test_without_pillow_it_says_what_to_install(self):
        with mock.patch.dict("sys.modules", {"PIL": None}):
            with self.assertRaises(SystemExit) as raised:
                self.art.build(out=tempfile.gettempdir())
        self.assertIn("Pillow", str(raised.exception))


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

    def test_the_first_eager_picture_is_preloaded_from_the_head(self):
        manifest = {"desktop/b.png": _entry(2640, 1756, "desktop/b", (640, 2640)),
                    "shelf/a.png": _entry()}
        page = ('<head>\n</head><body><img data-picture src="assets/shelf/a.png">'
                '<img data-picture="eager" data-sizes="50vw" src="assets/desktop/b.png">'
                '<img data-picture="eager" src="assets/shelf/a.png"></body>')
        out = build_site.apply_pictures(page, "", manifest)
        head = out.split("</head>")[0]
        self.assertEqual(head.count('rel="preload"'), 1)
        self.assertIn('imagesrcset="assets/desktop/b-640.avif 640w, assets/desktop/b-2640.avif 2640w" '
                      'imagesizes="50vw" fetchpriority="high"', head)

    def test_no_eager_picture_or_no_head_means_no_preload(self):
        manifest = {"shelf/a.png": _entry()}
        lazy = build_site.apply_pictures('<head></head><img data-picture src="assets/shelf/a.png">', "", manifest)
        self.assertNotIn("preload", lazy)
        headless = build_site.apply_pictures('<img data-picture="eager" src="assets/shelf/a.png">', "", manifest)
        self.assertNotIn("preload", headless)

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
