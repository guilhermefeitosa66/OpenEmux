"""Which actions the held inputs light on the controller drawing (issue 816)."""

import unittest

from openemux.core.input_actions import default_bindings_for_device
from openemux.core.input_held import HeldKeys, key_token, lit_actions


class LitActionsTests(unittest.TestCase):
    def test_a_held_key_lights_the_action_bound_to_it(self):
        bindings = {"a": "z", "b": "x", "start": "enter"}
        self.assertEqual(lit_actions(bindings, {"z"}), {"a"})
        self.assertEqual(lit_actions(bindings, {"z", "enter"}), {"a", "start"})

    def test_an_input_bound_to_nothing_lights_nothing(self):
        bindings = {"a": "z", "b": ""}
        self.assertEqual(lit_actions(bindings, {"q"}), set())
        self.assertEqual(lit_actions(bindings, set()), set())
        # An unbound action is not "bound to the empty token".
        self.assertEqual(lit_actions(bindings, {""}), set())

    def test_one_input_on_two_actions_lights_both(self):
        # The D-pad folded onto the stick, or a button the user doubled up.
        self.assertEqual(lit_actions({"up": "h0up", "l_up": "h0up"}, {"h0up"}), {"up", "l_up"})

    def test_on_a_pad_a_hotkey_lights_only_with_its_modifier(self):
        bindings = default_bindings_for_device("gamepad", console="SFC")
        # Start is button 7, and Select + Start opens the menu.
        self.assertEqual(lit_actions(bindings, {"7"}), {"start"})
        self.assertEqual(
            lit_actions(bindings, {"6", "7"}), {"select", "enable_hotkey", "start", "menu_toggle"}
        )

    def test_the_modifier_itself_lights_alone(self):
        bindings = default_bindings_for_device("gamepad", console="SFC")
        self.assertEqual(lit_actions(bindings, {"6"}), {"select", "enable_hotkey"})

    def test_on_a_keyboard_with_no_modifier_a_hotkey_lights_on_its_own_key(self):
        bindings = default_bindings_for_device("keyboard", console="SFC")
        self.assertEqual(bindings["enable_hotkey"], "")
        self.assertEqual(lit_actions(bindings, {"f1"}), {"menu_toggle"})


class HeldKeysTests(unittest.TestCase):
    def test_a_press_and_its_release(self):
        keys = HeldKeys()
        self.assertTrue(keys.press(38, "a"))
        self.assertEqual(keys.tokens, frozenset({"a"}))
        self.assertTrue(keys.release(38))
        self.assertEqual(keys.tokens, frozenset())

    def test_a_repeat_and_an_unknown_release_change_nothing(self):
        keys = HeldKeys()
        keys.press(38, "a")
        self.assertFalse(keys.press(38, "a"))  # the key's autorepeat
        self.assertFalse(keys.release(99))
        self.assertEqual(keys.tokens, frozenset({"a"}))

    def test_a_key_is_released_by_its_keycode_whatever_it_is_called_by_then(self):
        # 1 goes down, Shift goes down, 1 comes up as "exclam".
        keys = HeldKeys()
        keys.press(10, "1")
        keys.press(50, "Shift_L")
        self.assertEqual(keys.tokens, frozenset({"num1", "shift"}))
        keys.release(10)
        self.assertEqual(keys.tokens, frozenset({"shift"}))

    def test_names_are_spelled_as_bindings_spell_them(self):
        self.assertEqual(key_token("Return"), "enter")
        self.assertEqual(key_token("A"), "a")
        self.assertEqual(key_token("KP_Add"), "kp_plus")
        self.assertEqual(key_token(None), "")

    def test_a_key_with_no_name_is_not_held(self):
        keys = HeldKeys()
        self.assertFalse(keys.press(7, None))
        self.assertEqual(keys.tokens, frozenset())

    def test_clearing_forgets_everything_and_says_whether_anything_was_held(self):
        keys = HeldKeys()
        self.assertFalse(keys.clear())
        keys.press(38, "a")
        self.assertTrue(keys.clear())
        self.assertEqual(keys.tokens, frozenset())


if __name__ == "__main__":
    unittest.main()
