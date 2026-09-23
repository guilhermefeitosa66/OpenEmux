"""The command channels -- stdin and UDP -- and volume stepping (issue #69)."""

import os
import socket
import unittest
from unittest import mock
from unittest.mock import patch

from openemux.core import retroarch_command
from openemux.core.retroarch_command import (
    DEFAULT_NETWORK_CMD_PORT,
    DEFAULT_VOLUME_DB,
    MAX_VOLUME_DB,
    MIN_VOLUME_DB,
    SATURATION_MARGIN_DB,
    RetroArchCommandClient,
    StdinCommandClient,
    VolumePacer,
    clamp_volume_db,
    pick_free_udp_port,
    uses_stdin_channel,
    volume_steps,
)
from tests.platform_marks import posix_only


class ClampTests(unittest.TestCase):
    def test_range_and_garbage(self):
        self.assertEqual(clamp_volume_db(0.0), 0.0)
        # +5 dB is inside RetroArch's real range (it amplifies to +12).
        self.assertEqual(clamp_volume_db(5), 5.0)
        self.assertEqual(clamp_volume_db(20), MAX_VOLUME_DB)
        self.assertEqual(clamp_volume_db(-100), MIN_VOLUME_DB)
        # Garbage falls back to unity gain, never to the +12 dB ceiling.
        self.assertEqual(clamp_volume_db("nonsense"), DEFAULT_VOLUME_DB)
        self.assertEqual(clamp_volume_db(None), DEFAULT_VOLUME_DB)


class VolumeStepTests(unittest.TestCase):
    def test_down_and_up_in_half_db_steps(self):
        self.assertEqual(volume_steps(0.0, -6.0), ("VOLUME_DOWN", 12))
        self.assertEqual(volume_steps(-10.0, -5.0), ("VOLUME_UP", 10))

    def test_no_steps_when_already_there(self):
        self.assertEqual(volume_steps(-3.0, -3.0), (None, 0))
        # Sub-step differences round away rather than emitting a wrong step.
        self.assertEqual(volume_steps(-3.0, -3.1), (None, 0))

    def test_targets_are_clamped_before_stepping(self):
        command, count = volume_steps(0.0, -999)
        self.assertEqual(command, "VOLUME_DOWN")
        self.assertEqual(count, int(abs(MIN_VOLUME_DB) / 0.5))


class CommandClientTests(unittest.TestCase):
    def test_commands_arrive_as_plain_text_datagrams(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server:
            server.bind(("127.0.0.1", 0))
            server.settimeout(2)
            port = server.getsockname()[1]
            client = RetroArchCommandClient(port)
            # The client keeps one reusable UDP socket; without this the test
            # ends holding it and the run reports an unclosed-socket
            # ResourceWarning after the summary (issue #244).
            self.addCleanup(client.close)

            self.assertTrue(client.send("MUTE"))
            data, _addr = server.recvfrom(64)
            self.assertEqual(data, b"MUTE")

            self.assertEqual(client.send_repeated("VOLUME_DOWN", 3), 3)
            for _ in range(3):
                data, _addr = server.recvfrom(64)
                self.assertEqual(data, b"VOLUME_DOWN")

    def test_empty_command_is_refused(self):
        client = RetroArchCommandClient(1)
        self.addCleanup(client.close)
        self.assertFalse(client.send(""))
        self.assertFalse(client.send(None))

    def test_the_socket_is_reused_across_commands(self):
        # A volume walk is dozens of datagrams; one socket per packet is a
        # syscall pair each time for no gain (issue #125).
        client = RetroArchCommandClient(55355)
        client.send("MUTE")
        first = client._sock
        client.send("MUTE")
        self.assertIsNotNone(first)
        self.assertIs(client._sock, first)
        client.close()
        self.assertIsNone(client._sock)


class WhichChannelTests(unittest.TestCase):
    """RetroArch binds its UDP socket on every interface, not on loopback.

    Measured against the vendored 1.22.2 and the Flathub build: the socket is
    0.0.0.0:<port> and answers on the machine's LAN address, so any host on
    the network could QUIT, RESET or overwrite a state in a running game. The
    stdin interface has no such reach, and only Windows lacks it.
    """

    def test_everywhere_but_windows_the_channel_is_stdin(self):
        with patch.object(retroarch_command, "IS_WINDOWS", False):
            self.assertTrue(uses_stdin_channel())

    def test_windows_keeps_udp_because_its_build_has_no_stdin_interface(self):
        with patch.object(retroarch_command, "IS_WINDOWS", True):
            self.assertFalse(uses_stdin_channel())


class _Pipe:
    """A real pipe: the read end is RetroArch, the write end is Popen.stdin."""

    def __init__(self, case):
        read_fd, write_fd = os.pipe()
        self.reader = os.fdopen(read_fd, "rb", buffering=0)
        self.stream = os.fdopen(write_fd, "wb")
        case.addCleanup(self.reader.close)
        case.addCleanup(self.stream.close)

    def drain(self):
        """Everything written so far; the reader stays blocking-free."""
        os.set_blocking(self.reader.fileno(), False)
        chunks = []
        while True:
            try:
                chunk = self.reader.read(65536)
            except BlockingIOError:
                break
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)


