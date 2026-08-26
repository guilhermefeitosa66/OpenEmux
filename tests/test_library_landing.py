"""Where the library lands, and what the sidebar offers, per library state.

The onboarding page for an empty library could never be shown: the Favorites
row is always in the sidebar, the list selects its first row as soon as it
takes focus, and a fresh install was met with "No favorites yet: right-click a
game" -- about a game it does not have (issue #224).
"""

import unittest

from openemux.ui.window import (
    ALL_CONSOLES_ID,
    FAVORITES_ID,
    LIBRARY_EMPTY_ID,
    OpenEmuxWindow,
    collection_scope,
)


class SidebarRowsTests(unittest.TestCase):
    def _rows(self, consoles, slugs=()):
        return OpenEmuxWindow._sidebar_row_ids(consoles, slugs)

    def test_an_empty_library_gets_no_rows_at_all(self):
        self.assertEqual(self._rows([]), [])

    def test_not_even_a_favorites_row(self):
        # The row that buried the onboarding page.
        self.assertNotIn(FAVORITES_ID, self._rows([]))

    def test_collections_are_not_offered_over_an_empty_library_either(self):
        # Every row is a view over ROMs; with none, they all lead nowhere.
        self.assertEqual(self._rows([], ["best-of-snes"]), [])

    def test_a_populated_library_keeps_its_usual_order(self):
        self.assertEqual(
            self._rows(["FC", "SFC"], ["best-of-snes"]),
            [
                ALL_CONSOLES_ID,
                FAVORITES_ID,
                collection_scope("best-of-snes"),
                "FC",
                "SFC",
            ],
        )

    def test_the_rows_come_back_with_the_first_console(self):
        self.assertEqual(self._rows([]), [])
        self.assertTrue(self._rows(["FC"]))


class LandingViewTests(unittest.TestCase):
    def _landing(self, consoles, target):
        return OpenEmuxWindow._landing_view(consoles, target)

    def test_an_empty_library_lands_on_the_onboarding_page(self):
        self.assertEqual(self._landing([], None), LIBRARY_EMPTY_ID)

    def test_an_empty_library_lands_there_even_with_a_remembered_view(self):
        # A library whose drive went away: the remembered console is gone, and
        # the page that says how to point the app at a folder is the useful one.
        self.assertEqual(self._landing([], "SFC"), LIBRARY_EMPTY_ID)

    def test_a_remembered_console_is_honoured(self):
        self.assertEqual(self._landing(["FC", "SFC"], "SFC"), "SFC")

    def test_the_virtual_views_are_honoured(self):
        self.assertEqual(self._landing(["FC"], ALL_CONSOLES_ID), ALL_CONSOLES_ID)
        self.assertEqual(self._landing(["FC"], FAVORITES_ID), FAVORITES_ID)

    def test_a_console_that_is_gone_falls_back_to_favorites(self):
        self.assertEqual(self._landing(["FC"], "SFC"), FAVORITES_ID)

    def test_no_remembered_view_falls_back_to_favorites(self):
        self.assertEqual(self._landing(["FC"], None), FAVORITES_ID)


if __name__ == "__main__":
    unittest.main()
