import unittest

from openemux.core.input_actions import (
    DEFAULT_GAMEPAD_BINDINGS,
    DEFAULT_KEYBOARD_BINDINGS,
    GLOBAL_HOTKEY_ACTIONS,
    default_bindings_for_device,
    RETROARCH_BASE_KEYS,
    get_actions_for_console,
    normalize_bindings,
    retroarch_key_for,
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

    # ----- multi-port -------------------------------------------------
    def test_base_keys_table_still_describes_player_one(self):
        self.assertEqual(RETROARCH_BASE_KEYS["a"], "input_player1_a")
        self.assertEqual(RETROARCH_BASE_KEYS["l1"], "input_player1_l")
        self.assertEqual(RETROARCH_BASE_KEYS["enable_hotkey"], "input_enable_hotkey")

    def test_retroarch_key_for_numbers_gameplay_actions(self):
        self.assertEqual(retroarch_key_for("a", 1), "input_player1_a")
        self.assertEqual(retroarch_key_for("a", 3), "input_player3_a")
        self.assertEqual(retroarch_key_for("l1", 4), "input_player4_l")
        self.assertEqual(retroarch_key_for("r2", 2), "input_player2_r2")

    def test_retroarch_key_for_leaves_hotkeys_unnumbered(self):
        for action in GLOBAL_HOTKEY_ACTIONS:
            for player in (1, 2, 3, 4):
                key = retroarch_key_for(action, player)
                self.assertEqual(key, RETROARCH_BASE_KEYS[action])
                self.assertNotIn("player", key)

    def test_overrides_default_to_player_one(self):
        overrides = to_retroarch_overrides({"a": "z"}, "keyboard", console="GBA")
        self.assertIn("input_player1_a", overrides)

    def test_overrides_for_port_two_use_player_two_keys(self):
        overrides = to_retroarch_overrides(
            {"a": "0", "l2": "+2"}, "gamepad", player=2
        )
        self.assertEqual(overrides["input_player2_a_btn"], '"0"')
        self.assertEqual(overrides["input_player2_l2_axis"], '"+2"')
        self.assertNotIn("input_player1_a_btn", overrides)

    def test_overrides_for_extra_ports_omit_global_hotkeys(self):
        for player in (2, 3, 4):
            overrides = to_retroarch_overrides({}, "gamepad", console="SFC", player=player)
            for action in GLOBAL_HOTKEY_ACTIONS:
                self.assertNotIn(RETROARCH_BASE_KEYS[action], overrides)
            self.assertIn(f"input_player{player}_a_btn", overrides)


if __name__ == "__main__":
    unittest.main()


class FullscreenToggleTests(unittest.TestCase):
    """Fullscreen is a global RetroArch hotkey, like the other F-key actions."""

    def test_emits_retroarch_fullscreen_key(self):
        bindings = default_bindings_for_device("keyboard", console="SFC")
        overrides = to_retroarch_overrides(bindings, "keyboard", console="SFC")
        # Verified against a real retroarch.cfg: the key is input_toggle_fullscreen.
        self.assertEqual(overrides["input_toggle_fullscreen"], '"f"')

    def test_gamepad_binding_uses_a_button_token(self):
        bindings = default_bindings_for_device("gamepad", console="SFC")
        overrides = to_retroarch_overrides(bindings, "gamepad", console="SFC")
        self.assertEqual(overrides["input_toggle_fullscreen_btn"], '"15"')

    def test_default_does_not_collide_with_another_binding(self):
        values = list(DEFAULT_KEYBOARD_BINDINGS.values())
        self.assertEqual(values.count("f"), 1)
        gamepad = list(DEFAULT_GAMEPAD_BINDINGS.values())
        self.assertEqual(gamepad.count("15"), 1)

    def test_stays_unnumbered_on_extra_ports(self):
        # One global hotkey set: writing it from port 2 would clobber port 1.
        bindings = default_bindings_for_device("gamepad", console="SFC")
        overrides = to_retroarch_overrides(bindings, "gamepad", console="SFC", player=2)
        self.assertNotIn("input_toggle_fullscreen_btn", overrides)

    def test_is_offered_for_every_console(self):
        for console in ("FC", "SFC", "GBA", "PS", "MD"):
            self.assertIn("fullscreen_toggle", get_actions_for_console(console), console)
