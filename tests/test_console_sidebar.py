"""The sidebar: its rows, its right-click menu, and dragging a console.

`ui/console_sidebar.py` sat at 54%: building the window builds the rows, so the
list itself was exercised, and nothing else was. What was left is every way a
user acts on a console from here -- the drop hint that follows the pointer, the
menu that mirrors the header buttons per console, the Core/Shader/Layout
submenus that write straight to the config, and the "Move up"/"Move down"
entries that exist because drag-and-drop is unusable with a keyboard or a
gamepad (issue #386).

Driven against the real window; the popovers are built and their entries
invoked directly, so nothing is ever put on screen for a person to click.
"""

import unittest
from unittest import mock

from tests.gtk_display import HAVE_DISPLAY, needs_display
from tests.window_harness import WindowCase

if HAVE_DISPLAY:
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Gdk, Gtk

    from openemux.ui import console_sidebar as sidebar_module
    from openemux.ui.context_menu import SEPARATOR, Submenu
    from openemux.ui.scopes import ALL_CONSOLES_ID, FAVORITES_ID, collection_scope


class _SidebarCase(WindowCase):
    def setUp(self):
        super().setUp()
        self.sidebar = self.win.sidebar

    def rows(self):
        ids = []
        row = self.sidebar.list_box.get_first_child()
        while row is not None:
            ids.append(row.id)
            row = row.get_next_sibling()
        return ids

    def caught_menu(self):
        """Catch the popover the sidebar builds instead of showing it."""
        caught = []
        patcher = mock.patch.object(
            sidebar_module, "present_context_popover", caught.append
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        return caught


@needs_display
class TheRowsTests(_SidebarCase):
    def test_the_library_gets_an_all_row_above_the_consoles(self):
        self.assertEqual(self.rows()[0], ALL_CONSOLES_ID)

    def test_every_visible_console_gets_a_row(self):
        for console in self.win.visible_consoles:
            self.assertIsNotNone(self.sidebar.find_row(console))

    def test_a_console_that_is_not_there_has_no_row(self):
        self.assertIsNone(self.sidebar.find_row("N64"))

    def test_a_row_is_labelled_by_its_console_id_and_full_name(self):
        self.assertTrue(self.sidebar.label_for("SFC").startswith("SFC - "))

    def test_the_virtual_views_are_labelled_after_their_own_strings(self):
        self.assertEqual(self.sidebar.label_for(ALL_CONSOLES_ID), self.said("sidebar.all"))
        self.assertEqual(
            self.sidebar.label_for(FAVORITES_ID), self.said("sidebar.favorites")
        )

    def test_a_collection_row_is_labelled_after_the_collection(self):
        slug = self.win.collection_manager.create("RPGs")
        self.assertEqual(self.sidebar.label_for(collection_scope(slug)), "RPGs")

    def test_a_collection_with_no_name_falls_back_to_its_slug(self):
        self.assertEqual(
            self.sidebar.label_for(collection_scope("gone")), "gone"
        )

    def test_selecting_a_row_reports_whether_there_was_one(self):
        self.assertTrue(self.sidebar.select("SFC"))
        self.assertEqual(self.sidebar.selected_id(), "SFC")
        self.assertFalse(self.sidebar.select("N64"))

    def test_the_highlight_is_restored_after_a_rebuild(self):
        self.sidebar.select("FC")
        self.sidebar.rebuild(self.win.visible_consoles)
        self.sidebar.reselect_current()
        self.assertEqual(self.sidebar.selected_id(), "FC")

    def test_a_window_on_no_page_restores_no_highlight(self):
        self.win.current_console = None
        self.sidebar.rebuild(self.win.visible_consoles)
        self.sidebar.reselect_current()
        self.assertIsNone(self.sidebar.selected_id())

    def test_nothing_selected_reports_no_console(self):
        self.sidebar.list_box.unselect_all()
        self.assertIsNone(self.sidebar.selected_id())

    def test_the_playlist_button_only_appears_once_there_are_games(self):
        self.assertTrue(self.sidebar.new_collection_button.get_visible())
        self.win.visible_consoles = []
        self.sidebar.sync_footer()
        self.assertFalse(self.sidebar.new_collection_button.get_visible())


@needs_display
class TheFavoritesRowTests(_SidebarCase):
    """Issue #382: the row comes and goes with the favorites themselves."""

    def test_an_empty_favorites_list_gets_no_row(self):
        self.assertIsNone(self.sidebar.find_row(FAVORITES_ID))

    def test_the_first_star_puts_the_row_in_second_place(self):
        self.win._toggle_favorite_from_ui(self.rom())
        self.assertIsNotNone(self.sidebar.find_row(FAVORITES_ID))
        self.assertEqual(self.rows()[1], FAVORITES_ID)

    def test_the_last_unstar_takes_the_row_out_again(self):
        rom = self.rom()
        self.win._toggle_favorite_from_ui(rom)
        self.win._toggle_favorite_from_ui(rom)
        self.assertIsNone(self.sidebar.find_row(FAVORITES_ID))

    def test_the_row_stays_while_the_user_is_standing_on_the_page(self):
        # Un-starring the last game must not yank the row out from under them:
        # the empty state is what explains what just happened.
        rom = self.rom()
        self.win._toggle_favorite_from_ui(rom)
        self.win.current_console = FAVORITES_ID
        self.win._toggle_favorite_from_ui(rom)
        self.assertIsNotNone(self.sidebar.find_row(FAVORITES_ID))

    def test_a_sync_that_changes_nothing_touches_no_row(self):
        before = self.rows()
        self.sidebar.sync_favorites_row()
        self.assertEqual(self.rows(), before)

    def test_an_empty_library_gets_no_favorites_row_either(self):
        # No "All" row means no rows at all to insert one beside.
        self.sidebar.rebuild([])
        self.win.playlist_manager.toggle_favorite(self.rom())
        self.sidebar.sync_favorites_row()
        self.assertIsNone(self.sidebar.find_row(FAVORITES_ID))


@needs_display
class TheHoverButtonTests(_SidebarCase):
    def row_and_button(self, console="SFC"):
        row = self.sidebar.find_row(console)
        return row, row.menu_button

    def test_a_console_row_carries_a_menu_button_faded_out(self):
        _row, button = self.row_and_button()
        self.assertEqual(button.get_opacity(), 0)
        self.assertFalse(button.get_can_target())

    def test_the_virtual_views_carry_no_menu_button_at_all(self):
        row = self.sidebar.find_row(ALL_CONSOLES_ID)
        self.assertIsNone(getattr(row, "menu_button", None))

    def test_hovering_fades_the_button_in(self):
        _row, button = self.row_and_button()
        self.sidebar._show_menu_button(button)
        self.assertEqual(button.get_opacity(), 1)
        self.assertTrue(button.get_can_target())

    def test_leaving_fades_it_out_again(self):
        row, button = self.row_and_button()
        self.sidebar._show_menu_button(button)
        self.sidebar._hide_menu_button(button, row)
        self.assertEqual(button.get_opacity(), 0)

    def test_it_stays_while_its_own_menu_is_open(self):
        row, button = self.row_and_button()
        self.sidebar._show_menu_button(button)
        self.sidebar._menu_row = row
        self.sidebar._hide_menu_button(button, row)
        self.assertEqual(button.get_opacity(), 1)

    def test_clicking_it_opens_the_menu_under_itself(self):
        row, button = self.row_and_button()
        with mock.patch.object(self.sidebar, "_show_menu") as show:
            self.sidebar._on_menu_button(button, row, "SFC")
        show.assert_called_once()

    def test_a_button_with_no_bounds_yet_opens_the_menu_at_the_origin(self):
        row, _button = self.row_and_button()
        button = mock.Mock()
        button.compute_bounds.return_value = (False, None)
        with mock.patch.object(self.sidebar, "_show_menu") as show:
            self.sidebar._on_menu_button(button, row, "SFC")
        self.assertEqual(show.call_args[0][2:], (0, 0))

    def test_closing_the_menu_fades_the_button_out_again(self):
        row, button = self.row_and_button()
        self.sidebar._show_menu_button(button)
        self.sidebar._menu_row = row
        popover = Gtk.Popover()
        popover.set_parent(row)
        self.addCleanup(popover.unparent)
        self.sidebar._on_popover_closed(popover, row)
        self.assertIsNone(self.sidebar._menu_row)
        self.assertEqual(button.get_opacity(), 0)

    def test_closing_a_menu_that_belongs_to_another_row_keeps_the_current(self):
        row, _button = self.row_and_button()
        other = self.sidebar.find_row("FC")
        self.sidebar._menu_row = row
        popover = Gtk.Popover()
        popover.set_parent(other)
        self.addCleanup(popover.unparent)
        self.sidebar._on_popover_closed(popover, other)
        self.assertIs(self.sidebar._menu_row, row)


@needs_display
class DraggingAConsoleTests(_SidebarCase):
    """Issue #386: only the console rows take part in the arrangement."""

    def row(self, console="SFC"):
        return self.sidebar.find_row(console)

    def test_a_drag_marks_the_row_it_started_on(self):
        row = self.row()
        self.sidebar._on_drag_begin(row)
        self.assertTrue(row.has_css_class("console-row-dragging"))

    def test_the_drop_hint_follows_which_half_of_the_row_the_pointer_is_on(self):
        row = self.row()
        with mock.patch.object(row, "get_height", return_value=40):
            self.assertEqual(
                self.sidebar._on_drop_motion(row, 5), Gdk.DragAction.MOVE
            )
            self.assertTrue(row.has_css_class("console-drop-above"))
            self.sidebar._on_drop_motion(row, 35)
        self.assertTrue(row.has_css_class("console-drop-below"))
        self.assertFalse(row.has_css_class("console-drop-above"))

    def test_moving_onto_another_row_clears_the_previous_hint(self):
        first, second = self.row("SFC"), self.row("FC")
        with mock.patch.object(first, "get_height", return_value=40):
            with mock.patch.object(second, "get_height", return_value=40):
                self.sidebar._on_drop_motion(first, 5)
                self.sidebar._on_drop_motion(second, 5)
        self.assertFalse(first.has_css_class("console-drop-above"))
        self.assertTrue(second.has_css_class("console-drop-above"))

    def test_leaving_the_row_the_hint_is_on_clears_it(self):
        row = self.row()
        with mock.patch.object(row, "get_height", return_value=40):
            self.sidebar._on_drop_motion(row, 5)
        self.sidebar._on_drop_leave(row)
        self.assertFalse(row.has_css_class("console-drop-above"))

    def test_leaving_another_row_leaves_the_hint_alone(self):
        row, other = self.row("SFC"), self.row("FC")
        with mock.patch.object(row, "get_height", return_value=40):
            self.sidebar._on_drop_motion(row, 5)
        self.sidebar._on_drop_leave(other)
        self.assertTrue(row.has_css_class("console-drop-above"))

    def test_clearing_the_hint_also_unmarks_the_dragged_row(self):
        row = self.row()
        self.sidebar._on_drag_begin(row)
        self.sidebar._clear_drop_hint()
        self.assertFalse(row.has_css_class("console-row-dragging"))

    def test_dropping_above_a_row_puts_the_console_there(self):
        target = self.row("FC")
        with mock.patch.object(target, "get_height", return_value=40):
            with mock.patch.object(self.win, "place_console_in_order") as place:
                self.assertTrue(self.sidebar._on_row_drop("SFC", target, 5))
        place.assert_called_once_with("SFC", "FC")

    def test_dropping_below_the_last_row_puts_the_console_last(self):
        last = self.row(self.win.visible_consoles[-1])
        with mock.patch.object(last, "get_height", return_value=40):
            with mock.patch.object(self.win, "place_console_in_order") as place:
                self.sidebar._on_row_drop(self.win.visible_consoles[0], last, 35)
        self.assertIsNone(place.call_args[0][1])

    def test_dropping_a_console_where_it_already_is_writes_nothing(self):
        first = self.win.visible_consoles[0]
        row = self.row(first)
        with mock.patch.object(row, "get_height", return_value=40):
            with mock.patch.object(self.win, "place_console_in_order") as place:
                self.assertTrue(self.sidebar._on_row_drop(first, row, 5))
        place.assert_not_called()

    def test_a_payload_that_is_not_a_console_is_refused(self):
        row = self.row("FC")
        with mock.patch.object(self.win, "place_console_in_order") as place:
            self.assertFalse(self.sidebar._on_row_drop(object(), row, 5))
            self.assertFalse(self.sidebar._on_row_drop("N64", row, 5))
        place.assert_not_called()

    def test_a_drop_on_a_virtual_view_is_refused(self):
        # "All", "Favorites" and the collections are views over the ROMs, not
        # part of the hardware arrangement.
        row = self.sidebar.find_row(ALL_CONSOLES_ID)
        with mock.patch.object(self.win, "place_console_in_order") as place:
            self.assertFalse(self.sidebar._on_row_drop("SFC", row, 5))
        place.assert_not_called()

    def test_the_console_below_one_is_the_one_it_would_land_above(self):
        first, second = self.win.visible_consoles[:2]
        self.assertEqual(self.sidebar._console_after(first), second)

    def test_the_last_console_has_nothing_below_it(self):
        self.assertIsNone(
            self.sidebar._console_after(self.win.visible_consoles[-1])
        )

    def test_a_console_that_is_not_in_the_list_has_nothing_below_it(self):
        self.assertIsNone(self.sidebar._console_after("N64"))


@needs_display
class TheConsoleMenuTests(_SidebarCase):
    def entries(self, console="SFC"):
        """The entry list the menu would have been built from.

        `build_context_popover` is where the list turns into widgets, so
        catching it there keeps the menu off the screen and hands back
        something a test can read.
        """
        caught = []
        row = self.sidebar.find_row(console)
        with mock.patch.object(
            sidebar_module,
            "build_context_popover",
            lambda entries: caught.append(entries) or Gtk.Popover(),
        ):
            with mock.patch.object(sidebar_module, "present_context_popover"):
                self.sidebar._show_menu(row, console, 0, 0)
        return caught[-1]

    def labels(self, entries):
        out = []
        for entry in entries:
            if entry is SEPARATOR:
                continue
            out.append(entry.label if isinstance(entry, Submenu) else entry[0])
        return out

    def test_the_menu_mirrors_the_header_buttons_and_adds_open_folder(self):
        labels = self.labels(self.entries())
        self.assertIn(self.said("context.rescan.console"), labels)
        self.assertIn(self.said("header.import"), labels)
        self.assertIn(self.said("header.sync_covers"), labels)
        self.assertIn(self.said("context.open_folder"), labels)

    def test_the_layout_submenu_is_always_offered(self):
        self.assertIn(self.said("layout.menu"), self.labels(self.entries()))

    def test_a_console_with_no_core_installed_gets_no_core_submenu(self):
        # An empty submenu is worse than no submenu.
        with mock.patch.object(
            self.win.core_catalog, "cores_for_console", return_value=[]
        ):
            labels = self.labels(self.entries())
        self.assertNotIn(self.said("context.console.core"), labels)

    def test_a_console_with_cores_gets_the_core_submenu(self):
        core = mock.Mock(filename="snes9x_libretro.so", display_name="Snes9x")
        with mock.patch.object(
            self.win.core_catalog, "cores_for_console", return_value=[core]
        ):
            labels = self.labels(self.entries())
        self.assertIn(self.said("context.console.core"), labels)

    def test_the_shader_submenu_is_offered_when_the_catalog_has_options(self):
        labels = self.labels(self.entries())
        self.assertIn(self.said("context.console.shader"), labels)

    def test_an_empty_shader_catalog_gets_no_submenu(self):
        with mock.patch.object(
            self.win.shader_catalog, "get_options", return_value=[]
        ):
            labels = self.labels(self.entries())
        self.assertNotIn(self.said("context.console.shader"), labels)

    def test_the_first_console_is_offered_only_move_down(self):
        labels = self.labels(self.entries(self.win.visible_consoles[0]))
        self.assertNotIn(self.said("sidebar.move_up"), labels)
        self.assertIn(self.said("sidebar.move_down"), labels)

    def test_the_last_console_is_offered_only_move_up(self):
        labels = self.labels(self.entries(self.win.visible_consoles[-1]))
        self.assertIn(self.said("sidebar.move_up"), labels)
        self.assertNotIn(self.said("sidebar.move_down"), labels)

    def test_a_library_with_one_console_is_offered_neither(self):
        # An entry that can only do nothing is worse than no entry.
        with mock.patch.object(self.win, "visible_consoles", ["SFC"]):
            self.assertEqual(self.sidebar._move_entries("SFC"), [])

    def test_a_console_outside_the_arrangement_is_offered_neither(self):
        self.assertEqual(self.sidebar._move_entries("N64"), [])

    def test_a_collection_row_gets_its_own_menu_instead(self):
        slug = self.win.collection_manager.create("RPGs")
        self.win.refresh_library(force=True)
        scope = collection_scope(slug)
        labels = self.labels(self.entries(scope))
        self.assertIn(self.said("collections.rename"), labels)
        self.assertIn(self.said("collections.delete"), labels)

    def _empty_area_gesture(self, listbox):
        """The click gesture the sidebar installs on the list itself.

        A widget carries controllers of its own (a shortcut controller, for
        one), so the gesture is picked out by type rather than by position.
        """
        self.sidebar._install_empty_area_menu(listbox)
        controllers = listbox.observe_controllers()
        for index in range(controllers.get_n_items()):
            controller = controllers.get_item(index)
            if isinstance(controller, Gtk.GestureClick):
                return controller
        raise AssertionError("the sidebar installed no click gesture")

    def test_right_clicking_empty_space_offers_a_new_collection(self):
        # The per-row gestures claim their own clicks, so this only fires
        # where the release lands below the last row.
        caught = self.caught_menu()
        listbox = Gtk.ListBox()
        self.addCleanup(listbox.unparent)
        gesture = self._empty_area_gesture(listbox)
        gesture.emit("released", 1, 5.0, 500.0)
        self.assertEqual(len(caught), 1)

    def test_right_clicking_a_row_leaves_the_empty_area_menu_alone(self):
        caught = self.caught_menu()
        listbox = Gtk.ListBox()
        self.addCleanup(listbox.unparent)
        listbox.append(Gtk.ListBoxRow())
        gesture = self._empty_area_gesture(listbox)
        with mock.patch.object(
            listbox, "get_row_at_y", return_value=Gtk.ListBoxRow()
        ):
            gesture.emit("released", 1, 5.0, 5.0)
        self.assertEqual(caught, [])


@needs_display
class TheCoreSubmenuTests(_SidebarCase):
    def setUp(self):
        super().setUp()
        self.core = mock.Mock(filename="snes9x_libretro.so", display_name="Snes9x")
        patcher = mock.patch.object(
            self.win.core_catalog, "cores_for_console", return_value=[self.core]
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        name_patch = mock.patch.object(
            self.win.core_catalog, "display_name_for", return_value="Snes9x"
        )
        name_patch.start()
        self.addCleanup(name_patch.stop)

    def test_automatic_carries_the_check_while_there_is_no_override(self):
        submenu = self.sidebar._core_submenu("SFC")
        self.assertEqual(submenu.entries[0][2], "emblem-ok-symbolic")

    def test_the_chosen_core_carries_the_check_instead(self):
        self.config.set_console_core_override("SFC", "snes9x_libretro.so")
        submenu = self.sidebar._core_submenu("SFC")
        self.assertIsNone(submenu.entries[0][2])
        self.assertEqual(submenu.entries[-1][2], "emblem-ok-symbolic")

    def test_choosing_a_core_stores_it_warns_about_bios_and_says_so(self):
        with mock.patch.object(self.win, "_warn_missing_bios_for_core") as warn:
            self.sidebar.set_console_core("SFC", "snes9x_libretro.so")
        warn.assert_called_once()
        self.assertEqual(
            self.config.get_console_core_override("SFC"), "snes9x_libretro.so"
        )
        self.assertIn(
            self.said("toast.console_core_set", console="SFC", core="Snes9x"),
            self.toasts,
        )

    def test_going_back_to_automatic_clears_it_without_a_bios_warning(self):
        with mock.patch.object(self.win, "_warn_missing_bios_for_core") as warn:
            self.sidebar.set_console_core("SFC", None)
        warn.assert_not_called()
        self.assertFalse(self.config.get_console_core_override("SFC"))


@needs_display
class TheShaderSubmenuTests(_SidebarCase):
    def test_the_shader_in_use_carries_the_check(self):
        submenu = self.sidebar._shader_submenu("SFC")
        checked = [entry for entry in submenu.entries if entry[2]]
        self.assertEqual(len(checked), 1)

    def test_choosing_a_shader_stores_it_and_says_so(self):
        options = self.win.shader_catalog.get_options()
        shader_id = options[-1][0]
        self.sidebar.set_console_shader("SFC", shader_id)
        self.assertEqual(self.config.get_shader_for_console("SFC"), shader_id)
        self.assertTrue(self.toasts)

    def test_the_submenu_follows_the_show_all_setting(self):
        with mock.patch.object(
            self.win.shader_catalog, "get_options", return_value=[("a", "A")]
        ) as options:
            self.sidebar._shader_submenu("SFC")
        self.assertFalse(options.call_args.kwargs["show_all"])


@needs_display
class TheLayoutSubmenuTests(_SidebarCase):
    """The fastest route when setting several consoles in a row."""

    def test_use_global_carries_the_check_while_the_page_follows_it(self):
        submenu = self.sidebar._layout_submenu("SFC")
        self.assertEqual(submenu.entries[0][2], "emblem-ok-symbolic")

    def test_the_view_mode_in_use_carries_the_check(self):
        submenu = self.sidebar._layout_submenu("SFC")
        checked = [entry for entry in submenu.entries[2:] if entry[2]]
        self.assertEqual(len(checked), 1)

    def test_choosing_a_mode_gives_that_console_its_own_layout(self):
        other = next(
            mode
            for mode in sidebar_module.VIEW_MODES
            if mode != self.config.get_display_settings("SFC")["view_mode"]
        )
        self.sidebar._set_view_mode("SFC", other)
        self.assertEqual(
            self.config.get_display_settings("SFC")["view_mode"], other
        )

    def test_going_back_to_the_global_layout_drops_the_override(self):
        self.config.enable_scope_override("SFC")
        self.sidebar._use_global_layout("SFC")
        self.assertFalse(self.config.has_scope_override("SFC"))

    def test_a_change_to_the_page_on_screen_re_syncs_the_header(self):
        self.win.sidebar.select("SFC")
        with mock.patch.object(self.win, "_refresh_scope_settings") as refresh:
            self.sidebar._after_layout_changed("SFC")
        refresh.assert_called_once()

    def test_a_change_to_another_page_only_re_renders_that_page(self):
        self.win.sidebar.select("SFC")
        with mock.patch.object(self.win, "_refresh_scope_settings") as refresh:
            self.sidebar._after_layout_changed("FC")
        refresh.assert_not_called()


@needs_display
class TheMenuActionsTests(_SidebarCase):
    def setUp(self):
        super().setUp()
        self.sidebar._ensure_action_group()
        self.sidebar._menu_console = "SFC"

    def test_the_actions_are_installed_once(self):
        group = self.sidebar._action_group
        self.sidebar._ensure_action_group()
        self.assertIs(self.sidebar._action_group, group)

    def test_refresh_rescans_the_console_the_menu_belongs_to(self):
        with mock.patch.object(self.win, "_rescan_single_console") as rescan:
            self.sidebar._act_refresh(None, None)
        rescan.assert_called_once_with("SFC", show_toast=True)

    def test_refresh_on_a_virtual_view_rescans_everything(self):
        self.sidebar._menu_console = ALL_CONSOLES_ID
        with mock.patch.object(self.win, "_rescan_all_consoles") as rescan:
            self.sidebar._act_refresh(None, None)
        rescan.assert_called_once_with(show_toast=True)

    def test_import_opens_the_picker(self):
        with mock.patch.object(self.win.imports, "open_picker") as picker:
            self.sidebar._act_import(None, None)
        picker.assert_called_once()

    def test_sync_covers_covers_that_console(self):
        with mock.patch.object(self.win, "_start_cover_sync") as sync:
            self.sidebar._act_sync_covers(None, None)
        sync.assert_called_once_with(scope="console", selected_console="SFC")

    def test_sync_covers_from_a_virtual_view_covers_the_library(self):
        self.sidebar._menu_console = FAVORITES_ID
        with mock.patch.object(self.win, "_start_cover_sync") as sync:
            self.sidebar._act_sync_covers(None, None)
        sync.assert_called_once_with(scope="all", selected_console=None)

    def test_controller_opens_preferences_on_that_console(self):
        with mock.patch.object(self.win, "_open_preferences") as prefs:
            self.sidebar._act_controller(None, None)
        prefs.assert_called_once_with(page="input", console="SFC")

    def test_open_folder_opens_that_consoles_own_directory(self):
        with mock.patch.object(self.win, "_open_path_in_file_manager") as open_path:
            self.sidebar._act_open_folder(None, None)
        self.assertEqual(open_path.call_args[0][0].name, "SFC")

    def test_move_up_and_move_down_reach_the_window(self):
        with mock.patch.object(self.win, "move_console_in_order") as move:
            self.sidebar._act_move_up(None, None)
            self.sidebar._act_move_down(None, None)
        self.assertEqual([call[0][1] for call in move.call_args_list], [-1, 1])

    def test_moving_with_no_console_in_the_menu_moves_nothing(self):
        self.sidebar._menu_console = None
        with mock.patch.object(self.win, "move_console_in_order") as move:
            self.sidebar._act_move_up(None, None)
        move.assert_not_called()


if __name__ == "__main__":
    unittest.main()
