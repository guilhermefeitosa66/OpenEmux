"""Big Picture's pages: the games, the detail pane, Recent, Import (issue 957)."""

# Builds real windows through tests.window_harness (via BigPictureCase): CI runs this
# module in the windowed process, with the other window tests.

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.bigpicture_harness import BigPictureCase
from tests.gtk_display import HAVE_DISPLAY, needs_display

if HAVE_DISPLAY:
    from gi.repository import Gdk, GdkPixbuf, GLib, Gtk, Pango

    from openemux.core import library_facets
    from openemux.ui.bigpicture import file_browser as browser_module
    from openemux.ui.bigpicture import recent as recent_module
    from openemux.ui.scopes import ALL_CONSOLES_ID, FAVORITES_ID, RECENT_ID


@needs_display
class TheGamesPage(BigPictureCase):
    def open(self, scope="SFC"):
        self.show()
        self.shell.open_library(scope)
        self.pump()
        return self.shell.library

    def test_the_heading_the_chips_and_the_view(self):
        games = self.open("SFC")
        self.assertEqual(games.eyebrow_label.get_label(), "SNES")
        self.assertEqual(games.title_label.get_label(), self.win.sidebar.label_for("SFC"))
        self.assertEqual(games.count_label.get_label(), self.said("header.subtitle.games", count=2))
        self.assertNotIn(RECENT_ID, games.console_chips)
        self.assertEqual(games.console_chips[ALL_CONSOLES_ID].get_label(), self.said("big_picture.games.all"))
        self.assertEqual(games.console_chips["SFC"].get_label(), "SNES")
        self.assertTrue(games.console_chips["SFC"].has_css_class("bp-current"))
        self.assertEqual(games.view_label.get_label(), self.said("big_picture.view.cartridge"))
        self.assertTrue(games.segments.buttons["cartridge"].has_css_class("bp-current"))
        games.select_scope(ALL_CONSOLES_ID)
        self.pump()
        self.assertEqual(games.eyebrow_label.get_label(), self.said("big_picture.games.eyebrow.all").upper())
        self.assertEqual(games.title_label.get_label(), self.said("big_picture.shelf.all_games"))
        games.select_scope("FC")
        self.pump()
        self.assertEqual(games.count_label.get_label(), self.said("header.subtitle.one_game"))
        self.assertTrue(games.select_scope("FC"))  # already there

    def test_favorites_and_playlists_have_their_own_heading(self):
        self.win._toggle_favorite_from_ui(self.rom("SFC"))
        self.pump()
        slug = self.win.collection_manager.create("Couch")
        self.win.collection_manager.add(slug, [self.rom("SFC")["path"]])
        self.win.refresh_library()
        self.pump()
        games = self.open(FAVORITES_ID)
        self.assertEqual(games.eyebrow_label.get_label(), self.said("big_picture.games.eyebrow.favorites").upper())
        playlist = next(scope for scope in games.chip_scopes() if scope.startswith("col:"))
        games.select_scope(playlist)
        self.pump()
        self.assertEqual(games.eyebrow_label.get_label(), self.said("big_picture.shelf.playlist").upper())
        self.assertEqual(games.console_chips[playlist].get_label(), "Couch")

    def test_the_shoulders_walk_the_chips_and_the_focus_stays_in_the_grid(self):
        games = self.open("SFC")
        ids = games.chip_scopes()
        index = ids.index("SFC")
        grid = self.win.pages.grid_for("SFC")
        self.pump_until(lambda: grid.card_for(grid.entries()[0]) is not None)
        grid.focus_first_card()
        self.pump()
        with mock.patch.object(self.win.navigation, "_cmd_focus_grid") as focus_grid:
            self.assertTrue(self.shell.step_console(1))
            self.pump()
        focus_grid.assert_called()
        self.assertEqual(self.win.current_console, ids[(index + 1) % len(ids)])
        self.assertTrue(games.console_chips[self.win.current_console].has_css_class("bp-current"))
        self.assertTrue(self.shell.step_console(-1))
        self.pump()
        self.assertEqual(self.win.current_console, "SFC")
        with mock.patch.object(games, "chip_scopes", return_value=["SFC"]):
            self.assertFalse(games.step_section(1))
        with mock.patch.object(games, "chip_scopes", return_value=[]):
            self.assertFalse(games.step_section(1))
        games.console_chips["FC"].emit("clicked")
        self.pump()
        self.assertEqual(self.win.current_console, "FC")
        unallocated = mock.Mock()
        unallocated.get_allocation.return_value = mock.Mock(width=0)
        self.assertIsNone(games._scroll_chip_into_view(unallocated))

    def test_the_filter_chips_count_and_filter(self):
        games = self.open("SFC")
        rom = self.rom("SFC")
        self.win._toggle_favorite_from_ui(rom)
        self.pump()
        games.sync()
        chip = games.facet_chips[library_facets.FAVORITES]
        self.assertEqual(
            chip.get_label(),
            self.said("big_picture.facet.count", name=self.said("big_picture.facet.favorites"), count=1),
        )
        self.assertIsNone(games.facet_filter())
        chip.emit("clicked")
        self.pump()
        self.assertTrue(chip.is_on())
        grid = self.win.pages.grid_for("SFC")
        self.assertTrue(self.pump_until(lambda: grid.count() == 1))
        key, predicate = games.facet_filter()
        self.assertTrue(predicate(rom))
        self.assertFalse(predicate(self.rom("SFC", 1)))
        self.assertEqual(self.shell.facet_filter()[0], key)
        self.assertFalse(games.set_facets({library_facets.FAVORITES}))  # no change
        chip.emit("clicked")
        self.pump()
        self.assertTrue(self.pump_until(lambda: grid.count() == 2))
        games.filter_button.emit("clicked")
        self.assertFalse(games.facets_scroller.get_visible())
        games.toggle_filters()
        self.assertTrue(games.facets_scroller.get_visible())
        # Leaving the mode drops the chips.
        games.toggle_facet(library_facets.NEVER_PLAYED)
        self.leave()
        self.assertEqual(games.active_facets, frozenset())
        self.assertIsNone(self.shell.facet_filter())

    def test_the_facts_without_a_grid(self):
        games = self.open("SFC")
        with mock.patch.object(self.win.pages, "grid_for", return_value=None):
            self.assertEqual(games._scope_roms(), [])

    def test_the_view_switch_is_big_pictures_own(self):
        games = self.open("SFC")
        desktop_view = self.config.get_display_settings("SFC")["view_mode"]
        self.assertFalse(games.set_view("cartridge"))
        games.segments.buttons["list"].emit("clicked")
        self.pump()
        self.assertEqual(self.config.get_big_picture_settings()["view_mode"], "list")
        self.assertEqual(self.win.display_settings_for("SFC")["view_mode"], "list")
        self.assertEqual(games.view_label.get_label(), self.said("big_picture.view.list"))
        self.assertEqual(self.config.get_display_settings("SFC")["view_mode"], desktop_view)
        games.set_view("cover")
        self.assertEqual(games._art_kind(), "covers")
        self.leave()
        self.assertEqual(self.win.display_settings_for("SFC")["view_mode"], desktop_view)

    def test_a_game_shows_in_the_pane_and_b_goes_back_to_the_grid(self):
        games = self.open("SFC")
        self.assertEqual(games.pane_stack.get_visible_child_name(), "empty")
        rom = self.rom("SFC")
        grid = self.win.pages.grid_for("SFC")
        self.pump_until(lambda: grid.card_for(grid.entries()[0]) is not None)
        grid.focus_first_card()
        self.pump()
        self.press("confirm")
        self.assertEqual(games.pane_stack.get_visible_child_name(), "game")
        self.assertIsNotNone(games.detail.rom)
        self.assertTrue(games.pane_has_focus())
        self.assertEqual(games.context_for(self.focus_widget()), "bp-pane")
        hints = games.hints(self.win.navigation.glyphs(), self.win.t)
        self.assertEqual(hints[0][1], self.said("details.play"))
        with mock.patch.object(self.win, "_toggle_favorite_from_ui") as favorite:
            self.press("context")
        favorite.assert_called_once()
        with mock.patch.object(self.win, "share_roms") as share:
            self.press("favorite")
        share.assert_called_once()
        self.press("back")
        self.assertFalse(games.pane_has_focus())
        self.assertIs(self.visible_page(), games)
        self.assertFalse(games.on_pad_action("context"))
        self.assertFalse(games.handle_back())
        # The game going away empties the pane.
        games.show_game(rom)
        self.pump()
        games.forget_games({"/somewhere/else"})
        self.assertEqual(games.pane_stack.get_visible_child_name(), "game")
        self.shell.forget_games({games.detail.rom["path"]})
        self.pump()
        self.assertEqual(games.pane_stack.get_visible_child_name(), "empty")
        # Elsewhere than the games page, a game opens expanded.
        self.shell.go_home()
        self.pump()
        self.shell.show_game(rom)
        self.pump()
        self.assertIs(self.visible_page(), self.shell._details)
        self.shell.forget_games({rom["path"]})
        self.pump()
        self.assertIsNot(self.visible_page(), self.shell._details)

    def test_y_opens_the_options_sheet(self):
        games = self.open("SFC")
        rom = self.rom("SFC")
        games.open_options(rom)
        self.pump()
        chooser = self.shell._chooser
        self.assertIs(self.visible_page(), chooser)
        self.assertEqual([row.option_id for row in chooser.rows],
                         ["share", "rename", "artwork", "core", "playlists", "remove"])
        with mock.patch.object(self.win, "share_roms") as share:
            next(row for row in chooser.rows if row.option_id == "share").emit("clicked")
            self.pump()
        share.assert_called_once()
        games.open_options(rom)
        self.pump()
        with mock.patch.object(self.win, "_confirm_delete_roms") as delete:
            next(row for row in self.shell._chooser.rows if row.option_id == "remove").emit("clicked")
            self.pump()
        delete.assert_called_once()

    def test_the_focus_lands_on_a_chip_when_there_are_no_games(self):
        games = self.open("SFC")
        with mock.patch.object(self.win.pages, "grid_for", return_value=None):
            self.assertTrue(games.focus_default())
        self.assertIs(self.focus_widget(), games.console_chips["SFC"])
        with mock.patch.object(self.win.pages, "grid_for", return_value=None), mock.patch.object(
            games, "console_chips", {}
        ):
            self.assertTrue(games.focus_default())
        self.assertIs(self.focus_widget(), games.back_button)
        games.back_button.emit("clicked")
        self.pump()
        self.assertIs(self.visible_page(), self.shell.shelf)

    def test_attaching_twice_and_detaching_twice_are_harmless(self):
        games = self.shell.library
        games.attach_content()
        self.assertIs(self.win.content_overlay.get_parent(), games.content_host)
        self.leave()
        games.detach_content()
        self.assertIs(self.win.content_toolbar.get_content(), self.win.content_overlay)

    def test_the_hints(self):
        games = self.open("SFC")
        g = dict(self.win.navigation.glyphs(), search="View", select="Menu")
        self.assertEqual(games.hints(g, self.win.t)[1][1], self.said("big_picture.hints.shelf"))
        grid = games.grid_hints(g, self.win.t)
        self.assertEqual(grid[0][1], self.said("big_picture.hints.details"))
        self.assertEqual(grid[2][1], self.said("big_picture.hints.options"))
        self.assertEqual(grid[4], ("Menu", self.said("big_picture.hints.select")))


