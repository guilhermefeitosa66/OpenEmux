"""Routes gamepad actions into GTK focus movement and window commands.

The decision half is pure (``resolve``: context x action -> command) so it can
be unit tested without a display; ``NavigationController`` executes the
commands against the live widget tree and keeps the bottom-bar hints in step
with where the user is and what device they last touched.

Keyboard navigation itself is GTK's native keynav (arrows/Tab/Enter work once
the cards are focusable); the controller only listens to key presses to switch
the hints to their keyboard variant.
"""

import logging

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Gdk, GLib

logger = logging.getLogger(__name__)

# Focus contexts, from the innermost scope out.
CTX_POPOVER = "popover"
CTX_DIALOG = "dialog"
CTX_GRID = "grid"
CTX_SIDEBAR = "sidebar"
CTX_OTHER = "other"

# Input sources for the hint bar.
SOURCE_GAMEPAD = "gamepad"
SOURCE_KEYBOARD = "keyboard"
SOURCE_MOUSE = "mouse"

_DIRECTIONS = {"up", "down", "left", "right"}

_GTK_DIRECTIONS = {
    "up": Gtk.DirectionType.UP,
    "down": Gtk.DirectionType.DOWN,
    "left": Gtk.DirectionType.LEFT,
    "right": Gtk.DirectionType.RIGHT,
}

#: Keys that mean the user is steering with the keyboard (for hint switching).
_KEYNAV_KEYVALS = {
    Gdk.KEY_Up, Gdk.KEY_Down, Gdk.KEY_Left, Gdk.KEY_Right,
    Gdk.KEY_Tab, Gdk.KEY_ISO_Left_Tab, Gdk.KEY_Return, Gdk.KEY_KP_Enter,
    Gdk.KEY_Escape, Gdk.KEY_space, Gdk.KEY_Menu, Gdk.KEY_F6,
}


def resolve(context, action):
    """Map a (focus context, nav action) pair to an executable command.

    Commands are plain tuples so this stays testable without GTK:
      ("move", direction)        directional focus within the current scope
      ("move-or-sidebar",)       move left; at the grid's edge go to sidebar
      ("activate",)              activate the focused widget
      ("close-popover",)         dismiss the open popover
      ("close-dialog",)          close the open dialog (fires close response)
      ("focus-sidebar",)         move focus to the console list
      ("focus-grid",)            move focus into the game grid
      ("context-menu",)          open the focused card's context menu
      ("favorite",)              toggle favourite on the focused card
      ("console-delta", n)       select previous/next console (wraps)
      ("close-search",)          leave search mode if it is open
      ("noop",)                  nothing sensible in this context
    """
    if context == CTX_POPOVER:
        if action in _DIRECTIONS:
            return ("move", action)
        if action == "confirm":
            return ("activate",)
        if action in ("back", "context"):
            return ("close-popover",)
        return ("noop",)

    if context == CTX_DIALOG:
        if action in _DIRECTIONS:
            return ("move", action)
        if action == "confirm":
            return ("activate",)
        if action == "back":
            return ("close-dialog",)
        return ("noop",)

    # Main window: console switching works from anywhere.
    if action == "prev_console":
        return ("console-delta", -1)
    if action == "next_console":
        return ("console-delta", 1)

    if context == CTX_GRID:
        if action == "left":
            return ("move-or-sidebar",)
        if action in _DIRECTIONS:
            return ("move", action)
        if action == "confirm":
            return ("activate",)
        if action == "back":
            return ("focus-sidebar",)
        if action == "context":
            return ("context-menu",)
        if action == "favorite":
            return ("favorite",)
        return ("noop",)

    if context == CTX_SIDEBAR:
        if action in ("right", "confirm"):
            return ("focus-grid",)
        if action in _DIRECTIONS:
            return ("move", action)
        if action == "back":
            return ("close-search",)
        return ("noop",)

    # Focus is elsewhere (header buttons, search entry, nothing).
    if action in _DIRECTIONS:
        return ("move", action)
    if action == "confirm":
        return ("activate",)
    if action == "back":
        return ("focus-sidebar",)
    return ("noop",)


