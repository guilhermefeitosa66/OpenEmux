"""Which controls of a pad are held, for the controller drawing (issue 816).

The capture reader answers "what was just pressed" once and stops. Lighting a
drawn button for as long as it is down needs the other half: releases, and a
reader that keeps going. This covers that half on both backends -- the evdev
reader with a pipe standing in for the device node, as
`tests/test_gamepad_capture.py` does, and the SDL one through the pump's own
listener call.
"""

import os
import struct
import unittest
from unittest import mock

from openemux.core import gamepad_backend as gb
from openemux.core import gamepad_reader
from openemux.core import gamepad_sdl as gs
from openemux.core.gamepad_reader import (
    EV_ABS,
    EV_KEY,
    INPUT_EVENT_FORMAT,
    JS_EVENT_AXIS,
    JS_EVENT_BUTTON,
    JS_EVENT_FORMAT,
    JS_EVENT_INIT,
    GamepadDevice,
    GamepadHeldReader,
    TokenMapper,
    joydev_transitions,
)
from tests.platform_marks import linux_only

ABS_HAT0X, ABS_HAT0Y = 0x10, 0x11


def _mapper():
    # Two buttons, two axes and one hat: the smallest pad that has them all.
    return TokenMapper([0x130, 0x131], [0x00, 0x01, ABS_HAT0X, ABS_HAT0Y])


class WhatAnEvdevEventPressesAndReleasesTests(unittest.TestCase):
    def test_a_button_goes_down_and_comes_up(self):
        mapper = _mapper()
        self.assertEqual(mapper.transitions_for_event(EV_KEY, 0x131, 1), [("1", True)])
        self.assertEqual(mapper.transitions_for_event(EV_KEY, 0x131, 0), [("1", False)])

    def test_autorepeat_and_keys_the_pad_does_not_have_change_nothing(self):
        mapper = _mapper()
        self.assertEqual(mapper.transitions_for_event(EV_KEY, 0x131, 2), [])
        self.assertEqual(mapper.transitions_for_event(EV_KEY, 0x1FF, 1), [])

    def test_a_hat_presses_one_side_and_lets_go_of_the_other(self):
        mapper = _mapper()
        self.assertEqual(
            mapper.transitions_for_event(EV_ABS, ABS_HAT0X, -1), [("h0left", True), ("h0right", False)]
        )
        self.assertEqual(
            mapper.transitions_for_event(EV_ABS, ABS_HAT0X, 1), [("h0left", False), ("h0right", True)]
        )
        self.assertEqual(
            mapper.transitions_for_event(EV_ABS, ABS_HAT0Y, 1), [("h0up", False), ("h0down", True)]
        )

    def test_a_hat_centring_lets_go_of_both(self):
        self.assertEqual(
            _mapper().transitions_for_event(EV_ABS, ABS_HAT0Y, 0), [("h0up", False), ("h0down", False)]
        )

    def test_an_axis_is_held_only_past_the_deadzone(self):
        mapper = _mapper()
        self.assertEqual(mapper.transitions_for_event(EV_ABS, 0x01, 32767), [("-1", False), ("+1", True)])
        self.assertEqual(mapper.transitions_for_event(EV_ABS, 0x01, -32768), [("-1", True), ("+1", False)])
        self.assertEqual(mapper.transitions_for_event(EV_ABS, 0x01, 900), [("-1", False), ("+1", False)])

    def test_an_axis_the_pad_does_not_have_and_other_event_types_change_nothing(self):
        mapper = _mapper()
        self.assertEqual(mapper.transitions_for_event(EV_ABS, 0x05, 32767), [])
        self.assertEqual(mapper.transitions_for_event(0x04, 0x04, 1), [])