@needs_display
class TheSearch(BigPictureCase):
    def test_the_keyboard_types_into_the_search_box(self):
        self.show()
        self.shell.open_library("SFC")
        self.pump()
        games = self.shell.library
        self.assertTrue(self.shell.open_search())
        self.pump()
        self.assertTrue(self.shell.search_open)
        self.win.search_button.set_active(False)
        self.shell.osk.type_char("C")
        self.assertEqual(self.win.search_entry.get_text(), "c")
        self.assertTrue(self.win.search_button.get_active())
        self.assertTrue(games.search_label.get_visible())
        self.assertEqual(games.search_label.get_label(), self.said("big_picture.games.searching", query="c"))
        # A real keyboard types too, while the keyboard shows.
        self.assertTrue(self.shell._on_sheet_key(None, Gdk.KEY_h, 0, 0))
        self.assertEqual(self.win.search_entry.get_text(), "ch")
        self.assertTrue(self.shell._on_sheet_key(None, Gdk.KEY_BackSpace, 0, 0))
        self.assertEqual(self.win.search_entry.get_text(), "c")
        self.assertFalse(self.shell._on_sheet_key(None, Gdk.KEY_h, 0, Gdk.ModifierType.CONTROL_MASK))
        self.assertFalse(self.shell._on_sheet_key(None, Gdk.KEY_Up, 0, 0))
        self.shell.osk.handle_action("search")  # Start: done
        self.pump()
        self.assertFalse(self.shell.search_open)
        # Asked again while open, it closes.
        self.shell.show_search()
        self.assertFalse(self.shell.open_search())
        self.assertFalse(self.shell.search_open)
        # From the Shelf: All games first, then the keyboard.
        self.shell.go_home()
        self.pump()
        self.assertTrue(self.shell.open_search())
        self.pump()
        self.assertIs(self.visible_page(), games)
        self.assertEqual(self.win.current_console, ALL_CONSOLES_ID)
        self.assertTrue(self.shell.search_open)
        self.assertTrue(self.shell.handle_back())
        self.assertFalse(self.shell.search_open)
        # An empty search lets the search button go.
        self.shell.show_search()
        self.shell.osk.clear()
        self.shell.hide_search()
        self.assertFalse(self.win.search_button.get_active())
        self.shell.hide_search()  # already hidden

    def test_a_disabled_search_opens_nothing(self):
        self.win.search_entry.set_sensitive(False)
        try:
            self.assertFalse(self.shell.open_search())
        finally:
            self.win.search_entry.set_sensitive(True)


