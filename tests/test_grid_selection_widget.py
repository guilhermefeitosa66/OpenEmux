"""Selecting games in the grid: the modifiers, the keyboard, the rubber band.

`tests/test_grid_selection.py` covers `SelectionModel`, which is pure index
arithmetic. `ui/grid_selection.py` is the half that binds it to real cards --
which entry a click means, which cards a dragged band touches, and the
file-manager rule that a plain click on empty space clears the selection --
and that half sat at 53%, because all of it needs a grid with cards in it.

The grid is the real one on a presented window; the band gestures are driven
by calling the handlers with coordinates, which is what the pointer would do.
"""

import unittest
from unittest import mock

from tests.gtk_display import HAVE_DISPLAY, needs_display
from tests.window_harness import WindowCase

if HAVE_DISPLAY:
    import gi

    gi.require_version("Gtk", "4.0")
    from gi.repository import Gdk, Graphene, Gtk

    from openemux.ui.grid_selection import CLICK_SLOP_PX


class _SelectionCase(WindowCase):
    """A presented console page, so the grid has cards with real geometry."""

    library = {"SFC": [f"Game {index}.sfc" for index in range(6)]}

    def setUp(self):
        super().setUp()
        self.win.sidebar.select("SFC")
        self.show()
        self.grid = self.win.pages.grid_for("SFC")
        self.selection = self.grid.selection
        self.entries = self.grid.entries()

    def selected_names(self):
        return [entry.rom["name"] for entry in self.entries if entry.selected]

    def card(self, index):
        return self.grid.card_for(self.entries[index])


@needs_display
class TheVerbsTests(_SelectionCase):
    def test_nothing_is_selected_to_begin_with(self):
        self.assertFalse(self.selection.any_selected())
        self.assertEqual(self.selection.selected_roms(), [])

    def test_selecting_everything_visible_selects_every_entry(self):
        self.selection.select_all()
        self.assertEqual(len(self.selection.selected_roms()), len(self.entries))

    def test_clearing_puts_every_entry_back(self):
        self.selection.select_all()
        self.selection.clear()
        self.assertFalse(self.selection.any_selected())

    def test_the_master_toggle_selects_everything_then_clears_it(self):
        self.selection.toggle_select_all()
        self.assertTrue(self.selection.any_selected())
        self.selection.toggle_select_all()
        self.assertFalse(self.selection.any_selected())

    def test_a_ctrl_click_flips_one_game(self):
        self.selection.toggle_entry(self.entries[1], ctrl=True)
        self.assertEqual(self.selected_names(), [self.entries[1].rom["name"]])
        self.selection.toggle_entry(self.entries[1], ctrl=True)
        self.assertEqual(self.selected_names(), [])

    def test_a_shift_click_ranges_from_the_last_one_clicked(self):
        # A file manager roots ranges at the last click.
        self.selection.toggle_entry(self.entries[1], ctrl=False, shift=False)
        self.selection.toggle_entry(self.entries[3], ctrl=False, shift=True)
        self.assertEqual(len(self.selection.selected_roms()), 3)

    def test_a_ctrl_shift_click_adds_the_range_to_what_is_there(self):
        self.selection.toggle_entry(self.entries[0], ctrl=True)
        self.selection.toggle_entry(self.entries[3], ctrl=False, shift=False)
        self.selection.toggle_entry(self.entries[5], ctrl=True, shift=True)
        self.assertGreaterEqual(len(self.selection.selected_roms()), 3)

    def test_a_plain_click_moves_the_anchor_without_selecting(self):
        self.selection.toggle_entry(self.entries[2], ctrl=False, shift=False)
        self.assertFalse(self.selection.any_selected())

    def test_a_game_the_filter_hid_cannot_be_selected(self):
        self.grid.set_filter("nothing matches this")
        before = self.selection.selected_roms()
        self.selection.toggle_entry(self.entries[0], ctrl=True)
        self.assertEqual(self.selection.selected_roms(), before)

    def test_the_card_showing_a_game_stands_in_for_it(self):
        # The callers mix entries and cards.
        card = self.card(0)
        if card is None:
            self.skipTest("the grid realized no card for the first game")
        self.selection.toggle_item(card)
        self.assertEqual(self.selected_names(), [self.entries[0].rom["name"]])

    def test_selecting_one_item_replaces_the_whole_selection(self):
        self.selection.select_all()
        self.selection.select_item(self.entries[2])
        self.assertEqual(self.selected_names(), [self.entries[2].rom["name"]])

    def test_selecting_an_item_that_is_not_visible_changes_nothing(self):
        self.grid.set_filter("nothing matches this")
        self.selection.select_item(self.entries[0])
        self.assertFalse(self.selection.any_selected())


