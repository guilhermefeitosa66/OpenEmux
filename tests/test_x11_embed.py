"""The X11 layer the game window adopts RetroArch through.

Only the parts that can be answered without a real X server: the tri-state
"is the game still inside our window?" check, whose whole point is that
"unknown" and "no" mean opposite things (issue #267).
"""

import unittest

from openemux.core.x11_embed import RetroArchWindowEmbedder


class _FakeWindow:
    def __init__(self, parent_id=None, error=None):
        self._parent_id = parent_id
        self._error = error

    def query_tree(self):
        if self._error is not None:
            raise self._error
        return _FakeTree(self._parent_id)


class _FakeTree:
    def __init__(self, parent_id):
        self.parent = _FakeParent(parent_id)


class _FakeParent:
    def __init__(self, parent_id):
        self.id = parent_id


class _FakeDisplay:
    def __init__(self, window):
        self._window = window

    def create_resource_object(self, _kind, _xid):
        return self._window


class IsChildOfTests(unittest.TestCase):
    def _embedder(self, window):
        embedder = RetroArchWindowEmbedder()
        embedder._display = _FakeDisplay(window)
        # _dpy() only opens a real display when the cached one is None.
        embedder._dpy = lambda: embedder._display
        return embedder

    def test_still_ours(self):
        embedder = self._embedder(_FakeWindow(parent_id=4242))
        self.assertIs(embedder.is_child_of(0x1234, 4242), True)

    def test_reparented_away_is_a_definite_no(self):
        embedder = self._embedder(_FakeWindow(parent_id=1))
        self.assertIs(embedder.is_child_of(0x1234, 4242), False)

    def test_a_window_that_is_gone_is_unknown_not_drifted(self):
        # A BadWindow means the game's window was destroyed -- the game is
        # ending. Reading that as "it drifted" would re-parent and steal X
        # focus every second for the rest of the session.
        embedder = self._embedder(_FakeWindow(error=RuntimeError("BadWindow")))
        self.assertIsNone(embedder.is_child_of(0x1234, 4242))

    def test_no_display_is_unknown(self):
        embedder = RetroArchWindowEmbedder()
        embedder._dpy = lambda: None
        self.assertIsNone(embedder.is_child_of(0x1234, 4242))


if __name__ == "__main__":
    unittest.main()
