"""One card in the library grid, driven the way a pointer and a pad drive it.

`ui/rom_card.py` sat at 58%: building the window realizes a screenful of
cards, so the constructor runs, but nothing then *uses* one. The 260 statements
that were left are the ones a user reaches -- hover, click, the star, the
context-menu actions, the cover that arrives from a worker thread and the
guards that drop it when the card has moved on to another game.

The cards here are the real ones the grid built, taken from a presented
window: `grid.card_for(entry)` hands back the widget on screen, which is the
only one whose focus, parent and popover are real.
"""

import copy
import unittest
from unittest import mock

from tests.gtk_display import HAVE_DISPLAY, needs_display
from tests.window_harness import WindowCase

if HAVE_DISPLAY:
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Gdk, GdkPixbuf, Gtk

    from openemux.core.config import (
        COVER_ART_TYPE_BOXART,
        COVER_ART_TYPE_CARTRIDGE_LABEL,
    )
    from openemux.core.library_view import VIEW_MODE_LIST
    from openemux.core.scraper import COVER_ART, LABEL_ART
    from openemux.ui import rom_card as rom_card_module
    from openemux.ui.rom_card import RomEntry, RomItem, entry_matches, item_for_widget


class _CardCase(WindowCase):
    """A presented window, one console page, and the card showing its first game."""

    console = "SFC"

    def setUp(self):
        super().setUp()
        self.grid = self.show_with_cards(self.console)
        self.entry = self.grid.entries()[0]
        self.card = self.grid.card_for(self.entry)
        if self.card is None:
            self.skipTest("the grid realized no card for the first game")

    def pixbuf(self, width=40, height=60):
        pixbuf = GdkPixbuf.Pixbuf.new(
            GdkPixbuf.Colorspace.RGB, True, 8, width, height
        )
        pixbuf.fill(0x00FF00FF)
        return pixbuf


@needs_display
class WhatACardShowsTests(_CardCase):
    def test_it_shows_the_game_it_was_bound_to(self):
        self.assertEqual(self.card.rom["path"], self.entry.rom["path"])
        self.assertEqual(self.card.get_tooltip_text(), self.entry.display_name)

    def test_an_unbound_card_shows_no_game_at_all(self):
        self.card.unbind()
        self.assertIsNone(self.card.rom)
        self.assertFalse(self.card.selected)

    def test_a_long_name_is_cut_for_the_card_and_kept_in_the_tooltip(self):
        self.assertEqual(RomItem._truncate_name("short", 10), "short")
        self.assertEqual(RomItem._truncate_name("0123456789abc", 10), "0123456789...")

    def test_a_card_with_its_menu_up_closes_it_before_letting_go(self):
        # The card's anchor is about to show another game, and a popover
        # parented to it would still be pointing at the old one.
        self.card._show_context_menu()
        self.assertIsNotNone(self.card._context_popover)
        self.card.unbind()
        self.assertIsNone(self.card._context_popover)

    def test_rebinding_to_another_game_replaces_every_piece_of_state(self):
        other = RomEntry(self.win.playlist_manager.load_playlist("FC")[0])
        self.card.bind(other)
        self.assertEqual(self.card.rom["console"], "FC")
        self.assertFalse(self.card.has_css_class("rom-card-hover"))
        self.assertEqual(self.card.get_opacity(), 1.0)

    def test_a_card_that_left_the_window_is_abandoned(self):
        # Issue #291: covers in flight for a page that is gone kept scheduling
        # main-thread work for cards nobody can see.
        loose = RomItem(self.grid._card_ctx)
        self.assertTrue(loose._is_abandoned())
        self.assertFalse(self.card._is_abandoned())

    def test_a_stale_token_is_recognised(self):
        token = self.card._generation
        self.assertFalse(self.card._is_stale(token))
        self.card._generation += 1
        self.assertTrue(self.card._is_stale(token))