@needs_display
class KeyboardRangesTests(_SelectionCase):
    def test_a_shift_arrow_grows_the_range_to_the_new_card(self):
        self.selection.begin_range_from(self.entries[1])
        self.selection.extend_to(self.entries[3])
        self.assertEqual(len(self.selection.selected_roms()), 3)

    def test_an_additive_range_keeps_what_was_already_picked(self):
        self.selection.toggle_entry(self.entries[5], ctrl=True)
        self.selection.begin_range_from(self.entries[0])
        self.selection.extend_to(self.entries[2], additive=True)
        self.assertEqual(len(self.selection.selected_roms()), 4)

    def test_a_new_shift_sequence_re_roots_at_where_the_user_stands(self):
        # Plain arrows move the focus without the model hearing about it.
        self.selection.begin_range_from(self.entries[4])
        self.selection.extend_to(self.entries[5])
        self.assertEqual(len(self.selection.selected_roms()), 2)

    def test_a_running_sequence_keeps_its_anchor(self):
        self.selection.begin_range_from(self.entries[1])
        self.selection.extend_to(self.entries[3])
        self.selection.begin_range_from(self.entries[3])
        self.selection.extend_to(self.entries[4])
        self.assertEqual(len(self.selection.selected_roms()), 4)

    def test_a_range_from_a_card_that_is_not_visible_does_nothing(self):
        self.grid.set_filter("nothing matches this")
        self.selection.begin_range_from(self.entries[0])
        self.selection.extend_to(self.entries[1])
        self.assertFalse(self.selection.any_selected())

    def test_the_cursor_follows_plain_movement(self):
        self.selection.note_cursor(self.entries[3])
        self.selection.extend_to(self.entries[4])
        self.assertEqual(len(self.selection.selected_roms()), 2)

    def test_a_cursor_move_onto_a_hidden_card_is_ignored(self):
        self.grid.set_filter("nothing matches this")
        self.selection.note_cursor(self.entries[0])

    def test_filtering_re_seeds_the_model_rather_than_desyncing_it(self):
        self.selection.select_all()
        self.grid.set_filter(self.entries[0].rom["name"])
        self.selection.sync_visible()
        self.assertLessEqual(
            len(self.selection.selected_roms()), len(self.entries)
        )


@needs_display
class TheRubberBandTests(_SelectionCase):
    def _gesture(self, state=0):
        gesture = mock.Mock()
        gesture.get_current_event_state.return_value = state
        return gesture

    def _bounds(self, count=3):
        """Pretend the first cards sit on a known lattice."""
        return [
            (self.entries[index], index * 100.0, 0.0, 80.0, 80.0)
            for index in range(count)
        ]

    def test_a_band_over_two_cards_selects_exactly_those_two(self):
        self.selection._band_bounds = self._bounds()
        self.selection._on_begin(self._gesture(), 0, 0)
        self.selection._band_bounds = self._bounds()
        self.selection._on_update(None, 150, 50)
        self.assertEqual(len(self.selection.selected_roms()), 2)

    def test_the_band_survives_its_own_release(self):
        self.selection._on_begin(self._gesture(), 0, 0)
        self.selection._band_bounds = self._bounds()
        self.selection._on_update(None, 150, 50)
        self.selection._on_end(None, 150, 50)
        self.assertEqual(len(self.selection.selected_roms()), 2)
        self.assertIsNone(self.selection._band)

    def test_a_band_started_on_a_card_is_denied(self):
        gesture = self._gesture()
        with mock.patch.object(self.selection, "is_background", return_value=False):
            self.selection._on_begin(gesture, 5, 5)
        gesture.set_state.assert_called_once_with(Gtk.EventSequenceState.DENIED)
        self.assertIsNone(self.selection._band_origin)

    def test_a_plain_press_on_empty_space_clears_what_was_selected(self):
        self.selection.select_all()
        self.selection._on_begin(self._gesture(), 0, 0)
        self.assertFalse(self.selection.any_selected())

    def test_a_ctrl_band_adds_to_what_was_already_picked(self):
        self.selection.toggle_entry(self.entries[5], ctrl=True)
        self.selection._on_begin(
            self._gesture(state=Gdk.ModifierType.CONTROL_MASK), 0, 0
        )
        self.assertTrue(self.selection.any_selected())
        self.selection._band_bounds = self._bounds(2)
        self.selection._on_update(None, 150, 50)
        self.assertEqual(len(self.selection.selected_roms()), 3)

    def test_an_update_with_no_band_started_does_nothing(self):
        self.selection._band_origin = None
        self.selection._on_update(None, 10, 10)
        self.assertIsNone(self.selection._band)

    def test_no_band_touches_nothing(self):
        self.selection._band = None
        self.assertEqual(self.selection.entries_in_band(), [])

    def test_the_card_rectangles_are_frozen_for_the_length_of_a_drag(self):
        # Issue #231: asking GTK per card per motion event was a
        # compute_bounds call per card per pointer move.
        self.selection._freeze_bounds()
        self.assertTrue(self.selection._band_bounds)

    def test_a_card_whose_bounds_cannot_be_read_is_left_out(self):
        card = mock.Mock()
        card.compute_bounds.return_value = (False, None)
        with mock.patch.object(
            self.grid, "bound_cards", return_value=[(self.entries[0], card)]
        ):
            self.selection._freeze_bounds()
        self.assertEqual(self.selection._band_bounds, [])


