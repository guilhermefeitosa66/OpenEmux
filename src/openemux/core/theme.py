"""The interface theme the user picked (issue #198).

Three built-in values, stored as ``ui.theme``: ``system`` follows the desktop
-- what the app did before there was a setting at all -- while ``light`` and
``dark`` pin it regardless of what GNOME is doing. Besides those, ``ui.theme``
may hold the id of one of the user's own themes (issue 1011,
``openemux.core.custom_themes``). Config cannot know which theme folders
exist, so any well-formed id is kept here; one that has no folder is painted
as ``system`` when it is applied.

Only the vocabulary lives here, never libadwaita: config and its tests must
stay importable without GTK. The mapping onto ``Adw.ColorScheme`` is in
``openemux.ui.theming``.
"""

import re

THEME_SYSTEM = "system"
THEME_LIGHT = "light"
THEME_DARK = "dark"

#: Also the order the Preferences combo lists them in.
THEMES = (THEME_SYSTEM, THEME_LIGHT, THEME_DARK)

#: The ready-made themes the app ships (issue 1012): read-only, like the
#: three above, with the same ids on Android. Their colors and pictures are in
#: ``openemux.core.ready_themes``; the ids are reserved here so a user theme
#: can never take one.
READY_MADE = ("pastel", "dracula", "kitty", "neon", "tokyo-night")

DEFAULT_THEME = THEME_SYSTEM

#: A custom theme's id: its folder name, so lower-case, digits and dashes.
_CUSTOM_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,47}$")


def is_custom_theme_id(value):
    """Whether ``value`` can name a user theme (never a built-in one)."""
    return (
        isinstance(value, str)
        and value not in THEMES
        and value not in READY_MADE
        and bool(_CUSTOM_ID.match(value))
    )


def is_ready_made(value):
    return value in READY_MADE


def normalize_theme(value):
    """Anything unknown -- an older config, a hand-edited typo -- is the default."""
    if isinstance(value, str) and value.strip().lower() in THEMES:
        return value.strip().lower()
    if is_custom_theme_id(value) or is_ready_made(value):
        return value
    return DEFAULT_THEME


def toggled_theme(currently_dark):
    """What the header toggle switches to, given what is on screen right now.

    Deliberately reads the rendered appearance rather than the stored value:
    from ``system`` there is no "other" theme to flip to, but there is always
    a visible one to flip away from.
    """
    return THEME_LIGHT if currently_dark else THEME_DARK