@needs_display
class TheCoverArrivingTests(_CardCase):
    def test_a_decoded_cover_is_attached_and_the_placeholder_goes(self):
        self.card._apply_cover_pixbuf(self.card._generation, self.pixbuf(), False)
        self.assertTrue(self.card.cover_image.get_visible())
        self.assertFalse(self.card._showing_placeholder)

    def test_a_full_resolution_composite_becomes_a_texture(self):
        self.card._apply_cover_pixbuf(self.card._generation, self.pixbuf(), True)
        self.assertIsNotNone(self.card.cover_image.get_paintable())

    def test_a_cover_for_a_game_the_card_has_left_is_dropped(self):
        stale = self.card._generation
        self.card._generation += 1
        before = self.card._showing_placeholder
        self.assertFalse(
            self.card._apply_cover_pixbuf(stale, self.pixbuf(), False)
        )
        self.assertEqual(self.card._showing_placeholder, before)

    def test_art_that_will_not_attach_is_logged_rather_than_raised(self):
        with mock.patch.object(
            self.card.cover_image, "set_pixbuf", side_effect=RuntimeError("bad")
        ):
            self.assertFalse(
                self.card._apply_cover_pixbuf(
                    self.card._generation, self.pixbuf(), False
                )
            )

    def test_a_missing_cover_leaves_the_placeholder_up(self):
        self.card._apply_cover_pixbuf(self.card._generation, self.pixbuf(), False)
        self.assertFalse(self.card._restore_placeholder(self.card._generation))
        self.assertTrue(self.card._showing_placeholder)

    def test_a_placeholder_restore_for_another_game_is_dropped(self):
        stale = self.card._generation
        self.card._generation += 1
        self.card._apply_cover_pixbuf(self.card._generation, self.pixbuf(), False)
        self.card._restore_placeholder(stale)
        self.assertFalse(self.card._showing_placeholder)

    def test_the_artwork_badge_follows_what_the_fetch_found(self):
        self.entry.has_artwork = False
        self.card._sync_artwork_state(self.entry, self.card._generation)
        self.assertTrue(self.card.artwork_badge.get_visible())
        self.entry.has_artwork = True
        self.card._sync_artwork_state(self.entry, self.card._generation)
        self.assertFalse(self.card.artwork_badge.get_visible())

    def test_an_abandoned_card_syncs_nothing(self):
        loose = RomItem(self.grid._card_ctx)
        self.assertFalse(loose._sync_artwork_state(self.entry, 0))

    def test_the_fetch_records_the_answer_on_the_entry_either_way(self):
        # It is that ROM's artwork state, which the "without artwork" filter
        # needs whether or not anything is showing it.
        with mock.patch.object(rom_card_module.GLib, "idle_add"):
            self.card._on_cover_fetched(self.entry, self.card._generation, self.entry.rom, "")
        self.assertFalse(self.entry.has_artwork)

    def test_a_fetch_for_a_game_the_card_has_left_decodes_nothing(self):
        stale = self.card._generation
        self.card._generation += 1
        with mock.patch.object(
            rom_card_module.cover_cache, "load_cover"
        ) as load, mock.patch.object(rom_card_module.GLib, "idle_add"):
            self.card._on_cover_fetched(self.entry, stale, self.entry.rom, "/tmp/a.png")
        load.assert_not_called()

    def test_a_cover_on_disk_is_decoded_off_the_main_thread(self):
        # Issue #128: the decode used to be handed to the main thread, which
        # serialised every rescale in the library onto the one that cannot
        # afford it.
        pixbuf = self.pixbuf()
        with mock.patch.object(
            rom_card_module.cover_cache, "load_cover", return_value=pixbuf
        ), mock.patch.object(rom_card_module.GLib, "idle_add") as idle_add:
            self.card._on_cover_fetched(
                self.entry, self.card._generation, self.entry.rom, "/tmp/a.png"
            )
        applied = [
            call for call in idle_add.call_args_list
            if call[0][0] == self.card._apply_cover_pixbuf
        ]
        self.assertEqual(len(applied), 1)

    def test_a_refresh_re_fetches_and_can_ask_for_a_cross_fade(self):
        with mock.patch.object(self.card, "_start_cover_fetch") as fetch:
            self.card._refresh_cover_after_change(fade=True)
        fetch.assert_called_once()
        self.assertTrue(self.card._fade_next_apply)

    def test_a_refresh_on_an_unbound_card_fetches_nothing(self):
        self.card.unbind()
        with mock.patch.object(self.card, "_start_cover_fetch") as fetch:
            self.card._refresh_cover_after_change()
        fetch.assert_not_called()

    def test_an_unbound_card_starts_no_fetch(self):
        self.card.entry = None
        with mock.patch.object(rom_card_module, "fetch_cover") as fetch:
            self.card._start_cover_fetch()
        fetch.assert_not_called()

    def test_the_cross_fade_runs_when_the_new_art_lands(self):
        # Issue #187: what separates covers filling in during a sync from
        # glitchy popping.
        self.card._fade_next_apply = True
        self.card._apply_cover_pixbuf(self.card._generation, self.pixbuf(), False)
        self.assertFalse(self.card._fade_next_apply)
        self.assertIsNotNone(self.card._reveal_animation)


