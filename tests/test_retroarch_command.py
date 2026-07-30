"""The UDP command channel and volume stepping (issue #69)."""

import socket
import unittest
from unittest.mock import patch

from openemux.core.retroarch_command import (
    MAX_VOLUME_DB,
    MIN_VOLUME_DB,
    RetroArchCommandClient,
    VolumePacer,
    clamp_volume_db,
    volume_steps,
)


class ClampTests(unittest.TestCase):
    def test_range_and_garbage(self):
        self.assertEqual(clamp_volume_db(0.0), 0.0)
        self.assertEqual(clamp_volume_db(5), MAX_VOLUME_DB)
        self.assertEqual(clamp_volume_db(-100), MIN_VOLUME_DB)
        self.assertEqual(clamp_volume_db("nonsense"), MAX_VOLUME_DB)
        self.assertEqual(clamp_volume_db(None), MAX_VOLUME_DB)


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

            self.assertTrue(client.send("MUTE"))
            data, _addr = server.recvfrom(64)
            self.assertEqual(data, b"MUTE")

            self.assertEqual(client.send_repeated("VOLUME_DOWN", 3), 3)
            for _ in range(3):
                data, _addr = server.recvfrom(64)
                self.assertEqual(data, b"VOLUME_DOWN")

    def test_empty_command_is_refused(self):
        client = RetroArchCommandClient(1)
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


class PacedDeliveryTests(unittest.TestCase):
    """Issue #125: paced steps actually arrive; unpaced bursts did not."""

    def test_a_paced_walk_delivers_every_step(self):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as server:
            server.bind(("127.0.0.1", 0))
            server.settimeout(2)
            port = server.getsockname()[1]
            client = RetroArchCommandClient(port)

            # Driven with a no-op sleep: the real 16 ms cadence over a full
            # 40 dB walk would be 1.3 s, uncomfortably close to the timeout
            # above, and what is under test here is delivery, not timing.
            pacer = VolumePacer(client, level=0.0, sleep=lambda _s: None)
            pacer.set_target(-10.0)
            pacer.join(5)

            for _ in range(20):
                data, _addr = server.recvfrom(64)
                self.assertEqual(data, b"VOLUME_DOWN")
            self.assertEqual(pacer.level, -10.0)
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


if __name__ == "__main__":
    unittest.main()
