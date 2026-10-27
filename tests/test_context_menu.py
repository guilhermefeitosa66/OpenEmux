import unittest

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib

from openemux.ui import context_menu


class FakeAnchor:
    """A widget the menu hangs off that is not in any window yet."""

    def get_root(self):
        return None


class FakePopover:
    """Everything the owner touches on a popover, and nothing else.

    The real ones need a display; the ownership rule does not.
    """

    def __init__(self, name="menu", parent=None):
        self.name = name
        self.shown = False
        self.popdowns = 0
        self.unparented = 0
        self._parent = FakeAnchor() if parent is None else parent
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
        context_menu._outside_guard = None

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


class FakeSurface:
    pass


class FakeWindow:
    """The controller bookkeeping of a ``Gtk.Window``, and its surface."""

    def __init__(self):
        self.surface = FakeSurface()
        self.controllers = []

    def get_surface(self):
        return self.surface

    def remove_controller(self, controller):
        self.controllers.remove(controller)
        controller.widget = None


class FakeController:
    def __init__(self, window):
        self.widget = window
        window.controllers.append(self)

    def get_widget(self):
        return self.widget


class FakeEvent:
    def __init__(self, surface):
        self._surface = surface

    def get_surface(self):
        return self._surface


class FakeGesture:
    def __init__(self, surface=None):
        self._event = None if surface is None else FakeEvent(surface)
        self.state = None

    def get_current_event(self):
        return self._event

    def set_state(self, state):
        self.state = state


class OutsideClickTests(unittest.TestCase):
    """A press outside the menu closes it and reaches nothing else (issue #601).

    Installing the guard needs a real window, which is the widget test's job
    (`tests/test_context_menu_rows.py`); the decisions it takes on a press do
    not.
    """

    def setUp(self):
        context_menu._open_popover = None
        context_menu._outside_guard = None
        self.window = FakeWindow()

    tearDown = setUp

    def open_menu(self):
        menu = FakePopover()
        context_menu.present_context_popover(menu)
        controller = FakeController(self.window)
        context_menu._outside_guard = (self.window, controller)
        return menu, controller

    def press(self, surface):
        gesture = FakeGesture(surface)
        context_menu._on_outside_press(gesture, 1, 0, 0, self.window)
        return gesture

    def test_a_menu_with_no_anchor_still_pops_up_unguarded(self):
        menu = FakePopover()
        menu.unparent()
        context_menu.present_context_popover(menu)
        self.assertTrue(menu.shown)
        self.assertIsNone(context_menu._outside_guard)

    def test_an_anchor_outside_any_window_leaves_the_menu_unguarded(self):
        menu = FakePopover()
        context_menu.present_context_popover(menu)
        self.assertTrue(menu.shown)
        self.assertIsNone(context_menu._outside_guard)

    def test_a_press_on_the_window_closes_the_menu_and_is_claimed(self):
        # Claimed, so the card under the pointer never sees the click and the
        # game it shows is not launched.
        menu, controller = self.open_menu()
        with self.assertLogs("openemux.ui.context_menu", "INFO") as logs:
            gesture = self.press(self.window.surface)
        self.assertEqual(gesture.state, context_menu.Gtk.EventSequenceState.CLAIMED)
        self.assertFalse(menu.shown)
        self.assertIsNone(context_menu._open_popover)
        self.assertIsNone(context_menu._outside_guard)
        self.assertNotIn(controller, self.window.controllers)
        self.assertIn("context menu dismissed by a click outside", logs.output[0])

    def test_a_press_inside_the_menu_is_left_alone(self):
        # A row of the menu or of a submenu: a surface of its own, whose events
        # still travel up through the card to the window.
        menu, _controller = self.open_menu()
        gesture = self.press(FakeSurface())
        self.assertIsNone(gesture.state)
        self.assertTrue(menu.shown)
        self.assertIsNotNone(context_menu._outside_guard)

    def test_a_press_with_no_event_to_read_is_left_alone(self):
        menu, _controller = self.open_menu()
        gesture = FakeGesture()
        context_menu._on_outside_press(gesture, 1, 0, 0, self.window)
        self.assertIsNone(gesture.state)
        self.assertTrue(menu.shown)

    def test_a_stale_guard_removes_itself_without_eating_the_click(self):
        controller = FakeController(self.window)
        context_menu._outside_guard = (self.window, controller)
        gesture = self.press(self.window.surface)
        self.assertIsNone(gesture.state)
        self.assertIsNone(context_menu._outside_guard)
        self.assertNotIn(controller, self.window.controllers)

    def test_closing_by_itself_removes_the_guard(self):
        # Escape, a row activated, or the compositor's own autohide.
        menu, controller = self.open_menu()
        menu.popdown()
        self.assertIsNone(context_menu._outside_guard)
        self.assertNotIn(controller, self.window.controllers)

    def test_dismissing_removes_the_guard(self):
        _menu, controller = self.open_menu()
        context_menu.dismiss_context_popover()
        self.assertIsNone(context_menu._outside_guard)
        self.assertNotIn(controller, self.window.controllers)

    def test_a_guard_the_window_already_dropped_is_not_removed_twice(self):
        _menu, controller = self.open_menu()
        self.window.remove_controller(controller)
        context_menu.dismiss_context_popover()
        self.assertIsNone(context_menu._outside_guard)

    def test_a_menu_closed_in_some_other_way_keeps_the_new_ones_guard(self):
        # The replaced menu's "closed" must not take the new menu's guard.
        first, _controller = self.open_menu()
        second = FakePopover("card-b")
        context_menu._open_popover = second
        guard = context_menu._outside_guard
        context_menu._forget_context_popover(first)
        self.assertIs(context_menu._outside_guard, guard)


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
        menu = FakePopover()
        menu.unparent()
        menu.unparented = 0
        context_menu.unparent_when_idle(menu)
        self._flush_idle()
        self.assertEqual(menu.unparented, 0)


if __name__ == "__main__":
    unittest.main()