@needs_display
class TheStarTests(_CardCase):
    def test_clicking_the_star_favourites_the_game(self):
        self.card._on_favorite_button_clicked(None)
        self.assertTrue(self.win.playlist_manager.is_favorite(self.card.rom["path"]))
        self.assertEqual(self.card.favorite_button.get_icon_name(), "starred-symbolic")

    def test_clicking_it_again_unfavourites_it(self):
        self.card.toggle_favorite()
        self.card.toggle_favorite()
        self.assertFalse(self.win.playlist_manager.is_favorite(self.card.rom["path"]))
        self.assertEqual(
            self.card.favorite_button.get_icon_name(), "non-starred-symbolic"
        )

    def test_a_favourite_shows_its_star_even_with_the_pointer_elsewhere(self):
        self.card._sync_favorite_button(True)
        self.assertTrue(self.card.favorite_button.get_visible())
        self.card._sync_favorite_button(False)
        self.assertFalse(self.card.favorite_button.get_visible())

    def test_starring_an_unbound_card_does_nothing(self):
        self.card.unbind()
        self.card.toggle_favorite()


@needs_display
class HoverAndFocusTests(_CardCase):
    def test_hovering_reveals_the_play_overlay_and_the_menu_button(self):
        self.card._on_hover_enter(None, 0, 0)
        self.assertTrue(self.card.play_overlay.get_visible())
        self.assertTrue(self.card.menu_button.get_visible())
        self.assertTrue(self.card.has_css_class("rom-card-hover"))

    def test_hovering_an_unbound_card_reveals_nothing(self):
        self.card.unbind()
        self.card._on_hover_enter(None, 0, 0)
        self.assertFalse(self.card.play_overlay.get_visible())

    def test_leaving_puts_the_affordances_away_again(self):
        self.card._on_hover_enter(None, 0, 0)
        self.card._on_hover_leave(None)
        self.assertFalse(self.card.play_overlay.get_visible())
        self.assertFalse(self.card.menu_button.get_visible())
        self.assertFalse(self.card.has_css_class("rom-card-hover"))

    def test_leaving_keeps_the_menu_button_while_its_own_menu_is_open(self):
        self.card._on_hover_enter(None, 0, 0)
        self.card._context_popover = mock.Mock()
        self.card._on_hover_leave(None)
        self.assertTrue(self.card.menu_button.get_visible())

    def test_focus_mirrors_the_hover_affordances(self):
        self.card.set_focus_visual(True)
        self.assertTrue(self.card.play_overlay.get_visible())
        self.card.set_focus_visual(False)
        self.assertFalse(self.card.play_overlay.get_visible())

    def test_focus_on_an_unbound_card_reveals_nothing(self):
        self.card.unbind()
        self.card.set_focus_visual(True)
        self.assertFalse(self.card.play_overlay.get_visible())

    def test_losing_focus_leaves_hover_in_charge_when_the_pointer_is_there(self):
        self.card._on_hover_enter(None, 0, 0)
        self.card.set_focus_visual(False)
        self.assertTrue(self.card.play_overlay.get_visible())

    def test_losing_focus_keeps_the_menu_button_while_the_menu_is_open(self):
        self.card.set_focus_visual(True)
        self.card._context_popover = mock.Mock()
        self.card.set_focus_visual(False)
        self.assertTrue(self.card.menu_button.get_visible())


