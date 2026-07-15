from openemux.i18n.locales import de, en, es, fr, ja, pt_BR, zh_CN

SUPPORTED_LOCALES = ["en", "de", "ja", "fr", "zh_CN", "pt_BR", "es"]

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
    return "en"


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
