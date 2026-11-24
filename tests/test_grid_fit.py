"""Big Picture's games grid fills the width with large cards (issue 1000).

The desktop grid draws its cards at the zoom's size and parks what the last
column did not take on the end margin. In Big Picture that left an empty
strip as wide as almost a whole card on the right. There the grid takes as
many columns of the 200% card as fit, then widens the cards so those
columns reach the far margin: ``fit_card_width`` is the arithmetic, the
rest is ``RomGrid`` rebuilding its cards at the size the width calls for.
"""

import unittest
from unittest import mock

from openemux.ui.card_layout import (
    CONSOLE_COVER_ASPECTS,
    FIT_WIDTH_STEP,
    GRID_SPACING,
    cover_size_for_console,
    cover_size_for_width,
    fit_card_width,
    uniform_slot_size,
)
from tests.gtk_display import HAVE_DISPLAY, needs_display

if HAVE_DISPLAY:
    from tests.bigpicture_harness import BigPictureCase, GLib
    from openemux.ui import grid as grid_module
    from openemux.ui.grid import REFIT_DELAY_MS, RomGrid
    from openemux.ui.scopes import ALL_CONSOLES_ID
else:  # pragma: no cover - the widget tests are skipped without a display
    BigPictureCase = unittest.TestCase

CARD = 416  # a 400 px cartridge plus the card's padding


def cells(columns, card=CARD, spacing=GRID_SPACING):
    return columns * (card + spacing)


class FitCardWidthTests(unittest.TestCase):
    def test_an_exact_fit_takes_the_columns_and_grows_nothing(self):
        self.assertEqual(fit_card_width(cells(3), CARD), (3, 0))

    def test_the_leftover_is_shared_between_the_cards(self):
        # Almost a fourth card left over, as on the maintainer's screen.
        columns, growth = fit_card_width(cells(4) - 1, CARD)
        self.assertEqual(columns, 3)
        self.assertGreater(growth, 0)
        # The grown cells never take more than the width there is...
        self.assertLessEqual(columns * (CARD + growth + GRID_SPACING), cells(4) - 1)
        # ...and leave less than a step per column over.
        self.assertLess(cells(4) - 1 - columns * (CARD + growth + GRID_SPACING),
                        columns * FIT_WIDTH_STEP)

    def test_the_growth_comes_in_whole_steps(self):
        for available in range(cells(2), cells(3), 7):
            _columns, growth = fit_card_width(available, CARD)
            self.assertEqual(growth % FIT_WIDTH_STEP, 0)

    def test_the_cards_are_never_drawn_smaller_than_the_floor(self):
        for available in (1, 100, CARD, cells(1), cells(2) - 1, cells(5) + 3):
            _columns, growth = fit_card_width(available, CARD)
            self.assertGreaterEqual(growth, 0)

    def test_a_window_narrower_than_a_card_still_has_one_column(self):
        self.assertEqual(fit_card_width(200, CARD), (1, 0))

    def test_a_wider_window_takes_a_column_before_it_grows_past_one(self):
        self.assertEqual(fit_card_width(cells(4), CARD)[0], 4)

    def test_a_step_of_zero_is_taken_as_one(self):
        self.assertEqual(fit_card_width(cells(3) + 5, CARD, step=0), (3, 1))


class CoverSizeForWidthTests(unittest.TestCase):
    def test_it_keeps_the_console_s_proportions(self):
        width, height = cover_size_for_width("PS", 520)
        self.assertEqual((width, height), (520, round(520 / CONSOLE_COVER_ASPECTS["PS"])))

    def test_a_page_mixing_consoles_gets_the_uniform_slot_s_shape(self):
        self.assertEqual(cover_size_for_width("SFC", 400, mixed_consoles=True), (400, 350))
        self.assertEqual(cover_size_for_width("SFC", 400, mixed_consoles=True),
                         uniform_slot_size(2.0))

    def test_the_zoom_s_size_is_the_same_as_before(self):
        self.assertEqual(cover_size_for_console("FC", 2.0), cover_size_for_width("FC", 400))

    def test_a_console_with_no_aspect_is_square(self):
        self.assertEqual(cover_size_for_width("NOPE", 300), (300, 300))

    def test_a_zero_aspect_falls_back_to_a_square(self):
        with mock.patch.dict(CONSOLE_COVER_ASPECTS, {"SFC": 0}):
            self.assertEqual(cover_size_for_width("SFC", 300), (300, 300))