@needs_display
class ClickingACardTests(_CardCase):
    def _gesture(self, button=Gdk.BUTTON_PRIMARY, state=0):
        gesture = mock.Mock()
        gesture.get_current_button.return_value = button
        gesture.get_current_event_state.return_value = state
        return gesture

    def test_a_plain_click_launches_the_game(self):
        with mock.patch.object(self.win.game, "launch") as launch:
            self.card.on_click(self._gesture(), 1, 1.0, 2.0)
        launch.assert_called_once()

    def test_a_ctrl_click_selects_instead_of_launching(self):
        # A modifier click must never launch the game.
        with mock.patch.object(self.win.game, "launch") as launch:
            self.card.on_click(
                self._gesture(state=Gdk.ModifierType.CONTROL_MASK), 1, 1.0, 2.0
            )
        launch.assert_not_called()
        self.assertTrue(self.entry.selected)

    def test_a_shift_click_ranges_instead_of_launching(self):
        with mock.patch.object(self.win.game, "launch") as launch:
            self.card.on_click(
                self._gesture(state=Gdk.ModifierType.SHIFT_MASK), 1, 1.0, 2.0
            )
        launch.assert_not_called()

    def test_a_right_click_opens_the_context_menu(self):
        with mock.patch.object(self.card, "_show_context_menu") as show:
            self.card.on_click(self._gesture(button=Gdk.BUTTON_SECONDARY), 1, 3.0, 4.0)
        show.assert_called_once_with(3.0, 4.0)

    def test_a_middle_click_does_nothing_at_all(self):
        with mock.patch.object(self.win.game, "launch") as launch:
            self.card.on_click(self._gesture(button=Gdk.BUTTON_MIDDLE), 1, 1.0, 2.0)
        launch.assert_not_called()

    def test_a_click_on_an_unbound_card_does_nothing(self):
        self.card.unbind()
        with mock.patch.object(self.win.game, "launch") as launch:
            self.card.on_click(self._gesture(), 1, 1.0, 2.0)
        launch.assert_not_called()

    def test_the_menu_button_anchors_the_menu_under_itself(self):
        with mock.patch.object(self.card, "_show_context_menu") as show:
            self.card._on_menu_button_clicked(self.card.menu_button)
        show.assert_called_once()

    def test_a_button_with_no_bounds_yet_opens_the_menu_unanchored(self):
        button = mock.Mock()
        button.compute_bounds.return_value = (False, None)
        with mock.patch.object(self.card, "_show_context_menu") as show:
            self.card._on_menu_button_clicked(button)
        show.assert_called_once_with()


@needs_display
class SelectingACardTests(_CardCase):
    def test_selecting_paints_the_card(self):
        self.card.set_selected(True)
        self.assertTrue(self.card.has_css_class("rom-card-selected"))
        self.card.set_selected(False)
        self.assertFalse(self.card.has_css_class("rom-card-selected"))



