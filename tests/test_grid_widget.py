"""The library grid itself: focus, layout, launching and the card lookup.

`ui/grid.py` sat at 75%. Building the window runs the constructor and the
factory, but the parts that only a user reaches were left: following focus
from the window (the cards' wrappers are recycled, so the grid cannot watch
them), the column retune that packs cards on a fixed lattice, the Enter/Menu
keys, and the double-click debounce that stopped a habitual double-click from
producing "a game is already running" on every launch (issue #236).

The grid is the real one on a presented window.
"""

import unittest
from unittest import mock

from tests.gtk_display import HAVE_DISPLAY, needs_display
from tests.window_harness import WindowCase

if HAVE_DISPLAY:
    import gi

    gi.require_version("Gtk", "4.0")
    from gi.repository import Gdk, Gtk

    from openemux.core.library_view import VIEW_MODE_LIST
    from openemux.ui import grid as grid_module
    from openemux.ui.grid import ACTIVATION_DEBOUNCE_US, RomGrid, RomItem
    from openemux.ui.scopes import ALL_CONSOLES_ID


class _GridCase(WindowCase):
    library = {"SFC": [f"Game {index}.sfc" for index in range(6)]}

    def setUp(self):
        super().setUp()
        self.grid = self.show_with_cards("SFC")
        self.entries = self.grid.entries()

    def card(self, index=0):
        card = self.grid.card_for(self.entries[index])
        if card is None:
            self.skipTest("the grid realized no card at that position")
        return card


@needs_display
class FindingACardTests(_GridCase):
    def test_a_bound_entry_has_a_card_on_screen(self):
        self.assertIsNotNone(self.grid.card_for(self.entries[0]))

    def test_a_card_can_be_asked_for_by_position(self):
        self.assertIs(self.grid.card_at(0), self.grid.card_for(self.entries[0]))

    def test_a_position_off_the_end_has_no_card(self):
        self.assertIsNone(self.grid.card_at(999))
        self.assertIsNone(self.grid.card_at(-1))

    def test_the_grid_counts_what_the_filter_lets_through(self):
        self.assertEqual(self.grid.count(), len(self.entries))
        self.grid.set_filter(self.entries[0].rom["name"])
        self.assertEqual(self.grid.count(), 1)

    def test_a_filter_that_matches_nothing_leaves_the_page_empty(self):
        self.grid.set_filter("nothing matches this")
        self.assertEqual(self.grid.count(), 0)

    def test_an_entry_that_is_not_on_this_page_has_no_position(self):
        self.assertIsNone(self.grid._position_of(None))

    def test_a_widget_inside_a_card_resolves_to_it(self):
        card = self.card()
        self.assertIs(RomGrid.item_for_widget(card.name_label), card)


@needs_display
class TheFactoryCallbacksTests(_GridCase):
    """GTK recycles a cell's widget; the bookkeeping has to follow it.

    `Gtk.ListItem` cannot be constructed, so the callbacks are driven with a
    stand-in that answers the three questions they ask of one.
    """

    class _Cell:
        def __init__(self, child=None, item=None):
            self._child = child
            self._item = item

        def get_child(self):
            return self._child

        def get_item(self):
            return self._item

        def set_child(self, child):
            self._child = child

    def test_an_entry_no_longer_on_the_page_has_no_position(self):
        # The filter changed under a lookup started before it.
        entry = self.entries[-1]
        self.grid.set_filter(self.entries[0].rom["name"])
        self.assertIsNone(self.grid._position_of(entry))

    def test_a_cell_with_nothing_in_it_yet_binds_nothing(self):
        self.grid._on_factory_bind(None, self._Cell())
        self.grid._on_factory_bind(None, self._Cell(child=self.card()))

    def test_a_rebind_carries_the_focus_to_the_game_that_landed_there(self):
        # The card kept the focus through the recycle, so the focused *entry*
        # is now whatever was just bound into it.
        card = self.card()
        self.grid._focused_card = card
        self.grid._on_factory_bind(None, self._Cell(card, self.entries[-1]))
        self.assertIs(self.grid._focused_entry, self.entries[-1])

    def test_an_empty_cell_unbinds_nothing(self):
        self.grid._on_factory_unbind(None, self._Cell())

    def test_a_cell_torn_down_releases_the_game_it_was_showing(self):
        card = self.card()
        entry = card.entry
        cell = self._Cell(card, entry)
        self.grid._on_factory_teardown(None, cell)
        self.assertIsNone(card.entry)
        self.assertIsNone(self.grid.card_for(entry))
        self.assertIsNone(cell.get_child())

    def test_an_empty_cell_is_torn_down_all_the_same(self):
        cell = self._Cell()
        self.grid._on_factory_teardown(None, cell)
        self.assertIsNone(cell.get_child())


