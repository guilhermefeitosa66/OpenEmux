"""The controller half of gamepad and keyboard navigation (issue #78).

`tests/test_navigation.py` covers the routing matrix -- context x action ->
command -- which is pure. What it cannot reach is the other 280 statements:
resolving *which* context the user is in from the focused widget, executing
each command against the real grid and sidebar, and keeping the hint bar in
step. All of it needs a window, so it ran only when a person used the app.

The window is the real one (`tests.window_harness`); the grid is real where
the assertion is about the grid, and a stand-in where the assertion is about
what the controller asked it to do.
"""

import unittest
from unittest import mock

from tests.gtk_display import HAVE_DISPLAY, needs_display
from tests.window_harness import WindowCase

if HAVE_DISPLAY:
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gdk, Gtk

    from openemux.ui import navigation as navigation_module
    from openemux.ui.navigation import (
        CTX_DIALOG,
        CTX_GRID,
        CTX_GRID_SELECTION,
        CTX_INPUT_CAPTURE,
        CTX_OTHER,
        CTX_POPOVER,
        CTX_SIDEBAR,
        SOURCE_GAMEPAD,
        SOURCE_KEYBOARD,
        SOURCE_MOUSE,
    )


class _NavigationCase(WindowCase):
    def setUp(self):
        super().setUp()
        self.nav = self.win.navigation

    def fake_grid(self, **attrs):
        """Stand in for the page's grid, and make it the current one."""
        grid = mock.Mock(**attrs)
        grid.is_group = attrs.get("is_group", False)
        patcher = mock.patch.object(self.nav, "_current_grid", return_value=grid)
        patcher.start()
        self.addCleanup(patcher.stop)
        return grid

    def presented_dialog(self):
        """An `Adw.AlertDialog` really attached to the window.

        Only a presented dialog puts itself in the widget's parent chain, and
        that chain is what `_scope_for` walks.
        """
        dialog = Adw.AlertDialog()
        button = Gtk.Button(label="ok")
        dialog.set_extra_child(button)
        self.show()
        dialog.present(self.win)
        self.pump()
        self.addCleanup(dialog.force_close)
        return dialog, button

    def focus_on(self, widget):
        """Report ``widget`` as the focused one, without a mapped window."""
        patcher = mock.patch.object(self.win, "get_focus", return_value=widget)
        patcher.start()
        self.addCleanup(patcher.stop)
        return widget


@needs_display
class WhichContextTheUserIsInTests(_NavigationCase):
    def test_a_window_with_nothing_focused_is_no_context_in_particular(self):
        self.focus_on(None)
        self.assertEqual(self.nav.current_context(), CTX_OTHER)

    def test_a_capture_waiting_for_a_button_outranks_everything(self):
        # The reader thread only notices the suspend flag on its next poll, so
        # an action already in flight has to be dropped here.
        self.win.input_capture_active = True
        self.assertEqual(self.nav.current_context(), CTX_INPUT_CAPTURE)

    def test_focus_inside_the_sidebar_list_is_the_sidebar(self):
        row = self.win.console_list.get_row_at_index(0)
        self.focus_on(row)
        self.assertEqual(self.nav.current_context(), CTX_SIDEBAR)

    def test_focus_inside_a_dialog_is_the_dialog(self):
        _dialog, button = self.presented_dialog()
        self.focus_on(button)
        self.assertEqual(self.nav.current_context(), CTX_DIALOG)

    def test_focus_inside_a_popover_is_the_popover(self):
        popover = Gtk.Popover()
        button = Gtk.Button()
        popover.set_child(button)
        self.focus_on(button)
        self.assertEqual(self.nav.current_context(), CTX_POPOVER)

    def test_a_menu_still_animating_open_already_counts_as_a_popover(self):
        # Gtk.Popover.popup() animates, so focus has not reached the menu by
        # the time the next button press arrives.
        popover = mock.Mock()
        popover.get_mapped.return_value = True
        self.nav._tracked_popover = popover
        self.focus_on(None)
        self.assertEqual(self.nav.current_context(), CTX_POPOVER)

    def test_a_tracked_menu_that_has_gone_is_forgotten(self):
        popover = mock.Mock()
        popover.get_mapped.return_value = False
        self.nav._tracked_popover = popover
        self.focus_on(None)
        self.assertEqual(self.nav.current_context(), CTX_OTHER)
        self.assertIsNone(self.nav._tracked_popover)

    def test_focus_on_a_card_in_the_page_grid_is_the_grid(self):
        self.win.sidebar.select("SFC")
        grid = self.win.pages.grid_for("SFC")
        self.focus_on(grid)
        self.assertEqual(self.nav.current_context(), CTX_GRID)

    def test_the_grid_in_selection_mode_is_its_own_context(self):
        self.win.sidebar.select("SFC")
        grid = self.win.pages.grid_for("SFC")
        self.focus_on(grid)
        self.win._selection_mode = True
        self.assertEqual(self.nav.current_context(), CTX_GRID_SELECTION)

    def test_a_grouped_page_asks_the_group_whether_it_holds_the_widget(self):
        # Issue #384: a grouped page is several grids behind one façade, so
        # the walk up cannot end in an identity check against one object.
        widget = Gtk.Button()
        group = self.fake_grid(is_group=True)
        group.holds_widget.side_effect = lambda node: node is widget
        self.focus_on(widget)
        self.assertEqual(self.nav.current_context(), CTX_GRID)

    def test_a_window_with_no_pages_yet_has_no_current_grid(self):
        with mock.patch.object(self.win, "pages", None):
            self.assertIsNone(self.nav._current_grid())

    def test_nothing_is_the_current_grid_when_there_is_no_grid(self):
        with mock.patch.object(self.nav, "_current_grid", return_value=None):
            self.assertFalse(self.nav._is_current_grid(Gtk.Button()))


