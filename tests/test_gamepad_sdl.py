"""The SDL2 gamepad backend (issue #118).

Every test here runs on Linux against a fake SDL: the point of the backend is
that it produces the *same* binding tokens the evdev reader does, and that is a
property of the decoding, not of the machine. A real controller is still needed
once -- see RT-118-a in the regression test book -- but nothing below depends on
one, so the numbering stays covered on every push.
"""

import struct
import threading
import time
import unittest
from collections import deque

from openemux.core import gamepad_sdl as gs
from openemux.core.gamepad_reader import GamepadError


# ----- raw SDL_Event builders ------------------------------------------------
def _pad(raw):
    return raw + b"\x00" * (gs.SDL_EVENT_SIZE - len(raw))


def button_event(kind, which, button, state):
    return _pad(struct.pack("=IIiBBBB", kind, 0, which, button, state, 0, 0))


def axis_event(which, axis, value):
    return _pad(struct.pack("=IIiBBBBhH", gs.SDL_JOYAXISMOTION, 0, which,
                            axis, 0, 0, 0, value, 0))


def hat_event(which, hat, value):
    return _pad(struct.pack("=IIiBBBB", gs.SDL_JOYHATMOTION, 0, which, hat, value, 0, 0))


def device_event(kind, which):
    return _pad(struct.pack("=IIi", kind, 0, which))


# ----- a fake SDL2 -----------------------------------------------------------
class FakeJoystick:
    def __init__(self, name="Fake Pad", instance_id=0, axes=()):
        self.name = name
        self.instance_id = instance_id
        self.axes = list(axes)


class FakeSdl:
    """The six calls :class:`SdlJoystickPump` makes, and nothing else."""

    def __init__(self, joysticks=(), events=()):
        self.joysticks = list(joysticks)
        self.events = deque(events)
        self.initialised = False
        self.quit_called = False
        self.closed = []
        self._lock = threading.Lock()

    def push(self, *events):
        with self._lock:
            self.events.extend(events)

    # -- SdlLibrary's surface
    def init(self):
        self.initialised = True

    def quit(self):
        self.quit_called = True

    def error(self):
        return "fake sdl"

    def poll_event(self):
        with self._lock:
            return self.events.popleft() if self.events else None

    def num_joysticks(self):
        return len(self.joysticks)

    def name_for_index(self, index):
        return self.joysticks[index].name

    def open(self, index):
        if 0 <= index < len(self.joysticks):
            return self.joysticks[index]
        return None

    def close(self, handle):
        self.closed.append(handle)

    def instance_id(self, handle):
        return handle.instance_id

    def name(self, handle):
        return handle.name

    def num_axes(self, handle):
        return len(handle.axes)

    def axis(self, handle, index):
        return handle.axes[index]


class Recorder:
    """A pump listener that keeps what it was told."""

    def __init__(self):
        self.transitions = []
        self.connected = []
        self.disconnected = 0

    def on_transition(self, pad, token, pressed):
        self.transitions.append((token, pressed))

    def on_connected(self, name):
        self.connected.append(name)

    def on_disconnected(self):
        self.disconnected += 1


