#!/usr/bin/env python3
"""Build the GitHub Pages site in every language the app speaks.

The site is one page, kept as a template (``site/page.html``) and one string
table per language (``site/strings/<locale>.json``). This writes English to
``docs/index.html`` -- the URL every link already points at -- and each other
language to ``docs/<slug>/index.html``, with the language picker, ``hreflang``
and ``lang`` set for that page.

The manual is built the same way, from ``site/manual.html`` and
``site/manual/<locale>.json``: English at ``docs/manual/``, the others at
``docs/<slug>/manual/``. Its screenshots stay in ``docs/manual/img`` for every
language.

The languages are the app's own (``openemux.i18n.LANGUAGE_META``): the site
offers exactly what the app offers, under the same flag and native name.

    tools/build_site.py           write the pages
    tools/build_site.py --images  encode the screenshots' AVIF/WebP widths too
    tools/build_site.py --check   exit 1 if a page or an image in docs/ is out of date

Screenshots are served through ``<picture>`` (issue #683). Every PNG matched by
``IMAGE_SOURCES`` gets AVIF and WebP siblings at the ``WIDTHS`` that fit it,
and ``site/images.json`` records each source's hash and each variant's size
and hash. ``--images`` is the only step that needs Pillow (a dev-only
dependency); ``--check`` compares hashes against that manifest, so it stays on
the standard library and never depends on which encoder version is installed.
An ``<img data-picture ...>`` in the template becomes the ``<picture>``.

The generated pages are committed, because GitHub Pages serves docs/ as is.
``tests/test_site.py`` runs the check, so a template or string edit that was
not rebuilt fails the suite instead of shipping half a change.
"""

import argparse
import hashlib
import html
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from openemux.i18n import LANGUAGE_META  # noqa: E402

SITE_URL = "https://guilhermefeitosa66.github.io/OpenEmux/"
TEMPLATE = REPO / "site" / "page.html"
STRINGS = REPO / "site" / "strings"
MANUAL_TEMPLATE = REPO / "site" / "manual.html"
MANUAL_STRINGS = REPO / "site" / "manual"
DOCS = REPO / "docs"
ASSETS = DOCS / "assets"
IMAGE_MANIFEST = REPO / "site" / "images.json"

#: The PNGs, under docs/assets/, that get AVIF/WebP widths and a <picture>.
IMAGE_SOURCES = ("desktop/*.png", "shelf/*.png", "android/*.png", "share/*.png")

#: The responsive widths offered, each only when it is below the source's own.
WIDTHS = (640, 1280, 1920, 2560)

#: Encoder settings: high enough that UI text stays crisp. The PNG masters
#: stay TrueColor and lossless (they are the <img> fallback).
AVIF_QUALITY = 70
WEBP_QUALITY = 85

#: A generated variant's file name: ``<stem>-<width>.<avif|webp>``.
VARIANT = re.compile(r"-(\d+)\.(avif|webp)$")

#: The order the picker lists them in. English first, as the default page.
ORDER = ("en", "pt_BR", "es", "fr", "de", "ja", "zh_CN", "ta")

PLACEHOLDER = re.compile(r"\{\{([a-zA-Z0-9_.-]+)\}\}")


def slug(locale):
    """The page's directory: ``""`` for English (the site root), ``pt-br`` …"""
    return "" if locale == "en" else locale.lower().replace("_", "-")


def html_lang(locale):
    """The BCP 47 tag for ``lang`` and ``hreflang``: ``pt-BR``, ``zh-CN`` …"""
    return locale.replace("_", "-")


def page_url(locale, page=""):
    """The page's public URL; ``page`` is ``"manual/"`` for the manual."""
    return SITE_URL + (slug(locale) + "/" if slug(locale) else "") + page


def load_strings(locale):
    return json.loads((STRINGS / f"{locale}.json").read_text(encoding="utf-8"))


def load_manual_strings(locale):
    return json.loads((MANUAL_STRINGS / f"{locale}.json").read_text(encoding="utf-8"))