@needs_display
class WhereFocusGoesBackToTests(_NavigationCase):
    def test_a_widget_in_this_window_is_restorable(self):
        self.show()
        self.assertTrue(self.nav._is_restorable(self.win.search_button))

    def test_nothing_at_all_is_not_restorable(self):
        self.assertFalse(self.nav._is_restorable(None))

    def test_a_widget_from_somewhere_else_is_not_restorable(self):
        self.assertFalse(self.nav._is_restorable(Gtk.Button()))

    def test_focus_goes_back_where_it_was_before_a_menu_opened(self):
        self.show()
        target = self.win.search_button
        self.nav._restore_target = target
        with mock.patch.object(target, "grab_focus") as grab:
            self.assertTrue(self.nav.restore_focus())
        grab.assert_called_once()
        self.assertIsNone(self.nav._restore_target)

    def test_with_nowhere_to_go_back_to_it_falls_back_to_the_grid(self):
        # A window with nothing focused is a dead end on a controller.
        self.nav._restore_target = None
        self.nav._focus_before_scope = None
        with mock.patch.object(self.nav, "_cmd_focus_grid") as focus_grid:
            self.nav.restore_focus()
        focus_grid.assert_called_once()

    def test_the_idle_wrapper_never_asks_glib_to_repeat_it(self):
        with mock.patch.object(self.nav, "restore_focus", return_value=True):
            self.assertFalse(self.nav._restore_focus_idle())

    def test_a_focus_change_inside_the_window_is_remembered(self):
        target = self.focus_on(self.win.search_button)
        self.nav._on_focus_changed()
        self.assertIs(self.nav._focus_before_scope, target)

    def test_a_focus_change_into_a_dialog_is_not_remembered(self):
        # Restoring focus *into* a dialog that has since closed would be worse
        # than leaving it nowhere.
        _dialog, button = self.presented_dialog()
        self.nav._focus_before_scope = None
        self.focus_on(button)
        self.nav._on_focus_changed()
        self.assertIsNone(self.nav._focus_before_scope)

    def test_losing_focus_altogether_puts_it_back(self):
        self.focus_on(None)
        with mock.patch.object(self.nav, "restore_focus") as restore:
            self.nav._on_focus_changed()
        restore.assert_called_once()

    def test_the_restore_target_is_only_taken_from_the_window_proper(self):
        popover = Gtk.Popover()
        button = Gtk.Button()
        popover.set_child(button)
        self.focus_on(button)
        self.nav._remember_restore_target()
        self.assertIsNone(self.nav._restore_target)


