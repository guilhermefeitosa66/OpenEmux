"""Big Picture's home and library pages, and the shell's corners (issue 914)."""

# Builds real windows through tests.window_harness (via BigPictureCase): CI runs this
# module in the windowed process, with the other window tests.

import unittest
from unittest import mock

from tests.bigpicture_harness import BigPictureCase
from tests.gtk_display import HAVE_DISPLAY, needs_display

if HAVE_DISPLAY:
    from gi.repository import GdkPixbuf, GLib, Gtk

    from openemux.ui import navigation
    from openemux.ui.bigpicture import home as home_module
    from openemux.ui.scopes import ALL_CONSOLES_ID, RECENT_ID, collection_scope


@needs_display
class ContinueCards(BigPictureCase):
    def test_a_cover_arrives_on_the_card_and_a_missing_one_does_not(self):
        rom = self.rom("SFC")
        card = home_module.ContinueCard(self.win, rom, "caption")
        self.assertEqual(card._apply(None), GLib.SOURCE_REMOVE)
        self.assertIsNone(card.picture.get_paintable())
        # Not in a window: a late decode is dropped.
        pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, 4, 4)
        card._apply(pixbuf)
        self.assertIsNone(card.picture.get_paintable())
        self.shell.home.continue_row.strip.append(card)
        self.show()
        card._apply(pixbuf)
        self.assertIsNotNone(card.picture.get_paintable())
        self.shell.home.continue_row.strip.remove(card)

    def test_the_count_labels_by_scope_kind(self):
        home = self.shell.home
        slug = self.win.collection_manager.create("Mega Man")
        self.win.collection_manager.add(slug, [self.rom("SFC")["path"]])
        self.win.refresh_library(force=True)
        self.pump()
        scope = collection_scope(slug)
        self.assertEqual(self.shell.game_count(scope), 1)
        self.assertEqual(home._count_label(scope, "collection"), self.said("big_picture.home.playlist_count", count=1))
        self.assertEqual(home._count_label("FC", "console"), self.said("header.subtitle.one_game"))
        with mock.patch.object(self.shell, "game_count", return_value=None):
            self.assertIsNone(home._count_label("FC", "console"))
        self.assertEqual(home_module.scope_kind(RECENT_ID), "recent")
        self.assertEqual(home_module.scope_kind(scope), "collection")
        self.assertIn(scope, home.get_tiles_scopes() if hasattr(home, "get_tiles_scopes") else [t.scope_id for t in home.console_tiles])

    def test_focus_falls_through_the_rows(self):
        home = self.shell.home
        self.show()
        home.continue_cards = []
        self.assertTrue(home.focus_default())
        self.assertIs(self.focus_widget(), home.console_tiles[0])
        home.console_tiles = []
        self.assertTrue(home.focus_default())
        self.assertIs(self.focus_widget(), home.system_tiles[0])
        home.refresh()


@needs_display
class TheLibraryPageCorners(BigPictureCase):
    def test_attaching_twice_and_detaching_twice_are_harmless(self):
        library = self.shell.library
        library.attach_content()
        self.assertIs(self.win.content_overlay.get_parent(), library.content_host)
        library.detach_content()
        library.detach_content()
        self.assertIs(self.win.content_toolbar.get_content(), self.win.content_overlay)
        library.attach_content()

    def test_the_shoulders_keep_the_focus_on_the_rail_when_it_is_there(self):
        self.show()
        self.shell.open_library("FC")
        self.pump()
        library = self.shell.library
        library.rail.focus_current()
        self.pump()
        self.assertTrue(library.step_console(1))
        self.pump()
        self.assertTrue(self.focus_widget().is_ancestor(library.rail))
        with mock.patch.object(library.rail, "move", return_value=False):
            self.assertFalse(library.step_console(1))

    def test_focus_lands_on_the_rail_when_the_page_has_no_games(self):
        self.show()
        self.shell.open_library(ALL_CONSOLES_ID)
        self.pump()
        library = self.shell.library
        with mock.patch.object(self.win.pages, "grid_for", return_value=None):
            self.assertTrue(library.focus_default())
        self.assertTrue(self.focus_widget().is_ancestor(library.rail))

    def test_the_search_sheet_toggles_and_respects_a_disabled_search(self):
        self.show()
        self.shell.open_library("SFC")
        self.pump()
        library = self.shell.library
        self.assertTrue(library.toggle_search())
        self.assertFalse(library.toggle_search())
        self.assertFalse(library.search_open)
        library.hide_search()  # already hidden: nothing to do
        self.win._set_search_enabled(False)
        self.assertFalse(library.show_search())
        self.win._set_search_enabled(True)
        # A query left in the box keeps the search bar on when the sheet goes.
        library.show_search()
        library.osk.type_char("c")
        library.hide_search()
        self.assertTrue(self.win.search_button.get_active())
        self.win.search_entry.set_text("")
        # No match on screen: the focus goes to the rail instead of a card.
        library.show_search()
        with mock.patch.object(self.win, "_visible_grid", return_value=None):
            library.hide_search()
        self.pump()
        self.assertTrue(self.focus_widget().is_ancestor(library.rail))
        # Typing with the bar closed opens it.
        self.win.search_button.set_active(False)
        library._on_search_typed("m")
        self.assertTrue(self.win.search_button.get_active())
        self.assertEqual(self.win.search_entry.get_text(), "m")
        self.win.search_entry.set_text("")


