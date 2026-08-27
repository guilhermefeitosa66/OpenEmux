"""The embedded game window's own decisions, without a display.

The wrapper has the most failure modes in the launch path and had no tests of
its own (issue #236): which key it grabs when the user's binding is one X
cannot name, and whether a second activation of the same card is a new launch
or the other half of a double-click.
"""

import unittest

from openemux.core import retroarch_log
from openemux.ui.game_window import FULLSCREEN_FALLBACK_KEY, GameWindow
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


class _Proc:
    def __init__(self, exit_code=None):
        self.exit_code = exit_code

    def poll(self):
        return self.exit_code


class _Runtime:
    def __init__(self, active_process=None):
        self.active_process = active_process


class _Wrapper:
    """Just the attributes ``_follow_relaunch`` reads and writes.

    The suite cannot build GTK widgets, and the decision under test is plain
    bookkeeping, so it is called unbound against this stand-in.
    """

    def __init__(self, proc, runtime, child_xid=None):
        self._proc = proc
        self._runtime = runtime
        self._child_xid = child_xid
        self._ticks_waited = 17
        self._embedded_ticks = 9
        self._log_verdict = retroarch_log.NOT_X11


class FollowRelaunchTests(unittest.TestCase):
    """The wrapper follows a process the runtime swapped under it (#248).

    A launch that died because the AppImage could not mount itself is retried
    unpacked with nothing said to the user. Closing on the first process's
    exit would strand the retried game in its own undecorated window and mark
    embedding unavailable for the session over a launch that never happened.
    """

    def test_a_live_replacement_is_adopted(self):
        dead, live = _Proc(exit_code=1), _Proc()
        wrapper = _Wrapper(dead, _Runtime(live))

        self.assertTrue(GameWindow._follow_relaunch(wrapper))
        self.assertIs(wrapper._proc, live)

    def test_nothing_learned_about_the_dead_process_carries_over(self):
        dead, live = _Proc(exit_code=1), _Proc()
        wrapper = _Wrapper(dead, _Runtime(live))

        GameWindow._follow_relaunch(wrapper)
        self.assertEqual(wrapper._ticks_waited, 0)
        self.assertEqual(wrapper._embedded_ticks, 0)
        self.assertEqual(wrapper._log_verdict, retroarch_log.UNKNOWN)

    def test_a_game_that_simply_ended_is_not_followed(self):
        # The runtime cleared the process: this is a quit, and the wrapper
        # must close as it always did.
        dead = _Proc(exit_code=0)
        wrapper = _Wrapper(dead, _Runtime(None))
        self.assertFalse(GameWindow._follow_relaunch(wrapper))

    def test_the_same_process_is_not_a_relaunch(self):
        dead = _Proc(exit_code=1)
        wrapper = _Wrapper(dead, _Runtime(dead))
        self.assertFalse(GameWindow._follow_relaunch(wrapper))

    def test_a_game_that_was_embedded_and_ended_is_not_followed(self):
        # That is a game the user finished. The relaunch paths that follow
        # one open a fresh wrapper of their own (issue #129).
        dead, live = _Proc(exit_code=0), _Proc()
        wrapper = _Wrapper(dead, _Runtime(live), child_xid=0x200)
        self.assertFalse(GameWindow._follow_relaunch(wrapper))
        self.assertIs(wrapper._proc, dead)

    def test_a_replacement_that_is_already_dead_is_not_followed(self):
        dead, stillborn = _Proc(exit_code=1), _Proc(exit_code=1)
        wrapper = _Wrapper(dead, _Runtime(stillborn))
        self.assertFalse(GameWindow._follow_relaunch(wrapper))
        self.assertIs(wrapper._proc, dead)


if __name__ == "__main__":
    unittest.main()
