import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from openemux.core.input_profiles import (
    ANALOG_DPAD_LEFT_STICK,
    ANALOG_DPAD_OFF,
    ANALOG_DPAD_RIGHT_STICK,
    DEVICE_IDS,
    EXTRA_PORT_DEVICE_IDS,
    PROFILE_VERSION,
    InputProfileManager,
    clear_unreachable_gamepad_buttons,
    controller_types_for,
    normalize_controller_type,
    default_analog_dpad_mode,
    normalize_analog_dpad_mode,
    normalize_turbo_settings,
    player_for_device,
)


class InputProfilesTests(unittest.TestCase):
    def test_load_profile_creates_default_when_missing(self):
        with TemporaryDirectory() as tmp_dir:
            manager = InputProfileManager(tmp_dir)
            profile = manager.load_profile("FC")

        self.assertEqual(profile["console"], "FC")
        self.assertIn("keyboard", profile["devices"])
        self.assertIn("gamepad_p1", profile["devices"])

    def test_save_profile_normalizes_and_persists(self):
        with TemporaryDirectory() as tmp_dir:
            manager = InputProfileManager(tmp_dir)
            saved = manager.save_profile(
                "snes",
                {
                    "active_device": "keyboard",
                    "devices": {
                        "keyboard": {
                            "type": "keyboard",
                            "bindings": {"a": "Z", "start": "ENTER"},
                        }
                    },
                },
            )
            loaded = manager.load_profile("SFC")

        self.assertEqual(saved["console"], "SFC")
        self.assertEqual(loaded["devices"]["keyboard"]["bindings"]["a"], "z")
        self.assertEqual(loaded["devices"]["keyboard"]["bindings"]["start"], "enter")

    def test_profile_actions_are_console_specific(self):
        with TemporaryDirectory() as tmp_dir:
            manager = InputProfileManager(tmp_dir)
            gba = manager.load_profile("GBA")
            sfc = manager.load_profile("SFC")

        gba_keys = set(gba["devices"]["keyboard"]["bindings"].keys())
        sfc_keys = set(sfc["devices"]["keyboard"]["bindings"].keys())
        self.assertNotIn("x", gba_keys)
        self.assertNotIn("y", gba_keys)
        self.assertIn("x", sfc_keys)
        self.assertIn("y", sfc_keys)

    # ----- multi-port -------------------------------------------------
    def test_default_profile_has_all_four_ports(self):
        with TemporaryDirectory() as tmp_dir:
            profile = InputProfileManager(tmp_dir).load_profile("SFC")

        self.assertEqual(sorted(profile["devices"]), sorted(DEVICE_IDS))
        self.assertTrue(profile["devices"]["keyboard"]["enabled"])
        self.assertTrue(profile["devices"]["gamepad_p1"]["enabled"])
        for device_id in EXTRA_PORT_DEVICE_IDS:
            self.assertFalse(profile["devices"][device_id]["enabled"])
            self.assertEqual(profile["devices"][device_id]["type"], "gamepad")

    def test_player_for_device(self):
        self.assertEqual(player_for_device("keyboard"), 1)
        self.assertEqual(player_for_device("gamepad_p1"), 1)
        self.assertEqual(player_for_device("gamepad_p2"), 2)
        self.assertEqual(player_for_device("gamepad_p4"), 4)
        self.assertEqual(player_for_device("nonsense"), 1)

    def test_legacy_v1_profile_still_loads(self):
        legacy = {
            "version": 1,
            "console": "SFC",
            "active_device": "gamepad_p1",
            "devices": {
                "keyboard": {"type": "keyboard", "bindings": {"a": "z"}},
                "gamepad_p1": {"type": "gamepad", "bindings": {"a": "4"}},
            },
        }
        with TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "SFC.config"
            path.write_text(json.dumps(legacy), encoding="utf-8")
            profile = InputProfileManager(tmp_dir).load_profile("SFC")

        # Existing choices survive the migration...
        self.assertEqual(profile["active_device"], "gamepad_p1")
        self.assertEqual(profile["devices"]["keyboard"]["bindings"]["a"], "z")
        self.assertEqual(profile["devices"]["gamepad_p1"]["bindings"]["a"], "4")
        # ...and the new ports appear, disabled by default.
        for device_id in EXTRA_PORT_DEVICE_IDS:
            self.assertIn(device_id, profile["devices"])
            self.assertFalse(profile["devices"][device_id]["enabled"])

    def test_extra_ports_round_trip_through_save_and_load(self):
        with TemporaryDirectory() as tmp_dir:
            manager = InputProfileManager(tmp_dir)
            profile = manager.load_profile("SFC")
            for index, device_id in enumerate(EXTRA_PORT_DEVICE_IDS, start=2):
                profile["devices"][device_id]["enabled"] = True
                profile["devices"][device_id]["bindings"]["a"] = str(index)
            manager.save_profile("SFC", profile)
            reloaded = manager.load_profile("SFC")

        for index, device_id in enumerate(EXTRA_PORT_DEVICE_IDS, start=2):
            self.assertTrue(reloaded["devices"][device_id]["enabled"])
            self.assertEqual(reloaded["devices"][device_id]["bindings"]["a"], str(index))

    def test_active_device_cannot_be_an_extra_port(self):
        with TemporaryDirectory() as tmp_dir:
            manager = InputProfileManager(tmp_dir)
            saved = manager.save_profile("SFC", {"active_device": "gamepad_p3", "devices": {}})

        self.assertEqual(saved["active_device"], "keyboard")


