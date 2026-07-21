"""End-to-end check of the navigator against a real kernel input device.

Creates a virtual gamepad through uinput and asserts that GamepadNavigator
discovers it, decodes its events and emits the right UI actions -- the one
seam the pure unit tests in test_ui_gamepad.py cannot cover, since it involves
udev's button numbering and /dev/input reading.

Skipped wherever /dev/uinput is not writable (CI, containers, hosts where the
user is not in the input group).
"""

import fcntl
import os
import struct
import time
import unittest

from openemux.core.gamepad_reader import list_gamepads
from openemux.core.ui_gamepad import GamepadNavigator

UI_SET_EVBIT = 0x40045564
UI_SET_KEYBIT = 0x40045565
UI_SET_ABSBIT = 0x40045567
UI_DEV_SETUP = 0x405C5503
UI_ABS_SETUP = 0x401C5504
UI_DEV_CREATE = 0x5501
UI_DEV_DESTROY = 0x5502

EV_SYN, EV_KEY, EV_ABS = 0x00, 0x01, 0x03
BTN_SOUTH, BTN_EAST, BTN_NORTH, BTN_WEST = 0x130, 0x131, 0x133, 0x134
BTN_TL, BTN_TR, BTN_SELECT, BTN_START = 0x136, 0x137, 0x13A, 0x13B
ABS_HAT0X, ABS_HAT0Y = 0x10, 0x11

#: Advertised in ascending keycode order, which is how udev assigns indices:
#: A=0 B=1 X=2 Y=3 L1=4 R1=5 select=6 start=7 -- the layout NAV_TOKEN_ACTIONS
#: is written against.
BUTTONS = [BTN_SOUTH, BTN_EAST, BTN_NORTH, BTN_WEST,
           BTN_TL, BTN_TR, BTN_SELECT, BTN_START]

PAD_NAME = "OpenEmux Test Pad"


def uinput_available():
    try:
        fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
    except OSError:
        return False
    os.close(fd)
    return True


class VirtualGamepad:
    def __init__(self, name=PAD_NAME):
        self.fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
        for bit in (EV_KEY, EV_ABS, EV_SYN):
            fcntl.ioctl(self.fd, UI_SET_EVBIT, bit)
        for code in BUTTONS:
            fcntl.ioctl(self.fd, UI_SET_KEYBIT, code)
        for code in (ABS_HAT0X, ABS_HAT0Y):
            fcntl.ioctl(self.fd, UI_SET_ABSBIT, code)
            # struct uinput_abs_setup { __u16 code; struct input_absinfo; }
            # The __u16 is padded to int alignment: 2 + 2 + 6*4 = 28 bytes.
            fcntl.ioctl(self.fd, UI_ABS_SETUP,
                        struct.pack("H2x6i", code, 0, -1, 1, 0, 0, 0))
        fcntl.ioctl(self.fd, UI_DEV_SETUP,
                    struct.pack("HHHH80sI", 0x03, 0x1234, 0x5678, 1, name.encode(), 0))
        fcntl.ioctl(self.fd, UI_DEV_CREATE)
        time.sleep(0.6)  # let udev create the device nodes

    def _emit(self, ev_type, code, value):
        os.write(self.fd, struct.pack("llHHi", 0, 0, ev_type, code, value))

    def _sync(self):
        self._emit(EV_SYN, 0, 0)

    def press(self, code, hold=0.05):
        self._emit(EV_KEY, code, 1)
        self._sync()
        time.sleep(hold)
        self._emit(EV_KEY, code, 0)
        self._sync()
        time.sleep(0.05)

    def hat(self, code, value, hold=0.05):
        self._emit(EV_ABS, code, value)
        self._sync()
        time.sleep(hold)
        self._emit(EV_ABS, code, 0)
        self._sync()
        time.sleep(0.05)

    def hold(self, code, value):
        self._emit(EV_ABS, code, value)
        self._sync()

    def close(self):
        try:
            fcntl.ioctl(self.fd, UI_DEV_DESTROY)
        except OSError:
            pass
        os.close(self.fd)


@unittest.skipUnless(uinput_available(), "/dev/uinput is not writable here")
class GamepadNavigatorDeviceTests(unittest.TestCase):
    def setUp(self):
        self.pad = VirtualGamepad()
        self.actions = []
        self.connected = []
        self.nav = GamepadNavigator(
            on_action=self.actions.append,
            on_connected=self.connected.append,
        )
        self.nav.start()
        time.sleep(1.5)  # discovery rescans about once a second

    def tearDown(self):
        self.nav.stop()
        self.pad.close()

    def _last_action(self, settle=0.35):
        time.sleep(settle)
        return self.actions[0] if self.actions else None

    def test_device_is_discovered(self):
        self.assertTrue(any(PAD_NAME in pad.name for pad in list_gamepads()))
        self.assertIn(PAD_NAME, self.connected)

    def test_face_buttons_map_to_actions(self):
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
                self.assertEqual(self._last_action(), expected)

    def test_shoulders_switch_console(self):
        for code, expected in ((BTN_TL, "prev_console"), (BTN_TR, "next_console")):
            with self.subTest(button=hex(code)):
                self.actions.clear()
                self.pad.press(code)
                self.assertEqual(self._last_action(), expected)

    def test_dpad_maps_to_directions(self):
        for code, value, expected in (
            (ABS_HAT0Y, -1, "up"),
            (ABS_HAT0Y, 1, "down"),
            (ABS_HAT0X, -1, "left"),
            (ABS_HAT0X, 1, "right"),
        ):
            with self.subTest(axis=hex(code), value=value):
                self.actions.clear()
                self.pad.hat(code, value)
                self.assertEqual(self._last_action(), expected)

    def test_held_direction_repeats_then_stops_on_release(self):
        self.actions.clear()
        self.pad.hold(ABS_HAT0Y, 1)
        time.sleep(1.2)
        self.pad.hold(ABS_HAT0Y, 0)
        time.sleep(0.3)
        repeats = list(self.actions)
        self.assertGreaterEqual(len(repeats), 4, f"expected auto-repeat, got {repeats}")
        self.assertTrue(all(action == "down" for action in repeats), repeats)

        self.actions.clear()
        time.sleep(0.6)
        self.assertEqual(self.actions, [], "repeat kept firing after release")


@unittest.skipUnless(uinput_available(), "/dev/uinput is not writable here")
class SuspendedNavigatorTests(unittest.TestCase):
    def test_suspended_navigator_drops_input(self):
        """While a game is running the pad belongs to RetroArch, not the UI."""
        pad = VirtualGamepad()
        actions = []
        nav = GamepadNavigator(on_action=actions.append, should_suspend=lambda: True)
        nav.start()
        try:
            time.sleep(1.5)
            pad.press(BTN_SOUTH)
            time.sleep(0.4)
            self.assertEqual(actions, [])
        finally:
            nav.stop()
            pad.close()


if __name__ == "__main__":
    unittest.main()
