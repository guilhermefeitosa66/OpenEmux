"""Mixed pages are grouped by console, in sidebar order (issue #384).

"All", "Favorites" and the collections concatenated every console's playlist
into one pile and sorted it A-Z, so a Mega Drive game sat between two SNES
ones. The grouping itself is pure: consoles in, groups out.
"""

import unittest

from openemux.core.library_groups import UNKNOWN_CONSOLE, group_roms_by_console


def _rom(name, console):
    return {"name": name, "console": console, "path": f"/roms/{console}/{name}"}


class GroupingTests(unittest.TestCase):
    def test_nothing_groups_into_nothing(self):
        self.assertEqual(group_roms_by_console([], ["FC", "SFC"]), [])

    def test_one_console_is_one_group(self):
        roms = [_rom("Contra", "FC"), _rom("Metroid", "FC")]
        self.assertEqual(group_roms_by_console(roms, ["FC"]), [("FC", roms)])

    def test_the_groups_follow_the_given_order(self):
        roms = [_rom("Contra", "FC"), _rom("Sonic", "MD"), _rom("Mario", "SFC")]
        self.assertEqual(
            [console for console, _ in group_roms_by_console(roms, ["SFC", "MD", "FC"])],
            ["SFC", "MD", "FC"],
        )

    def test_a_console_with_no_games_here_gets_no_group(self):
        # A header over nothing is worse than no header.
        roms = [_rom("Contra", "FC")]
        self.assertEqual(
            [console for console, _ in group_roms_by_console(roms, ["SFC", "FC", "MD"])],
            ["FC"],
        )

    def test_a_console_the_order_does_not_know_goes_last(self):
        # A console imported after the order was saved (issue #386).
        roms = [_rom("Sonic", "MD"), _rom("Contra", "FC")]
        self.assertEqual(
            [console for console, _ in group_roms_by_console(roms, ["FC"])],
            ["FC", "MD"],
        )

    def test_several_unknown_consoles_keep_the_order_they_appear_in(self):
        roms = [_rom("Sonic", "MD"), _rom("Alex", "SMS"), _rom("Contra", "FC")]
        self.assertEqual(
            [console for console, _ in group_roms_by_console(roms, ["FC"])],
            ["FC", "MD", "SMS"],
        )

    def test_no_order_at_all_keeps_first_seen_order(self):
        roms = [_rom("Sonic", "MD"), _rom("Contra", "FC")]
        self.assertEqual(
            [console for console, _ in group_roms_by_console(roms)],
            ["MD", "FC"],
        )

    def test_the_order_inside_a_group_is_the_order_it_arrived_in(self):
        # The page sorted the whole list first, so grouping must never move a
        # game past another game of the same console.
        roms = [
            _rom("Aladdin", "MD"),
            _rom("Chrono Trigger", "SFC"),
            _rom("Sonic", "MD"),
            _rom("Zelda", "SFC"),
        ]
        groups = dict(group_roms_by_console(roms, ["SFC", "MD"]))
        self.assertEqual([r["name"] for r in groups["SFC"]], ["Chrono Trigger", "Zelda"])
        self.assertEqual([r["name"] for r in groups["MD"]], ["Aladdin", "Sonic"])

    def test_every_rom_ends_up_in_exactly_one_group(self):
        roms = [_rom(f"Game {i}", ["FC", "SFC", "MD"][i % 3]) for i in range(30)]
        groups = group_roms_by_console(roms, ["FC", "SFC", "MD"])
        self.assertEqual(sum(len(games) for _, games in groups), len(roms))

    def test_a_rom_with_no_console_is_kept_rather_than_dropped(self):
        roms = [_rom("Contra", "FC"), {"name": "Mystery", "path": "/roms/x"}]
        groups = group_roms_by_console(roms, ["FC"])
        self.assertEqual([console for console, _ in groups], ["FC", UNKNOWN_CONSOLE])


if __name__ == "__main__":
    unittest.main()
