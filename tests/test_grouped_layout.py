"""The arithmetic of a grouped page's scrolling (issue #511)."""

import unittest

from openemux.core.grouped_layout import scroll_to_show, slice_for


class SliceTests(unittest.TestCase):
    """``slice_for(top, height, scroll, viewport)``."""

    def test_a_child_entirely_above_the_viewport_is_off_screen(self):
        self.assertIsNone(slice_for(0, 100, 200, 500))

    def test_a_child_entirely_below_the_viewport_is_off_screen(self):
        self.assertIsNone(slice_for(800, 100, 200, 500))

    def test_a_child_ending_exactly_at_the_top_edge_is_off_screen(self):
        self.assertIsNone(slice_for(100, 100, 200, 500))

    def test_a_child_cut_by_the_top_edge_starts_at_the_top_scrolled_into(self):
        self.assertEqual(slice_for(100, 300, 200, 500), (0, 200, 100))

    def test_a_child_cut_by_the_bottom_edge_is_shown_from_its_own_top(self):
        self.assertEqual(slice_for(600, 300, 200, 500), (400, 100, 0))

    def test_a_child_taller_than_the_viewport_fills_it(self):
        self.assertEqual(slice_for(0, 5000, 1200, 500), (0, 500, 1200))

    def test_a_child_that_fits_exactly_is_allocated_whole(self):
        self.assertEqual(slice_for(200, 500, 200, 500), (0, 500, 0))

    def test_a_viewport_with_no_height_shows_nothing(self):
        self.assertIsNone(slice_for(0, 100, 0, 0))


class ScrollToShowTests(unittest.TestCase):
    """``scroll_to_show(scroll, viewport, top, height)``."""

    def test_something_already_in_view_does_not_move_the_page(self):
        self.assertEqual(scroll_to_show(100, 500, 200, 50), 100)

    def test_something_above_comes_in_at_the_top(self):
        self.assertEqual(scroll_to_show(300, 500, 200, 50), 200)

    def test_something_below_comes_in_at_the_bottom(self):
        self.assertEqual(scroll_to_show(0, 500, 600, 50), 150)

    def test_something_taller_than_the_viewport_is_shown_from_its_top(self):
        self.assertEqual(scroll_to_show(0, 500, 600, 800), 600)


if __name__ == "__main__":
    unittest.main()
