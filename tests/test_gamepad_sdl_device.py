"""End-to-end check of the SDL backend against a real kernel input device.

``test_gamepad_sdl.py`` drives the decoding with a fake SDL, which proves the
state machine. It cannot prove the part that actually decides whether the
Windows port works: that **SDL numbers a pad's controls the way OpenEmux
assumes**, and therefore that ``NAV_TOKEN_ACTIONS`` -- one fixed token-to-action
map, shared by both backends -- picks the same physical buttons either way.

So this creates a virtual gamepad through uinput and reads it through the real
libSDL2. SDL's Linux joystick backend reads the same ``/dev/input/event*`` node
the evdev reader does, which makes the two directly comparable: the assertions
below are the ones ``test_ui_gamepad_device.py`` makes, against the other
backend.

Linux-only and skipped wherever ``/dev/uinput`` is not writable or libSDL2 is
absent -- so, in practice, on the maintainer's machine and nowhere else. The
Windows half of the round trip (RetroArch reading the token back) is RT-264,
and needs a person with a controller.
"""

import time
import unittest

from tests.platform_marks import IS_LINUX

if not IS_LINUX:  # the virtual pad below is a Linux kernel interface
    raise unittest.SkipTest("uinput is a Linux kernel interface")

from openemux.core import gamepad_sdl as gs
from openemux.core.ui_gamepad import action_for_token
from tests.test_ui_gamepad_device import (
    ABS_HAT0X,
    ABS_HAT0Y,
    BTN_EAST,
    BTN_NORTH,
    BTN_SOUTH,
    BTN_START,
    BTN_TL,
    BTN_TR,
    BTN_WEST,
    PAD_NAME,
    VirtualGamepad,
    uinput_available,
)

ABS_X, ABS_Y = 0x00, 0x01


def sdl2_available():
    try:
        gs.load_sdl2().init()
    except Exception:
        return False
    return True


@unittest.skipUnless(uinput_available(), "/dev/uinput is not writable here")
@unittest.skipUnless(sdl2_available(), "libSDL2 is not installed here")
class SdlNavigatorDeviceTests(unittest.TestCase):
    def setUp(self):
        self.pad = VirtualGamepad(axes=(ABS_X, ABS_Y))
        self.actions = []
        self.connected = []
        # A pump of its own, not the process-wide one: a test must not leave
        # SDL initialised for whatever runs next.
        self.pump = gs.SdlJoystickPump()
        self.nav = gs.SdlNavigator(
            self.actions.append,
            on_connected=self.connected.append,
            pump=self.pump,
        )
        self.nav.start()
        deadline = time.monotonic() + 5.0
        while not self.connected and time.monotonic() < deadline:
            time.sleep(0.05)

    def tearDown(self):
        self.nav.stop()
        self.pad.close()

    def _first_action(self, settle=0.35):
        time.sleep(settle)
        return self.actions[0] if self.actions else None

    def test_the_pad_is_discovered_through_sdl(self):
        self.assertTrue(any(PAD_NAME in name for name in self.connected),
                        f"SDL never announced the pad; saw {self.connected}")

    def test_face_buttons_map_to_the_same_actions_as_evdev(self):
        # The assertion this whole file exists for. These are the pairs
        # test_ui_gamepad_device.py asserts against the evdev reader; if SDL
        # numbered the same device differently, UI navigation on Windows would
        # act on the wrong buttons and nothing else would notice.
        for code, expected in (
            (BTN_SOUTH, "confirm"),
            (BTN_EAST, "back"),
            (BTN_NORTH, "context"),
            (BTN_WEST, "favorite"),
            (BTN_START, "confirm"),
        ):
            with self.subTest(button=hex(code)):
                self.actions.clear()
                self.pad.press(code)
                self.assertEqual(self._first_action(), expected)

    def test_the_shoulders_switch_console(self):
        for code, expected in ((BTN_TL, "prev_console"), (BTN_TR, "next_console")):
            with self.subTest(button=hex(code)):
                self.actions.clear()
                self.pad.press(code)
                self.assertEqual(self._first_action(), expected)

    def test_the_hat_steers(self):
        for code, value, expected in (
            (ABS_HAT0Y, -1, "up"),
            (ABS_HAT0Y, 1, "down"),
            (ABS_HAT0X, -1, "left"),
            (ABS_HAT0X, 1, "right"),
        ):
            with self.subTest(hat=(code, value)):
                self.actions.clear()
                self.pad.hat(code, value)
                self.assertEqual(self._first_action(), expected)

    def test_the_left_stick_steers(self):
        for code, value, expected in (
            (ABS_Y, -32000, "up"),
            (ABS_Y, 32000, "down"),
            (ABS_X, -32000, "left"),
            (ABS_X, 32000, "right"),
        ):
            with self.subTest(axis=(code, value)):
                self.actions.clear()
                self.pad.hold(code, value)
                observed = self._first_action()
                self.pad.hold(code, 0)
                time.sleep(0.1)
                self.assertEqual(observed, expected)

    def test_an_idle_pad_reports_nothing(self):
        # The resting-trigger trap, on a real device: opening the pad must not
        # look like a control being held.
        time.sleep(0.5)
        self.assertEqual(self.actions, [])


@unittest.skipUnless(uinput_available(), "/dev/uinput is not writable here")
@unittest.skipUnless(sdl2_available(), "libSDL2 is not installed here")
class SdlCaptureDeviceTests(unittest.TestCase):
    """The remapping screen's half: a press becomes a token to store."""

    def setUp(self):
        self.pad = VirtualGamepad(axes=(ABS_X, ABS_Y))
        self.pump = gs.SdlJoystickPump()
        self.tokens = []
        self.errors = []
        self.reader = gs.SdlCaptureReader(
            on_token=self.tokens.append,
            on_error=self.errors.append,
            pump=self.pump,
        )
        self.reader.start()
        time.sleep(1.0)

    def tearDown(self):
        self.reader.stop()
        self.pad.close()

    def test_a_press_is_captured_as_a_token_the_ui_can_name(self):
        self.pad.press(BTN_SOUTH)
        deadline = time.monotonic() + 3.0
        while not self.tokens and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertEqual(self.errors, [])
        self.assertEqual(self.tokens, ["0"])
        # And the same token the navigation map reads as "confirm", which is
        # what makes one map serve both backends.
        self.assertEqual(action_for_token(self.tokens[0]), "confirm")


if __name__ == "__main__":
    unittest.main()