@needs_display
class TheGameGridOnlyScrollsDown(BigPictureCase):
    """Sideways is the chips', never the games' (issue 954)."""

    LONG = "Zelda no Densetsu - Kamigami no Triforce, a very long title (Japan) (Rev 1)"
    # Short titles first, so the grid measures its columns off a short card
    # and only meets the long one further down -- the order that overflowed.
    library = {
        "SFC": [f"A{i:02d}.sfc" for i in range(30)] + [f"{LONG}.sfc"],
        "GBA": ["Short.gba"],
    }

    def test_a_long_title_never_widens_the_columns_past_the_screen(self):
        self.show()
        self.shell.open_library("SFC")
        grid = self.win.pages.grid_for("SFC")

        def long_card():
            for card in grid._bound.values():
                if card.name_label.get_label().startswith("Zelda"):
                    return card
            return None

        self.assertTrue(self.pump_until(lambda: long_card() is not None and grid.get_width() > 0))
        self.pump()
        card = long_card()
        self.assertLessEqual(
            card.measure(Gtk.Orientation.HORIZONTAL, -1)[0], grid._card_allocation_width()
        )
        adjustment = grid.get_hadjustment()
        self.assertLessEqual(adjustment.get_upper(), adjustment.get_page_size() + 0.5)
        self.assertEqual(adjustment.get_value(), 0)
        self.assertEqual(card.name_label.get_ellipsize(), Pango.EllipsizeMode.END)

    def test_the_desktop_keeps_its_titles_whole(self):
        self.leave()
        self.assertNotIn("big_picture", self.win.display_settings_for("SFC"))
        grid = self.show_with_cards("SFC")
        card = next(iter(grid._bound.values()))
        self.assertEqual(card.name_label.get_ellipsize(), Pango.EllipsizeMode.NONE)


