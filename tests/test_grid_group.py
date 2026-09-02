"""The grids of a mixed page, spoken to as if they were one (issue #384).

"All", "Favorites" and the collections are grouped by console, and each group
is a grid of its own -- so "the grid of this page" stopped being one object,
and the dozen places in the window and the navigation controller that assumed
it was talk to this façade instead.
"""

import unittest

from openemux.core.library_view import SORT_ORDERS, SORT_PLATFORM
from openemux.ui.grid_group import GridGroup, GridSection
from openemux.ui.library_pages import is_mixed_scope
from openemux.ui.scopes import ALL_CONSOLES_ID, FAVORITES_ID, collection_scope
from openemux.ui.window import OpenEmuxWindow


class _Entry:
    def __init__(self, name, selected=False):
        self.name = name
        self.selected = selected

    def __repr__(self):  # pragma: no cover - test output only
        return f"<{self.name}>"


class _Container:
    def __init__(self):
        self._visible = True

    def set_visible(self, visible):
        self._visible = bool(visible)

    def get_visible(self):
        return self._visible


class _Grid:
    """Everything the group asks of a grid, and nothing that needs a display."""

    def __init__(self, console, names):
        self.console = console
        self._entries = [_Entry(name) for name in names]
        self._query = ""
        self.compact = False
        self.calls = []

    # -- what it holds
    def entries(self):
        return list(self._entries)

    def visible_entries(self):
        return [e for e in self._entries if self._query in e.name.lower()]

    def count(self):
        return len(self.visible_entries())

    # -- filtering
    def set_filter(self, query="", only_missing_artwork=False):
        self._query = (query or "").lower()

    # -- selection
    def selected_roms(self):
        return [e.name for e in self._entries if e.selected]

    def clear_selection(self):
        for entry in self._entries:
            entry.selected = False

    def select_all(self):
        for entry in self.visible_entries():
            entry.selected = True

    def sync_visible_selection(self):
        self.calls.append("sync")

    def note_cursor(self, item, keep_anchor=False):
        self.calls.append(("note", item, keep_anchor))

    def begin_range_from(self, item):
        self.calls.append(("anchor", item))

    def extend_selection_to(self, item, additive=False):
        self.calls.append(("extend", item, additive))

    def toggle_item(self, item):
        self.calls.append(("toggle", item))

    def select_item(self, item):
        self.calls.append(("select", item))

    # -- focus
    def focus_first_card(self):
        self.calls.append("focus-first")
        return bool(self.visible_entries())

    def focus_last_card(self):
        self.calls.append("focus-last")
        return bool(self.visible_entries())

    def has_focus_memory(self):
        return False

    # -- per-ROM refreshes
    def refresh_rom_frame(self, rom):
        return rom.get("console") == self.console

    def refresh_rom_artwork(self, rom, fade=False):
        return rom.get("console") == self.console


def _group(*specs):
    group = GridGroup()
    grids = []
    for console, names in specs:
        grid = _Grid(console, names)
        grids.append(grid)
        group.add_section(GridSection(console, grid, _Container(), object()))
    return group, grids


class WhatThePageHoldsTests(unittest.TestCase):
    def test_the_entries_of_every_group_in_order(self):
        group, _ = _group(("FC", ["Contra"]), ("SFC", ["Zelda", "Mario"]))
        self.assertEqual(
            [e.name for e in group.entries()], ["Contra", "Zelda", "Mario"]
        )

    def test_the_count_is_the_whole_page(self):
        group, _ = _group(("FC", ["Contra"]), ("SFC", ["Zelda", "Mario"]))
        self.assertEqual(group.count(), 3)

    def test_an_empty_page_counts_nothing(self):
        self.assertEqual(GridGroup().count(), 0)

    def test_the_consoles_are_the_groups_in_order(self):
        group, _ = _group(("SFC", ["Zelda"]), ("FC", ["Contra"]))
        self.assertEqual(group.consoles(), ["SFC", "FC"])


class FilteringTests(unittest.TestCase):
    def test_the_search_reaches_every_group(self):
        group, grids = _group(("FC", ["Contra", "Mario"]), ("SFC", ["Mario Kart"]))
        group.set_filter("mario")
        self.assertEqual([e.name for e in group.visible_entries()], ["Mario", "Mario Kart"])

    def test_a_group_the_search_empties_is_hidden(self):
        group, _ = _group(("FC", ["Contra"]), ("SFC", ["Mario Kart"]))
        group.set_filter("mario")
        visible = [s.console for s in group.sections if s.container.get_visible()]
        self.assertEqual(visible, ["SFC"])

    def test_clearing_the_search_brings_the_groups_back(self):
        group, _ = _group(("FC", ["Contra"]), ("SFC", ["Mario Kart"]))
        group.set_filter("mario")
        group.set_filter("")
        visible = [s.console for s in group.sections if s.container.get_visible()]
        self.assertEqual(visible, ["FC", "SFC"])

    def test_the_count_follows_the_filter(self):
        group, _ = _group(("FC", ["Contra", "Mario"]))
        group.set_filter("mario")
        self.assertEqual(group.count(), 1)


