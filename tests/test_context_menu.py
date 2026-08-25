import unittest

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib

from openemux.ui import context_menu


class FakePopover:
    """Everything the owner touches on a popover, and nothing else.

    The real ones need a display; the ownership rule does not.
    """

    def __init__(self, name="menu", parent="anchor"):
        self.name = name
        self.shown = False
        self.popdowns = 0
        self.unparented = 0
        self._parent = parent
        self._closed_handlers = []

    def connect(self, signal, handler):
        assert signal == "closed"
        self._closed_handlers.append(handler)

    def popup(self):
        self.shown = True

    def popdown(self):
        # GTK emits "closed" from popdown, so the fake does too: the owner has
        # to survive its own handler running inside its own call.
        self.popdowns += 1
        self.shown = False
        for handler in list(self._closed_handlers):
            handler(self)

    def get_parent(self):
        return self._parent

    def unparent(self):
        assert self._parent is not None, "unparent with no parent is a GTK critical"
        self._parent = None
        self.unparented += 1


class ContextMenuOwnerTests(unittest.TestCase):
    """One context menu at a time, whoever opened it (issue #275)."""

    def setUp(self):
        context_menu._open_popover = None

    tearDown = setUp

    def test_presenting_pops_the_menu_up(self):
        menu = FakePopover()
        context_menu.present_context_popover(menu)
        self.assertTrue(menu.shown)
        self.assertIs(context_menu._open_popover, menu)

    def test_a_second_menu_closes_the_first(self):
        # The reported bug: the keyboard and gamepad paths open a menu without
        # a click, so autohide never serialises them and two grabs stack.
        first = FakePopover("card-a")
        second = FakePopover("card-b")
        context_menu.present_context_popover(first)
        context_menu.present_context_popover(second)
        self.assertEqual(first.popdowns, 1)
        self.assertFalse(first.shown)
        self.assertTrue(second.shown)
        self.assertIs(context_menu._open_popover, second)

    def test_the_second_menu_survives_the_first_ones_closed_signal(self):
        # popdown() emits "closed" synchronously, and the first menu's handler
        # must not clear the entry the new menu just claimed.
        first = FakePopover("card-a")
        second = FakePopover("card-b")
        context_menu.present_context_popover(first)
        context_menu.present_context_popover(second)
        self.assertIs(context_menu._open_popover, second)

    def test_presenting_the_same_menu_again_does_not_close_it(self):
        menu = FakePopover()
        context_menu.present_context_popover(menu)
        context_menu.present_context_popover(menu)
        self.assertEqual(menu.popdowns, 0)
        self.assertTrue(menu.shown)

    def test_closing_by_itself_releases_the_slot(self):
        menu = FakePopover()
        context_menu.present_context_popover(menu)
        menu.popdown()  # click outside / Escape
        self.assertIsNone(context_menu._open_popover)

    def test_dismiss_closes_the_open_menu(self):
        menu = FakePopover()
        context_menu.present_context_popover(menu)
        self.assertTrue(context_menu.dismiss_context_popover())
        self.assertEqual(menu.popdowns, 1)
        self.assertIsNone(context_menu._open_popover)

    def test_dismiss_with_nothing_open_is_a_no_op(self):
        self.assertFalse(context_menu.dismiss_context_popover())

    def test_a_menu_closed_by_hand_is_not_dismissed_twice(self):
        menu = FakePopover()
        context_menu.present_context_popover(menu)
        menu.popdown()
        self.assertFalse(context_menu.dismiss_context_popover())
        self.assertEqual(menu.popdowns, 1)


class UnparentWhenIdleTests(unittest.TestCase):
    """The queued unparent must survive its parent dying first (issue #275)."""

    @staticmethod
    def _flush_idle():
        context = GLib.MainContext.default()
        while context.pending():
            context.iteration(False)

    def test_a_parented_popover_is_unparented(self):
        menu = FakePopover()
        context_menu.unparent_when_idle(menu)
        self._flush_idle()
        self.assertEqual(menu.unparented, 1)

    def test_an_orphaned_popover_is_left_alone(self):
        # A playlist switch disposes the card the menu hung off before the idle
        # runs; unparenting then is a GTK critical.
        menu = FakePopover(parent=None)
        context_menu.unparent_when_idle(menu)
        self._flush_idle()
        self.assertEqual(menu.unparented, 0)


if __name__ == "__main__":
    unittest.main()
