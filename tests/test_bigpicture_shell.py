"""Big Picture's shell: the way in and out, the pages, the hints (issue 914)."""

# Builds real windows through tests.window_harness (via BigPictureCase): CI runs this
# module in the windowed process, with the other window tests.

import unittest
from unittest import mock

from tests.bigpicture_harness import BigPictureCase
from tests.gtk_display import HAVE_DISPLAY, needs_display

if HAVE_DISPLAY:
    from gi.repository import Gdk, GLib

    from openemux.ui import navigation
    from openemux.ui.scopes import ALL_CONSOLES_ID, FAVORITES_ID, RECENT_ID

# Pure Python: the theme's tests run with no display at all.
from openemux.ui.bigpicture import theme  # noqa: E402


@needs_display
class TheWayInAndOut(BigPictureCase):
    enter_mode = False

    def test_the_toggle_swaps_the_layout_and_goes_fullscreen(self):
        self.assertFalse(self.win.big_picture)
        self.assertTrue(self.win.toggle_big_picture())
        self.assertTrue(self.win.has_css_class("big-picture"))
        self.assertEqual(self.win.mode_stack.get_visible_child_name(), "big-picture")
        self.fullscreen_calls.assert_called_once()
        self.assertIn(self.said("big_picture.toast.on"), self.toasts)
        shell = self.win.big_picture_shell
        self.assertTrue(shell.active)
        # The desktop's page stack is under the rail now.
        self.assertIs(self.win.content_overlay.get_parent(), shell.library.content_host)
        self.assertEqual(self.win._zoom, max(self.config.get_zoom(), 1.5))

        self.assertFalse(self.win.toggle_big_picture())
        self.unfullscreen_calls.assert_called_once()
        self.assertFalse(self.win.has_css_class("big-picture"))
        self.assertEqual(self.win.mode_stack.get_visible_child_name(), "desktop")
        self.assertIs(self.win.content_toolbar.get_content(), self.win.content_overlay)
        self.assertIn(self.said("big_picture.toast.off"), self.toasts)
        self.assertFalse(shell.active)

    def test_f11_is_taken_in_the_capture_phase_and_nothing_else_is(self):
        self.assertFalse(self.win._on_big_picture_key(None, Gdk.KEY_a, 0, 0))
        self.assertTrue(self.win._on_big_picture_key(None, Gdk.KEY_F11, 0, 0))
        self.assertTrue(self.win.big_picture)
        # Ctrl+F11 and Alt+F11 belong to whoever bound them.
        self.assertFalse(
            self.win._on_big_picture_key(None, Gdk.KEY_F11, 0, Gdk.ModifierType.CONTROL_MASK)
        )
        self.win.input_capture_active = True
        self.assertFalse(self.win._on_big_picture_key(None, Gdk.KEY_F11, 0, 0))
        self.win.input_capture_active = False
        self.assertTrue(self.win._on_big_picture_key(None, Gdk.KEY_F11, 0, 0))
        self.assertFalse(self.win.big_picture)

    def test_the_action_the_menu_and_the_header_button_reach_the_toggle(self):
        self.assertEqual(self.win.big_picture_btn.get_action_name(), "win.big-picture")
        self.win.lookup_action("big-picture").activate(None)
        self.assertTrue(self.win.big_picture)
        self.win.lookup_action("big-picture").activate(None)
        self.assertFalse(self.win.big_picture)
        self.assertIn(self.win.t("menu.big_picture"), self.win.t("menu.big_picture"))

    def test_the_setting_and_the_flag_open_the_mode_at_start(self):
        self.assertFalse(self.win._wants_big_picture_at_start())
        self.config.set_big_picture_start(True)
        self.assertTrue(self.win._wants_big_picture_at_start())
        self.config.set_big_picture_start(False)
        self.app.start_big_picture = True
        try:
            self.assertTrue(self.win._wants_big_picture_at_start())
            self.assertEqual(self.win._enter_big_picture_at_start(), GLib.SOURCE_REMOVE)
            self.assertTrue(self.win.big_picture)
            self.assertEqual(self.win._enter_big_picture_at_start(), GLib.SOURCE_REMOVE)
            self.assertTrue(self.win.big_picture)
        finally:
            self.app.start_big_picture = False
            self.leave()

    def test_the_stylesheet_is_released_when_the_window_closes(self):
        self.enter()
        shell = self.shell
        self.assertIsNotNone(shell._provider)
        self.win.emit("close-request")
        self.assertIsNone(shell._provider)
        self.assertEqual(shell._clock_source, 0)