@needs_display
class TheRecentTab(BigPictureCase):
    def test_nothing_played_shows_the_empty_state(self):
        self.show()
        page = self.shell.open_recent()
        self.pump()
        self.assertEqual(page.rows, [])
        self.assertTrue(page.empty.get_visible())
        self.assertTrue(page.focus_default())
        self.assertEqual(page.hints(self.win.navigation.glyphs(), self.win.t)[0][1],
                         self.said("big_picture.hints.details"))

    def test_the_played_games_newest_first_and_a_opens_one(self):
        first, second = self.rom("SFC"), self.rom("SFC", 1)
        self.win.play_history.record_launch(first["path"])
        self.win.play_history.record_launch(second["path"])
        self.show()
        page = self.shell.open_recent()
        self.pump()
        self.assertEqual({row.rom["path"] for row in page.rows}, {second["path"], first["path"]})
        self.assertFalse(page.empty.get_visible())
        self.assertTrue(page.focus_default())
        self.assertIs(self.focus_widget(), page.rows[0])
        page.refresh()  # rebuilt over the rows it had
        self.assertEqual(len(page.rows), 2)
        page.rows[0].emit("clicked")
        self.pump()
        self.assertIs(self.visible_page(), self.shell._details)
        with mock.patch.object(page, "refresh") as refresh:
            self.shell.on_library_changed()
        refresh.assert_called_once()

    def test_the_picture_is_the_latest_state_or_the_art(self):
        rom = self.rom("SFC")
        states = Path(self.config.get_console_states_dir("SFC"))
        states.mkdir(parents=True, exist_ok=True)
        self.assertIsNone(recent_module.latest_picture(self.win, rom))
        stem = Path(rom["path"]).stem
        (states / f"{stem}.state1").write_text("x")
        png = states / f"{stem}.state1.png"
        pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, 8, 8)
        pixbuf.savev(str(png), "png", [], [])
        self.assertEqual(recent_module.latest_picture(self.win, rom), png)
        row = recent_module.RecentRow(rom, "x", lambda r: None)
        row.show_pixbuf(None)
        self.assertIsNone(row.picture.get_paintable())
        row.show_pixbuf(pixbuf)
        self.assertIsNotNone(row.picture.get_paintable())
        self.assertEqual(recent_module.RecentPage._apply(row, None), GLib.SOURCE_REMOVE)


