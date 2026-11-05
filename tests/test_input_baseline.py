import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from openemux.core import input_baseline
from openemux.core.input_actions import RETROARCH_STOCK_KEYBOARD_HOTKEYS
from openemux.core.retroarch_input_defaults import (
    GLOBAL_DEFAULTS,
    PLAYER_DEFAULTS,
    PLAYERS,
)


class TheBaselineTests(unittest.TestCase):
    """RetroArch's own default for every input key (issue #759)."""

    def setUp(self):
        self.baseline = input_baseline.baseline_overrides()

    def test_every_player_gets_every_key(self):
        self.assertEqual(PLAYERS, 16)
        for player in range(1, PLAYERS + 1):
            for suffix in PLAYER_DEFAULTS:
                self.assertIn(f"input_player{player}_{suffix}", self.baseline)
        self.assertNotIn("input_player17_a", self.baseline)
        self.assertEqual(
            len(self.baseline),
            len(GLOBAL_DEFAULTS) + PLAYERS * (len(PLAYER_DEFAULTS) + 3) + 1,
        )

    def test_known_defaults_of_retroarch_1_22_2(self):
        expected = {
            "input_player1_a": '"x"',
            "input_player1_b": '"z"',
            "input_player1_start": '"enter"',
            "input_player1_a_btn": '"nul"',
            "input_player2_a": '"nul"',
            "input_player1_joypad_index": '"0"',
            "input_player5_joypad_index": '"4"',
            "input_player16_mouse_index": '"15"',
            "input_exit_emulator": '"escape"',
            "input_menu_toggle": '"f1"',
            "input_reset": '"h"',
            "input_toggle_fast_forward": '"space"',
            "input_menu_toggle_gamepad_combo": '"0"',
            "input_autodetect_enable": '"true"',
            "input_max_users": '"8"',
            "input_libretro_device_p1": '"1"',
            "input_libretro_device_p16": '"1"',
        }
        for key, value in expected.items():
            self.assertEqual(self.baseline[key], value, key)

    def test_remap_files_are_off(self):
        self.assertEqual(self.baseline["auto_remaps_enable"], '"false"')

    def test_plumbing_and_overlay_settings_are_left_out(self):
        for key in (
            "input_driver",
            "input_joypad_driver",
            "input_keyboard_layout",
            "input_remapping_directory",
            "input_overlay",
            "input_overlay_enable",
            "input_osk_overlay",
        ):
            self.assertNotIn(key, self.baseline)
        # The overlay and keyboard hotkeys are binds, and stay.
        self.assertIn("input_overlay_next", self.baseline)
        self.assertIn("input_osk_toggle", self.baseline)

    def test_each_call_is_a_fresh_dict(self):
        self.baseline["input_player1_a"] = '"g"'
        self.assertEqual(input_baseline.baseline_overrides()["input_player1_a"], '"x"')


class TheStockHotkeysTests(unittest.TestCase):
    def test_only_global_keyboard_binds_with_a_key(self):
        hotkeys = input_baseline.stock_keyboard_hotkeys()
        self.assertEqual(hotkeys["input_exit_emulator"], "escape")
        self.assertEqual(hotkeys["input_toggle_fast_forward"], "space")
        self.assertEqual(hotkeys["input_state_slot_decrease"], "f6")
        # Unbound in stock RetroArch, pad suffixes and plain settings: none.
        self.assertNotIn("input_close_content", hotkeys)
        self.assertNotIn("input_exit_emulator_btn", hotkeys)
        self.assertNotIn("input_max_users", hotkeys)
        self.assertFalse([key for key in hotkeys if key.startswith("input_player")])

    def test_the_conflict_list_is_the_derived_one(self):
        self.assertEqual(
            RETROARCH_STOCK_KEYBOARD_HOTKEYS, input_baseline.stock_keyboard_hotkeys()
        )


class ReadingTheUsersFileTests(unittest.TestCase):
    def test_values_are_read_unquoted(self):
        with TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "retroarch.cfg"
            path.write_text('input_player1_a = "t"\nvideo_driver = "gl"\n', encoding="utf-8")
            self.assertEqual(
                input_baseline.read_cfg_values(path),
                {"input_player1_a": "t", "video_driver": "gl"},
            )

    def test_a_missing_file_is_empty(self):
        with TemporaryDirectory() as tmp_dir:
            self.assertEqual(input_baseline.read_cfg_values(Path(tmp_dir) / "none.cfg"), {})

    def test_a_file_that_is_not_utf8_is_empty(self):
        with TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "retroarch.cfg"
            path.write_bytes(b'input_player1_a = "\xff\xfe"\n')
            with self.assertLogs("openemux.core.input_baseline", level="DEBUG"):
                self.assertEqual(input_baseline.read_cfg_values(path), {})


class TheOverriddenKeysTests(unittest.TestCase):
    def test_only_input_keys_written_with_another_value(self):
        written = {
            "input_player1_a": '"g"',
            "input_exit_emulator": '"escape"',
            "input_menu_toggle": '"f1"',
            "auto_remaps_enable": '"false"',
            "video_driver": '"gl"',
        }
        user = {
            "input_player1_a": "t",          # differs -> listed
            "input_menu_toggle": "f1",       # same -> not listed
            "input_exit_emulator": "q",      # differs -> listed
            "auto_remaps_enable": "true",    # ours too -> listed
            "video_driver": "vulkan",        # not input -> ignored
            "input_driver": "x",             # not written -> still the user's
        }
        self.assertEqual(
            input_baseline.overridden_user_keys(user, written),
            ["auto_remaps_enable", "input_exit_emulator", "input_player1_a"],
        )

    def test_nothing_to_compare(self):
        self.assertEqual(input_baseline.overridden_user_keys(None, {"input_a": '"x"'}), [])


if __name__ == "__main__":
    unittest.main()
