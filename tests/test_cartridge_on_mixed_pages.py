"""The cartridge shelf on "All", "Favorites" and the collections (issue #385).

The shelf is the look OpenEmux ships with, and it was exactly the look those
three pages could not have: the card shape comes from the frame art, a
`Gtk.GridView` lays out on one lattice, and a page mixing consoles has no
single shape to follow -- so `RomGrid` refused the frame and drew plain covers
whatever the view mode said. Nothing blocked the *action*, though: picking
"Cartridge" there simply did nothing, which reads as a bug.

With the page grouped by console (issue #384) each grid is bound to one
console, and the per-console path applies unchanged. The rule lives in
``cartridge_frame_for`` so it can be stated without a display -- nothing in
``tests/`` can build a GTK widget.
"""

import unittest
import unittest.mock

from openemux.core import cartridge_render
from openemux.core.library_view import (
    VIEW_MODE_CARTRIDGE,
    VIEW_MODE_COVER,
)
from openemux.ui.card_layout import (
    FIXED_ITEM_WIDTH,
    cartridge_frame_for,
    cartridge_frame_svg,
    tallest_cartridge_frame,
)


class _FramedConsole:
    """The first console that actually has frame art, and one that has none."""

    WITH_FRAME = "FC"
    WITHOUT_FRAME = "PS"


class TheRuleTests(unittest.TestCase):
    def setUp(self):
        if not cartridge_render.has_frame(_FramedConsole.WITH_FRAME):
            self.skipTest("no cartridge art shipped for the reference console")

    def test_a_console_grid_in_cartridge_view_gets_its_frame(self):
        self.assertIsNotNone(
            cartridge_frame_for(_FramedConsole.WITH_FRAME, VIEW_MODE_CARTRIDGE)
        )

    def test_a_group_of_a_mixed_page_is_a_console_grid(self):
        # This is the whole of #385: the group is bound to one console, so it
        # takes the same path a console page takes.
        self.assertEqual(
            cartridge_frame_for(
                _FramedConsole.WITH_FRAME, VIEW_MODE_CARTRIDGE, mixed_consoles=False
            ),
            cartridge_frame_for(_FramedConsole.WITH_FRAME, VIEW_MODE_CARTRIDGE),
        )

    def test_a_grid_that_still_mixes_consoles_gets_no_frame(self):
        # One lattice, one card size: a mixed grid cannot draw per-console
        # shells, which is why the page is grouped instead.
        self.assertIsNone(
            cartridge_frame_for(
                _FramedConsole.WITH_FRAME, VIEW_MODE_CARTRIDGE, mixed_consoles=True
            )
        )

    def test_cover_view_draws_covers(self):
        self.assertIsNone(
            cartridge_frame_for(_FramedConsole.WITH_FRAME, VIEW_MODE_COVER)
        )

    def test_list_view_never_draws_a_frame(self):
        # A frame at thumbnail size is an unreadable smudge.
        self.assertIsNone(
            cartridge_frame_for(
                _FramedConsole.WITH_FRAME, VIEW_MODE_CARTRIDGE, compact=True
            )
        )

    def test_a_console_with_no_frame_art_falls_back_to_covers(self):
        if cartridge_render.has_frame(_FramedConsole.WITHOUT_FRAME):
            self.skipTest("the reference disc console gained frame art")
        self.assertIsNone(
            cartridge_frame_for(_FramedConsole.WITHOUT_FRAME, VIEW_MODE_CARTRIDGE)
        )

    def test_one_group_without_art_does_not_cost_the_others_theirs(self):
        # The page keeps its shelf; only that console's group shows covers.
        self.assertIsNone(
            cartridge_frame_for(_FramedConsole.WITHOUT_FRAME, VIEW_MODE_CARTRIDGE)
        )
        self.assertIsNotNone(
            cartridge_frame_for(_FramedConsole.WITH_FRAME, VIEW_MODE_CARTRIDGE)
        )

    def test_an_unknown_console_is_not_an_error(self):
        self.assertIsNone(cartridge_frame_for("NOPE", VIEW_MODE_CARTRIDGE))


class OneGridInPlayOrderTests(unittest.TestCase):
    """"Recently played" stays one grid and still draws cartridges (issue 942).

    Every shell is drawn at the same width, so the cell only has to be as tall
    as the tallest shell on the page.
    """

    SHELLED = ("FC", "SFC", "N64", "GBA")

    def setUp(self):
        self.consoles = [c for c in self.SHELLED if cartridge_render.has_frame(c)]
        if len(self.consoles) < 2 or cartridge_frame_svg(self.consoles[0]) is None:
            self.skipTest("not enough cartridge art shipped (or no rsvg)")

    def height(self, console):
        frame = cartridge_render.load_frame(cartridge_frame_svg(console))
        return frame.size_for_width(FIXED_ITEM_WIDTH)[1]

    def test_the_cell_follows_the_tallest_shell_on_the_page(self):
        tallest = max(self.consoles, key=self.height)
        self.assertEqual(
            tallest_cartridge_frame(self.consoles + ["PS"], VIEW_MODE_CARTRIDGE),
            cartridge_frame_svg(tallest),
        )

    def test_the_same_console_twice_is_looked_at_once(self):
        with unittest.mock.patch(
            "openemux.ui.card_layout.cartridge_frame_svg", wraps=cartridge_frame_svg
        ) as resolve:
            tallest_cartridge_frame([self.consoles[0]] * 3, VIEW_MODE_CARTRIDGE)
        resolve.assert_called_once_with(self.consoles[0])

    def test_a_page_of_consoles_with_no_shell_draws_covers(self):
        self.assertIsNone(tallest_cartridge_frame(["NO-SUCH-CONSOLE"], VIEW_MODE_CARTRIDGE))
        self.assertIsNone(tallest_cartridge_frame([], VIEW_MODE_CARTRIDGE))

    def test_cover_view_and_list_view_draw_no_shell(self):
        self.assertIsNone(tallest_cartridge_frame(self.consoles, VIEW_MODE_COVER))
        self.assertIsNone(
            tallest_cartridge_frame(self.consoles, VIEW_MODE_CARTRIDGE, compact=True)
        )


if __name__ == "__main__":
    unittest.main()
