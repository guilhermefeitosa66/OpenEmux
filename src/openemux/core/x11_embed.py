"""Reparent a running RetroArch's X11 window into an OpenEmux window (POC).

X11 only (an XWayland RetroArch also qualifies -- what matters is that
*both* windows are X clients, which is why ``main.py`` forces
``GDK_BACKEND=x11`` while the embed flag is on). The mechanism is plain
``XReparentWindow``: once RetroArch's toplevel becomes a child of the
OpenEmux window it leaves window-manager control, so its titlebar and
borders disappear and OpenEmux decides its position and size.

Every method is best-effort and never raises to the UI: a lost race with a
closing window costs the embed, not the app.
"""

import logging

logger = logging.getLogger(__name__)

try:
    from Xlib import X, XK, Xatom, Xcursorfont
    from Xlib import display as x11_display

    XLIB_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only without python-xlib
    XLIB_AVAILABLE = False

#: WM_CLASS values that identify a RetroArch window, lowercased.
RETROARCH_WM_CLASSES = {"retroarch"}

#: The glyph the embedded game window's pointer is defined to (XC_left_ptr).
#: RetroArch defines an invisible cursor on its own window, and X resolves the
#: pointer from the *innermost* window under it, so the child's cursor wins
#: over anything GTK sets on the wrapper (issue #276).
CURSOR_GLYPH = 68


