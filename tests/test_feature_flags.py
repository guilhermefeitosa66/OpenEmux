import unittest
from unittest import mock

from openemux.core import feature_flags


class EnvBoolTest(unittest.TestCase):
    def test_truthy_values(self):
        for value in ("1", "true", "True", "TRUE", "yes", "on", " true "):
            with mock.patch.dict("os.environ", {"FLAG": value}):
                self.assertTrue(feature_flags.env_bool("FLAG"), value)

    def test_falsy_values(self):
        for value in ("0", "false", "no", "off", "banana"):
            with mock.patch.dict("os.environ", {"FLAG": value}):
                self.assertFalse(feature_flags.env_bool("FLAG"), value)

    def test_unset_uses_default(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertFalse(feature_flags.env_bool("FLAG"))
            self.assertTrue(feature_flags.env_bool("FLAG", default=True))

    def test_blank_uses_default(self):
        with mock.patch.dict("os.environ", {"FLAG": "  "}):
            self.assertTrue(feature_flags.env_bool("FLAG", default=True))

    def test_retroarch_embed_frame_flag(self):
        with mock.patch.dict("os.environ", {"OPENEMUX_RETROARCH_EMBED_FRAME": "true"}):
            self.assertTrue(feature_flags.retroarch_embed_frame_enabled())
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertFalse(feature_flags.retroarch_embed_frame_enabled())

    def test_the_game_window_is_no_longer_a_flag(self):
        # It graduated to runtime.game_window (issue #199); a leftover env var
        # from an old .env must not switch anything on or off.
        self.assertFalse(hasattr(feature_flags, "retroarch_embed_enabled"))


if __name__ == "__main__":
    unittest.main()