@needs_display
class FollowingFocusTests(_GridCase):
    def test_the_focused_card_is_the_one_painted_as_focused(self):
        card = self.card()
        root = mock.Mock()
        root.get_focus.return_value = card
        self.grid._on_root_focus_changed(root, None)
        self.assertIs(self.grid._focused_card, card)
        self.assertTrue(card.play_overlay.get_visible())

    def test_moving_the_focus_unpaints_the_card_it_left(self):
        first, second = self.card(0), self.card(1)
        root = mock.Mock()
        root.get_focus.return_value = first
        self.grid._on_root_focus_changed(root, None)
        root.get_focus.return_value = second
        self.grid._on_root_focus_changed(root, None)
        self.assertFalse(first.play_overlay.get_visible())
        self.assertTrue(second.play_overlay.get_visible())

    def test_focus_landing_outside_any_card_paints_nothing(self):
        root = mock.Mock()
        root.get_focus.return_value = Gtk.Button()
        self.grid._on_root_focus_changed(root, None)
        self.assertIsNone(self.grid._focused_card)

    def test_a_card_from_another_page_is_not_ours_to_paint(self):
        card = self.card()
        with mock.patch.object(card, "ctx", object()):
            root = mock.Mock()
            root.get_focus.return_value = card
            self.grid._on_root_focus_changed(root, None)
        self.assertIsNone(self.grid._focused_card)

    def test_the_window_is_watched_only_once(self):
        # The window outlives the grid, so a handler left on it would keep
        # the grid, its cards and their textures alive (issue #218).
        handler = self.grid._root_focus_handler
        self.grid._watch_root_focus()
        self.assertEqual(self.grid._root_focus_handler, handler)

    def test_a_grid_with_no_window_yet_watches_nothing(self):
        loose = RomGrid(
            "SFC", [], None, None, None, None, None, None, None, lambda k, **kw: k, "/tmp"
        )
        loose._watch_root_focus()
        self.assertIsNone(loose._root_focus_handler)

    def test_unmapping_lets_go_of_the_window(self):
        self.grid._unwatch_root_focus()
        self.assertIsNone(self.grid._root_focus_handler)
        self.assertIsNone(self.grid._focused_card)

    def test_unwatching_twice_is_harmless(self):
        self.grid._unwatch_root_focus()
        self.grid._unwatch_root_focus()