@needs_display
class TheHomePage(BigPictureCase):
    def test_home_is_the_root_with_the_library_scopes_as_tiles(self):
        home = self.shell.home
        self.assertIs(self.visible_page(), home)
        ids = [tile.scope_id for tile in home.console_tiles]
        self.assertEqual(ids[0], ALL_CONSOLES_ID)
        self.assertIn("SFC", ids)
        self.assertIn("FC", ids)
        self.assertEqual(self.shell.library_scopes(), ids)
        self.assertEqual(self.shell.game_count("SFC"), 2)
        self.assertEqual(self.shell.game_count(ALL_CONSOLES_ID), 3)
        self.assertEqual(self.shell.game_count(FAVORITES_ID), 0)
        self.assertEqual(self.shell.game_count(RECENT_ID), 0)
        self.assertFalse(home.continue_row.get_visible())
        entry_ids = [tile.entry_id for tile in home.system_tiles]
        self.assertEqual(entry_ids, ["search", "import", "covers", "share", "settings", "desktop"])

    def test_a_played_game_puts_a_continue_card_first(self):
        rom = self.rom("SFC")
        self.win.play_history.record_launch(rom["path"])
        self.win.play_history.record_play_time(rom["path"], 90)
        self.shell.home.refresh()
        self.pump()
        cards = self.shell.home.continue_cards
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0].rom["path"], rom["path"])
        self.assertTrue(self.shell.home.continue_row.get_visible())
        self.assertEqual(self.shell.game_count(RECENT_ID), 1)
        with mock.patch.object(self.win, "on_launch_game") as launch:
            cards[0].emit("clicked")
        self.assertEqual(launch.call_args[0][0]["path"], rom["path"])
        self.show()
        self.assertTrue(self.shell.home.focus_default())
        self.assertIs(self.focus_widget(), cards[0])

    def test_a_console_tile_opens_the_library_on_that_console(self):
        self.show()
        tile = next(t for t in self.shell.home.console_tiles if t.scope_id == "SFC")
        tile.emit("clicked")
        self.pump()
        self.assertIs(self.visible_page(), self.shell.library)
        self.assertEqual(self.win.current_console, "SFC")
        self.assertEqual(self.shell.library.rail.current_id, "SFC")
        self.assertTrue(self.shell.handle_back())
        self.pump()
        self.assertIs(self.visible_page(), self.shell.home)
        self.assertFalse(self.shell.handle_back())

    def test_the_system_tiles_run_the_quick_actions(self):
        with mock.patch.object(self.shell, "run_quick_action") as run:
            self.shell.home.system_tiles[0].emit("clicked")
        run.assert_called_once_with("search")


