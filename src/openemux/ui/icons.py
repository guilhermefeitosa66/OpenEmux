"""Bundled fallback for the symbolic icons the UI references by name.

The interface asks GTK for themed icons (``folder-symbolic``,
``applications-games-symbolic``, ...), which normally resolve through the icon
theme installed on the host. Icon themes that do not inherit Adwaita (Mint-Y,
Papirus, Breeze, ...) and adwaita-icon-theme releases that dropped legacy
names leave those lookups empty, so users see blank buttons and menu entries.

``assets/icons/symbolic/`` vendors an SVG for every symbolic name the app
uses (``tests/test_icon_assets.py`` keeps the set complete). Registering that
directory as an icon search path makes GTK pick them up as unthemed fallback
icons: the host theme still wins whenever it does ship a name, the bundled
copy only fills the gaps.
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

SYMBOLIC_ICON_DIR = Path(__file__).resolve().parent / "assets" / "icons" / "symbolic"

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

    Gtk.IconTheme.get_for_display(display).add_search_path(str(SYMBOLIC_ICON_DIR))
    _registered = True
    logger.debug("registered bundled symbolic icons from %s", SYMBOLIC_ICON_DIR)