class SelectionTests(unittest.TestCase):
    def test_select_all_crosses_every_group(self):
        group, _ = _group(("FC", ["Contra"]), ("SFC", ["Zelda", "Mario"]))
        group.select_all()
        self.assertEqual(len(group.selected_roms()), 3)

    def test_clearing_crosses_every_group(self):
        group, _ = _group(("FC", ["Contra"]), ("SFC", ["Zelda"]))
        group.select_all()
        group.clear_selection()
        self.assertEqual(group.selected_roms(), [])

    def test_ctrl_a_on_a_partly_selected_page_selects_the_rest(self):
        # One group fully selected is not the page fully selected.
        group, grids = _group(("FC", ["Contra"]), ("SFC", ["Zelda"]))
        grids[0].select_all()
        group.toggle_select_all()
        self.assertEqual(len(group.selected_roms()), 2)

    def test_ctrl_a_again_clears_the_page(self):
        group, _ = _group(("FC", ["Contra"]), ("SFC", ["Zelda"]))
        group.toggle_select_all()
        group.toggle_select_all()
        self.assertEqual(group.selected_roms(), [])

    def test_ctrl_a_on_an_empty_page_selects_nothing_rather_than_clearing(self):
        group, _ = _group(("FC", []))
        group.toggle_select_all()
        self.assertEqual(group.selected_roms(), [])

    def test_the_page_reports_every_group_when_one_of_them_moves(self):
        # Each grid tells its own callback about its own ROMs; without the
        # group in between, selecting in the second silently dropped the first.
        reported = []
        group, grids = _group(("FC", ["Contra"]), ("SFC", ["Zelda"]))
        group.on_selection_changed = reported.append
        grids[0].select_all()
        grids[1].select_all()
        group.on_child_selection_changed()
        self.assertEqual(reported[-1], ["Contra", "Zelda"])

    def test_a_range_stays_in_the_group_it_was_started_in(self):
        group, grids = _group(("FC", ["Contra"]), ("SFC", ["Zelda"]))
        entry = grids[1].entries()[0]
        group.begin_range_from(entry)
        group.extend_selection_to(entry)
        self.assertEqual(grids[0].calls, [])
        self.assertEqual(
            grids[1].calls, [("anchor", entry), ("extend", entry, False)]
        )

    def test_an_item_from_no_group_is_ignored(self):
        group, grids = _group(("FC", ["Contra"]))
        group.toggle_item(_Entry("Stranger"))
        self.assertEqual(grids[0].calls, [])


class NavigationTests(unittest.TestCase):
    def test_a_widget_of_one_of_the_grids_is_the_page_grid(self):
        group, grids = _group(("FC", ["Contra"]), ("SFC", ["Zelda"]))
        self.assertTrue(group.holds_widget(grids[1]))
        self.assertFalse(group.holds_widget(object()))

    def test_the_next_group_down_and_up(self):
        group, grids = _group(("FC", ["A"]), ("GB", ["B"]), ("SFC", ["C"]))
        self.assertIs(group.grid_after(grids[0]), grids[1])
        self.assertIs(group.grid_before(grids[2]), grids[1])

    def test_there_is_nothing_past_the_ends(self):
        group, grids = _group(("FC", ["A"]), ("SFC", ["C"]))
        self.assertIsNone(group.grid_after(grids[-1]))
        self.assertIsNone(group.grid_before(grids[0]))

    def test_a_group_the_search_hid_is_skipped(self):
        group, grids = _group(("FC", ["Mario"]), ("GB", ["Tetris"]), ("SFC", ["Mario Kart"]))
        group.set_filter("mario")
        self.assertIs(group.grid_after(grids[0]), grids[2])

    def test_focus_lands_in_the_first_group_that_has_a_card(self):
        group, grids = _group(("FC", []), ("SFC", ["Zelda"]))
        self.assertTrue(group.focus_first_card())
        self.assertEqual(grids[1].calls, ["focus-first"])


class RefreshTests(unittest.TestCase):
    def test_a_rom_is_refreshed_by_the_group_that_owns_it(self):
        group, _ = _group(("FC", ["Contra"]), ("SFC", ["Zelda"]))
        self.assertTrue(group.refresh_rom_artwork({"console": "SFC"}))
        self.assertFalse(group.refresh_rom_artwork({"console": "MD"}))

    def test_the_same_for_a_cartridge_shell(self):
        group, _ = _group(("FC", ["Contra"]))
        self.assertTrue(group.refresh_rom_frame({"console": "FC"}))


class MixedScopeTests(unittest.TestCase):
    """Which pages are grouped at all."""

    def test_the_three_mixed_pages(self):
        for scope in (ALL_CONSOLES_ID, FAVORITES_ID, collection_scope("best")):
            with self.subTest(scope=scope):
                self.assertTrue(is_mixed_scope(scope))

    def test_a_console_page_is_left_alone(self):
        self.assertFalse(is_mixed_scope("SFC"))
        self.assertFalse(is_mixed_scope(None))


class _ScopeStub:
    _sort_orders_for_scope = OpenEmuxWindow._sort_orders_for_scope
    _scope_groups_by_console = OpenEmuxWindow._scope_groups_by_console

    def __init__(self, scope):
        self.scope = scope

    def _current_scope(self):
        return self.scope


class SortOrdersOnAGroupedPageTests(unittest.TestCase):
    """"Platform" is not offered where it would do nothing (issue #384)."""

    def test_a_grouped_page_does_not_offer_platform(self):
        for scope in (ALL_CONSOLES_ID, FAVORITES_ID, collection_scope("best")):
            with self.subTest(scope=scope):
                self.assertNotIn(
                    SORT_PLATFORM, _ScopeStub(scope)._sort_orders_for_scope()
                )

    def test_it_offers_every_other_order(self):
        offered = _ScopeStub(ALL_CONSOLES_ID)._sort_orders_for_scope()
        self.assertEqual(offered, [o for o in SORT_ORDERS if o != SORT_PLATFORM])

    def test_a_console_page_keeps_the_full_list(self):
        self.assertEqual(_ScopeStub("SFC")._sort_orders_for_scope(), list(SORT_ORDERS))


if __name__ == "__main__":
    unittest.main()
