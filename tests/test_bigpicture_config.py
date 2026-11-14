"""Big Picture's settings in the config, and its command-line option (issue 914)."""

import shutil
import tempfile
import unittest
from pathlib import Path

from openemux.core.config import (
    DEFAULT_BIG_PICTURE_TEXT_SIZE,
    MAX_BIG_PICTURE_TEXT_SIZE,
    MIN_BIG_PICTURE_TEXT_SIZE,
    ConfigManager,
    normalize_big_picture_text_size,
)


class BigPictureSettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.config = ConfigManager(self.tmp / "config.yaml")

    def test_the_defaults_are_off_and_one_hundred_percent(self):
        self.assertEqual(
            self.config.get_big_picture_settings(),
            {"start": False, "text_size": DEFAULT_BIG_PICTURE_TEXT_SIZE},
        )

    def test_start_and_text_size_are_stored_and_normalized(self):
        self.config.set_big_picture_start(True)
        self.assertTrue(self.config.get_big_picture_settings()["start"])
        self.assertEqual(self.config.set_big_picture_text_size(123), 120)
        self.assertEqual(self.config.get_big_picture_settings()["text_size"], 120)
        self.assertEqual(self.config.set_big_picture_text_size(9000), MAX_BIG_PICTURE_TEXT_SIZE)
        self.assertEqual(self.config.set_big_picture_text_size(-5), MIN_BIG_PICTURE_TEXT_SIZE)
        self.assertEqual(self.config.set_big_picture_text_size("x"), DEFAULT_BIG_PICTURE_TEXT_SIZE)
        # Written out and read back: the debounced save lands on disk.
        self.config.save_config()
        again = ConfigManager(self.tmp / "config.yaml")
        self.assertEqual(again.get_big_picture_settings(), {"start": True, "text_size": 100})

    def test_a_config_with_junk_under_the_key_falls_back(self):
        self.config.config["ui"]["big_picture"] = "nonsense"
        self.assertEqual(self.config.get_big_picture_settings()["start"], False)

    def test_normalization(self):
        self.assertEqual(normalize_big_picture_text_size(None), DEFAULT_BIG_PICTURE_TEXT_SIZE)
        self.assertEqual(normalize_big_picture_text_size(86), 90)
        self.assertEqual(normalize_big_picture_text_size(84), 80)
        self.assertEqual(normalize_big_picture_text_size(150.0), 150)


if __name__ == "__main__":
    unittest.main()
