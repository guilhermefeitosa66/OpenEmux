"""Applying the chosen theme to libadwaita (issue #198, custom themes issue 1011).

The only place that talks to ``Adw.StyleManager``. Kept apart from the window
so the app can set the scheme before any window exists -- switching it after
the first one is drawn is a visible flash.

A custom theme is its base's color scheme plus one app-wide
``Gtk.CssProvider`` holding the stylesheet generated from its values
(``theme_css``). Switching themes swaps that provider's text; a built-in
theme empties it. Nothing needs a restart.

A theme's background images (issue 1012) are painted from processed copies
(``theme_images``): one is used at once when it is already in the cache, and
otherwise rendered on a worker thread while the area shows its plain color;
the stylesheet is reloaded when it is ready, unless something else was
painted meanwhile. The sizes the widgets read themselves (grid gap, card
size, sidebar width) and Big Picture's palette are not CSS here: whoever
needs them registers with ``add_listener`` and reads ``current_paint()``.
"""

import logging
import threading
import weakref
from dataclasses import dataclass, field
from pathlib import Path

import gi

gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gdk, GLib, Gtk

from openemux.core import theme_images
from openemux.core.custom_themes import IMAGE_AREAS, IMAGE_SURFACES, KEYS_BY_NAME
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
#: Big Picture is on screen: it paints itself from the theme (issue 1012),
#: so the desktop's provider is emptied until it closes.
_suspended = False
#: What is on screen: (theme id, base, values, image dir), for ``restore``.
_applied = (THEME_SYSTEM, None, {}, None)
#: Where processed backgrounds are cached; set by the app at start-up.
_cache_dir = None
#: Bumped on every paint, so a background finishing late for an earlier
#: paint does not reload over a newer one.
_generation = 0
_listeners = []


@dataclass
class Paint:
    """What a custom theme put on screen; ``base`` is None for a built-in."""

    base: str = None
    values: dict = field(default_factory=dict)
    folder: Path = None
    #: area -> {"uri", "fit", "path"} for the backgrounds ready to show.
    backgrounds: dict = field(default_factory=dict)

    def effective(self, key):
        if key in self.values:
            return self.values[key]
        return KEYS_BY_NAME[key].default(self.base or THEME_DARK)


_paint = Paint()


def _spawn(target):
    threading.Thread(target=target, daemon=True).start()


def set_cache_dir(path):
    global _cache_dir
    _cache_dir = Path(path) if path is not None else None


def _ref(callback):
    # A window's method is held weakly: a window that went away without
    # saying so must not be kept alive, nor called, by the theme.
    if hasattr(callback, "__self__"):
        return weakref.WeakMethod(callback)
    return lambda: callback


def add_listener(callback):
    """Call ``callback()`` after every change of what is painted."""
    remove_listener(callback)
    _listeners.append(_ref(callback))


def remove_listener(callback):
    _listeners[:] = [ref for ref in _listeners if ref() not in (None, callback)]


def _notify():
    for ref in list(_listeners):
        callback = ref()
        if callback is None:
            continue
        try:
            callback()
        except Exception:  # noqa: BLE001 - one listener must not stop the rest
            logger.exception("Theme listener failed")


def current_paint():
    """The custom theme on screen (``base`` None when it is a built-in)."""
    return _paint


def background_settings(base, values, area):
    """(dim, blur, surface color, fit) of ``area``'s image under ``values``."""
    def effective(key):
        return values[key] if key in values else KEYS_BY_NAME[key].default(base)

    return (
        effective(f"{area}_image_dim"),
        effective(f"{area}_image_blur"),
        effective(IMAGE_SURFACES[area]),
        effective(f"{area}_image_fit"),
    )


def prepare_backgrounds(base, values, folder, on_ready=None):
    """The processed backgrounds of a theme that are ready now, by area.

    Each one not yet in the cache is rendered on a worker thread, and
    ``on_ready()`` runs on the main loop when it lands. Returns
    ``{area: {"path", "uri", "fit"}}``.
    """
    ready = {}
    if folder is None or _cache_dir is None:
        return ready
    for area in IMAGE_AREAS:
        name = values.get(f"{area}_image")
        source = Path(folder) / name if name else None
        if source is None or not source.is_file():
            continue
        dim, blur, surface, fit = background_settings(base, values, area)
        # The format stores the dim as a fraction; the renderer takes percent.
        dim = int(round(dim * 100))
        target = theme_images.processed_path(source, dim, blur, surface, _cache_dir)
        if target.is_file():
            ready[area] = {"path": target, "uri": target.as_uri(), "fit": fit}
            continue

        def work(source=source, dim=dim, blur=blur, surface=surface):
            done = theme_images.render(source, dim, blur, surface, _cache_dir)
            if done is not None and on_ready is not None:
                GLib.idle_add(_call_once, on_ready)

        _spawn(work)
    return ready


def _call_once(callback):
    callback()
    return GLib.SOURCE_REMOVE


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


def _stylesheet():
    return theme_css.stylesheet(
        _paint.values, css_variables=uses_css_variables(), base=_paint.base,
        backgrounds=_paint.backgrounds,
    )


def paint(base, values, folder=None):
    """Paint ``values`` over ``base`` (light or dark) right now."""
    global _paint, _generation
    _generation += 1
    generation = _generation
    values = dict(values)

    def landed():
        # A background finished: paint again, unless something newer did.
        if generation == _generation:
            _paint.backgrounds = prepare_backgrounds(base, values, folder)
            _refresh()

    _paint = Paint(base, values, folder,
                   prepare_backgrounds(base, values, folder, on_ready=landed))
    Adw.StyleManager.get_default().set_color_scheme(_COLOR_SCHEMES[base])
    _refresh()


def _refresh():
    if not _suspended:
        _load_css(_stylesheet())
    _notify()


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
        _applied = (theme, custom.base, dict(custom.values), custom.folder)
        paint(custom.base, custom.values, custom.folder)
        return theme
    _applied = (theme, None, {}, None)
    _paint_builtin(theme)
    return theme


def _paint_builtin(theme):
    global _paint, _generation
    _generation += 1
    _paint = Paint()
    scheme = _COLOR_SCHEMES.get(theme, Adw.ColorScheme.DEFAULT)
    Adw.StyleManager.get_default().set_color_scheme(scheme)
    if _provider is not None:
        _load_css("")
    _notify()


def restore():
    """Put back what the last ``apply_theme`` painted (after a live preview)."""
    theme, base, values, folder = _applied
    if base is None:
        _paint_builtin(theme)
    else:
        paint(base, values, folder)


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
    if _paint.base is not None:
        _load_css(_stylesheet())


def applied_theme():
    """The id ``apply_theme`` last put on screen."""
    return _applied[0]


def is_dark():
    """Whether the interface is being painted dark *right now*.

    Not the same question as the stored setting: under ``system`` the answer
    is the desktop's, and it can change while the app is open.
    """
    return bool(Adw.StyleManager.get_default().get_dark())
