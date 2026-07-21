import unittest

from openemux.ui.navigation import (
    CTX_DIALOG,
    CTX_GRID,
    CTX_OTHER,
    CTX_POPOVER,
    CTX_SIDEBAR,
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


if __name__ == "__main__":
    unittest.main()
