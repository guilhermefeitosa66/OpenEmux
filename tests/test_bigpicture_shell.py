"""Big Picture's shell: the way in and out, the tabs, the Shelf, the hints (issues 914, 957)."""

# Builds real windows through tests.window_harness (via BigPictureCase): CI runs this
# module in the windowed process, with the other window tests.

import unittest
from unittest import mock

from tests.bigpicture_harness import BigPictureCase
from tests.gtk_display import HAVE_DISPLAY, needs_display

if HAVE_DISPLAY:
    from gi.repository import Adw, Gdk, GLib, Gtk

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
        # The desktop's page stack is under the chips now.
        self.assertIs(self.win.content_overlay.get_parent(), shell.library.content_host)
        self.assertEqual(self.win._zoom, 2.0)  # the largest zoom, the games alone on the page

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
class TheTabs(BigPictureCase):
    def test_the_shelf_is_the_first_page_and_the_shoulders_walk_the_tabs(self):
        shell = self.shell
        self.show()
        self.assertIs(self.visible_page(), shell.shelf)
        self.assertEqual(shell.tab, "library")
        self.assertTrue(shell.rail.buttons["library"].has_css_class("bp-current"))
        self.assertTrue(shell.is_root())
        self.assertTrue(shell.step_console(1))
        self.pump()
        self.assertEqual(shell.tab, "recent")
        self.assertIs(self.visible_page(), shell._recent)
        self.assertTrue(shell.rail.buttons["recent"].has_css_class("bp-current"))
        self.assertTrue(shell.step_console(1))
        self.pump()
        self.assertIs(self.visible_page(), shell._import)
        self.assertTrue(shell.step_console(1))
        self.pump()
        self.assertIs(self.visible_page(), shell._settings)
        self.assertTrue(shell.step_console(1))  # wraps
        self.pump()
        self.assertIs(self.visible_page(), shell.shelf)
        self.assertTrue(shell.step_console(-1))
        self.pump()
        self.assertEqual(shell.tab, "settings")
        self.assertFalse(shell.switch_tab("nowhere"))
        # A tab of the rail, clicked.
        shell.rail.buttons["recent"].emit("clicked")
        self.pump()
        self.assertEqual(shell.tab, "recent")
        # B on another tab's first page goes to the Library; on the Shelf, nowhere.
        self.assertTrue(shell.handle_back())
        self.pump()
        self.assertIs(self.visible_page(), shell.shelf)
        self.assertFalse(shell.handle_back())
        self.assertTrue(self.win.big_picture)

    def test_switching_tabs_drops_the_pages_pushed_over_the_last_one(self):
        shell = self.shell
        self.show()
        shell.open_library("SFC")
        self.pump()
        self.assertIs(self.visible_page(), shell.library)
        self.assertFalse(shell.is_root())
        shell.open_recent()
        self.pump()
        self.assertIs(self.visible_page(), shell._recent)
        self.assertEqual(shell.nav.get_navigation_stack().get_n_items(), 1)
        shell.open_import()
        self.pump()
        self.assertIs(self.visible_page(), shell._import)
        # A tab asked for while already showing alone is left as it is.
        shell.switch_tab("import")
        self.pump()
        self.assertIs(self.visible_page(), shell._import)
        # The library opened from another tab comes back to the Library tab.
        shell.open_library("FC")
        self.pump()
        self.assertEqual(shell.tab, "library")
        self.assertIs(self.visible_page(), shell.library)
        self.assertTrue(shell.handle_back())
        self.pump()
        self.assertIs(self.visible_page(), shell.shelf)

    def test_the_rail_has_focus_hints_and_retranslates(self):
        shell = self.shell
        self.show()
        self.assertTrue(shell.rail.focus_current())
        self.assertEqual(self.win.navigation.current_context(), navigation.CTX_BP_RAIL)
        self.assertEqual(shell.rail.neighbour(-1), "settings")
        shell.rail.retranslate(lambda key: key.upper())
        self.assertEqual(shell.rail.buttons["library"].label.get_label(), "BIG_PICTURE.TAB.LIBRARY")

    def test_the_rail_is_slim(self):
        # Issue 975: well under half the width it had (232 px at 1080p), the
        # labels still whole and the pause menu's icons left as they were.
        self.show()
        # The test window is small, so the labels, not the theme's minimum,
        # set the width here: it must still be under the old rail's half at
        # 1080p (plus a gap of slack), never near the 232 px it was.
        scale = max(self.shell.apply_scale(), 1.0)
        natural = self.shell.rail.measure(Gtk.Orientation.HORIZONTAL, -1)[1]
        self.assertLess(natural, 232 * scale / 2 + theme.px("gap", scale))
        self.assertLessEqual(theme.SIZES["rail_width"], 232 // 2)
        self.assertEqual(theme.SIZES["pause_icon"], 34)
        for button in (*self.shell.rail.buttons.values(), self.shell.rail.desktop):
            self.assertEqual(button.label.get_layout().get_unknown_glyphs_count(), 0)
            self.assertFalse(button.label.get_layout().is_ellipsized())

    def test_back_to_desktop_on_the_rail_leaves_the_mode(self):
        # Issue 978: Down from Settings reaches it; A leaves, as Guide does.
        shell = self.shell
        self.show()
        shell.switch_tab("settings", focus=False)
        self.pump()
        self.assertTrue(shell.rail.focus_current())
        glyphs = self.win.navigation.glyphs()
        self.assertEqual(shell.hints_for(navigation.CTX_BP_RAIL, glyphs)[0][1], self.said("big_picture.hints.open"))
        self.press("down")
        self.assertIs(self.focus_widget(), shell.rail.desktop)
        self.assertEqual(self.win.navigation.current_context(), navigation.CTX_BP_RAIL)
        # A says it leaves, not "Open", and the bar is redrawn on the way in.
        self.assertEqual(shell.hints_for(navigation.CTX_BP_RAIL, glyphs)[0][1], self.said("big_picture.tab.desktop"))
        labels = [slot[2].get_label() for slot in shell.hint_bar.slots if slot[0].get_visible()]
        self.assertIn(self.said("big_picture.tab.desktop"), labels)
        self.assertEqual(shell.tab, "settings")
        self.press("confirm")
        # A button's activate clicks it a moment later, by the clock.
        self.pump_until(lambda: not self.win.big_picture)
        self.assertFalse(self.win.big_picture)
        self.assertEqual(self.win.mode_stack.get_visible_child_name(), "desktop")
        self.assertIn(self.said("big_picture.toast.off"), self.toasts)


@needs_display
class TheShelf(BigPictureCase):
    def test_a_card_per_scope_in_its_console_color(self):
        shelf = self.shell.shelf
        ids = [card.scope_id for card in shelf.cards]
        self.assertEqual(ids[0], ALL_CONSOLES_ID)
        self.assertNotIn(RECENT_ID, ids)
        self.assertIn("SFC", ids)
        sfc = next(card for card in shelf.cards if card.scope_id == "SFC")
        self.assertTrue(sfc.has_css_class("bp-shelf-sfc"))
        self.assertEqual(sfc.eyebrow_label.get_label(), "SNES")
        self.assertEqual(sfc.count_label.get_label(), self.said("header.subtitle.games", count=2))
        fc = next(card for card in shelf.cards if card.scope_id == "FC")
        self.assertEqual(fc.count_label.get_label(), self.said("header.subtitle.one_game"))
        first = shelf.cards[0]
        self.assertTrue(first.has_css_class("bp-shelf-all"))
        self.assertEqual(first.name_label.get_label(), self.said("big_picture.shelf.all_games"))
        self.assertEqual(
            shelf.heading.subtitle_label.get_label(),
            self.said("big_picture.shelf.summary", consoles=2, games=self.said("header.subtitle.games", count=3)),
        )
        # Three to a row.
        self.assertEqual(shelf.grid.get_child_at(0, 0), shelf.cards[0])
        self.assertEqual(shelf.grid.get_child_at(0, 1), shelf.cards[3] if len(shelf.cards) > 3 else None)

    def test_favorites_and_playlists_are_cards_too(self):
        self.win._toggle_favorite_from_ui(self.rom("SFC"))
        self.pump()
        slug = self.win.collection_manager.create("Couch")
        self.win.collection_manager.add(slug, [self.rom("SFC")["path"]])
        self.win.refresh_library(force=True)
        self.pump()
        shelf = self.shell.shelf
        shelf.refresh()
        kinds = {card.scope_id: card.style_kind for card in shelf.cards}
        self.assertEqual(kinds[FAVORITES_ID], "favorites")
        self.assertIn("collection", kinds.values())
        playlist = next(card for card in shelf.cards if card.style_kind == "collection")
        self.assertEqual(playlist.eyebrow_label.get_label(), self.said("big_picture.shelf.playlist"))

    def test_a_card_opens_its_games_and_the_header_buttons_work(self):
        shelf = self.shell.shelf
        self.show()
        self.assertTrue(shelf.focus_default())
        self.assertIs(self.focus_widget(), shelf.cards[0])
        card = next(card for card in shelf.cards if card.scope_id == "SFC")
        card.emit("clicked")
        self.pump()
        self.assertIs(self.visible_page(), self.shell.library)
        self.assertEqual(self.win.current_console, "SFC")
        self.shell.go_home()
        self.pump()
        with mock.patch.object(self.shell, "open_search") as search:
            shelf.search_button.emit("clicked")
        search.assert_called_once()
        shelf.import_button.emit("clicked")
        self.pump()
        self.assertEqual(self.shell.tab, "import")
        # Y: the console order, in Settings.
        self.shell.go_home()
        self.pump()
        self.assertFalse(shelf.on_pad_action("context"))
        self.assertTrue(shelf.on_pad_action("favorite"))
        self.pump()
        self.assertEqual(self.shell.tab, "settings")
        self.assertEqual(self.shell._settings.current, "roms")
        # With no consoles, the Import button takes the focus.
        with mock.patch.object(shelf, "cards", []):
            self.assertTrue(shelf.focus_default() is not None)

    def test_a_rebuild_keeps_the_focus_on_its_card(self):
        # A scan or a sync ending rebuilds the cards under the pad (issue 957).
        shelf = self.shell.shelf
        self.show()
        card = next(card for card in shelf.cards if card.scope_id == "SFC")
        card.grab_focus()
        self.pump()
        shelf.refresh()
        self.pump()
        self.assertEqual(self.focus_widget().scope_id, "SFC")
        self.assertIsNot(self.focus_widget(), card)
        # Its scope gone: the first card.
        scopes = [scope for scope in self.shell.library_scopes() if scope != "SFC"]
        with mock.patch.object(self.shell, "library_scopes", return_value=scopes):
            shelf.refresh()
        self.pump()
        self.assertIs(self.focus_widget(), shelf.cards[0])
        # Not on a card: the focus is left where it is.
        shelf.import_button.grab_focus()
        shelf.refresh()
        self.assertIs(self.focus_widget(), shelf.import_button)

    def test_console_art_is_drawn_at_a_whole_multiple(self):
        # Issue 964: the pixel art in the shelf's art box, nearest-neighbour
        # at a whole multiple (issue 962's PixelIcon), never stretched.
        from gi.repository import Gsk

        from openemux.ui.bigpicture.shelf import ShelfCard
        from openemux.ui.bigpicture.widgets import PixelIcon

        sfc = next(card for card in self.shell.shelf.cards if card.scope_id == "SFC")
        self.assertIsInstance(sfc.art, PixelIcon)
        self.assertTrue(sfc.art.has_css_class("bp-shelf-art"))
        self.assertFalse(sfc.art.has_css_class("bp-chip-art"))
        self.assertFalse(sfc.art.get_hexpand())
        size = sfc.art.textures[0].get_width()
        snapshot = Gtk.Snapshot()
        with mock.patch.object(sfc.art, "get_width", return_value=size * 2 + 8), \
                mock.patch.object(sfc.art, "get_height", return_value=size * 2 + 8):
            sfc.art.do_snapshot(snapshot)
        node = snapshot.to_node()
        self.assertIsInstance(node, Gsk.TextureScaleNode)
        self.assertEqual(node.get_filter(), Gsk.ScalingFilter.NEAREST)
        bounds = node.get_bounds()
        self.assertEqual((bounds.get_x(), bounds.get_width()), (4, size * 2))
        # The library cards keep a symbolic icon, centred in the art box.
        first = self.shell.shelf.cards[0]
        self.assertIsInstance(first.art, Gtk.CenterBox)
        self.assertTrue(first.art.has_css_class("bp-shelf-art"))
        self.assertIsInstance(first.art.get_center_widget(), Gtk.Image)
        # A console with no art at all: the generic pad glyph.
        bare = ShelfCard("XX", "XX", "Unknown", "", textures=(None, None))
        self.assertIsInstance(bare.art, Gtk.CenterBox)
        self.assertEqual(bare.art.get_center_widget().get_icon_name(), "input-gaming-symbolic")

    def test_every_console_name_fits_on_one_line(self):
        # Issue 964: at 1920x1080 and 2560x1440 the text column of a card is
        # wider than every shipped console name, set in the card's name font.
        from gi.repository import Pango

        from openemux.core.systems import SYSTEMS, get_system_display_name
        from openemux.ui.bigpicture.shelf import COLUMNS, GRID_SPACING

        label = self.shell.shelf.cards[0].name_label
        font = label.get_pango_context().get_font_description().copy()
        font.set_weight(Pango.Weight.BOLD)
        names = [get_system_display_name(system["id"]) for system in SYSTEMS]
        self.assertIn("Famicom Disk System", names)
        for width, height in ((1920, 1080), (2560, 1440)):
            scale = theme.scale_for(height)
            s = lambda name, scale=scale: theme.px(name, scale)  # noqa: E731
            content = width - s("rail_width") - s("safe_x") - GRID_SPACING * (COLUMNS - 1)
            column = content // COLUMNS - 2 * s("shelf_pad_x") - s("shelf_art") - s("shelf_gap")
            font.set_absolute_size(s("shelf_name") * Pango.SCALE)
            for name in names:
                layout = label.create_pango_layout(name)
                layout.set_font_description(font)
                self.assertLess(layout.get_pixel_size()[0], column, f"{name} at {width}x{height}")

    def test_recently_played_has_a_tab_not_a_card(self):
        self.win.play_history.record_launch(self.rom("SFC")["path"])
        self.win.refresh_library()
        self.pump()
        self.assertIn(RECENT_ID, self.shell.library_scopes())
        self.shell.shelf.refresh()
        self.assertNotIn(RECENT_ID, [card.scope_id for card in self.shell.shelf.cards])
        self.assertEqual(self.shell.game_count(RECENT_ID), 1)

    def test_a_pad_connecting_reaches_the_shell(self):
        with mock.patch.object(self.shell, "sync_status") as sync:
            self.win.navigation.on_gamepad_connected("Pad")
        sync.assert_called()
        self.leave()
        self.shell.on_library_changed()  # inert while the mode is off

    def test_counts_and_hints(self):
        shell = self.shell
        self.assertEqual(shell.game_count("SFC"), 2)
        self.assertEqual(shell.game_count(ALL_CONSOLES_ID), 3)
        self.assertEqual(shell.game_count(FAVORITES_ID), 0)
        self.assertEqual(shell.game_count(RECENT_ID), 0)
        self.win._initial_roms.pop("FC", None)
        self.assertEqual(shell.game_count("FC"), 1)
        glyphs = dict(self.win.navigation.glyphs(), search="View", select="Menu")
        hints = shell.shelf.hints(glyphs, self.win.t)
        self.assertEqual(hints[1], (glyphs["favorite"], self.said("big_picture.hints.order")))
        self.assertEqual(hints[2], ("View", self.said("hints.search")))


@needs_display
class TheNavigatorInBigPicture(BigPictureCase):
    def test_contexts_follow_the_focus(self):
        self.show()
        nav = self.win.navigation
        self.assertEqual(nav.current_context(), navigation.CTX_BP_SHELF)
        self.shell.open_library("SFC")
        self.pump()
        self.shell.library.console_chips["SFC"].grab_focus()
        self.assertEqual(nav.current_context(), navigation.CTX_BP_GAMES)
        self.shell.rail.focus_current()
        self.assertEqual(nav.current_context(), navigation.CTX_BP_RAIL)
        grid = self.win.pages.grid_for("SFC")
        self.pump_until(lambda: grid.card_for(grid.entries()[0]) is not None)
        grid.focus_first_card()
        self.pump()
        self.assertEqual(nav.current_context(), navigation.CTX_BP_GRID)
        self.win.enter_selection_mode()
        self.assertEqual(nav.current_context(), navigation.CTX_BP_SELECTION)
        self.win.leave_selection_mode()
        self.shell.show_game(self.rom("SFC"))
        self.pump()
        self.assertEqual(nav.current_context(), navigation.CTX_BP_PANE)
        self.shell.show_search()
        self.pump()
        self.assertEqual(nav.current_context(), navigation.CTX_BP_OSK)

    def test_the_resolution_of_every_context(self):
        r = navigation.resolve
        self.assertEqual(r(navigation.CTX_BP_PAUSE, "up"), ("move", "up"))
        self.assertEqual(r(navigation.CTX_BP_PAUSE, "confirm"), ("activate",))
        self.assertEqual(r(navigation.CTX_BP_PAUSE, "back"), ("bp-pause-back",))
        self.assertEqual(r(navigation.CTX_BP_PAUSE, "big_picture"), ("bp-pause-close",))
        self.assertEqual(r(navigation.CTX_BP_PAUSE, "search"), ("bp-pause-close",))
        self.assertEqual(r(navigation.CTX_BP_PAUSE, "next_console"), ("bp-pause-slot", 1))
        self.assertEqual(r(navigation.CTX_BP_PAUSE, "prev_console"), ("bp-pause-slot", -1))
        self.assertEqual(r(navigation.CTX_BP_PAUSE, "favorite"), ("noop",))
        self.assertEqual(r(navigation.CTX_BP_SHELF, "big_picture"), ("big-picture",))
        self.assertEqual(r(navigation.CTX_BP_OSK, "menu"), ("noop",))
        self.assertEqual(r(navigation.CTX_BP_TEXT, "menu"), ("noop",))
        self.assertEqual(r(navigation.CTX_BP_SELECTION, "left"), ("selection-move", "left"))
        self.assertEqual(r(navigation.CTX_BP_SELECTION, "confirm"), ("toggle-select",))
        self.assertEqual(r(navigation.CTX_BP_SELECTION, "context"), ("selection-select-all",))
        self.assertEqual(r(navigation.CTX_BP_SELECTION, "favorite"), ("bp-remove-selected",))
        self.assertEqual(r(navigation.CTX_BP_SELECTION, "menu"), ("bp-share-selected",))
        self.assertEqual(r(navigation.CTX_BP_SELECTION, "back"), ("selection-exit",))
        self.assertEqual(r(navigation.CTX_BP_SELECTION, "range"), ("noop",))
        self.assertEqual(r(navigation.CTX_BP_SHELF, "menu"), ("bp-search",))
        self.assertEqual(r(navigation.CTX_BP_SHELF, "search"), ("bp-search",))
        self.assertEqual(r(navigation.CTX_BP_GRID, "confirm"), ("bp-details",))
        self.assertEqual(r(navigation.CTX_BP_GRID, "confirm_hold"), ("selection-enter",))
        self.assertEqual(r(navigation.CTX_BP_GRID, "context"), ("favorite",))
        self.assertEqual(r(navigation.CTX_BP_GRID, "favorite"), ("bp-options",))
        self.assertEqual(r(navigation.CTX_BP_GRID, "search"), ("selection-enter",))
        self.assertEqual(r(navigation.CTX_BP_GRID, "range"), ("noop",))
        self.assertEqual(r(navigation.CTX_BP_PANE, "context"), ("bp-page-action", "context"))
        self.assertEqual(r(navigation.CTX_BP_PANE, "range"), ("noop",))

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
        with mock.patch.object(self.shell.osk, "handle_action") as osk:
            nav._cmd_bp_osk("favorite")
        osk.assert_called_once_with("favorite")
        with mock.patch.object(self.win, "toggle_big_picture") as toggle:
            nav._cmd_big_picture()
        toggle.assert_called_once()
        item = mock.Mock(rom={"name": "x"})
        for command, target in (("_cmd_bp_details", "show_game"),):
            with mock.patch.object(self.win, "_focused_rom_item", return_value=None):
                getattr(nav, command)()
            with mock.patch.object(self.win, "_focused_rom_item", return_value=item), mock.patch.object(
                self.shell, target
            ) as called:
                getattr(nav, command)()
            called.assert_called_once_with(item.rom)
        with mock.patch.object(self.win, "_focused_rom_item", return_value=None):
            nav._cmd_bp_options()
        with mock.patch.object(self.win, "_focused_rom_item", return_value=item), mock.patch.object(
            self.shell.library, "open_options"
        ) as options:
            nav._cmd_bp_options()
        options.assert_called_once_with(item.rom)
        page = mock.Mock()
        with mock.patch.object(self.shell, "visible_page", return_value=page):
            nav._cmd_bp_page_action("favorite")
        page.on_pad_action.assert_called_once_with("favorite")
        with mock.patch.object(self.shell, "visible_page", return_value=object()):
            nav._cmd_bp_page_action("favorite")
        # The multi-select's Y and View.
        roms = [self.rom("SFC")]
        with mock.patch.object(self.win, "_confirm_delete_roms") as delete, mock.patch.object(
            self.win, "share_roms"
        ) as share:
            nav._cmd_bp_remove_selected()
            nav._cmd_bp_share_selected()
            delete.assert_not_called()
            share.assert_not_called()
            self.win._selected_roms = roms
            nav._cmd_bp_remove_selected()
            nav._cmd_bp_share_selected()
            self.win._selected_roms = []
        delete.assert_called_once_with(roms)
        share.assert_called_once_with(roms)

    def test_the_keyboard_keys_stand_in_for_the_pad(self):
        self.show()
        nav = self.win.navigation
        self.shell.open_library("FC")
        self.pump()
        before = self.win.current_console
        self.assertTrue(nav.handle_pane_key(Gdk.KEY_Tab, 0))
        self.pump()
        self.assertNotEqual(self.win.current_console, before)
        self.assertTrue(nav.handle_pane_key(Gdk.KEY_ISO_Left_Tab, 0))
        self.pump()
        self.assertEqual(self.win.current_console, before)
        self.assertFalse(nav.handle_pane_key(Gdk.KEY_a, 0))
        with mock.patch.object(nav, "dispatch") as dispatch:
            self.assertTrue(nav.handle_pane_key(Gdk.KEY_d, Gdk.ModifierType.CONTROL_MASK))
            self.assertTrue(nav.handle_pane_key(Gdk.KEY_Return, Gdk.ModifierType.ALT_MASK))
        self.assertEqual([c.args[0] for c in dispatch.call_args_list], ["context", "favorite"])
        # The Menu key: multi-select on a game, nothing elsewhere.
        self.shell.library.console_chips["FC"].grab_focus()
        with mock.patch.object(nav, "_cmd_selection_enter") as select:
            self.assertTrue(nav.handle_pane_key(Gdk.KEY_Menu, 0))
            select.assert_not_called()
            with mock.patch.object(nav, "current_context", return_value=navigation.CTX_BP_GRID):
                self.assertTrue(nav.handle_pane_key(Gdk.KEY_Menu, 0))
        select.assert_called_once()
        # Nothing to step from the rail, and Tab falls through to GTK there.
        with mock.patch.object(self.shell, "step_console", return_value=False):
            self.assertFalse(nav.handle_pane_key(Gdk.KEY_Tab, 0))

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
        glyphs = nav.glyphs()
        self.assertEqual(self.shell.hints_for(navigation.CTX_BP_OSK, glyphs)[0][1], self.said("big_picture.hints.type"))
        self.assertEqual(self.shell.hints_for(navigation.CTX_BP_RAIL, glyphs)[1][1], self.said("big_picture.hints.tabs"))
        with mock.patch.object(self.shell, "visible_page", return_value=None):
            self.assertEqual(self.shell.hints_for(navigation.CTX_BP_PAGE, glyphs), [])
            self.assertEqual(self.shell.context_for(None), navigation.CTX_BP_PAGE)
        self.assertEqual(nav._big_picture_hints(navigation.SOURCE_GAMEPAD, navigation.CTX_DIALOG)[1][1], self.said("hints.close"))
        selection = nav._big_picture_hints(navigation.SOURCE_KEYBOARD, navigation.CTX_BP_SELECTION)
        self.assertEqual(selection[0], ("Enter", self.said("big_picture.hints.select")))
        self.assertEqual(selection[3], ("Ctrl+F", self.said("big_picture.hints.share")))
        pad = nav._big_picture_hints(navigation.SOURCE_GAMEPAD, navigation.CTX_BP_GRID)
        self.assertEqual(pad[4], (glyphs["start"], self.said("big_picture.hints.select")))
        self.win.pause_menu = mock.Mock()
        self.win.pause_menu.hints.return_value = [("A", "x")]
        self.assertEqual(nav._big_picture_hints(navigation.SOURCE_GAMEPAD, navigation.CTX_BP_PAUSE), [("A", "x")])
        self.win.pause_menu = None
        # The desktop's own slots stay empty while the mode is on.
        self.assertFalse(self.win.hint_box.get_visible())

    def test_a_number_row_takes_left_and_right(self):
        from openemux.ui.bigpicture.widgets import ROW_NUMBER, Row

        steps = []
        row = Row("n", kind=ROW_NUMBER, value=1, on_step=steps.append)
        self.shell.shelf.body.append(row)
        self.show()
        row.grab_focus()
        self.pump()
        self.win.navigation._cmd_move("right")
        self.win.navigation._cmd_move("left")
        self.assertEqual(steps, [1, -1])
        self.shell.shelf.body.remove(row)


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
        shell.release()
        shell.release()
        self.assertIsNone(shell._provider)

    def test_the_clock_and_the_dark_theme(self):
        shell = self.shell
        clock = shell._clocks[0]
        self.assertEqual(len(clock.get_label()), 5)
        self.assertEqual(shell._on_clock(), GLib.SOURCE_CONTINUE)
        shell._start_clock()
        source = shell._clock_source
        shell._start_clock()
        self.assertEqual(shell._clock_source, source)
        shell._stop_clock()
        self.assertEqual(shell._clock_source, 0)
        style = Adw.StyleManager.get_default()
        self.assertEqual(style.get_color_scheme(), Adw.ColorScheme.FORCE_DARK)
        before = shell._color_scheme
        self.leave()
        self.assertEqual(style.get_color_scheme(), before)
        shell._force_dark(False)  # nothing to restore twice

    def test_a_theme_chosen_inside_is_the_one_given_back(self):
        shell = self.shell
        style = Adw.StyleManager.get_default()
        original = shell._color_scheme
        self.addCleanup(style.set_color_scheme, original)
        # The Appearance entry applies the new theme, then hands it over.
        style.set_color_scheme(Adw.ColorScheme.FORCE_LIGHT)
        shell.adopt_color_scheme()
        self.assertEqual(style.get_color_scheme(), Adw.ColorScheme.FORCE_DARK)
        self.assertEqual(shell._color_scheme, Adw.ColorScheme.FORCE_LIGHT)
        self.leave()
        self.assertEqual(style.get_color_scheme(), Adw.ColorScheme.FORCE_LIGHT)

    def test_pushing_a_page_already_on_the_stack_pops_back_to_it(self):
        shell = self.shell
        self.show()
        shell.open_library("SFC")
        self.pump()
        page = shell.library
        shell.push(page)  # already visible: only the focus
        self.pump()
        self.assertIs(shell.visible_page(), page)
        from openemux.ui.bigpicture.widgets import BigPage

        other = BigPage(shell, "Other", tag="bp-other")
        shell.push(other)
        self.pump()
        self.assertIs(shell.visible_page(), other)
        self.assertFalse(shell.step_console(1))  # nothing to walk there
        shell.push(page)
        self.pump()
        self.assertIs(shell.visible_page(), page)
        self.assertNotIn(other, shell._pushed)
        shell.go_home()
        self.pump()
        self.assertIs(shell.visible_page(), shell.shelf)
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
        # A card's activation shows the game, the desktop's launches it.
        with mock.patch.object(shell, "show_game") as show:
            self.win.on_grid_activate(rom)
        show.assert_called_once_with(rom)
        self.leave()
        with mock.patch.object(self.win, "on_launch_game") as launch:
            self.win.on_grid_activate(rom)
        launch.assert_called_once_with(rom)

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

    def test_the_task_banner_offers_to_stop_the_task(self):
        shell = self.shell
        self.assertFalse(shell.run_task_action())
        cancelled = []
        task = self.win.tasks.begin("scan", "Scanning", total=4, on_cancel=lambda: cancelled.append(1))
        self.win.tasks.update(task, 1, 4, "Scanning")
        shell.sync_status()
        banner = shell.shelf.banners
        self.assertTrue(banner.get_visible())
        self.assertTrue(banner.task.get_visible())
        self.assertEqual(banner.task.detail_label.get_label(), "· " + self.said("big_picture.banner.progress", current=1, total=4))
        self.assertTrue(banner.task.progress.get_visible())
        with self.caught_dialog() as dialogs:
            banner.task.emit("clicked")
        dialogs[0].emit("response", "confirm")
        self.pump()
        self.assertTrue(self.win.tasks.current_task()["cancelling"])
        self.win.tasks.finish(task)
        shell.sync_status()
        self.assertFalse(banner.get_visible())
        # A task with no total has no progress line.
        task = self.win.tasks.begin("scan", "Looking")
        shell.sync_status()
        self.assertFalse(banner.task.progress.get_visible())
        self.win.tasks.finish(task)
        # The update banner, mirrored, does what the desktop's button does.
        self.win.update_banner.set_title("New version")
        self.win.update_banner.set_revealed(True)
        shell.sync_status()
        self.assertTrue(banner.update.get_visible())
        with mock.patch.object(self.win, "_on_update_banner_clicked") as clicked:
            banner.update.emit("clicked")
        clicked.assert_called_once_with(self.win.update_banner)
        self.win.update_banner.set_revealed(False)

    def test_share_falls_back_to_receiving(self):
        with mock.patch.object(self.win, "receive_games") as receive, mock.patch.object(
            self.win, "share_roms"
        ) as share:
            self.shell.open_share()
            self.shell.open_share([self.rom("SFC")])
        receive.assert_called_once()
        share.assert_called_once()


@needs_display
class TheFixesOfQaRoundOne(BigPictureCase):
    """Issue 957, QA round 1: search from the Shelf, Up out of the grid, A in multi-select."""

    def _games(self, console="FC"):
        self.show()
        self.shell.open_library(console)
        self.pump()
        grid = self.win.pages.grid_for(console)
        self.pump_until(lambda: grid.card_for(grid.entries()[0]) is not None)
        grid.focus_first_card()
        self.pump()
        return grid

    def test_search_from_the_shelf_keeps_the_focus_on_the_keyboard(self):
        self.show()
        self.assertIs(self.shell.visible_page(), self.shell.shelf)
        self.assertTrue(self.shell.open_search())
        self.pump_until(lambda: self.shell.search_open)
        self.pump()
        # The page's ``shown`` comes last and must not take the focus back.
        self.shell._on_page_shown(self.shell.library)
        self.assertTrue(self.focus_widget().is_ancestor(self.shell.osk))
        self.shell._focus_visible()
        self.assertTrue(self.focus_widget().is_ancestor(self.shell.osk))
        self.assertEqual(self.win.navigation.current_context(), navigation.CTX_BP_OSK)
        # Closed, the page's default is back.
        self.shell.hide_search()
        self.pump()
        with mock.patch.object(self.shell.library, "on_shown") as shown:
            self.shell._on_page_shown(self.shell.library)
        shown.assert_called_once_with()

    def test_up_from_the_top_row_reaches_the_view_switch(self):
        self._games()
        nav = self.win.navigation
        self.assertEqual(nav.current_context(), navigation.CTX_BP_GRID)
        nav._cmd_move("up")
        self.pump()
        segments = self.shell.library.segments
        self.assertTrue(self.focus_widget().is_ancestor(segments))
        self.assertIs(self.focus_widget(), segments.buttons[segments.current])

    def test_the_keyboard_arrows_on_the_games_go_through_the_pads_table(self):
        self._games()
        nav = self.win.navigation
        with mock.patch.object(nav, "dispatch") as dispatch:
            self.assertTrue(nav.handle_pane_key(Gdk.KEY_Up, 0))
            # With a modifier, or off the games, they stay GTK's.
            self.assertFalse(nav.handle_pane_key(Gdk.KEY_Up, Gdk.ModifierType.SHIFT_MASK))
            self.shell.library.console_chips["FC"].grab_focus()
            self.assertFalse(nav.handle_pane_key(Gdk.KEY_Down, 0))
        dispatch.assert_called_once_with("up")

    def test_the_keyboard_arrows_walk_the_on_screen_keyboard_like_the_pad(self):
        self._games()
        nav = self.win.navigation
        self.shell.show_search()
        self.pump()
        osk = self.shell.osk
        osk.rows[0][0].grab_focus()
        self.pump()
        self.assertIs(self.focus_widget(), osk.rows[0][0])
        self.assertTrue(nav.handle_pane_key(Gdk.KEY_Down, 0))
        self.pump()
        self.assertIs(self.focus_widget(), osk.rows[1][0])  # "1" -> "Q"
        self.assertTrue(nav.handle_pane_key(Gdk.KEY_Left, 0))
        self.pump()
        self.assertIs(self.focus_widget(), osk.rows[1][-1])  # wraps to "P"
        self.shell.hide_search()
        self.pump()

    def test_leaving_the_grid_upward_only_when_stuck_on_the_games(self):
        grid = self._games()
        nav = self.win.navigation
        focus = self.focus_widget()
        with mock.patch.object(self.shell.library, "focus_above_grid") as above:
            nav._leave_grid_up_if_stuck("down", focus)
            nav._leave_grid_up_if_stuck("up", None)
            # The move landed somewhere else.
            nav._leave_grid_up_if_stuck("up", self.shell.library.back_button)
            # Stuck, but not on the games.
            chip = self.shell.library.console_chips["FC"]
            chip.grab_focus()
            nav._leave_grid_up_if_stuck("up", chip)
            # Multi-select stays on the games.
            grid.focus_first_card()
            self.pump()
            self.win.enter_selection_mode()
            nav._leave_grid_up_if_stuck("up", self.focus_widget())
            above.assert_not_called()
            self.win.leave_selection_mode()
            nav._leave_grid_up_if_stuck("up", self.focus_widget())
            above.assert_called_once_with()
            # Not in Big Picture: the desktop grid is left alone.
            above.reset_mock()
            with mock.patch.object(nav, "_big_picture_on", return_value=False):
                nav._leave_grid_up_if_stuck("up", self.focus_widget())
            above.assert_not_called()

    def test_the_view_switch_takes_the_focus_on_its_current_segment(self):
        from openemux.ui.bigpicture.widgets import Segments

        segments = Segments([("a", "view-grid-symbolic", "A"), ("b", "view-list-symbolic", "B")],
                            lambda _id: None)
        with mock.patch.object(segments.buttons["a"], "grab_focus", return_value=True) as first, \
                mock.patch.object(segments.buttons["b"], "grab_focus", return_value=True) as second:
            self.assertTrue(segments.focus_current())  # none current yet: the first
            segments.set_current("b")
            self.assertTrue(segments.focus_current())
        first.assert_called_once_with()
        second.assert_called_once_with()
        self.assertFalse(Segments([], lambda _id: None).focus_current())

    def test_a_in_multi_select_toggles_the_game_and_stays(self):
        grid = self._games()
        item = self.win._focused_rom_item()
        self.win.enter_selection_mode()
        with mock.patch.object(self.shell, "show_game") as show:
            self.win.on_grid_activate(item.rom)
            self.assertEqual([r.get("path") for r in grid.selected_roms()], [item.rom.get("path")])
            self.win.on_grid_activate(item.rom)
            self.assertEqual(grid.selected_roms(), [])
            # Another game than the focused one: nothing to toggle.
            other = dict(item.rom, path="/elsewhere.nes")
            self.win.on_grid_activate(other)
            self.assertEqual(grid.selected_roms(), [])
        show.assert_not_called()
        self.assertTrue(self.win.selection_mode_active)
        self.assertEqual(self.win.navigation.current_context(), navigation.CTX_BP_SELECTION)
        # And from the keyboard: Enter on the card goes the same way.
        with mock.patch.object(self.win, "_toggle_selected_rom") as toggle:
            grid._last_activation = (None, 0)
            grid._launch_rom(item.rom)
        toggle.assert_called_once_with(item.rom)
        # Nothing focused: nothing toggled.
        with mock.patch.object(self.win, "_focused_rom_item", return_value=None):
            self.win._toggle_selected_rom(item.rom)
        self.assertEqual(grid.selected_roms(), [])


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
        css = theme.stylesheet(1.0)
        self.assertIn(".big-picture .bp-row {", css)
        self.assertIn(f"font-size: {theme.SIZES['title']}px", css)
        double = theme.stylesheet(2.0)
        self.assertIn(f"font-size: {theme.SIZES['title'] * 2}px", double)
        # Android's dark palette, always, and the 951 focus tones.
        self.assertIn(theme.PALETTE["bg"], css)
        self.assertIn(theme.FOCUS_FILL, css)
        self.assertIn(theme.FOCUS_ACCENT, css)
        self.assertIn(".big-picture .bp-shelf-card.bp-shelf-fc { background-color: #7A2E2E; }", css)
        # Issue 964: the art/text gap is the stylesheet's, so it scales.
        self.assertIn(f"border-spacing: {theme.SIZES['shelf_gap']}px", css)
        # Issue 955: a wide tile's icon box is its own, smaller size.
        self.assertIn(".big-picture .bp-tile.bp-wide .bp-badge {", css)
        self.assertIn(f"min-width: {theme.SIZES['wide_badge']}px", css)
        self.assertLess(theme.SIZES["wide_badge"], theme.SIZES["badge"])
        self.assertIn(f"min-width: {theme.SIZES['wide_tile_width']}px", css)
        self.assertEqual(theme.px("gap", 0.5), 8)
        self.assertEqual(theme.px("gap", 0.01), 1)


if __name__ == "__main__":
    unittest.main()
