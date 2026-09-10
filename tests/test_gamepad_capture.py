"""Reading a gamepad press off the kernel, without a gamepad.

`tests/test_gamepad_reader.py` covers the parsing and the token vocabulary --
the half that turns `/proc/bus/input/devices` into udev's own numbering. What
it leaves is the reader itself: opening the device node, draining what is
already queued, waiting on it, and falling back to the legacy joydev API when
`/dev/input/event*` cannot be opened. All of it is file descriptors, so a pipe
stands in for the device: the reader is handed one and fed the exact bytes the
kernel would put there.

Linux-only throughout: `struct input_event` and `struct js_event` are the
kernel ABI, and asserting them elsewhere would only assert that Windows is
Windows.
"""

import errno
import os
import struct
import unittest
from unittest import mock

from openemux.core import gamepad_reader
from openemux.core.gamepad_reader import (
    ABS_MAX,
    ABSINFO_FORMAT,
    ABSINFO_SIZE,
    EV_ABS,
    EV_KEY,
    INPUT_EVENT_FORMAT,
    INPUT_EVENT_SIZE,
    JS_EVENT_AXIS,
    JS_EVENT_BUTTON,
    JS_EVENT_FORMAT,
    JS_EVENT_INIT,
    GamepadCaptureReader,
    GamepadDevice,
    GamepadError,
    _drain,
    _read_axis_ranges,
    _read_proc_devices,
    joydev_token,
    list_gamepads,
)
from tests.platform_marks import linux_only


def _input_event(ev_type, code, value):
    return struct.pack(INPUT_EVENT_FORMAT, 0, 0, ev_type, code, value)


def _js_event(ev_type, number, value):
    return struct.pack(JS_EVENT_FORMAT, 0, value, ev_type, number)


class _Pipe:
    """A pipe standing in for a device node, closed with the test."""

    def __init__(self, case):
        self.read_fd, self.write_fd = os.pipe()
        os.set_blocking(self.read_fd, False)
        case.addCleanup(self._close)

    def feed(self, payload):
        os.write(self.write_fd, payload)

    def _close(self):
        for fd in (self.read_fd, self.write_fd):
            try:
                os.close(fd)
            except OSError:
                pass


class TheErrorTests(unittest.TestCase):
    def test_it_carries_a_machine_readable_reason(self):
        error = GamepadError("permission_denied")
        self.assertEqual(error.reason, "permission_denied")
        self.assertEqual(str(error), "permission_denied")

    def test_a_message_of_its_own_wins_over_the_reason(self):
        self.assertEqual(str(GamepadError("no_gamepad", "nothing plugged in")),
                         "nothing plugged in")


class TheNumberingSkipsTests(unittest.TestCase):
    """udev's numbering ignores codes the kernel cannot be reporting."""

    def test_an_axis_code_past_the_abs_range_is_not_numbered(self):
        index_map = gamepad_reader.build_axis_index_map([0x00, ABS_MAX + 1])
        self.assertEqual(index_map, {0x00: 0})

    def test_an_axis_the_device_does_not_advertise_yields_no_token(self):
        mapper = gamepad_reader.TokenMapper(key_codes=[], abs_codes=[0x00])
        self.assertIsNone(mapper.token_for_event(EV_ABS, 0x02, 32767))


@linux_only("/proc/bus/input/devices and the /dev/input node layout")
class ListingTheGamepadsTests(unittest.TestCase):
    def test_a_device_file_that_cannot_be_read_lists_nothing(self):
        self.assertEqual(_read_proc_devices("/nowhere/at/all"), "")

    def test_the_device_file_is_read_as_the_kernel_wrote_it(self):
        import tempfile
        from pathlib import Path

        path = Path(tempfile.mkdtemp()) / "devices"
        path.write_text('N: Name="Pad"\n', encoding="utf-8")
        self.assertEqual(_read_proc_devices(str(path)), 'N: Name="Pad"\n')

    def test_a_gamepad_with_no_node_at_all_is_skipped(self):
        # Nothing to open: neither an event nor a js handler.
        content = (
            'I: Bus=0003 Vendor=054c Product=09cc Version=8111\n'
            'N: Name="Wireless Controller"\n'
            "H: Handlers=kbd \n"
            "B: EV=20000b\n"
            "B: KEY=7fdb000000000000 0 0 0 0\n"
            "B: ABS=3003f\n"
            "\n"
        )
        self.assertEqual(list_gamepads(proc_content=content), [])