class WhatALegacyJoydevEventPressesAndReleasesTests(unittest.TestCase):
    def test_a_button_goes_down_and_comes_up(self):
        self.assertEqual(joydev_transitions(0, 1, JS_EVENT_BUTTON, 3), [("3", True)])
        self.assertEqual(joydev_transitions(0, 0, JS_EVENT_BUTTON, 3), [("3", False)])

    def test_the_start_up_state_counts(self):
        # The capture reader skips it (it is not a press); a reader of what is
        # held starts from it.
        self.assertEqual(joydev_transitions(0, 1, JS_EVENT_BUTTON | JS_EVENT_INIT, 0), [("0", True)])

    def test_an_axis_is_held_only_past_the_deadzone(self):
        self.assertEqual(joydev_transitions(0, 32767, JS_EVENT_AXIS, 1), [("-1", False), ("+1", True)])
        self.assertEqual(joydev_transitions(0, -32767, JS_EVENT_AXIS, 1), [("-1", True), ("+1", False)])
        self.assertEqual(joydev_transitions(0, 100, JS_EVENT_AXIS, 1), [("-1", False), ("+1", False)])

    def test_an_event_kind_joydev_does_not_define_changes_nothing(self):
        self.assertEqual(joydev_transitions(0, 1, 0x04, 0), [])


def _input_event(ev_type, code, value):
    return struct.pack(INPUT_EVENT_FORMAT, 0, 0, ev_type, code, value)


def _js_event(ev_type, number, value):
    return struct.pack(JS_EVENT_FORMAT, 0, value, ev_type, number)


@linux_only("struct input_event and struct js_event are the kernel ABI")
class TheEvdevHeldReaderTests(unittest.TestCase):
    """A reader whose device node is a pipe the test writes into."""

    def setUp(self):
        self.changes = []
        self.errors = []
        self.read_fd, self.write_fd = os.pipe()
        os.set_blocking(self.read_fd, False)
        self.addCleanup(self._close)
        self.reader = GamepadHeldReader(on_change=self.changes.append, on_error=self.errors.append)
        for target, attribute, value in (
            (gamepad_reader.os, "open", self.read_fd),
            (gamepad_reader, "_read_axis_ranges", {}),
        ):
            patch = mock.patch.object(target, attribute, return_value=value)
            patch.start()
            self.addCleanup(patch.stop)

    def _close(self):
        for fd in (self.read_fd, self.write_fd):
            try:
                os.close(fd)
            except OSError:
                pass

    def _device(self):
        return GamepadDevice(
            name="Wireless Controller", event_path="/dev/input/event9", js_path="/dev/input/js0",
            key_codes=[0x130, 0x131], abs_codes=[0x00, 0x01, ABS_HAT0X],
        )

    def _read(self, *events, legacy=False):
        # Everything is queued before the read starts, so the drain that
        # throws stale events away has to be out of the way; the pipe's end
        # of file is what ends the read.
        os.write(self.write_fd, b"".join(events))
        os.close(self.write_fd)
        with mock.patch.object(gamepad_reader, "_drain"):
            if legacy:
                self.reader._read_joydev(self._device())
            else:
                self.reader._read_evdev(self._device())

    def test_it_keeps_reading_and_reports_every_change(self):
        self._read(
            _input_event(EV_KEY, 0x131, 1),
            _input_event(EV_KEY, 0x130, 1),
            _input_event(EV_KEY, 0x131, 0),
            _input_event(EV_KEY, 0x130, 0),
        )
        self.assertEqual(
            self.changes,
            [frozenset({"1"}), frozenset({"0", "1"}), frozenset({"0"}), frozenset()],
        )
        self.assertEqual(self.errors, [])

    def test_an_event_that_changes_nothing_is_not_reported(self):
        self._read(
            _input_event(EV_KEY, 0x131, 1),
            _input_event(EV_KEY, 0x131, 2),   # autorepeat
            _input_event(EV_KEY, 0x130, 0),   # a release of something not held
            _input_event(EV_ABS, 0x00, 300),  # inside the deadzone
        )
        self.assertEqual(self.changes, [frozenset({"1"})])

    def test_a_hat_swinging_straight_across_is_a_change(self):
        # Left to right with no centre in between: one let go, one pressed,
        # the same number held.
        self._read(_input_event(EV_ABS, ABS_HAT0X, -1), _input_event(EV_ABS, ABS_HAT0X, 1))
        self.assertEqual(self.changes, [frozenset({"h0left"}), frozenset({"h0right"})])

    def test_nothing_is_reported_once_it_was_stopped(self):
        # stop() sets the flag from another thread while an event is in hand.
        self.reader._cancel.set()
        self.reader._feed([("1", True)])
        self.assertEqual(self.changes, [])

    def test_the_legacy_api_reports_the_same_way(self):
        self._read(
            _js_event(JS_EVENT_BUTTON, 2, 1),
            _js_event(JS_EVENT_AXIS, 0, -32767),
            _js_event(JS_EVENT_BUTTON, 2, 0),
            legacy=True,
        )
        self.assertEqual(self.changes, [frozenset({"2"}), frozenset({"2", "-0"}), frozenset({"-0"})])

    def test_it_runs_on_a_thread_named_for_what_it_does(self):
        self.assertEqual(GamepadHeldReader.THREAD_NAME, "gamepad-held")
        with mock.patch.object(gamepad_reader.threading, "Thread") as thread:
            self.reader.start()
        self.assertEqual(thread.call_args.kwargs["name"], "gamepad-held")

    def test_no_pad_is_an_error_not_a_change(self):
        with mock.patch.object(gamepad_reader, "list_gamepads", return_value=[]):
            self.reader._run()
        self.assertEqual(self.errors, ["no_gamepad"])
        self.assertEqual(self.changes, [])


