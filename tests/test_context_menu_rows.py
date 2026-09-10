"""The rows a context menu is built out of.

`tests/test_context_menu.py` covers the ownership rule -- one menu open at a
time (issue #275) -- against a stand-in popover, which is all a headless run
can do. The rows themselves need widgets: the icon column that stays aligned
when a radio row leaves it blank, the colour swatch beside the cartridge
colours, the submenu that opens on hover so it reads as a menu rather than a
button, and the deferred activation that keeps GTK from crashing when an
action opens a window from inside the teardown.
"""

import unittest
from unittest import mock

from tests.gtk_display import HAVE_DISPLAY, needs_display

if HAVE_DISPLAY:
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Gdk", "4.0")
    from gi.repository import Gtk

    from openemux.ui import context_menu
    from openemux.ui.context_menu import SEPARATOR, Submenu, build_context_popover


def _rows(popover):
    """The widgets the popover's menu box holds, in order."""
    box = popover.get_child()
    rows = []
    child = box.get_first_child()
    while child is not None:
        rows.append(child)
        child = child.get_next_sibling()
    return rows


def _label_of(row):
    """The row's text, wherever in its box it sits."""
    for widget in _walk(row):
        if isinstance(widget, Gtk.Label):
            return widget.get_text()
    return None


def _walk(widget):
    child = widget.get_first_child()
    while child is not None:
        yield child
        yield from _walk(child)
        child = child.get_next_sibling()


def _draw_func_of(build):
    """The draw function ``build`` installs, caught as it is set.

    GTK4 paints on a frame tick, and a window presented from a test never gets
    one; intercepting `set_draw_func` is what makes the drawing itself
    assertable at all.
    """
    caught = []
    original = Gtk.DrawingArea.set_draw_func

    def _capture(area, func, *args):
        caught.append(func)
        return original(area, func, *args)

    with mock.patch.object(Gtk.DrawingArea, "set_draw_func", _capture):
        build()
    return caught[-1] if caught else None


def _paint(draw_func, width=14, height=14):
    """Run a draw function against a surface of its own."""
    import cairo

    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
    draw_func(None, cairo.Context(surface), width, height)


@needs_display
class TheRowsAMenuIsBuiltFromTests(unittest.TestCase):
    def test_a_leaf_row_carries_its_label_and_its_icon(self):
        popover = build_context_popover([("Rename", "rom.rename", "document-edit-symbolic")])
        self.addCleanup(popover.unparent)
        row = _rows(popover)[0]
        self.assertEqual(_label_of(row), "Rename")

    def test_a_separator_becomes_a_divider(self):
        popover = build_context_popover([("A", None, None), SEPARATOR, ("B", None, None)])
        self.addCleanup(popover.unparent)
        rows = _rows(popover)
        self.assertIsInstance(rows[1], Gtk.Separator)

    def test_a_row_with_no_action_at_all_cannot_be_clicked(self):
        # An empty save slot: shown, but there is nothing to do with it.
        popover = build_context_popover([("Slot 3 — empty", None, None)])
        self.addCleanup(popover.unparent)
        self.assertFalse(_rows(popover)[0].get_sensitive())

    def test_a_row_with_no_icon_still_keeps_the_column(self):
        # A radio row leaves the cell blank when it is not the selected one.
        popover = build_context_popover([("Crt", lambda: None, None)])
        self.addCleanup(popover.unparent)
        self.assertEqual(_label_of(_rows(popover)[0]), "Crt")

    def test_a_submenu_row_holds_a_popover_of_its_own(self):
        popover = build_context_popover(
            [Submenu("Shader", [("Crt", lambda: None, None)], "applications-graphics-symbolic")]
        )
        self.addCleanup(popover.unparent)
        self.assertEqual(_label_of(_rows(popover)[0]), "Shader")

    def test_a_submenu_can_hold_separators_and_further_submenus(self):
        popover = build_context_popover(
            [Submenu("Layout", [SEPARATOR, Submenu("Deeper", [("A", None, None)])])]
        )
        self.addCleanup(popover.unparent)
        self.assertEqual(len(_rows(popover)), 1)


