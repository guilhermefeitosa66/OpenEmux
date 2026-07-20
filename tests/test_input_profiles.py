import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from openemux.core.input_profiles import (
    DEVICE_IDS,
    EXTRA_PORT_DEVICE_IDS,
    InputProfileManager,
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


if __name__ == "__main__":
    unittest.main()
