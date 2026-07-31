"""Global input tuning (issues #154, #155)."""

import unittest

from openemux.core import input_tuning


class ClampTests(unittest.TestCase):
    def test_ranges_are_respected(self):
        self.assertEqual(input_tuning.clamp("analog_deadzone", 9.0), 1.0)
        self.assertEqual(input_tuning.clamp("analog_deadzone", -1), 0.0)
        self.assertEqual(input_tuning.clamp("rumble_gain", 500), 100)
        self.assertEqual(input_tuning.clamp("max_users", 99), 16)
        self.assertEqual(input_tuning.clamp("poll_type_behavior", 7), 2)

    def test_garbage_falls_back_to_retroarchs_default(self):
        self.assertEqual(input_tuning.clamp("analog_deadzone", "nonsense"), 0.0)
        self.assertEqual(input_tuning.clamp("rumble_gain", None), 100)

    def test_booleans_accept_the_shapes_yaml_produces(self):
        self.assertTrue(input_tuning.clamp("descriptor_label_show", "true"))
        self.assertTrue(input_tuning.clamp("descriptor_label_show", True))
        self.assertFalse(input_tuning.clamp("descriptor_label_show", "false"))
        self.assertFalse(input_tuning.clamp("descriptor_label_show", 0))


class OverrideTests(unittest.TestCase):
    def test_an_untouched_install_writes_nothing(self):
        # Every value equal to RetroArch's own default, so the override file
        # is byte-identical to what it was before these settings existed.
        defaults = {name: input_tuning.default_for(name) for name in input_tuning.INPUT_TUNING}
        self.assertEqual(input_tuning.to_retroarch_overrides(defaults), {})
        self.assertEqual(input_tuning.to_retroarch_overrides({}), {})
        self.assertEqual(input_tuning.to_retroarch_overrides(None), {})

    def test_only_what_differs_is_written(self):
        overrides = input_tuning.to_retroarch_overrides({"analog_deadzone": 0.15})
        self.assertEqual(overrides, {"input_analog_deadzone": '"0.150000"'})

    def test_floats_are_written_the_way_retroarch_writes_them(self):
        overrides = input_tuning.to_retroarch_overrides({"analog_sensitivity": 1.5})
        self.assertEqual(overrides["input_analog_sensitivity"], '"1.500000"')

    def test_booleans_are_written_lowercase(self):
        overrides = input_tuning.to_retroarch_overrides({"descriptor_label_show": False})
        self.assertEqual(overrides["input_descriptor_label_show"], '"false"')

    def test_integers_carry_no_decimal_point(self):
        overrides = input_tuning.to_retroarch_overrides({"rumble_gain": 40})
        self.assertEqual(overrides["input_rumble_gain"], '"40"')

    def test_out_of_range_values_are_clamped_before_writing(self):
        overrides = input_tuning.to_retroarch_overrides({"analog_deadzone": 9.0})
        self.assertEqual(overrides["input_analog_deadzone"], '"1.000000"')

    def test_the_keys_are_the_ones_retroarch_reads(self):
        # Taken from a real retroarch.cfg -- notably the turbo one is
        # input_turbo_button, not input_turbo_default_button.
        keys = {entry[0] for entry in input_tuning.INPUT_TUNING.values()}
        self.assertIn("input_analog_deadzone", keys)
        self.assertIn("input_axis_threshold", keys)
        self.assertIn("input_auto_game_focus", keys)
        self.assertIn("input_poll_type_behavior", keys)


if __name__ == "__main__":
    unittest.main()