class RetroArchWindowEmbedder:
    """Finds the RetroArch X11 window and re-parents it under ours."""

    def __init__(self):
        self._display = None
        # RetroArch windows already on screen before the launch; the
        # WM_CLASS fallback must never grab one of those.
        self._preexisting_xids = set()
        # The left_ptr cursor resource, created lazily and reused: it belongs
        # to the display, so it dies with it.
        self._cursor = None

    @property
    def available(self):
        return XLIB_AVAILABLE

    def _dpy(self):
        if not XLIB_AVAILABLE:
            return None
        if self._display is None:
            try:
                self._display = x11_display.Display()
            except Exception as exc:
                logger.warning("embed: cannot open X display: %s", exc)
                return None
        return self._display

    def close(self):
        if self._display is not None:
            try:
                self._display.close()
            except Exception:
                pass
            self._display = None
        self._cursor = None

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
            logger.warning("embed: reading _NET_CLIENT_LIST failed: %s", exc)
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

    # -- pointer ------------------------------------------------------------
    def _pointer_cursor(self, dpy):
        """The shared left_ptr cursor, created once per display."""
        if self._cursor is not None:
            return self._cursor
        try:
            font = dpy.open_font("cursor")
            if font is None:
                return None
            # The standard X idiom: the cursor font is its own mask, and the
            # mask glyph is the source glyph plus one.
            self._cursor = font.create_glyph_cursor(
                font,
                CURSOR_GLYPH,
                CURSOR_GLYPH + 1,
                (0, 0, 0),
                (65535, 65535, 65535),
            )
        except Exception as exc:
            logger.warning("embed: cannot create a pointer cursor: %s", exc)
            return None
        return self._cursor

    def set_child_cursor(self, child_xid):
        """Give the embedded game window a visible pointer.

        RetroArch defines an invisible cursor on its own window and only
        redefines it on a menu toggle, a video re-init or a focus transition.
        A screen lock breaks that transition -- the locker grabs the pointer
        without updating ``_NET_ACTIVE_WINDOW``, so the wrapper and the locker
        fight over X focus -- and RetroArch can come back with the cursor
        still hidden. Since the game window is now *our* X child, the wrapper
        can define the pointer on it and stop depending on RetroArch for it
        (issue #276).
        """
        dpy = self._dpy()
        if dpy is None:
            return False
        cursor = self._pointer_cursor(dpy)
        if cursor is None:
            return False
        try:
            child = dpy.create_resource_object("window", child_xid)
            child.change_attributes(cursor=cursor)
            dpy.sync()
            return True
        except Exception as exc:
            logger.warning("embed: cannot set the game window cursor: %s", exc)
            return False

    # -- embedding ----------------------------------------------------------
    def embed(self, child_xid, parent_xid, x, y, width, height):
        """Reparent ``child_xid`` under ``parent_xid`` at the given rect."""
        dpy = self._dpy()
        if dpy is None:
            return False
        try:
            child = dpy.create_resource_object("window", child_xid)
            parent = dpy.create_resource_object("window", parent_xid)
            child.reparent(parent, int(x), int(y))
            child.configure(
                x=int(x), y=int(y), width=max(1, int(width)), height=max(1, int(height))
            )
            child.map()
            dpy.sync()
        except Exception as exc:
            logger.warning("embed: reparent failed: %s", exc)
            return False
        # Every adoption, the re-adoptions after a drift included: a re-map
        # keeps whatever cursor the child carried.
        self.set_child_cursor(child_xid)
        return True

    def is_child_of(self, child_xid, parent_xid):
        """Is the game window still re-parented under ours? Tri-state.

        ``True``/``False``, or ``None`` when the question cannot be answered
        -- no display, or the window is gone. The distinction matters: a
        BadWindow means the game's window was destroyed, which is the game
        ending, not the embed drifting. Treating "unknown" as "drifted" would
        re-parent and steal X focus once a second for the rest of the
        session (issue #267).
        """
        dpy = self._dpy()
        if dpy is None:
            return None
        try:
            child = dpy.create_resource_object("window", child_xid)
            return int(child.query_tree().parent.id) == int(parent_xid)
        except Exception as exc:
            logger.debug("embed: cannot read the game window's parent: %s", exc)
            return None

    def move_resize(self, child_xid, x, y, width, height):
        dpy = self._dpy()
        if dpy is None:
            return False
        try:
            child = dpy.create_resource_object("window", child_xid)
            child.configure(
                x=int(x), y=int(y), width=max(1, int(width)), height=max(1, int(height))
            )
            dpy.sync()
            return True
        except Exception as exc:
            logger.warning("embed: move/resize failed: %s", exc)
            return False

    def focus(self, child_xid):
        """Hand X keyboard focus to the game so RetroArch sees key input."""
        dpy = self._dpy()
        if dpy is None:
            return False
        try:
            child = dpy.create_resource_object("window", child_xid)
            dpy.set_input_focus(child, X.RevertToParent, X.CurrentTime)
            dpy.sync()
            return True
        except Exception as exc:
            logger.warning("embed: focusing game window failed: %s", exc)
            return False

    def ensure_focus(self, child_xid, toplevel_xid):
        """Keep X keyboard focus on the game while our window is the active one.

        The window manager re-focuses the *toplevel* on every click and on
        activation, and an embedded child never gets focus back on its own.
        RetroArch gates keyboard -- and, through its focus check, gamepad --
        input on that focus, so this runs periodically to reclaim it. Only
        while the wrapper is the WM's active window: focus must never be
        stolen from another application or from our own dialogs.
        """
        dpy = self._dpy()
        if dpy is None:
            return False
        try:
            root = dpy.screen().root
            active = root.get_full_property(
                dpy.intern_atom("_NET_ACTIVE_WINDOW"), Xatom.WINDOW
            )
            if not active or not active.value or int(active.value[0]) != int(toplevel_xid):
                return False
            focus = dpy.get_input_focus().focus
            focus_xid = focus if isinstance(focus, int) else focus.id
            if focus_xid == child_xid:
                return True
            child = dpy.create_resource_object("window", child_xid)
            dpy.set_input_focus(child, X.RevertToParent, X.CurrentTime)
            dpy.sync()
        except Exception as exc:
            logger.warning("embed: ensure-focus failed: %s", exc)
            return False
        # Focus was elsewhere and just came back: an unlock, an Alt+Tab, a
        # click on another window. That is exactly when RetroArch may have
        # left its own cursor hidden, and the only branch that pays for it --
        # a tick that finds focus already on the game returns above.
        self.set_child_cursor(child_xid)
        return True

    # -- wrapper hotkeys ----------------------------------------------------
    def grab_key(self, toplevel_xid, key_name):
        """Passively grab one key on the wrapper toplevel; the keycode or None.

        Every normal key event goes to the game (X focus sits on the
        embedded child), so the only way the wrapper can see a hotkey of
        its own is a passive grab -- grabs on an ancestor fire even while
        focus is on a descendant, and they die with this display
        connection, so ``close()`` is also the ungrab.
        """
        dpy = self._dpy()
        if dpy is None:
            return None
        try:
            keysym = XK.string_to_keysym(key_name)
            if keysym == X.NoSymbol:
                # Binding names are lowercase ("f11"); keysym names for
                # function keys are capitalized ("F11"). Same keycode.
                keysym = XK.string_to_keysym(key_name.upper())
            keycode = dpy.keysym_to_keycode(keysym) if keysym != X.NoSymbol else 0
            if not keycode:
                logger.warning("embed: no keycode for hotkey %r", key_name)
                return None
            toplevel = dpy.create_resource_object("window", toplevel_xid)
            # Caps/Num lock must not disable the hotkey.
            for modifiers in (0, X.LockMask, X.Mod2Mask, X.LockMask | X.Mod2Mask):
                toplevel.grab_key(
                    keycode, modifiers, False, X.GrabModeAsync, X.GrabModeAsync
                )
            dpy.sync()
            return keycode
        except Exception as exc:
            logger.warning("embed: grabbing key %r failed: %s", key_name, exc)
            return None

    def pressed_grabbed_keycodes(self):
        """Keycodes of grabbed keys pressed since the last call."""
        dpy = self._dpy()
        if dpy is None:
            return []
        pressed = []
        try:
            while dpy.pending_events():
                event = dpy.next_event()
                if event.type == X.KeyPress:
                    pressed.append(event.detail)
        except Exception as exc:
            logger.warning("embed: reading grabbed keys failed: %s", exc)
        return pressed

    def release(self, child_xid):
        """Detach the game window before ours goes away.

        X destroys children along with their parent, and RetroArch reacts
        to its window dying under it with an X error abort instead of a
        clean quit. Unmapped first so the freed toplevel does not flash
        WM-decorated while QUIT is still in flight.
        """
        dpy = self._dpy()
        if dpy is None:
            return False
        try:
            child = dpy.create_resource_object("window", child_xid)
            child.unmap()
            child.reparent(dpy.screen().root, 0, 0)
            dpy.sync()
            return True
        except Exception as exc:
            logger.warning("embed: releasing game window failed: %s", exc)
            return False