@needs_display
class _FitCase(BigPictureCase):
    library = {
        "SFC": [f"Game {index:02d}.sfc" for index in range(30)],
        "GBA": ["Lonely.gba"],
    }

    def setUp(self):
        super().setUp()
        RomGrid._fit_viewport = None
        self.addCleanup(setattr, RomGrid, "_fit_viewport", None)

    def show(self):
        # Wide enough for several columns of the 200% card whatever display
        # the suite runs on: CI's Xvfb screen is far smaller than a TV.
        self.win.set_size_request(1920, 1080)
        self.addCleanup(self.win.set_size_request, -1, -1)
        super().show()

    def open_grid(self, console="SFC"):
        self.show()
        self.shell.open_library(console)
        grid = self.win.pages.grid_for(console)
        self.assertTrue(self.pump_until(
            lambda: grid.get_width() > 0 and grid._refit_source is None
            and grid._column_state is not None and bool(grid._bound)
        ))
        self.pump()
        return grid


class FillingTheRowTests(_FitCase):
    def test_a_big_picture_grid_sizes_its_cards_from_the_width(self):
        grid = self.open_grid()
        self.assertTrue(grid._fit_width)
        columns, growth = grid._growth_for(grid._available_width())
        self.assertEqual(grid._growth, growth)
        self.assertEqual(grid._column_state[0], columns)

    def test_a_full_row_parks_nothing_on_the_end_margin(self):
        grid = self.open_grid()
        self.assertEqual(grid._column_state[1], 0)
        available = grid._available_width()
        columns = grid._column_state[0]
        cell = grid._min_card_allocation_width() + grid._growth + grid._spacing
        # What is left right of the last column is less than a gap.
        self.assertLess(available - columns * cell, grid._spacing)

    def test_the_cards_are_never_smaller_than_the_zoom_s(self):
        grid = self.open_grid()
        self.assertGreaterEqual(grid._card_size[0], grid._base_artwork_width)
        self.assertGreaterEqual(grid._card_allocation_width(), grid._min_card_allocation_width())

    def test_the_cards_are_built_at_the_grown_size(self):
        grid = self.open_grid()
        card = next(iter(grid._bound.values()))
        self.assertEqual(card.card_size, grid._card_size)

    def test_a_page_with_fewer_games_than_columns_keeps_the_size_and_the_slack(self):
        grid = self.open_grid("GBA")
        self.assertEqual(grid._column_state[0], 1)
        self.assertGreater(grid._column_state[1], 0)

    def test_the_sleeping_height_counts_the_fitted_columns(self):
        grid = self.open_grid()
        width = grid.get_width()
        self.assertEqual(grid._columns_for(width), grid._column_state[0])

    def test_a_list_page_is_not_fitted(self):
        grid = self.open_grid()
        with mock.patch.object(grid, "compact", True):
            self.assertEqual(grid._columns_for(1200), 1)
        self.shell.library.set_view("list")
        self.pump()
        self.assertFalse(self.win.pages.grid_for("SFC")._fit_width)

    def test_the_next_grid_is_built_at_the_size_the_last_one_found(self):
        grid = self.open_grid()
        self.assertIsNotNone(RomGrid._fit_viewport)
        RomGrid._fit_viewport = 2 * (grid._available_width() + 2 * grid._margin)
        fresh = RomGrid(
            "SFC", [], None, None, None, None, None, None, None, lambda k, **kw: k, "/tmp",
            ui_settings=self.win.display_settings_for("SFC"),
        )
        self.assertGreater(fresh._growth, 0)
        fresh.teardown()

    def test_the_desktop_grid_is_never_fitted(self):
        self.leave()
        grid = self.show_with_cards("SFC")
        self.assertFalse(grid._fit_width)
        self.assertEqual(grid._growth, 0)