@needs_display
class TheLibraryPage(BigPictureCase):
    def test_the_shoulders_walk_the_rail_and_the_page_follows(self):
        self.show()
        self.shell.open_library("FC")
        self.pump()
        library = self.shell.library
        self.assertEqual(library.rail.current_id, "FC")
        ids = library.rail.ids()
        index = ids.index("FC")
        self.assertTrue(self.shell.step_console(1))
        self.pump()
        self.assertEqual(self.win.current_console, ids[(index + 1) % len(ids)])
        self.assertTrue(self.shell.step_console(-1))
        self.pump()
        self.assertEqual(self.win.current_console, "FC")
        # Not on home: the shoulders have nothing to walk there.
        self.shell.go_home()
        self.pump()
        self.assertFalse(self.shell.step_console(1))

    def test_tab_is_the_keyboards_shoulder(self):
        self.show()
        self.shell.open_library("FC")
        self.pump()
        before = self.win.current_console
        self.assertTrue(self.win.navigation.handle_pane_key(Gdk.KEY_Tab, 0))
        self.pump()
        self.assertNotEqual(self.win.current_console, before)
        self.assertTrue(self.win.navigation.handle_pane_key(Gdk.KEY_ISO_Left_Tab, 0))
        self.pump()
        self.assertEqual(self.win.current_console, before)
        self.assertFalse(self.win.navigation.handle_pane_key(Gdk.KEY_a, 0))
        # The Menu key is the keyboard's View button.
        with mock.patch.object(self.shell, "open_quick_menu") as menu:
            self.assertTrue(self.win.navigation.handle_pane_key(Gdk.KEY_Menu, 0))
        menu.assert_called_once()
        # Nothing to step on home, and Tab falls through to GTK there.
        self.shell.go_home()
        self.pump()
        self.assertFalse(self.win.navigation.handle_pane_key(Gdk.KEY_Tab, 0))

    def test_the_search_sheet_types_into_the_search_box(self):
        self.show()
        self.shell.open_library("SFC")
        self.pump()
        library = self.shell.library
        self.assertTrue(self.shell.open_search())
        self.pump()
        self.assertTrue(library.search_open)
        library.osk.type_char("C")
        self.assertEqual(self.win.search_entry.get_text(), "c")
        self.assertTrue(self.win.search_button.get_active())
        self.assertEqual(library.search_scope_label(), self.said("big_picture.search.in", scope=self.win.sidebar.label_for("SFC")))
        library.osk.handle_action("search")  # Start: done
        self.pump()
        self.assertFalse(library.search_open)
        # Opened from home: the library comes first, then the sheet.
        self.shell.go_home()
        self.pump()
        self.assertTrue(self.shell.open_search())
        self.pump()
        self.assertIs(self.visible_page(), library)
        self.assertTrue(library.search_open)
        self.assertTrue(self.shell.handle_back())
        self.assertFalse(library.search_open)
        self.win.sidebar.select(ALL_CONSOLES_ID)
        self.assertEqual(library.search_scope_label(), self.said("big_picture.search.everywhere"))

    def test_the_rail_rebuilds_when_the_scopes_change(self):
        library = self.shell.library
        library.sync()
        before = library.rail.ids()
        self.win._toggle_favorite_from_ui(self.rom("SFC"))
        self.pump()
        self.assertIn(FAVORITES_ID, library.rail.ids())
        self.assertNotEqual(before, library.rail.ids())
        # Outside the mode the shell is left alone.
        self.leave()
        with mock.patch.object(self.shell, "on_library_changed") as changed:
            self.win.refresh_library()
        changed.assert_not_called()
        self.assertFalse(self.shell.active)
        self.shell.on_library_changed()  # inert while the mode is off


