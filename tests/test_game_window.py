"""The embedded game window's own decisions, without a display.

The wrapper has the most failure modes in the launch path and had no tests of
its own (issue #236): which key it grabs when the user's binding is one X
cannot name, and whether a second activation of the same card is a new launch
or the other half of a double-click.
"""

import unittest

from openemux.ui.game_window import FULLSCREEN_FALLBACK_KEY
from openemux.ui.grid import ACTIVATION_DEBOUNCE_US, RomGrid


class _Embedder:
    """Records the grab and answers with a keycode only for keys X knows."""

    def __init__(self, resolvable=("f", "f11")):
        self.resolvable = set(resolvable)
        self.calls = []

    def grab_key(self, toplevel_xid, key_name, fallback_key_name=None):
        self.calls.append((key_name, fallback_key_name))
        if key_name in self.resolvable:
            return 42
        if fallback_key_name and fallback_key_name in self.resolvable:
            return 43
        return None


class FullscreenBindingTests(unittest.TestCase):
    """RetroArch's own toggle is unbound while embedded, so this grab is the
    only fullscreen key there is (issue #236)."""

    def test_the_binding_the_user_chose_is_grabbed(self):
        embedder = _Embedder()
        keycode = embedder.grab_key(0x100, "f", FULLSCREEN_FALLBACK_KEY)
        self.assertEqual(keycode, 42)
        self.assertEqual(embedder.calls, [("f", FULLSCREEN_FALLBACK_KEY)])

    def test_a_binding_x_cannot_name_falls_back_instead_of_giving_up(self):
        # "enter", "num1", "pageup", "kp_plus", "del", "rshift"... all
        # legitimate stored values that resolved to nothing.
        embedder = _Embedder()
        self.assertEqual(embedder.grab_key(0x100, "enter", FULLSCREEN_FALLBACK_KEY), 43)

    def test_the_fallback_is_the_default_binding(self):
        self.assertEqual(FULLSCREEN_FALLBACK_KEY, "f")

    def test_the_window_defaults_to_the_fallback_when_nothing_is_bound(self):
        # What __init__ does with a profile that has no fullscreen_toggle.
        bindings = {}
        chosen = bindings.get("fullscreen_toggle") or FULLSCREEN_FALLBACK_KEY
        self.assertEqual(chosen, FULLSCREEN_FALLBACK_KEY)

    def test_the_embedder_takes_a_fallback(self):
        # The contract the wrapper relies on at both grab sites: the initial
        # adoption and the re-adoption after the game window drifts out.
        import inspect

        from openemux.core.x11_embed import RetroArchWindowEmbedder

        parameters = inspect.signature(RetroArchWindowEmbedder.grab_key).parameters
        self.assertIn("fallback_key_name", parameters)
        self.assertIsNone(parameters["fallback_key_name"].default)


class _GridStub:
    _last_activation = (None, 0)
    _is_repeat_activation = RomGrid._is_repeat_activation


class DoubleClickTests(unittest.TestCase):
    """A double-click emits child-activated twice; the second launch is
    refused with an error toast, so it must never be attempted (#236)."""

    def _grid(self, last_path, last_at):
        grid = _GridStub()
        grid._last_activation = (last_path, last_at)
        return grid

    def test_the_second_half_of_a_double_click_is_swallowed(self):
        grid = self._grid("/roms/FC/Contra.nes", 1_000_000)
        self.assertTrue(
            grid._is_repeat_activation("/roms/FC/Contra.nes", 1_000_000 + 120_000)
        )

    def test_a_deliberate_relaunch_later_is_not(self):
        grid = self._grid("/roms/FC/Contra.nes", 1_000_000)
        self.assertFalse(
            grid._is_repeat_activation(
                "/roms/FC/Contra.nes", 1_000_000 + ACTIVATION_DEBOUNCE_US + 1
            )
        )

    def test_a_different_game_is_never_swallowed(self):
        grid = self._grid("/roms/FC/Contra.nes", 1_000_000)
        self.assertFalse(grid._is_repeat_activation("/roms/FC/Mario.nes", 1_000_100))

    def test_the_first_activation_of_a_session_goes_through(self):
        grid = self._grid(None, 0)
        self.assertFalse(grid._is_repeat_activation("/roms/FC/Contra.nes", 1_000_000))

    def test_the_window_is_half_a_second(self):
        self.assertEqual(ACTIVATION_DEBOUNCE_US, 500_000)


if __name__ == "__main__":
    unittest.main()