@needs_display
class WhichInputIsDrivingTests(_NavigationCase):
    def test_a_click_says_the_mouse_is_driving(self):
        self.nav._set_source(SOURCE_GAMEPAD)
        self.nav._on_click_watch(None, 1, 0, 0)
        self.assertEqual(self.nav._source, SOURCE_MOUSE)
        self.assertFalse(self.win.has_css_class("keynav-active"))

    def test_an_arrow_key_says_the_keyboard_is_driving(self):
        self.nav._on_key_watch(None, Gdk.KEY_Down, 0, 0)
        self.assertEqual(self.nav._source, SOURCE_KEYBOARD)
        self.assertTrue(self.win.has_css_class("keynav-active"))

    def test_an_ordinary_key_says_nothing_about_the_source(self):
        self.nav._set_source(SOURCE_MOUSE)
        self.nav._on_key_watch(None, Gdk.KEY_x, 0, 0)
        self.assertEqual(self.nav._source, SOURCE_MOUSE)

    def test_the_source_is_only_acted_on_when_it_actually_changes(self):
        self.nav._set_source(SOURCE_GAMEPAD)
        with mock.patch.object(self.nav, "refresh_hints") as refresh:
            self.nav._set_source(SOURCE_GAMEPAD)
        refresh.assert_not_called()

    def test_a_pad_being_plugged_in_is_announced(self):
        self.assertFalse(self.nav.on_gamepad_connected("Pro Controller"))
        self.assertTrue(self.nav.gamepad_connected)
        self.assertIn(
            self.said("toast.gamepad.connected", name="Pro Controller"), self.toasts
        )

    def test_a_pad_being_unplugged_hands_the_hints_back_to_the_mouse(self):
        self.nav.on_gamepad_connected("Pro Controller")
        self.nav._set_source(SOURCE_GAMEPAD)
        self.assertFalse(self.nav.on_gamepad_disconnected())
        self.assertFalse(self.nav.gamepad_connected)
        self.assertEqual(self.nav._source, SOURCE_MOUSE)
        self.assertIn(self.said("toast.gamepad.disconnected"), self.toasts)

    def test_a_pad_unplugged_while_the_keyboard_drives_leaves_it_alone(self):
        self.nav._set_source(SOURCE_KEYBOARD)
        self.nav.on_gamepad_disconnected()
        self.assertEqual(self.nav._source, SOURCE_KEYBOARD)


@needs_display
class GamepadActionsTests(_NavigationCase):
    def test_a_pad_action_is_dispatched_and_marks_the_pad_as_driving(self):
        with mock.patch.object(self.nav, "dispatch") as dispatch:
            self.assertFalse(self.nav.on_gamepad_action("confirm"))
        dispatch.assert_called_once_with("confirm")
        self.assertEqual(self.nav._source, SOURCE_GAMEPAD)

    def test_a_held_trigger_is_tracked_rather_than_dispatched(self):
        # The triggers are the pad's Shift (issue #78).
        with mock.patch.object(self.nav, "dispatch") as dispatch:
            self.nav.on_gamepad_action("range_on")
            self.assertTrue(self.nav.range_held)
            self.nav.on_gamepad_action("range_off")
            self.assertFalse(self.nav.range_held)
        dispatch.assert_not_called()

    def test_an_unknown_command_is_executed_as_nothing(self):
        self.nav._execute(("not-a-command",))

    def test_the_no_op_command_does_nothing(self):
        self.nav._cmd_noop()


@needs_display
class ThePaneKeysTests(_NavigationCase):
    def test_a_key_inside_an_open_menu_is_left_to_the_menu(self):
        popover = mock.Mock()
        popover.get_mapped.return_value = True
        self.nav._tracked_popover = popover
        self.assertFalse(self.nav.handle_pane_key(Gdk.KEY_Right, 0))

    def test_a_key_typed_into_a_text_field_is_left_to_the_field(self):
        # Backspace and Tab belong to the entry, not to pane navigation.
        self.focus_on(self.win.search_entry)
        self.assertFalse(self.nav.handle_pane_key(Gdk.KEY_BackSpace, 0))

    def test_a_key_no_pane_command_claims_is_left_to_gtk(self):
        self.focus_on(None)
        self.assertFalse(self.nav.handle_pane_key(Gdk.KEY_x, 0))

    def test_right_out_of_the_sidebar_is_claimed_and_enters_the_grid(self):
        row = self.win.console_list.get_row_at_index(0)
        self.focus_on(row)
        with mock.patch.object(self.nav, "_cmd_focus_grid") as focus_grid:
            self.assertTrue(self.nav.handle_pane_key(Gdk.KEY_Right, 0))
        focus_grid.assert_called_once()

    def test_ctrl_up_in_the_sidebar_moves_the_console(self):
        row = self.win.console_list.get_row_at_index(0)
        self.focus_on(row)
        with mock.patch.object(self.nav, "_cmd_move_console") as move:
            self.nav.handle_pane_key(Gdk.KEY_Up, Gdk.ModifierType.CONTROL_MASK)
        move.assert_called_once_with(-1)