@posix_only("a non-blocking anonymous pipe is the POSIX side of Popen(stdin=PIPE)")
class StdinCommandClientTests(unittest.TestCase):
    def test_commands_arrive_one_per_line(self):
        # RetroArch splits its stdin on newlines; a command without one sits
        # in its buffer until the next arrives and the two run together.
        pipe = _Pipe(self)
        client = StdinCommandClient(pipe.stream)
        self.assertTrue(client.send("VOLUME_UP"))
        self.assertTrue(client.send("  SAVE_STATE_SLOT 3 \n"))
        self.assertEqual(client.send_repeated("VOLUME_DOWN", 2), 2)
        self.assertEqual(
            pipe.drain(), b"VOLUME_UP\nSAVE_STATE_SLOT 3\nVOLUME_DOWN\nVOLUME_DOWN\n"
        )

    def test_the_pipe_is_made_non_blocking(self):
        pipe = _Pipe(self)
        StdinCommandClient(pipe.stream)
        self.assertFalse(os.get_blocking(pipe.stream.fileno()))

    def test_empty_command_is_refused(self):
        pipe = _Pipe(self)
        client = StdinCommandClient(pipe.stream)
        self.assertFalse(client.send(""))
        self.assertFalse(client.send(None))
        self.assertFalse(client.send("   "))
        self.assertEqual(pipe.drain(), b"")

    def test_a_full_pipe_refuses_a_command_whole_instead_of_blocking(self):
        # A RetroArch that stopped reading must not freeze the UI thread that
        # pressed pause -- and a refused command must not leave half a line
        # behind to be glued onto the next one.
        pipe = _Pipe(self)
        client = StdinCommandClient(pipe.stream)
        fd = pipe.stream.fileno()
        for size in (65536, 4096, 1):
            while True:
                try:
                    os.write(fd, b"x" * size)
                except BlockingIOError:
                    break
        with self.assertLogs("openemux.core.retroarch_command", level="WARNING"):
            self.assertFalse(client.send("PAUSE_TOGGLE"))
        self.assertEqual(set(pipe.drain()), {ord("x")})
        # Room again: the very next command goes through, on a line of its own.
        self.assertTrue(client.send("PAUSE_TOGGLE"))
        self.assertEqual(pipe.drain(), b"PAUSE_TOGGLE\n")

    def test_a_game_that_has_gone_says_no(self):
        pipe = _Pipe(self)
        client = StdinCommandClient(pipe.stream)
        pipe.reader.close()
        with self.assertLogs("openemux.core.retroarch_command", level="WARNING"):
            self.assertFalse(client.send("QUIT"))

    def test_close_hands_retroarch_eof_and_nothing_more_goes_out(self):
        pipe = _Pipe(self)
        client = StdinCommandClient(pipe.stream)
        client.close()
        self.assertTrue(pipe.stream.closed)
        self.assertEqual(pipe.reader.read(), b"")
        self.assertFalse(client.send("QUIT"))

    def test_a_closed_stream_is_an_unusable_channel_not_a_crash(self):
        pipe = _Pipe(self)
        pipe.stream.close()
        with self.assertLogs("openemux.core.retroarch_command", level="WARNING"):
            client = StdinCommandClient(pipe.stream)
        self.assertFalse(client.send("QUIT"))
        client.close()


class StdinCommandClientCornerTests(unittest.TestCase):
    def test_a_stream_that_will_not_close_is_let_go_anyway(self):
        stream = mock.Mock()
        stream.fileno.side_effect = OSError("no descriptor")
        stream.close.side_effect = OSError("already gone")
        with self.assertLogs("openemux.core.retroarch_command", level="WARNING"):
            client = StdinCommandClient(stream)
        client.close()
        stream.close.assert_called_once()
        self.assertFalse(client.send("QUIT"))


