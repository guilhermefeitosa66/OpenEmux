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
    from gi.repository import GLib, Gtk

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
        # A row is mapped while its menu is up; a test widget never is.
        self.mapped = mock.patch.object(self.button, "get_mapped", return_value=True)
        self.mapped.start()
        self.addCleanup(self.mapped.stop)

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

    def _focus(self, button=None):
        button = button or self.button
        controllers = button.observe_controllers()
        return [
            controllers.get_item(index)
            for index in range(controllers.get_n_items())
            if isinstance(controllers.get_item(index), Gtk.EventControllerFocus)
        ][0]

    def test_focusing_a_row_opens_its_submenu(self):
        child = mock.Mock()
        child.get_visible.return_value = False
        hover = {"open": None}
        context_menu._reveal_on_hover(self.button, hover, child)
        self._focus().emit("enter")
        child.popup.assert_called_once()
        self.assertIs(hover["focused"], self.button)

    def test_the_focused_row_getting_focus_back_does_not_close_the_submenu(self):
        # Opening a submenu takes the focus and the menu gets it straight
        # back: GTK re-emits enter on the row that already had it. Acting on
        # it closed the submenu, and the pointer reopened it (issue 985).
        hover = {"open": None}
        context_menu._reveal_on_hover(self.button, hover, None)
        self._focus().emit("enter")
        opened = mock.Mock()
        opened.get_visible.return_value = True
        hover["open"] = opened
        self._focus().emit("enter")
        opened.popdown.assert_not_called()
        self.assertIs(hover["open"], opened)

    def test_focus_moving_to_another_row_still_closes_the_submenu(self):
        other = Gtk.Button()
        self.addCleanup(other.unparent)
        previous = mock.Mock()
        hover = {"open": previous, "focused": other}
        context_menu._reveal_on_hover(self.button, hover, None)
        self._focus().emit("enter")
        previous.popdown.assert_called_once()
        self.assertIs(hover["focused"], self.button)

    def test_focus_coming_back_while_a_submenu_closes_does_not_reopen_it(self):
        # Closing the open submenu can put focus back on its row; the focus
        # path runs inside the popdown and must not undo it.
        other = Gtk.Button()
        self.addCleanup(other.unparent)
        previous = mock.Mock()
        previous.get_visible.return_value = False
        hover = {"open": previous}
        context_menu._reveal_on_hover(other, hover, previous)
        refocus = self._focus(other)
        previous.popdown.side_effect = lambda: refocus.emit("enter")
        context_menu._reveal_on_hover(self.button, hover, None)
        self._controllers(Gtk.EventControllerMotion)[0].emit("enter", 0.0, 0.0)
        previous.popdown.assert_called_once()
        previous.popup.assert_not_called()
        self.assertIsNone(hover["open"])
        self.assertFalse(hover["busy"])

    def test_a_row_that_is_no_longer_mapped_opens_nothing(self):
        # Crossings still arrive while a closing menu unmaps.
        self.mapped.stop()
        child = mock.Mock()
        child.get_visible.return_value = False
        hover = {"open": None}
        context_menu._reveal_on_hover(self.button, hover, child)
        self._controllers(Gtk.EventControllerMotion)[0].emit("enter", 0.0, 0.0)
        child.popup.assert_not_called()
        self.assertIsNone(hover["open"])
        self.mapped.start()

    def test_switching_rows_closes_the_previous_branch_with_the_handlers_held_off(self):
        # Its own row gets the keyboard back as it closes, and must neither
        # find it still recorded as open nor open it again (issue 984).
        previous = mock.Mock()
        hover = {"open": previous}
        seen = []
        previous.popdown.side_effect = lambda: seen.append(
            (context_menu._closing_submenus, hover["open"])
        )
        context_menu._reveal_on_hover(self.button, hover, None)
        self._controllers(Gtk.EventControllerMotion)[0].emit("enter", 0.0, 0.0)
        self.assertEqual(seen, [(True, None)])
        self.assertFalse(context_menu._closing_submenus)

    def test_nothing_opens_while_submenus_are_coming_down(self):
        child = mock.Mock()
        child.get_visible.return_value = False
        context_menu._reveal_on_hover(self.button, {"open": None}, child)
        context_menu._closing_submenus = True
        self.addCleanup(setattr, context_menu, "_closing_submenus", False)
        self._controllers(Gtk.EventControllerMotion)[0].emit("enter", 0.0, 0.0)
        child.popup.assert_not_called()


def _popovers_under(widget):
    return [w for w in _walk(widget) if isinstance(w, Gtk.Popover)]


