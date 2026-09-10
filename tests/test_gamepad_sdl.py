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
import unittest.mock
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

    def test_unplugging_a_pad_mid_direction_stops_the_repeat(self):
        # The pump releases what was held before announcing the disconnect, and
        # those releases are what stop the auto-repeat. Dropping them left the
        # grid scrolling on its own after the pad was unplugged mid-push.
        self._start_with_pad()
        self.sdl.push(hat_event(11, 0, gs.SDL_HAT_RIGHT))
        self.assertTrue(wait_for(lambda: self.actions))
        self.sdl.push(device_event(gs.SDL_JOYDEVICEREMOVED, 11))
        self.assertTrue(wait_for(lambda: not self.pump.connected_pads()))
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


class _CtypesFunction:
    """One SDL entry point: takes the ctypes annotations and answers a value."""

    def __init__(self, result=0, record=None, name=""):
        self.argtypes = None
        self.restype = None
        self._result = result
        self._record = record
        self._name = name

    def __call__(self, *args):
        if self._record is not None:
            self._record.append((self._name, args))
        return self._result(*args) if callable(self._result) else self._result


class _CtypesHandle:
    """A stand-in for the loaded SDL2 shared object."""

    def __init__(self, results=None, record=None):
        self._results = results or {}
        self._record = record if record is not None else []
        self._functions = {}

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        if name not in self._functions:
            self._functions[name] = _CtypesFunction(
                self._results.get(name, 0), self._record, name
            )
        return self._functions[name]


class TheSdlEntryPointsTests(unittest.TestCase):
    """The ctypes wrapper: six methods a fake can stand in for elsewhere."""

    def _library(self, **results):
        self.record = []
        return gs.SdlLibrary(_CtypesHandle(results, self.record))

    def test_initialising_sets_the_two_hints_and_enables_events(self):
        library = self._library()
        library.init()
        called = [name for name, _args in self.record]
        self.assertIn("SDL_SetHint", called)
        self.assertIn("SDL_JoystickEventState", called)

    def test_an_sdl_that_will_not_initialise_says_why(self):
        library = self._library(SDL_Init=1, SDL_GetError=b"no audio device")
        with self.assertRaises(gs.SdlUnavailable) as raised:
            library.init()
        self.assertIn("no audio device", str(raised.exception))

    def test_quitting_reaches_sdl(self):
        library = self._library()
        library.quit()
        self.assertIn("SDL_Quit", [name for name, _args in self.record])

    def test_an_error_that_is_not_set_reads_as_empty(self):
        self.assertEqual(self._library(SDL_GetError=None).error(), "")

    def test_an_empty_event_queue_yields_no_event(self):
        self.assertIsNone(self._library(SDL_PollEvent=0).poll_event())

    def test_a_queued_event_comes_back_as_raw_bytes(self):
        library = self._library(SDL_PollEvent=1)
        raw = library.poll_event()
        self.assertEqual(len(raw), gs.SDL_EVENT_SIZE)

    def test_the_connected_count_is_reported(self):
        self.assertEqual(self._library(SDL_NumJoysticks=3).num_joysticks(), 3)

    def test_a_pad_with_no_name_falls_back_to_a_generic_one(self):
        self.assertEqual(self._library(SDL_JoystickNameForIndex=None).name_for_index(0),
                         "Gamepad")
        self.assertEqual(self._library(SDL_JoystickName=b"").name(object()), "Gamepad")

    def test_a_pad_that_names_itself_keeps_its_name(self):
        library = self._library(SDL_JoystickNameForIndex=b"Wireless Controller")
        self.assertEqual(library.name_for_index(0), "Wireless Controller")

    def test_a_pad_that_will_not_open_yields_no_handle(self):
        self.assertIsNone(self._library(SDL_JoystickOpen=0).open(0))

    def test_a_pad_that_opens_yields_its_handle(self):
        self.assertEqual(self._library(SDL_JoystickOpen=1234).open(0), 1234)

    def test_closing_reaches_sdl(self):
        library = self._library()
        library.close(1234)
        self.assertIn("SDL_JoystickClose", [name for name, _args in self.record])

    def test_the_instance_id_and_the_axes_are_reported(self):
        library = self._library(
            SDL_JoystickInstanceID=7, SDL_JoystickNumAxes=6, SDL_JoystickGetAxis=-32000
        )
        self.assertEqual(library.instance_id(object()), 7)
        self.assertEqual(library.num_axes(object()), 6)
        self.assertEqual(library.axis(object(), 1), -32000)


