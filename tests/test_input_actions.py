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
        # Select + L1 since #124; the old "15" was a button no pad has.
        self.assertEqual(overrides["input_toggle_fullscreen_btn"], '"4"')

    def test_default_does_not_collide_with_another_binding(self):
        values = list(DEFAULT_KEYBOARD_BINDINGS.values())
        self.assertEqual(values.count("f"), 1)
        # On a pad the hotkey shares a token with the gameplay button it rides
        # on (Select + L1), so "4" appears twice on purpose -- what must stay
        # unique is the hotkey token among the hotkeys themselves.
        hotkey_tokens = [
            DEFAULT_GAMEPAD_BINDINGS[action]
            for action in GLOBAL_HOTKEY_ACTIONS
            if action in DEFAULT_GAMEPAD_BINDINGS and action != "enable_hotkey"
        ]
        self.assertEqual(hotkey_tokens.count("4"), 1)
        self.assertEqual(len(hotkey_tokens), len(set(hotkey_tokens)))

    def test_stays_unnumbered_on_extra_ports(self):
        # One global hotkey set: writing it from port 2 would clobber port 1.
        bindings = default_bindings_for_device("gamepad", console="SFC")
        overrides = to_retroarch_overrides(bindings, "gamepad", console="SFC", player=2)
        self.assertNotIn("input_toggle_fullscreen_btn", overrides)

    def test_is_offered_for_every_console(self):
        for console in ("FC", "SFC", "GBA", "PS", "MD"):
            self.assertIn("fullscreen_toggle", get_actions_for_console(console), console)


class AnalogStickAxisTests(unittest.TestCase):
    """Issue #126: the sticks have to be declared or they do nothing."""

    def test_gamepad_overrides_declare_every_stick_axis(self):
        from openemux.core.input_actions import ANALOG_STICK_BINDINGS

        overrides = to_retroarch_overrides({"a": "0"}, "gamepad", console="SFC")
        for suffix, token in ANALOG_STICK_BINDINGS.items():
            self.assertEqual(overrides[f"input_player1_{suffix}_axis"], f'"{token}"')

    def test_axes_follow_the_port_being_written(self):
        overrides = to_retroarch_overrides({"a": "0"}, "gamepad", player=3)
        self.assertEqual(overrides["input_player3_l_x_minus_axis"], '"-0"')
        self.assertNotIn("input_player1_l_x_minus_axis", overrides)

    def test_keyboard_overrides_declare_none(self):
        overrides = to_retroarch_overrides({"a": "z"}, "keyboard", console="SFC")
        self.assertFalse([key for key in overrides if key.endswith("_x_plus_axis")])

    def test_axes_are_not_bindable_actions(self):
        # They must stay out of the action list, or Preferences would grow
        # rows for them and input capture would demand the user bind a stick.
        from openemux.core.input_actions import ACTION_ORDER, ANALOG_STICK_BINDINGS

        for console in ("FC", "SFC", "N64"):
            actions = get_actions_for_console(console)
            for suffix in ANALOG_STICK_BINDINGS:
                self.assertNotIn(suffix, actions, console)
                self.assertNotIn(suffix, ACTION_ORDER)

    def test_axes_do_not_collide_with_the_analog_triggers(self):
        # Axes 2 and 5 are the triggers (l2/r2); claiming them for a stick
        # would make a resting trigger read as a held direction.
        from openemux.core.input_actions import ANALOG_STICK_BINDINGS

        claimed = {token.lstrip("+-") for token in ANALOG_STICK_BINDINGS.values()}
        self.assertNotIn("2", claimed)
        self.assertNotIn("5", claimed)