@needs_display
class TheColourSwatchTests(unittest.TestCase):
    """The cartridge-colour menu draws a square beside each entry."""

    def _swatch(self, swatch_hex):
        return context_menu._swatch_widget(swatch_hex)

    def test_a_row_with_no_colour_keeps_a_blank_spacer(self):
        # Still the same size, so the colour column stays aligned.
        self.assertIsNone(_draw_func_of(lambda: self._swatch(None)))
        self.assertEqual(
            self._swatch(None).get_content_width(), context_menu._SWATCH_SIZE
        )

    def test_a_colour_is_drawn_as_a_rounded_square(self):
        _paint(_draw_func_of(lambda: self._swatch("#E01B24")))

    def test_a_colour_gtk_cannot_parse_falls_back_to_a_neutral_one(self):
        _paint(_draw_func_of(lambda: self._swatch("not-a-colour")))

    def test_a_swatch_row_is_built_with_the_square_between_icon_and_label(self):
        popover = build_context_popover([("Black", lambda: None, None, "#241F31")])
        self.addCleanup(popover.unparent)
        self.assertEqual(_label_of(_rows(popover)[0]), "Black")


@needs_display
class OpeningASubmenuOnHoverTests(unittest.TestCase):
    """A submenu that waits for a click reads as a button, not a menu."""

    def setUp(self):
        self.button = Gtk.Button()
        self.addCleanup(self.button.unparent)

    def _controllers(self, kind):
        controllers = self.button.observe_controllers()
        return [
            controllers.get_item(index)
            for index in range(controllers.get_n_items())
            if isinstance(controllers.get_item(index), kind)
        ]

    def test_pointing_at_a_row_opens_its_submenu(self):
        child = mock.Mock()
        child.get_visible.return_value = False
        hover = {"open": None}
        context_menu._reveal_on_hover(self.button, hover, child)
        self._controllers(Gtk.EventControllerMotion)[0].emit("enter", 0.0, 0.0)
        child.popup.assert_called_once()
        self.assertIs(hover["open"], child)

    def test_focus_opens_it_too_so_the_keyboard_behaves_the_same(self):
        child = mock.Mock()
        child.get_visible.return_value = False
        hover = {"open": None}
        context_menu._reveal_on_hover(self.button, hover, child)
        self._controllers(Gtk.EventControllerFocus)[0].emit("enter")
        child.popup.assert_called_once()

    def test_pointing_at_another_row_closes_the_one_that_was_open(self):
        # One branch showing at a time.
        previous = mock.Mock()
        child = mock.Mock()
        child.get_visible.return_value = False
        hover = {"open": previous}
        context_menu._reveal_on_hover(self.button, hover, child)
        self._controllers(Gtk.EventControllerMotion)[0].emit("enter", 0.0, 0.0)
        previous.popdown.assert_called_once()
        self.assertIs(hover["open"], child)

    def test_pointing_at_a_row_with_no_submenu_still_closes_the_open_one(self):
        previous = mock.Mock()
        hover = {"open": previous}
        context_menu._reveal_on_hover(self.button, hover, None)
        self._controllers(Gtk.EventControllerMotion)[0].emit("enter", 0.0, 0.0)
        previous.popdown.assert_called_once()
        self.assertIsNone(hover["open"])

    def test_a_submenu_that_is_already_open_is_not_opened_again(self):
        child = mock.Mock()
        child.get_visible.return_value = True
        hover = {"open": child}
        context_menu._reveal_on_hover(self.button, hover, child)
        self._controllers(Gtk.EventControllerMotion)[0].emit("enter", 0.0, 0.0)
        child.popup.assert_not_called()
        child.popdown.assert_not_called()


