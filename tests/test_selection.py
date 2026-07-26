"""The pure selection model (issue #78): ranges, anchors, additive extends."""

import unittest

from openemux.core.selection import SelectionModel


class SelectionModelTests(unittest.TestCase):
    def setUp(self):
        self.model = SelectionModel(10)

    def test_select_replaces_and_roots_the_anchor(self):
        self.model.select(3)
        self.assertEqual(self.model.selected, {3})
        self.model.select(7)
        self.assertEqual(self.model.selected, {7})
        self.assertEqual(self.model.anchor, 7)
        self.assertEqual(self.model.cursor, 7)

    def test_toggle_flips_and_moves_the_anchor(self):
        self.model.toggle(2)
        self.model.toggle(5)
        self.assertEqual(self.model.selected, {2, 5})
        self.model.toggle(2)
        self.assertEqual(self.model.selected, {5})
        self.assertEqual(self.model.anchor, 2)

    def test_extend_selects_the_contiguous_range(self):
        # A range in a grid runs across row boundaries: it is the linear
        # index range, exactly like a file manager.
        self.model.select(2)
        self.model.extend(6)
        self.assertEqual(self.model.selected, {2, 3, 4, 5, 6})
        self.assertEqual(self.model.anchor, 2)
        self.assertEqual(self.model.cursor, 6)

    def test_extend_backwards(self):
        self.model.select(6)
        self.model.extend(2)
        self.assertEqual(self.model.selected, {2, 3, 4, 5, 6})

    def test_extend_replaces_the_previous_range(self):
        self.model.select(4)
        self.model.extend(8)
        self.model.extend(5)
        self.assertEqual(self.model.selected, {4, 5})

    def test_extend_additive_keeps_the_pre_shift_selection(self):
        self.model.toggle(0)
        self.model.toggle(9)  # anchor is now 9
        self.model.extend_additive(7)
        self.assertEqual(self.model.selected, {0, 7, 8, 9})
        # Growing the same Shift sequence still unions with the same base.
        self.model.extend_additive(5)
        self.assertEqual(self.model.selected, {0, 5, 6, 7, 8, 9})

    def test_toggle_then_extend_ranges_from_the_new_anchor(self):
        self.model.select(1)
        self.model.toggle(5)
        self.model.extend(8)
        self.assertEqual(self.model.selected, {5, 6, 7, 8})

    def test_select_all_and_clear(self):
        self.model.select_all()
        self.assertEqual(self.model.selected, set(range(10)))
        self.assertTrue(self.model.all_selected())
        self.model.clear()
        self.assertEqual(self.model.selected, set())
        self.assertFalse(self.model.all_selected())

    def test_select_all_over_a_filtered_list(self):
        # The model only ever sees visible items; a filter re-seeds it.
        self.model.reset(3)
        self.model.select_all()
        self.assertEqual(self.model.selected, {0, 1, 2})

    def test_plain_movement_leaves_the_selection_alone(self):
        self.model.select(2)
        self.model.extend(4)
        self.model.move_cursor(5)
        self.assertEqual(self.model.selected, {2, 3, 4})
        # ...but re-roots the anchor, so the next Shift ranges from here.
        self.model.extend(7)
        self.assertEqual(self.model.selected, {5, 6, 7})

    def test_ctrl_movement_keeps_the_anchor(self):
        self.model.select(2)
        self.model.move_cursor(5, keep_anchor=True)
        self.assertEqual(self.model.anchor, 2)
        self.model.extend(6)
        self.assertEqual(self.model.selected, {2, 3, 4, 5, 6})

    def test_extend_with_no_anchor_starts_at_the_index(self):
        self.model.extend(3)
        self.assertEqual(self.model.selected, {3})
        self.assertEqual(self.model.anchor, 3)

    def test_out_of_range_indices_are_ignored(self):
        self.model.select(20)
        self.model.toggle(-1)
        self.model.extend(99)
        self.assertEqual(self.model.selected, set())

    def test_replace_adopts_an_external_selection(self):
        self.model.replace([1, 3, 99])
        self.assertEqual(self.model.selected, {1, 3})
        # The adopted selection is the new base for additive ranges.
        self.model.anchor = 5
        self.model.extend_additive(6)
        self.assertEqual(self.model.selected, {1, 3, 5, 6})

    def test_reset_forgets_everything(self):
        self.model.select(2)
        self.model.reset(4)
        self.assertEqual(self.model.selected, set())
        self.assertIsNone(self.model.anchor)
        self.assertIsNone(self.model.cursor)


if __name__ == "__main__":
    unittest.main()
