import os

from openemux.i18n.locales import de, en, es, fr, ja, pt_BR, zh_CN

SUPPORTED_LOCALES = ["en", "de", "ja", "fr", "zh_CN", "pt_BR", "es"]

#: Fallback locale when nothing else matches.
DEFAULT_LOCALE = "en"

#: Regional variant to use when only the language is known and the language
#: itself is not a locale we ship (pt_PT -> pt_BR, zh_TW -> zh_CN).
LANGUAGE_FALLBACKS = {
    "pt": "pt_BR",
    "zh": "zh_CN",
}

#: Environment variables that describe the desktop language, most specific
#: first. This is the POSIX precedence glibc itself uses, minus LC_ALL's
#: override semantics, which do not matter for a read-only lookup.
LOCALE_ENV_VARS = ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG")

#: Locales that mean "no translation", not "English was chosen".
_NEUTRAL_LOCALES = {"c", "posix", ""}

LANGUAGE_META = {
    "en": {"name": "English", "native_name": "English", "flag": "🇺🇸"},
    "de": {"name": "German", "native_name": "Deutsch", "flag": "🇩🇪"},
    "ja": {"name": "Japanese", "native_name": "日本語", "flag": "🇯🇵"},
    "fr": {"name": "French", "native_name": "Français", "flag": "🇫🇷"},
    "zh_CN": {"name": "Mandarin", "native_name": "简体中文", "flag": "🇨🇳"},
    "pt_BR": {"name": "Portuguese (Brazil)", "native_name": "Português (Brasil)", "flag": "🇧🇷"},
    "es": {"name": "Spanish", "native_name": "Español", "flag": "🇪🇸"},
}

LOCALE_TRANSLATIONS = {
    "en": en.TRANSLATIONS,
    "de": de.TRANSLATIONS,
    "ja": ja.TRANSLATIONS,
    "fr": fr.TRANSLATIONS,
    "zh_CN": zh_CN.TRANSLATIONS,
    "pt_BR": pt_BR.TRANSLATIONS,
    "es": es.TRANSLATIONS,
}


def normalize_locale(locale):
    if locale in SUPPORTED_LOCALES:
        return locale
    return DEFAULT_LOCALE


def _canonical_locale_tag(value):
    """Reduce an OS locale string to ``language_REGION``.

    ``pt_BR.UTF-8``, ``pt-br@euro`` and ``pt_BR`` all collapse to ``pt_BR``.
    Returns ``""`` for the neutral C/POSIX locales and for junk.
    """
    tag = (value or "").strip()
    for separator in (".", "@"):
        tag = tag.split(separator, 1)[0]
    tag = tag.replace("-", "_")
    if tag.lower() in _NEUTRAL_LOCALES:
        return ""
    parts = tag.split("_")
    language = parts[0].lower()
    if not language.isalpha():
        return ""
    if len(parts) > 1 and parts[1]:
        return f"{language}_{parts[1].upper()}"
    return language


def match_locale(value):
    """Best supported locale for one OS locale string, or ``None``.

    Matching is exact first (``pt_BR`` -> ``pt_BR``), then by language alone,
    so a locale we ship no regional variant of still lands somewhere sensible:
    ``fr_CA`` -> ``fr``, ``pt_PT`` -> ``pt_BR``, ``en_GB`` -> ``en``.
    """
    tag = _canonical_locale_tag(value)
    if not tag:
        return None
    if tag in SUPPORTED_LOCALES:
        return tag
    language = tag.split("_")[0]
    if language in SUPPORTED_LOCALES:
        return language
    return LANGUAGE_FALLBACKS.get(language)


def detect_system_locale(environ=None):
    """The desktop's language as a supported locale, else ``en``.

    Reads the standard environment variables rather than ``locale.setlocale``:
    the process locale is "C" unless something calls setlocale, while these
    variables carry what the user actually picked in their session. ``LANGUAGE``
    holds a colon-separated preference list, which is walked in order.
    """
    env = os.environ if environ is None else environ
    for name in LOCALE_ENV_VARS:
        for candidate in (env.get(name) or "").split(":"):
            matched = match_locale(candidate)
            if matched:
                return matched
    return DEFAULT_LOCALE


def merged_translations(locale):
    selected = normalize_locale(locale)
    base = dict(LOCALE_TRANSLATIONS["en"])
    if selected != "en":
        base.update(LOCALE_TRANSLATIONS.get(selected, {}))
    return base


def tr(locale, key, **kwargs):
    selected = normalize_locale(locale)
    merged = merged_translations(selected)
    text = merged.get(key, LOCALE_TRANSLATIONS["en"].get(key, key))
    if kwargs:
        return text.format(**kwargs)
    return text
