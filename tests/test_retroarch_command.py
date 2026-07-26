"""The UDP command channel and volume stepping (issue #69)."""

import socket
import unittest

from openemux.core.retroarch_command import (
    MAX_VOLUME_DB,
    MIN_VOLUME_DB,
    RetroArchCommandClient,
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


if __name__ == "__main__":
    unittest.main()
