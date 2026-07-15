import unittest
from tempfile import TemporaryDirectory

from openemux.core.input_profiles import InputProfileManager


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


if __name__ == "__main__":
    unittest.main()
