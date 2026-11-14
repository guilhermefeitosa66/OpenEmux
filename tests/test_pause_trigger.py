"""The gesture that opens Big Picture's pause menu during a game (issue 957)."""

import unittest

from openemux.core import pause_trigger as pt


class TheModes(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(pt.normalize_mode("l3_r3"), pt.L3_R3)
        self.assertEqual(pt.normalize_mode("nope"), pt.DEFAULT_MODE)
        self.assertEqual(pt.normalize_mode(None), pt.GUIDE)
        self.assertEqual(pt.PauseTrigger("nope").mode, pt.GUIDE)

    def test_guide_fires_on_the_press_only(self):
        trigger = pt.PauseTrigger(pt.GUIDE)
        self.assertTrue(trigger.feed("8", True, 0))
        self.assertFalse(trigger.feed("8", False, 0.1))
        self.assertFalse(trigger.feed("7", True, 0.2))
        self.assertFalse(trigger.poll(5))
        self.assertIsNone(trigger.next_deadline(5))

    def test_hold_start_fires_once_after_the_delay(self):
        trigger = pt.PauseTrigger(pt.HOLD_START)
        self.assertFalse(trigger.feed("7", True, 10.0))
        self.assertAlmostEqual(trigger.next_deadline(10.2), pt.HOLD_SECONDS - 0.2)
        self.assertFalse(trigger.poll(10.0 + pt.HOLD_SECONDS / 2))
        self.assertTrue(trigger.poll(10.0 + pt.HOLD_SECONDS))
        self.assertFalse(trigger.poll(20.0))  # once per press
        self.assertIsNone(trigger.next_deadline(20.0))
        self.assertFalse(trigger.feed("7", False, 21.0))
        # A short press reaches the game and opens nothing.
        self.assertFalse(trigger.feed("7", True, 30.0))
        self.assertFalse(trigger.feed("7", False, 30.2))
        self.assertFalse(trigger.poll(40.0))
        self.assertIsNone(trigger.next_deadline(40.0))
        # Another button does not touch the clock.
        self.assertFalse(trigger.feed("0", True, 50.0))

    def test_hold_start_fires_from_a_feed_too(self):
        trigger = pt.PauseTrigger(pt.HOLD_START)
        trigger.feed("7", True, 0.0)
        self.assertTrue(trigger.feed("3", True, pt.HOLD_SECONDS + 0.1))

    def test_chords(self):
        for mode, first, second in ((pt.START_SELECT, "7", "6"), (pt.L3_R3, "9", "10")):
            trigger = pt.PauseTrigger(mode)
            self.assertFalse(trigger.feed(first, True, 0))
            self.assertTrue(trigger.feed(second, True, 0.1))
            self.assertFalse(trigger.feed("0", True, 0.2))  # already fired
            self.assertFalse(trigger.feed(second, False, 0.3))
            self.assertTrue(trigger.feed(second, True, 0.4))  # again after a release

    def test_off_never_fires(self):
        trigger = pt.PauseTrigger(pt.OFF)
        for token in ("6", "7", "8", "9", "10"):
            self.assertFalse(trigger.feed(token, True, 0))

    def test_set_mode_resets(self):
        trigger = pt.PauseTrigger(pt.HOLD_START)
        trigger.feed("7", True, 0)
        trigger.set_mode(pt.START_SELECT)
        self.assertEqual(trigger.mode, pt.START_SELECT)
        self.assertFalse(trigger.feed("6", True, 1))  # Start was forgotten


if __name__ == "__main__":
    unittest.main()
