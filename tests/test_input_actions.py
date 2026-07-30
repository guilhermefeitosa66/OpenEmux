import unittest

from openemux.core.input_actions import (
    DEFAULT_GAMEPAD_BINDINGS,
    DEFAULT_KEYBOARD_BINDINGS,
    GLOBAL_HOTKEY_ACTIONS,
    conflicting_stock_hotkeys,
    default_bindings_for_device,
    RETROARCH_BASE_KEYS,
    get_actions_for_console,
    normalize_bindings,
    retroarch_key_for,
    retroarch_key_token,
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
        # No modifier on a keyboard: there are plenty of free keys and none of
        # the hotkey defaults collide with a gameplay one (issue #144).
        self.assertEqual(normalized["enable_hotkey"], "")

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
        # Translated to the token RetroArch actually resolves (issue #144).
        self.assertEqual(overrides["input_enable_hotkey"], '"rshift"')
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


class RetroArchKeyNameTests(unittest.TestCase):
    """Issue #144: GTK and RetroArch name keys differently.

    Names on the RetroArch side were taken from its own key table and from
    the tokens RetroArch writes into retroarch.cfg.
    """

    def test_the_reported_case_equals_versus_equal(self):
        # Binding "-" worked and "=" did not: GTK calls it `equal`, RetroArch
        # `equals`, and an unresolvable token simply never fires.
        self.assertEqual(retroarch_key_token("equal"), "equals")
        self.assertEqual(retroarch_key_token("minus"), "minus")

    def test_top_row_digits_are_not_bare_digits(self):
        for digit in range(10):
            self.assertEqual(retroarch_key_token(str(digit)), f"num{digit}")

    def test_keypad_digits_are_distinct_from_the_top_row(self):
        self.assertEqual(retroarch_key_token("kp_0"), "keypad0")
        self.assertEqual(retroarch_key_token("kp_9"), "keypad9")

    def test_page_keys(self):
        self.assertEqual(retroarch_key_token("page_up"), "pageup")
        self.assertEqual(retroarch_key_token("page_down"), "pagedown")

    def test_modifiers_use_retroarchs_left_bare_right_prefixed_form(self):
        self.assertEqual(retroarch_key_token("shift_l"), "shift")
        self.assertEqual(retroarch_key_token("shift_r"), "rshift")
        self.assertEqual(retroarch_key_token("control_r"), "rctrl")
        self.assertEqual(retroarch_key_token("alt_l"), "alt")

    def test_the_spellings_this_app_used_to_write_are_healed(self):
        # A profile saved before the fix must not need a reset.
        self.assertEqual(retroarch_key_token("right shift"), "rshift")
        self.assertEqual(retroarch_key_token("left ctrl"), "ctrl")

    def test_shared_names_pass_through_untouched(self):
        for name in ("a", "z", "f1", "f12", "enter", "space", "escape",
                     "up", "down", "left", "right", "comma", "minus"):
            self.assertEqual(retroarch_key_token(name), name)

    def test_translation_is_idempotent(self):
        # Applied at capture *and* when the override is written.
        for name in ("equal", "1", "page_up", "right shift", "kp_0"):
            once = retroarch_key_token(name)
            self.assertEqual(retroarch_key_token(once), once, name)

    def test_empty_stays_empty(self):
        self.assertEqual(retroarch_key_token(""), "")
        self.assertIsNone(retroarch_key_token(None))

    def test_overrides_are_written_with_the_translated_token(self):
        overrides = to_retroarch_overrides(
            {"volume_up": "equal", "volume_down": "minus", "r3": "1"},
            "keyboard",
        )
        self.assertEqual(overrides["input_volume_up"], '"equals"')
        self.assertEqual(overrides["input_volume_down"], '"minus"')
        self.assertEqual(overrides["input_player1_r3"], '"num1"')

    def test_gamepad_tokens_are_left_alone(self):
        # Pad tokens are a different namespace: "1" is button one, not a key.
        overrides = to_retroarch_overrides({"a": "1", "l2": "+2"}, "gamepad")
        self.assertEqual(overrides["input_player1_a_btn"], '"1"')
        self.assertEqual(overrides["input_player1_l2_axis"], '"+2"')


class KeyboardHotkeyModifierTests(unittest.TestCase):
    """Issue #144: no enable_hotkey on a keyboard, and no fallback letter."""

    def test_keyboard_has_no_hotkey_modifier(self):
        defaults = default_bindings_for_device("keyboard", console="SFC")
        self.assertEqual(defaults["enable_hotkey"], "")
        normalized = normalize_bindings({}, "keyboard", console="SFC")
        self.assertEqual(normalized["enable_hotkey"], "")

    def test_it_is_therefore_not_written_to_the_override(self):
        overrides = to_retroarch_overrides({}, "keyboard", console="SFC")
        self.assertNotIn("input_enable_hotkey", overrides)

    def test_the_pad_keeps_its_modifier(self):
        # A pad has ~10 buttons, so Select has to do double duty (issue #124).
        normalized = normalize_bindings({}, "gamepad", console="SFC")
        self.assertEqual(normalized["enable_hotkey"], "6")

    def test_no_hotkey_is_ever_handed_a_fallback_letter(self):
        from openemux.core.input_actions import FALLBACK_KEYS

        normalized = normalize_bindings({}, "keyboard", console="SFC")
        for action in GLOBAL_HOTKEY_ACTIONS:
            self.assertNotIn(normalized[action], FALLBACK_KEYS, action)

    def test_no_keyboard_hotkey_default_collides_with_a_gameplay_key(self):
        # What makes dropping the modifier safe: without one, a hotkey key
        # pressed during play would otherwise also move the character.
        defaults = default_bindings_for_device("keyboard", console=None)
        gameplay = {
            defaults[action]
            for action in defaults
            if action not in GLOBAL_HOTKEY_ACTIONS and defaults[action]
        }
        for action in GLOBAL_HOTKEY_ACTIONS:
            value = defaults.get(action)
            if value:
                self.assertNotIn(value, gameplay, action)


class StockHotkeyConflictTests(unittest.TestCase):
    """Issue #146: our override is appended to RetroArch's own config.

    A stock hotkey sitting on a key we bind still fires alongside ours, so
    pressing `m` would mute *and* cycle the shader.
    """

    def _keyboard_overrides(self, console="SFC"):
        # Seeded from the defaults, as a real profile is: normalize_bindings
        # deliberately never auto-fills an OPTIONAL_ACTIONS entry, so an empty
        # dict is "the user unbound everything", not "a fresh profile".
        return to_retroarch_overrides(
            default_bindings_for_device("keyboard", console=console),
            "keyboard",
            console=console,
        )

    def test_the_shipped_defaults_clear_the_hotkeys_they_take(self):
        cleared = conflicting_stock_hotkeys(self._keyboard_overrides())
        # m -> audio_mute, t -> turbo, n -> disk_next.
        self.assertEqual(cleared.get("input_shader_next"), '"nul"')
        self.assertEqual(cleared.get("input_cheat_index_minus"), '"nul"')
        self.assertEqual(cleared.get("input_shader_prev"), '"nul"')
        # Rewind is no longer cleared: we bind it ourselves now (#153), so
        # our value simply wins rather than needing the stock one removed.
        self.assertNotIn("input_rewind", cleared)

    def test_the_analog_stick_keys_clear_what_sits_on_them(self):
        # i and k are the stick on an analog console (#158), and RetroArch
        # ships frame advance on k and netplay watch on i.
        cleared = conflicting_stock_hotkeys(self._keyboard_overrides(console="PS"))
        self.assertEqual(cleared.get("input_frame_advance"), '"nul"')
        self.assertEqual(cleared.get("input_netplay_game_watch"), '"nul"')

    def test_clearing_follows_the_consoles_own_action_set(self):
        # `e` is the l2 default, and only a console with shoulder triggers
        # binds it -- so slow motion only has to go where l2 exists.
        full = conflicting_stock_hotkeys(self._keyboard_overrides(console=None))
        self.assertEqual(full.get("input_hold_slowmotion"), '"nul"')
        # SFC has no L2.
        sfc = conflicting_stock_hotkeys(self._keyboard_overrides(console="SFC"))
        self.assertNotIn("input_hold_slowmotion", sfc)

    def test_untouched_hotkeys_are_left_alone(self):
        cleared = conflicting_stock_hotkeys(self._keyboard_overrides())
        for key in ("input_cheat_toggle", "input_exit_emulator",
                    "input_grab_mouse_toggle", "input_desktop_menu_toggle"):
            self.assertNotIn(key, cleared)

    def test_a_hotkey_we_write_ourselves_is_never_cleared(self):
        # Our value already wins; clearing it would undo our own binding.
        overrides = self._keyboard_overrides()
        cleared = conflicting_stock_hotkeys(overrides)
        for key in ("input_reset", "input_audio_mute", "input_menu_toggle",
                    "input_toggle_fullscreen"):
            self.assertIn(key, overrides)
            self.assertNotIn(key, cleared)

    def test_a_gamepad_profile_clears_nothing(self):
        # "6" is a button, not a key: pad tokens are a different namespace.
        overrides = to_retroarch_overrides({}, "gamepad", console="SFC")
        self.assertEqual(conflicting_stock_hotkeys(overrides), {})

    def test_a_user_rebinding_moves_the_conflict(self):
        bindings = default_bindings_for_device("keyboard", console="SFC")
        bindings["a"] = "u"
        bindings["disk_next"] = ""
        overrides = to_retroarch_overrides(bindings, "keyboard", console="SFC")
        cleared = conflicting_stock_hotkeys(overrides)
        # `a` is now `u`, so RetroArch's cheat toggle has to go...
        self.assertEqual(cleared.get("input_cheat_toggle"), '"nul"')
        # ...and with disk_next unbound, `n` is free for shader_prev again.
        self.assertNotIn("input_shader_prev", cleared)


class KeyboardDefaultsTests(unittest.TestCase):
    """The keyboard defaults requested in issue #146."""

    def test_the_requested_keys(self):
        defaults = default_bindings_for_device("keyboard", console="SFC")
        self.assertEqual(defaults["reset_game"], "r")
        self.assertEqual(defaults["audio_mute"], "m")
        self.assertEqual(defaults["turbo"], "t")
        self.assertEqual(defaults["state_slot_increase"], "pageup")
        self.assertEqual(defaults["state_slot_decrease"], "pagedown")

    def test_they_reach_retroarch_under_the_right_keys(self):
        overrides = to_retroarch_overrides(
            default_bindings_for_device("keyboard", console="SFC"),
            "keyboard",
            console="SFC",
        )
        self.assertEqual(overrides["input_reset"], '"r"')
        self.assertEqual(overrides["input_audio_mute"], '"m"')
        self.assertEqual(overrides["input_state_slot_increase"], '"pageup"')
        self.assertEqual(overrides["input_state_slot_decrease"], '"pagedown"')
        self.assertEqual(overrides["input_player1_turbo"], '"t"')

    def test_none_of_them_collides_with_a_gameplay_key(self):
        defaults = default_bindings_for_device("keyboard", console=None)
        gameplay = {
            value
            for action, value in defaults.items()
            if action not in GLOBAL_HOTKEY_ACTIONS and action != "turbo" and value
        }
        for action in ("reset_game", "audio_mute", "turbo",
                       "state_slot_increase", "state_slot_decrease"):
            self.assertNotIn(defaults[action], gameplay, action)

    def test_the_defaults_are_unique_among_themselves(self):
        defaults = default_bindings_for_device("keyboard", console=None)
        bound = [value for value in defaults.values() if value]
        self.assertEqual(len(bound), len(set(bound)))

    def test_the_pad_is_untouched(self):
        pad = default_bindings_for_device("gamepad", console="SFC")
        for action in ("reset_game", "audio_mute", "turbo",
                       "state_slot_increase", "state_slot_decrease"):
            self.assertEqual(pad[action], "", action)


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


class KeyboardAnalogStickTests(unittest.TestCase):
    """Issue #158: the left stick, playable from the keyboard.

    A pad declares its stick as axes; a keyboard has nothing to declare --
    RetroArch takes a plain key for an analog direction. Without these an N64
    or PlayStation game that needs the stick cannot be played without a pad.
    """

    def test_the_rows_appear_only_where_a_stick_exists(self):
        for console in ("N64", "PS", "PSP", "GC", "SATURN"):
            actions = get_actions_for_console(console)
            for action in ("l_up", "l_down", "l_left", "l_right"):
                self.assertIn(action, actions, console)
        # A digital console's core has no analog input to reach.
        for console in ("FC", "SFC", "GB", "MD"):
            actions = get_actions_for_console(console)
            self.assertNotIn("l_up", actions, console)

    def test_the_ijkl_defaults(self):
        defaults = default_bindings_for_device("keyboard", console="N64")
        self.assertEqual(defaults["l_up"], "i")
        self.assertEqual(defaults["l_left"], "j")
        self.assertEqual(defaults["l_down"], "k")
        self.assertEqual(defaults["l_right"], "l")

    def test_they_reach_retroarch_as_plain_key_binds(self):
        # input_player1_l_x_minus, no suffix -- the keyboard form, alongside
        # the _axis form a pad uses.
        overrides = to_retroarch_overrides(
            default_bindings_for_device("keyboard", console="N64"),
            "keyboard",
            console="N64",
        )
        self.assertEqual(overrides["input_player1_l_y_minus"], '"i"')
        self.assertEqual(overrides["input_player1_l_x_minus"], '"j"')
        self.assertEqual(overrides["input_player1_l_y_plus"], '"k"')
        self.assertEqual(overrides["input_player1_l_x_plus"], '"l"')

    def test_up_is_y_minus(self):
        # Same sign convention the pad axes already use (-1 is up).
        from openemux.core.input_actions import PLAYER_ACTION_SUFFIXES

        self.assertEqual(PLAYER_ACTION_SUFFIXES["l_up"], "l_y_minus")
        self.assertEqual(PLAYER_ACTION_SUFFIXES["l_down"], "l_y_plus")

    def test_the_pad_keeps_declaring_axes_and_binds_no_directions(self):
        overrides = to_retroarch_overrides(
            default_bindings_for_device("gamepad", console="N64"),
            "gamepad",
            console="N64",
        )
        self.assertEqual(overrides["input_player1_l_x_minus_axis"], '"-0"')
        # The physical stick is the axes; the direction rows stay unbound.
        self.assertNotIn("input_player1_l_x_minus_btn", overrides)

    def test_the_defaults_do_not_collide_with_anything_else(self):
        defaults = default_bindings_for_device("keyboard", console="N64")
        bound = [value for value in defaults.values() if value]
        self.assertEqual(len(bound), len(set(bound)))


class ForcedAnalogDpadModeTests(unittest.TestCase):
    """Issue #152: the only modes that do anything on an analog console."""

    def test_all_five_modes_are_offered(self):
        from openemux.core.input_profiles import ANALOG_DPAD_MODES

        self.assertEqual(tuple(ANALOG_DPAD_MODES), (0, 1, 2, 3, 4))

    def test_the_forced_modes_survive_normalization(self):
        from openemux.core.input_profiles import normalize_analog_dpad_mode

        self.assertEqual(normalize_analog_dpad_mode(3, "N64"), 3)
        self.assertEqual(normalize_analog_dpad_mode("4", "PS"), 4)
        # Still nothing above the real range.
        self.assertEqual(normalize_analog_dpad_mode(5, "N64"), 0)


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


class ResetGameHotkeyTests(unittest.TestCase):
    """Issue #130: restarting is a bindable hotkey, not a header button.

    A button in the OpenEmux window needed an alt-tab away from the game to
    reach it. RetroArch's own ``input_reset`` fires while the game has focus,
    which is the only time anyone wants it.
    """

    def test_it_maps_to_retroarchs_reset_key(self):
        self.assertEqual(retroarch_key_for("reset_game"), "input_reset")
        # Global, like every other hotkey: never numbered per player.
        self.assertEqual(retroarch_key_for("reset_game", player=3), "input_reset")

    def test_it_is_offered_for_every_console(self):
        for console in ("FC", "SFC", "GBA", "PS", "MD", "N64"):
            self.assertIn("reset_game", get_actions_for_console(console), console)

    def test_it_is_never_bound_on_a_pad(self):
        # Every reachable Select combo is already taken, so a pad default
        # would fire two hotkeys at once. The keyboard gets `r` (issue #146).
        defaults = default_bindings_for_device("gamepad", console="SFC")
        self.assertEqual(defaults["reset_game"], "")
        self.assertEqual(normalize_bindings({}, "gamepad", console="SFC")["reset_game"], "")

    def test_the_keyboard_default_is_r(self):
        defaults = default_bindings_for_device("keyboard", console="SFC")
        self.assertEqual(defaults["reset_game"], "r")

    def test_an_unbound_reset_emits_no_key_at_all(self):
        overrides = to_retroarch_overrides({}, "gamepad", console="SFC")
        self.assertNotIn("input_reset", overrides)
        self.assertNotIn("input_reset_btn", overrides)

    def test_a_bound_reset_reaches_retroarch(self):
        overrides = to_retroarch_overrides(
            {"reset_game": "8"}, "gamepad", console="SFC"
        )
        self.assertEqual(overrides["input_reset_btn"], '"8"')
        keyboard = to_retroarch_overrides(
            {"reset_game": "h"}, "keyboard", console="SFC"
        )
        self.assertEqual(keyboard["input_reset"], '"h"')

    def test_it_lands_in_the_system_hotkeys_group(self):
        # GLOBAL_HOTKEY_ACTIONS is what routes a row to the System group in
        # Preferences, which is where the user was told to look for it.
        self.assertIn("reset_game", GLOBAL_HOTKEY_ACTIONS)

    def test_extra_ports_do_not_rewrite_it(self):
        for player in (2, 3, 4):
            overrides = to_retroarch_overrides(
                {"reset_game": "8"}, "gamepad", console="SFC", player=player
            )
            self.assertNotIn("input_reset_btn", overrides)


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
        self.assertEqual(defaults["audio_mute"], "m")
        # The page keys rather than RetroArch's F6/F7, which would collide
        # with fast_forward_toggle (issue #146).
        self.assertEqual(defaults["state_slot_increase"], "pageup")
        self.assertEqual(defaults["state_slot_decrease"], "pagedown")
        gamepad = default_bindings_for_device("gamepad", console="SFC")
        self.assertEqual(gamepad["volume_up"], "")