class TurboSettingsTests(unittest.TestCase):
    """Turbo timing (issue #72): normalized, clamped, per console."""

    def test_defaults(self):
        self.assertEqual(
            normalize_turbo_settings(None),
            {"period": 6, "duty_cycle": 3, "mode": 0},
        )

    def test_clamping_and_garbage(self):
        settings = normalize_turbo_settings(
            {"period": 999, "duty_cycle": -4, "mode": "x"}
        )
        self.assertEqual(settings["period"], 120)
        self.assertEqual(settings["duty_cycle"], 1)
        self.assertEqual(settings["mode"], 0)

    def test_duty_cycle_never_reaches_the_period(self):
        settings = normalize_turbo_settings({"period": 4, "duty_cycle": 10})
        self.assertEqual(settings["duty_cycle"], 3)

    def test_round_trip_through_the_profile(self):
        with TemporaryDirectory() as tmp_dir:
            manager = InputProfileManager(tmp_dir)
            manager.set_turbo_settings("FC", {"period": 10, "duty_cycle": 5, "mode": 1})
            again = InputProfileManager(tmp_dir)
            self.assertEqual(
                again.get_turbo_settings("FC"),
                {"period": 10, "duty_cycle": 5, "mode": 1},
            )


class TurboBindingTests(unittest.TestCase):
    """The turbo modifier is an optional binding: never auto-filled."""

    def test_turbo_stays_unbound_on_every_pad(self):
        # Issue #72: an accidental turbo modifier on a pad would corrupt
        # normal play, and there is no spare button for it. The keyboard has
        # a dedicated key since issue #146.
        with TemporaryDirectory() as tmp_dir:
            manager = InputProfileManager(tmp_dir)
            profile = manager.load_profile("FC")
        for device_id, device in profile["devices"].items():
            if device["type"] == "keyboard":
                self.assertEqual(device["bindings"].get("turbo"), "t")
                continue
            self.assertEqual(device["bindings"].get("turbo", ""), "", device_id)

    def test_a_bound_turbo_survives_normalization(self):
        with TemporaryDirectory() as tmp_dir:
            manager = InputProfileManager(tmp_dir)
            profile = manager.load_profile("FC")
            profile["devices"]["gamepad_p1"]["bindings"]["turbo"] = "9"
            saved = manager.save_profile("FC", profile)
        self.assertEqual(saved["devices"]["gamepad_p1"]["bindings"]["turbo"], "9")