def hreflang_links(page=""):
    lines = [
        f'  <link rel="alternate" hreflang="{html_lang(loc)}" href="{page_url(loc, page)}" />'
        for loc in ORDER
    ]
    lines.append(f'  <link rel="alternate" hreflang="x-default" href="{page_url("en", page)}" />')
    return "\n".join(lines)


def lang_switcher(current, label, page=""):
    """The picker: a <details> menu of links, so it works without JavaScript.

    Each entry is a link to the same page in that language, named in that
    language under its flag, the way the app's own language list shows it.
    ``page`` is ``"manual/"`` on the manual, whose pages sit one level deeper.
    """
    meta = LANGUAGE_META[current]
    root = "" if current == "en" else "../"
    if page:
        root += "../"
    items = []
    for loc in ORDER:
        entry = LANGUAGE_META[loc]
        href = root + (slug(loc) + "/" if slug(loc) else "") + page
        if not href:
            href = "./"
        current_attr = ' aria-current="page"' if loc == current else ""
        items.append(
            f'          <li><a href="{href}" hreflang="{html_lang(loc)}" lang="{html_lang(loc)}"'
            f'{current_attr}><span class="flag" aria-hidden="true">{entry["flag"]}</span>'
            f'{html.escape(entry["native_name"])}</a></li>'
        )
    return (
        '<details class="lang-switch">\n'
        f'        <summary aria-label="{html.escape(label)}: {html.escape(meta["native_name"])}">'
        f'<span class="flag" aria-hidden="true">{meta["flag"]}</span>'
        f'<span class="lang-name">{html.escape(meta["native_name"])}</span></summary>\n'
        '        <ul>\n' + "\n".join(items) + "\n        </ul>\n"
        "      </details>"
    )


def render(locale, template=None, strings=None, manifest=None):
    template = template if template is not None else TEMPLATE.read_text(encoding="utf-8")
    strings = strings if strings is not None else load_strings(locale)
    root = "" if locale == "en" else "../"
    # A few strings carry an <img> of their own (a screenshot with its
    # caption): their asset paths need the same "../" as the template's.
    values = {key: value.replace('src="assets/', f'src="{root}assets/') for key, value in strings.items()}
    values.update(
        {
            "root": root,
            "html_lang": html_lang(locale),
            # Only the root page picks a language by itself (lang.js): a
            # translated page a person opened is the page they asked for.
            "auto_attr": " data-lang-auto" if locale == "en" else "",
            "canonical": page_url(locale),
            "hreflang_links": hreflang_links(),
            "lang_switcher": lang_switcher(locale, strings["lang.label"]),
        }
    )

    def _sub(match):
        key = match.group(1)
        if key not in values:
            raise KeyError(f"{locale}: no string for {{{{{key}}}}}")
        return values[key]

    return apply_pictures(PLACEHOLDER.sub(_sub, template), root, manifest)


def render_manual(locale, template=None, strings=None):
    """The manual in ``locale``. Its own strings, plus the site's picker label."""
    template = template if template is not None else MANUAL_TEMPLATE.read_text(encoding="utf-8")
    values = dict(strings if strings is not None else load_manual_strings(locale))
    values.update(
        {
            "html_lang": html_lang(locale),
            "canonical": page_url(locale, "manual/"),
            "hreflang_links": hreflang_links("manual/"),
            "lang_switcher": lang_switcher(locale, load_strings(locale)["lang.label"], "manual/"),
            # docs/manual/ or docs/<slug>/manual/: the shared assets and the
            # screenshots, which every language reads from the English folder.
            "assets": "../" if locale == "en" else "../../",
            "img": "" if locale == "en" else "../../manual/",
        }
    )

    def _sub(match):
        key = match.group(1)
        if key not in values:
            raise KeyError(f"{locale}: no manual string for {{{{{key}}}}}")
        return values[key]

    return PLACEHOLDER.sub(_sub, template)


def plan_widths(width):
    """The widths a source ``width`` px wide is offered at, smallest first.

    The listed ``WIDTHS`` below it, then the source itself; a listed width
    within 5% of the source would be a second copy of it, so it is dropped.
    """
    return [w for w in WIDTHS if w < width * 0.95] + [width]