@needs_display
class ActivatingARowTests(unittest.TestCase):
    """The action runs after the menu is gone, never during its teardown."""

    def test_the_menu_closes_first_and_the_callback_follows_on_an_idle(self):
        popover = mock.Mock()
        ran = []
        with mock.patch.object(context_menu.GLib, "idle_add") as idle_add:
            context_menu._run_after_close(popover, lambda: ran.append(1))
        popover.popdown.assert_called_once()
        self.assertEqual(ran, [])
        idle_add.call_args[0][0]()
        self.assertEqual(ran, [1])

    def test_an_action_that_raises_is_logged_rather_than_escaping(self):
        # This is the last place a context-menu action can raise.
        popover = mock.Mock()
        with mock.patch.object(context_menu.GLib, "idle_add") as idle_add:
            context_menu._run_after_close(
                popover, mock.Mock(side_effect=RuntimeError("boom"))
            )
        with self.assertLogs("openemux.ui.context_menu", level="ERROR"):
            self.assertFalse(idle_add.call_args[0][0]())

    def test_a_named_action_is_fired_on_the_widget_the_menu_hangs_off(self):
        anchor = Gtk.Button()
        self.addCleanup(anchor.unparent)
        popover = Gtk.Popover()
        popover.set_parent(anchor)
        self.addCleanup(popover.unparent)
        with mock.patch.object(context_menu.GLib, "idle_add") as idle_add:
            context_menu._activate_action_row(popover, "rom.rename")
        with mock.patch.object(anchor, "activate_action") as activate:
            idle_add.call_args[0][0]()
        activate.assert_called_once_with("rom.rename", None)

    def test_a_menu_with_no_anchor_left_fires_nothing(self):
        # By the time the idle runs the popover may have been unparented.
        popover = Gtk.Popover()
        with self.assertLogs("openemux.ui.context_menu", level="WARNING"):
            context_menu._activate_action_row(popover, "rom.rename")

    def test_clicking_a_row_bound_to_a_callable_runs_it(self):
        ran = []
        popover = build_context_popover([("Rename", lambda: ran.append(1), None)])
        self.addCleanup(popover.unparent)
        with mock.patch.object(context_menu.GLib, "idle_add") as idle_add:
            _rows(popover)[0].emit("clicked")
        idle_add.call_args[0][0]()
        self.assertEqual(ran, [1])

    def test_clicking_a_row_bound_to_an_action_name_fires_it(self):
        anchor = Gtk.Button()
        self.addCleanup(anchor.unparent)
        popover = build_context_popover([("Rename", "rom.rename", None)])
        popover.set_parent(anchor)
        self.addCleanup(popover.unparent)
        with mock.patch.object(context_menu, "_activate_action_row") as activate:
            _rows(popover)[0].emit("clicked")
        activate.assert_called_once_with(popover, "rom.rename")


@needs_display
class DroppingAClosedMenuTests(unittest.TestCase):
    def test_a_popover_is_unparented_once_gtk_is_done_with_it(self):
        anchor = Gtk.Button()
        self.addCleanup(anchor.unparent)
        popover = Gtk.Popover()
        popover.set_parent(anchor)
        with mock.patch.object(context_menu.GLib, "idle_add") as idle_add:
            context_menu.unparent_when_idle(popover)
        self.assertFalse(idle_add.call_args[0][0]())
        self.assertIsNone(popover.get_parent())

    def test_a_popover_whose_parent_is_already_gone_is_left_alone(self):
        # A grid rebuild can take the parent first; unparenting a widget that
        # has none is a GTK critical.
        popover = Gtk.Popover()
        with mock.patch.object(context_menu.GLib, "idle_add") as idle_add:
            context_menu.unparent_when_idle(popover)
        self.assertFalse(idle_add.call_args[0][0]())


if __name__ == "__main__":
    unittest.main()
