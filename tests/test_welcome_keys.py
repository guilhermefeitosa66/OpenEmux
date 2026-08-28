"""The Welcome carousel must not flip slides under an open popup (issue #259).

The dialog's key controller runs in the bubble phase and claimed Left/Right
unconditionally. The language dropdown's list handles Up/Down but not
Left/Right, so those reached the carousel and changed the slide *behind* the
open list -- during the one interaction that slide exists for.
"""

import unittest

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

from openemux.ui.welcome import WelcomeAssistant

from tests.gtk_display import needs_display


class _Node:
    """A widget with a parent chain, which is all the walk reads."""

    def __init__(self, parent=None):
        self._parent = parent

    def get_parent(self):
        return self._parent


class _Popover(Gtk.Popover):
    """A real Gtk.Popover, so the isinstance check is the real one."""


@needs_display
class InsidePopoverTests(unittest.TestCase):
    def _inside(self, widget):
        return WelcomeAssistant._is_inside_popover(widget)

    def test_a_widget_in_the_dialog_body_is_not_in_a_popover(self):
        row = _Node(_Node(_Node()))
        self.assertFalse(self._inside(row))

    def test_the_dropdown_list_inside_the_popup_is(self):
        # What the language dropdown's open list looks like: a few boxes deep
        # inside the popover the DropDown puts up.
        popover = _Popover()
        listview = _Node(_Node(popover))
        self.assertTrue(self._inside(listview))

    def test_the_popover_itself_counts(self):
        self.assertTrue(self._inside(_Popover()))

    def test_nothing_focused_is_not_in_a_popover(self):
        self.assertFalse(self._inside(None))

    def test_the_walk_ends_at_the_top_of_the_tree(self):
        # A long chain with no popover must terminate, not loop.
        node = None
        for _ in range(50):
            node = _Node(node)
        self.assertFalse(self._inside(node))


class _Tree:
    """A widget tree the descendant walk can be run over."""

    def __init__(self, children=()):
        self._children = list(children)
        for index, child in enumerate(self._children):
            child._next = self._children[index + 1] if index + 1 < len(self._children) else None

    _next = None

    def get_first_child(self):
        return self._children[0] if self._children else None

    def get_next_sibling(self):
        return self._next


class _MappedPopover(Gtk.Popover):
    """A popover that reports itself as on screen."""

    def get_mapped(self):
        return True


class _ClosedPopover(Gtk.Popover):
    def get_mapped(self):
        return False


class _DialogStub(_Tree):
    """Just what the ownership rule reads: the focus and the widget tree."""

    _arrows_step_slides = WelcomeAssistant._arrows_step_slides
    _find_open_popover = classmethod(WelcomeAssistant._find_open_popover.__func__)
    _is_inside_popover = staticmethod(WelcomeAssistant._is_inside_popover)

    def __init__(self, focus=None, children=()):
        super().__init__(children)
        self._focus = focus

    def get_focus(self):
        return self._focus


def _popover_holder(popover):
    """A branch of the tree with a popover a few levels down, like a DropDown."""
    return _Tree([_Tree([popover])])


@needs_display
class OpenPopoverTests(unittest.TestCase):
    def test_a_dialog_with_no_popup_has_none(self):
        dialog = _DialogStub(children=[_Tree(), _Tree([_Tree()])])
        self.assertIsNone(dialog._find_open_popover(dialog))

    def test_an_open_popup_is_found_however_deep_it_sits(self):
        popover = _MappedPopover()
        dialog = _DialogStub(children=[_Tree(), _popover_holder(popover)])
        self.assertIs(dialog._find_open_popover(dialog), popover)

    def test_a_closed_popover_does_not_count(self):
        # A dropdown that merely has focus still leaves the arrows alone.
        dialog = _DialogStub(children=[_popover_holder(_ClosedPopover())])
        self.assertIsNone(dialog._find_open_popover(dialog))


@needs_display
class ArrowOwnershipTests(unittest.TestCase):
    """Whether Left/Right belong to the carousel right now."""

    def test_the_carousel_owns_the_arrows_normally(self):
        dialog = _DialogStub(focus=_Node(), children=[_Tree()])
        self.assertTrue(dialog._arrows_step_slides())

    def test_it_does_not_while_the_language_list_is_open(self):
        # The reported failure: picking a language and pressing Left/Right.
        dialog = _DialogStub(
            focus=_Node(), children=[_popover_holder(_MappedPopover())]
        )
        self.assertFalse(dialog._arrows_step_slides())

    def test_focus_reported_inside_the_popup_also_yields(self):
        # The other way a session can report it: a GTK4 popover is a native
        # surface, so which widget is "focused" is not something to build on.
        dialog = _DialogStub(focus=_Node(_Popover()), children=[_Tree()])
        self.assertFalse(dialog._arrows_step_slides())

    def test_nothing_focused_leaves_the_arrows_with_the_carousel(self):
        dialog = _DialogStub(focus=None, children=[_Tree()])
        self.assertTrue(dialog._arrows_step_slides())

    def test_a_focused_but_closed_dropdown_still_steps_slides(self):
        dialog = _DialogStub(
            focus=_Node(), children=[_popover_holder(_ClosedPopover())]
        )
        self.assertTrue(dialog._arrows_step_slides())


if __name__ == "__main__":
    unittest.main()
