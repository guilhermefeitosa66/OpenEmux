import errno
import os
import struct
import unittest
from unittest.mock import patch

from openemux.core.gamepad_reader import (
    ABS_HAT0X,
    BTN_GAMEPAD,
    EV_ABS,
    EV_KEY,
    INPUT_EVENT_FORMAT,
)

ABS_HAT0Y = ABS_HAT0X + 1
from openemux.core.ui_gamepad import (
    NAV_TOKEN_ACTIONS,
    GamepadNavigator,
    HoldClock,
    NavTokenTracker,
    OpenPad,
    RepeatClock,
    REPEATABLE_ACTIONS,
    action_for_token,
)
from tests.platform_marks import linux_only

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

    def test_the_right_stick_steers_like_the_left_one(self):
        for token, action in (
            ("-4", "up"), ("+4", "down"), ("-3", "left"), ("+3", "right"),
        ):
            with self.subTest(token=token):
                self.assertEqual(action_for_token(token), action)

    def test_the_triggers_are_not_directions(self):
        """Axes 2 and 5 are L2/R2: the range modifier when pressed (issue
        #78), and still nothing at rest -- a resting trigger reading as a held
        control was the original hazard."""
        for token in ("+2", "+5"):
            with self.subTest(token=token):
                self.assertEqual(action_for_token(token), "range")
        for token in ("-2", "-5"):
            with self.subTest(token=token):
                self.assertIsNone(action_for_token(token))

    def test_select_opens_the_window_menu(self):
        self.assertEqual(action_for_token("6"), "menu")

    def test_unknown_token_is_none(self):
        self.assertIsNone(action_for_token("9"))
        self.assertIsNone(action_for_token(""))
        self.assertIsNone(action_for_token(None))

    def test_only_directions_repeat(self):
        self.assertEqual(REPEATABLE_ACTIONS, {"up", "down", "left", "right"})
        for token in ("0", "1", "2", "3", "4", "5", "6", "7"):
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


class HoldClockTests(unittest.TestCase):
    """Tap vs long-press for Ⓐ (issue #78: hold enters selection mode)."""

    def setUp(self):
        self.time = FakeClock()
        self.clock = HoldClock(delay=0.5, now=self.time)

    def test_quick_release_is_a_tap(self):
        self.clock.press("confirm")
        self.time.advance(0.2)
        self.assertEqual(self.clock.due_actions(), [])
        # Released before the delay: the tap should still fire.
        self.assertTrue(self.clock.release("confirm"))

    def test_long_press_fires_the_hold_once_and_swallows_the_tap(self):
        self.clock.press("confirm")
        self.time.advance(0.6)
        self.assertEqual(self.clock.due_actions(), ["confirm"])
        # Only once, however long it stays held.
        self.time.advance(5)
        self.assertEqual(self.clock.due_actions(), [])
        # The release must not fire the tap on top of the hold.
        self.assertFalse(self.clock.release("confirm"))

    def test_a_new_press_after_a_hold_starts_clean(self):
        self.clock.press("confirm")
        self.time.advance(0.6)
        self.clock.due_actions()
        self.clock.release("confirm")
        self.clock.press("confirm")
        self.time.advance(0.1)
        self.assertTrue(self.clock.release("confirm"))

    def test_next_deadline_and_clear(self):
        self.assertIsNone(self.clock.next_deadline())
        self.clock.press("confirm")
        self.assertAlmostEqual(self.clock.next_deadline(), 0.5, places=6)
        self.clock.clear()
        self.assertIsNone(self.clock.next_deadline())
        self.time.advance(10)
        self.assertEqual(self.clock.due_actions(), [])


