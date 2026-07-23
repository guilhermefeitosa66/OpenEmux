import unittest

from openemux.core.library_view import (
    DEFAULT_VIEW_MODE,
    DEFAULT_ZOOM,
    MIN_SCALED_SPACING,
    ZOOM_LEVELS,
    LIST_ROW_MAX_THUMB_WIDTH,
    LIST_ROW_THUMB_HEIGHT,
    VIEW_MODE_CARTRIDGE,
    VIEW_MODE_COVER,
    VIEW_MODE_LIST,
    VIEW_MODES,
    DEFAULT_SORT_ORDER,
    SORT_FILE_SIZE,
    SORT_NAME_ASC,
    SORT_NAME_DESC,
    SORT_PLATFORM,
    SORT_RECENTLY_ADDED,
    SORT_RECENTLY_PLAYED,
    can_zoom,
    is_grid_view,
    normalize_sort_order,
    sort_roms,
    list_thumb_column_width,
    list_thumb_size,
    normalize_view_mode,
    normalize_zoom,
    renders_cartridge,
    scale_length,
    scale_spacing,
    view_mode_from_legacy,
    zoom_percent,
    zoom_step,
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

    def test_the_column_is_the_same_width_for_every_console(self):
        """Otherwise each console's aspect gives its titles a different indent."""
        self.assertEqual(list_thumb_column_width(1.0), LIST_ROW_MAX_THUMB_WIDTH)
        self.assertEqual(list_thumb_column_width(2.0), LIST_ROW_MAX_THUMB_WIDTH * 2)

    def test_no_thumbnail_is_wider_than_its_column(self):
        for cover in ((200, 200), (200, 100), (100, 200), (280, 100)):
            with self.subTest(cover=cover):
                width, _h = list_thumb_size(cover, 1.5)
                self.assertLessEqual(width, list_thumb_column_width(1.5))

    def test_a_degenerate_size_does_not_divide_by_zero(self):
        self.assertEqual(
            list_thumb_size((0, 0)), (LIST_ROW_MAX_THUMB_WIDTH, LIST_ROW_THUMB_HEIGHT)
        )


def rom(name, console="SFC", path=None):
    return {"name": name, "console": console, "path": path or f"/roms/{console}/{name}.rom"}


class SortOrderTests(unittest.TestCase):
    LIBRARY = [
        rom("Zelda", "SFC"),
        rom("chrono trigger", "SFC"),
        rom("Astérix", "MD"),
        rom("Mega Man", "FC"),
    ]

    def names(self, roms):
        return [entry["name"] for entry in roms]

    def test_unknown_orders_fall_back_to_a_z(self):
        for value in ("", None, "by_vibes"):
            with self.subTest(value=value):
                self.assertEqual(normalize_sort_order(value), DEFAULT_SORT_ORDER)

    def test_name_ascending_ignores_case(self):
        """Otherwise every lowercase title lands in a block after the Z's."""
        self.assertEqual(
            self.names(sort_roms(self.LIBRARY, SORT_NAME_ASC)),
            ["Astérix", "chrono trigger", "Mega Man", "Zelda"],
        )

    def test_name_descending_is_the_exact_reverse(self):
        self.assertEqual(
            self.names(sort_roms(self.LIBRARY, SORT_NAME_DESC)),
            list(reversed(self.names(sort_roms(self.LIBRARY, SORT_NAME_ASC)))),
        )

    def test_platform_groups_consoles_and_sorts_inside_each(self):
        self.assertEqual(
            self.names(sort_roms(self.LIBRARY, SORT_PLATFORM)),
            ["Mega Man", "Astérix", "chrono trigger", "Zelda"],
        )

    def test_file_size_is_largest_first(self):
        sizes = {"/roms/SFC/Zelda.rom": 4_000_000, "/roms/SFC/chrono trigger.rom": 8_000_000}
        ordered = sort_roms(
            self.LIBRARY, SORT_FILE_SIZE, file_stat=lambda p: (sizes.get(p, 0), 0.0)
        )
        self.assertEqual(self.names(ordered)[:2], ["chrono trigger", "Zelda"])

    def test_recently_added_is_newest_first(self):
        added = {"/roms/MD/Astérix.rom": 500.0, "/roms/FC/Mega Man.rom": 900.0}
        ordered = sort_roms(
            self.LIBRARY, SORT_RECENTLY_ADDED, file_stat=lambda p: (0, added.get(p, 0.0))
        )
        self.assertEqual(self.names(ordered)[:2], ["Mega Man", "Astérix"])

    def test_recently_played_is_newest_first(self):
        played = {"/roms/SFC/Zelda.rom": 20.0, "/roms/FC/Mega Man.rom": 90.0}
        ordered = sort_roms(
            self.LIBRARY, SORT_RECENTLY_PLAYED, last_played=lambda p: played.get(p, 0.0)
        )
        self.assertEqual(self.names(ordered)[:2], ["Mega Man", "Zelda"])

    def test_games_that_tie_fall_back_to_the_title(self):
        """Never-played games are all 0, so they must not come out shuffled."""
        ordered = sort_roms(self.LIBRARY, SORT_RECENTLY_PLAYED, last_played=lambda _p: 0.0)
        self.assertEqual(self.names(ordered), self.names(sort_roms(self.LIBRARY, SORT_NAME_ASC)))

    def test_a_missing_lookup_sorts_as_unknown_instead_of_raising(self):
        """A page can outlive the files on it (deleted ROM, unplugged drive)."""
        def exploding_stat(_path):
            raise OSError("gone")

        ordered = sort_roms(self.LIBRARY, SORT_FILE_SIZE, file_stat=exploding_stat)
        self.assertEqual(len(ordered), len(self.LIBRARY))

    def test_sorting_does_not_mutate_the_caller_s_list(self):
        original = list(self.LIBRARY)
        sort_roms(self.LIBRARY, SORT_NAME_DESC)
        self.assertEqual(self.LIBRARY, original)


class ZoomTests(unittest.TestCase):
    def test_known_levels_pass_through(self):
        for level in ZOOM_LEVELS:
            with self.subTest(level=level):
                self.assertEqual(normalize_zoom(level), level)

    def test_an_arbitrary_value_snaps_to_the_nearest_level(self):
        self.assertEqual(normalize_zoom(1.1), 1.0)
        self.assertEqual(normalize_zoom(1.4), 1.5)
        self.assertEqual(normalize_zoom(9.0), 2.0)
        self.assertEqual(normalize_zoom(0.1), 0.5)

    def test_junk_and_nonsense_fall_back_to_100_percent(self):
        for value in (None, "", "big", 0, -2):
            with self.subTest(value=value):
                self.assertEqual(normalize_zoom(value), DEFAULT_ZOOM)

    def test_a_stored_string_is_still_a_zoom(self):
        self.assertEqual(normalize_zoom("1.5"), 1.5)

    def test_stepping_walks_the_levels(self):
        self.assertEqual(zoom_step(1.0, 1), 1.25)
        self.assertEqual(zoom_step(1.0, -1), 0.75)

    def test_stepping_stops_at_the_ends_instead_of_wrapping(self):
        self.assertEqual(zoom_step(ZOOM_LEVELS[-1], 1), ZOOM_LEVELS[-1])
        self.assertEqual(zoom_step(ZOOM_LEVELS[0], -1), ZOOM_LEVELS[0])

    def test_can_zoom_reports_the_ends_so_the_buttons_can_dim(self):
        self.assertFalse(can_zoom(ZOOM_LEVELS[0], -1))
        self.assertTrue(can_zoom(ZOOM_LEVELS[0], 1))
        self.assertFalse(can_zoom(ZOOM_LEVELS[-1], 1))
        self.assertTrue(can_zoom(ZOOM_LEVELS[-1], -1))

    def test_percentage_label(self):
        self.assertEqual(zoom_percent(1.0), 100)
        self.assertEqual(zoom_percent(0.75), 75)
        self.assertEqual(zoom_percent(2.0), 200)


class ScalingTests(unittest.TestCase):
    def test_lengths_scale_with_the_zoom(self):
        self.assertEqual(scale_length(200, 1.0), 200)
        self.assertEqual(scale_length(200, 0.5), 100)
        self.assertEqual(scale_length(200, 2.0), 400)

    def test_a_length_never_collapses_to_zero(self):
        self.assertEqual(scale_length(1, 0.5), 1)

    def test_gaps_shrink_with_the_cards_but_keep_them_apart(self):
        self.assertEqual(scale_spacing(24, 1.0), 24)
        self.assertEqual(scale_spacing(24, 2.0), 48)
        self.assertEqual(scale_spacing(4, 0.5), MIN_SCALED_SPACING)

    def test_list_thumbnails_follow_the_zoom(self):
        _w, height = list_thumb_size((200, 200), 1.0)
        _w2, doubled = list_thumb_size((200, 200), 2.0)
        self.assertEqual(doubled, height * 2)

    def test_the_width_cap_scales_too_so_the_row_stays_proportional(self):
        width, _h = list_thumb_size((200, 100), 2.0)
        self.assertEqual(width, LIST_ROW_MAX_THUMB_WIDTH * 2)


if __name__ == "__main__":
    unittest.main()