class AnalogDpadModeTests(unittest.TestCase):
    """The stick folded onto the D-pad (issue #71), per console."""

    def test_digital_consoles_default_to_the_left_stick(self):
        for console in ("FC", "SFC", "GB", "MD"):
            self.assertEqual(default_analog_dpad_mode(console), ANALOG_DPAD_LEFT_STICK)

    def test_analog_native_consoles_default_off(self):
        # Folding the stick onto the D-pad would steal it from the game.
        for console in ("N64", "PS", "PSP", "GC", "SATURN"):
            self.assertEqual(default_analog_dpad_mode(console), ANALOG_DPAD_OFF)

    def test_normalization_rejects_garbage(self):
        self.assertEqual(normalize_analog_dpad_mode(2, "SFC"), ANALOG_DPAD_RIGHT_STICK)
        self.assertEqual(normalize_analog_dpad_mode("1", "SFC"), ANALOG_DPAD_LEFT_STICK)
        self.assertEqual(normalize_analog_dpad_mode(9, "SFC"), ANALOG_DPAD_LEFT_STICK)
        self.assertEqual(normalize_analog_dpad_mode("x", "N64"), ANALOG_DPAD_OFF)

    def test_mode_round_trips_through_the_profile(self):
        with TemporaryDirectory() as tmp_dir:
            manager = InputProfileManager(tmp_dir)
            self.assertEqual(manager.get_analog_dpad_mode("SFC"), ANALOG_DPAD_LEFT_STICK)
            manager.set_analog_dpad_mode("SFC", ANALOG_DPAD_OFF)
            self.assertEqual(manager.get_analog_dpad_mode("SFC"), ANALOG_DPAD_OFF)
            # And survives a fresh manager (i.e. it is in the file).
            again = InputProfileManager(tmp_dir)
            self.assertEqual(again.get_analog_dpad_mode("SFC"), ANALOG_DPAD_OFF)

    def test_legacy_profile_without_the_key_gets_the_console_default(self):
        with TemporaryDirectory() as tmp_dir:
            manager = InputProfileManager(tmp_dir)
            path = Path(tmp_dir) / "SFC.config"
            path.write_text(json.dumps({"console": "SFC", "devices": {}}), encoding="utf-8")
            self.assertEqual(manager.get_analog_dpad_mode("SFC"), ANALOG_DPAD_LEFT_STICK)


class ProfileSettingsSurviveBindingSavesTests(unittest.TestCase):
    """Issue #126: the settings written by their own rows must not be lost.

    ``analog_dpad_mode`` and ``turbo`` are persisted the moment their row
    changes, while bindings are persisted by the Save button. Saving from a
    snapshot taken before the row changed silently reverted it -- change the
    stick row, press Save, lose the choice. Preferences now re-reads first,
    which is the flow these exercise.
    """

    def test_analog_mode_survives_a_later_binding_save(self):
        with TemporaryDirectory() as tmp_dir:
            manager = InputProfileManager(tmp_dir)
            manager.set_analog_dpad_mode("SFC", ANALOG_DPAD_RIGHT_STICK)

            profile = manager.load_profile("SFC")
            profile["devices"]["gamepad_p1"]["bindings"]["a"] = "1"
            manager.save_profile("SFC", profile)

            reloaded = InputProfileManager(tmp_dir)
            self.assertEqual(
                reloaded.get_analog_dpad_mode("SFC"), ANALOG_DPAD_RIGHT_STICK
            )
            self.assertEqual(
                reloaded.load_profile("SFC")["devices"]["gamepad_p1"]["bindings"]["a"],
                "1",
            )

    def test_turbo_settings_survive_a_later_binding_save(self):
        with TemporaryDirectory() as tmp_dir:
            manager = InputProfileManager(tmp_dir)
            manager.set_turbo_settings("SFC", {"period": 10, "duty_cycle": 4, "mode": 1})

            profile = manager.load_profile("SFC")
            profile["devices"]["gamepad_p1"]["bindings"]["b"] = "0"
            manager.save_profile("SFC", profile)

            self.assertEqual(
                InputProfileManager(tmp_dir).get_turbo_settings("SFC"),
                {"period": 10, "duty_cycle": 4, "mode": 1},
            )