class LoadingSdl2Tests(unittest.TestCase):
    def test_the_first_name_that_loads_wins(self):
        tried = []

        def _loader(name):
            tried.append(name)
            return _CtypesHandle()

        library = gs.load_sdl2(loader=_loader, names=["libSDL2.so.0", "SDL2.dll"])
        self.assertIsInstance(library, gs.SdlLibrary)
        self.assertEqual(tried, ["libSDL2.so.0"])

    def test_the_platform_search_is_the_last_resort(self):
        # A developer running the backend by hand may have a differently
        # versioned soname than the one the bundle ships.
        def _loader(name):
            if name == "found-by-the-platform":
                return _CtypesHandle()
            raise OSError(f"no {name}")

        with unittest.mock.patch.object(
            gs.ctypes.util, "find_library", return_value="found-by-the-platform"
        ):
            self.assertIsInstance(
                gs.load_sdl2(loader=_loader, names=["nope"]), gs.SdlLibrary
            )

    def test_a_platform_search_that_finds_an_unloadable_library_gives_up(self):
        def _loader(name):
            raise OSError(f"no {name}")

        with unittest.mock.patch.object(
            gs.ctypes.util, "find_library", return_value="broken"
        ):
            with self.assertRaises(gs.SdlUnavailable) as raised:
                gs.load_sdl2(loader=_loader, names=["nope"])
        self.assertIn("broken", str(raised.exception))

    def test_no_sdl_anywhere_names_everything_it_tried(self):
        def _loader(name):
            raise OSError(f"no {name}")

        with unittest.mock.patch.object(gs.ctypes.util, "find_library", return_value=None):
            with self.assertRaises(gs.SdlUnavailable) as raised:
                gs.load_sdl2(loader=_loader, names=["a", "b"])
        self.assertIn("a:", str(raised.exception))
        self.assertIn("b:", str(raised.exception))


class TheSharedPumpTests(unittest.TestCase):
    def test_it_can_be_dropped_between_tests(self):
        gs.reset_shared_pump()
        first = gs.shared_pump()
        self.assertIs(gs.shared_pump(), first)
        gs.reset_shared_pump()
        self.assertIsNot(gs.shared_pump(), first)
        gs.reset_shared_pump()


class ListingThePadsTests(unittest.TestCase):
    def test_sdl_that_is_missing_reports_no_pads_rather_than_raising(self):
        # A caller asking what is connected wants an answer; the reader that
        # follows reports the failure properly.
        pump = unittest.mock.Mock()
        pump.subscribe.side_effect = GamepadError("no_gamepad")
        with self.assertLogs("openemux.core.gamepad_sdl", level="WARNING"):
            self.assertEqual(gs.list_gamepads(pump=pump), [])

    def test_the_pads_come_back_in_the_order_sdl_announced_them(self):
        pads = [
            gs.SdlPadState("Pad A", instance_id=1),
            gs.SdlPadState("Pad B", instance_id=2),
        ]
        pump = unittest.mock.Mock()
        pump.connected_pads.return_value = pads
        devices = gs.list_gamepads(pump=pump, settle=0)
        self.assertEqual([device.name for device in devices], ["Pad A", "Pad B"])
        self.assertEqual([device.index for device in devices], [0, 1])
        pump.unsubscribe.assert_called_once()

    def test_a_cold_pump_is_given_its_settle_window_and_no_more(self):
        pump = unittest.mock.Mock()
        pump.connected_pads.return_value = []
        started = time.monotonic()
        self.assertEqual(gs.list_gamepads(pump=pump, settle=0.05), [])
        self.assertLess(time.monotonic() - started, 1.0)


