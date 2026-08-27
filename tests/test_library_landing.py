"""Where the library lands, and what the sidebar offers, per library state.

The onboarding page for an empty library could never be shown: the Favorites
row is always in the sidebar, the list selects its first row as soon as it
takes focus, and a fresh install was met with "No favorites yet: right-click a
game" -- about a game it does not have (issue #224).
"""

import unittest

from openemux.ui.window import OpenEmuxWindow
from openemux.ui.scopes import (
    ALL_CONSOLES_ID,
    FAVORITES_ID,
    LIBRARY_EMPTY_ID,
    collection_scope,
    landing_view,
    sidebar_row_ids,
)


class SidebarRowsTests(unittest.TestCase):
    def _rows(self, consoles, slugs=()):
        return sidebar_row_ids(consoles, slugs)

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
        return landing_view(consoles, target)

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


class CollectionSurvivesARescanTests(unittest.TestCase):
    """A rescan must not throw the user out of the collection they are in.

    Every rescan ends in refresh_library(preferred_view=origin_view), and the
    startup scan rescans on every launch -- so browsing a collection when it
    finished meant being yanked to Favorites, losing the view and the scroll
    position (issue #225).
    """

    def _landing(self, target, slugs=("best-of-snes",)):
        return landing_view(["FC", "SFC"], target, slugs)

    def test_a_collection_that_still_exists_is_kept(self):
        scope = collection_scope("best-of-snes")
        self.assertEqual(self._landing(scope), scope)

    def test_a_collection_that_was_deleted_falls_back_to_favorites(self):
        # No more a destination than a console that is gone.
        self.assertEqual(self._landing(collection_scope("gone")), FAVORITES_ID)

    def test_no_collections_at_all_falls_back_to_favorites(self):
        self.assertEqual(
            self._landing(collection_scope("best-of-snes"), slugs=()), FAVORITES_ID
        )

    def test_an_empty_library_still_wins_over_a_collection(self):
        self.assertEqual(
            landing_view([], collection_scope("best-of-snes"), ["best-of-snes"]),
            LIBRARY_EMPTY_ID,
        )

    def test_consoles_and_virtual_views_are_unaffected(self):
        self.assertEqual(self._landing("SFC"), "SFC")
        self.assertEqual(self._landing(ALL_CONSOLES_ID), ALL_CONSOLES_ID)
        self.assertEqual(self._landing(FAVORITES_ID), FAVORITES_ID)


class _QueueStub:
    """Just the rescan-queue state, so the merge rules can be asked."""

    _rescan_pending = None

    def __init__(self):
        self.started = []

    _queue_rescan = OpenEmuxWindow._queue_rescan
    _run_pending_rescan = OpenEmuxWindow._run_pending_rescan

    def _rescan_all_consoles(self, show_toast=False):
        self.started.append((None, show_toast))

    def _rescan_single_console(self, console, show_toast=False):
        self.started.append((console, show_toast))


class RescanQueueTests(unittest.TestCase):
    """A rescan asked for while one runs must happen, not vanish (#225)."""

    def test_a_dropped_rescan_runs_when_the_current_one_ends(self):
        # The reported failure: an import finishes while the always-on startup
        # scan is still in flight, so its rescan was dropped with no retry and
        # no message -- "imported", and then no new games.
        stub = _QueueStub()
        stub._queue_rescan(console=None, show_toast=False)
        stub._run_pending_rescan()
        self.assertEqual(stub.started, [(None, False)])

    def test_nothing_queued_starts_nothing(self):
        stub = _QueueStub()
        stub._run_pending_rescan()
        self.assertEqual(stub.started, [])

    def test_the_queue_is_consumed_once(self):
        stub = _QueueStub()
        stub._queue_rescan(console=None, show_toast=False)
        stub._run_pending_rescan()
        stub._run_pending_rescan()
        self.assertEqual(stub.started, [(None, False)])

    def test_a_single_console_request_is_kept_as_itself(self):
        stub = _QueueStub()
        stub._queue_rescan(console="SFC", show_toast=True)
        stub._run_pending_rescan()
        self.assertEqual(stub.started, [("SFC", True)])

    def test_a_full_rescan_absorbs_a_later_single_one(self):
        stub = _QueueStub()
        stub._queue_rescan(console=None, show_toast=False)
        stub._queue_rescan(console="SFC", show_toast=False)
        stub._run_pending_rescan()
        self.assertEqual(stub.started, [(None, False)])

    def test_two_different_consoles_become_a_full_rescan(self):
        stub = _QueueStub()
        stub._queue_rescan(console="FC", show_toast=False)
        stub._queue_rescan(console="SFC", show_toast=False)
        stub._run_pending_rescan()
        self.assertEqual(stub.started, [(None, False)])

    def test_the_same_console_twice_stays_one_request(self):
        stub = _QueueStub()
        stub._queue_rescan(console="FC", show_toast=False)
        stub._queue_rescan(console="FC", show_toast=False)
        stub._run_pending_rescan()
        self.assertEqual(stub.started, [("FC", False)])

    def test_a_request_that_wanted_a_toast_keeps_it_through_a_merge(self):
        stub = _QueueStub()
        stub._queue_rescan(console="FC", show_toast=True)
        stub._queue_rescan(console=None, show_toast=False)
        stub._run_pending_rescan()
        self.assertEqual(stub.started, [(None, True)])


if __name__ == "__main__":
    unittest.main()
