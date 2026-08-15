"""Applying the chosen theme to libadwaita (issue #198).

The only place that talks to ``Adw.StyleManager``. Kept apart from the window
so the app can set the scheme before any window exists -- switching it after
the first one is drawn is a visible flash.
"""

import gi

gi.require_version("Adw", "1")
from gi.repository import Adw

from openemux.core.theme import THEME_DARK, THEME_LIGHT, normalize_theme

_COLOR_SCHEMES = {
    THEME_LIGHT: Adw.ColorScheme.FORCE_LIGHT,
    THEME_DARK: Adw.ColorScheme.FORCE_DARK,
}


def apply_theme(theme):
    """Force light or dark; ``system`` hands the choice back to the desktop."""
    scheme = _COLOR_SCHEMES.get(normalize_theme(theme), Adw.ColorScheme.DEFAULT)
    Adw.StyleManager.get_default().set_color_scheme(scheme)


def is_dark():
    """Whether the interface is being painted dark *right now*.

    Not the same question as the stored setting: under ``system`` the answer
    is the desktop's, and it can change while the app is open.
    """
    return bool(Adw.StyleManager.get_default().get_dark())