class TheCaptureReaderLifecycleTests(unittest.TestCase):
    def test_a_second_start_does_not_add_a_second_thread(self):
        reader = gs.SdlCaptureReader(on_token=lambda _t: None, pump=unittest.mock.Mock())
        with unittest.mock.patch.object(gs.threading, "Thread") as thread:
            reader.start()
            reader.start()
        thread.assert_called_once()

    def test_the_first_press_is_the_only_one_reported(self):
        tokens = []
        reader = gs.SdlCaptureReader(on_token=tokens.append, pump=unittest.mock.Mock())
        reader._emit_token("3")
        reader._emit_token("4")
        self.assertEqual(tokens, ["3"])

    def test_an_error_after_a_press_is_not_reported(self):
        errors = []
        reader = gs.SdlCaptureReader(
            on_token=lambda _t: None, on_error=errors.append, pump=unittest.mock.Mock()
        )
        reader._emit_token("3")
        reader._emit_error("no_gamepad")
        self.assertEqual(errors, [])

    def test_a_reader_with_no_callbacks_at_all_is_harmless(self):
        reader = gs.SdlCaptureReader(on_token=None, pump=unittest.mock.Mock())
        reader._emit_token("3")
        reader = gs.SdlCaptureReader(on_token=None, pump=unittest.mock.Mock())
        reader._emit_error("no_gamepad")


class WhichPadTheCaptureListensToTests(unittest.TestCase):
    """Port N listens on the Nth pad, in the order SDL announced them."""

    def _reader(self, device):
        pump = unittest.mock.Mock()
        self.pads = [
            gs.SdlPadState("Pad A", instance_id=1),
            gs.SdlPadState("Pad B", instance_id=2),
        ]
        pump.connected_pads.return_value = self.pads
        return gs.SdlCaptureReader(on_token=lambda _t: None, device=device, pump=pump)

    def test_a_device_named_by_its_instance_matches_only_that_pad(self):
        reader = self._reader(gs.SdlGamepadDevice("Pad B", 1, instance_id=2))
        self.assertFalse(reader._matches(self.pads[0]))
        self.assertTrue(reader._matches(self.pads[1]))

    def test_a_device_named_by_its_index_matches_the_pad_in_that_slot(self):
        reader = self._reader(gs.SdlGamepadDevice("Pad B", 1))
        reader._device.instance_id = None
        self.assertTrue(reader._matches(self.pads[1]))
        self.assertFalse(reader._matches(self.pads[0]))

    def test_a_device_whose_instance_is_gone_falls_back_to_the_index(self):
        reader = self._reader(gs.SdlGamepadDevice("Pad B", 1, instance_id=99))
        self.assertTrue(reader._matches(self.pads[1]))

    def test_an_index_past_the_end_listens_to_whatever_is_there(self):
        reader = self._reader(gs.SdlGamepadDevice("Pad Z", 9))
        reader._device.instance_id = None
        self.assertTrue(reader._matches(self.pads[0]))


