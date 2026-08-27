"""The rule the rubber band selects by (issue #238).

The band lived inside `RomGrid` with the gestures, the coordinate transforms
and the snapshot that paints it, so the one thing about it worth checking --
which cards a dragged rectangle catches -- could not be asked without a
display and a laid-out grid.

The maths is pure, and this is it: a card counts as caught when the two
rectangles overlap at all, not when the band covers it. Dragging across the
top edge of a row selects that row, the way a file manager does.
"""

import unittest

from openemux.ui.grid_selection import entries_intersecting


#: Two rows of three 100x100 cards, 20px apart, starting at (10, 10).
def _bounds():
    cards = []
    for row in range(2):
        for column in range(3):
            cards.append(
                (
                    f"r{row}c{column}",
                    10 + column * 120,
                    10 + row * 120,
                    100,
                    100,
                )
            )
    return cards


class WhatABandCatchesTests(unittest.TestCase):
    def setUp(self):
        self.bounds = _bounds()

    def _caught(self, band):
        return entries_intersecting(band, self.bounds)

    def test_a_band_over_one_card_catches_that_card(self):
        self.assertEqual(self._caught((20, 20, 40, 40)), ["r0c0"])

    def test_clipping_a_corner_is_enough(self):
        # Not "covers": a band that grazes a card selects it.
        self.assertEqual(self._caught((100, 100, 15, 15)), ["r0c0"])

    def test_a_band_in_the_gap_catches_nothing(self):
        # The 20px gutter between the first and second column.
        self.assertEqual(self._caught((112, 40, 5, 20)), [])

    def test_a_band_across_a_row_catches_the_whole_row(self):
        self.assertEqual(self._caught((0, 50, 400, 10)), ["r0c0", "r0c1", "r0c2"])

    def test_a_band_down_a_column_catches_both_rows(self):
        self.assertEqual(self._caught((40, 0, 10, 400)), ["r0c0", "r1c0"])

    def test_a_band_over_everything_catches_everything(self):
        self.assertEqual(len(self._caught((0, 0, 1000, 1000))), 6)

    def test_the_order_follows_the_cards_not_the_drag(self):
        # The band is dragged upward here; the result is still in grid order,
        # which is what the selection model indexes by.
        self.assertEqual(self._caught((0, 0, 400, 400)), [c[0] for c in self.bounds])

    def test_a_zero_area_band_still_catches_what_it_is_on(self):
        # drag-update fires before the pointer has moved; a degenerate band
        # must not throw.
        self.assertEqual(self._caught((50, 50, 0, 0)), ["r0c0"])

    def test_a_band_past_the_last_card_catches_nothing(self):
        self.assertEqual(self._caught((500, 500, 100, 100)), [])

    def test_nothing_on_screen_catches_nothing(self):
        self.assertEqual(entries_intersecting((0, 0, 1000, 1000), []), [])


if __name__ == "__main__":
    unittest.main()
