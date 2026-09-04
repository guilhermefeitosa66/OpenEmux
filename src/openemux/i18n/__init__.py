import os
import sys
from functools import lru_cache

from openemux.i18n.locales import de, en, es, fr, ja, pt_BR, ta, zh_CN

SUPPORTED_LOCALES = ["en", "de", "ja", "fr", "zh_CN", "pt_BR", "es", "ta"]

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
    "ta": {"name": "Tamil", "native_name": "தமிழ்", "flag": "🇮🇳"},
}

LOCALE_TRANSLATIONS = {
    "en": en.TRANSLATIONS,
    "de": de.TRANSLATIONS,
    "ja": ja.TRANSLATIONS,
    "fr": fr.TRANSLATIONS,
    "zh_CN": zh_CN.TRANSLATIONS,
    "pt_BR": pt_BR.TRANSLATIONS,
    "es": es.TRANSLATIONS,
    "ta": ta.TRANSLATIONS,
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

    Windows sets none of those variables, so it falls back to asking the OS
    (:func:`_windows_ui_locale`). Without that every Windows user silently gets
    English -- and the bug hides during development, because the MSYS2 login
    shell *does* export ``LANG``: it only appears once the app is launched from
    Explorer or the Start Menu, which is to say only in the shipped build.
    """
    env = os.environ if environ is None else environ
    environment_named_a_language = False
    for name in LOCALE_ENV_VARS:
        for candidate in (env.get(name) or "").split(":"):
            matched = match_locale(candidate)
            if matched:
                return matched
            if _canonical_locale_tag(candidate):
                # A real locale we simply do not ship, e.g. ru_RU.
                environment_named_a_language = True

    # Two conditions, both necessary.
    #
    # ``environ is None``: an explicitly passed mapping means "evaluate against
    # exactly this", not "and then ask the OS". Without it every caller that
    # supplies an environment -- the whole test suite included -- would inherit
    # the host's Windows display language, so the same test would pass on an
    # English Windows and fail on a Portuguese one.
    #
    # ``not environment_named_a_language``: a desktop that says "ru_RU" has
    # stated a preference we understand and cannot honour, so it gets English.
    # Overriding that with the Windows UI language would ignore an explicit
    # choice; only silence should fall through.
    if environ is None and not environment_named_a_language:
        matched = match_locale(_windows_ui_locale())
        if matched:
            return matched

    return DEFAULT_LOCALE


def _windows_ui_locale():
    """The Windows UI language as a ``pt_BR``-style string, or ``""``.

    ``GetUserDefaultUILanguage`` returns the language of the user's Windows
    display language, which is what "the desktop's language" means here --
    ``locale.getlocale()`` reports the *formatting* locale, which a user can
    and does set independently (English Windows with Brazilian number formats
    is a common pairing).
    """
    if sys.platform != "win32":
        return ""
    try:
        import ctypes

        lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        # LOCALE_SNAME gives a BCP-47 tag such as "pt-BR"; the rest of this
        # module speaks the POSIX "pt_BR" form.
        buffer = ctypes.create_unicode_buffer(85)
        # 0x0000005C == LOCALE_SNAME
        if ctypes.windll.kernel32.GetLocaleInfoW(lang_id, 0x0000005C, buffer, 85):
            return buffer.value.replace("-", "_")
    except Exception:  # noqa: BLE001 - a language guess must never break startup
        pass
    return ""


@lru_cache(maxsize=None)
def _merged_table(selected):
    """The locale's table over English, built once per locale.

    The tables are module constants, so the merge can only ever produce the
    same dict. Rebuilding it per lookup copied 2x591 entries every time, and
    the hot callers are per ROM card and per progress event (issue #231).
    """
    base = dict(LOCALE_TRANSLATIONS["en"])
    if selected != "en":
        base.update(LOCALE_TRANSLATIONS.get(selected, {}))
    return base


def merged_translations(locale):
    """A caller-owned copy of the locale's table."""
    return dict(_merged_table(normalize_locale(locale)))


def reset_translation_cache():
    """Forget the merged tables.

    The catalogs are module constants and the cache assumes it: anything that
    edits ``LOCALE_TRANSLATIONS`` at runtime -- which in practice is only a
    test simulating a locale that lacks a key -- has to call this afterwards.
    """
    _merged_table.cache_clear()


def tr(locale, key, **kwargs):
    selected = normalize_locale(locale)
    merged = _merged_table(selected)
    text = merged.get(key, LOCALE_TRANSLATIONS["en"].get(key, key))
    if kwargs:
        return text.format(**kwargs)
    return text