class ThePumpInternalsTests(unittest.TestCase):
    """The reader loop, driven in place rather than on its own thread."""

    def setUp(self):
        self.joystick = FakeJoystick(name="Pad", instance_id=11, axes=[0, 0])
        self.sdl = FakeSdl(joysticks=[self.joystick])
        self.pump = gs.SdlJoystickPump(load=lambda: self.sdl)
        self.recorder = Recorder()
        self.pump._listeners.append(self.recorder)

    def test_a_drain_with_nothing_queued_reports_that_it_idled(self):
        self.assertFalse(self.pump._drain(self.sdl))

    def test_a_drain_stops_as_soon_as_the_reader_is_cancelled(self):
        self.sdl.push(device_event(gs.SDL_JOYDEVICEADDED, 0))
        self.pump._cancel.set()
        self.assertFalse(self.pump._drain(self.sdl))

    def test_an_event_for_a_pad_that_is_not_open_is_dropped(self):
        self.pump._handle(self.sdl, button_event(gs.SDL_JOYBUTTONDOWN, 99, 3, 1))
        self.assertEqual(self.recorder.transitions, [])

    def test_an_axis_motion_reaches_the_pad_it_belongs_to(self):
        self.pump._open(self.sdl, 0)
        self.pump._handle(self.sdl, axis_event(11, 0, -32000))
        self.assertEqual(self.recorder.transitions, [("-0", True)])

    def test_a_hat_motion_reaches_it_too(self):
        self.pump._open(self.sdl, 0)
        self.pump._handle(self.sdl, hat_event(11, 0, gs.SDL_HAT_UP))
        self.assertEqual(self.recorder.transitions, [("h0up", True)])

    def test_a_button_press_reaches_it_too(self):
        self.pump._open(self.sdl, 0)
        self.pump._handle(self.sdl, button_event(gs.SDL_JOYBUTTONDOWN, 11, 3, 1))
        self.assertEqual(self.recorder.transitions, [("3", True)])

    def test_a_pad_sdl_will_not_open_is_reported_not_raised(self):
        with self.assertLogs("openemux.core.gamepad_sdl", level="WARNING"):
            self.pump._open(self.sdl, 99)
        self.assertEqual(self.pump.connected_pads(), [])

    def test_a_pad_sdl_announces_twice_is_only_opened_once(self):
        self.pump._open(self.sdl, 0)
        self.pump._open(self.sdl, 0)
        self.assertEqual(len(self.pump.connected_pads()), 1)
        self.assertEqual(self.sdl.closed, [self.joystick])

    def test_a_reader_that_dies_says_so_instead_of_vanishing(self):
        ready = threading.Event()
        with unittest.mock.patch.object(
            gs.SdlJoystickPump, "_drain", side_effect=RuntimeError("boom")
        ):
            with self.assertLogs("openemux.core.gamepad_sdl", level="WARNING"):
                self.pump._run(ready)
        self.assertTrue(self.sdl.quit_called)

    def test_a_teardown_that_cannot_quit_sdl_is_logged_not_raised(self):
        ready = threading.Event()
        self.pump._cancel.set()
        self.sdl.quit = unittest.mock.Mock(side_effect=RuntimeError("already gone"))
        with self.assertLogs("openemux.core.gamepad_sdl", level="DEBUG"):
            self.pump._run(ready)


class TheNavigatorLoopTests(unittest.TestCase):
    """The two branches the timing makes hard to reach from outside."""

    def setUp(self):
        self.pump = unittest.mock.Mock()
        self.pump.connected_pads.return_value = []
        self.actions = []
        self.suspended = [False]
        self.nav = gs.SdlNavigator(
            self.actions.append,
            should_suspend=lambda: self.suspended[0],
            pump=self.pump,
        )

    def _run_once(self):
        """Let the loop take exactly one turn."""
        calls = []

        def _wait(_timeout):
            calls.append(1)
            self.nav._cancel.set()
            return True

        with unittest.mock.patch.object(self.nav._cancel, "wait", _wait):
            self.nav._run()

    def test_a_game_starting_drops_whatever_the_pad_was_holding(self):
        # Nothing may "stick" across a game session.
        self.suspended[0] = True
        self.nav._queue.append(("down", True))
        self._run_once()
        self.assertEqual(list(self.nav._queue), [])
        self.assertEqual(self.actions, [])

    def test_a_long_press_becomes_a_hold_action(self):
        self.nav._queue.append(("confirm", True))

        def _wait(_timeout):
            self.nav._cancel.set()
            return True

        with unittest.mock.patch.object(gs.HoldClock, "due_actions", return_value=["confirm"]):
            with unittest.mock.patch.object(self.nav._cancel, "wait", _wait):
                self.nav._run()
        self.assertIn("confirm_hold", self.actions)

    def test_a_pump_that_cannot_start_says_so_and_the_loop_ends(self):
        self.pump.subscribe.side_effect = GamepadError("no_gamepad")
        with self.assertLogs("openemux.core.gamepad_sdl", level="WARNING"):
            self.nav._run()
        self.pump.unsubscribe.assert_not_called()
