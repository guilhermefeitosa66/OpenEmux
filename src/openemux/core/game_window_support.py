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

Two questions, not one (issue #267). ``embedding_possible`` answers "could
this session ever embed?" from the environment alone -- Preferences asks that
one, so the switch stays usable and can be turned on for the next restart.
``embedding_ready`` answers "will *this* launch embed?", which additionally
needs GTK's own verdict about the display it ended up on, and must be false
once an embed has already failed in this session. Only the second one may
gate the launcher's overrides: writing them without a wrapper to own the
window leaves the game floating borderless.
"""

import os

from openemux.core.x11_embed import XLIB_AVAILABLE

#: GTK's verdict about the display it actually opened, published by the
#: library window once the toolkit is up (``ui.game_window
#: .display_supports_embedding``). ``None`` until then -- the pre-GTK backend
#: pick in ``main.py`` runs while it is still unknown, and must not be
#: affected by it.
_display_embeddable = None

#: Why the embed gave up, latched for the rest of the session. Set once a
#: wrapper has actually failed (or was never attempted), so every later
#: launch goes standalone *with RetroArch's own decorations* instead of
#: repeating the failure and stranding another borderless window.
_embed_failed_reason = None


def set_display_embeddable(value):
    """Publish GTK's answer about the display this process opened."""
    global _display_embeddable
    _display_embeddable = None if value is None else bool(value)


def mark_embed_unavailable(reason):
    """Latch "no embed this session"; the first reason wins."""
    global _embed_failed_reason
    if not _embed_failed_reason:
        _embed_failed_reason = str(reason or "unknown")
    return _embed_failed_reason


def embed_unavailable_reason():
    """The latched reason, or ``None`` while the embed is still viable."""
    return _embed_failed_reason


def reset_embed_state():
    """Forget both answers. For tests -- the state is process-global."""
    global _display_embeddable, _embed_failed_reason
    _display_embeddable = None
    _embed_failed_reason = None


def embedding_possible():
    """True when this session could host an embed, judged from the env alone.

    The capability question, not the "will it happen now" one -- see
    ``embedding_ready``. Preferences uses this so the switch row stays
    sensitive on a session where the app merely started on the wrong backend.
    """
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
    if backend:
        names = [name.strip() for name in backend.split(",") if name.strip()]
        # GTK walks the list in order and takes the first backend that opens,
        # so only the *first* entry decides. "wayland,x11" used to pass this
        # check and then put GTK on Wayland, where nothing can be reparented
        # -- and the launcher had already written the embed overrides (#212).
        if not names or names[0] != "x11":
            return False
    return True


def embedding_ready():
    """True when *this* launch can embed: capability, display and no failure.

    ``embedding_possible`` is deliberately called by name rather than aliased
    so tests can patch it on this module.
    """
    if _embed_failed_reason:
        return False
    if _display_embeddable is False:
        return False
    return embedding_possible()


def game_window_active(config_manager):
    """The preference and the capability together: is this launch embedded?

    Every caller must ask this rather than the setting alone. The launcher's
    embed overrides strip RetroArch's decorations and unbind its fullscreen
    hotkey, which only makes sense while a wrapper is there to own the window
    -- writing them without one leaves the game floating borderless.
    """
    return bool(config_manager.get_game_window_enabled()) and embedding_ready()