class FitColumnsTests(_FitCase):
    def test_a_new_growth_schedules_a_rebuild(self):
        grid = self.open_grid()
        with mock.patch.object(grid, "_schedule_refit") as schedule:
            grid._fit_columns(grid._available_width() + 600)
        schedule.assert_called_once()

    def test_coming_back_to_the_current_size_cancels_the_rebuild(self):
        grid = self.open_grid()
        grid._refit_source = GLib.timeout_add(60_000, lambda: False)
        grid._fit_columns(grid._available_width())
        self.assertIsNone(grid._refit_source)

    def test_the_first_rebuild_runs_at_once_the_later_ones_wait(self):
        grid = self.open_grid()
        grid._refitted = False
        with mock.patch.object(grid_module.GLib, "timeout_add", return_value=7) as timeout:
            grid._schedule_refit(8)
        self.assertEqual(timeout.call_args[0][0], 0)
        grid._refitted = True
        with mock.patch.object(grid_module.GLib, "timeout_add", return_value=8) as timeout, \
                mock.patch.object(grid_module.GLib, "source_remove") as remove:
            grid._schedule_refit(12)
        remove.assert_called_once_with(7)
        self.assertEqual(timeout.call_args[0][0], REFIT_DELAY_MS)
        self.assertEqual(grid._pending_growth, 12)
        grid._refit_source = None

    def test_the_rebuild_runs_with_the_last_growth_asked_for(self):
        grid = self.open_grid()
        grid._pending_growth = grid._growth + 8
        with mock.patch.object(grid, "refit") as refit:
            self.assertEqual(grid._run_refit(), GLib.SOURCE_REMOVE)
        refit.assert_called_once_with(grid._pending_growth)
        self.assertTrue(grid._refitted)

    def test_a_shrinking_window_never_asks_for_more_than_the_cards_fit(self):
        # Review of PR 1008: until the rebuild, the cards keep their width.
        grid = self.open_grid()
        grid._growth = 400
        available = grid._available_width()
        with mock.patch.object(grid, "_schedule_refit"):
            columns, _slack = grid._fit_columns(available)
        cell = grid._min_card_allocation_width() + 400 + grid._spacing
        self.assertLessEqual(columns * cell, max(cell, available))

    def test_the_sleeping_groups_wait_for_the_width_to_settle(self):
        grid = self.open_grid()
        grid._refitted = True
        with mock.patch.object(grid_module.GLib, "timeout_add", side_effect=[5, 6]) as timeout, \
                mock.patch.object(grid_module.GLib, "source_remove") as remove:
            grid._schedule_siblings()
            grid._schedule_siblings()
        remove.assert_called_once_with(5)
        self.assertEqual(timeout.call_args[0][0], REFIT_DELAY_MS)
        self.assertEqual(grid._siblings_source, 6)
        grid._siblings_source = None

    def test_a_torn_down_grid_touches_nothing_from_its_idles(self):
        grid = self.open_grid()
        siblings = GLib.timeout_add(60_000, lambda: False)
        grid._siblings_source = siblings
        with mock.patch.object(grid_module.GLib, "source_remove") as remove:
            grid.teardown()
        remove.assert_any_call(siblings)
        GLib.source_remove(siblings)
        self.assertIsNone(grid._siblings_source)
        with mock.patch.object(grid, "get_parent") as parent:
            self.assertEqual(grid._fit_sleeping_siblings(), GLib.SOURCE_REMOVE)
        parent.assert_not_called()
        with mock.patch.object(grid, "get_vadjustment") as vadj:
            self.assertEqual(grid._restore_anchor((0, 0.0)), GLib.SOURCE_REMOVE)
        vadj.assert_not_called()
        with mock.patch.object(grid, "_take_focus_back") as focus:
            grid._refocus_after_refit(object())
        focus.assert_not_called()

    def test_tearing_down_cancels_a_waiting_rebuild(self):
        grid = self.open_grid()
        source = GLib.timeout_add(60_000, lambda: False)
        grid._refit_source = source
        with mock.patch.object(grid_module.GLib, "source_remove") as remove:
            grid.teardown()
        remove.assert_any_call(source)
        self.assertIsNone(grid._refit_source)
        GLib.source_remove(source)


