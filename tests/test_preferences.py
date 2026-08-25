"""The binding buffer behind the Controls page.

Only the pure part: which action has to let go of a token when the user points
a button at a new command (issue #281). The dialog itself needs a display; the
rule does not.
"""

import unittest

from openemux.ui.preferences import OpenEmuxPreferences


class _Buffer:
    """Just enough of the dialog for _actions_holding to be asked."""

    def __init__(self, bindings):
        self._bindings_buffer = dict(bindings)


class ActionsHoldingTests(unittest.TestCase):
    GBA = {
        "a": "0",
        "b": "1",
        "select": "6",
        "start": "7",
        "enable_hotkey": "6",
        "save_state": "2",
        "load_state": "3",
    }

    def _holding(self, action, value, bindings=None):
        return OpenEmuxPreferences._actions_holding(
            _Buffer(bindings or self.GBA), action, value
        )

    def test_a_hotkey_on_the_token_has_to_let_go(self):
        # The reported case: GBA "B" onto the Xbox X button, which the save
        # state hotkey holds.
        self.assertEqual(self._holding("b", "2"), ["save_state"])

    def test_a_gameplay_button_on_the_token_has_to_let_go(self):
        self.assertEqual(self._holding("a", "1"), ["b"])

    def test_enable_hotkey_keeps_the_button_it_shares(self):
        # It ships on Select's token on purpose: a hotkey that only fires
        # while a modifier is held is a shared button, not a conflict (#124).
        self.assertEqual(self._holding("b", "6"), ["select"])
        self.assertEqual(self._holding("enable_hotkey", "7"), [])

    def test_binding_a_button_to_what_it_already_has_releases_nothing(self):
        self.assertEqual(self._holding("b", "1"), [])

    def test_an_empty_capture_releases_nothing(self):
        self.assertEqual(self._holding("b", ""), [])

    def test_every_holder_is_released(self):
        bindings = dict(self.GBA, load_state="2", save_state="2")
        self.assertEqual(
            sorted(self._holding("b", "2", bindings)), ["load_state", "save_state"]
        )


if __name__ == "__main__":
    unittest.main()
