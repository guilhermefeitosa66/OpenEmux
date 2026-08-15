"""Whether the game window can host RetroArch, answered without GTK.

The game window adopts RetroArch's own window with ``XReparentWindow`` (see
``openemux.core.x11_embed``), so it only exists where three things hold:
python-xlib is installed, an X display is reachable, and this process speaks
X11 rather than Wayland. Three places need that answer and must agree on it --
``main.py`` picks the GDK backend before GTK is imported, the launcher writes
RetroArch's window overrides, and the library window decides whether to open a
wrapper -- which is why it lives here, in a module that imports no GTK.

Whether the user *wants* it is a separate question, stored as
``runtime.game_window`` and read through ``ConfigManager``.
``game_window_active`` is the two together.
"""

import os

from openemux.core.x11_embed import XLIB_AVAILABLE


def embedding_possible():
    """True when this process can reparent an X11 window into its own."""
    if not XLIB_AVAILABLE:
        return False
    if not (os.environ.get("DISPLAY") or "").strip():
        # No X server to talk to: a Wayland session without XWayland, or the
        # Flatpak sandbox on Wayland, where --socket=fallback-x11 hands out no
        # X socket at all. Checked before anything forces GDK_BACKEND=x11 --
        # doing that here would leave GTK with no display and the app would
        # not start.
        return False
    backend = (os.environ.get("GDK_BACKEND") or "").strip().lower()
    if backend and "x11" not in [name.strip() for name in backend.split(",")]:
        # A backend chosen by hand, and not X11: that choice wins, and a
        # wrapper on a Wayland surface could not reparent anything anyway.
        return False
    return True


def game_window_active(config_manager):
    """The preference and the capability together: is this launch embedded?

    Every caller must ask this rather than the setting alone. The launcher's
    embed overrides strip RetroArch's decorations and unbind its fullscreen
    hotkey, which only makes sense while a wrapper is there to own the window
    -- writing them without one leaves the game floating borderless.
    """
    return bool(config_manager.get_game_window_enabled()) and embedding_possible()