@needs_display
class TheImportTab(BigPictureCase):
    def test_the_buttons_and_the_formats(self):
        self.show()
        page = self.shell.open_import()
        self.pump()
        self.assertTrue(page.focus_default())
        self.assertIs(self.focus_widget(), page.files_button)
        labels = [row.extensions_label.get_label() for row in page.format_rows]
        self.assertTrue(all(".zip" in label for label in labels))
        with mock.patch.object(self.win, "receive_games") as receive:
            page.receive_button.emit("clicked")
        receive.assert_called_once()
        with mock.patch.object(self.shell, "open_browser") as open_browser:
            page.files_button.emit("clicked")
            page.folder_button.emit("clicked")
        self.assertEqual([c.args[0] for c in open_browser.call_args_list], ["files", "folder"])
        with mock.patch.object(self.win.imports, "begin") as begin:
            self.assertFalse(page.import_paths([]))
            self.assertTrue(page.import_paths([Path("/x/a.sfc")]))
        begin.assert_called_once_with(["/x/a.sfc"], detect=True)
        self.assertEqual(page.hints(self.win.navigation.glyphs(), self.win.t)[2][1],
                         self.said("big_picture.hints.tabs"))

    def test_a_console_without_an_icon_gets_the_generic_one(self):
        from openemux.ui.bigpicture import import_page

        with mock.patch.object(import_page, "console_texture", return_value=None):
            row = import_page.FormatRow({"id": "SFC", "display_name": "Super Nintendo", "extensions": ["sfc"]})
        self.assertIsInstance(row.get_first_child(), Gtk.Image)