@needs_display
class MovingFocusAroundTests(_GridCase):
    def test_a_fresh_grid_remembers_no_card(self):
        self.grid._focused_entry = None
        self.assertFalse(self.grid.has_focus_memory())

    def test_focusing_the_first_card_reports_success(self):
        self.assertTrue(self.grid.focus_first_card())

    def test_focusing_the_last_card_reports_success(self):
        self.assertTrue(self.grid.focus_last_card())

    def test_an_empty_page_has_no_card_to_focus(self):
        self.grid.set_filter("nothing matches this")
        self.assertFalse(self.grid.focus_first_card())

    def test_restoring_goes_back_to_the_card_the_user_was_on(self):
        self.grid._focused_entry = self.entries[2]
        self.assertTrue(self.grid.focus_restore())
        self.assertTrue(self.grid.has_focus_memory())

    def test_restoring_with_no_memory_falls_back_to_the_first_card(self):
        self.grid._focused_entry = None
        self.assertTrue(self.grid.focus_restore())

    def test_a_card_that_is_off_screen_is_scrolled_to_first(self):
        # A virtualized grid has no widget to grab until the scroll builds it.
        with mock.patch.object(
            self.grid, "_grab_focus_on", return_value=False
        ), mock.patch.object(self.grid, "scroll_to") as scroll, mock.patch.object(
            grid_module.GLib, "idle_add"
        ) as idle_add:
            self.assertTrue(self.grid._focus_position(0))
        scroll.assert_called_once()
        self.assertEqual(idle_add.call_args[0][0], self.grid._grab_focus_when_realized)

    def test_the_retry_after_a_scroll_never_repeats(self):
        self.assertFalse(self.grid._grab_focus_when_realized(self.entries[0]))

    def test_an_entry_with_no_card_cannot_be_focused(self):
        self.assertFalse(self.grid._grab_focus_on(object()))


@needs_display
class LaunchingFromTheGridTests(_GridCase):
    def test_activating_a_card_launches_its_game(self):
        with mock.patch.object(self.win.game, "launch") as launch:
            self.grid._launch_rom(self.entries[0].rom)
        launch.assert_called_once()

    def test_the_second_half_of_a_double_click_is_swallowed(self):
        # Issue #236: the second launch is refused with an error toast, so a
        # habitual double-click reported "a game is already running".
        rom = self.entries[0].rom
        with mock.patch.object(self.win.game, "launch") as launch:
            self.grid._launch_rom(rom)
            self.grid._launch_rom(rom)
        launch.assert_called_once()

    def test_a_deliberate_relaunch_later_goes_through(self):
        rom = self.entries[0].rom
        with mock.patch.object(self.win.game, "launch") as launch:
            self.grid._launch_rom(rom)
            self.grid._last_activation = (
                rom["path"],
                grid_module.GLib.get_monotonic_time() - ACTIVATION_DEBOUNCE_US - 1,
            )
            self.grid._launch_rom(rom)
        self.assertEqual(launch.call_count, 2)

    def test_a_different_game_is_never_swallowed(self):
        with mock.patch.object(self.win.game, "launch") as launch:
            self.grid._launch_rom(self.entries[0].rom)
            self.grid._launch_rom(self.entries[1].rom)
        self.assertEqual(launch.call_count, 2)

    def test_launching_nothing_at_all_does_nothing(self):
        with mock.patch.object(self.win.game, "launch") as launch:
            self.grid._launch_rom(None)
        launch.assert_not_called()


@needs_display
class TheGridKeysTests(_GridCase):
    def press(self, keyval, state=0):
        return self.grid._on_grid_key_pressed(None, keyval, 0, state)

    def _focus(self, card):
        patcher = mock.patch.object(self.win, "get_focus", return_value=card)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_key_the_grid_does_not_claim_is_left_to_gtk(self):
        self.assertFalse(self.press(Gdk.KEY_a))

    def test_enter_launches_the_focused_game(self):
        card = self.card()
        self._focus(card)
        with mock.patch.object(self.grid, "_launch_rom") as launch:
            self.assertTrue(self.press(Gdk.KEY_Return))
        launch.assert_called_once_with(card.rom)

    def test_space_launches_it_too(self):
        self._focus(self.card())
        with mock.patch.object(self.grid, "_launch_rom") as launch:
            self.assertTrue(self.press(Gdk.KEY_space))
        launch.assert_called_once()

    def test_enter_with_a_modifier_is_a_selection_gesture_not_a_launch(self):
        self._focus(self.card())
        self.assertFalse(self.press(Gdk.KEY_Return, Gdk.ModifierType.CONTROL_MASK))
        self.assertFalse(self.press(Gdk.KEY_space, Gdk.ModifierType.SHIFT_MASK))

    def test_the_menu_key_opens_the_context_menu(self):
        card = self.card()
        self._focus(card)
        with mock.patch.object(card, "show_context_menu") as show:
            self.assertTrue(self.press(Gdk.KEY_Menu))
        show.assert_called_once()

    def test_shift_f10_opens_it_too(self):
        card = self.card()
        self._focus(card)
        with mock.patch.object(card, "show_context_menu") as show:
            self.assertTrue(self.press(Gdk.KEY_F10, Gdk.ModifierType.SHIFT_MASK))
        show.assert_called_once()

    def test_a_key_with_no_card_focused_is_left_to_gtk(self):
        self._focus(Gtk.Button())
        self.assertFalse(self.press(Gdk.KEY_Return))


