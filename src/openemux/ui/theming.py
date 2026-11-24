"""Applying the chosen theme to libadwaita (issue #198, custom themes issue 1011).

The only place that talks to ``Adw.StyleManager``. Kept apart from the window
so the app can set the scheme before any window exists -- switching it after
the first one is drawn is a visible flash.

A custom theme is its base's color scheme plus one app-wide
``Gtk.CssProvider`` holding the stylesheet generated from its values
(``theme_css``). Switching themes swaps that provider's text; a built-in
theme empties it. Nothing needs a restart.
"""

import logging

import gi

gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gdk, Gtk

from openemux.core.theme import THEME_DARK, THEME_LIGHT, THEME_SYSTEM, normalize_theme
from openemux.ui import theme_css

logger = logging.getLogger(__name__)

_COLOR_SCHEMES = {
    THEME_LIGHT: Adw.ColorScheme.FORCE_LIGHT,
    THEME_DARK: Adw.ColorScheme.FORCE_DARK,
}

#: Above the app's ``style.css`` (APPLICATION) so a theme's rules win over
#: it. Big Picture's dress sits at the same level, and its rules, all under
#: ``.big-picture``, are the more specific ones, so it keeps its own palette
#: (theming it is a later part of issue 1010).
PROVIDER_PRIORITY = Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1

_provider = None
#: Big Picture is on screen: it keeps its own dark palette, so the custom
#: provider is emptied until it closes (issue 1011; theming it is part 5).
_suspended = False
#: What is on screen: (theme id, base, values), for ``restore``.
_applied = (THEME_SYSTEM, None, {})


def uses_css_variables():
    """libadwaita 1.6 paints from CSS variables; 1.5 rejects their syntax."""
    return (Adw.get_major_version(), Adw.get_minor_version()) >= (1, 6)


def _custom_provider():
    global _provider
    if _provider is None:
        display = Gdk.Display.get_default()
        if display is None:
            return None
        _provider = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_display(display, _provider, PROVIDER_PRIORITY)
    return _provider


def _load_css(text):
    provider = _custom_provider()
    if provider is not None:
        # load_from_string is GTK 4.12+; load_from_data is what 4.10 had.
        if hasattr(provider, "load_from_string"):
            provider.load_from_string(text)
        else:  # pragma: no cover - GTK older than 4.12, never in CI or the devbox
            provider.load_from_data(text, -1)


def paint(base, values):
    """Paint ``values`` over ``base`` (light or dark) right now."""
    Adw.StyleManager.get_default().set_color_scheme(_COLOR_SCHEMES[base])
    if not _suspended:
        _load_css(theme_css.stylesheet(values, css_variables=uses_css_variables()))


def apply_theme(theme, store=None):
    """Put ``theme`` on screen: a built-in one, or a custom id from ``store``.

    A custom id with no readable theme behind it paints ``system``. Returns
    the theme id that was actually applied.
    """
    global _applied
    theme = normalize_theme(theme)
    custom = None
    if theme not in (THEME_SYSTEM, THEME_LIGHT, THEME_DARK):
        custom = store.get(theme) if store is not None else None
        if custom is None:
            logger.info("Theme %s is not available; using System", theme)
            theme = THEME_SYSTEM
    if custom is not None:
        paint(custom.base, custom.values)
        _applied = (theme, custom.base, dict(custom.values))
        return theme
    scheme = _COLOR_SCHEMES.get(theme, Adw.ColorScheme.DEFAULT)
    Adw.StyleManager.get_default().set_color_scheme(scheme)
    if _provider is not None:
        _load_css("")
    _applied = (theme, None, {})
    return theme


def restore():
    """Put back what the last ``apply_theme`` painted (after a live preview)."""
    theme, base, values = _applied
    if base is None:
        Adw.StyleManager.get_default().set_color_scheme(
            _COLOR_SCHEMES.get(theme, Adw.ColorScheme.DEFAULT)
        )
        if _provider is not None:
            _load_css("")
    else:
        paint(base, values)


def set_suspended(suspended):
    """Take the custom colors off while Big Picture is shown, and back after."""
    global _suspended
    if suspended == _suspended:
        return
    _suspended = suspended
    if suspended:
        if _provider is not None:
            _load_css("")
        return
    # The scheme is Big Picture's to give back; only the colors return here.
    _theme, base, values = _applied
    if base is not None:
        _load_css(theme_css.stylesheet(values, css_variables=uses_css_variables()))


def applied_theme():
    """The id ``apply_theme`` last put on screen."""
    return _applied[0]


def is_dark():
    """Whether the interface is being painted dark *right now*.

    Not the same question as the stored setting: under ``system`` the answer
    is the desktop's, and it can change while the app is open.
    """
    return bool(Adw.StyleManager.get_default().get_dark())
