import unittest

from openemux.core import screen_geometry


class FitContainTest(unittest.TestCase):
    def test_width_limited(self):
        x, y, w, h = screen_geometry.fit_contain(200, 100, 100, 100)
        self.assertEqual((x, y, w, h), (0.0, 25.0, 100.0, 50.0))

    def test_height_limited(self):
        x, y, w, h = screen_geometry.fit_contain(100, 200, 100, 100)
        self.assertEqual((x, y, w, h), (25.0, 0.0, 50.0, 100.0))

    def test_degenerate_box_is_empty(self):
        self.assertEqual(
            screen_geometry.fit_contain(100, 100, 0, 50), (0.0, 0.0, 0.0, 0.0)
        )

    def test_keeps_aspect(self):
        img_w, img_h = screen_geometry.FRAME_IMAGE_SIZE
        _, _, w, h = screen_geometry.frame_paint_rect(800, 600)
        self.assertAlmostEqual(w / h, img_w / img_h, places=5)


class ScreenRectTest(unittest.TestCase):
    def test_no_frame_fills_allocation(self):
        self.assertEqual(
            screen_geometry.screen_rect(640, 480, frame_enabled=False),
            (0.0, 0.0, 640.0, 480.0),
        )

    def test_frame_screen_sits_inside_paint_rect(self):
        alloc = (900, 900)
        fx, fy, fw, fh = screen_geometry.frame_paint_rect(*alloc)
        sx, sy, sw, sh = screen_geometry.screen_rect(*alloc, frame_enabled=True)
        self.assertGreater(sx, fx)
        self.assertGreater(sy, fy)
        self.assertLess(sx + sw, fx + fw)
        self.assertLess(sy + sh, fy + fh)

    def test_frame_screen_scales_with_allocation(self):
        small = screen_geometry.screen_rect(450, 450, frame_enabled=True)
        large = screen_geometry.screen_rect(900, 900, frame_enabled=True)
        for small_v, large_v in zip(small, large):
            self.assertAlmostEqual(large_v, small_v * 2.0, places=5)


if __name__ == "__main__":
    unittest.main()