@needs_display
class MovingAroundTests(_NavigationCase):
    def test_a_move_with_nothing_focused_lands_in_the_grid(self):
        self.focus_on(None)
        with mock.patch.object(self.nav, "_cmd_focus_grid") as focus_grid:
            self.nav._cmd_move("down")
        focus_grid.assert_called_once()

    def test_a_move_inside_a_menu_cannot_escape_into_the_window(self):
        popover = mock.Mock()
        popover.get_mapped.return_value = True
        self.nav._tracked_popover = popover
        self.focus_on(Gtk.Button())
        self.nav._cmd_move("down")
        popover.child_focus.assert_called_once()

    def test_left_out_of_the_grid_falls_back_to_the_sidebar(self):
        self.focus_on(Gtk.Button())
        with mock.patch.object(
            self.win, "child_focus", return_value=False
        ), mock.patch.object(self.nav, "_cmd_focus_sidebar") as sidebar:
            self.nav._cmd_move_or_sidebar()
        sidebar.assert_called_once()

    def test_left_that_lands_somewhere_leaves_the_sidebar_alone(self):
        self.focus_on(Gtk.Button())
        with mock.patch.object(
            self.win, "child_focus", return_value=True
        ), mock.patch.object(self.nav, "_cmd_focus_sidebar") as sidebar:
            self.nav._cmd_move_or_sidebar()
        sidebar.assert_not_called()

    def test_focusing_the_sidebar_reveals_it_on_a_narrow_window(self):
        with mock.patch.object(
            self.win.split_view, "get_collapsed", return_value=True
        ), mock.patch.object(self.win.split_view, "set_show_content") as show:
            self.nav._cmd_focus_sidebar()
        show.assert_called_once_with(False)

    def test_focusing_the_grid_reveals_the_content_on_a_narrow_window(self):
        grid = self.fake_grid()
        with mock.patch.object(
            self.win.split_view, "get_collapsed", return_value=True
        ), mock.patch.object(self.win.split_view, "set_show_content") as show:
            self.nav._cmd_focus_grid()
        show.assert_called_once_with(True)
        grid.focus_restore.assert_called_once()

    def test_focusing_a_page_with_no_grid_is_harmless(self):
        with mock.patch.object(self.nav, "_current_grid", return_value=None):
            self.nav._cmd_focus_grid()

    def test_f6_cycles_between_the_two_panes(self):
        with mock.patch.object(
            self.nav, "current_context", return_value=CTX_SIDEBAR
        ), mock.patch.object(self.nav, "_cmd_focus_grid") as grid:
            self.nav.toggle_pane_focus()
        grid.assert_called_once()
        with mock.patch.object(
            self.nav, "current_context", return_value=CTX_GRID
        ), mock.patch.object(self.nav, "_cmd_focus_sidebar") as sidebar:
            self.nav.toggle_pane_focus()
        sidebar.assert_called_once()

    def test_escape_from_the_grid_steps_back_to_the_sidebar(self):
        with mock.patch.object(
            self.nav, "current_context", return_value=CTX_GRID
        ), mock.patch.object(self.nav, "_cmd_focus_sidebar") as sidebar:
            self.assertTrue(self.nav.escape_to_sidebar())
        sidebar.assert_called_once()

    def test_escape_from_anywhere_else_is_not_handled_here(self):
        with mock.patch.object(self.nav, "current_context", return_value=CTX_OTHER):
            self.assertFalse(self.nav.escape_to_sidebar())


