"""The library reopens where it was left (issue #383).

Nothing was remembered: the landing page was computed from what was on screen
*right now*, which at startup is nothing at all, so every launch fell through
to the default. The view lives in a file of its own -- it is written on every
navigation, and config.yaml holds the ROM path, the credentials, the
per-console cores and the input profiles, none of which want rewriting that
often.
"""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from openemux.core import state_recovery
from openemux.core.session_store import DEFAULT_SESSION, SessionStore
from openemux.ui.scopes import ALL_CONSOLES_ID, LIBRARY_EMPTY_ID, collection_scope
from openemux.ui.window import OpenEmuxWindow


class SessionStoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.path = self.root / "session.json"
        state_recovery.reset_quarantine_log()

    def tearDown(self):
        self._tmp.cleanup()
        state_recovery.reset_quarantine_log()

    def _store(self):
        return SessionStore(self.path)

    # -- the round trip ----------------------------------------------------
    def test_a_fresh_install_remembers_nothing(self):
        self.assertIsNone(self._store().get_last_view())

    def test_nothing_is_written_before_there_is_something_to_write(self):
        self._store().get_last_view()
        self.assertFalse(self.path.exists())

    def test_a_view_survives_a_new_store_on_the_same_file(self):
        self._store().set_last_view("SFC")
        self.assertEqual(self._store().get_last_view(), "SFC")

    def test_the_virtual_views_and_collections_round_trip_too(self):
        for view in ("__all__", "__favorites__", "col:best-of-snes"):
            with self.subTest(view=view):
                self._store().set_last_view(view)
                self.assertEqual(self._store().get_last_view(), view)

    def test_the_file_is_json_with_the_view_in_it(self):
        self._store().set_last_view("MD")
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(data["last_view"], "MD")
        self.assertEqual(data["version"], DEFAULT_SESSION["version"])

    def test_storing_the_same_view_again_writes_nothing(self):
        # Every navigation asks; a rescan that lands where it started must not
        # cost a write.
        store = self._store()
        self.assertTrue(store.set_last_view("SFC"))
        stamp = self.path.stat().st_mtime_ns
        self.assertFalse(store.set_last_view("SFC"))
        self.assertEqual(self.path.stat().st_mtime_ns, stamp)

    def test_a_later_view_replaces_the_earlier_one(self):
        store = self._store()
        store.set_last_view("SFC")
        store.set_last_view("MD")
        self.assertEqual(self._store().get_last_view(), "MD")

    # -- what the file can be, and what it must never cost -----------------
    def test_an_unreadable_file_is_set_aside_and_not_overwritten(self):
        self.path.write_text("{not json", encoding="utf-8")

        self.assertIsNone(self._store().get_last_view())

        kept = state_recovery.quarantined_files()
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["original"], self.path)
        self.assertTrue(Path(kept[0]["kept_as"]).exists())
        self.assertEqual(
            Path(kept[0]["kept_as"]).read_text(encoding="utf-8"), "{not json"
        )

    def test_a_file_that_is_not_an_object_is_set_aside_too(self):
        self.path.write_text('["SFC"]', encoding="utf-8")
        self.assertIsNone(self._store().get_last_view())
        self.assertEqual(len(state_recovery.quarantined_files()), 1)

    def test_a_view_that_is_not_a_string_reads_as_nothing_stored(self):
        self.path.write_text(json.dumps({"last_view": 7}), encoding="utf-8")
        self.assertIsNone(self._store().get_last_view())

    def test_an_empty_view_reads_as_nothing_stored(self):
        self.path.write_text(json.dumps({"last_view": "   "}), encoding="utf-8")
        self.assertIsNone(self._store().get_last_view())

    def test_a_missing_version_does_not_lose_the_view(self):
        self.path.write_text(json.dumps({"last_view": "GBA"}), encoding="utf-8")
        self.assertEqual(self._store().get_last_view(), "GBA")

    def test_clearing_the_view_is_allowed(self):
        store = self._store()
        store.set_last_view("SFC")
        store.set_last_view(None)
        self.assertIsNone(self._store().get_last_view())

    def test_a_directory_that_cannot_be_written_does_not_raise(self):
        # A file where the directory should be: the save fails, and the app
        # opens on the default next time rather than dying on the way out.
        blocker = self.root / "blocked"
        blocker.write_text("not a directory", encoding="utf-8")
        store = SessionStore(blocker / "session.json")
        self.assertFalse(store.set_last_view("SFC"))


class _WindowStub:
    """Just the window's half of remembering: what it stores, and when."""

    _remember_current_view = OpenEmuxWindow._remember_current_view
    _on_close_remember_view = OpenEmuxWindow._on_close_remember_view

    class _Config:
        def __init__(self, session):
            self.session = session

    def __init__(self, store, view):
        self.config_manager = self._Config(store)
        self.current_console = view


class WhatTheWindowRemembersTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.store = SessionStore(Path(self._tmp.name) / "session.json")

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_console_is_remembered(self):
        _WindowStub(self.store, "SFC")._remember_current_view()
        self.assertEqual(self.store.get_last_view(), "SFC")

    def test_so_are_all_and_a_collection(self):
        for view in (ALL_CONSOLES_ID, collection_scope("best-of-snes")):
            with self.subTest(view=view):
                _WindowStub(self.store, view)._remember_current_view()
                self.assertEqual(self.store.get_last_view(), view)

    def test_the_onboarding_page_is_not_a_view_to_come_back_to(self):
        # A library whose drive went missing lands there; storing it would
        # throw away the console the user was actually on.
        self.store.set_last_view("SFC")
        _WindowStub(self.store, LIBRARY_EMPTY_ID)._remember_current_view()
        self.assertEqual(self.store.get_last_view(), "SFC")

    def test_being_nowhere_stores_nothing(self):
        self.store.set_last_view("SFC")
        _WindowStub(self.store, None)._remember_current_view()
        self.assertEqual(self.store.get_last_view(), "SFC")

    def test_the_close_handler_stores_and_lets_the_window_close(self):
        window = _WindowStub(self.store, "MD")
        self.assertFalse(window._on_close_remember_view())
        self.assertEqual(self.store.get_last_view(), "MD")


if __name__ == "__main__":
    unittest.main()
