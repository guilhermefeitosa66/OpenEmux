import unittest

from opemux.core.input_actions import (
    get_actions_for_console,
    normalize_bindings,
    to_retroarch_overrides,
)


class InputActionsTests(unittest.TestCase):
    def test_console_specific_actions_for_gba_and_sfc(self):
        gba_actions = get_actions_for_console("GBA")
        sfc_actions = get_actions_for_console("SFC")
        self.assertIn("l1", gba_actions)
        self.assertIn("r1", gba_actions)
        self.assertNotIn("x", gba_actions)
        self.assertNotIn("y", gba_actions)
        self.assertIn("x", sfc_actions)
        self.assertIn("y", sfc_actions)
        self.assertIn("save_state", gba_actions)
        self.assertIn("save_state", sfc_actions)

    def test_keyboard_defaults_fill_missing_bindings(self):
        normalized = normalize_bindings({"a": "z", "b": "x"}, "keyboard", console="SFC")
        self.assertEqual(normalized["a"], "z")
        self.assertEqual(normalized["b"], "x")
        self.assertEqual(normalized["start"], "enter")
        self.assertEqual(normalized["enable_hotkey"], "right shift")

    def test_gamepad_axis_binding_generates_axis_suffix(self):
        overrides = to_retroarch_overrides({"l2": "+2", "a": "0"}, "gamepad")
        self.assertEqual(overrides["input_player1_l2_axis"], '"+2"')
        self.assertEqual(overrides["input_player1_a_btn"], '"0"')

    def test_keyboard_hotkeys_mapped(self):
        overrides = to_retroarch_overrides(
            {
                "enable_hotkey": "right shift",
                "menu_toggle": "f1",
                "save_state": "f2",
                "load_state": "f4",
                "fast_forward_toggle": "f6",
            },
            "keyboard",
            console="GBA",
        )
        self.assertEqual(overrides["input_enable_hotkey"], '"right shift"')
        self.assertEqual(overrides["input_menu_toggle"], '"f1"')
        self.assertEqual(overrides["input_save_state"], '"f2"')
        self.assertEqual(overrides["input_load_state"], '"f4"')
        self.assertEqual(overrides["input_toggle_fast_forward"], '"f6"')

    def test_overrides_exclude_buttons_not_supported_by_console(self):
        overrides = to_retroarch_overrides({"x": "s", "a": "z"}, "keyboard", console="GBA")
        self.assertIn("input_player1_a", overrides)
        self.assertNotIn("input_player1_x", overrides)


if __name__ == "__main__":
    unittest.main()
