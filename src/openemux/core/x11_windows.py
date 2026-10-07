"""Find RetroArch's X11 window and set its title (issue #469).

OpenEmux no longer captures RetroArch's window -- the game's controls are a
RetroArch overlay now (``overlay_bar``) -- but RetroArch's own window is what
the user plays in, and RetroArch titles it with the core's version hash.
``window_title`` uses this to find the window a launch opened and name the
game on it instead.

X11 only, and best-effort throughout: every method swallows the X errors a
window vanishing mid-call raises, because a title is never worth failing a
game over.
"""

import importlib.util
import logging

logger = logging.getLogger(__name__)

try:
    # Xlib.display is located rather than imported. It drags the protocol and
    # socket machinery along with it -- 9 ms of the 10.5 this block used to
    # cost -- and it is touched in exactly one place, _dpy(), on the launches
    # that actually retitle a window. Xatom is cheap and stays eager (issue
    # #364). Finding Xlib.display proves it is installed, which is the whole
    # of what XLIB_AVAILABLE claims.
    from Xlib import Xatom

    XLIB_AVAILABLE = importlib.util.find_spec("Xlib.display") is not None
except ImportError:  # pragma: no cover - exercised only without python-xlib
    XLIB_AVAILABLE = False

#: WM_CLASS values that identify a RetroArch window, lowercased.
RETROARCH_WM_CLASSES = {"retroarch"}


class RetroArchWindows:
    """The X display, as far as RetroArch's toplevel windows are concerned."""

    def __init__(self):
        self._display = None
        # RetroArch windows already on screen before the launch; the
        # WM_CLASS fallback must never pick one of those.
        self._preexisting_xids = set()

    def _dpy(self):
        if not XLIB_AVAILABLE:
            return None
        if self._display is None:
            try:
                # See the import block at the top of the file: this is the one
                # place Xlib.display is reached for, and the first retitle of the
                # session is when it gets loaded.
                from Xlib import display as x11_display

                self._display = x11_display.Display()
            except Exception as exc:
                logger.warning("x11: cannot open X display: %s", exc)
                return None
        return self._display

    def close(self):
        if self._display is not None:
            try:
                self._display.close()
            except Exception:
                pass
            self._display = None

    # -- window discovery ---------------------------------------------------
    def _client_xids(self):
        dpy = self._dpy()
        if dpy is None:
            return []
        try:
            root = dpy.screen().root
            prop = root.get_full_property(
                dpy.intern_atom("_NET_CLIENT_LIST"), Xatom.WINDOW
            )
            return list(prop.value) if prop else []
        except Exception as exc:
            logger.warning("x11: reading _NET_CLIENT_LIST failed: %s", exc)
            return []

    def _window_pid(self, window):
        dpy = self._dpy()
        prop = window.get_full_property(
            dpy.intern_atom("_NET_WM_PID"), Xatom.CARDINAL
        )
        if prop and prop.value:
            return int(prop.value[0])
        return None

    @staticmethod
    def _is_retroarch_class(window):
        wm_class = window.get_wm_class()
        if not wm_class:
            return False
        return any((part or "").lower() in RETROARCH_WM_CLASSES for part in wm_class)

    def snapshot_existing(self):
        """Record RetroArch windows that predate the launch we care about."""
        dpy = self._dpy()
        if dpy is None:
            return
        for xid in self._client_xids():
            try:
                window = dpy.create_resource_object("window", xid)
                if self._is_retroarch_class(window):
                    self._preexisting_xids.add(xid)
            except Exception:
                continue

    def find_game_window(self, pid):
        """The freshly launched RetroArch toplevel's XID, or ``None``.

        A ``_NET_WM_PID`` match wins. The WM_CLASS fallback covers launch
        paths where the Popen PID is not the window's process (AppImage
        wrappers that fork, flatpak-spawn), restricted to windows that were
        not on screen before the launch.
        """
        dpy = self._dpy()
        if dpy is None:
            return None
        class_fallback = None
        for xid in self._client_xids():
            try:
                window = dpy.create_resource_object("window", xid)
                if pid is not None and self._window_pid(window) == int(pid):
                    return xid
                if (
                    class_fallback is None
                    and xid not in self._preexisting_xids
                    and self._is_retroarch_class(window)
                ):
                    class_fallback = xid
            except Exception:
                # The window can vanish between listing and inspecting it.
                continue
        return class_fallback

    # -- title ----------------------------------------------------------------
    def window_title(self, xid):
        """The window's ``_NET_WM_NAME``, or ``None`` when it cannot be read."""
        dpy = self._dpy()
        if dpy is None:
            return None
        try:
            window = dpy.create_resource_object("window", xid)
            prop = window.get_full_property(
                dpy.intern_atom("_NET_WM_NAME"), dpy.intern_atom("UTF8_STRING")
            )
        except Exception:
            return None
        if not prop or prop.value is None:
            return None
        value = prop.value
        return value.decode("utf-8", "replace") if isinstance(value, bytes) else str(value)

    def set_window_title(self, xid, title):
        """Retitle a window: ``_NET_WM_NAME`` for the WM, ``WM_NAME`` for the rest."""
        dpy = self._dpy()
        if dpy is None:
            return False
        try:
            window = dpy.create_resource_object("window", xid)
            window.change_property(
                dpy.intern_atom("_NET_WM_NAME"),
                dpy.intern_atom("UTF8_STRING"),
                8,
                title.encode("utf-8"),
            )
            # The legacy property too, for tools that read it (``xdotool
            # search --name`` among them). Latin-1 is all it holds, and
            # RetroArch keeps writing its own back: a courtesy, not a promise.
            window.change_property(
                Xatom.WM_NAME, Xatom.STRING, 8, title.encode("latin-1", "replace")
            )
            dpy.flush()
        except Exception as exc:
            logger.debug("retitle failed: %s", exc)
            return False
        return True