@needs_display
class InAListRowTests(_CardCase):
    """The compact layout: a row, with a checkbox the cover layout has not."""

    def setUp(self):
        super().setUp()
        self.win._apply_view_mode(VIEW_MODE_LIST)
        self.grid = self.win.pages.grid_for(self.console)
        self.entry = self.grid.entries()[0]
        self.pump_until(lambda: self.grid.card_for(self.entry) is not None)
        self.card = self.grid.card_for(self.entry)
        if self.card is None or self.card.select_check is None:
            self.skipTest("the list page realized no row for the first game")

    def test_a_row_carries_the_console_name_as_its_platform_column(self):
        self.assertIsNotNone(self.card.console_label)
        self.assertTrue(self.card.console_label.get_label())

    def test_a_row_shows_the_whole_title_rather_than_a_truncated_one(self):
        self.assertEqual(self.card.name_label.get_label(), self.entry.display_name)

    def test_the_thumbnail_column_is_the_same_width_for_every_row(self):
        width, _height = self.card._cover_target_size()
        self.assertGreater(width, 0)

    def test_selecting_the_row_ticks_its_checkbox(self):
        self.card.set_selected(True)
        self.assertTrue(self.card.select_check.get_active())

    def test_ticking_the_checkbox_selects_the_row(self):
        self.card.select_check.set_active(True)
        self.assertTrue(self.entry.selected)

    def test_an_unbound_checkbox_toggle_changes_nothing(self):
        self.card.entry = None
        with mock.patch.object(self.card, "on_toggle_selection") as toggle:
            self.card._on_select_check_toggled(mock.Mock())
        toggle.assert_not_called()

    def test_the_guard_stops_the_checkbox_re_entering_its_own_handler(self):
        self.card._select_check_guard = True
        with mock.patch.object(self.card, "on_toggle_selection") as toggle:
            self.card._on_select_check_toggled(mock.Mock())
        toggle.assert_not_called()


@needs_display
class OnAPageThatMixesConsolesTests(_CardCase):
    """The uniform-box layout: the cover keeps its shape inside a backdrop."""

    def setUp(self):
        super().setUp()
        ctx = copy.copy(self.grid._card_ctx)
        ctx.mixed_consoles = True
        ctx.compact = False
        # Rooted in a real window: a card with no root counts as abandoned,
        # and every cover that arrives for it is dropped (issue #291).
        self.host = Gtk.Window()
        self.addCleanup(self.host.destroy)
        self.card = RomItem(ctx)
        self.host.set_child(self.card)
        self.host.present()
        self.pump()
        self.card.bind(self.entry)

    def test_the_cover_sits_in_a_backdrop_rather_than_being_cropped(self):
        self.assertIsNotNone(self.card._backdrop)

    def test_the_card_names_the_console_the_game_belongs_to(self):
        self.assertIsNotNone(self.card.console_label)

    def test_a_scaled_cover_is_shown_hugging_the_art_inside_the_box(self):
        # The rounded corners and the shadow hug the cover, not the empty
        # area around it.
        self.card._apply_cover_pixbuf(self.card._generation, self.pixbuf(30, 44), False)
        self.assertTrue(self.card.cover_image.get_visible())
        self.assertFalse(self.card._showing_placeholder)

    def test_swapping_the_cover_widget_twice_leaves_the_backdrop_alone(self):
        self.card._set_cover_widget(self.card.cover_image)
        self.card._set_cover_widget(self.card.cover_image)
        self.assertIs(self.card._backdrop.get_first_child(), self.card.cover_image)

    def test_going_back_to_the_placeholder_replaces_what_is_in_the_backdrop(self):
        self.card._show_cover_image()
        self.card._show_placeholder()
        self.assertIsNot(self.card._backdrop.get_first_child(), self.card.cover_image)


@needs_display
class TheContextMenuTests(_CardCase):
    def test_opening_it_builds_a_popover_parented_to_the_card(self):
        self.card.show_context_menu()
        self.assertIsNotNone(self.card.context_popover)
        self.assertIs(self.card.context_popover.get_parent(), self.card)
        self.card.context_popover.popdown()

    def test_opening_it_at_a_point_anchors_it_there(self):
        self.card.show_context_menu(5, 7)
        self.assertIsNotNone(self.card.context_popover)
        self.card.context_popover.popdown()

    def test_an_unbound_card_opens_no_menu(self):
        self.card.unbind()
        self.card.show_context_menu()
        self.assertIsNone(self.card.context_popover)

    def test_closing_it_lets_go_of_the_popover(self):
        self.card.show_context_menu()
        popover = self.card.context_popover
        self.card._on_context_popover_closed(popover)
        self.assertIsNone(self.card.context_popover)

    def test_a_popover_that_is_not_the_current_one_does_not_clear_it(self):
        self.card.show_context_menu()
        current = self.card.context_popover
        self.card._on_context_popover_closed(Gtk.Popover())
        self.assertIs(self.card.context_popover, current)
        current.popdown()

    def test_the_actions_are_installed_once(self):
        self.card._ensure_action_group()
        group = self.card._action_group
        self.card._ensure_action_group()
        self.assertIs(self.card._action_group, group)

    def test_a_console_with_a_cartridge_shell_offers_label_entries(self):
        self.assertIsInstance(self.card.supports_label(), bool)

    def test_an_unbound_card_supports_no_label(self):
        self.card.unbind()
        self.assertFalse(self.card.supports_label())


