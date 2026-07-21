import unittest

from openemux.core.gamepad_reader import (
    ABS_HAT0X,
    BTN_GAMEPAD,
    EV_ABS,
    EV_KEY,
)

ABS_HAT0Y = ABS_HAT0X + 1
from openemux.core.ui_gamepad import (
    NAV_TOKEN_ACTIONS,
    NavTokenTracker,
    RepeatClock,
    REPEATABLE_ACTIONS,
    action_for_token,
)

# A typical pad: 11 buttons from BTN_GAMEPAD (indices 0..10), left/right
# sticks + triggers (axes 0..5 after hat exclusion) and one hat.
KEY_CODES = list(range(BTN_GAMEPAD, BTN_GAMEPAD + 11))
ABS_CODES = [0, 1, 2, 3, 4, 5, ABS_HAT0X, ABS_HAT0Y]


def make_tracker():
    return NavTokenTracker(KEY_CODES, ABS_CODES)


class ActionMapTests(unittest.TestCase):
    def test_confirm_back_context_favorite(self):
        self.assertEqual(action_for_token("0"), "confirm")
        self.assertEqual(action_for_token("1"), "back")
        self.assertEqual(action_for_token("2"), "context")
        self.assertEqual(action_for_token("3"), "favorite")

    def test_start_confirms_and_shoulders_switch_console(self):
        self.assertEqual(action_for_token("7"), "confirm")
        self.assertEqual(action_for_token("4"), "prev_console")
        self.assertEqual(action_for_token("5"), "next_console")

    def test_dpad_and_left_stick_are_directions(self):
        for token, action in (
            ("h0up", "up"), ("h0down", "down"), ("h0left", "left"), ("h0right", "right"),
            ("-1", "up"), ("+1", "down"), ("-0", "left"), ("+0", "right"),
        ):
            self.assertEqual(action_for_token(token), action)

    def test_unknown_token_is_none(self):
        self.assertIsNone(action_for_token("9"))
        self.assertIsNone(action_for_token(""))
        self.assertIsNone(action_for_token(None))

    def test_only_directions_repeat(self):
        self.assertEqual(REPEATABLE_ACTIONS, {"up", "down", "left", "right"})
        for token in ("0", "1", "2", "3", "4", "5", "7"):
            self.assertNotIn(NAV_TOKEN_ACTIONS[token], REPEATABLE_ACTIONS)


class NavTokenTrackerTests(unittest.TestCase):
    def test_button_press_and_release(self):
        tracker = make_tracker()
        self.assertEqual(tracker.feed(EV_KEY, BTN_GAMEPAD, 1), [("0", True)])
        self.assertEqual(tracker.feed(EV_KEY, BTN_GAMEPAD, 0), [("0", False)])

    def test_kernel_autorepeat_is_ignored(self):
        tracker = make_tracker()
        tracker.feed(EV_KEY, BTN_GAMEPAD, 1)
        self.assertEqual(tracker.feed(EV_KEY, BTN_GAMEPAD, 2), [])

    def test_release_without_press_is_silent(self):
        tracker = make_tracker()
        self.assertEqual(tracker.feed(EV_KEY, BTN_GAMEPAD, 0), [])

    def test_unknown_keycode_is_silent(self):
        tracker = make_tracker()
        self.assertEqual(tracker.feed(EV_KEY, 0x1234, 1), [])

    def test_hat_press_and_center(self):
        tracker = make_tracker()
        self.assertEqual(tracker.feed(EV_ABS, ABS_HAT0Y, -1), [("h0up", True)])
        self.assertEqual(tracker.feed(EV_ABS, ABS_HAT0Y, 0), [("h0up", False)])

    def test_hat_flip_releases_then_presses(self):
        tracker = make_tracker()
        tracker.feed(EV_ABS, ABS_HAT0X, -1)
        self.assertEqual(
            tracker.feed(EV_ABS, ABS_HAT0X, 1),
            [("h0left", False), ("h0right", True)],
        )

    def test_hat_axes_are_independent(self):
        tracker = make_tracker()
        self.assertEqual(tracker.feed(EV_ABS, ABS_HAT0X, 1), [("h0right", True)])
        self.assertEqual(tracker.feed(EV_ABS, ABS_HAT0Y, -1), [("h0up", True)])
        self.assertEqual(tracker.feed(EV_ABS, ABS_HAT0X, 0), [("h0right", False)])

    def test_axis_press_hysteresis_and_release(self):
        tracker = make_tracker()
        # Inside the deadzone: nothing.
        self.assertEqual(tracker.feed(EV_ABS, 1, 4000), [])
        # Past the threshold: press...
        self.assertEqual(tracker.feed(EV_ABS, 1, 30000), [("+1", True)])
        # ...held past threshold: no repeat from the tracker itself...
        self.assertEqual(tracker.feed(EV_ABS, 1, 32000), [])
        # ...back inside the deadzone: release.
        self.assertEqual(tracker.feed(EV_ABS, 1, 100), [("+1", False)])

    def test_axis_swing_across_zero(self):
        tracker = make_tracker()
        tracker.feed(EV_ABS, 0, 30000)
        self.assertEqual(
            tracker.feed(EV_ABS, 0, -30000),
            [("+0", False), ("-0", True)],
        )

    def test_release_all_forgets_held_state(self):
        tracker = make_tracker()
        tracker.feed(EV_KEY, BTN_GAMEPAD, 1)
        tracker.feed(EV_ABS, ABS_HAT0Y, 1)
        tracker.release_all()
        self.assertEqual(tracker.feed(EV_KEY, BTN_GAMEPAD, 0), [])
        self.assertEqual(tracker.feed(EV_ABS, ABS_HAT0Y, 0), [])


class FakeClock:
    def __init__(self):
        self.value = 100.0

    def advance(self, seconds):
        self.value += seconds

    def __call__(self):
        return self.value


class RepeatClockTests(unittest.TestCase):
    def setUp(self):
        self.time = FakeClock()
        self.clock = RepeatClock(delay=0.4, interval=0.12, now=self.time)

    def test_no_repeat_before_delay(self):
        self.clock.press("down")
        self.time.advance(0.39)
        self.assertEqual(self.clock.due_actions(), [])

    def test_repeats_after_delay_then_interval(self):
        self.clock.press("down")
        self.time.advance(0.4)
        self.assertEqual(self.clock.due_actions(), ["down"])
        self.time.advance(0.12)
        self.assertEqual(self.clock.due_actions(), ["down"])
        self.time.advance(0.05)
        self.assertEqual(self.clock.due_actions(), [])

    def test_release_stops_repeat(self):
        self.clock.press("down")
        self.clock.release("down")
        self.time.advance(10)
        self.assertEqual(self.clock.due_actions(), [])
        self.assertIsNone(self.clock.next_deadline())

    def test_next_deadline_tracks_earliest(self):
        self.clock.press("down")
        self.time.advance(0.1)
        self.clock.press("right")
        deadline = self.clock.next_deadline()
        self.assertAlmostEqual(deadline, 0.3, places=6)

    def test_clear_drops_everything(self):
        self.clock.press("down")
        self.clock.press("right")
        self.clock.clear()
        self.time.advance(10)
        self.assertEqual(self.clock.due_actions(), [])


if __name__ == "__main__":
    unittest.main()