class ControllerTypeTests(unittest.TestCase):
    """Issue #151: what the core is told is plugged into the port.

    The ids come from loading each core and reading the controller info it
    publishes, so they are the core's own, not derived from libretro's
    subclass formula.
    """

    def test_only_consoles_with_a_real_choice_offer_one(self):
        self.assertTrue(controller_types_for("PS"))
        self.assertTrue(controller_types_for("MD"))
        # mupen64plus_next publishes exactly one type, so there is nothing
        # to pick -- which is why this is not the Super Mario 64 fix.
        self.assertEqual(controller_types_for("N64"), ())
        self.assertEqual(controller_types_for("GB"), ())

    def test_playstation_offers_dualshock(self):
        ids = dict(controller_types_for("PS"))
        self.assertEqual(ids[517], "DualShock")
        self.assertEqual(ids[1], "Standard")

    def test_mega_drive_offers_the_six_button_pad(self):
        ids = dict(controller_types_for("MD"))
        self.assertEqual(ids[513], "MD Joypad 6 Button")

    def test_unset_means_the_cores_own_default(self):
        self.assertIsNone(normalize_controller_type(None, "PS"))
        self.assertIsNone(normalize_controller_type("", "PS"))

    def test_an_id_the_console_does_not_offer_is_refused(self):
        self.assertIsNone(normalize_controller_type(513, "PS"))
        self.assertIsNone(normalize_controller_type(517, "N64"))
        self.assertIsNone(normalize_controller_type("nonsense", "PS"))

    def test_a_valid_id_survives_as_an_int(self):
        self.assertEqual(normalize_controller_type("517", "PS"), 517)
        self.assertEqual(normalize_controller_type(517, "PS"), 517)

    def test_it_round_trips_through_the_profile(self):
        with TemporaryDirectory() as tmp_dir:
            manager = InputProfileManager(tmp_dir)
            self.assertIsNone(manager.get_controller_type("PS"))
            manager.set_controller_type("PS", 517)
            self.assertEqual(InputProfileManager(tmp_dir).get_controller_type("PS"), 517)

    def test_a_console_without_choices_never_stores_one(self):
        with TemporaryDirectory() as tmp_dir:
            manager = InputProfileManager(tmp_dir)
            manager.set_controller_type("N64", 517)
            self.assertIsNone(manager.get_controller_type("N64"))


class V4KeyboardDefaultsMigrationTests(unittest.TestCase):
    """Issue #146: the new keyboard defaults have to reach existing profiles.

    All five actions are in OPTIONAL_ACTIONS, which normalize_bindings skips
    by design, and first_boot already wrote a .config for every console -- so
    a new default alone reaches nobody who has already run the app.
    """

    def _v3_profile(self, keyboard_bindings):
        return {
            "version": 3,
            "console": "SFC",
            "active_device": "keyboard",
            "devices": {
                "keyboard": {
                    "type": "keyboard",
                    "enabled": True,
                    "bindings": keyboard_bindings,
                }
            },
        }

    def _load(self, tmp_dir, profile):
        path = Path(tmp_dir) / "SFC.config"
        path.write_text(json.dumps(profile), encoding="utf-8")
        return InputProfileManager(tmp_dir).load_profile("SFC"), path

    def test_unbound_actions_are_filled(self):
        with TemporaryDirectory() as tmp_dir:
            profile, _path = self._load(
                tmp_dir, self._v3_profile({"a": "z", "audio_mute": "f9"})
            )
            bindings = profile["devices"]["keyboard"]["bindings"]
            self.assertEqual(bindings["reset_game"], "r")
            self.assertEqual(bindings["turbo"], "t")
            self.assertEqual(bindings["state_slot_increase"], "pageup")
            self.assertEqual(bindings["state_slot_decrease"], "pagedown")

    def test_the_superseded_mute_default_is_replaced(self):
        # f9 was what the app put there, not a choice anyone made.
        with TemporaryDirectory() as tmp_dir:
            profile, _path = self._load(tmp_dir, self._v3_profile({"audio_mute": "f9"}))
            self.assertEqual(
                profile["devices"]["keyboard"]["bindings"]["audio_mute"], "m"
            )

    def test_a_deliberate_binding_is_left_alone(self):
        with TemporaryDirectory() as tmp_dir:
            profile, _path = self._load(
                tmp_dir,
                self._v3_profile({"audio_mute": "f10", "reset_game": "backspace"}),
            )
            bindings = profile["devices"]["keyboard"]["bindings"]
            self.assertEqual(bindings["audio_mute"], "f10")
            self.assertEqual(bindings["reset_game"], "backspace")

    def test_it_is_persisted_at_the_new_version(self):
        with TemporaryDirectory() as tmp_dir:
            _profile, path = self._load(tmp_dir, self._v3_profile({"a": "z"}))
            stored = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(stored["version"], PROFILE_VERSION)
            self.assertEqual(
                stored["devices"]["keyboard"]["bindings"]["reset_game"], "r"
            )

    def test_it_does_not_run_twice(self):
        # Once migrated, clearing a binding must stick.
        with TemporaryDirectory() as tmp_dir:
            manager = InputProfileManager(tmp_dir)
            profile = manager.load_profile("SFC")
            profile["devices"]["keyboard"]["bindings"]["reset_game"] = ""
            manager.save_profile("SFC", profile)
            again = InputProfileManager(tmp_dir).load_profile("SFC")
            self.assertEqual(
                again["devices"]["keyboard"]["bindings"]["reset_game"], ""
            )

    def test_the_superseded_hotkey_modifier_is_cleared(self):
        # "right shift" is not a name RetroArch resolves, so hotkeys have
        # always fired directly. Translating it (issue #144) would otherwise
        # start demanding a modifier for every hotkey on existing profiles.
        with TemporaryDirectory() as tmp_dir:
            profile, _path = self._load(
                tmp_dir, self._v3_profile({"enable_hotkey": "right shift"})
            )
            self.assertEqual(
                profile["devices"]["keyboard"]["bindings"]["enable_hotkey"], ""
            )

    def test_a_deliberate_hotkey_modifier_survives(self):
        with TemporaryDirectory() as tmp_dir:
            profile, _path = self._load(
                tmp_dir, self._v3_profile({"enable_hotkey": "f12"})
            )
            self.assertEqual(
                profile["devices"]["keyboard"]["bindings"]["enable_hotkey"], "f12"
            )

    def test_the_pad_keeps_its_modifier(self):
        with TemporaryDirectory() as tmp_dir:
            profile, _path = self._load(tmp_dir, self._v3_profile({"a": "z"}))
            self.assertEqual(
                profile["devices"]["gamepad_p1"]["bindings"]["enable_hotkey"], "6"
            )

    def test_the_pad_is_not_touched(self):
        with TemporaryDirectory() as tmp_dir:
            profile, _path = self._load(tmp_dir, self._v3_profile({"a": "z"}))
            pad = profile["devices"]["gamepad_p1"]["bindings"]
            for action in ("reset_game", "turbo", "audio_mute",
                           "state_slot_increase", "state_slot_decrease"):
                self.assertEqual(pad.get(action, ""), "", action)