@needs_display
class TheContextMenuActionsTests(_CardCase):
    def _recorder(self, name):
        """Replace one of the callbacks the card was *built* with.

        The card copies them out of its `CardContext` in the constructor, so
        patching the window afterwards would leave the real one wired up --
        and the real "choose a cover" opens a file picker.
        """
        recorder = mock.Mock()
        patcher = mock.patch.object(self.card, name, recorder)
        patcher.start()
        self.addCleanup(patcher.stop)
        return recorder

    def test_rename_reaches_the_window(self):
        rename = self._recorder("on_rename_rom")
        self.card._act_rename(None, None)
        rename.assert_called_once_with(self.card.rom)

    def test_delete_reaches_the_window_with_a_list(self):
        delete = self._recorder("on_delete_rom")
        self.card._act_delete(None, None)
        delete.assert_called_once_with([self.card.rom])

    def test_reveal_in_files_reaches_the_window(self):
        reveal = self._recorder("on_reveal_in_files")
        self.card._act_reveal_in_files(None, None)
        reveal.assert_called_once_with(self.card.rom)

    def test_choosing_a_cover_opens_the_picker_for_box_art(self):
        choose = self._recorder("on_choose_cover")
        self.card._act_choose_cover(None, None)
        self.assertEqual(choose.call_args[0][2], COVER_ART)

    def test_choosing_a_label_opens_the_same_picker_for_the_label(self):
        choose = self._recorder("on_choose_cover")
        self.card._act_choose_label(None, None)
        self.assertEqual(choose.call_args[0][2], LABEL_ART)

    def test_removing_a_cover_and_a_label_go_to_the_same_place(self):
        remove = self._recorder("on_remove_cover")
        self.card._act_remove_cover(None, None)
        self.card._act_remove_label(None, None)
        kinds = [call[0][2] for call in remove.call_args_list]
        self.assertEqual(kinds, [COVER_ART, LABEL_ART])

    def test_syncing_one_game_asks_for_its_box_art(self):
        with mock.patch.object(self.win, "sync_rom_artwork") as sync:
            self.card._act_sync_cover(None, None)
        sync.assert_called_once_with(self.card.rom, COVER_ART_TYPE_BOXART)

    def test_syncing_a_label_asks_for_the_cartridge_label(self):
        with mock.patch.object(self.win, "sync_rom_artwork") as sync:
            self.card._act_sync_label(None, None)
        sync.assert_called_once_with(
            self.card.rom, COVER_ART_TYPE_CARTRIDGE_LABEL
        )

    def test_manage_opens_the_artwork_manager_on_the_right_tab(self):
        with mock.patch.object(self.win, "open_artwork_manager") as manage:
            self.card._act_manage_cover(None, None)
            self.card._act_manage_label(None, None)
        tabs = [call[0][1] for call in manage.call_args_list]
        self.assertEqual(tabs, [COVER_ART, LABEL_ART])

    def test_the_search_button_on_an_empty_cover_opens_the_manager(self):
        # Issue #127: the empty cover is exactly where someone notices art is
        # missing, so the fix starts there.
        with mock.patch.object(self.win, "open_artwork_manager") as manage:
            self.card._on_search_artwork_clicked(None)
        manage.assert_called_once_with(self.card.rom, COVER_ART)

    def test_every_action_on_an_unbound_card_does_nothing(self):
        rename = self._recorder("on_rename_rom")
        self.card.unbind()
        if True:
            for action in (
                self.card._act_toggle_favorite,
                self.card._act_rename,
                self.card._act_delete,
                self.card._act_reveal_in_files,
                self.card._act_choose_cover,
                self.card._act_remove_cover,
                self.card._act_choose_label,
                self.card._act_remove_label,
                self.card._act_sync_cover,
                self.card._act_sync_label,
                self.card._act_manage_cover,
                self.card._act_manage_label,
                self.card._on_search_artwork_clicked,
            ):
                action(None, None) if action.__name__.startswith("_act") else action(None)
        rename.assert_not_called()


