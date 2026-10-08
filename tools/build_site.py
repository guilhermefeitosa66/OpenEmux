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
    tools/build_site.py --check   exit 1 if a page in docs/ is out of date

The generated pages are committed, because GitHub Pages serves docs/ as is.
``tests/test_site.py`` runs the check, so a template or string edit that was
not rebuilt fails the suite instead of shipping half a change.
"""

import argparse
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


def render(locale, template=None, strings=None):
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

    return PLACEHOLDER.sub(_sub, template)


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


def output_path(locale):
    return DOCS / (slug(locale) + "/index.html" if slug(locale) else "index.html")


def manual_output_path(locale):
    return DOCS / (slug(locale) + "/manual" if slug(locale) else "manual") / "index.html"


def pages():
    template = TEMPLATE.read_text(encoding="utf-8")
    manual = MANUAL_TEMPLATE.read_text(encoding="utf-8")
    built = {output_path(loc): render(loc, template) for loc in ORDER}
    built.update({manual_output_path(loc): render_manual(loc, manual) for loc in ORDER})
    return built


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail if docs/ is out of date")
    args = parser.parse_args(argv)

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
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
