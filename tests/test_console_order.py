"""The console order is the user's, not the SYSTEMS list's (issue #386).

The sidebar walked SYSTEM_IDS and kept the consoles that had ROMs, so the
order was the declaration order of a Python list -- something nobody chose and
nobody could change. One stored list of ids now feeds the sidebar, the console
groups on "All", "Favorites" and the collections (#384) and the console
cycling, because all three read the same ``visible_consoles``.
"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from openemux.core.config import ConfigManager
from openemux.core.console_order import (
    apply_console_order,
    merge_visible_into_order,
    move_console,
    normalize_console_order,
    place_console,
)
from openemux.core.systems import SYSTEM_IDS


class NormalizeTests(unittest.TestCase):
    def test_the_familiar_names_resolve_to_canonical_ids(self):
        self.assertEqual(normalize_console_order(["SNES", "NES"]), ["SFC", "FC"])

    def test_an_unknown_console_is_dropped(self):
        self.assertEqual(normalize_console_order(["SFC", "NOPE"]), ["SFC"])

    def test_a_duplicate_is_kept_once(self):
        self.assertEqual(normalize_console_order(["SFC", "SNES", "FC"]), ["SFC", "FC"])

    def test_garbage_is_not_an_order(self):
        for value in (None, "SFC", 7, {"SFC": 1}):
            with self.subTest(value=value):
                self.assertEqual(normalize_console_order(value), [])

    def test_non_strings_inside_a_list_are_skipped(self):
        self.assertEqual(normalize_console_order([None, 3, "SFC"]), ["SFC"])

    def test_whitespace_is_forgiven(self):
        self.assertEqual(normalize_console_order([" SFC "]), ["SFC"])


class ApplyTests(unittest.TestCase):
    def test_no_stored_order_keeps_the_systems_order(self):
        consoles = ["SFC", "FC", "MD"]
        expected = [c for c in SYSTEM_IDS if c in set(consoles)]
        self.assertEqual(apply_console_order(consoles), expected)

    def test_the_stored_order_wins(self):
        self.assertEqual(
            apply_console_order(["FC", "MD", "SFC"], ["SFC", "MD", "FC"]),
            ["SFC", "MD", "FC"],
        )

    def test_a_console_the_order_does_not_know_goes_after_the_ones_it_does(self):
        # A console imported after the order was saved must not land at a
        # position nobody chose.
        ordered = apply_console_order(["FC", "MD", "SFC"], ["SFC"])
        self.assertEqual(ordered[0], "SFC")
        self.assertEqual(set(ordered[1:]), {"FC", "MD"})

    def test_the_unknown_ones_follow_the_systems_order_among_themselves(self):
        ordered = apply_console_order(["SFC", "FC", "MD"], ["SFC"])
        rest = [c for c in SYSTEM_IDS if c in {"FC", "MD"}]
        self.assertEqual(ordered[1:], rest)

    def test_a_stored_console_with_no_games_is_simply_absent(self):
        self.assertEqual(apply_console_order(["FC"], ["MD", "FC"]), ["FC"])

    def test_a_garbage_stored_value_falls_back_to_the_default(self):
        consoles = ["SFC", "FC"]
        expected = [c for c in SYSTEM_IDS if c in set(consoles)]
        self.assertEqual(apply_console_order(consoles, "nonsense"), expected)

    def test_nothing_in_the_library_is_nothing_to_order(self):
        self.assertEqual(apply_console_order([], ["SFC"]), [])

    def test_no_console_is_ever_lost(self):
        consoles = ["SFC", "FC", "MD", "GBA"]
        self.assertEqual(
            sorted(apply_console_order(consoles, ["MD"])), sorted(consoles)
        )


class MoveTests(unittest.TestCase):
    def test_moving_up(self):
        self.assertEqual(move_console(["FC", "MD", "SFC"], "SFC", -1), ["FC", "SFC", "MD"])

    def test_moving_down(self):
        self.assertEqual(move_console(["FC", "MD", "SFC"], "FC", 1), ["MD", "FC", "SFC"])

    def test_the_top_has_nowhere_further_up(self):
        order = ["FC", "MD"]
        self.assertEqual(move_console(order, "FC", -1), order)

    def test_the_bottom_has_nowhere_further_down(self):
        order = ["FC", "MD"]
        self.assertEqual(move_console(order, "MD", 1), order)

    def test_a_console_that_is_not_there_moves_nothing(self):
        order = ["FC", "MD"]
        self.assertEqual(move_console(order, "SFC", -1), order)

    def test_the_input_list_is_not_mutated(self):
        order = ["FC", "MD"]
        move_console(order, "MD", -1)
        self.assertEqual(order, ["FC", "MD"])


class PlaceTests(unittest.TestCase):
    """What a drop means: let go above some row, or past the last one."""

    def test_dropping_above_a_row(self):
        self.assertEqual(
            place_console(["FC", "GB", "SFC"], "SFC", "GB"), ["FC", "SFC", "GB"]
        )

    def test_dropping_past_the_end(self):
        self.assertEqual(
            place_console(["FC", "GB", "SFC"], "FC", None), ["GB", "SFC", "FC"]
        )

    def test_dropping_a_console_on_itself_changes_nothing(self):
        order = ["FC", "GB"]
        self.assertEqual(place_console(order, "FC", "FC"), order)

    def test_dropping_above_a_row_that_is_gone_puts_it_last(self):
        self.assertEqual(place_console(["FC", "GB"], "FC", "SFC"), ["GB", "FC"])


class MergeTests(unittest.TestCase):
    """A drag rearranges the *visible* consoles; the stored order is wider."""

    def test_a_console_with_no_games_keeps_its_slot(self):
        # The list is the user's arrangement, not a snapshot of the library:
        # delete every Mega Drive ROM, import one again, and it comes back
        # where it was.
        self.assertEqual(
            merge_visible_into_order(["MD", "FC", "SFC"], ["SFC", "FC"]),
            ["MD", "SFC", "FC"],
        )

    def test_a_console_the_stored_order_has_never_seen_lands_at_the_end(self):
        self.assertEqual(
            merge_visible_into_order(["FC", "GB"], ["FC", "GB", "MD"]),
            ["FC", "GB", "MD"],
        )

    def test_with_nothing_stored_the_visible_order_is_the_order(self):
        self.assertEqual(merge_visible_into_order([], ["SFC", "FC"]), ["SFC", "FC"])

    def test_the_visible_rearrangement_survives_the_merge(self):
        merged = merge_visible_into_order(["FC", "GB", "SFC"], ["SFC", "GB", "FC"])
        self.assertEqual(merged, ["SFC", "GB", "FC"])


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.config = ConfigManager(config_file=Path(self._tmp.name) / "config.yaml")

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_fresh_config_has_no_order_of_its_own(self):
        self.assertEqual(self.config.get_console_order(), [])

    def test_an_order_survives_a_reopen(self):
        self.config.set_console_order(["SNES", "MD"])
        reopened = ConfigManager(config_file=self.config.config_file)
        self.assertEqual(reopened.get_console_order(), ["SFC", "MD"])

    def test_what_is_stored_is_cleaned_first(self):
        self.assertEqual(
            self.config.set_console_order(["SFC", "bogus", "SNES", 7]), ["SFC"]
        )

    def test_restoring_the_default_empties_it(self):
        self.config.set_console_order(["MD"])
        self.config.clear_console_order()
        self.assertEqual(self.config.get_console_order(), [])
        self.assertEqual(
            ConfigManager(config_file=self.config.config_file).get_console_order(), []
        )


if __name__ == "__main__":
    unittest.main()