@needs_display
class RefreshingOneCardTests(_GridCase):
    def test_a_cover_change_re_fetches_only_that_card(self):
        card = self.card()
        with mock.patch.object(card, "_refresh_cover_after_change") as refresh:
            self.assertTrue(self.grid.refresh_rom_artwork(card.rom, fade=True))
        refresh.assert_called_once_with(fade=True)

    def test_a_game_that_is_not_on_this_page_is_not_refreshed(self):
        self.assertFalse(self.grid.refresh_rom_artwork({"path": "/nowhere.sfc"}))

    def test_a_game_off_screen_has_its_artwork_state_dropped_instead(self):
        entry = self.entries[0]
        with mock.patch.object(self.grid, "_bound", {}):
            self.grid.refresh_rom_artwork(entry.rom)
        self.assertIsNone(entry.has_artwork)

    def test_a_page_that_is_not_a_cartridge_shelf_re_frames_nothing(self):
        with mock.patch.object(self.grid, "_base_frame_path", None):
            self.assertFalse(self.grid.refresh_rom_frame(self.entries[0].rom))

    def test_a_game_that_is_not_on_this_page_is_not_re_framed(self):
        self.assertFalse(self.grid.refresh_rom_frame({"path": "/nowhere.sfc"}))

    def test_a_shell_colour_change_re_composes_the_card_on_screen(self):
        card = self.card()
        with mock.patch.object(self.grid, "_base_frame_path", "/tmp/base.svg"):
            with mock.patch.object(card, "set_cartridge_frame") as set_frame:
                self.assertTrue(self.grid.refresh_rom_frame(card.rom))
        set_frame.assert_called_once()

    def test_a_page_with_no_shell_resolves_no_frame(self):
        with mock.patch.object(self.grid, "_base_frame_path", None):
            self.assertIsNone(self.grid._frame_path_for_rom(self.entries[0].rom))

    def test_a_game_off_screen_forgets_its_remembered_art_too(self):
        entry = self.entries[0]
        entry.art_path = "/roms/SFC/covers/Game.png"
        with mock.patch.object(self.grid, "_bound", {}):
            self.grid.refresh_rom_artwork(entry.rom)
        self.assertIs(entry.art_path, grid_module.ART_UNRESOLVED)

    def test_a_shell_colour_is_resolved_once_per_grid(self):
        # Issue 907: two file probes and a frame stat per bind, for a frame
        # that never changes while the app runs.
        with mock.patch.object(self.grid, "_base_frame_path", "/tmp/base.svg"), mock.patch.object(
            self.grid, "_frame_color_for_rom", return_value="red"
        ), mock.patch.object(
            grid_module, "cartridge_frame_svg", return_value="/tmp/base-red.svg"
        ) as resolve:
            for entry in self.entries:
                self.assertEqual(self.grid._frame_path_for_rom(entry.rom), "/tmp/base-red.svg")
        resolve.assert_called_once()

    def test_a_page_with_no_colour_lookup_uses_the_console_shell(self):
        with mock.patch.object(self.grid, "_base_frame_path", "/tmp/base.svg"):
            with mock.patch.object(self.grid, "_frame_color_for_rom", None):
                self.assertEqual(
                    self.grid._frame_path_for_rom(self.entries[0].rom),
                    "/tmp/base.svg",
                )


