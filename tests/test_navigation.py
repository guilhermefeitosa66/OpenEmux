import unittest

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gdk

from openemux.ui.navigation import (
    CTX_DIALOG,
    CTX_GRID,
    CTX_OTHER,
    CTX_POPOVER,
    CTX_SIDEBAR,
    pane_key_command,
    resolve,
)


class ResolveTests(unittest.TestCase):
    """The pure context x action routing matrix behind the gamepad."""

    def test_popover(self):
        self.assertEqual(resolve(CTX_POPOVER, "up"), ("move", "up"))
        self.assertEqual(resolve(CTX_POPOVER, "confirm"), ("activate",))
        self.assertEqual(resolve(CTX_POPOVER, "back"), ("close-popover",))
        # X toggles the menu shut instead of opening a second one.
        self.assertEqual(resolve(CTX_POPOVER, "context"), ("close-popover",))
        self.assertEqual(resolve(CTX_POPOVER, "favorite"), ("noop",))
        self.assertEqual(resolve(CTX_POPOVER, "next_console"), ("noop",))

    def test_dialog(self):
        self.assertEqual(resolve(CTX_DIALOG, "left"), ("move", "left"))
        self.assertEqual(resolve(CTX_DIALOG, "confirm"), ("activate",))
        self.assertEqual(resolve(CTX_DIALOG, "back"), ("close-dialog",))
        # L1/R1 must not switch pages behind a modal.
        self.assertEqual(resolve(CTX_DIALOG, "prev_console"), ("noop",))
        self.assertEqual(resolve(CTX_DIALOG, "context"), ("noop",))

    def test_grid(self):
        self.assertEqual(resolve(CTX_GRID, "up"), ("move", "up"))
        self.assertEqual(resolve(CTX_GRID, "down"), ("move", "down"))
        self.assertEqual(resolve(CTX_GRID, "right"), ("move", "right"))
        # Left keeps moving until the edge, then crosses into the sidebar.
        self.assertEqual(resolve(CTX_GRID, "left"), ("move-or-sidebar",))
        self.assertEqual(resolve(CTX_GRID, "confirm"), ("activate",))
        self.assertEqual(resolve(CTX_GRID, "back"), ("focus-sidebar",))
        self.assertEqual(resolve(CTX_GRID, "context"), ("context-menu",))
        self.assertEqual(resolve(CTX_GRID, "favorite"), ("favorite",))

    def test_sidebar(self):
        self.assertEqual(resolve(CTX_SIDEBAR, "up"), ("move", "up"))
        self.assertEqual(resolve(CTX_SIDEBAR, "down"), ("move", "down"))
        # Both right and A step into the game list.
        self.assertEqual(resolve(CTX_SIDEBAR, "right"), ("focus-grid",))
        self.assertEqual(resolve(CTX_SIDEBAR, "confirm"), ("focus-grid",))
        self.assertEqual(resolve(CTX_SIDEBAR, "back"), ("close-search",))
        self.assertEqual(resolve(CTX_SIDEBAR, "context"), ("noop",))
        self.assertEqual(resolve(CTX_SIDEBAR, "favorite"), ("noop",))

    def test_console_switch_works_across_the_main_window(self):
        for context in (CTX_GRID, CTX_SIDEBAR, CTX_OTHER):
            self.assertEqual(resolve(context, "prev_console"), ("console-delta", -1))
            self.assertEqual(resolve(context, "next_console"), ("console-delta", 1))

    def test_other(self):
        self.assertEqual(resolve(CTX_OTHER, "down"), ("move", "down"))
        self.assertEqual(resolve(CTX_OTHER, "confirm"), ("activate",))
        self.assertEqual(resolve(CTX_OTHER, "back"), ("focus-sidebar",))
        self.assertEqual(resolve(CTX_OTHER, "context"), ("noop",))
        self.assertEqual(resolve(CTX_OTHER, "favorite"), ("noop",))


class PaneKeyTests(unittest.TestCase):
    """Keys that cross between the console list and the game grid."""

    def test_right_from_the_sidebar_enters_the_games(self):
        """Not the header bar: GTK's own keynav would land on those buttons."""
        self.assertEqual(pane_key_command(CTX_SIDEBAR, Gdk.KEY_Right), ("focus-grid",))
        self.assertEqual(pane_key_command(CTX_SIDEBAR, Gdk.KEY_KP_Right), ("focus-grid",))

    def test_tab_toggles_between_the_two_panes(self):
        self.assertEqual(pane_key_command(CTX_SIDEBAR, Gdk.KEY_Tab), ("focus-grid",))
        self.assertEqual(pane_key_command(CTX_GRID, Gdk.KEY_Tab), ("focus-sidebar",))

    def test_backspace_returns_to_the_console_list(self):
        self.assertEqual(pane_key_command(CTX_GRID, Gdk.KEY_BackSpace), ("focus-sidebar",))

    def test_arrows_in_the_grid_move_the_focus(self):
        """GtkFlowBox does not move focus on arrows, so we route them ourselves.

        This is the regression that made the ROM list unnavigable: the keys
        reached the card and bubbled back out without anything acting on them.
        """
        for keyval, action in (
            (Gdk.KEY_Up, "up"),
            (Gdk.KEY_Down, "down"),
            (Gdk.KEY_Right, "right"),
            (Gdk.KEY_KP_Down, "down"),
        ):
            with self.subTest(keyval=keyval):
                self.assertEqual(pane_key_command(CTX_GRID, keyval), ("move", action))

    def test_left_in_the_grid_crosses_to_the_sidebar_only_at_the_edge(self):
        self.assertEqual(pane_key_command(CTX_GRID, Gdk.KEY_Left), ("move-or-sidebar",))

    def test_grid_arrows_match_the_gamepad_routing(self):
        """Keyboard and gamepad share one table, so they cannot drift apart."""
        for keyval, action in ((Gdk.KEY_Up, "up"), (Gdk.KEY_Left, "left")):
            with self.subTest(keyval=keyval):
                self.assertEqual(
                    pane_key_command(CTX_GRID, keyval), resolve(CTX_GRID, action)
                )

    def test_shift_tab_is_left_as_the_way_out_to_the_rest_of_the_window(self):
        """Otherwise the header bar and menu stop being keyboard-reachable."""
        self.assertIsNone(pane_key_command(CTX_SIDEBAR, Gdk.KEY_Tab, shift=True))
        self.assertIsNone(pane_key_command(CTX_GRID, Gdk.KEY_Tab, shift=True))

    def test_sidebar_arrows_are_left_to_the_list_box(self):
        """It moves *and* selects, which is what makes the page follow along."""
        for keyval in (Gdk.KEY_Up, Gdk.KEY_Down, Gdk.KEY_Left):
            with self.subTest(keyval=keyval):
                self.assertIsNone(pane_key_command(CTX_SIDEBAR, keyval))

    def test_backspace_in_the_sidebar_is_not_claimed(self):
        self.assertIsNone(pane_key_command(CTX_SIDEBAR, Gdk.KEY_BackSpace))

    def test_nothing_is_claimed_outside_the_two_panes(self):
        """Dialogs, menus and the search field keep every key."""
        for context in (CTX_DIALOG, CTX_POPOVER, CTX_OTHER):
            for keyval in (Gdk.KEY_Right, Gdk.KEY_Tab, Gdk.KEY_BackSpace):
                with self.subTest(context=context, keyval=keyval):
                    self.assertIsNone(pane_key_command(context, keyval))


if __name__ == "__main__":
    unittest.main()