@linux_only("EVIOCGABS is the kernel ABI")
class ReadingTheAxisRangesTests(unittest.TestCase):
    def test_a_range_the_kernel_reports_is_used(self):
        absinfo = struct.pack(ABSINFO_FORMAT, 0, -128, 127, 0, 0, 0)
        with mock.patch("fcntl.ioctl", return_value=absinfo):
            self.assertEqual(_read_axis_ranges(3, [0x00]), {0x00: (-128, 127)})

    def test_an_axis_the_kernel_refuses_falls_back_to_the_default_range(self):
        with mock.patch("fcntl.ioctl", side_effect=OSError("ENOTTY")):
            self.assertEqual(_read_axis_ranges(3, [0x00]), {})

    def test_a_flat_range_is_no_range_at_all(self):
        absinfo = struct.pack(ABSINFO_FORMAT, 0, 5, 5, 0, 0, 0)
        with mock.patch("fcntl.ioctl", return_value=absinfo):
            self.assertEqual(_read_axis_ranges(3, [0x00]), {})

    def test_a_code_past_the_abs_range_is_never_asked_about(self):
        with mock.patch("fcntl.ioctl") as ioctl:
            self.assertEqual(_read_axis_ranges(3, [ABS_MAX + 1]), {})
        ioctl.assert_not_called()

    def test_the_request_is_the_ioctl_the_kernel_defines(self):
        seen = []
        absinfo = struct.pack(ABSINFO_FORMAT, 0, -1, 1, 0, 0, 0)

        def _ioctl(_fd, request, _buf):
            seen.append(request)
            return absinfo

        with mock.patch("fcntl.ioctl", _ioctl):
            _read_axis_ranges(3, [0x00])
        expected = (2 << 30) | (ABSINFO_SIZE << 16) | (ord("E") << 8) | 0x40
        self.assertEqual(seen, [expected])


@linux_only("the /dev/input nodes this drains")
class DrainingWhatIsAlreadyQueuedTests(unittest.TestCase):
    """A stale event must not be reported as the user's press."""

    def test_everything_queued_is_thrown_away(self):
        pipe = _Pipe(self)
        pipe.feed(_input_event(EV_KEY, 0x130, 1))
        _drain(pipe.read_fd, INPUT_EVENT_SIZE)
        with self.assertRaises(BlockingIOError):
            os.read(pipe.read_fd, INPUT_EVENT_SIZE)

    def test_an_empty_device_drains_at_once(self):
        pipe = _Pipe(self)
        _drain(pipe.read_fd, INPUT_EVENT_SIZE)

    def test_a_closed_device_drains_at_once_too(self):
        pipe = _Pipe(self)
        os.close(pipe.read_fd)
        _drain(pipe.read_fd, INPUT_EVENT_SIZE)

    def test_a_device_at_end_of_file_stops_the_drain(self):
        read_fd, write_fd = os.pipe()
        self.addCleanup(lambda: os.close(read_fd))
        os.close(write_fd)
        _drain(read_fd, INPUT_EVENT_SIZE)