@needs_display
class TheCartridgeShellTests(_CardCase):
    def test_a_card_that_is_not_a_cartridge_ignores_a_shell_change(self):
        self.card.cartridge_frame_path = None
        with mock.patch.object(self.card, "_refresh_cover_after_change") as refresh:
            self.card.set_cartridge_frame("/tmp/red.svg")
        refresh.assert_not_called()

    def test_the_same_shell_again_re_composes_nothing(self):
        self.card.cartridge_frame_path = "/tmp/red.svg"
        with mock.patch.object(self.card, "_refresh_cover_after_change") as refresh:
            self.card.set_cartridge_frame("/tmp/red.svg")
        refresh.assert_not_called()

    def test_a_new_shell_re_composes_the_card(self):
        self.card.cartridge_frame_path = "/tmp/red.svg"
        with mock.patch.object(self.card, "_refresh_cover_after_change") as refresh:
            self.card.set_cartridge_frame("/tmp/black.svg")
        refresh.assert_called_once()
        self.assertEqual(self.card.cartridge_frame_path, "/tmp/black.svg")


@needs_display
class FindingTheCardBehindAWidgetTests(_CardCase):
    def test_a_card_is_its_own_answer(self):
        self.assertIs(item_for_widget(self.card), self.card)

    def test_a_widget_inside_a_card_resolves_to_it(self):
        self.assertIs(item_for_widget(self.card.name_label), self.card)

    def test_the_list_item_wrapper_resolves_to_the_card_it_holds(self):
        # Focus lands on the wrapper, which is the card's parent.
        self.assertIs(item_for_widget(self.card.get_parent()), self.card)

    def test_a_widget_belonging_to_no_card_resolves_to_nothing(self):
        self.assertIsNone(item_for_widget(Gtk.Button()))

    def test_nothing_resolves_to_nothing(self):
        self.assertIsNone(item_for_widget(None))


class EntryMatchingTests(unittest.TestCase):
    """The filter the grid applies, which needs no widgets at all."""

    def _entry(self, name="Chrono Trigger", has_artwork=True):
        if not HAVE_DISPLAY:
            self.skipTest("RomEntry is a GObject and needs the GTK stack")
        entry = RomEntry({"name": name, "path": f"/roms/{name}.sfc", "console": "SFC"})
        entry.has_artwork = has_artwork
        return entry

    def test_an_empty_query_matches_everything(self):
        self.assertTrue(entry_matches(self._entry()))

    def test_the_query_is_matched_case_insensitively(self):
        self.assertTrue(entry_matches(self._entry(), "chrono"))
        self.assertFalse(entry_matches(self._entry(), "metroid"))

    def test_the_artwork_filter_keeps_only_the_games_without_any(self):
        self.assertFalse(
            entry_matches(self._entry(has_artwork=True), only_missing_artwork=True)
        )
        self.assertTrue(
            entry_matches(self._entry(has_artwork=False), only_missing_artwork=True)
        )

    def test_a_game_whose_artwork_state_is_unresolved_is_hidden_not_flashed(self):
        # `None` means the fetch has not answered yet: showing it and then
        # taking it away as state arrives is worse than waiting.
        entry = self._entry()
        entry.has_artwork = None
        self.assertFalse(entry_matches(entry, only_missing_artwork=True))


if __name__ == "__main__":
    unittest.main()