class V5KeyboardDefaultsMigrationTests(unittest.TestCase):
    """Issue #153/#158: the new hotkeys and stick keys reach old profiles."""

    def _v4_profile(self, keyboard_bindings, console="PS"):
        return {
            "version": 4,
            "console": console,
            "active_device": "keyboard",
            "devices": {
                "keyboard": {
                    "type": "keyboard",
                    "enabled": True,
                    "bindings": keyboard_bindings,
                }
            },
        }

    def _load(self, tmp_dir, profile, console="PS"):
        path = Path(tmp_dir) / f"{console}.config"
        path.write_text(json.dumps(profile), encoding="utf-8")
        return InputProfileManager(tmp_dir).load_profile(console)

    def test_the_new_hotkeys_are_filled(self):
        with TemporaryDirectory() as tmp_dir:
            bindings = self._load(tmp_dir, self._v4_profile({"a": "z"}))[
                "devices"
            ]["keyboard"]["bindings"]
            self.assertEqual(bindings["rewind"], "w")
            self.assertEqual(bindings["pause_toggle"], "p")
            self.assertEqual(bindings["screenshot"], "f8")
            self.assertEqual(bindings["disk_next"], "n")
            self.assertEqual(bindings["disk_prev"], "b")
            self.assertEqual(bindings["disk_eject_toggle"], "f9")

    def test_the_stick_keys_are_filled_on_an_analog_console(self):
        with TemporaryDirectory() as tmp_dir:
            bindings = self._load(tmp_dir, self._v4_profile({"a": "z"}))[
                "devices"
            ]["keyboard"]["bindings"]
            self.assertEqual(bindings["l_up"], "i")
            self.assertEqual(bindings["l_left"], "j")

    def test_a_digital_console_gets_no_stick_keys(self):
        with TemporaryDirectory() as tmp_dir:
            bindings = self._load(
                tmp_dir, self._v4_profile({"a": "z"}, console="SFC"), console="SFC"
            )["devices"]["keyboard"]["bindings"]
            self.assertNotIn("l_up", bindings)

    def test_a_deliberate_binding_is_left_alone(self):
        with TemporaryDirectory() as tmp_dir:
            bindings = self._load(
                tmp_dir, self._v4_profile({"rewind": "f12", "disk_next": "y"})
            )["devices"]["keyboard"]["bindings"]
            self.assertEqual(bindings["rewind"], "f12")
            self.assertEqual(bindings["disk_next"], "y")

    def test_it_does_not_run_twice(self):
        with TemporaryDirectory() as tmp_dir:
            manager = InputProfileManager(tmp_dir)
            profile = manager.load_profile("PS")
            profile["devices"]["keyboard"]["bindings"]["rewind"] = ""
            manager.save_profile("PS", profile)
            again = InputProfileManager(tmp_dir).load_profile("PS")
            self.assertEqual(again["devices"]["keyboard"]["bindings"]["rewind"], "")

    def test_the_pad_gets_none_of_them(self):
        with TemporaryDirectory() as tmp_dir:
            pad = self._load(tmp_dir, self._v4_profile({"a": "z"}))["devices"][
                "gamepad_p1"
            ]["bindings"]
            for action in ("rewind", "pause_toggle", "disk_next", "l_up"):
                self.assertEqual(pad.get(action, ""), "", action)