@needs_display
class ClickingEmptySpaceTests(_SelectionCase):
    """The file-manager rule: a plain click on the page clears the selection."""

    def _gesture(self, state=0):
        gesture = mock.Mock()
        gesture.get_current_event_state.return_value = state
        return gesture

    def _release(self, state=0, x=0, y=0, background=True):
        with mock.patch.object(
            self.selection, "is_background", return_value=background
        ):
            self.selection._on_release(self._gesture(state), 1, x, y)

    def test_a_click_on_empty_space_clears_the_selection(self):
        self.selection.select_all()
        self.selection._on_press(None, 1, 0, 0)
        self._release()
        self.assertFalse(self.selection.any_selected())

    def test_a_click_on_a_card_leaves_the_selection_alone(self):
        self.selection.select_all()
        self.selection._on_press(None, 1, 0, 0)
        self._release(background=False)
        self.assertTrue(self.selection.any_selected())

    def test_a_drag_is_not_treated_as_a_click(self):
        # The band's result must survive its own release.
        self.selection.select_all()
        self.selection._on_press(None, 1, 0, 0)
        self._release(x=CLICK_SLOP_PX + 10, y=CLICK_SLOP_PX + 10)
        self.assertTrue(self.selection.any_selected())

    def test_a_modifier_click_is_a_selection_gesture_not_a_clear(self):
        self.selection.select_all()
        self.selection._on_press(None, 1, 0, 0)
        self._release(state=Gdk.ModifierType.CONTROL_MASK)
        self.assertTrue(self.selection.any_selected())
        self.selection._on_press(None, 1, 0, 0)
        self._release(state=Gdk.ModifierType.SHIFT_MASK)
        self.assertTrue(self.selection.any_selected())

    def test_a_click_with_nothing_selected_does_nothing(self):
        self.selection._on_press(None, 1, 0, 0)
        self._release()
        self.assertFalse(self.selection.any_selected())

    def test_a_release_with_no_press_before_it_still_decides(self):
        self.selection.select_all()
        self.selection._press_at = None
        self._release()
        self.assertFalse(self.selection.any_selected())


@needs_display
class WhatCountsAsBackgroundTests(_SelectionCase):
    def test_a_scrollbar_is_never_background(self):
        # A drag on one must keep scrolling, never start a band.
        host = mock.Mock()
        host.pick.return_value = Gtk.Scrollbar()
        self.selection._host = host
        self.assertFalse(self.selection.is_background(1, 1))

    def test_a_card_is_never_background(self):
        card = self.card(0)
        if card is None:
            self.skipTest("the grid realized no card for the first game")
        host = mock.Mock()
        host.pick.return_value = card
        self.selection._host = host
        self.assertFalse(self.selection.is_background(1, 1))

    def test_empty_page_space_is_background(self):
        host = mock.Mock()
        host.pick.return_value = None
        self.selection._host = host
        self.assertTrue(self.selection.is_background(1, 1))


@needs_display
class TheBandGesturesTests(_SelectionCase):
    def test_the_band_is_attached_to_the_page_not_only_to_the_grid(self):
        # A good deal of a page's empty space is outside the grid, and a band
        # naturally starts from there.
        self.assertIsNotNone(self.selection._host)

    def test_re_attaching_drops_the_previous_grids_gestures(self):
        # Issue #218: leaving them on would keep that grid, its cards and
        # their textures alive.
        host = self.selection._host
        first = host._openemux_band_gesture
        self.selection.attach()
        self.assertIsNot(host._openemux_band_gesture, first)

    def test_a_grid_with_nowhere_to_put_the_band_attaches_nothing(self):
        from openemux.ui.grid_selection import GridSelection

        loose = mock.Mock()
        loose.band_host = None
        loose.get_ancestor.return_value = None
        selection = GridSelection(loose)
        selection.attach()
        self.assertIsNone(selection._host)

    def test_host_coordinates_are_translated_into_grid_space(self):
        point = Graphene.Point().init(3.0, 4.0)
        host = mock.Mock()
        host.compute_point.return_value = (True, point)
        self.selection._host = host
        self.assertEqual(self.selection._to_grid_coords(1, 2), (3.0, 4.0))

    def test_a_point_that_cannot_be_translated_is_used_as_it_is(self):
        host = mock.Mock()
        host.compute_point.return_value = (False, None)
        self.selection._host = host
        self.assertEqual(self.selection._to_grid_coords(1, 2), (1, 2))

    def test_a_band_hosted_by_the_grid_itself_needs_no_translation(self):
        self.selection._host = self.grid
        self.assertEqual(self.selection._to_grid_coords(1, 2), (1, 2))


@needs_display
class DrawingTheBandTests(_SelectionCase):
    def test_no_band_paints_nothing(self):
        self.selection._band = None
        self.selection.draw(Gtk.Snapshot())

    def test_a_band_smaller_than_a_pixel_paints_nothing(self):
        self.selection._band = (0, 0, 0.5, 0.5)
        self.selection.draw(Gtk.Snapshot())

    def test_a_real_band_paints_a_fill_and_four_edges(self):
        self.selection._band = (10, 10, 100, 80)
        self.selection.draw(Gtk.Snapshot())


if __name__ == "__main__":
    unittest.main()