class PacedDeliveryTests(unittest.TestCase):
    """Issue #125: paced steps actually arrive; unpaced bursts did not."""

    def test_a_paced_walk_delivers_every_step(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server:
            server.bind(("127.0.0.1", 0))
            server.settimeout(2)
            port = server.getsockname()[1]
            client = RetroArchCommandClient(port)

            # Driven with a no-op sleep: the real 75 ms cadence over a full
            # walk would take seconds, and what is under test here is
            # delivery, not timing.
            pacer = VolumePacer(client, level=0.0, sleep=lambda _s: None)
            pacer.set_target(-10.0)
            pacer.join(5)

            for _ in range(20):
                data, _addr = server.recvfrom(64)
                self.assertEqual(data, b"VOLUME_DOWN")
            self.assertEqual(pacer.level, -10.0)
            client.close()

    def test_a_walk_to_the_top_saturates_past_the_clamp(self):
        # Aiming at RetroArch's own +12 dB clamp sends extra steps: the
        # emulator pins there, so the overshoot is free and it re-syncs the
        # tracker after hotkey changes the tracker never saw (the reported
        # "slider at max is not RetroArch's max").
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server:
            server.bind(("127.0.0.1", 0))
            server.settimeout(2)
            port = server.getsockname()[1]
            client = RetroArchCommandClient(port)

            pacer = VolumePacer(client, level=MAX_VOLUME_DB - 1.0, sleep=lambda _s: None)
            pacer.set_target(MAX_VOLUME_DB)
            pacer.join(5)

            expected = int(SATURATION_MARGIN_DB / 0.5)
            for _ in range(expected):
                data, _addr = server.recvfrom(64)
                self.assertEqual(data, b"VOLUME_UP")
            self.assertEqual(pacer.level, MAX_VOLUME_DB)
            client.close()

    def test_send_repeated_can_pace_itself(self):
        client = RetroArchCommandClient(55355)
        with patch("openemux.core.retroarch_command.time.sleep") as sleep:
            self.assertEqual(client.send_repeated("VOLUME_UP", 4, delay=0.016), 4)
        # Between packets only -- no trailing wait after the last one.
        self.assertEqual(sleep.call_count, 3)
        client.close()

    def test_send_repeated_stays_unpaced_by_default(self):
        client = RetroArchCommandClient(55355)
        with patch("openemux.core.retroarch_command.time.sleep") as sleep:
            client.send_repeated("VOLUME_UP", 4)
        self.assertEqual(sleep.call_count, 0)
        client.close()


class SettlingWalkTests(unittest.TestCase):
    """A step that never left must not abandon the walk (issue #284)."""

    class _Client:
        def __init__(self, failures=()):
            self.sent = []
            self._failures = list(failures)

        def send(self, command):
            self.sent.append(command)
            if self._failures and self._failures.pop(0):
                return False
            return True

    def _pacer(self, client, level=0.0):
        return VolumePacer(client, level=level, sleep=lambda _s: None, interval=0)

    def test_a_lost_step_is_retried_and_the_walk_continues(self):
        client = self._Client(failures=[False, True, False, False])
        pacer = self._pacer(client)
        pacer.set_target(-2.0)
        pacer.join(2)
        # 4 steps of 0.5 dB, plus the one retry of the step that failed.
        self.assertEqual(len(client.sent), 5)
        self.assertAlmostEqual(pacer.level, -2.0)

    def test_a_step_that_fails_twice_stops_the_walk_where_it_landed(self):
        client = self._Client(failures=[False, True, True])
        pacer = self._pacer(client)
        pacer.set_target(-5.0)
        pacer.join(2)
        self.assertAlmostEqual(pacer.level, -0.5)
        # The tracker holds what actually landed, so the UI can reconcile.
        self.assertTrue(pacer.settling)

    def test_settling_is_false_once_the_level_reaches_the_target(self):
        pacer = self._pacer(self._Client())
        self.assertFalse(pacer.settling)
        pacer.set_target(-3.0)
        pacer.join(2)
        self.assertFalse(pacer.settling)


class FreePortTests(unittest.TestCase):
    """Each launch gets a port of its own (issue #227)."""

    def test_the_picked_port_is_free_and_usable(self):
        port = pick_free_udp_port()
        self.assertGreater(port, 0)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.bind(("127.0.0.1", port))  # nothing else holds it

    def test_successive_picks_do_not_collide(self):
        ports = {pick_free_udp_port() for _ in range(5)}
        self.assertNotIn(0, ports)

    def test_a_failed_probe_falls_back_to_the_default(self):
        # A broken channel still beats refusing to launch.
        with patch("openemux.core.retroarch_command.socket.socket", side_effect=OSError("no")):
            self.assertEqual(pick_free_udp_port(), DEFAULT_NETWORK_CMD_PORT)


class WhenTheSocketGoesBadTests(unittest.TestCase):
    """A dead handle must not be kept: every later command would fail on it."""

    def _client(self, sock):
        client = RetroArchCommandClient(port=55555)
        client._sock = sock
        return client

    def test_a_send_that_fails_drops_the_socket_and_says_no(self):
        sock = mock.Mock()
        sock.sendto.side_effect = OSError("no route to host")
        client = self._client(sock)
        with self.assertLogs("openemux.core.retroarch_command", level="WARNING"):
            self.assertFalse(client.send("PAUSE_TOGGLE"))
        self.assertIsNone(client._sock)
        sock.close.assert_called_once()

    def test_a_socket_that_will_not_close_is_dropped_anyway(self):
        sock = mock.Mock()
        sock.close.side_effect = OSError("already gone")
        client = self._client(sock)
        client._drop_socket()
        self.assertIsNone(client._sock)


class WhatThePacerIsAimingAtTests(unittest.TestCase):
    def test_the_target_is_where_the_volume_is_heading(self):
        # Read by the OSD while the walk is still on its way there.
        client = RetroArchCommandClient(port=55555)
        self.addCleanup(client._drop_socket)
        pacer = VolumePacer(client, sleep=lambda _s: None)
        pacer.reset(0.0)
        self.assertEqual(pacer.target, 0.0)
        pacer.set_target(-12.0)
        pacer.join(2)
        self.assertEqual(pacer.target, -12.0)


if __name__ == "__main__":
    unittest.main()
