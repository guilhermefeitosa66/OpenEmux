"""A grouped page keeps every game on screen, however big it is (issue #511).

"All", "Favorites" and the collections stacked one grid per console in a box
inside the page's scroller. A box is wrapped in a viewport, so no grid ever
saw the page scroll, and a ``GtkGridView`` only builds the cards around an
anchor that never moved: past a few dozen rows a big console's group was
blank cells. ``GroupedScroll`` hands each grid the slice of the page that is
on screen instead.
"""

import time
import unittest

from tests.gtk_display import HAVE_DISPLAY, needs_display
from tests.window_harness import WindowCase


if HAVE_DISPLAY:
    import gi

    gi.require_version("Gtk", "4.0")
    from gi.repository import GLib, Gtk

    from openemux.ui.grouped_scroll import GroupedScroll
    from openemux.ui.scopes import ALL_CONSOLES_ID


def _pump_until(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    context = GLib.MainContext.default()
    while time.monotonic() < deadline:
        if predicate():
            return True
        while context.pending():
            context.iteration(False)
        time.sleep(0.005)
    return predicate()


def _settle(rounds=20):
    context = GLib.MainContext.default()
    for _ in range(rounds):
        while context.pending():
            context.iteration(False)
        time.sleep(0.01)


@needs_display
class TheWidgetTests(unittest.TestCase):
    """The container on its own, over plain grids of labels."""

    def setUp(self):
        self.bound = {}
        self.window = Gtk.Window(default_width=800, default_height=600)
        self.addCleanup(self.window.destroy)
        self.scroller = Gtk.ScrolledWindow()
        self.window.set_child(self.scroller)
        self.body = GroupedScroll()
        self.headers = []
        self.grids = []
        for tag, count in (("a", 600), ("b", 40)):
            header = Gtk.Label(label=tag)
            grid = self._grid(tag, count)
            self.body.add_section(header, grid)
            self.headers.append(header)
            self.grids.append(grid)
        self.scroller.set_child(self.body)
        self.window.present()
        self.vadj = self.scroller.get_vadjustment()
        # Bound is not laid out: a grid can bind its first cards before the
        # page has been allocated once.
        _pump_until(
            lambda: "a0" in self.bound
            and self.vadj.get_upper() > self.vadj.get_page_size() > 0
            and self.grids[0] in self.body._layout
        )

    def _grid(self, tag, count):
        store = Gtk.StringList.new([f"{tag}{index}" for index in range(count)])
        factory = Gtk.SignalListItemFactory()
        factory.connect(
            "setup",
            lambda _f, item: item.set_child(
                Gtk.Label(width_request=100, height_request=120, focusable=True)
            ),
        )

        def bind(_f, item):
            name = item.get_item().get_string()
            item.get_child().set_label(name)
            self.bound[name] = item.get_child()

        def unbind(_f, item):
            self.bound.pop(item.get_item().get_string(), None)

        factory.connect("bind", bind)
        factory.connect("unbind", unbind)
        grid = Gtk.GridView(model=Gtk.NoSelection(model=store), factory=factory)
        grid.set_min_columns(6)
        grid.set_max_columns(6)
        return grid

    def scroll_to(self, fraction):
        self.vadj.set_value((self.vadj.get_upper() - self.vadj.get_page_size()) * fraction)
        _settle()

    def test_the_scroller_takes_it_as_its_scrollable_with_no_viewport(self):
        self.assertIs(self.scroller.get_child(), self.body)
        self.assertIs(self.body.get_vadjustment(), self.vadj)

    def test_the_page_is_as_tall_as_every_group_together(self):
        # 100 rows of the first grid alone are taller than the window.
        self.assertGreater(self.vadj.get_upper(), 100 * 120)

    def test_every_game_gets_a_card_somewhere_on_the_way_down(self):
        seen = set(self.bound)
        for step in range(1, 41):
            self.scroll_to(step / 40)
            seen |= set(self.bound)
        self.assertEqual(len(seen), 640)

    def test_the_end_of_the_page_shows_the_last_game_of_both_groups(self):
        self.scroll_to(1)
        self.assertIn("b39", self.bound)
        self.scroll_to(self._fraction_of(self.grids[0], 0.995))
        self.assertIn("a599", self.bound)

    def test_the_middle_of_the_big_group_has_its_cards(self):
        self.scroll_to(self._fraction_of(self.grids[0], 0.5))
        self.assertTrue(any(f"a{index}" in self.bound for index in range(290, 310)))

    def _fraction_of(self, grid, within):
        top, height = self.body._layout[grid]
        target = top + height * within - self.vadj.get_page_size() / 2
        return max(0, target) / (self.vadj.get_upper() - self.vadj.get_page_size())

    def test_scrolling_never_unmaps_a_grid(self):
        unmapped = []
        for grid in self.grids:
            grid.connect("unmap", lambda g: unmapped.append(g))
        for step in (0.25, 0.5, 1, 0.75, 0):
            self.scroll_to(step)
        self.assertEqual(unmapped, [])

    def test_a_hidden_group_takes_no_room(self):
        before = self.vadj.get_upper()
        self.headers[0].set_visible(False)
        self.grids[0].set_visible(False)
        _settle()
        self.assertLess(self.vadj.get_upper(), before / 2)
        self.assertIn("b0", self.bound)

    def test_a_page_that_gets_shorter_clamps_the_scroll(self):
        self.scroll_to(1)
        self.headers[0].set_visible(False)
        self.grids[0].set_visible(False)
        _settle()
        self.assertLessEqual(
            self.vadj.get_value(), self.vadj.get_upper() - self.vadj.get_page_size()
        )
        self.assertIn("b39", self.bound)

    def test_a_grid_scrolling_itself_is_put_back_to_its_slice(self):
        # GTK scrolls a grid to the card that takes focus; on this page the
        # scrolling is the page's, so the grid stays where the page has it.
        self.scroll_to(0)
        self.grids[0].scroll_to(300, Gtk.ListScrollFlags.FOCUS, None)
        _settle()
        self.assertEqual(self.vadj.get_value(), 0)
        self.assertEqual(self.grids[0].get_vadjustment().get_value(), 0)
        self.assertIn("a0", self.bound)

    def test_revealing_an_item_below_the_window_scrolls_down_to_it(self):
        self.scroll_to(0)
        self.assertTrue(self.body.reveal_position(self.grids[0], 300))
        _settle()
        self.assertIn("a300", self.bound)
        self.assertIs(self.bound["a300"].get_mapped(), True)
        ok, bounds = self.bound["a300"].compute_bounds(self.body)
        self.assertTrue(ok)
        self.assertGreaterEqual(bounds.get_y(), 0)
        self.assertLessEqual(
            bounds.get_y() + bounds.get_height(), self.vadj.get_page_size() + 1
        )

    def test_revealing_an_item_above_the_window_scrolls_up_to_it(self):
        self.scroll_to(1)
        self.assertTrue(self.body.reveal_position(self.grids[0], 0))
        _settle()
        top, _height = self.body._layout[self.grids[0]]
        self.assertEqual(self.vadj.get_value(), top)
        self.assertIn("a0", self.bound)

    def test_revealing_an_item_already_on_screen_leaves_the_page_alone(self):
        self.scroll_to(0)
        self.assertTrue(self.body.reveal_position(self.grids[0], 0))
        self.assertEqual(self.vadj.get_value(), 0)

    def test_a_grid_that_was_never_laid_out_is_not_revealed(self):
        self.assertFalse(self.body.reveal_position(Gtk.GridView(), 0))

    def test_a_grid_with_no_model_is_one_row(self):
        grid = Gtk.GridView()
        self.body.add_section(Gtk.Label(label="c"), grid)
        _settle()
        self.assertTrue(self.body.reveal_position(grid, 0))

    def test_a_scroll_during_a_layout_pass_lays_the_page_out_again(self):
        # A card focused while the grids are allocated reveals itself then.
        self.scroll_to(0)
        original = self.body._allocate_children
        passes = []

        def allocate(width, height, scroll):
            passes.append(scroll)
            original(width, height, scroll)
            if len(passes) == 1:
                self.vadj.set_value(500)

        self.body._allocate_children = allocate
        self.body.queue_allocate()
        _settle()
        self.assertEqual(passes[:2], [0, 500])

    def test_the_width_is_the_widest_child_and_never_scrolls(self):
        minimum, natural, _, _ = self.body.measure(Gtk.Orientation.HORIZONTAL, -1)
        self.assertGreaterEqual(natural, minimum)
        hadj = self.scroller.get_hadjustment()
        self.assertIs(self.body.get_hadjustment(), hadj)
        self.assertEqual(hadj.get_upper(), hadj.get_page_size())

    def test_destroying_it_lets_go_of_its_children(self):
        self.scroller.set_child(None)
        self.body.run_dispose()
        self.assertIsNone(self.grids[0].get_parent())
        self.assertIsNone(self.headers[1].get_parent())


@needs_display
class WithNoScrollerTests(unittest.TestCase):
    """Allocated with no adjustments at all: nothing to scroll, nothing breaks."""

    def test_it_lays_out_without_adjustments(self):
        window = Gtk.Window(default_width=300, default_height=200)
        self.addCleanup(window.destroy)
        body = GroupedScroll()
        body.add_section(Gtk.Label(label="h"), Gtk.GridView())
        window.set_child(body)
        window.present()
        _settle()
        self.assertIsNone(body.get_vadjustment())
        self.assertFalse(body.reveal_position(body._sections[0][1], 0))

    def test_a_new_adjustment_replaces_the_old_one(self):
        body = GroupedScroll()
        first, second = Gtk.Adjustment(), Gtk.Adjustment()
        body.set_vadjustment(first)
        body.set_vadjustment(second)
        first.set_value(10)  # no longer connected: must not reach the widget
        self.assertIs(body.get_vadjustment(), second)
        self.assertFalse(body.get_border()[0])


@needs_display
class TheAllPageTests(WindowCase):
    """The bug as reported: "All" over a console with hundreds of games."""

    library = {
        "FC": [f"Game {index:03d} (USA).nes" for index in range(600)],
        "SFC": [f"Quest {index:02d} (USA).sfc" for index in range(40)],
    }

    def setUp(self):
        super().setUp()
        self.win.set_default_size(1400, 700)
        self.win.sidebar.select(ALL_CONSOLES_ID)
        self.show()
        self.group = self.win.pages.grid_for(ALL_CONSOLES_ID)
        self.fc, self.sfc = self.group.grids()
        self.pump_until(lambda: self.fc.card_for(self.fc.entries()[0]) is not None)
        self.vadj = self.fc.get_parent().get_vadjustment()

    def scroll_to(self, value):
        self.vadj.set_value(value)
        self.pump()
        _settle()

    def scroll_into(self, grid, within):
        top, height = grid.get_parent()._layout[grid]
        self.scroll_to(max(0, top + height * within - self.vadj.get_page_size() / 2))

    def test_the_page_body_is_the_grouped_scroller(self):
        self.assertIsInstance(self.fc.get_parent(), GroupedScroll)

    def test_the_last_game_of_each_group_has_a_card_at_the_end(self):
        self.scroll_to(self.vadj.get_upper())
        self.assertIsNotNone(self.sfc.card_for(self.sfc.entries()[-1]))
        self.scroll_into(self.fc, 0.999)
        self.assertIsNotNone(self.fc.card_for(self.fc.entries()[-1]))

    def test_the_middle_of_the_big_group_has_its_cards(self):
        self.scroll_into(self.fc, 0.5)
        middle = self.fc.entries()[280:320]
        self.assertTrue(any(self.fc.card_for(entry) is not None for entry in middle))

    def test_fewer_columns_still_reach_the_end(self):
        columns = self.fc.get_max_columns()
        # Shrink from the width the window got, not the one it asked for: a
        # toplevel is clamped to the monitor, and a CI runner's screen can be
        # narrower than 1400 (the Windows one is 1024). Stay above the 700sp
        # breakpoint, past which the layout changes for other reasons.
        width = self.win.get_width()
        self.win.set_default_size(max(800, width - 400), 700)
        self.assertTrue(
            self.pump_until(lambda: self.fc.get_max_columns() < columns),
            f"{columns} columns at {width}px, {self.fc.get_max_columns()} after",
        )
        # The columns change while the grid is allocated; the page lays itself
        # out again on the next pass, and only then is the group its new height.
        body = self.fc.get_parent()
        self.assertTrue(
            self.pump_until(
                lambda: body._layout[self.fc][1]
                == self.fc.measure(Gtk.Orientation.VERTICAL, body.get_width())[1]
            )
        )
        self.scroll_into(self.fc, 0.999)
        self.assertIsNotNone(self.fc.card_for(self.fc.entries()[-1]))

    def test_a_search_that_hides_the_first_group_keeps_the_second_on_screen(self):
        self.scroll_to(self.vadj.get_upper())
        self.group.set_filter("quest")
        _settle()
        self.assertFalse(self.fc.get_visible())
        self.assertIsNotNone(self.sfc.card_for(self.sfc.visible_entries()[0]))
        self.group.set_filter("")
        _settle()
        self.assertTrue(self.fc.get_visible())

    def test_focusing_the_last_card_of_the_big_group_brings_it_on_screen(self):
        self.scroll_to(0)
        self.assertTrue(self.fc.focus_last_card())
        last = self.fc.entries()[-1]
        self.assertTrue(self.pump_until(lambda: self.fc.card_for(last) is not None))
        self.pump_until(lambda: self.vadj.get_value() > 0)
        self.assertGreater(self.vadj.get_value(), 0)

    def test_entering_the_next_group_from_above_scrolls_the_page_to_it(self):
        self.scroll_into(self.fc, 0.999)
        before = self.vadj.get_value()
        self.assertTrue(self.sfc.focus_first_card())
        self.assertTrue(
            self.pump_until(lambda: self.sfc.card_for(self.sfc.entries()[0]) is not None)
        )
        self.pump_until(lambda: self.vadj.get_value() > before)
        top, _height = self.sfc.get_parent()._layout[self.sfc]
        self.assertGreater(self.vadj.get_value() + self.vadj.get_page_size(), top)

    def focused_card_is_on_screen(self):
        focus = self.win.get_focus()
        body = self.fc.get_parent()
        ok, bounds = focus.compute_bounds(body)
        if not ok:
            return False
        top = bounds.get_y()
        bottom = top + bounds.get_height()
        return bottom > 0 and top < body.get_height()

    def walk(self, direction, presses, settle_every):
        """Press ``direction`` like a key held down; check the focus as it goes."""
        lost = []
        for press in range(1, presses + 1):
            self.win.navigation._cmd_move(direction)
            self.pump()
            if press % settle_every == 0:
                _settle()
                if not self.focused_card_is_on_screen():
                    lost.append(press)
        return lost

    def test_walking_down_a_tall_group_keeps_the_focused_card_on_screen(self):
        # QA round 1 of #511: after a hundred-odd presses the page scrolled
        # back up and left the focused card below the window.
        self.scroll_to(0)
        self.assertTrue(self.fc.focus_first_card())
        self.assertTrue(self.pump_until(lambda: self.win.get_focus() is not None))
        self.assertEqual(self.walk("down", 200, 10), [])
        self.assertEqual(self.walk("up", 60, 10), [])


if __name__ == "__main__":
    unittest.main()
