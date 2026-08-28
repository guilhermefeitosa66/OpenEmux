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

import importlib.util
import logging

logger = logging.getLogger(__name__)

try:
    # Xcursorfont is unused, and imported anyway: this block is the probe for
    # whether python-xlib is installed at all, and importing the whole set is
    # what makes XLIB_AVAILABLE mean "every module this file may reach for".
    #
    # Xlib.display is the one exception, located rather than imported. It drags
    # the protocol and socket machinery along with it -- 9 ms of the 10.5 this
    # block used to cost -- and it is touched in exactly one place, _dpy(), on
    # the launches that actually embed a window. The other four are 1.5 ms
    # together, so they stay eager and every call site below reads unchanged
    # (issue #364). Finding it proves it is installed, which is the whole of
    # what XLIB_AVAILABLE claims; importing it is deferred to the first embed.
    from Xlib import X, XK, Xatom, Xcursorfont  # noqa: F401

    XLIB_AVAILABLE = importlib.util.find_spec("Xlib.display") is not None
except ImportError:  # pragma: no cover - exercised only without python-xlib
    XLIB_AVAILABLE = False

#: WM_CLASS values that identify a RetroArch window, lowercased.
RETROARCH_WM_CLASSES = {"retroarch"}

#: RetroArch's own key vocabulary translated back into X keysym names.
#:
#: Input profiles store bindings the way RetroArch writes them, and X does not
#: know most of those words: ``string_to_keysym`` answers NoSymbol for
#: ``enter``, ``num1``, ``pageup``, ``kp_plus``, ``backquote``, ``del`` and
#: ``rshift``, all of which a user can legitimately have bound. This is the
#: inverse of ``input_actions.RETROARCH_KEY_NAMES``, with the X spelling
#: chosen where several map onto one token (issue #236).
X_KEYSYM_NAMES = {
    # Top-row digits -- RetroArch files these under num*, and the keypad ones
    # under keypad*.
    **{f"num{digit}": str(digit) for digit in range(10)},
    **{f"keypad{digit}": f"KP_{digit}" for digit in range(10)},
    "equals": "equal",
    "kp_equals": "KP_Equal",
    "kp_plus": "KP_Add",
    "kp_minus": "KP_Subtract",
    "kp_period": "KP_Decimal",
    "kp_enter": "KP_Enter",
    "pageup": "Prior",
    "pagedown": "Next",
    "del": "Delete",
    "enter": "Return",
    "backquote": "grave",
    "leftbracket": "bracketleft",
    "rightbracket": "bracketright",
    "quote": "apostrophe",
    "capslock": "Caps_Lock",
    "numlock": "Num_Lock",
    "scrolllock": "Scroll_Lock",
    "print_screen": "Print",
    # Modifiers: RetroArch names the left-hand one bare and prefixes the right.
    "shift": "Shift_L",
    "rshift": "Shift_R",
    "ctrl": "Control_L",
    "rctrl": "Control_R",
    "alt": "Alt_L",
    "ralt": "Alt_R",
    "lsuper": "Super_L",
    "rsuper": "Super_R",
    "lmeta": "Meta_L",
    "rmeta": "Meta_R",
}


def _keysym_candidates(key_name):
    """The X keysym names to try for a stored binding, best first."""
    name = str(key_name or "").strip()
    if not name:
        return []
    mapped = X_KEYSYM_NAMES.get(name.lower())
    candidates = [mapped] if mapped else []
    candidates.append(name)
    # Binding names are lowercase ("f11"); keysym names for function keys are
    # capitalized ("F11"). Same keycode.
    candidates.append(name.upper())
    seen = set()
    return [c for c in candidates if not (c in seen or seen.add(c))]


#: The glyph the embedded game window's pointer is defined to (XC_left_ptr).
#: RetroArch defines an invisible cursor on its own window, and X resolves the
#: pointer from the *innermost* window under it, so the child's cursor wins
#: over anything GTK sets on the wrapper (issue #276).
CURSOR_GLYPH = 68


class RetroArchWindowEmbedder:
    """Finds the RetroArch X11 window and re-parents it under ours."""

    def __init__(self):
        self._display = None
        # Logged once per embedder; the reclaim tick runs five times a second.
        self._warned_no_active_window = False
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
                # See the import block at the top of the file: this is the one
                # place Xlib.display is reached for, and the first embed of the
                # session is when it gets loaded.
                from Xlib import display as x11_display

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
            active_xid = int(active.value[0]) if active and active.value else None
            focus = dpy.get_input_focus().focus
            focus_xid = focus if isinstance(focus, int) else focus.id
            if not self.should_reclaim_focus(active_xid, focus_xid, child_xid, toplevel_xid):
                return False
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

    def should_reclaim_focus(self, active_xid, focus_xid, child_xid, toplevel_xid):
        """Whether the reclaim tick may take X focus back for the game.

        ``_NET_ACTIVE_WINDOW`` is the honest answer -- it is the window
        manager saying which toplevel the user is on -- but not every
        (XWayland) window manager keeps it current, and the old code read a
        missing property as "not us" and silently did nothing. On such a
        session the reclaim loop never fired at all and RetroArch went
        input-dead after any click on the wrapper chrome, with nothing in the
        log to point at it (issue #236).

        So when the property is absent, X's own input focus decides: if it
        already sits on our toplevel or on the game, the user is on us and the
        reclaim is safe. Focus anywhere else still means hands off -- stealing
        it from another application would be far worse than a missed tick.
        """
        if active_xid is not None:
            return active_xid == int(toplevel_xid)
        self._warn_missing_active_window()
        return focus_xid in (int(toplevel_xid), int(child_xid))

    def _warn_missing_active_window(self):
        """Say it once. A 200 ms tick would otherwise fill the log."""
        if self._warned_no_active_window:
            return
        self._warned_no_active_window = True
        logger.warning(
            "embed: the window manager does not publish _NET_ACTIVE_WINDOW; "
            "falling back to the X input focus to decide when to reclaim it"
        )

    # -- wrapper hotkeys ----------------------------------------------------
    def grab_key(self, toplevel_xid, key_name, fallback_key_name=None):
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
            keycode = self._keycode_for(dpy, key_name)
            if not keycode and fallback_key_name:
                # A binding X cannot name is not a reason to have no
                # fullscreen key at all: RetroArch's own toggle is unbound
                # while embedded, so this grab is the only one there is.
                logger.warning(
                    "embed: no keycode for hotkey %r; falling back to %r",
                    key_name,
                    fallback_key_name,
                )
                keycode = self._keycode_for(dpy, fallback_key_name)
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

    @staticmethod
    def _keycode_for(dpy, key_name):
        """The keycode for a stored binding name, or 0.

        Bindings are stored in RetroArch's vocabulary, which is not X's:
        ``string_to_keysym`` answers NoSymbol for ``enter``, ``num1``,
        ``pageup``, ``kp_plus``, ``del``, ``rshift`` and every other token in
        :data:`X_KEYSYM_NAMES`. Passing those straight through is what left a
        user who rebound fullscreen to one of them with no fullscreen key at
        all (issue #236).
        """
        for candidate in _keysym_candidates(key_name):
            keysym = XK.string_to_keysym(candidate)
            if keysym == X.NoSymbol:
                continue
            keycode = dpy.keysym_to_keycode(keysym)
            if keycode:
                return keycode
        return 0

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
