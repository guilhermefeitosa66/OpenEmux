"""Bundled fallback for the symbolic icons the UI references by name.

The interface asks GTK for themed icons (``folder-symbolic``,
``applications-games-symbolic``, ...), which normally resolve through the icon
theme installed on the host. Icon themes that do not inherit Adwaita (Mint-Y,
Papirus, Breeze, ...) and adwaita-icon-theme releases that dropped legacy
names leave those lookups empty, so users see blank buttons and menu entries.

``assets/icons/symbolic/`` vendors an SVG for every symbolic name the app
uses (``tests/test_icon_assets.py`` keeps the set complete). Registering that
directory as an icon search path adds them to the hicolor theme, the one every
theme falls back to: the host theme still wins whenever it does ship a name,
the bundled copy only fills the gaps.

The SVGs sit in ``hicolor/scalable/actions/`` rather than loose in the
directory. GTK 4.14 (Ubuntu 24.04's, the oldest this runs on) never marks a
loose ("unthemed") icon as symbolic, so it drew those in their literal dark
fill instead of the theme's foreground: invisible in the dark theme.
``openemux-share-symbolic``, the one name no theme ships, was where it showed
(issue #626). ``hicolor/index.theme`` stands in for the host's on a system with
no hicolor theme installed.
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

#: Share nearby's glyph: the three connected nodes the Android app draws. A
#: name of our own rather than a themed "send to" or "share" name, which icon
#: themes draw as anything from an arrow to a paper plane (issue #611).
SHARE_ICON = "openemux-share-symbolic"

#: The icon search path: a base directory holding the ``hicolor`` theme.
ICON_SEARCH_DIR = Path(__file__).resolve().parent / "assets" / "icons" / "symbolic"

#: Where the SVGs themselves are.
SYMBOLIC_ICON_DIR = ICON_SEARCH_DIR / "hicolor" / "scalable" / "actions"

_registered = False


def register_bundled_icons():
    """Add the vendored symbolic icons to the default display's icon theme.

    Call once GTK is initialized, before the first window is built. Safe to
    call repeatedly; only the first call with a display does anything.
    """
    global _registered
    if _registered:
        return

    from gi.repository import Gdk, Gtk

    display = Gdk.Display.get_default()
    if display is None:
        return
    if not SYMBOLIC_ICON_DIR.is_dir():
        logger.warning("bundled symbolic icons missing at %s", SYMBOLIC_ICON_DIR)
        return

    Gtk.IconTheme.get_for_display(display).add_search_path(str(ICON_SEARCH_DIR))
    _registered = True
    logger.debug("registered bundled symbolic icons from %s", ICON_SEARCH_DIR)
