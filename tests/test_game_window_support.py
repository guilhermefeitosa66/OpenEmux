"""What decides whether a game plays inside an OpenEmux window (issue #199).

The answer is asked in three places that must agree -- the pre-GTK backend
pick, the launcher's RetroArch overrides, and the library window -- so the
capability rules live in one module and are tested here.
"""

import unittest
from unittest import mock

from openemux.core import game_window_support


X11_ENV = {"DISPLAY": ":0"}


class _ResetsEmbedState(unittest.TestCase):
    """The display verdict and the failure latch are process-global.

    Without this, a latch set by one test silently flips every later one --
    including, because discovery runs this file first, the launcher tests
    that assert the embed overrides are written.
    """

    def setUp(self):
        game_window_support.reset_embed_state()
        self.addCleanup(game_window_support.reset_embed_state)


class EmbeddingPossibleTests(_ResetsEmbedState):
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

    def test_only_the_first_backend_in_the_list_counts(self):
        # GTK walks the list in order and takes the first that opens, so
        # "wayland,x11" puts GTK on Wayland -- where nothing can be
        # reparented. This used to pass the check and the launcher went on to
        # strip RetroArch's decorations for a wrapper that could never
        # exist (issue #212).
        env = dict(X11_ENV, GDK_BACKEND="wayland,x11")
        with mock.patch.dict("os.environ", env, clear=True):
            with mock.patch.object(game_window_support, "XLIB_AVAILABLE", True):
                self.assertFalse(game_window_support.embedding_possible())


class EmbeddingReadyTests(_ResetsEmbedState):
    """The launch-time question, which knows things the environment cannot."""

    def test_ready_when_nothing_has_gone_wrong(self):
        with mock.patch.object(game_window_support, "embedding_possible", lambda: True):
            self.assertTrue(game_window_support.embedding_ready())

    def test_gtks_verdict_about_the_display_overrules_the_environment(self):
        # The env looked X11-capable but the app opened a Wayland display.
        with mock.patch.object(game_window_support, "embedding_possible", lambda: True):
            game_window_support.set_display_embeddable(False)
            self.assertFalse(game_window_support.embedding_ready())

    def test_a_failed_embed_latches_for_the_session(self):
        with mock.patch.object(game_window_support, "embedding_possible", lambda: True):
            game_window_support.mark_embed_unavailable("RetroArch is not an X11 client")
            self.assertFalse(game_window_support.embedding_ready())
            self.assertEqual(
                game_window_support.embed_unavailable_reason(),
                "RetroArch is not an X11 client",
            )

    def test_the_first_reason_wins(self):
        game_window_support.mark_embed_unavailable("first")
        game_window_support.mark_embed_unavailable("second")
        self.assertEqual(game_window_support.embed_unavailable_reason(), "first")

    def test_neither_answer_touches_the_capability_predicate(self):
        # The whole reason there are two predicates: Preferences asks
        # embedding_possible(), and its switch has to stay usable so the
        # setting can be turned on for the next restart.
        env = dict(X11_ENV)
        with mock.patch.dict("os.environ", env, clear=True):
            with mock.patch.object(game_window_support, "XLIB_AVAILABLE", True):
                game_window_support.set_display_embeddable(False)
                game_window_support.mark_embed_unavailable("no X11 window")
                self.assertTrue(game_window_support.embedding_possible())
                self.assertFalse(game_window_support.embedding_ready())


class _FakeConfig:
    def __init__(self, enabled):
        self._enabled = enabled

    def get_game_window_enabled(self):
        return self._enabled


class GameWindowActiveTests(_ResetsEmbedState):
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

    def test_a_latched_failure_sends_later_launches_standalone(self):
        # After one failed embed the rest of the session runs standalone --
        # which is what makes the launcher write RetroArch's own decorations
        # back, instead of stranding another borderless window (issue #267).
        with mock.patch.object(game_window_support, "embedding_possible", lambda: True):
            game_window_support.mark_embed_unavailable("reparenting failed")
            self.assertFalse(game_window_support.game_window_active(_FakeConfig(True)))


if __name__ == "__main__":
    unittest.main()
