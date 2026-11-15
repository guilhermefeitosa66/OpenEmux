"""The Big Picture games page's filter chips (issue 957)."""

import tempfile
import unittest
from pathlib import Path

from openemux.core import library_facets as facets


def rom(name, console="SFC"):
    return {"name": name, "console": console, "path": f"/roms/{console}/{name}.sfc"}


class FactsCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        states = Path(self.tmp.name) / "SFC"
        (states / "Snes9x").mkdir(parents=True)
        (states / "Saved.state1").write_text("x")
        (states / "Snes9x" / "Deep.state").write_text("x")
        (states / "Auto.state.auto").write_text("x")  # not a user slot
        self.listed = []

        def states_dir_for(console):
            self.listed.append(console)
            return str(states) if console == "SFC" else None

        self.facts = facets.RomFacts(
            ["/roms/SFC/Fav.sfc"],
            states_dir_for,
            lambda r: r["name"] != "Bare",
            lambda path: 0 if "Never" in path else 1000.0,
        )


class TheFacts(FactsCase):
    def test_each_facet(self):
        f = self.facts
        self.assertTrue(f.has(rom("Fav"), facets.FAVORITES))
        self.assertFalse(f.has(rom("Saved"), facets.FAVORITES))
        self.assertTrue(f.has(rom("Saved"), facets.HAS_STATE))
        self.assertTrue(f.has(rom("Deep"), facets.HAS_STATE))
        self.assertFalse(f.has(rom("Auto"), facets.HAS_STATE))
        self.assertTrue(f.has(rom("Bare"), facets.MISSING_ARTWORK))
        self.assertFalse(f.has(rom("Saved"), facets.MISSING_ARTWORK))
        self.assertTrue(f.has(rom("Never"), facets.NEVER_PLAYED))
        self.assertFalse(f.has(rom("Saved"), facets.NEVER_PLAYED))
        self.assertFalse(f.has(rom("Saved"), "made-up"))

    def test_states_are_listed_once_per_console(self):
        for name in ("A", "B", "C"):
            self.facts.has(rom(name), facets.HAS_STATE)
        self.facts.has(rom("D", console="FC"), facets.HAS_STATE)
        self.assertEqual(self.listed, ["SFC", "FC"])

    def test_a_console_without_a_states_dir_has_no_states(self):
        self.assertFalse(self.facts.has(rom("Saved", console="FC"), facets.HAS_STATE))


class TheChips(FactsCase):
    def test_matches_needs_every_chip(self):
        f = self.facts
        self.assertTrue(facets.matches(rom("Bare"), (), f))
        self.assertTrue(facets.matches(rom("Bare"), {facets.MISSING_ARTWORK}, f))
        self.assertFalse(facets.matches(rom("Bare"), {facets.MISSING_ARTWORK, facets.FAVORITES}, f))
        # Unknown chips are ignored rather than matching nothing.
        self.assertTrue(facets.matches(rom("Bare"), {"made-up"}, f))

    def test_counts(self):
        roms = [rom("Fav"), rom("Saved"), rom("Bare"), rom("Never")]
        self.assertEqual(
            facets.facet_counts(roms, self.facts),
            {facets.FAVORITES: 1, facets.HAS_STATE: 1, facets.MISSING_ARTWORK: 1, facets.NEVER_PLAYED: 1},
        )

    def test_toggle_and_normalize(self):
        on = facets.toggle(frozenset(), facets.FAVORITES)
        self.assertEqual(on, {facets.FAVORITES})
        self.assertEqual(facets.toggle(on, facets.FAVORITES), frozenset())
        self.assertEqual(facets.toggle(on, "made-up"), on)
        self.assertEqual(facets.normalize(None), frozenset())
        self.assertEqual(facets.normalize(["made-up", facets.HAS_STATE]), {facets.HAS_STATE})


if __name__ == "__main__":
    unittest.main()
