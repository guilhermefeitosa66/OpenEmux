"""The user's name stays out of the log and the bug report (issue #461)."""

import unittest
from pathlib import Path
from unittest import mock

from openemux.core import privacy
from openemux.core.privacy import redact_home


class _HomeCase(unittest.TestCase):
    home = "/home/guilherme"
    real_home = "/home/guilherme"

    def setUp(self):
        for target, value in (("home", self.home), ("real", self.real_home)):
            if target == "home":
                patcher = mock.patch.object(privacy.Path, "home", return_value=Path(value))
            else:
                patcher = mock.patch.object(privacy, "get_real_home", return_value=Path(value))
            patcher.start()
            self.addCleanup(patcher.stop)


class RedactingAHomeTests(_HomeCase):
    def test_a_path_under_home_starts_with_a_tilde(self):
        self.assertEqual(
            redact_home("path=/home/guilherme/.openemux/playlists/VB.list"),
            "path=~/.openemux/playlists/VB.list",
        )

    def test_the_home_itself_and_every_occurrence(self):
        self.assertEqual(
            redact_home("/home/guilherme and '/home/guilherme/a', (/home/guilherme)"),
            "~ and '~/a', (~)",
        )

    def test_someone_elses_home_is_left_alone(self):
        self.assertEqual(redact_home("/home/guilherme2/x"), "/home/guilherme2/x")

    def test_nothing_to_redact(self):
        self.assertEqual(redact_home(""), "")
        self.assertIsNone(redact_home(None))
        self.assertEqual(redact_home("/tmp/x"), "/tmp/x")


class AFlatpakHomeTests(_HomeCase):
    home = "/home/guilherme/.var/app/io.github.guilhermefeitosa66.OpenEmux"

    def test_the_private_home_and_the_real_one_both_go(self):
        self.assertEqual(
            redact_home(f"{self.home}/config and /home/guilherme/games"),
            "~/config and ~/games",
        )


class AWindowsHomeTests(_HomeCase):
    home = "C:\\Users\\Guilherme"
    real_home = "C:\\Users\\Guilherme"

    def test_both_separators(self):
        self.assertEqual(
            redact_home("C:\\Users\\Guilherme\\.openemux and C:/Users/Guilherme/roms"),
            "~\\.openemux and ~/roms",
        )


class AHomeTooShortToRedactTests(_HomeCase):
    home = "/"
    real_home = "/"

    def test_a_root_home_rewrites_nothing(self):
        self.assertEqual(redact_home("/usr/lib/x"), "/usr/lib/x")


if __name__ == "__main__":
    unittest.main()