@needs_display
class TheShellCorners(BigPictureCase):
    def test_the_scale_falls_back_to_the_monitor_and_then_the_design(self):
        shell = self.shell
        with mock.patch.object(self.win, "get_height", return_value=0):
            with mock.patch.object(self.win, "get_surface", return_value=None):
                self.assertEqual(shell.scale(), 1.0)
            monitor = mock.Mock()
            monitor.get_geometry.return_value = mock.Mock(height=720)
            display = mock.Mock()
            display.get_monitor_at_surface.return_value = monitor
            with mock.patch.object(self.win, "get_surface", return_value=object()), mock.patch.object(
                self.win, "get_display", return_value=display
            ):
                self.assertEqual(shell.scale(), round(720 / 1080, 3))
        # The same scale twice is not reloaded.
        self.assertEqual(shell.apply_scale(), shell.apply_scale())
        self.assertEqual(shell._apply_scale_idle(), GLib.SOURCE_REMOVE)
        self.config.set_big_picture_text_size(150)
        self.assertNotEqual(shell.apply_scale(), shell.scale() / 1.5)
        shell.release()
        shell.release()
        self.assertIsNone(shell._provider)

    def test_the_status_shows_the_pad_the_task_and_the_clock(self):
        shell = self.shell
        nav = self.win.navigation
        pad, pad_label, task, task_label, clock = shell._status_boxes[0]
        self.assertFalse(pad.get_visible())
        nav.gamepad_connected = True
        nav.gamepad_name = ""
        shell.sync_status()
        self.assertTrue(pad.get_visible())
        self.assertEqual(pad_label.get_label(), self.said("big_picture.status.pad"))
        nav.gamepad_name = "Xbox pad"
        nav.on_gamepad_connected("Xbox pad")
        self.assertEqual(pad_label.get_label(), "Xbox pad")
        nav.on_gamepad_disconnected()
        self.assertFalse(pad.get_visible())
        self.assertFalse(task.get_visible())
        task_id = self.win.tasks.begin("scan", "Scanning", total=4)
        self.assertTrue(task.get_visible())
        self.assertIn("Scanning", task_label.get_label())
        self.win.tasks.finish(task_id)
        self.assertFalse(task.get_visible())
        self.assertEqual(len(clock.get_label()), 5)
        self.assertEqual(shell._on_clock(), GLib.SOURCE_CONTINUE)
        shell._start_clock()
        source = shell._clock_source
        shell._start_clock()
        self.assertEqual(shell._clock_source, source)
        shell._stop_clock()
        self.assertEqual(shell._clock_source, 0)

    def test_scope_changes_reach_the_rail_only_while_the_mode_is_on(self):
        shell = self.shell
        self.win.sidebar.select("FC")
        self.pump()
        self.assertEqual(shell.library.rail.current_id, "FC")
        self.leave()
        with mock.patch.object(shell.library.rail, "mark_current") as mark:
            shell.on_scope_changed("SFC")
        mark.assert_not_called()

    def test_pushing_a_page_already_on_the_stack_pops_back_to_it(self):
        shell = self.shell
        self.show()
        shell.open_library("SFC")
        self.pump()
        # A second page over the library, then the library asked for again.
        page = shell.library
        shell.push(page)  # already visible: only the focus
        self.pump()
        self.assertIs(shell.visible_page(), page)
        from openemux.ui.bigpicture.widgets import BigPage

        other = BigPage(shell, "Other", tag="bp-other")
        shell.push(other)
        self.pump()
        self.assertIs(shell.visible_page(), other)
        shell.push(page)
        self.pump()
        self.assertIs(shell.visible_page(), page)
        self.assertNotIn(other, shell._pushed)
        shell.go_home()
        self.pump()
        self.assertIs(shell.visible_page(), shell.home)
        # Nothing focused when the mode is off.
        self.leave()
        self.assertEqual(shell._focus_visible(), GLib.SOURCE_REMOVE)

    def test_open_library_without_a_scope_keeps_the_current_one(self):
        self.win.sidebar.select("FC")
        self.pump()
        self.assertTrue(self.shell.open_library())
        self.pump()
        self.assertEqual(self.win.current_console, "FC")
        self.assertIs(self.shell.visible_page(), self.shell.library)

    def test_the_quick_actions_that_open_pages(self):
        shell = self.shell
        for entry_id, name in (("import", "open_import"), ("covers", "open_covers"), ("settings", "open_settings")):
            with mock.patch.object(shell, name, return_value=True) as opener:
                self.assertTrue(shell.run_quick_action(entry_id))
            opener.assert_called_once()

    def test_counts_without_a_snapshot_and_a_pages_own_sections(self):
        shell = self.shell
        self.win._initial_roms.pop("FC", None)
        self.assertEqual(shell.game_count("FC"), 1)
        from openemux.ui.bigpicture.widgets import BigPage

        page = BigPage(shell, "Sections", tag="bp-sections")
        page.step_section = mock.Mock(return_value=True)
        shell.push(page)
        self.pump()
        self.assertTrue(shell.step_console(-1))
        page.step_section.assert_called_once_with(-1)
        shell.go_home()
        self.pump()

    def test_deleting_the_game_a_details_page_shows_pops_it(self):
        shell = self.shell
        self.show()
        rom = self.rom("SFC")
        shell.open_details(rom)
        self.pump()
        self.assertIs(shell.visible_page(), shell._details)
        # Another game going leaves the page alone.
        other = self.rom("SFC", 1)
        with mock.patch("openemux.ui.window.delete_rom"):
            self.win._delete_roms([other])
        self.pump()
        self.assertIs(shell.visible_page(), shell._details)
        with mock.patch("openemux.ui.window.delete_rom"):
            self.win._delete_roms([rom])
        self.pump()
        self.assertIsNot(shell.visible_page(), shell._details)
        # Nothing deleted: nothing popped either.
        shell.open_details(self.rom("FC"))
        self.pump()
        with mock.patch("openemux.ui.window.delete_rom", side_effect=__import__("openemux.core.rom_actions", fromlist=["RomActionError"]).RomActionError("no")):
            self.win._delete_roms([self.rom("FC")])
        self.pump()
        self.assertIs(shell.visible_page(), shell._details)

    def test_the_slide_follows_the_animation_setting(self):
        settings = Gtk.Settings.get_default()
        before = settings.get_property("gtk-enable-animations")
        try:
            settings.set_property("gtk-enable-animations", False)
            self.assertFalse(self.shell.nav.get_animate_transitions())
            settings.set_property("gtk-enable-animations", True)
            self.assertTrue(self.shell.nav.get_animate_transitions())
        finally:
            settings.set_property("gtk-enable-animations", before)
        with mock.patch.object(Gtk.Settings, "get_default", return_value=None):
            self.shell._sync_animations()
        self.assertTrue(self.shell.nav.get_animate_transitions())

    def test_the_windows_desktop_entry_points_lead_into_the_mode(self):
        shell = self.shell
        rom = self.rom("SFC")
        with mock.patch.object(shell, "open_search") as search:
            self.assertIsNone(self.win.open_onscreen_keyboard())
            self.win._toggle_search()
        self.assertEqual(search.call_count, 2)
        with mock.patch.object(shell, "open_settings") as settings:
            self.win._open_preferences(page="input", console="SFC")
        settings.assert_called_once_with("input", console="SFC")
        with mock.patch.object(shell, "open_details") as details:
            self.win.open_game_details(rom)
        details.assert_called_once_with(rom)

    def test_a_window_built_with_the_setting_on_opens_in_the_mode(self):
        from openemux.ui.window import OpenEmuxWindow

        self.config.set_big_picture_start(True)
        with mock.patch.object(OpenEmuxWindow, "fullscreen"), mock.patch.object(
            OpenEmuxWindow, "unfullscreen"
        ):
            win = OpenEmuxWindow(self.app)
            try:
                self.pump()
                self.assertTrue(win.big_picture)
            finally:
                win.emit("close-request")
                win.destroy()
        self.config.set_big_picture_start(False)

    def test_the_hints_with_no_visible_page(self):
        with mock.patch.object(self.shell, "visible_page", return_value=None):
            self.assertEqual(self.shell.context_for(None), navigation.CTX_BP_PAGE)
            self.assertEqual(self.shell.hints_for(navigation.CTX_BP_PAGE, {}), [])


if __name__ == "__main__":
    unittest.main()