@needs_display
class TheFileBrowser(BigPictureCase):
    def setUp(self):
        super().setUp()
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        root = self.root = Path(self.dir.name)
        (root / "Sub").mkdir()
        (root / "Sub" / "Inner.gba").write_text("x")
        (root / "One.sfc").write_text("x")
        (root / "Two.sfc").write_text("x")
        (root / "notes.txt").write_text("x")

    def open(self, mode):
        self.show()
        picked = []
        page = self.shell.open_browser(mode, picked.append)
        page.open(mode, picked.append, folder=str(self.root))
        self.pump()
        return page, picked

    def test_files_are_marked_and_imported(self):
        page, picked = self.open("files")
        self.assertEqual([row.entry.name for row in page.rows], ["Sub", "One.sfc", "Two.sfc"])
        self.assertEqual(page.path_label.get_label(), str(self.root))
        one, two = page.rows[1], page.rows[2]
        one.emit("clicked")  # A on a file marks it
        self.assertTrue(one.mark.get_visible())
        one.grab_focus()
        self.press("context")  # X unmarks the focused one
        self.assertFalse(one.mark.get_visible())
        self.assertFalse(page.toggle_mark(page.rows[0]))  # a folder is not marked
        self.assertFalse(page.toggle_mark(None))
        two.emit("clicked")
        self.press("favorite")  # Y imports what is marked
        self.assertEqual(picked, [[two.entry.path]])
        self.assertIsNot(self.visible_page(), page)

    def test_y_with_nothing_marked_imports_the_focused_file(self):
        page, picked = self.open("files")
        page.rows[0].grab_focus()
        self.assertFalse(page.confirm())  # a folder
        with mock.patch.object(self.win, "get_focus", return_value=None):
            self.assertFalse(page.confirm())
        page.rows[1].grab_focus()
        self.assertTrue(page.confirm())
        self.assertEqual(picked, [[page.rows[1].entry.path]])

    def test_folders_are_entered_and_b_goes_up_then_closes(self):
        page, picked = self.open("folder")
        self.assertEqual([row.entry.name for row in page.rows], ["Sub"])  # no files when picking a folder
        page.rows[0].emit("clicked")
        self.pump()
        self.assertEqual(page.folder, self.root / "Sub")
        self.assertEqual(page.rows, [])
        self.assertTrue(page.empty.get_visible())
        self.assertFalse(page.focus_default())
        self.press("back")
        self.assertEqual(page.folder, self.root)
        self.assertTrue(self.pump_until(lambda: self.focus_widget() is page.rows[0]))
        self.assertFalse(page.handle_back())  # where it opened: B closes it
        hints = page.hints(self.win.navigation.glyphs(), self.win.t)
        self.assertEqual(hints[1][1], self.said("big_picture.browser.import_folder"))
        self.assertTrue(page.on_pad_action("favorite"))
        self.assertEqual(picked, [[self.root]])
        self.assertFalse(page.on_pad_action("range"))

    def test_the_root_has_no_parent_and_the_start_folder(self):
        page, _picked = self.open("files")
        self.assertEqual(page.hints(self.win.navigation.glyphs(), self.win.t)[1][1],
                         self.said("big_picture.browser.mark"))
        page.folder = self.root / "Sub"
        with mock.patch.object(browser_module.pad_browser, "parent", return_value=None):
            self.assertFalse(page.handle_back())
        page.folder = None
        self.assertFalse(page.handle_back())
        page.open("files", None)
        self.assertEqual(page.start, browser_module.pad_browser.start_folder(self.config.get_roms_path()))
        page.mode = "folder"
        self.assertTrue(page.confirm())


if __name__ == "__main__":
    unittest.main()