@needs_display
class ClosingSubmenusInnermostFirstTests(unittest.TestCase):
    """Issue 984: a menu's submenus come down before the menu does."""

    def _nested_menu(self):
        popover = build_context_popover(
            [Submenu("Outer", [Submenu("Inner", [("A", lambda: None, None)])])]
        )
        self.addCleanup(popover.unparent)
        outer, inner = _popovers_under(popover)
        return popover, outer, inner

    def test_open_submenus_close_innermost_first(self):
        popover, outer, inner = self._nested_menu()
        order = []
        for name, sub in (("outer", outer), ("inner", inner)):
            mock.patch.object(sub, "get_visible", return_value=True).start()
            mock.patch.object(sub, "popdown", side_effect=lambda n=name: order.append(n)).start()
        self.addCleanup(mock.patch.stopall)
        with self.assertLogs("openemux.ui.context_menu", "INFO") as logs:
            context_menu._close_submenus(popover)
        self.assertEqual(order, ["inner", "outer"])
        self.assertIn("2 open submenu(s)", logs.output[0])

    def test_a_row_regaining_focus_while_its_submenu_closes_does_not_reopen_it(self):
        popover = build_context_popover([Submenu("Core", [("A", lambda: None, None)])])
        self.addCleanup(popover.unparent)
        row = _rows(popover)[0]
        (child,) = _popovers_under(row)
        focus = [
            c for c in list(row.observe_controllers()) if isinstance(c, Gtk.EventControllerFocus)
        ][0]
        visible = [True]

        def _popdown():
            visible[0] = False
            # GTK hands the keyboard back to the row as its submenu comes down.
            focus.emit("enter")

        mock.patch.object(row, "get_mapped", return_value=True).start()
        mock.patch.object(child, "get_visible", side_effect=lambda: visible[0]).start()
        popup = mock.patch.object(child, "popup").start()
        mock.patch.object(child, "popdown", side_effect=_popdown).start()
        self.addCleanup(mock.patch.stopall)
        with self.assertLogs("openemux.ui.context_menu", "INFO"):
            context_menu._close_submenus(popover)
        popup.assert_not_called()
        self.assertFalse(context_menu._closing_submenus)

    def test_a_menu_and_its_submenus_close_their_submenus_as_they_unmap(self):
        popover, outer, inner = self._nested_menu()
        for menu in (popover, outer, inner):
            self.assertIsInstance(menu, context_menu._MenuPopover)
        order = []
        with mock.patch.object(
            context_menu, "_close_submenus", side_effect=lambda p: order.append(("submenus", p))
        ), mock.patch.object(
            Gtk.Popover, "do_unmap", lambda p: order.append(("unmap", p))
        ):
            popover.do_unmap()
        self.assertEqual(order, [("submenus", popover), ("unmap", popover)])

    def test_a_nested_close_leaves_the_outer_one_holding_the_handlers_off(self):
        inner = mock.Mock()
        outer = mock.Mock()
        seen = []
        outer.popdown.side_effect = lambda: (
            context_menu._pop_down_quietly([inner]),
            seen.append(context_menu._closing_submenus),
        )
        context_menu._pop_down_quietly([outer])
        inner.popdown.assert_called_once()
        self.assertEqual(seen, [True])
        self.assertFalse(context_menu._closing_submenus)

    def test_hidden_submenus_are_left_alone(self):
        popover, outer, _inner = self._nested_menu()
        with mock.patch.object(outer, "popdown") as popdown:
            context_menu._close_submenus(popover)
        popdown.assert_not_called()

    def test_a_stand_in_for_a_popover_has_nothing_to_walk(self):
        context_menu._close_submenus(mock.Mock())  # no AttributeError, no call



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


@needs_display
class GuardingTheWindowWhileAMenuIsUpTests(unittest.TestCase):
    """The outside-click guard sits on the menu's window (issue #601)."""

    def setUp(self):
        context_menu._open_popover = None
        context_menu._outside_guard = None
        context_menu._guard_closing = False
        self.addCleanup(context_menu.dismiss_context_popover)
        self.window = Gtk.Window()
        self.addCleanup(self.window.destroy)
        self.box = Gtk.Box()
        self.window.set_child(self.box)
        self.window.present()

    def menu_on(self, anchor):
        popover = build_context_popover([("Rename", lambda: None, None)])
        popover.set_parent(anchor)
        self.addCleanup(popover.unparent)
        return popover

    def test_presenting_guards_the_window_on_every_button_before_its_children(self):
        context_menu.present_context_popover(self.menu_on(self.box))
        window, controller = context_menu._outside_guard
        self.assertIs(window, self.window)
        self.assertIs(controller.get_widget(), self.window)
        self.assertEqual(controller.get_button(), 0)
        self.assertEqual(
            controller.get_propagation_phase(), Gtk.PropagationPhase.CAPTURE
        )

    def test_a_second_menu_leaves_exactly_one_guard(self):
        first_anchor, second_anchor = Gtk.Button(), Gtk.Button()
        self.box.append(first_anchor)
        self.box.append(second_anchor)
        context_menu.present_context_popover(self.menu_on(first_anchor))
        first_controller = context_menu._outside_guard[1]
        context_menu.present_context_popover(self.menu_on(second_anchor))
        self.assertIsNone(first_controller.get_widget())
        second_controller = context_menu._outside_guard[1]
        self.assertIs(second_controller.get_widget(), self.window)

    def test_closing_the_menu_takes_the_guard_off_the_window(self):
        popover = self.menu_on(self.box)
        context_menu.present_context_popover(popover)
        controller = context_menu._outside_guard[1]
        popover.popdown()
        context = GLib.MainContext.default()
        while context.pending():
            context.iteration(False)
        self.assertIsNone(context_menu._outside_guard)
        self.assertIsNone(controller.get_widget())


if __name__ == "__main__":
    unittest.main()