class SuspendGuardTests(unittest.TestCase):
    """A failing suspend check must not take the reader thread down (#223).

    ``should_suspend`` reaches into the window and the runtime manager, and
    ``_run`` is a bare thread: nothing above it catches. One
    ``AttributeError`` from the game-exit race ended navigation for the rest
    of the session, with only a line in the startup log to show for it.
    """

    def _navigator(self, should_suspend):
        return GamepadNavigator(on_action=lambda action: None,
                                should_suspend=should_suspend)

    def test_a_raising_check_reads_as_suspended(self):
        def _boom():
            raise AttributeError("'NoneType' object has no attribute 'poll'")

        nav = self._navigator(_boom)
        with self.assertLogs("openemux.core.ui_gamepad", level="WARNING"):
            self.assertTrue(nav._suspended())
        # And again: one failure must not latch anything off.
        with self.assertLogs("openemux.core.ui_gamepad", level="WARNING"):
            self.assertTrue(nav._suspended())

    def test_a_recovering_check_resumes_navigation(self):
        calls = []

        def _flaky():
            calls.append(None)
            if len(calls) == 1:
                raise RuntimeError("transient")
            return False

        nav = self._navigator(_flaky)
        with self.assertLogs("openemux.core.ui_gamepad", level="WARNING"):
            self.assertTrue(nav._suspended())
        self.assertFalse(nav._suspended())

    def test_a_normal_check_is_passed_through(self):
        self.assertFalse(self._navigator(lambda: False)._suspended())
        self.assertTrue(self._navigator(lambda: True)._suspended())

    def test_no_callback_means_never_suspended(self):
        nav = GamepadNavigator(on_action=lambda action: None)
        self.assertFalse(nav._suspended())


class _FakeDevice:
    def __init__(self, name, event_path):
        self.name = name
        self.event_path = event_path
        self.js_path = None
        self.key_codes = KEY_CODES
        self.abs_codes = ABS_CODES


@linux_only("it opens /dev/input nodes and select()s on them")
class HotplugScanTests(unittest.TestCase):
    """A second pad plugged in next to a working one has to be picked up.

    ``_open_pads`` used to run only while nothing was open, so the rescan never
    happened once a pad was connected: the second controller was invisible to
    UI navigation until the first was unplugged (#223).
    """

    def setUp(self):
        self.opened = []
        self.devices = [_FakeDevice("Pad One", "/dev/input/event20")]

        # Captured before the patch: patching os.open on the module patches
        # the shared os module, so calling it again would recurse.
        real_open = os.open

        def _fake_open(path, flags):
            self.opened.append(path)
            # A real fd, so _close_all has something valid to close.
            return real_open(os.devnull, os.O_RDONLY)

        self._patches = [
            patch("openemux.core.ui_gamepad.list_gamepads", lambda: list(self.devices)),
            patch("openemux.core.ui_gamepad.os.open", _fake_open),
            patch("openemux.core.ui_gamepad._read_axis_ranges", lambda fd, codes: {}),
        ]
        for entry in self._patches:
            entry.start()
        self.addCleanup(lambda: [entry.stop() for entry in self._patches])
        self.nav = GamepadNavigator(on_action=lambda action: None)

    def test_a_rescan_adds_a_new_pad_without_reopening_the_old_one(self):
        pads = self.nav._open_pads()
        self.assertEqual(self.opened, ["/dev/input/event20"])
        self.assertEqual([pad.name for pad in pads.values()], ["Pad One"])

        self.devices.append(_FakeDevice("Pad Two", "/dev/input/event21"))
        held = {pad.path for pad in pads.values()}
        added = self.nav._open_pads(held)

        self.assertEqual([pad.name for pad in added.values()], ["Pad Two"])
        self.assertEqual(self.opened, ["/dev/input/event20", "/dev/input/event21"])
        self.nav._close_all(pads)
        self.nav._close_all(added)

    def test_a_rescan_with_nothing_new_opens_nothing(self):
        pads = self.nav._open_pads()
        again = self.nav._open_pads({pad.path for pad in pads.values()})

        self.assertEqual(again, {})
        self.assertEqual(self.opened, ["/dev/input/event20"])
        self.nav._close_all(pads)