class RefittingTests(_FitCase):
    def test_the_same_growth_rebuilds_nothing(self):
        grid = self.open_grid()
        self.assertFalse(grid.refit(grid._growth))

    def test_a_new_growth_rebuilds_the_cards_at_that_size(self):
        grid = self.open_grid()
        width = grid._card_size[0]
        self.assertTrue(grid.refit(grid._growth + 8))
        self.assertEqual(grid._card_size[0], width + 8)
        self.pump()
        self.assertTrue(self.pump_until(lambda: bool(grid._bound)))
        card = next(iter(grid._bound.values()))
        self.assertEqual(card.card_size, grid._card_size)

    def test_the_focused_game_keeps_the_focus(self):
        grid = self.open_grid()
        entry = grid.visible_entries()[4]
        grid._focus_position(4)
        self.assertTrue(self.pump_until(lambda: grid._focused_entry is entry
                                        and grid._focused_card is not None))
        grid.refit(grid._growth + 8)
        self.assertTrue(self.pump_until(
            lambda: grid._focused_card is not None and grid._focused_card.entry is entry
        ))

    def test_a_scrolled_page_keeps_the_row_at_the_top(self):
        grid = self.open_grid()
        vadj = grid.get_vadjustment()
        row = grid._row_height()
        self.assertTrue(self.pump_until(lambda: vadj.get_upper() > vadj.get_page_size() + row))
        vadj.set_value(row * 1.5)
        grid._focused_card = None
        columns = grid._column_state[0]
        with mock.patch.object(grid_module.GLib, "idle_add") as idle:
            grid.refit(grid._growth + 8)
        callback, anchor = idle.call_args[0]
        self.assertEqual(anchor[0], columns)
        self.assertAlmostEqual(anchor[1], 0.5)
        self.pump()
        grid._column_state = (columns, 0)
        self.assertEqual(callback(anchor), GLib.SOURCE_REMOVE)
        expected = min(1.5 * grid._row_height(), vadj.get_upper() - vadj.get_page_size())
        self.assertAlmostEqual(vadj.get_value(), expected, delta=1)

    def test_the_anchor_counts_the_columns_the_width_calls_for_before_the_relayout(self):
        # Review of PR 1008: restoring before the relayout used to count one.
        grid = self.open_grid()
        vadj = mock.Mock()
        vadj.get_upper.return_value = 100_000
        vadj.get_page_size.return_value = 100
        grid._column_state = None
        columns = grid._columns_for(grid.get_width())
        self.assertGreater(columns, 1)
        with mock.patch.object(grid, "get_vadjustment", return_value=vadj), \
                mock.patch.object(grid, "_row_height", return_value=100):
            grid._restore_anchor((columns, 0.5))
        vadj.set_value.assert_called_once_with(150.0)

    def test_an_unscrolled_page_has_no_anchor(self):
        grid = self.open_grid()
        grid.get_vadjustment().set_value(0)
        self.assertIsNone(grid._scroll_anchor())

    def test_a_row_with_no_height_has_no_anchor(self):
        grid = self.open_grid()
        vadj = mock.Mock()
        vadj.get_value.return_value = 10
        with mock.patch.object(grid, "get_vadjustment", return_value=vadj), \
                mock.patch.object(grid, "_row_height", return_value=0):
            self.assertIsNone(grid._scroll_anchor())

    def test_with_no_columns_yet_the_anchor_counts_one(self):
        grid = self.open_grid()
        vadj = mock.Mock()
        vadj.get_value.return_value = 30
        grid._column_state = None
        with mock.patch.object(grid, "get_vadjustment", return_value=vadj), \
                mock.patch.object(grid, "_row_height", return_value=20):
            self.assertEqual(grid._scroll_anchor(), (1, 0.5))

    def test_restoring_with_no_scroller_does_nothing(self):
        grid = self.open_grid()
        with mock.patch.object(grid, "get_vadjustment", return_value=None):
            self.assertEqual(grid._restore_anchor((0, 0.0)), GLib.SOURCE_REMOVE)

    def test_a_card_not_built_yet_takes_the_focus_when_it_is_bound(self):
        grid = self.open_grid()
        entry = grid.visible_entries()[2]
        with mock.patch.object(grid, "_grab_focus_on", return_value=False), \
                mock.patch.object(grid, "scroll_to") as scroll:
            grid._refocus_after_refit(entry)
        scroll.assert_called_once()
        self.assertIs(grid._refocus_entry, entry)
        with mock.patch.object(grid_module.GLib, "idle_add") as idle:
            list_item = mock.Mock()
            card = mock.Mock()
            list_item.get_child.return_value = card
            list_item.get_item.return_value = entry
            list_item.get_position.return_value = 2
            grid._bind_cell(list_item)
        idle.assert_called_once_with(grid._finish_refocus, entry)
        grid._bound.pop(entry, None)
        with mock.patch.object(grid, "_take_focus_back") as grab:
            self.assertEqual(grid._finish_refocus(entry), GLib.SOURCE_REMOVE)
            grab.assert_called_once_with(entry)
            self.assertIsNone(grid._refocus_entry)
            grid._finish_refocus(entry)
            grab.assert_called_once()

    def test_a_bound_card_takes_the_focus_at_once(self):
        grid = self.open_grid()
        entry = grid.visible_entries()[0]
        with mock.patch.object(grid, "_grab_focus_on", return_value=True), \
                mock.patch.object(grid, "scroll_to") as scroll:
            grid._refocus_after_refit(entry)
        scroll.assert_not_called()
        self.assertIsNone(grid._refocus_entry)

    def test_a_game_gone_from_the_page_is_not_refocused(self):
        grid = self.open_grid()
        grid._refocus_entry = object()
        with mock.patch.object(grid, "_position_of", return_value=None), \
                mock.patch.object(grid, "_take_focus_back") as focus:
            self.assertEqual(grid._refocus_after_refit(object()), GLib.SOURCE_REMOVE)
        focus.assert_not_called()
        self.assertIsNone(grid._refocus_entry)

    def test_a_game_that_never_came_back_does_not_take_the_focus_later(self):
        # Review of PR 1008: leaving the page, sleeping, or moving on drops it.
        grid = self.open_grid()
        entry = grid.visible_entries()[3]
        grid._refocus_entry = entry
        grid.set_dormant(True)
        self.assertIsNone(grid._refocus_entry)
        grid.set_dormant(False)
        self.pump()
        grid._refocus_entry = entry
        other = grid.card_for(grid.visible_entries()[0])
        self.assertIsNotNone(other)
        root = self.win
        with mock.patch.object(grid, "item_for_widget", return_value=other):
            grid._on_root_focus_changed(root, None)
        self.assertIsNone(grid._refocus_entry)

    def test_the_rebuilt_card_itself_keeps_the_pending_focus(self):
        grid = self.open_grid()
        entry = grid.visible_entries()[0]
        card = grid.card_for(entry)
        grid._refocus_entry = entry
        with mock.patch.object(grid, "item_for_widget", return_value=card):
            grid._on_root_focus_changed(self.win, None)
        self.assertIs(grid._refocus_entry, entry)
        grid._refocus_entry = None

    def test_taking_the_focus_back_follows_the_new_card(self):
        grid = self.open_grid()
        entry = grid.visible_entries()[0]
        with mock.patch.object(grid, "_grab_focus_on", return_value=False):
            self.assertFalse(grid._take_focus_back(entry))
        with mock.patch.object(grid, "_grab_focus_on", return_value=True), \
                mock.patch.object(grid, "_on_root_focus_changed") as follow:
            self.assertTrue(grid._take_focus_back(entry))
            follow.assert_called_once()
            grid._focus_root, root = None, grid._focus_root
            self.assertTrue(grid._take_focus_back(entry))
            grid._focus_root = root
        follow.assert_called_once()