@needs_display
class TheColumnLatticeTests(_GridCase):
    def test_the_width_it_lays_out_in_is_its_own_when_none_is_given(self):
        # The retune is also called from the size-allocate, which has one.
        self.assertEqual(
            self.grid._available_width(), self.grid._available_width(self.grid.get_width())
        )

    """GtkGridView spreads its width between its columns; this takes it back."""

    def test_a_degenerate_allocation_is_not_passed_on(self):
        # The content stack hands one out for a frame while it swaps pages.
        with mock.patch.object(Gtk.GridView, "do_size_allocate") as allocate:
            self.grid.do_size_allocate(0, 100, -1)
            self.grid.do_size_allocate(100, 0, -1)
        allocate.assert_not_called()

    def test_a_real_allocation_retunes_the_columns_first(self):
        with mock.patch.object(Gtk.GridView, "do_size_allocate"):
            with mock.patch.object(self.grid, "_retune_columns") as retune:
                self.grid.do_size_allocate(1200, 800, -1)
        retune.assert_called_once_with(1200)

    def test_a_width_no_card_fits_in_is_answered_honestly(self):
        # A zero here becomes a screenful of "needs at least 216" warnings.
        minimum, natural, min_baseline, nat_baseline = self.grid.do_measure(
            Gtk.Orientation.VERTICAL, 1
        )
        self.assertGreaterEqual(minimum, 0)
        del natural, min_baseline, nat_baseline

    def test_a_width_has_no_baseline(self):
        _min, _nat, min_baseline, nat_baseline = self.grid.do_measure(
            Gtk.Orientation.HORIZONTAL, -1
        )
        self.assertEqual((min_baseline, nat_baseline), (-1, -1))

    def test_the_columns_are_retuned_to_what_the_width_calls_for(self):
        self.grid._column_state = None
        with mock.patch.object(grid_module.GLib, "idle_add"):
            self.grid._retune_columns(1200)
        self.assertIsNotNone(self.grid._column_state)
        self.assertEqual(self.grid.get_min_columns(), self.grid.get_max_columns())

    def test_an_unchanged_width_retunes_nothing(self):
        with mock.patch.object(grid_module.GLib, "idle_add"):
            self.grid._retune_columns(1200)
            state = self.grid._column_state
            self.grid._retune_columns(1200)
        self.assertEqual(self.grid._column_state, state)

    def test_a_narrower_page_takes_the_column_count_down(self):
        with mock.patch.object(grid_module.GLib, "idle_add"):
            self.grid._retune_columns(2000)
            wide = self.grid._column_state[0]
            self.grid._retune_columns(400)
            narrow = self.grid._column_state[0]
        self.assertLessEqual(narrow, wide)

    def test_a_page_with_no_width_yet_retunes_nothing(self):
        self.grid._column_state = None
        self.grid._retune_columns(0)
        self.assertIsNone(self.grid._column_state)

    def test_a_list_row_page_leaves_the_columns_alone(self):
        with mock.patch.object(self.grid, "compact", True):
            self.grid._column_state = None
            self.grid._retune_columns(1200)
        self.assertIsNone(self.grid._column_state)

    def test_the_available_width_adds_back_the_slack_parked_on_the_margin(self):
        self.grid.set_margin_end(self.grid._margin + 40)
        self.assertEqual(self.grid._available_width(1000), 1040)

    def test_a_page_with_no_allocation_has_no_width_to_offer(self):
        self.assertEqual(self.grid._available_width(0), 0)

    def test_the_card_width_is_measured_once_and_kept(self):
        self.grid._measured_card_width = None
        width = self.grid._card_allocation_width()
        self.assertEqual(self.grid._card_allocation_width(), width)

    def test_before_any_card_exists_a_probe_card_is_measured_instead(self):
        # Issue 899: the nominal width packed the columns a padding too
        # tight, and a sleeping grid's height follows the column count, so
        # the count has to be right before the first card exists.
        self.grid._measured_card_width = None
        with mock.patch.object(self.grid, "_bound", {}):
            probed = self.grid._card_allocation_width()
        self.grid._measured_card_width = None
        self.assertEqual(probed, self.grid._card_allocation_width())
        self.assertGreaterEqual(probed, self.grid._card_size[0])


