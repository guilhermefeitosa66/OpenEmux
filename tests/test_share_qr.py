"""This device's address as a QR code, with and without segno (#589)."""

import importlib.util
import sys
import types
import unittest
from unittest import mock

from openemux.core.share import qr

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class QrTests(unittest.TestCase):
    def test_without_segno_there_is_no_picture(self):
        with mock.patch.object(importlib.util, "find_spec", return_value=None):
            self.assertFalse(qr.available())
            self.assertIsNone(qr.png_bytes("openemux-share://10.0.0.2:53319"))

    def test_a_broken_finder_counts_as_missing(self):
        with mock.patch.object(importlib.util, "find_spec", side_effect=ValueError):
            self.assertFalse(qr.available())

    def test_the_code_is_made_with_the_documented_options(self):
        made = mock.Mock()
        made.save.side_effect = lambda buffer, **kwargs: buffer.write(PNG_SIGNATURE)
        fake = types.SimpleNamespace(make=mock.Mock(return_value=made))
        with mock.patch.dict(sys.modules, {"segno": fake}), \
                mock.patch.object(importlib.util, "find_spec", return_value=object()):
            self.assertEqual(qr.png_bytes("uri", scale=6), PNG_SIGNATURE)
        fake.make.assert_called_once_with("uri", error="m", micro=False)
        kwargs = made.save.call_args.kwargs
        self.assertEqual((kwargs["kind"], kwargs["scale"], kwargs["border"]), ("png", 6, 4))
        self.assertEqual((kwargs["dark"], kwargs["light"]), ("#000000", "#ffffff"))

    @unittest.skipUnless(importlib.util.find_spec("segno"), "segno is not installed (optional)")
    def test_a_real_png_with_segno(self):  # pragma: no cover - only where segno is installed
        self.assertTrue(qr.png_bytes("openemux-share://10.0.0.2:53319#" + "a" * 64).startswith(PNG_SIGNATURE))


if __name__ == "__main__":
    unittest.main()