@needs_display
class CrossingGroupBoundariesTests(_NavigationCase):
    """Issue #384: Down at the bottom of one group enters the next."""

    def test_a_sideways_move_never_crosses_a_group(self):
        group = self.fake_grid(is_group=True)
        self.nav._cross_group_if_stuck("left", None)
        group.grid_after.assert_not_called()

    def test_a_move_that_landed_somewhere_is_not_second_guessed(self):
        group = self.fake_grid(is_group=True)
        self.focus_on(Gtk.Button())
        self.nav._cross_group_if_stuck("down", None)
        group.grid_after.assert_not_called()

    def test_an_ungrouped_page_has_no_next_group_to_enter(self):
        grid = self.fake_grid(is_group=False)
        previous = self.focus_on(Gtk.Button())
        self.nav._cross_group_if_stuck("down", previous)
        grid.grid_after.assert_not_called()

    def test_down_at_the_bottom_of_a_group_enters_the_next_one(self):
        group = self.fake_grid(is_group=True)
        previous = self.focus_on(Gtk.Button())
        target = mock.Mock()
        group.grid_after.return_value = target
        self.nav._cross_group_if_stuck("down", previous)
        target.focus_first_card.assert_called_once()

    def test_up_at_the_top_of_a_group_enters_the_one_above(self):
        group = self.fake_grid(is_group=True)
        previous = self.focus_on(Gtk.Button())
        target = mock.Mock()
        group.grid_before.return_value = target
        self.nav._cross_group_if_stuck("up", previous)
        target.focus_last_card.assert_called_once()

    def test_the_last_group_has_nothing_below_it(self):
        group = self.fake_grid(is_group=True)
        previous = self.focus_on(Gtk.Button())
        group.grid_after.return_value = None
        self.assertIsNone(self.nav._cross_group_if_stuck("down", previous))

    def test_the_first_group_has_nothing_above_it(self):
        group = self.fake_grid(is_group=True)
        previous = self.focus_on(Gtk.Button())
        group.grid_before.return_value = None
        self.nav._cross_group_if_stuck("up", previous)

    def test_a_widget_no_group_owns_crosses_nothing(self):
        group = self.fake_grid(is_group=True)
        group.item_for_widget.return_value = None
        previous = self.focus_on(Gtk.Button())
        self.nav._cross_group_if_stuck("down", previous)
        group.grid_after.assert_not_called()


@needs_display
class ActivatingAndMenusTests(_NavigationCase):
    def test_activating_nothing_does_nothing(self):
        self.focus_on(None)
        self.nav._cmd_activate()

    def test_a_widget_that_activates_itself_is_left_to_it(self):
        button = mock.Mock()
        button.activate.return_value = True
        self.focus_on(button)
        with mock.patch.object(self.win, "_focused_rom_item") as item:
            self.nav._cmd_activate()
        item.assert_not_called()

    def test_a_card_that_cannot_activate_launches_the_game_behind_it(self):
        button = mock.Mock()
        button.activate.return_value = False
        self.focus_on(button)
        item = mock.Mock(rom={"name": "Chrono Trigger"})
        with mock.patch.object(self.win, "_focused_rom_item", return_value=item):
            self.nav._cmd_activate()
        item.on_launch_callback.assert_called_once_with(item.rom)

    def test_a_widget_belonging_to_no_game_just_does_nothing(self):
        button = mock.Mock()
        button.activate.return_value = False
        self.focus_on(button)
        with mock.patch.object(self.win, "_focused_rom_item", return_value=None):
            self.nav._cmd_activate()

    def test_closing_a_menu_pops_it_down_and_queues_the_focus_back(self):
        popover = mock.Mock()
        popover.get_mapped.return_value = True
        self.nav._tracked_popover = popover
        with mock.patch.object(navigation_module.GLib, "idle_add") as idle_add:
            self.nav._cmd_close_popover()
        popover.popdown.assert_called_once()
        self.assertIsNone(self.nav._tracked_popover)
        idle_add.assert_called_once_with(self.nav._restore_focus_idle)

    def test_closing_a_menu_that_is_not_open_does_nothing(self):
        self.focus_on(None)
        self.nav._cmd_close_popover()

    def test_closing_a_dialog_closes_it_and_queues_the_focus_back(self):
        dialog, button = self.presented_dialog()
        self.focus_on(button)
        with mock.patch.object(dialog, "close") as close, mock.patch.object(
            navigation_module.GLib, "idle_add"
        ):
            self.nav._cmd_close_dialog()
        close.assert_called_once()

    def test_closing_a_dialog_when_none_is_open_does_nothing(self):
        self.focus_on(None)
        self.nav._cmd_close_dialog()

    def test_the_menu_button_opens_and_lands_on_the_first_entry(self):
        button = self.win.primary_menu_button
        popover = mock.Mock()
        with mock.patch.object(button, "popup") as popup, mock.patch.object(
            button, "get_popover", return_value=popover
        ):
            self.nav._cmd_open_menu()
        popup.assert_called_once()
        popover.child_focus.assert_called_once_with(Gtk.DirectionType.TAB_FORWARD)
        self.assertIs(self.nav._tracked_popover, popover)

    def test_a_window_with_no_menu_button_opens_nothing(self):
        with mock.patch.object(self.win, "primary_menu_button", None):
            self.nav._cmd_open_menu()

    def test_the_context_menu_opens_on_the_focused_card(self):
        item = mock.Mock()
        with mock.patch.object(self.win, "_focused_rom_item", return_value=item):
            self.nav._cmd_context_menu()
        item.show_context_menu.assert_called_once()
        self.assertIs(self.nav._tracked_popover, item.context_popover)

    def test_the_context_menu_with_no_card_focused_opens_nothing(self):
        with mock.patch.object(self.win, "_focused_rom_item", return_value=None):
            self.nav._cmd_context_menu()
        self.assertIsNone(self.nav._tracked_popover)

    def test_a_card_with_no_popover_yet_is_not_focused_into(self):
        item = mock.Mock(context_popover=None)
        with mock.patch.object(self.win, "_focused_rom_item", return_value=item):
            self.nav._cmd_context_menu()

    def test_the_favorite_button_goes_through_the_focused_card(self):
        item = mock.Mock()
        with mock.patch.object(self.win, "_focused_rom_item", return_value=item):
            self.nav._cmd_favorite()
        item.toggle_favorite.assert_called_once()

    def test_the_favorite_button_with_no_card_focused_does_nothing(self):
        with mock.patch.object(self.win, "_focused_rom_item", return_value=None):
            self.nav._cmd_favorite()

    def test_back_closes_the_search_bar_when_it_is_open(self):
        self.win.search_button.set_active(True)
        self.nav._cmd_close_search()
        self.assertFalse(self.win.search_button.get_active())

    def test_back_with_the_search_bar_shut_does_nothing(self):
        self.win.search_button.set_active(False)
        self.nav._cmd_close_search()