class ReadErrorTests(unittest.TestCase):
    """An unexpected errno drops the descriptor instead of spinning (#223).

    Returning True left the fd in the select set: select reports it readable,
    the read raises, and around again at full speed on one core.
    """

    def setUp(self):
        self.nav = GamepadNavigator(on_action=lambda action: None)
        self.pads = {7: OpenPad(make_tracker(), "Pad One", "/dev/input/event20")}

    def _read_raising(self, errno_value):
        with patch("openemux.core.ui_gamepad.os.read",
                   side_effect=OSError(errno_value, "boom")):
            return self.nav._read_fd(7, self.pads, RepeatClock(), HoldClock(), False)

    def test_a_device_that_went_away_is_dropped(self):
        self.assertFalse(self._read_raising(errno.ENODEV))

    def test_an_unexpected_errno_is_dropped_too(self):
        with self.assertLogs("openemux.core.ui_gamepad", level="WARNING"):
            self.assertFalse(self._read_raising(errno.EINVAL))

    def test_try_again_keeps_the_descriptor(self):
        with patch("openemux.core.ui_gamepad.os.read", side_effect=BlockingIOError):
            self.assertTrue(
                self.nav._read_fd(7, self.pads, RepeatClock(), HoldClock(), False)
            )


@linux_only("it drives the evdev reader through select() on a file")
class StaleSuspendFlagTests(unittest.TestCase):
    """The suspend flag is re-read after select(), not before it (#223).

    ``select()`` blocks for up to 200 ms and the events it reports arrived
    *during* that wait. Deciding with the value snapshotted beforehand meant a
    button pressed within that window of an input capture starting was both
    bound by the capture and acted on by the UI -- the double-handling
    exclusive capture exists to prevent.

    The fakes put the flip exactly inside ``select()``, which is the interleave
    that a real capture starting mid-wait produces.
    """

    #: Token "4" -> prev_console: not repeatable, not stateful, not holdable,
    #: so a press emits its action immediately and nothing else can mask it.
    PRESS_CODE = BTN_GAMEPAD + 4

    def _drive_one_pass(self, flip_during_select):
        actions = []
        suspended = [False]
        real_open = os.open

        press = struct.pack(INPUT_EVENT_FORMAT, 0, 0, EV_KEY, self.PRESS_CODE, 1)
        delivered = []

        nav = GamepadNavigator(
            on_action=actions.append,
            should_suspend=lambda: suspended[0],
        )

        selects = []

        def _fake_select(rlist, wlist, xlist, timeout):
            selects.append(timeout)
            if len(selects) > 1:
                # One pass with a press in it is all this needs. Cancelling
                # here rather than in the read keeps _emit alive for the
                # iteration under test -- it drops callbacks once cancelled.
                nav._cancel.set()
                return ([], [], [])
            if flip_during_select:
                suspended[0] = True
            return (list(rlist), [], [])

        def _fake_read(fd, size):
            if delivered:
                raise BlockingIOError
            delivered.append(fd)
            return press

        with patch("openemux.core.ui_gamepad.list_gamepads",
                   lambda: [_FakeDevice("Pad One", "/dev/input/event20")]), \
             patch("openemux.core.ui_gamepad.os.open",
                   lambda path, flags: real_open(os.devnull, os.O_RDONLY)), \
             patch("openemux.core.ui_gamepad._read_axis_ranges", lambda fd, codes: {}), \
             patch("openemux.core.ui_gamepad.select.select", _fake_select), \
             patch("openemux.core.ui_gamepad.os.read", _fake_read):
            nav._run()

        self.assertEqual(len(delivered), 1, "the press was never read")
        return actions

    def test_a_press_arriving_during_the_wait_is_dropped_once_suspended(self):
        self.assertEqual(self._drive_one_pass(flip_during_select=True), [])

    def test_the_same_press_is_acted_on_while_not_suspended(self):
        self.assertEqual(self._drive_one_pass(flip_during_select=False),
                         ["prev_console"])


if __name__ == "__main__":
    unittest.main()
