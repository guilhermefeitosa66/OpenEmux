"""What decides whether a game plays inside an OpenEmux window (issue #199).

The answer is asked in three places that must agree -- the pre-GTK backend
pick, the launcher's RetroArch overrides, and the library window -- so the
capability rules live in one module and are tested here.
"""

import unittest
from unittest import mock

from openemux.core import game_window_support


X11_ENV = {"DISPLAY": ":0"}


class EmbeddingPossibleTests(unittest.TestCase):
    def test_x11_session_with_xlib(self):
        with mock.patch.dict("os.environ", X11_ENV, clear=True):
            with mock.patch.object(game_window_support, "XLIB_AVAILABLE", True):
                self.assertTrue(game_window_support.embedding_possible())

    def test_without_python_xlib(self):
        with mock.patch.dict("os.environ", X11_ENV, clear=True):
            with mock.patch.object(game_window_support, "XLIB_AVAILABLE", False):
                self.assertFalse(game_window_support.embedding_possible())

    def test_without_an_x_display(self):
        # A Wayland session with no XWayland, or the Flatpak sandbox on
        # Wayland: forcing GDK_BACKEND=x11 here would leave GTK with no
        # display at all, so this has to be false.
        with mock.patch.dict("os.environ", {}, clear=True):
            with mock.patch.object(game_window_support, "XLIB_AVAILABLE", True):
                self.assertFalse(game_window_support.embedding_possible())

    def test_blank_display_counts_as_none(self):
        with mock.patch.dict("os.environ", {"DISPLAY": "  "}, clear=True):
            with mock.patch.object(game_window_support, "XLIB_AVAILABLE", True):
                self.assertFalse(game_window_support.embedding_possible())

    def test_a_backend_chosen_by_hand_wins(self):
        env = dict(X11_ENV, GDK_BACKEND="wayland")
        with mock.patch.dict("os.environ", env, clear=True):
            with mock.patch.object(game_window_support, "XLIB_AVAILABLE", True):
                self.assertFalse(game_window_support.embedding_possible())

    def test_an_x11_backend_still_qualifies(self):
        for value in ("x11", "X11", "x11,wayland"):
            env = dict(X11_ENV, GDK_BACKEND=value)
            with mock.patch.dict("os.environ", env, clear=True):
                with mock.patch.object(game_window_support, "XLIB_AVAILABLE", True):
                    self.assertTrue(game_window_support.embedding_possible(), value)


class _FakeConfig:
    def __init__(self, enabled):
        self._enabled = enabled

    def get_game_window_enabled(self):
        return self._enabled


class GameWindowActiveTests(unittest.TestCase):
    def test_setting_on_and_session_able(self):
        with mock.patch.object(game_window_support, "embedding_possible", lambda: True):
            self.assertTrue(game_window_support.game_window_active(_FakeConfig(True)))

    def test_setting_off(self):
        with mock.patch.object(game_window_support, "embedding_possible", lambda: True):
            self.assertFalse(game_window_support.game_window_active(_FakeConfig(False)))

    def test_session_unable(self):
        # The setting says yes, the session cannot: the launcher must not
        # write the embed overrides, or RetroArch ends up borderless with no
        # wrapper to hold it.
        with mock.patch.object(game_window_support, "embedding_possible", lambda: False):
            self.assertFalse(game_window_support.game_window_active(_FakeConfig(True)))


if __name__ == "__main__":
    unittest.main()