@needs_display
class TheNavigatorInBigPicture(BigPictureCase):
    def test_contexts_follow_the_focus(self):
        self.show()
        nav = self.win.navigation
        self.assertEqual(nav.current_context(), navigation.CTX_BP_HOME)
        self.shell.open_library("SFC")
        self.pump()
        self.shell.library.rail.focus_current()
        self.assertEqual(nav.current_context(), navigation.CTX_BP_RAIL)
        grid = self.win.pages.grid_for("SFC")
        self.pump_until(lambda: grid.card_for(grid.entries()[0]) is not None)
        grid.focus_first_card()
        self.pump()
        self.assertEqual(nav.current_context(), navigation.CTX_BP_GRID)
        self.shell.library.show_search()
        self.pump()
        self.assertEqual(nav.current_context(), navigation.CTX_BP_OSK)

    def test_the_pad_actions_reach_the_shell(self):
        nav = self.win.navigation
        with mock.patch.object(self.shell, "handle_back") as back:
            nav._cmd_bp_back()
        back.assert_called_once()
        with mock.patch.object(self.shell, "step_console") as step:
            nav._cmd_bp_console_delta(1)
        step.assert_called_once_with(1)
        with mock.patch.object(self.shell, "open_search") as search:
            nav._cmd_bp_search()
        search.assert_called_once()
        with mock.patch.object(self.shell, "open_quick_menu") as menu:
            nav._cmd_bp_quick_menu()
        menu.assert_called_once()
        with mock.patch.object(self.shell.library.osk, "handle_action") as osk:
            nav._cmd_bp_osk("favorite")
        osk.assert_called_once_with("favorite")
        with mock.patch.object(self.win, "toggle_big_picture") as toggle:
            nav._cmd_big_picture()
        toggle.assert_called_once()
        with mock.patch.object(self.win, "_focused_rom_item", return_value=None):
            nav._cmd_bp_details()
        item = mock.Mock(rom={"name": "x"})
        with mock.patch.object(self.win, "_focused_rom_item", return_value=item), mock.patch.object(
            self.shell, "open_details"
        ) as details:
            nav._cmd_bp_details()
        details.assert_called_once_with(item.rom)
        page = mock.Mock()
        with mock.patch.object(self.shell, "visible_page", return_value=page):
            nav._cmd_bp_page_action("favorite")
        page.on_pad_action.assert_called_once_with("favorite")
        with mock.patch.object(self.shell, "visible_page", return_value=object()):
            nav._cmd_bp_page_action("favorite")

    def test_the_hints_are_the_pages_and_always_shown(self):
        nav = self.win.navigation
        nav._source = navigation.SOURCE_MOUSE
        nav.refresh_hints(force=True)
        keys = [slot[1].get_label() for slot in self.shell.hint_bar.slots if slot[0].get_visible()]
        self.assertIn("Enter", keys)
        nav.gamepad_connected = True
        nav._source = navigation.SOURCE_GAMEPAD
        nav.refresh_hints(force=True)
        keys = [slot[1].get_label() for slot in self.shell.hint_bar.slots if slot[0].get_visible()]
        self.assertIn(nav.glyphs()["confirm"], keys)
        self.assertEqual(self.shell.hints_for(navigation.CTX_BP_OSK, nav.glyphs())[0][1], self.said("big_picture.hints.type"))
        self.assertEqual(self.shell.hints_for(navigation.CTX_BP_RAIL, nav.glyphs())[0][1], self.said("big_picture.hints.open"))
        with mock.patch.object(self.shell, "visible_page", return_value=None):
            self.assertEqual(self.shell.hints_for(navigation.CTX_BP_PAGE, nav.glyphs()), [])
        self.assertEqual(nav._big_picture_hints(navigation.SOURCE_GAMEPAD, navigation.CTX_DIALOG)[1][1], self.said("hints.close"))
        self.assertEqual(nav._big_picture_hints(navigation.SOURCE_KEYBOARD, navigation.CTX_GRID_SELECTION)[0][0], "Enter")
        # The desktop's own slots stay empty while the mode is on.
        self.assertFalse(self.win.hint_box.get_visible())

    def test_a_number_row_takes_left_and_right(self):
        from openemux.ui.bigpicture.widgets import ROW_NUMBER, Row

        steps = []
        row = Row("n", kind=ROW_NUMBER, value=1, on_step=steps.append)
        self.shell.home.body.append(row)
        self.show()
        row.grab_focus()
        self.pump()
        self.win.navigation._cmd_move("right")
        self.win.navigation._cmd_move("left")
        self.assertEqual(steps, [1, -1])
        self.shell.home.body.remove(row)