def wait_for(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return predicate()


# ----- token decoding --------------------------------------------------------
class HatTokenTests(unittest.TestCase):
    def test_each_direction_has_the_evdev_spelling(self):
        self.assertEqual(gs.hat_direction_tokens(0, gs.SDL_HAT_UP), {"h0up"})
        self.assertEqual(gs.hat_direction_tokens(0, gs.SDL_HAT_DOWN), {"h0down"})
        self.assertEqual(gs.hat_direction_tokens(0, gs.SDL_HAT_LEFT), {"h0left"})
        self.assertEqual(gs.hat_direction_tokens(0, gs.SDL_HAT_RIGHT), {"h0right"})

    def test_a_diagonal_is_two_tokens(self):
        self.assertEqual(
            gs.hat_direction_tokens(0, gs.SDL_HAT_UP | gs.SDL_HAT_RIGHT),
            {"h0up", "h0right"},
        )

    def test_centred_is_nothing(self):
        self.assertEqual(gs.hat_direction_tokens(0, gs.SDL_HAT_CENTERED), set())

    def test_the_hat_number_is_carried(self):
        self.assertEqual(gs.hat_direction_tokens(2, gs.SDL_HAT_LEFT), {"h2left"})


class AxisTokenTests(unittest.TestCase):
    def test_inside_the_deadzone_is_no_press(self):
        self.assertIsNone(gs.axis_token(1, 0))
        self.assertIsNone(gs.axis_token(1, 16000))
        self.assertIsNone(gs.axis_token(1, -16000))

    def test_past_the_deadzone_carries_the_sign(self):
        self.assertEqual(gs.axis_token(1, 32000), "+1")
        self.assertEqual(gs.axis_token(1, -32000), "-1")

    def test_the_threshold_is_half_the_signed_range(self):
        # The same fraction the evdev reader uses, so a stick pushed the same
        # distance binds the same token on either backend.
        self.assertEqual(gs.AXIS_THRESHOLD, 16384.0)


class PadStateTests(unittest.TestCase):
    def setUp(self):
        self.pad = gs.SdlPadState("Fake Pad", 0)

    def test_a_button_press_and_release_are_one_transition_each(self):
        self.assertEqual(self.pad.feed_button(3, True), [("3", True)])
        self.assertEqual(self.pad.feed_button(3, False), [("3", False)])

    def test_a_repeated_press_is_not_reported_twice(self):
        self.pad.feed_button(3, True)
        self.assertEqual(self.pad.feed_button(3, True), [])

    def test_a_release_with_nothing_held_is_nothing(self):
        self.assertEqual(self.pad.feed_button(3, False), [])

    def test_an_axis_crossing_the_deadzone_presses_and_releases(self):
        self.assertEqual(self.pad.feed_axis(1, -32000), [("-1", True)])
        self.assertEqual(self.pad.feed_axis(1, 0), [("-1", False)])

    def test_an_axis_swinging_across_centre_releases_before_it_presses(self):
        self.pad.feed_axis(0, 32000)
        self.assertEqual(self.pad.feed_axis(0, -32000), [("+0", False), ("-0", True)])

    def test_movement_inside_the_deadzone_says_nothing(self):
        self.assertEqual(self.pad.feed_axis(0, 100), [])
        self.assertEqual(self.pad.feed_axis(0, -900), [])

    def test_a_resting_trigger_is_seeded_not_reported(self):
        # SDL rests an analogue trigger at -32768, which is well past the
        # deadzone. Read as an event it would look like a control held down
        # from the moment the pad opened, and the navigator would treat the
        # first real pull as a *release*.
        self.pad.seed_axis(2, -32768)
        self.assertEqual(self.pad.feed_axis(2, -32768), [])
        self.assertEqual(self.pad.feed_axis(2, 32000), [("-2", False), ("+2", True)])

    def test_a_hat_diagonal_then_a_single_direction(self):
        self.assertEqual(
            self.pad.feed_hat(0, gs.SDL_HAT_UP | gs.SDL_HAT_RIGHT),
            [("h0right", True), ("h0up", True)],
        )
        self.assertEqual(self.pad.feed_hat(0, gs.SDL_HAT_UP), [("h0right", False)])
        self.assertEqual(self.pad.feed_hat(0, gs.SDL_HAT_CENTERED), [("h0up", False)])

    def test_release_all_lets_go_of_everything_held(self):
        self.pad.feed_button(1, True)
        self.pad.feed_hat(0, gs.SDL_HAT_LEFT)
        self.pad.feed_axis(0, 32000)
        self.assertEqual(
            sorted(self.pad.release_all()),
            [("+0", False), ("1", False), ("h0left", False)],
        )
        self.assertEqual(self.pad.release_all(), [])


class EventDecodingTests(unittest.TestCase):
    def test_the_header_fields_are_read_at_the_right_offsets(self):
        raw = button_event(gs.SDL_JOYBUTTONDOWN, 7, 4, 1)
        self.assertEqual(gs.event_type(raw), gs.SDL_JOYBUTTONDOWN)
        self.assertEqual(gs.event_which(raw), 7)

    def test_an_event_is_the_size_sdl_declares(self):
        self.assertEqual(len(axis_event(0, 1, 100)), 56)


# ----- the pump --------------------------------------------------------------
class PumpTests(unittest.TestCase):
    def setUp(self):
        self.joystick = FakeJoystick(name="Fake Pad", instance_id=11, axes=[0, 0, -32768])
        self.sdl = FakeSdl(joysticks=[self.joystick])
        self.pump = gs.SdlJoystickPump(load=lambda: self.sdl)
        self.recorder = Recorder()

    def tearDown(self):
        self.pump.unsubscribe(self.recorder)

    def _subscribe_with_pad(self, listener=None):
        listener = listener or self.recorder
        self.sdl.push(device_event(gs.SDL_JOYDEVICEADDED, 0))
        self.pump.subscribe(listener)
        self.assertTrue(wait_for(lambda: self.pump.connected_pads()))
        return listener

    def test_a_pad_present_at_start_is_opened_and_announced(self):
        self._subscribe_with_pad()
        self.assertTrue(wait_for(lambda: self.recorder.connected == ["Fake Pad"]))

    def test_a_button_becomes_the_same_token_evdev_would_emit(self):
        self._subscribe_with_pad()
        self.sdl.push(button_event(gs.SDL_JOYBUTTONDOWN, 11, 3, 1),
                      button_event(gs.SDL_JOYBUTTONUP, 11, 3, 0))
        self.assertTrue(wait_for(lambda: len(self.recorder.transitions) == 2))
        self.assertEqual(self.recorder.transitions, [("3", True), ("3", False)])

    def test_a_hat_becomes_a_direction_token(self):
        self._subscribe_with_pad()
        self.sdl.push(hat_event(11, 0, gs.SDL_HAT_UP))
        self.assertTrue(wait_for(lambda: self.recorder.transitions))
        self.assertEqual(self.recorder.transitions[0], ("h0up", True))

    def test_the_resting_trigger_is_seeded_from_the_open_joystick(self):
        # Axis 2 rests at -32768 on the fake pad, and opening it must not look
        # like the user is holding the left trigger.
        self._subscribe_with_pad()
        self.sdl.push(button_event(gs.SDL_JOYBUTTONDOWN, 11, 0, 1))
        self.assertTrue(wait_for(lambda: self.recorder.transitions))
        self.assertEqual(self.recorder.transitions, [("0", True)])

    def test_unplugging_releases_what_was_held(self):
        self._subscribe_with_pad()
        self.sdl.push(hat_event(11, 0, gs.SDL_HAT_LEFT))
        self.assertTrue(wait_for(lambda: self.recorder.transitions))
        self.sdl.push(device_event(gs.SDL_JOYDEVICEREMOVED, 11))
        self.assertTrue(wait_for(lambda: self.recorder.disconnected == 1))
        # Without this the direction would repeat forever: the navigator never
        # sees the release that would stop it.
        self.assertIn(("h0left", False), self.recorder.transitions)

    def test_every_listener_sees_every_event(self):
        # The reason there is a pump at all: SDL has one event queue per
        # process, so a navigator and a capture reader polling it separately
        # would steal each other's presses.
        second = Recorder()
        self._subscribe_with_pad()
        self.pump.subscribe(second)
        self.addCleanup(self.pump.unsubscribe, second)
        self.sdl.push(button_event(gs.SDL_JOYBUTTONDOWN, 11, 2, 1))
        self.assertTrue(wait_for(lambda: self.recorder.transitions and second.transitions))
        self.assertEqual(second.transitions, [("2", True)])

    def test_a_listener_joining_a_running_pump_is_told_about_the_pad(self):
        self._subscribe_with_pad()
        self.assertTrue(wait_for(lambda: self.recorder.connected))
        second = Recorder()
        self.pump.subscribe(second)
        self.addCleanup(self.pump.unsubscribe, second)
        self.assertEqual(second.connected, ["Fake Pad"])

    def test_sdl_is_shut_down_when_the_last_listener_leaves(self):
        self._subscribe_with_pad()
        self.pump.unsubscribe(self.recorder)
        self.assertTrue(wait_for(lambda: self.sdl.quit_called))
        self.assertIn(self.joystick, self.sdl.closed)

    def test_a_raising_listener_does_not_stop_the_pump(self):
        class Angry:
            def on_transition(self, pad, token, pressed):
                raise RuntimeError("boom")

        angry = Angry()
        self.pump.subscribe(angry)
        self.addCleanup(self.pump.unsubscribe, angry)
        self._subscribe_with_pad()
        with self.assertLogs("openemux.core.gamepad_sdl", level="WARNING"):
            self.sdl.push(button_event(gs.SDL_JOYBUTTONDOWN, 11, 1, 1))
            self.assertTrue(wait_for(lambda: self.recorder.transitions))
        self.assertEqual(self.recorder.transitions, [("1", True)])

    def test_a_missing_sdl_is_reported_to_the_subscriber(self):
        def _explode():
            raise gs.SdlUnavailable("SDL2.dll not found")

        pump = gs.SdlJoystickPump(load=_explode)
        with self.assertLogs("openemux.core.gamepad_sdl", level="WARNING"):
            with self.assertRaises(GamepadError) as caught:
                pump.subscribe(Recorder())
        self.assertEqual(caught.exception.reason, "no_gamepad")


class LoadTests(unittest.TestCase):
    def test_every_candidate_name_is_tried_before_giving_up(self):
        tried = []

        def _loader(name):
            tried.append(name)
            raise OSError("nope")

        with self.assertRaises(gs.SdlUnavailable):
            gs.load_sdl2(loader=_loader, names=("SDL2.dll", "libSDL2-2.0.so.0"))
        self.assertEqual(tried[:2], ["SDL2.dll", "libSDL2-2.0.so.0"])

    def test_the_failure_is_a_gamepad_error_the_ui_already_handles(self):
        with self.assertRaises(GamepadError) as caught:
            gs.load_sdl2(loader=lambda name: (_ for _ in ()).throw(OSError("nope")),
                         names=("nothing-here.so",))
        self.assertEqual(caught.exception.reason, "no_gamepad")


# ----- the readers -----------------------------------------------------------
class CaptureReaderTests(unittest.TestCase):
    def setUp(self):
        self.sdl = FakeSdl(joysticks=[
            FakeJoystick(name="Pad One", instance_id=11),
            FakeJoystick(name="Pad Two", instance_id=22),
        ])
        self.pump = gs.SdlJoystickPump(load=lambda: self.sdl)

    def _reader(self, device=None):
        self.tokens = []
        self.errors = []
        reader = gs.SdlCaptureReader(
            on_token=self.tokens.append,
            on_error=self.errors.append,
            device=device,
            pump=self.pump,
        )
        self.addCleanup(reader.stop)
        return reader

    def test_the_first_press_is_captured_and_the_reader_stops(self):
        self.sdl.push(device_event(gs.SDL_JOYDEVICEADDED, 0))
        reader = self._reader()
        reader.start()
        self.assertTrue(wait_for(lambda: self.pump.connected_pads()))
        self.sdl.push(button_event(gs.SDL_JOYBUTTONDOWN, 11, 5, 1),
                      button_event(gs.SDL_JOYBUTTONDOWN, 11, 6, 1))
        self.assertTrue(wait_for(lambda: self.tokens))
        self.assertEqual(self.tokens, ["5"])
        self.assertTrue(reader.cancelled)

    def test_a_release_is_not_a_capture(self):
        self.sdl.push(device_event(gs.SDL_JOYDEVICEADDED, 0))
        reader = self._reader()
        reader.start()
        self.assertTrue(wait_for(lambda: self.pump.connected_pads()))
        self.sdl.push(button_event(gs.SDL_JOYBUTTONUP, 11, 5, 0))
        time.sleep(0.05)
        self.assertEqual(self.tokens, [])

    def test_a_port_listens_only_on_its_own_pad(self):
        self.sdl.push(device_event(gs.SDL_JOYDEVICEADDED, 0),
                      device_event(gs.SDL_JOYDEVICEADDED, 1))
        reader = self._reader(device=gs.SdlGamepadDevice("Pad Two", 1, instance_id=22))
        reader.start()
        self.assertTrue(wait_for(lambda: len(self.pump.connected_pads()) == 2))
        self.sdl.push(button_event(gs.SDL_JOYBUTTONDOWN, 11, 1, 1))
        time.sleep(0.05)
        self.assertEqual(self.tokens, [], "port 2 must not bind port 1's button")
        self.sdl.push(button_event(gs.SDL_JOYBUTTONDOWN, 22, 4, 1))
        self.assertTrue(wait_for(lambda: self.tokens))
        self.assertEqual(self.tokens, ["4"])

    def test_nothing_connected_is_reported_as_no_gamepad(self):
        self.sdl.joysticks = []
        reader = self._reader()
        reader.SETTLE = 0.05
        reader.start()
        self.assertTrue(wait_for(lambda: self.errors))
        self.assertEqual(self.errors, ["no_gamepad"])

    def test_a_missing_sdl_is_reported_as_no_gamepad(self):
        pump = gs.SdlJoystickPump(load=lambda: (_ for _ in ()).throw(
            gs.SdlUnavailable("SDL2.dll not found")))
        errors = []
        reader = gs.SdlCaptureReader(on_token=lambda t: None, on_error=errors.append,
                                     pump=pump)
        self.addCleanup(reader.stop)
        with self.assertLogs("openemux.core.gamepad_sdl", level="WARNING"):
            reader.start()
            self.assertTrue(wait_for(lambda: errors))
        self.assertEqual(errors, ["no_gamepad"])

    def test_it_answers_the_legacy_api_question_the_ui_asks(self):
        # The evdev reader can fall back to joydev, whose numbering the UI
        # warns about. SDL has no such fallback; the attribute exists so the
        # dialog can ask either backend the same thing.
        self.assertFalse(self._reader().uses_legacy_api)


class NavigatorTests(unittest.TestCase):
    def setUp(self):
        self.sdl = FakeSdl(joysticks=[FakeJoystick(name="Pad One", instance_id=11)])
        self.pump = gs.SdlJoystickPump(load=lambda: self.sdl)
        self.actions = []
        self.connected = []
        self.suspended = [False]
        self.nav = gs.SdlNavigator(
            self.actions.append,
            on_connected=self.connected.append,
            should_suspend=lambda: self.suspended[0],
            pump=self.pump,
        )
        self.addCleanup(self.nav.stop)

    def _start_with_pad(self):
        self.sdl.push(device_event(gs.SDL_JOYDEVICEADDED, 0))
        self.nav.start()
        self.assertTrue(wait_for(lambda: self.pump.connected_pads()))

    def test_a_press_becomes_the_ui_action_the_token_maps_to(self):
        self._start_with_pad()
        self.sdl.push(hat_event(11, 0, gs.SDL_HAT_DOWN))
        self.assertTrue(wait_for(lambda: self.actions))
        self.assertEqual(self.actions[0], "down")

    def test_the_connect_callback_names_the_pad(self):
        self._start_with_pad()
        self.assertTrue(wait_for(lambda: self.connected == ["Pad One"]))

    def test_nothing_is_acted_on_while_suspended(self):
        self._start_with_pad()
        self.assertTrue(wait_for(lambda: self.connected))
        self.suspended[0] = True
        self.sdl.push(button_event(gs.SDL_JOYBUTTONDOWN, 11, 4, 1))
        time.sleep(0.1)
        self.assertEqual(self.actions, [])

    def test_a_held_direction_repeats(self):
        self._start_with_pad()
        self.sdl.push(hat_event(11, 0, gs.SDL_HAT_RIGHT))
        self.assertTrue(wait_for(lambda: len(self.actions) >= 3, timeout=3.0))
        self.assertEqual(set(self.actions), {"right"})

    def test_letting_go_stops_the_repeat(self):
        self._start_with_pad()
        self.sdl.push(hat_event(11, 0, gs.SDL_HAT_RIGHT))
        self.assertTrue(wait_for(lambda: self.actions))
        self.sdl.push(hat_event(11, 0, gs.SDL_HAT_CENTERED))
        self.assertTrue(wait_for(lambda: not self.nav._queue))
        time.sleep(0.1)
        settled = len(self.actions)
        time.sleep(0.6)
        self.assertEqual(len(self.actions), settled)

    def test_a_missing_sdl_ends_the_thread_quietly(self):
        pump = gs.SdlJoystickPump(load=lambda: (_ for _ in ()).throw(
            gs.SdlUnavailable("SDL2.dll not found")))
        nav = gs.SdlNavigator(lambda action: None, pump=pump)
        with self.assertLogs("openemux.core.gamepad_sdl", level="WARNING") as logs:
            nav.start()
            nav.stop(join_timeout=5.0)  # returns once the reader thread is done
        self.assertTrue(any("SDL2.dll not found" in line for line in logs.output))
        self.assertEqual(self.actions, [])


if __name__ == "__main__":
    unittest.main()
