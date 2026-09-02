"""The card's public favorite toggle, which three paths go through.

The star badge, the grid's ``Ctrl+D`` and the gamepad's Ⓨ all call
``RomItem.toggle_favorite``. Splitting grid.py (issue #238) left it calling
itself, so all three died with a RecursionError before touching
FAVORITES.list -- and only the context-menu entry, which reaches the action
directly, went on working (found while wiring issue #382).
"""

import unittest

from openemux.ui.rom_card import RomItem


class _CardStub:
    """Just the two methods the toggle involves; a real card needs a display."""

    toggle_favorite = RomItem.toggle_favorite

    def __init__(self):
        self.actions = []

    def _act_toggle_favorite(self, action, param):
        self.actions.append((action, param))


class ToggleFavoriteTests(unittest.TestCase):
    def test_the_public_toggle_reaches_the_action(self):
        card = _CardStub()
        card.toggle_favorite()
        self.assertEqual(card.actions, [(None, None)])

    def test_it_does_not_call_itself(self):
        # The regression, and the reason it was invisible in review: the name
        # reads right, and the context menu -- the path everyone tries first --
        # never goes through it.
        card = _CardStub()
        try:
            card.toggle_favorite()
        except RecursionError:  # pragma: no cover - the bug being guarded
            self.fail("RomItem.toggle_favorite recursed into itself")
        self.assertEqual(len(card.actions), 1)

    def test_toggling_twice_acts_twice(self):
        card = _CardStub()
        card.toggle_favorite()
        card.toggle_favorite()
        self.assertEqual(len(card.actions), 2)


if __name__ == "__main__":
    unittest.main()
