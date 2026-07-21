import unittest

from openemux.ui.grid import (
    GRID_SPACING,
    card_size_for,
    columns_and_slack,
    cover_size_for_console,
)

CARD = 216  # a 200px cover plus the card's 8px padding on each side


def line_width(columns, card=CARD, spacing=GRID_SPACING):
    return columns * card + (columns - 1) * spacing


class ColumnsAndSlackTests(unittest.TestCase):
    """The grid packs cards to the start by leaving GtkFlowBox no slack.

    GtkFlowBox always justifies: any width left over on a line is shared out
    *between* the children. The leftover is handed to the end margin instead,
    so the flow box is allocated exactly the cards plus their gaps.
    """

    def test_slack_is_zero_at_an_exact_fit(self):
        for columns in (1, 2, 3, 5):
            with self.subTest(columns=columns):
                available = line_width(columns)
                self.assertEqual(
                    columns_and_slack(available, CARD, item_count=50),
                    (columns, 0),
                )

    def test_leftover_becomes_slack(self):
        available = line_width(3) + 100
        columns, slack = columns_and_slack(available, CARD, item_count=50)
        self.assertEqual(columns, 3)
        self.assertEqual(slack, 100)

    def test_a_column_is_only_taken_when_it_fully_fits(self):
        # One pixel short of a fourth card: still three columns.
        available = line_width(4) - 1
        columns, _ = columns_and_slack(available, CARD, item_count=50)
        self.assertEqual(columns, 3)

    def test_page_with_fewer_cards_than_fit_is_sized_for_what_it_has(self):
        """Two cards in a four-column viewport must not spread across it."""
        available = line_width(4)
        columns, slack = columns_and_slack(available, CARD, item_count=2)
        self.assertEqual(columns, 4)
        self.assertEqual(available - slack, line_width(2))

    def test_single_card_page(self):
        available = line_width(4)
        _columns, slack = columns_and_slack(available, CARD, item_count=1)
        self.assertEqual(available - slack, CARD)

    def test_empty_page_does_not_produce_a_negative_width(self):
        _columns, slack = columns_and_slack(line_width(3), CARD, item_count=0)
        self.assertGreaterEqual(slack, 0)

    def test_viewport_narrower_than_a_card_keeps_one_column(self):
        columns, slack = columns_and_slack(120, CARD, item_count=10)
        self.assertEqual(columns, 1)
        self.assertEqual(slack, 0)

    def test_result_is_stable_when_fed_its_own_output(self):
        """Guards the oscillation the end-margin trick could otherwise cause.

        The margin changes the grid's own allocation, so the computation is fed
        the viewport width instead. If it were ever fed the reduced width, this
        is the loop that would show up.
        """
        available = line_width(4) + 137
        columns, slack = columns_and_slack(available, CARD, item_count=50)
        again = columns_and_slack(available, CARD, item_count=50)
        self.assertEqual((columns, slack), again)


class CardSizeTests(unittest.TestCase):
    def test_caption_height_is_added_to_the_cover(self):
        self.assertEqual(card_size_for((200, 300)), (200, 344))

    def test_mixed_console_pages_reserve_a_second_caption_line(self):
        _w, single = card_size_for((200, 300))
        _w, mixed = card_size_for((200, 300), mixed_consoles=True)
        self.assertEqual(mixed - single, 18)

    def test_console_cover_sizes_follow_their_own_proportions(self):
        """Cards are fixed per console, sized to that console's box art."""
        # SNES box art is wide and short, N64 is tall: different card heights.
        _w, sfc = cover_size_for_console("SFC")
        _w, n64 = cover_size_for_console("N64")
        _w, fc = cover_size_for_console("FC")
        self.assertLess(sfc, fc)
        self.assertLess(n64, fc)
        self.assertNotEqual(sfc, n64)

    def test_every_console_card_has_the_same_width(self):
        widths = {cover_size_for_console(c)[0] for c in ("FC", "SFC", "N64", "GBA", "PS")}
        self.assertEqual(len(widths), 1)

    def test_unknown_console_falls_back_to_a_square_cover(self):
        width, height = cover_size_for_console("NOT-A-CONSOLE")
        self.assertEqual(width, height)


if __name__ == "__main__":
    unittest.main()