class _ReaderCase(unittest.TestCase):
    """A reader whose device node is a pipe the test writes into."""

    def setUp(self):
        self.tokens = []
        self.errors = []
        self.pipe = _Pipe(self)
        self.reader = GamepadCaptureReader(
            on_token=self.tokens.append, on_error=self.errors.append
        )
        # The reader opens by path; it is handed the test's pipe instead, and
        # closes it on the way out like any real device node.
        open_patch = mock.patch.object(
            gamepad_reader.os, "open", return_value=self.pipe.read_fd
        )
        open_patch.start()
        self.addCleanup(open_patch.stop)
        # Draining is tested on its own; here it would eat the press.
        drain_patch = mock.patch.object(gamepad_reader, "_drain")
        drain_patch.start()
        self.addCleanup(drain_patch.stop)
        ranges_patch = mock.patch.object(
            gamepad_reader, "_read_axis_ranges", return_value={}
        )
        ranges_patch.start()
        self.addCleanup(ranges_patch.stop)

    def device(self, event_path="/dev/input/event9", js_path="/dev/input/js0"):
        return GamepadDevice(
            name="Wireless Controller",
            event_path=event_path,
            js_path=js_path,
            key_codes=[0x130, 0x131],
            abs_codes=[0x00, 0x01],
        )


@linux_only("struct input_event is the kernel ABI")
class ReadingAnEvdevPressTests(_ReaderCase):
    def test_a_button_press_is_reported_as_its_udev_index(self):
        self.pipe.feed(_input_event(EV_KEY, 0x131, 1))
        self.reader._read_evdev(self.device())
        self.assertEqual(self.tokens, ["1"])

    def test_an_axis_push_is_reported_with_its_direction(self):
        self.pipe.feed(_input_event(EV_ABS, 0x01, 32767))
        self.reader._read_evdev(self.device())
        self.assertEqual(self.tokens, ["+1"])

    def test_a_release_is_not_a_press_and_the_reader_keeps_waiting(self):
        self.pipe.feed(_input_event(EV_KEY, 0x131, 0))
        self.reader._cancel.set()
        self.reader._read_evdev(self.device())
        self.assertEqual(self.tokens, [])

    def test_a_device_that_reports_end_of_file_stops_the_reader(self):
        os.close(self.pipe.write_fd)
        self.reader._read_evdev(self.device())
        self.assertEqual(self.tokens, [])

    def test_a_read_that_would_block_is_simply_retried(self):
        reads = [BlockingIOError(), b""]
        with mock.patch.object(
            gamepad_reader.os, "read", side_effect=reads
        ), mock.patch.object(self.reader, "_wait_readable", return_value=True):
            self.reader._read_evdev(self.device())
        self.assertEqual(self.tokens, [])

    def test_a_device_that_disappears_mid_read_stops_the_reader(self):
        with mock.patch.object(
            gamepad_reader.os, "read", side_effect=OSError("ENODEV")
        ), mock.patch.object(self.reader, "_wait_readable", return_value=True):
            self.reader._read_evdev(self.device())
        self.assertEqual(self.tokens, [])


@linux_only("struct js_event is the kernel ABI")
class ReadingALegacyJoydevPressTests(_ReaderCase):
    def test_a_button_press_is_reported_by_its_joydev_number(self):
        self.pipe.feed(_js_event(JS_EVENT_BUTTON, 3, 1))
        self.reader._read_joydev(self.device())
        self.assertEqual(self.tokens, ["3"])

    def test_a_device_that_reports_end_of_file_stops_the_reader(self):
        os.close(self.pipe.write_fd)
        self.reader._read_joydev(self.device())
        self.assertEqual(self.tokens, [])

    def test_a_read_that_would_block_is_simply_retried(self):
        with mock.patch.object(
            gamepad_reader.os, "read", side_effect=[BlockingIOError(), b""]
        ), mock.patch.object(self.reader, "_wait_readable", return_value=True):
            self.reader._read_joydev(self.device())
        self.assertEqual(self.tokens, [])

    def test_a_device_that_disappears_mid_read_stops_the_reader(self):
        with mock.patch.object(
            gamepad_reader.os, "read", side_effect=OSError("ENODEV")
        ), mock.patch.object(self.reader, "_wait_readable", return_value=True):
            self.reader._read_joydev(self.device())
        self.assertEqual(self.tokens, [])

    def test_the_synthetic_initial_state_is_not_a_press(self):
        self.assertIsNone(joydev_token(0, 1, JS_EVENT_BUTTON | JS_EVENT_INIT, 3))

    def test_an_axis_inside_the_deadzone_is_not_a_press(self):
        self.assertIsNone(joydev_token(0, 10, JS_EVENT_AXIS, 1))

    def test_an_axis_past_the_deadzone_carries_its_direction(self):
        self.assertEqual(joydev_token(0, -32000, JS_EVENT_AXIS, 1), "-1")

    def test_an_event_kind_joydev_does_not_define_is_not_a_press(self):
        self.assertIsNone(joydev_token(0, 1, 0x04, 3))