@needs_display
class SelectionCommandsTests(_NavigationCase):
    """Issue #78: the gamepad's own multi-select mode."""

    def test_with_no_grid_there_is_no_focused_item(self):
        with mock.patch.object(self.nav, "_current_grid", return_value=None):
            self.assertEqual(self.nav._focused_item_and_grid(), (None, None))

    def test_with_nothing_focused_there_is_no_item(self):
        self.fake_grid()
        self.focus_on(None)
        self.assertIsNone(self.nav._focused_item_and_grid()[0])

    def test_ctrl_arrows_move_the_cursor_and_keep_the_anchor(self):
        grid = self.fake_grid()
        self.focus_on(Gtk.Button())
        with mock.patch.object(self.nav, "_cmd_move"):
            self.nav._cmd_move_keep("down")
        grid.note_cursor.assert_called_once()
        self.assertTrue(grid.note_cursor.call_args.kwargs["keep_anchor"])

    def test_a_cursor_move_off_the_cards_notes_nothing(self):
        grid = self.fake_grid()
        grid.item_for_widget.return_value = None
        self.focus_on(Gtk.Button())
        with mock.patch.object(self.nav, "_cmd_move"):
            self.nav._cmd_move_keep("down")
        grid.note_cursor.assert_not_called()

    def test_shift_arrows_re_anchor_then_grow_the_range(self):
        grid = self.fake_grid()
        self.focus_on(Gtk.Button())
        with mock.patch.object(self.nav, "_cmd_move"):
            self.nav._cmd_move_select("down")
        grid.begin_range_from.assert_called_once()
        grid.extend_selection_to.assert_called_once()

    def test_an_additive_range_says_so_to_the_grid(self):
        grid = self.fake_grid()
        self.focus_on(Gtk.Button())
        with mock.patch.object(self.nav, "_cmd_move"):
            self.nav._cmd_move_select("down", additive=True)
        self.assertTrue(grid.extend_selection_to.call_args.kwargs["additive"])

    def test_a_range_started_off_the_cards_anchors_nothing(self):
        grid = self.fake_grid()
        grid.item_for_widget.return_value = None
        self.focus_on(Gtk.Button())
        with mock.patch.object(self.nav, "_cmd_move"):
            self.nav._cmd_move_select("down")
        grid.begin_range_from.assert_not_called()

    def test_toggling_a_card_reaches_the_grid(self):
        grid = self.fake_grid()
        self.focus_on(Gtk.Button())
        self.nav._cmd_toggle_select()
        grid.toggle_item.assert_called_once()

    def test_toggling_with_nothing_focused_reaches_nothing(self):
        grid = self.fake_grid()
        grid.item_for_widget.return_value = None
        self.focus_on(Gtk.Button())
        self.nav._cmd_toggle_select()
        grid.toggle_item.assert_not_called()

    def test_a_long_press_selects_the_card_and_enters_selection_mode(self):
        grid = self.fake_grid()
        self.focus_on(Gtk.Button())
        self.nav._cmd_selection_enter()
        grid.select_item.assert_called_once()
        self.assertTrue(self.win.selection_mode_active)

    def test_a_long_press_off_the_cards_enters_nothing(self):
        grid = self.fake_grid()
        grid.item_for_widget.return_value = None
        self.focus_on(Gtk.Button())
        self.nav._cmd_selection_enter()
        self.assertFalse(self.win.selection_mode_active)

    def test_leaving_selection_mode_clears_the_selection(self):
        self.win.enter_selection_mode()
        self.nav._cmd_selection_exit()
        self.assertFalse(self.win.selection_mode_active)

    def test_the_dpad_ranges_while_a_trigger_is_held(self):
        self.nav.range_held = True
        with mock.patch.object(self.nav, "_cmd_move_select") as ranged:
            self.nav._cmd_selection_move("down")
        ranged.assert_called_once_with("down")

    def test_the_dpad_just_moves_the_cursor_with_no_trigger_held(self):
        self.nav.range_held = False
        with mock.patch.object(self.nav, "_cmd_move_keep") as moved:
            self.nav._cmd_selection_move("down")
        moved.assert_called_once_with("down")

    def test_select_all_reaches_the_grid(self):
        grid = self.fake_grid()
        self.nav._cmd_selection_select_all()
        grid.toggle_select_all.assert_called_once()

    def test_select_all_on_a_page_with_no_grid_is_harmless(self):
        with mock.patch.object(self.nav, "_current_grid", return_value=None):
            self.nav._cmd_selection_select_all()

    def test_the_actions_button_hands_focus_to_the_selection_bar(self):
        with mock.patch.object(self.win, "focus_selection_actions") as focus:
            self.nav._cmd_selection_actions()
        focus.assert_called_once()