@needs_display
class AllGamesTests(_FitCase):
    library = {
        "SFC": [f"Game {index:02d}.sfc" for index in range(12)],
        "FC": [f"Game {index:02d}.nes" for index in range(12)],
        "PS": [f"Game {index:02d}.cue" for index in range(12)],
    }

    def test_every_section_fills_its_own_row(self):
        self.show()
        self.shell.open_library(ALL_CONSOLES_ID)
        group = self.win.pages.grid_for(ALL_CONSOLES_ID)
        grids = dict(zip(group.consoles(), group.grids()))
        grids = [grids.get(console) for console in ("SFC", "FC", "PS")]
        self.assertTrue(all(g is not None for g in grids))
        # The sections below the window sleep until scrolled to: they are
        # sized when the page measures them, so they wake at their size.
        self.assertTrue(self.pump_until(
            lambda: all(g.get_width() > 0 and g._refit_source is None for g in grids)
            and any(g._column_state is not None for g in grids)
        ))
        self.pump()
        viewport = RomGrid._fit_viewport
        self.assertIsNotNone(viewport)
        for grid in grids:
            with self.subTest(console=grid.console):
                self.assertTrue(grid._fit_width)
                columns, growth = grid._growth_for(viewport - 2 * grid._margin)
                self.assertEqual(grid._growth, growth)
                self.assertEqual(grid._columns_for(-1), columns)
                if grid._column_state is not None:
                    self.assertEqual(grid._column_state, (columns, 0))

    def test_a_sleeping_section_wakes_at_the_page_s_size(self):
        self.show()
        self.shell.open_library(ALL_CONSOLES_ID)
        group = self.win.pages.grid_for(ALL_CONSOLES_ID)
        grid = group.grids()[-1]
        self.assertTrue(self.pump_until(lambda: RomGrid._fit_viewport is not None))
        grid.set_dormant(True)
        grid._size_cards(0)
        grid._column_state = None
        self.assertEqual(grid._columns_for(-1),
                         grid._growth_for(RomGrid._fit_viewport - 2 * grid._margin)[0])
        grid.set_dormant(False)
        self.assertEqual(grid._growth,
                         grid._growth_for(RomGrid._fit_viewport - 2 * grid._margin)[1])

    def test_a_grid_not_in_a_grouped_page_has_no_siblings_to_tell(self):
        self.show()
        self.shell.open_library("SFC")
        grid = self.win.pages.grid_for("SFC")
        self.assertEqual(grid._fit_sleeping_siblings(), GLib.SOURCE_REMOVE)

    def test_a_sleeping_grid_counts_no_more_columns_than_it_has_games(self):
        self.show()
        self.shell.open_library(ALL_CONSOLES_ID)
        grid = self.win.pages.grid_for(ALL_CONSOLES_ID).grids()[-1]
        self.assertTrue(self.pump_until(lambda: RomGrid._fit_viewport is not None))
        grid._column_state = None
        with mock.patch.object(grid, "_entries", grid._entries[:1]):
            self.assertEqual(grid._columns_for(-1), 1)

    def test_with_no_width_known_a_sleeping_grid_keeps_its_size(self):
        self.show()
        self.shell.open_library(ALL_CONSOLES_ID)
        grid = self.win.pages.grid_for(ALL_CONSOLES_ID).grids()[-1]
        RomGrid._fit_viewport = None
        grid.set_dormant(True)
        grid._column_state = None
        growth = grid._growth
        grid._fit_while_asleep()
        self.assertEqual(grid._growth, growth)
        self.assertEqual(grid._columns_for(-1), 1)


if __name__ == "__main__":
    unittest.main()