class TheSdlHeldReaderTests(unittest.TestCase):
    def setUp(self):
        self.changes = []
        self.pump = mock.Mock()
        self.pads = [gs.SdlPadState("Pad A", instance_id=1), gs.SdlPadState("Pad B", instance_id=2)]
        self.pump.connected_pads.return_value = self.pads

    def _reader(self, device=None):
        return gs.SdlHeldReader(on_change=self.changes.append, device=device, pump=self.pump)

    def test_presses_and_releases_keep_the_set(self):
        reader = self._reader()
        reader.on_transition(self.pads[0], "5", True)
        reader.on_transition(self.pads[0], "h0up", True)
        reader.on_transition(self.pads[0], "5", False)
        self.assertEqual(self.changes, [frozenset({"5"}), frozenset({"5", "h0up"}), frozenset({"h0up"})])

    def test_a_transition_that_changes_nothing_is_not_reported(self):
        reader = self._reader()
        reader.on_transition(self.pads[0], "5", True)
        reader.on_transition(self.pads[0], "5", True)
        reader.on_transition(self.pads[0], "9", False)
        self.assertEqual(self.changes, [frozenset({"5"})])

    def test_a_port_listens_only_on_its_own_pad(self):
        reader = self._reader(gs.SdlGamepadDevice("Pad B", 1, instance_id=2))
        reader.on_transition(self.pads[0], "5", True)
        self.assertEqual(self.changes, [])
        reader.on_transition(self.pads[1], "5", True)
        self.assertEqual(self.changes, [frozenset({"5"})])

    def test_nothing_is_reported_once_it_was_stopped(self):
        reader = self._reader()
        reader.stop()
        reader.on_transition(self.pads[0], "5", True)
        self.assertEqual(self.changes, [])

    def test_it_answers_the_calls_the_capture_reader_answers(self):
        reader = self._reader()
        self.assertFalse(reader.uses_legacy_api)
        self.assertFalse(reader.cancelled)


class TheBackendBuildsTheRightOneTests(unittest.TestCase):
    def test_evdev_on_linux_and_sdl_on_windows(self):
        with mock.patch.object(gb, "backend_name", lambda: gb.EVDEV):
            self.assertIsInstance(gb.make_held_reader(lambda tokens: None), GamepadHeldReader)
        with mock.patch.object(gb, "backend_name", lambda: gb.SDL2):
            self.assertIsInstance(gb.make_held_reader(lambda tokens: None), gs.SdlHeldReader)

    def test_both_answer_start_and_stop(self):
        for cls in (GamepadHeldReader, gs.SdlHeldReader):
            for name in ("start", "stop"):
                self.assertTrue(callable(getattr(cls, name)), (cls.__name__, name))


if __name__ == "__main__":
    unittest.main()