def pane_key_command(context, keyval, shift=False):
    """Which pane a key crosses to, or None to leave the key to GTK.

    Only the crossings are claimed. Everything else -- including the arrows
    that move within a pane -- stays with GTK's keynav.

    Right out of the sidebar has to be claimed because GTK would otherwise walk
    into the header-bar buttons rather than into the games.
    """
    # Shift+Tab is deliberately not claimed: it stays the way out to the rest
    # of the window, so the header bar and menu remain keyboard-reachable.
    forward_tab = keyval in (Gdk.KEY_Tab, Gdk.KEY_KP_Tab) and not shift

    if context == CTX_SIDEBAR:
        if keyval in (Gdk.KEY_Right, Gdk.KEY_KP_Right) or forward_tab:
            return "focus-grid"
        return None

    if context == CTX_GRID:
        if keyval == Gdk.KEY_BackSpace or forward_tab:
            return "focus-sidebar"
        return None

    return None


class NavigationController:
    """Executes navigation commands and owns the bottom-bar hint state."""

    def __init__(self, window):
        self.window = window
        self.gamepad_connected = False
        self._source = SOURCE_MOUSE
        self._hint_state = None
        # Gtk.Popover.popup() animates, so focus has not reached the menu by the
        # time the next button press arrives. Tracking the popover we opened
        # keeps the routing correct in that window.
        self._tracked_popover = None

        # Capture phase: the pane keys have to be claimed before GTK's own
        # keynav sees them, otherwise Right out of the sidebar lands on the
        # header-bar buttons instead of the game grid.
        key_watch = Gtk.EventControllerKey()
        key_watch.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        key_watch.connect("key-pressed", self._on_key_watch)
        window.add_controller(key_watch)

        # A *click*, not pointer motion: moving the focus scrolls the grid under
        # a stationary pointer, and the motion events that produces used to flip
        # the source back to mouse, hiding the hints and resizing the bar — which
        # reflowed the grid and fed the loop again. Clicks are intentional.
        click_watch = Gtk.GestureClick()
        click_watch.set_button(0)
        click_watch.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        click_watch.connect("pressed", self._on_click_watch)
        window.add_controller(click_watch)

        # Context changes without input (page loads, dialogs opening) refresh
        # the hints lazily on the next focus change.
        window.connect("notify::focus-widget", lambda *_a: self.refresh_hints())

    # ----- input-source tracking ------------------------------------------

    def _on_key_watch(self, _controller, keyval, _keycode, state):
        if keyval in _KEYNAV_KEYVALS:
            self._set_source(SOURCE_KEYBOARD)
        return self.handle_pane_key(keyval, state)

    def handle_pane_key(self, keyval, state):
        """Move between the sidebar and the grid. True when the key is claimed.

        Only these crossings are intercepted; everything else is left to GTK's
        keynav, which still moves within a pane. Right out of the sidebar would
        otherwise walk into the header-bar buttons rather than the games.
        """
        if self._active_popover() is not None:
            return False
        focus = self._focus_widget()
        # Never steal keys from a text field: Backspace and Tab belong to it.
        if isinstance(focus, (Gtk.Editable, Gtk.Text)):
            return False

        command = pane_key_command(
            self.current_context(), keyval, bool(state & Gdk.ModifierType.SHIFT_MASK)
        )
        if command is None:
            return False
        getattr(self, "_cmd_" + command.replace("-", "_"))()
        self.refresh_hints()
        return True

    def _on_click_watch(self, _gesture, _n_press, _x, _y):
        self._set_source(SOURCE_MOUSE)

    def _set_source(self, source):
        if self._source != source:
            self._source = source
            self.refresh_hints()

    # ----- gamepad plumbing (called via GLib.idle_add from the reader) ----

    def on_gamepad_action(self, action):
        self._set_source(SOURCE_GAMEPAD)
        self.dispatch(action)
        return False

    def on_gamepad_connected(self, name):
        self.gamepad_connected = True
        self.window._toast(self.window.t("toast.gamepad.connected", name=name))
        self.refresh_hints()
        return False

    def on_gamepad_disconnected(self):
        self.gamepad_connected = False
        if self._source == SOURCE_GAMEPAD:
            self._source = SOURCE_MOUSE
        self.window._toast(self.window.t("toast.gamepad.disconnected"))
        self.refresh_hints()
        return False

    # ----- context resolution ---------------------------------------------

    def _focus_widget(self):
        return self.window.get_focus()

    def _scope_for(self, widget):
        """Innermost popover or dialog holding ``widget``, else None."""
        node = widget
        while node is not None and node is not self.window:
            if isinstance(node, Gtk.Popover):
                return node
            if isinstance(node, Adw.Dialog):
                return node
            node = node.get_parent()
        return None

    def _active_popover(self):
        """The popover the user is in, whether or not focus has landed yet."""
        scope = self._scope_for(self._focus_widget())
        if isinstance(scope, Gtk.Popover):
            return scope
        tracked = self._tracked_popover
        if tracked is not None and tracked.get_mapped():
            return tracked
        self._tracked_popover = None
        return None

    def current_context(self):
        focus = self._focus_widget()
        scope = self._scope_for(focus)
        if isinstance(scope, Adw.Dialog):
            return CTX_DIALOG
        if self._active_popover() is not None:
            return CTX_POPOVER
        node = focus
        while node is not None and node is not self.window:
            if node is getattr(self.window, "console_list", None):
                return CTX_SIDEBAR
            if node is self._current_grid():
                return CTX_GRID
            node = node.get_parent()
        return CTX_OTHER

    def _current_grid(self):
        # The controller exists before the first refresh_library() populates
        # _grids, and a focus notify can arrive in that window.
        grids = getattr(self.window, "_grids", None) or {}
        return grids.get(self.window.current_console)

    # ----- dispatch --------------------------------------------------------

    def dispatch(self, action):
        context = self.current_context()
        command = resolve(context, action)
        logger.debug("nav dispatch: context=%s action=%s -> %s", context, action, command)
        handler = getattr(self, "_cmd_" + command[0].replace("-", "_"), None)
        if handler:
            handler(*command[1:])
        self.refresh_hints()

    def _cmd_noop(self):
        pass

    def _cmd_move(self, direction):
        focus = self._focus_widget()
        # Scope the move to the open menu/dialog so it cannot escape into the
        # window behind it.
        scope = self._active_popover() or self._scope_for(focus) or self.window
        if focus is None and scope is self.window:
            self._cmd_focus_grid()
            return
        scope.child_focus(_GTK_DIRECTIONS[direction])

    def _cmd_move_or_sidebar(self):
        focus = self._focus_widget()
        if focus is None or not self.window.child_focus(Gtk.DirectionType.LEFT):
            self._cmd_focus_sidebar()

    def _cmd_activate(self):
        focus = self._focus_widget()
        if focus is None:
            return
        if focus.activate():
            return
        # The focused widget may not be activatable (a plain box inside a card)
        # while the game it belongs to is: launch that instead of doing nothing.
        item = self.window._focused_rom_item()
        if item is not None and item.on_launch_callback:
            item.on_launch_callback(item.rom)

    def _cmd_close_popover(self):
        popover = self._active_popover()
        if popover is not None:
            popover.popdown()
            self._tracked_popover = None

    def _cmd_close_dialog(self):
        scope = self._scope_for(self._focus_widget())
        if isinstance(scope, Adw.Dialog):
            scope.close()

    def _cmd_focus_sidebar(self):
        window = self.window
        if window.split_view.get_collapsed():
            window.split_view.set_show_content(False)
        row = window.console_list.get_selected_row() or window.console_list.get_row_at_index(0)
        if row is not None:
            row.grab_focus()

    def _cmd_focus_grid(self):
        window = self.window
        if window.split_view.get_collapsed():
            window.split_view.set_show_content(True)
        grid = self._current_grid()
        if grid is not None:
            grid.focus_restore()

    def _cmd_context_menu(self):
        item = self.window._focused_rom_item()
        if item is None:
            return
        item._show_context_menu()
        popover = item._context_popover
        self._tracked_popover = popover
        if popover is not None:
            # Put focus on the first entry right away: without it the menu opens
            # with nothing highlighted and the first D-pad press is spent just
            # entering the list.
            popover.child_focus(Gtk.DirectionType.TAB_FORWARD)

    def _cmd_favorite(self):
        item = self.window._focused_rom_item()
        if item is not None:
            item._act_toggle_favorite(None, None)

    def _cmd_close_search(self):
        window = self.window
        if window.search_bar.get_search_mode():
            window.search_button.set_active(False)

    def _cmd_console_delta(self, delta):
        window = self.window
        rows = []
        row = window.console_list.get_first_child()
        while row is not None:
            rows.append(row)
            row = row.get_next_sibling()
        if not rows:
            return
        selected = window.console_list.get_selected_row()
        index = rows.index(selected) if selected in rows else 0
        target = rows[(index + delta) % len(rows)]
        was_in_grid = self.current_context() == CTX_GRID
        window.console_list.select_row(target)
        if was_in_grid:
            # The page was just (re)rendered; focus its grid on the next tick.
            GLib.idle_add(self._cmd_focus_grid)

    # ----- hint bar --------------------------------------------------------

    def toggle_pane_focus(self):
        """F6: cycle focus between the sidebar and the grid."""
        if self.current_context() == CTX_SIDEBAR:
            self._cmd_focus_grid()
        else:
            self._cmd_focus_sidebar()
        self.refresh_hints()

    def escape_to_sidebar(self):
        """Escape in the grid steps back to the sidebar. True when handled."""
        if self.current_context() != CTX_GRID:
            return False
        self._cmd_focus_sidebar()
        self.refresh_hints()
        return True

    def refresh_hints(self):
        window = self.window
        if not hasattr(window, "set_hints"):
            return
        source = self._source
        if source == SOURCE_GAMEPAD and not self.gamepad_connected:
            source = SOURCE_MOUSE
        if source == SOURCE_MOUSE:
            state = ("hidden",)
            if state != self._hint_state:
                self._hint_state = state
                window.set_hints([])
            return

        context = self.current_context()
        state = (source, context)
        if state == self._hint_state:
            return
        self._hint_state = state
        t = window.t

        if source == SOURCE_GAMEPAD:
            if context in (CTX_DIALOG, CTX_POPOVER):
                hints = [("Ⓐ", t("hints.confirm")), ("Ⓑ", t("hints.close"))]
            elif context == CTX_SIDEBAR:
                hints = [
                    ("Ⓐ", t("hints.enter_pane")),
                    ("↕", t("hints.navigate")),
                    ("L1/R1", t("hints.console_switch")),
                ]
            else:
                hints = [
                    ("Ⓐ", t("hints.open")),
                    ("Ⓑ", t("hints.back")),
                    ("Ⓧ", t("hints.options")),
                    ("Ⓨ", t("hints.favorite")),
                    ("L1/R1", t("hints.console_switch")),
                ]
        else:  # keyboard
            if context in (CTX_DIALOG, CTX_POPOVER):
                hints = [("Enter", t("hints.confirm")), ("Esc", t("hints.close"))]
            elif context == CTX_SIDEBAR:
                hints = [
                    ("↕", t("hints.navigate")),
                    ("→", t("hints.enter_pane")),
                    ("Tab", t("hints.switch_pane")),
                ]
            else:
                hints = [
                    ("Enter", t("hints.open")),
                    ("Esc", t("hints.back")),
                    ("Menu", t("hints.options")),
                    ("Ctrl+D", t("hints.favorite")),
                    ("Tab", t("hints.switch_pane")),
                ]
        window.set_hints(hints)