@needs_display
class SleepingAndWakingTests(_GridCase):
    """A grid that let go of its model (issues 899 and 900)."""

    def test_a_sleeping_grid_has_no_cards_and_no_model_on_the_view(self):
        self.grid.set_dormant(True)
        self.pump()
        self.assertTrue(self.grid.is_dormant())
        self.assertIsNone(self.grid.get_model())
        self.assertEqual(self.grid.bound_cards(), [])

    def test_asleep_it_still_measures_as_tall_as_its_rows(self):
        width = self.grid.get_width()
        awake = self.grid.measure(Gtk.Orientation.VERTICAL, width)[1]
        self.grid.set_dormant(True)
        asleep = self.grid.measure(Gtk.Orientation.VERTICAL, width)[1]
        self.assertEqual(asleep, awake)

    def _margins(self, grid=None):
        grid = grid or self.grid
        return grid.get_margin_top() + grid.get_margin_bottom()

    def test_asleep_with_an_unknown_width_it_keeps_the_last_column_count(self):
        self.grid.set_dormant(True)
        columns = self.grid._column_state[0]
        rows = -(-len(self.entries) // columns)
        self.assertEqual(
            self.grid.measure(Gtk.Orientation.VERTICAL, -1)[1],
            rows * self.grid._row_height() + self._margins(),
        )

    def test_asleep_before_any_layout_it_counts_one_column(self):
        self.grid.set_dormant(True)
        self.grid._column_state = None
        self.assertEqual(self.grid._columns_for(-1), 1)
        self.assertEqual(self.grid._columns_for(0), 1)

    def test_a_sleeping_grid_with_nothing_to_show_is_flat(self):
        self.grid.set_dormant(True)
        self.grid.set_filter("nothing matches this")
        self.assertEqual(
            self.grid.measure(Gtk.Orientation.VERTICAL, -1)[1], self._margins()
        )

    def test_a_list_asleep_is_one_row_per_game(self):
        self.win._apply_view_mode(VIEW_MODE_LIST)
        grid = self.show_with_cards("SFC")
        grid.set_dormant(True)
        self.assertEqual(
            grid.measure(Gtk.Orientation.VERTICAL, -1)[1],
            len(grid.entries()) * grid._row_height() + self._margins(grid),
        )

    def test_waking_builds_the_cards_again(self):
        self.grid.set_dormant(True)
        self.pump()
        self.grid.set_dormant(False)
        self.assertTrue(
            self.pump_until(lambda: self.grid.card_for(self.entries[0]) is not None)
        )

    def test_sleeping_twice_and_waking_twice_are_no_ops(self):
        self.grid.set_dormant(False)
        self.grid.set_dormant(True)
        with mock.patch.object(self.grid, "set_model") as set_model:
            self.grid.set_dormant(True)
        set_model.assert_not_called()

    def test_waking_puts_the_page_back_where_it_was(self):
        vadj = self.grid.get_vadjustment()
        self.grid.set_dormant(True)
        self.grid._sleep_scroll = 50.0
        with mock.patch.object(vadj, "get_upper", return_value=1000.0), mock.patch.object(
            vadj, "get_page_size", return_value=100.0
        ), mock.patch.object(vadj, "set_value") as set_value:
            self.grid.set_dormant(False)
            self.pump()
        set_value.assert_called_with(50.0)
        self.assertIsNone(self.grid._restore_source)

    def test_a_restore_with_nowhere_to_scroll_is_left_alone(self):
        self.grid._sleep_scroll = None
        self.grid._restore_sleep_scroll()
        self.grid._sleep_scroll = 50.0
        self.grid._awake = False
        with mock.patch.object(self.grid.get_vadjustment(), "set_value") as set_value:
            self.grid._restore_sleep_scroll()
        set_value.assert_not_called()
        self.grid._awake = True
        with mock.patch.object(self.grid, "get_vadjustment", return_value=None):
            self.grid._restore_sleep_scroll()

    def test_leaving_the_page_puts_the_grid_to_sleep_and_coming_back_wakes_it(self):
        # Issue 900: ten console visits used to add about 9 MB each.
        self.win.sidebar.select(ALL_CONSOLES_ID)
        self.assertTrue(self.pump_until(self.grid.is_dormant))
        self.win.sidebar.select("SFC")
        self.assertTrue(self.pump_until(lambda: not self.grid.is_dormant()))

    def test_focusing_a_card_of_a_sleeping_grid_wakes_it(self):
        self.grid.set_dormant(True)
        self.pump()
        self.assertTrue(self.grid.focus_first_card())
        self.assertFalse(self.grid.is_dormant())

    def test_the_cards_on_screen_are_the_ones_overlapping_the_allocation(self):
        visible = self.grid.visible_cards()
        self.assertIn(self.card(), visible)
        with mock.patch.object(self.grid, "get_height", return_value=0):
            self.assertEqual(self.grid.visible_cards(), [])

    def test_a_card_whose_wrapper_is_gone_is_not_on_screen(self):
        loose = RomItem(self.grid._card_ctx)
        with mock.patch.object(self.grid, "_bound", {self.entries[0]: loose}):
            self.assertEqual(self.grid.visible_cards(), [])

    def test_a_card_whose_bounds_cannot_be_computed_is_not_on_screen(self):
        card = self.card()
        with mock.patch.object(
            Gtk.Widget, "compute_bounds", return_value=(False, None)
        ):
            self.assertNotIn(card, self.grid.visible_cards())

    def test_a_layout_promotes_the_fetches_of_the_cards_on_screen_once(self):
        # Issue 899: the visible cards used to wait behind the rows GTK keeps
        # around them.
        card = self.card()
        self.grid._promotion_pending = False
        with mock.patch.object(card, "promote_pending_fetch") as promote, mock.patch.object(
            grid_module.GLib, "idle_add", side_effect=lambda fn: fn()
        ) as idle_add:
            self.grid._queue_fetch_promotion()
            self.grid._promotion_pending = True
            self.grid._queue_fetch_promotion()
        self.assertEqual(idle_add.call_count, 1)
        promote.assert_called_once()

    def test_a_grid_with_no_cards_queues_no_promotion(self):
        with mock.patch.object(self.grid, "_bound", {}), mock.patch.object(
            grid_module.GLib, "idle_add"
        ) as idle_add:
            self.grid._queue_fetch_promotion()
        idle_add.assert_not_called()

    def test_tearing_down_lets_go_of_the_entries_and_the_cards(self):
        self.grid._restore_source = grid_module.GLib.idle_add(lambda: False)
        self.grid.teardown()
        self.assertTrue(self.grid.is_dormant())
        self.assertEqual(self.grid.entries(), [])
        self.assertEqual(self.grid.count(), 0)
        self.assertEqual(self.grid.bound_cards(), [])
        self.assertIsNone(self.grid._restore_source)
        self.assertIsNone(self.grid._probe)

    def test_a_cartridge_grid_grows_its_slot_by_the_shadow_margin_and_gives_it_back(self):
        # Issue 903: the composite carries its shadow in a transparent
        # margin; the lattice must not move for it.
        from openemux.core import cartridge_render
        from openemux.core.library_view import scale_length
        from openemux.ui.card_layout import FIXED_ITEM_WIDTH, GRID_MARGIN, GRID_SPACING

        grid = self.grid
        if not grid._base_frame_path:
            self.skipTest("this page draws covers, not cartridges")
        pad = grid_module.CARTRIDGE_SHADOW_PAD
        self.assertEqual(grid._shadow_pad, pad)
        frame = cartridge_render.load_frame(grid._base_frame_path)
        width, height = frame.size_for_width(scale_length(FIXED_ITEM_WIDTH, grid.zoom))
        self.assertEqual(grid._card_ctx.cover_size, (width + 2 * pad, height + 2 * pad))
        self.assertEqual(grid._card_ctx.shadow_pad, pad)
        self.assertEqual(grid._spacing, max(0, GRID_SPACING - 2 * pad))
        self.assertEqual(grid._margin, max(0, GRID_MARGIN - grid._card_margin - pad))

    def test_the_cards_render_their_composites_at_the_display_scale(self):
        # Issue 902: 2x on every monitor, four times the pixels of a 1x card.
        self.assertEqual(self.grid._card_ctx.render_scale, grid_module.cartridge_render_scale(self.grid))
        self.assertEqual(grid_module.cartridge_render_scale(self.grid), max(1, self.grid.get_scale_factor()))

    def test_a_widget_that_cannot_say_its_scale_renders_at_the_fallback(self):
        widget = mock.Mock()
        widget.get_scale_factor.side_effect = RuntimeError("no display")
        self.assertEqual(grid_module.cartridge_render_scale(widget), grid_module.CARTRIDGE_RENDER_SCALE)
        widget.get_scale_factor.side_effect = None
        widget.get_scale_factor.return_value = 0
        self.assertEqual(grid_module.cartridge_render_scale(widget), 1)

    def test_every_card_built_is_counted(self):
        before = grid_module.cards_built()
        self.grid._on_factory_setup(None, mock.Mock())
        self.assertEqual(grid_module.cards_built(), before + 1)


@needs_display
class TheArtworkFilterTests(_GridCase):
    def test_a_burst_of_cards_resolving_is_coalesced_onto_one_pass(self):
        # Issue #127: re-filtering per card would walk the whole page N times.
        self.grid._artwork_filter_pending = False
        with mock.patch.object(grid_module.GLib, "idle_add") as idle_add:
            self.grid._on_entry_artwork_state(self.entries[0])
            self.grid._on_entry_artwork_state(self.entries[1])
        idle_add.assert_called_once()

    def test_the_pass_re_filters_only_while_the_filter_is_on(self):
        self.grid._only_missing_artwork = False
        with mock.patch.object(self.grid._filter, "changed") as changed:
            self.grid._flush_artwork_filter()
        changed.assert_not_called()

    def test_with_the_filter_on_the_page_is_re_filtered(self):
        self.grid.set_filter(only_missing_artwork=True)
        with mock.patch.object(self.grid._filter, "changed") as changed:
            self.grid._flush_artwork_filter()
        self.assertTrue(changed.called)


@needs_display
class TheSelectionDelegatesTests(_GridCase):
    """The grid hands every selection verb to its `GridSelection`."""

    def test_every_verb_reaches_the_selection(self):
        for name, args in (
            ("clear_selection", ()),
            ("select_all", ()),
            ("toggle_select_all", ()),
            ("sync_visible_selection", ()),
            ("selected_roms", ()),
        ):
            getattr(self.grid, name)(*args)

    def test_the_item_verbs_reach_it_too(self):
        entry = self.entries[0]
        self.grid.select_item(entry)
        self.assertTrue(entry.selected)
        self.grid.toggle_item(entry)
        self.assertFalse(entry.selected)
        self.grid.begin_range_from(entry)
        self.grid.extend_selection_to(self.entries[1])
        self.assertTrue(self.grid.selected_roms())
        self.grid.note_cursor(entry, keep_anchor=True)

    def test_the_page_paints_its_band_when_it_draws(self):
        with mock.patch.object(self.grid.selection, "draw") as draw:
            self.grid.do_snapshot(Gtk.Snapshot())
        draw.assert_called_once()


if __name__ == "__main__":
    unittest.main()