class UnreachableGamepadButtonMigrationTests(unittest.TestCase):
    """Issue #124: repair profiles pinned to pad buttons that do not exist."""

    def _v2_profile(self):
        return {
            "version": 2,
            "console": "SFC",
            "active_device": "gamepad_p1",
            "devices": {
                "gamepad_p1": {
                    "type": "gamepad",
                    "enabled": True,
                    "bindings": {
                        "a": "0",
                        "select": "6",
                        "enable_hotkey": "14",
                        "save_state": "11",
                        "load_state": "12",
                        "fast_forward_toggle": "13",
                        "fullscreen_toggle": "15",
                        "l2": "+2",
                        "up": "h0up",
                    },
                }
            },
        }

    def test_v2_hotkeys_are_replaced_by_reachable_defaults(self):
        with TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "SFC.config"
            path.write_text(json.dumps(self._v2_profile()), encoding="utf-8")
            manager = InputProfileManager(tmp_dir)
            profile = manager.load_profile("SFC")

            bindings = profile["devices"]["gamepad_p1"]["bindings"]
            self.assertEqual(bindings["enable_hotkey"], "6")
            self.assertEqual(bindings["save_state"], "2")
            self.assertEqual(bindings["load_state"], "3")
            self.assertEqual(bindings["fullscreen_toggle"], "4")
            self.assertEqual(bindings["fast_forward_toggle"], "5")

    def test_migration_is_persisted_at_the_new_version(self):
        with TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "SFC.config"
            path.write_text(json.dumps(self._v2_profile()), encoding="utf-8")
            InputProfileManager(tmp_dir).load_profile("SFC")

            # load_profile re-saves when normalization changed anything, so the
            # repair survives without the user resetting anything.
            stored = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(stored["version"], PROFILE_VERSION)
            self.assertEqual(
                stored["devices"]["gamepad_p1"]["bindings"]["enable_hotkey"], "6"
            )

    def test_reachable_and_non_button_bindings_are_left_alone(self):
        with TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "SFC.config"
            path.write_text(json.dumps(self._v2_profile()), encoding="utf-8")
            bindings = InputProfileManager(tmp_dir).load_profile("SFC")[
                "devices"
            ]["gamepad_p1"]["bindings"]
            self.assertEqual(bindings["a"], "0")
            self.assertEqual(bindings["select"], "6")
            # SFC has no L2, so the axis token is exercised on the helper
            # directly below; here the hat proves non-button tokens survive.
            self.assertEqual(bindings["up"], "h0up")

    def test_a_current_profile_is_not_migrated_again(self):
        with TemporaryDirectory() as tmp_dir:
            manager = InputProfileManager(tmp_dir)
            manager.load_profile("SFC")
            profile = manager.load_profile("SFC")
            profile["devices"]["gamepad_p1"]["bindings"]["save_state"] = "11"
            saved = manager.save_profile("SFC", profile)
            # Already at PROFILE_VERSION: a deliberate choice is the user's.
            self.assertEqual(
                saved["devices"]["gamepad_p1"]["bindings"]["save_state"], "11"
            )

    def test_helper_only_clears_out_of_range_button_indices(self):
        cleared = clear_unreachable_gamepad_buttons(
            {"a": "10", "b": "11", "l2": "+2", "up": "h0up", "x": ""}
        )
        self.assertEqual(cleared["a"], "10")
        self.assertEqual(cleared["b"], "")
        self.assertEqual(cleared["l2"], "+2")
        self.assertEqual(cleared["up"], "h0up")


if __name__ == "__main__":
    unittest.main()