@needs_display
class SwitchingConsolesWithTheShouldersTests(_NavigationCase):
    def test_the_next_console_is_selected(self):
        rows = []
        row = self.win.console_list.get_first_child()
        while row is not None:
            rows.append(row)
            row = row.get_next_sibling()
        self.win.console_list.select_row(rows[0])
        self.nav._cmd_console_delta(1)
        self.assertIs(self.win.console_list.get_selected_row(), rows[1])

    def test_the_list_wraps_around_at_the_end(self):
        rows = []
        row = self.win.console_list.get_first_child()
        while row is not None:
            rows.append(row)
            row = row.get_next_sibling()
        self.win.console_list.select_row(rows[-1])
        self.nav._cmd_console_delta(1)
        self.assertIs(self.win.console_list.get_selected_row(), rows[0])

    def test_an_empty_sidebar_has_no_console_to_switch_to(self):
        with mock.patch.object(
            self.win.console_list, "get_first_child", return_value=None
        ):
            self.nav._cmd_console_delta(1)

    def test_switching_from_the_grid_puts_focus_back_in_the_new_grid(self):
        # The page is (re)rendered by the selection, so the grid can only be
        # focused on the next tick.
        with mock.patch.object(
            self.nav, "current_context", return_value=CTX_GRID
        ), mock.patch.object(navigation_module.GLib, "idle_add") as idle_add:
            self.nav._cmd_console_delta(1)
        self.assertIn(
            mock.call(self.nav._cmd_focus_grid), idle_add.call_args_list
        )


@needs_display
class MovingAConsoleWithTheKeyboardTests(_NavigationCase):
    """Issue #386: drag-and-drop is unusable with a keyboard or a gamepad."""

    def _select_console_row(self, console):
        row = self.win.sidebar.find_row(console)
        self.win.console_list.select_row(row)
        return row

    def test_the_selected_console_moves_and_keeps_the_focus(self):
        console = self.win.visible_consoles[0]
        self._select_console_row(console)
        self.nav._cmd_move_console(1)
        self.assertEqual(self.win.visible_consoles[1], console)

    def test_a_console_that_cannot_move_further_stays_put(self):
        console = self.win.visible_consoles[-1]
        self._select_console_row(console)
        with mock.patch.object(self.win.sidebar, "find_row") as find_row:
            self.nav._cmd_move_console(1)
        find_row.assert_not_called()

    def test_the_rows_above_the_consoles_are_not_part_of_the_arrangement(self):
        # "All", "Favorites" and the collections stay where they are.
        row = self.win.sidebar.find_row("__all__")
        if row is None:
            self.skipTest("the library has no All row")
        self.win.console_list.select_row(row)
        with mock.patch.object(self.win, "move_console_in_order") as move:
            self.nav._cmd_move_console(1)
        move.assert_not_called()

    def test_nothing_selected_moves_nothing(self):
        self.win.console_list.unselect_all()
        with mock.patch.object(self.win, "move_console_in_order") as move:
            self.nav._cmd_move_console(1)
        move.assert_not_called()