@linux_only("select on a /dev/input node")
class WaitingForTheDeviceTests(_ReaderCase):
    def test_a_device_with_data_is_readable(self):
        self.pipe.feed(b"x")
        self.assertTrue(self.reader._wait_readable(self.pipe.read_fd))

    def test_a_cancelled_capture_stops_waiting(self):
        self.reader._cancel.set()
        self.assertFalse(self.reader._wait_readable(self.pipe.read_fd))

    def test_a_device_that_cannot_be_selected_on_stops_the_wait(self):
        with mock.patch.object(
            gamepad_reader.select, "select", side_effect=OSError("EBADF")
        ):
            self.assertFalse(self.reader._wait_readable(self.pipe.read_fd))

    def test_a_device_that_stays_quiet_is_polled_until_cancelled(self):
        polls = []

        def _select(_r, _w, _x, _timeout):
            polls.append(1)
            self.reader._cancel.set()
            return ([], [], [])

        with mock.patch.object(gamepad_reader.select, "select", _select):
            self.assertFalse(self.reader._wait_readable(self.pipe.read_fd))
        self.assertEqual(len(polls), 1)


@linux_only("the /dev/input node layout")
class ChoosingWhatToReadTests(unittest.TestCase):
    """Which node the capture opens, and what it reports when none works."""

    def setUp(self):
        self.tokens = []
        self.errors = []
        self.reader = GamepadCaptureReader(
            on_token=self.tokens.append, on_error=self.errors.append
        )

    def _device(self, event_path="/dev/input/event9", js_path="/dev/input/js0"):
        return GamepadDevice(
            name="Pad", event_path=event_path, js_path=js_path,
            key_codes=[], abs_codes=[],
        )

    def test_with_no_pad_plugged_in_it_says_so(self):
        with mock.patch.object(gamepad_reader, "list_gamepads", return_value=[]):
            self.reader._run()
        self.assertEqual(self.errors, ["no_gamepad"])

    def test_with_no_device_named_it_takes_the_first_one(self):
        device = self._device()
        with mock.patch.object(
            gamepad_reader, "list_gamepads", return_value=[device]
        ), mock.patch.object(GamepadCaptureReader, "_read_evdev") as read:
            self.reader._run()
        read.assert_called_once_with(device)

    def test_an_unreadable_event_node_falls_back_to_the_legacy_api(self):
        # Better than refusing to capture at all, even though joydev's
        # numbering does not necessarily agree with udev's.
        self.reader._device = self._device()
        with mock.patch.object(
            GamepadCaptureReader, "_read_evdev", side_effect=PermissionError()
        ), mock.patch.object(GamepadCaptureReader, "_read_joydev") as joydev:
            self.reader._run()
        joydev.assert_called_once()
        self.assertTrue(self.reader.uses_legacy_api)

    def test_a_permission_errno_is_read_the_same_way_as_the_exception(self):
        # A bare OSError carrying EACCES: constructing OSError(EACCES, ...)
        # would give a PermissionError, which the branch above already catches.
        self.reader._device = self._device()
        denied = OSError("denied")
        denied.errno = errno.EACCES
        with mock.patch.object(
            GamepadCaptureReader, "_read_evdev", side_effect=denied
        ), mock.patch.object(GamepadCaptureReader, "_read_joydev") as joydev:
            self.reader._run()
        joydev.assert_called_once()

    def test_neither_node_readable_reports_the_permission_problem(self):
        self.reader._device = self._device()
        with mock.patch.object(
            GamepadCaptureReader, "_read_evdev", side_effect=PermissionError()
        ), mock.patch.object(
            GamepadCaptureReader, "_read_joydev", side_effect=PermissionError()
        ):
            self.reader._run()
        self.assertEqual(self.errors, ["permission_denied"])

    def test_a_legacy_node_that_reports_a_permission_errno_is_the_same(self):
        self.reader._device = self._device()
        denied = OSError("denied")
        denied.errno = errno.EPERM
        with mock.patch.object(
            GamepadCaptureReader, "_read_evdev", side_effect=PermissionError()
        ), mock.patch.object(
            GamepadCaptureReader, "_read_joydev", side_effect=denied
        ):
            self.reader._run()
        self.assertEqual(self.errors, ["permission_denied"])

    def test_a_device_with_no_node_at_all_reports_no_gamepad(self):
        self.reader._device = self._device(event_path=None, js_path=None)
        self.reader._run()
        self.assertEqual(self.errors, ["no_gamepad"])

    def test_an_event_node_error_that_is_not_a_permission_one_is_not_retried(self):
        self.reader._device = self._device(js_path=None)
        gone = OSError("gone")
        gone.errno = errno.ENODEV
        with mock.patch.object(
            GamepadCaptureReader, "_read_evdev", side_effect=gone
        ):
            self.reader._run()
        self.assertEqual(self.errors, ["no_gamepad"])

    def test_a_legacy_node_error_that_is_not_a_permission_one_says_no_gamepad(self):
        self.reader._device = self._device()
        gone = OSError("gone")
        gone.errno = errno.ENODEV
        with mock.patch.object(
            GamepadCaptureReader, "_read_evdev", side_effect=PermissionError()
        ), mock.patch.object(
            GamepadCaptureReader, "_read_joydev", side_effect=gone
        ):
            self.reader._run()
        self.assertEqual(self.errors, ["permission_denied"])

    def test_a_capture_cancelled_mid_fallback_stops_there(self):
        self.reader._device = self._device()

        def _deny(_reader, _device):
            self.reader._cancel.set()
            raise PermissionError()

        with mock.patch.object(
            GamepadCaptureReader, "_read_evdev", _deny
        ), mock.patch.object(GamepadCaptureReader, "_read_joydev") as joydev:
            self.reader._run()
        joydev.assert_not_called()


class TheCaptureLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tokens = []
        self.errors = []
        self.reader = GamepadCaptureReader(
            on_token=self.tokens.append, on_error=self.errors.append
        )

    def test_starting_runs_the_read_on_a_thread_of_its_own(self):
        with mock.patch.object(GamepadCaptureReader, "_run") as run:
            self.reader.start()
            self.reader.stop()
        run.assert_called_once()

    def test_a_second_start_does_not_add_a_second_thread(self):
        with mock.patch.object(gamepad_reader.threading, "Thread") as thread:
            self.reader.start()
            self.reader.start()
            self.reader.stop()
        thread.assert_called_once()

    def test_stopping_cancels_the_capture_and_waits_for_the_thread(self):
        thread = mock.Mock()
        thread.is_alive.return_value = True
        with mock.patch.object(
            gamepad_reader.threading, "Thread", return_value=thread
        ):
            self.reader.start()
            self.reader.stop(join_timeout=0.1)
        thread.join.assert_called_once_with(timeout=0.1)
        self.assertTrue(self.reader.cancelled)

    def test_stopping_a_capture_that_never_started_is_harmless(self):
        self.reader.stop()
        self.assertTrue(self.reader.cancelled)

    def test_the_first_press_is_the_only_one_reported(self):
        self.reader._emit_token("3")
        self.reader._emit_token("4")
        self.assertEqual(self.tokens, ["3"])

    def test_an_error_after_a_press_is_not_reported(self):
        self.reader._emit_token("3")
        self.reader._emit_error("no_gamepad")
        self.assertEqual(self.errors, [])

    def test_a_capture_with_no_callbacks_at_all_is_harmless(self):
        reader = GamepadCaptureReader(on_token=None)
        reader._emit_token("3")
        reader = GamepadCaptureReader(on_token=None)
        reader._emit_error("no_gamepad")


if __name__ == "__main__":
    unittest.main()
