"""The command channels -- stdin and UDP (issue #69)."""

import os
import socket
import unittest
from unittest import mock
from unittest.mock import patch

from openemux.core import retroarch_command
from openemux.core.retroarch_command import (
    DEFAULT_NETWORK_CMD_PORT,
    RetroArchCommandClient,
    StdinCommandClient,
    pick_free_udp_port,
    uses_stdin_channel,
)
from tests.platform_marks import posix_only


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

            for command in ("QUIT", "SAVE_STATE_SLOT 3"):
                self.assertTrue(client.send(command))
                data, _addr = server.recvfrom(64)
                self.assertEqual(data, command.encode())

    def test_empty_command_is_refused(self):
        client = RetroArchCommandClient(1)
        self.addCleanup(client.close)
        self.assertFalse(client.send(""))
        self.assertFalse(client.send(None))

    def test_the_socket_is_reused_across_commands(self):
        # One socket per packet is a syscall pair each time for no gain
        # (issue #125).
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
        self.assertTrue(client.send("LOAD_STATE"))
        self.assertTrue(client.send("  SAVE_STATE_SLOT 3 \n"))
        self.assertTrue(client.send("QUIT"))
        self.assertEqual(pipe.drain(), b"LOAD_STATE\nSAVE_STATE_SLOT 3\nQUIT\n")

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


if __name__ == "__main__":
    unittest.main()
