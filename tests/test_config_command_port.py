"""The RetroArch command port in config (issue #227).

55355 is RetroArch's own default, so it is exactly the port a standalone
RetroArch is already listening on. Both bind it -- the socket carries the
reuse flags -- and the kernel decides which one hears each datagram.
"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import yaml

from openemux.core.config import ConfigManager
from openemux.core.retroarch_command import (
    AUTO_NETWORK_CMD_PORT,
    DEFAULT_NETWORK_CMD_PORT,
)


class CommandPortConfigTests(unittest.TestCase):
    def _manager(self, tmp_dir, stored=None):
        path = Path(tmp_dir) / "config.yaml"
        if stored is not None:
            path.write_text(
                yaml.safe_dump({"runtime": {"network_cmd_port": stored}}),
                encoding="utf-8",
            )
        return ConfigManager(config_file=path)

    def test_a_fresh_config_picks_a_port_per_launch(self):
        with TemporaryDirectory() as tmp_dir:
            self.assertEqual(
                self._manager(tmp_dir).get_network_cmd_port(), AUTO_NETWORK_CMD_PORT
            )

    def test_the_untouched_retroarch_default_migrates_to_auto(self):
        # Nobody chose 55355; it is what the app shipped.
        with TemporaryDirectory() as tmp_dir:
            manager = self._manager(tmp_dir, stored=DEFAULT_NETWORK_CMD_PORT)
            self.assertEqual(manager.get_network_cmd_port(), AUTO_NETWORK_CMD_PORT)

    def test_a_port_the_user_pinned_is_left_alone(self):
        with TemporaryDirectory() as tmp_dir:
            manager = self._manager(tmp_dir, stored=54321)
            self.assertEqual(manager.get_network_cmd_port(), 54321)

    def test_garbage_falls_back_to_auto(self):
        with TemporaryDirectory() as tmp_dir:
            manager = self._manager(tmp_dir, stored="not a port")
            self.assertEqual(manager.get_network_cmd_port(), AUTO_NETWORK_CMD_PORT)


if __name__ == "__main__":
    unittest.main()