@needs_display
class TheHintBarTests(_NavigationCase):
    def hints(self):
        captured = []
        patcher = mock.patch.object(self.win, "set_hints", captured.append)
        patcher.start()
        self.addCleanup(patcher.stop)
        return captured

    def test_a_window_that_shows_no_hints_is_not_asked_to(self):
        # The controller is built before the bottom bar exists, and a focus
        # notify can arrive in that window.
        klass = type(self.win)
        original = klass.set_hints
        del klass.set_hints
        self.addCleanup(setattr, klass, "set_hints", original)
        self.nav.refresh_hints()

    def test_the_mouse_hides_the_hints_and_only_says_so_once(self):
        captured = self.hints()
        self.nav._hint_state = None
        self.nav._source = SOURCE_MOUSE
        self.nav.refresh_hints()
        self.nav.refresh_hints()
        self.assertEqual(captured, [[]])

    def test_a_pad_that_is_not_plugged_in_counts_as_the_mouse(self):
        captured = self.hints()
        self.nav._source = SOURCE_GAMEPAD
        self.nav.gamepad_connected = False
        self.nav._hint_state = None
        self.nav.refresh_hints()
        self.assertEqual(captured, [[]])

    def test_an_unchanged_context_is_not_redrawn(self):
        captured = self.hints()
        self.nav._source = SOURCE_KEYBOARD
        self.nav._hint_state = None
        with mock.patch.object(self.nav, "current_context", return_value=CTX_GRID):
            self.nav.refresh_hints()
            self.nav.refresh_hints()
        self.assertEqual(len(captured), 1)

    def _hints_for(self, source, context):
        captured = self.hints()
        self.nav._source = source
        self.nav.gamepad_connected = source == SOURCE_GAMEPAD
        self.nav._hint_state = None
        with mock.patch.object(self.nav, "current_context", return_value=context):
            self.nav.refresh_hints()
        return captured[-1]

    def test_a_capture_waiting_for_a_button_offers_no_action_at_all(self):
        self.assertEqual(
            self._hints_for(SOURCE_GAMEPAD, CTX_INPUT_CAPTURE), []
        )

    def test_the_pad_gets_the_selection_hints_in_selection_mode(self):
        glyphs = [glyph for glyph, _label in self._hints_for(
            SOURCE_GAMEPAD, CTX_GRID_SELECTION
        )]
        self.assertIn("L2/R2+✚", glyphs)

    def test_the_pad_gets_two_hints_in_a_dialog(self):
        self.assertEqual(len(self._hints_for(SOURCE_GAMEPAD, CTX_DIALOG)), 2)

    def test_the_pad_gets_the_sidebar_hints_in_the_sidebar(self):
        glyphs = [glyph for glyph, _label in self._hints_for(
            SOURCE_GAMEPAD, CTX_SIDEBAR
        )]
        self.assertIn("L1/R1", glyphs)

    def test_the_pad_gets_the_full_set_on_the_grid(self):
        self.assertEqual(len(self._hints_for(SOURCE_GAMEPAD, CTX_GRID)), 7)

    def test_the_keyboard_gets_enter_and_escape_in_a_popover(self):
        glyphs = [glyph for glyph, _label in self._hints_for(
            SOURCE_KEYBOARD, CTX_POPOVER
        )]
        self.assertEqual(glyphs, ["Enter", "Esc"])

    def test_the_keyboard_gets_the_pane_hints_in_the_sidebar(self):
        glyphs = [glyph for glyph, _label in self._hints_for(
            SOURCE_KEYBOARD, CTX_SIDEBAR
        )]
        self.assertIn("Tab", glyphs)

    def test_the_keyboard_gets_the_card_hints_on_the_grid(self):
        glyphs = [glyph for glyph, _label in self._hints_for(
            SOURCE_KEYBOARD, CTX_GRID
        )]
        self.assertIn("Ctrl+D", glyphs)


if __name__ == "__main__":
    unittest.main()