def variant_name(source, width, ext):
    """``shelf/sfc.png`` at 640 px as AVIF -> ``shelf/sfc-640.avif``."""
    return f"{source[: -len('.png')]}-{width}.{ext}"


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def image_sources(assets=None):
    """The source PNGs, relative to ``assets`` with ``/``, sorted."""
    assets = assets if assets is not None else ASSETS
    found = set()
    for pattern in IMAGE_SOURCES:
        found.update(p.relative_to(assets).as_posix() for p in assets.glob(pattern))
    return sorted(found)


def load_manifest(path=None):
    path = path if path is not None else IMAGE_MANIFEST
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def build_images(assets=None, manifest_path=None):
    """Encode the AVIF/WebP widths of every source that changed; write the manifest.

    A source whose hash and variants still match its manifest entry is left
    alone, so running this again never re-encodes (and never churns bytes
    because a newer libavif came along). Returns the sources it encoded.
    """
    assets = assets if assets is not None else ASSETS
    manifest_path = manifest_path if manifest_path is not None else IMAGE_MANIFEST
    try:
        from PIL import Image
    except ImportError:
        raise SystemExit("--images needs Pillow: pip install -r requirements-dev.lock") from None
    old = load_manifest(manifest_path)
    manifest, encoded = {}, []
    for source in image_sources(assets):
        digest = _sha256(assets / source)
        entry = old.get(source)
        if entry and entry["sha256"] == digest and not _variant_problems(assets, source, entry):
            manifest[source] = entry
            continue
        with Image.open(assets / source) as image:
            image = image.convert("RGB")
            width, height = image.size
            variants = []
            for w in plan_widths(width):
                h = round(height * w / width)
                scaled = image if w == width else image.resize((w, h), Image.LANCZOS)
                for ext, options in (
                    ("avif", {"quality": AVIF_QUALITY, "speed": 4}),
                    ("webp", {"quality": WEBP_QUALITY, "method": 6}),
                ):
                    name = variant_name(source, w, ext)
                    scaled.save(assets / name, ext.upper(), **options)
                    variants.append({"file": name, "width": w, "height": h,
                                     "sha256": _sha256(assets / name)})
        manifest[source] = {"sha256": digest, "width": width, "height": height,
                            "variants": variants}
        encoded.append(source)
    # A removed source takes its widths along, and a re-encoded one whose
    # widths changed (a capture retaken at another size) drops the ones it no
    # longer has: either would be an orphan --check fails on.
    keep = {v["file"] for entry in manifest.values() for v in entry["variants"]}
    for entry in old.values():
        for variant in entry["variants"]:
            if variant["file"] not in keep:
                (assets / variant["file"]).unlink(missing_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return encoded


def _variant_problems(assets, source, entry):
    problems = []
    for variant in entry["variants"]:
        path = assets / variant["file"]
        if not path.is_file():
            problems.append(f"{variant['file']}: missing (variant of {source})")
        elif _sha256(path) != variant["sha256"]:
            problems.append(f"{variant['file']}: changed since it was encoded")
    return problems


def check_images(assets=None, manifest=None):
    """What is out of date between the source PNGs, their variants and the manifest."""
    assets = assets if assets is not None else ASSETS
    manifest = manifest if manifest is not None else load_manifest()
    sources = image_sources(assets)
    problems = []
    for source in sources:
        entry = manifest.get(source)
        if entry is None:
            problems.append(f"{source}: no AVIF/WebP widths yet")
        elif _sha256(assets / source) != entry["sha256"]:
            problems.append(f"{source}: changed since its widths were encoded")
        else:
            problems.extend(_variant_problems(assets, source, entry))
    problems.extend(f"{source}: in the manifest but gone" for source in sorted(set(manifest) - set(sources)))
    known = {v["file"] for entry in manifest.values() for v in entry["variants"]}
    for pattern in IMAGE_SOURCES:
        folder = assets / pattern.rsplit("/", 1)[0]
        for path in sorted(folder.glob("*")):
            name = path.relative_to(assets).as_posix()
            if VARIANT.search(name) and name not in known:
                problems.append(f"{name}: generated file no source owns")
    return problems


IMG_TAG = re.compile(r"<img\b[^>]*\bdata-picture\b[^>]*>")
ATTR = re.compile(r'\s([a-zA-Z_:][-a-zA-Z0-9_:.]*)(?:="([^"]*)")?')


def picture(tag, root, manifest):
    """One opted-in ``<img data-picture ...>`` as a ``<picture>``.

    ``data-picture="eager"`` marks a first-screen image (no lazy loading, a
    high fetch priority); ``data-sizes`` is the ``sizes`` (default ``100vw``).
    Every other attribute is kept as written.
    """
    attrs = ATTR.findall(tag[len("<img"):])
    values = dict(attrs)
    prefix = f"{root}assets/"
    src = values.get("src", "")
    source = src[len(prefix):] if src.startswith(prefix) else src
    if source not in manifest:
        raise KeyError(f"{src}: data-picture on an image with no AVIF/WebP widths (run --images)")
    entry = manifest[source]
    eager = values.get("data-picture") == "eager"
    sizes = values.get("data-sizes", "100vw")
    sources = []
    for ext in ("avif", "webp"):
        srcset = ", ".join(f"{prefix}{v['file']} {v['width']}w"
                           for v in entry["variants"] if v["file"].endswith("." + ext))
        sources.append(f'<source type="image/{ext}" srcset="{srcset}" sizes="{sizes}" />')
    largest = max((v for v in entry["variants"] if v["file"].endswith(".webp")), key=lambda v: v["width"])
    kept = [(k, v) for k, v in attrs if k not in ("data-picture", "data-sizes", "width", "height",
                                                    "loading", "decoding", "fetchpriority")]
    loading = [("fetchpriority", "high")] if eager else [("loading", "lazy")]
    out = kept + [("width", str(entry["width"])), ("height", str(entry["height"]))] + loading + [
        ("decoding", "async"), ("data-full", prefix + largest["file"])]
    img = "<img" + "".join(f' {k}="{v}"' for k, v in out) + " />"
    return "<picture>" + "".join(sources) + img + "</picture>"


def apply_pictures(text, root, manifest=None):
    """Every ``<img data-picture ...>`` in a rendered page as a ``<picture>``."""
    manifest = manifest if manifest is not None else load_manifest()
    return IMG_TAG.sub(lambda m: picture(m.group(0), root, manifest), text)


def output_path(locale):
    return DOCS / (slug(locale) + "/index.html" if slug(locale) else "index.html")


def manual_output_path(locale):
    return DOCS / (slug(locale) + "/manual" if slug(locale) else "manual") / "index.html"


def pages():
    template = TEMPLATE.read_text(encoding="utf-8")
    manual = MANUAL_TEMPLATE.read_text(encoding="utf-8")
    manifest = load_manifest()
    built = {output_path(loc): render(loc, template, manifest=manifest) for loc in ORDER}
    built.update({manual_output_path(loc): render_manual(loc, manual) for loc in ORDER})
    return built


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail if docs/ is out of date")
    parser.add_argument("--images", action="store_true",
                        help="encode the screenshots' AVIF/WebP widths (needs Pillow)")
    args = parser.parse_args(argv)

    if args.images and not args.check:
        for source in build_images():
            print(f"encoded docs/assets/{source}")
    problems = check_images() if args.check else []
    if problems:
        print("images out of date (run tools/build_site.py --images):", *problems, sep="\n  ")
    stale = []
    for path, text in pages().items():
        current = path.read_text(encoding="utf-8") if path.exists() else None
        if current == text:
            continue
        if args.check:
            stale.append(path.relative_to(REPO))
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        print(f"wrote {path.relative_to(REPO)}")
    if stale:
        print("out of date (run tools/build_site.py):", *stale, sep="\n  ")
    return 1 if stale or problems else 0

if __name__ == "__main__":
    sys.exit(main())
