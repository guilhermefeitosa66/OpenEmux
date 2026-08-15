"""The interface theme the user picked (issue #198).

Three values, stored as ``ui.theme``: ``system`` follows the desktop -- what
the app did before there was a setting at all -- while ``light`` and ``dark``
pin it regardless of what GNOME is doing.

Only the vocabulary lives here, never libadwaita: config and its tests must
stay importable without GTK. The mapping onto ``Adw.ColorScheme`` is in
``openemux.ui.theming``.
"""

THEME_SYSTEM = "system"
THEME_LIGHT = "light"
THEME_DARK = "dark"

#: Also the order the Preferences combo lists them in.
THEMES = (THEME_SYSTEM, THEME_LIGHT, THEME_DARK)

DEFAULT_THEME = THEME_SYSTEM


def normalize_theme(value):
    """Anything unknown -- an older config, a hand-edited typo -- is the default."""
    if isinstance(value, str) and value.strip().lower() in THEMES:
        return value.strip().lower()
    return DEFAULT_THEME


def toggled_theme(currently_dark):
    """What the header toggle switches to, given what is on screen right now.

    Deliberately reads the rendered appearance rather than the stored value:
    from ``system`` there is no "other" theme to flip to, but there is always
    a visible one to flip away from.
    """
    return THEME_LIGHT if currently_dark else THEME_DARK
