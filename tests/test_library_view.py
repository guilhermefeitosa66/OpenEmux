import unittest

from openemux.core.library_view import (
    DEFAULT_VIEW_MODE,
    LIST_ROW_MAX_THUMB_WIDTH,
    LIST_ROW_THUMB_HEIGHT,
    VIEW_MODE_CARTRIDGE,
    VIEW_MODE_COVER,
    VIEW_MODE_LIST,
    VIEW_MODES,
    is_grid_view,
    list_thumb_size,
    normalize_view_mode,
    renders_cartridge,
    view_mode_from_legacy,
)


class ViewModeTests(unittest.TestCase):
    def test_known_modes_pass_through(self):
        for mode in VIEW_MODES:
            with self.subTest(mode=mode):
                self.assertEqual(normalize_view_mode(mode), mode)

    def test_unknown_values_fall_back_to_the_default(self):
        for value in ("", None, "grid", "COVERS", "  "):
            with self.subTest(value=value):
                self.assertEqual(normalize_view_mode(value), DEFAULT_VIEW_MODE)

    def test_case_and_padding_are_tolerated(self):
        self.assertEqual(normalize_view_mode(" Cover "), VIEW_MODE_COVER)

    def test_only_the_cartridge_mode_draws_a_frame(self):
        self.assertTrue(renders_cartridge(VIEW_MODE_CARTRIDGE))
        self.assertFalse(renders_cartridge(VIEW_MODE_COVER))
        self.assertFalse(renders_cartridge(VIEW_MODE_LIST))

    def test_only_the_list_mode_leaves_the_grid(self):
        self.assertTrue(is_grid_view(VIEW_MODE_COVER))
        self.assertTrue(is_grid_view(VIEW_MODE_CARTRIDGE))
        self.assertFalse(is_grid_view(VIEW_MODE_LIST))

    def test_the_old_switch_maps_onto_the_two_grid_modes(self):
        self.assertEqual(view_mode_from_legacy(True), VIEW_MODE_CARTRIDGE)
        self.assertEqual(view_mode_from_legacy(False), VIEW_MODE_COVER)


class ListThumbTests(unittest.TestCase):
    def test_height_is_fixed_and_the_aspect_is_kept(self):
        width, height = list_thumb_size((200, 200))
        self.assertEqual(height, LIST_ROW_THUMB_HEIGHT)
        self.assertEqual(width, LIST_ROW_THUMB_HEIGHT)

    def test_a_wide_cover_stays_wide(self):
        width, height = list_thumb_size((140, 100))
        self.assertEqual((width, height), (90, LIST_ROW_THUMB_HEIGHT))

    def test_a_very_wide_cover_is_capped_so_it_cannot_push_the_title_over(self):
        """N64/SFC boxes; without the cap their titles would sit further right."""
        width, _height = list_thumb_size((200, 100))
        self.assertEqual(width, LIST_ROW_MAX_THUMB_WIDTH)

    def test_a_tall_cover_is_narrower_than_the_row_height(self):
        width, _height = list_thumb_size((100, 200))
        self.assertEqual(width, 32)

    def test_a_degenerate_size_does_not_divide_by_zero(self):
        self.assertEqual(
            list_thumb_size((0, 0)), (LIST_ROW_MAX_THUMB_WIDTH, LIST_ROW_THUMB_HEIGHT)
        )


if __name__ == "__main__":
    unittest.main()