@needs_display
class TheQuickMenu(BigPictureCase):
    def test_every_tile_runs_its_action(self):
        from openemux.ui.bigpicture.quick_menu import QuickMenuDialog, quick_menu_entries

        ids = [entry[0] for entry in quick_menu_entries(self.win.t)]
        self.assertEqual(ids[-1], "quit")
        self.assertEqual(quick_menu_entries(self.win.t, "Syncing")[0][0], "stop")
        with mock.patch.object(QuickMenuDialog, "present"):
            dialog = self.shell.open_quick_menu()
        self.assertEqual([tile.entry_id for tile in dialog.tiles], ids)
        with mock.patch.object(self.shell, "run_quick_action") as run:
            dialog.tiles[0].emit("clicked")
            self.pump()
        run.assert_called_once_with("search")
        dialog._on_map()
        self.pump()
        dialog.force_close()

    def test_the_quick_menu_is_presented_over_the_window(self):
        self.show()
        dialog = self.shell.open_quick_menu()
        self.pump()
        self.assertIs(self.win.get_visible_dialog(), dialog)
        self.assertEqual(self.win.navigation.current_context(), navigation.CTX_DIALOG)
        self.pump_until(lambda: self.focus_widget() is dialog.tiles[0])
        self.assertIs(self.focus_widget(), dialog.tiles[0])
        dialog.force_close()
        self.pump()
        self.assertIsNone(self.win.get_visible_dialog())

    def test_the_quick_actions(self):
        shell = self.shell
        win = self.win
        with mock.patch.object(shell, "open_search") as search:
            shell.run_quick_action("search")
        search.assert_called_once()
        with mock.patch.object(win, "receive_games") as receive:
            shell.run_quick_action("receive")
        receive.assert_called_once()
        with mock.patch.object(win, "_rescan_all_consoles") as rescan:
            shell.run_quick_action("rescan")
        rescan.assert_called_once_with(show_toast=True)
        with mock.patch.object(win, "toggle_big_picture") as toggle:
            shell.run_quick_action("desktop")
        toggle.assert_called_once()
        with mock.patch.object(self.app, "quit") as quit_app:
            shell.run_quick_action("quit")
        quit_app.assert_called_once()
        shell.run_quick_action("stop")  # nothing running: nothing to stop
        task = win.tasks.begin("scan", "Scanning", on_cancel=lambda: None)
        self.assertEqual(win.tasks.current_label(), "Scanning")
        shell.run_quick_action("stop")
        self.assertTrue(win.tasks.current_task()["cancelling"])
        win.tasks.finish(task)
        self.assertIsNone(win.tasks.current_task())
        self.assertFalse(shell.run_quick_action("nothing"))
        with mock.patch.object(win, "share_roms") as share:
            win.sidebar.select("SFC")
            self.pump()
            shell.run_quick_action("share")
        self.assertEqual(len(share.call_args[0][0]), 2)
        with mock.patch.object(win, "_visible_grid", return_value=None), mock.patch.object(
            win, "receive_games"
        ) as receive:
            shell.open_share()
        receive.assert_called_once()


class TheTheme(unittest.TestCase):
    def test_the_scale_follows_the_height_and_the_text_size(self):
        self.assertEqual(theme.scale_for(1080), 1.0)
        self.assertEqual(theme.scale_for(720), round(720 / 1080, 3))
        self.assertEqual(theme.scale_for(1080, 150), 1.5)
        self.assertEqual(theme.scale_for(0), 1.0)
        self.assertEqual(theme.scale_for("x"), 1.0)
        self.assertEqual(theme.scale_for(10), theme.MIN_SCALE)
        self.assertEqual(theme.scale_for(10000), theme.MAX_SCALE)
        self.assertEqual(theme.normalize_text_size("abc"), 100)
        self.assertEqual(theme.normalize_text_size(123), 120)
        self.assertEqual(theme.normalize_text_size(500), 150)

    def test_the_stylesheet_is_scoped_and_scaled(self):
        css = theme.stylesheet(1.0, dark=True)
        self.assertIn(".big-picture .bp-row {", css)
        self.assertIn(f"font-size: {theme.SIZES['title']}px", css)
        light = theme.stylesheet(2.0, dark=False)
        self.assertIn(f"font-size: {theme.SIZES['title'] * 2}px", light)
        self.assertIn(theme.ACCENT_TEXT_LIGHT, light)
        self.assertNotIn(theme.ACCENT_TEXT_DARK, light)
        self.assertEqual(theme.px("ring", 0.5), 2)
        self.assertEqual(theme.px("ring", 0.01), 1)


if __name__ == "__main__":
    unittest.main()