class GamepadHotkeyReachabilityTests(unittest.TestCase):
    """Issue #124: the gamepad hotkey defaults must exist on a real pad.

    The old defaults pointed at buttons 11-15. An Xbox-style pad stops at 10,
    so ``enable_hotkey`` could never be pressed -- and RetroArch gates *every*
    hotkey behind it, which is why remapping save/load in Preferences changed
    nothing at all.
    """

    def _xbox_button_indices(self):
        from openemux.core.gamepad_reader import build_button_index_map

        try:
            from tests.test_gamepad_reader import XBOX_KEY_CODES
        except ImportError:  # `unittest discover -s tests` puts tests/ on sys.path
            from test_gamepad_reader import XBOX_KEY_CODES
        return set(build_button_index_map(XBOX_KEY_CODES).values())

    def test_every_gamepad_default_is_a_button_the_pad_exposes(self):
        available = self._xbox_button_indices()
        for action, token in DEFAULT_GAMEPAD_BINDINGS.items():
            if not token.isdigit():
                continue  # axis ("+2") and hat ("h0up") tokens live elsewhere
            self.assertIn(int(token), available, f"{action} -> {token}")

    def test_thumbstick_clicks_skip_the_guide_button(self):
        # Button 8 is BTN_MODE (Guide) on an Xbox pad; L3/R3 are 9 and 10.
        self.assertEqual(DEFAULT_GAMEPAD_BINDINGS["l3"], "9")
        self.assertEqual(DEFAULT_GAMEPAD_BINDINGS["r3"], "10")

    def test_enable_hotkey_is_emitted_and_shares_the_select_token(self):
        bindings = default_bindings_for_device("gamepad", console="SFC")
        overrides = to_retroarch_overrides(bindings, "gamepad", console="SFC")
        # The overlap with `select` is the point of a modifier, and it has to
        # survive normalization's dedup rather than being dropped by it.
        self.assertEqual(overrides["input_enable_hotkey_btn"], '"6"')
        self.assertEqual(overrides["input_player1_select_btn"], '"6"')

    def test_every_hotkey_survives_normalization(self):
        normalized = normalize_bindings({}, "gamepad", console="SFC")
        for action in ("enable_hotkey", "menu_toggle", "save_state",
                       "load_state", "fast_forward_toggle", "fullscreen_toggle"):
            self.assertEqual(normalized[action], DEFAULT_GAMEPAD_BINDINGS[action], action)

    def test_gamepad_profiles_never_get_a_keyboard_fallback_letter(self):
        from openemux.core.input_actions import FALLBACK_KEYS

        for console in ("FC", "SFC", "GBA", "PS", "MD", "N64"):
            normalized = normalize_bindings({}, "gamepad", console=console)
            for action, value in normalized.items():
                self.assertNotIn(value, FALLBACK_KEYS, f"{console}/{action}")

    def test_a_partial_profile_still_gets_reachable_hotkeys(self):
        # The user rebound a face button; the hotkeys must still fill in.
        normalized = normalize_bindings({"a": "1", "b": "0"}, "gamepad", console="SFC")
        self.assertEqual(normalized["a"], "1")
        self.assertEqual(normalized["enable_hotkey"], "6")
        self.assertEqual(normalized["save_state"], "2")


class VolumeAndSlotHotkeyTests(unittest.TestCase):
    """Volume and save-slot hotkeys (issues #69/#73 redo): bindable, optional."""

    def test_actions_map_to_retroarch_hotkey_keys(self):
        from openemux.core.input_actions import retroarch_key_for

        expected = {
            "volume_up": "input_volume_up",
            "volume_down": "input_volume_down",
            "audio_mute": "input_audio_mute",
            "state_slot_increase": "input_state_slot_increase",
            "state_slot_decrease": "input_state_slot_decrease",
        }
        for action, key in expected.items():
            # Global hotkeys: never numbered per player.
            self.assertEqual(retroarch_key_for(action, player=1), key)
            self.assertEqual(retroarch_key_for(action, player=3), key)

    def test_offered_for_every_console(self):
        for console in ("FC", "SFC", "GBA", "PS", "MD"):
            actions = get_actions_for_console(console)
            for action in ("volume_up", "volume_down", "audio_mute",
                           "state_slot_increase", "state_slot_decrease"):
                self.assertIn(action, actions, console)

    def test_never_auto_filled_on_existing_profiles(self):
        # A profile that predates these actions must not have fallback letters
        # grabbed for them: they stay unbound until the user binds them.
        from openemux.core.input_actions import normalize_bindings

        bindings = normalize_bindings({"a": "z"}, "keyboard", console="SFC")
        for action in ("volume_up", "volume_down", "audio_mute",
                       "state_slot_increase", "state_slot_decrease"):
            self.assertEqual(bindings[action], "", action)

    def test_fresh_profiles_get_retroarch_volume_defaults(self):
        from openemux.core.input_actions import default_bindings_for_device

        defaults = default_bindings_for_device("keyboard", console="SFC")
        self.assertEqual(defaults["volume_up"], "kp_plus")
        self.assertEqual(defaults["volume_down"], "kp_minus")
        self.assertEqual(defaults["audio_mute"], "f9")
        # The slot pair has no default anywhere (F6/F7 would collide).
        self.assertEqual(defaults["state_slot_increase"], "")
        self.assertEqual(defaults["state_slot_decrease"], "")
        gamepad = default_bindings_for_device("gamepad", console="SFC")
        self.assertEqual(gamepad["volume_up"], "")
