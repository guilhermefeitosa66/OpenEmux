"""A double-click on a card launches the game once (issue #236).

Moved here from the game window's tests when that window went away (issue
#469): this is the grid's debounce, and it never had anything to do with the
wrapper.
"""

import unittest

from openemux.ui.grid import ACTIVATION_DEBOUNCE_US, RomGrid


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
