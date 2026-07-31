"""The window's opening size (fixed 1200x800 did not fit a 720p screen)."""

import unittest

from openemux.ui.window import OpenEmuxWindow


class _Geometry:
    def __init__(self, width, height):
        self.width = width
        self.height = height


class DefaultWindowSizeTests(unittest.TestCase):
    def test_it_is_eighty_percent_of_the_monitor(self):
        self.assertEqual(OpenEmuxWindow._size_for_monitor(_Geometry(1920, 1080)), (1536, 864))
        self.assertEqual(OpenEmuxWindow._size_for_monitor(_Geometry(2560, 1440)), (2048, 1152))

    def test_it_fits_a_720p_screen(self):
        # The old fixed 1200x800 was taller than the screen itself.
        width, height = OpenEmuxWindow._size_for_monitor(_Geometry(1280, 720))
        self.assertLess(width, 1280)
        self.assertLess(height, 720)

    def test_it_never_exceeds_the_monitor(self):
        for w, h in ((1024, 600), (1280, 720), (1366, 768), (3840, 2160)):
            width, height = OpenEmuxWindow._size_for_monitor(_Geometry(w, h))
            self.assertLessEqual(width, w)
            self.assertLessEqual(height, h)

    def test_an_unreadable_monitor_falls_back(self):
        self.assertEqual(
            OpenEmuxWindow._size_for_monitor(None), OpenEmuxWindow.FALLBACK_WINDOW_SIZE
        )
        self.assertEqual(
            OpenEmuxWindow._size_for_monitor(_Geometry(0, 0)),
            OpenEmuxWindow.FALLBACK_WINDOW_SIZE,
        )


if __name__ == "__main__":
    unittest.main()
