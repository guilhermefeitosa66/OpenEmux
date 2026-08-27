"""The grid's model side: what a card no longer owns.

A virtualized grid keeps a screenful of widgets and re-binds them as the view
scrolls (issue #219), so the state that describes a *game* -- whether it is
selected, whether its artwork resolved, what the search box compares against --
moved off the card and onto ``RomEntry``. That state is plain Python and can be
tested without a display, which is more than the widgets it used to live on.
"""

import unittest

from openemux.ui.grid import RomEntry, entry_matches


def entry(name, path=None, console="SFC"):
    return RomEntry({"name": name, "path": path or f"/roms/{name}.sfc", "console": console})


class RomEntryTests(unittest.TestCase):
    def test_starts_unselected_with_artwork_unresolved(self):
        item = entry("Super Mario World")
        self.assertFalse(item.selected)
        self.assertIsNone(item.has_artwork)

    def test_search_name_is_precomputed_and_lowercased(self):
        self.assertEqual(entry("Super Mario World").search_name, "super mario world")

    def test_the_display_name_is_safe_for_gtk(self):
        """The library keeps the filesystem's own bytes; the label cannot.

        A name that is not valid UTF-8 arrives surrogate-escaped, and handing
        that to GTK raises (issue #214).
        """
        item = entry("Pok\udce9mon")
        self.assertNotIn("\udce9", item.display_name)
        item.display_name.encode("utf-8")  # must not raise

    def test_the_rom_dict_is_kept_untouched(self):
        rom = {"name": "Chrono Trigger", "path": "/roms/ct.sfc", "console": "SFC"}
        self.assertIs(RomEntry(rom).rom, rom)


class EntryMatchesTests(unittest.TestCase):
    def test_no_filter_lets_everything_through(self):
        self.assertTrue(entry_matches(entry("Sonic")))

    def test_the_query_matches_anywhere_in_the_name(self):
        item = entry("Super Mario World")
        self.assertTrue(entry_matches(item, "mario"))
        self.assertTrue(entry_matches(item, "world"))
        self.assertFalse(entry_matches(item, "zelda"))

    def test_the_artwork_filter_keeps_only_resolved_misses(self):
        missing = entry("A")
        missing.has_artwork = False
        found = entry("B")
        found.has_artwork = True
        unresolved = entry("C")

        self.assertTrue(entry_matches(missing, only_missing_artwork=True))
        self.assertFalse(entry_matches(found, only_missing_artwork=True))
        # Not yet answered: hidden, rather than flashed in and out as the
        # background fetches land (issue #127).
        self.assertFalse(entry_matches(unresolved, only_missing_artwork=True))

    def test_both_filters_have_to_agree(self):
        item = entry("Super Mario World")
        item.has_artwork = False
        self.assertTrue(entry_matches(item, "mario", only_missing_artwork=True))
        self.assertFalse(entry_matches(item, "zelda", only_missing_artwork=True))
        item.has_artwork = True
        self.assertFalse(entry_matches(item, "mario", only_missing_artwork=True))


if __name__ == "__main__":
    unittest.main()
