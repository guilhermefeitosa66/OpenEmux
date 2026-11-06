"""The arithmetic of the controller drawing (issue 815): no GTK, no display."""

import unittest

from openemux.core import controller_targets as ct
from openemux.core.controller_layouts import ControllerElement, ControllerLayout, layout_for


def _element(element_id, element_type, x, y, width, height, actions):
    return ControllerElement(
        id=element_id, type=element_type, bind=element_id, x=x, y=y, width=width, height=height,
        images={}, actions=tuple(actions),
    )


def _layout(*elements, width=540, height=670):
    return ControllerLayout(console="SFC", width=width, height=height, background=None, elements=elements)


class TargetsTests(unittest.TestCase):
    def test_a_pad_gets_an_arm_per_direction_on_its_thirds(self):
        pad = _element("dpad", "dpad", 30, 60, 90, 90, ("up", "down", "left", "right"))
        arms = {t.action: (t.x, t.y, t.width, t.height) for t in ct.targets_for(_layout(pad))}
        self.assertEqual(arms["up"], (60, 60, 30, 30))
        self.assertEqual(arms["left"], (30, 90, 30, 30))
        self.assertEqual(arms["right"], (90, 90, 30, 30))
        self.assertEqual(arms["down"], (60, 120, 30, 30))
        self.assertEqual([t.element_id for t in ct.targets_for(_layout(pad))], ["dpad"] * 4)

    def test_a_stick_gets_its_four_directions_too(self):
        stick = _element("stick", "stick", 0, 0, 30, 30, ("l_up", "l_down", "l_left", "l_right"))
        self.assertEqual(
            [t.action for t in ct.targets_for(_layout(stick))], ["l_up", "l_left", "l_right", "l_down"]
        )

    def test_a_button_is_one_target_and_round_when_square(self):
        square = _element("a", "button", 0, 0, 69, 68, ("a",))
        wide = _element("start", "button", 100, 0, 82, 26, ("start",))
        targets = ct.targets_for(_layout(square, wide))
        self.assertEqual([(t.action, t.round) for t in targets], [("a", True), ("start", False)])
        self.assertEqual((targets[1].x, targets[1].width), (100, 82))

    def test_a_square_keypad_is_not_drawn_round(self):
        keypad = _element("k", "keypad", 0, 0, 40, 40, ("a",))
        self.assertFalse(ct.targets_for(_layout(keypad))[0].round)

    def test_a_control_with_no_action_is_kept_as_not_remappable(self):
        for element in (
            _element("disk", "button", 0, 0, 40, 40, ()),
            _element("stick2", "stick", 0, 0, 40, 40, ()),
        ):
            (target,) = ct.targets_for(_layout(element))
            self.assertIsNone(target.action)
            self.assertEqual(target.element_id, element.id)

    def test_targets_follow_reading_order_row_by_row(self):
        # The SNES pad: shoulders and Menu, then the pad and the face buttons, then Select/Start.
        order = [(t.element_id, t.action) for t in ct.targets_for(layout_for("SFC"))]
        self.assertEqual(order, [
            ("l", "l1"), ("menu", "menu_toggle"), ("r", "r1"),
            ("dpad", "up"), ("dpad", "left"), ("dpad", "right"), ("dpad", "down"),
            ("x", "x"), ("y", "y"), ("a", "a"), ("b", "b"),
            ("select", "select"), ("start", "start"),
        ])


class SizeTests(unittest.TestCase):
    def test_the_art_is_capped_and_keeps_its_proportions(self):
        self.assertEqual(ct.drawn_size(540, 670, 1000), (360, 447, 360 / 540))

    def test_it_shrinks_with_the_width_it_gets(self):
        width, height, scale = ct.drawn_size(540, 670, 270)
        self.assertEqual((width, height, scale), (270, 335, 0.5))

    def test_small_art_is_never_scaled_up(self):
        self.assertEqual(ct.drawn_size(200, 100, 1000), (200, 100, 1.0))

    def test_a_zero_width_still_draws_something(self):
        self.assertEqual(ct.drawn_size(540, 670, 0)[0], 1)


class TargetBoxTests(unittest.TestCase):
    def test_a_target_scales_with_the_art_and_is_offset(self):
        target = ct.Target("a", "a", 100, 200, 60, 60)
        self.assertEqual(ct.target_box(target, 0.5, 10, 270, 335), (60, 100, 30, 30))

    def test_a_small_target_grows_about_its_centre(self):
        target = ct.Target("select", "select", 100, 100, 40, 10)
        # Its centre, (60, 52.5) on screen, stays put; 24 x 24 around it.
        self.assertEqual(ct.target_box(target, 0.5, 0, 270, 335), (48, 40, 24, 24))

    def test_a_grown_target_stays_inside_the_drawing(self):
        corner = ct.Target("l1", "l", 0, 0, 10, 10)
        self.assertEqual(ct.target_box(corner, 1.0, 5, 100, 100), (5, 0, 24, 24))
        far = ct.Target("r1", "r", 95, 95, 5, 5)
        self.assertEqual(ct.target_box(far, 1.0, 0, 100, 100), (76, 76, 24, 24))

    def test_a_drawing_smaller_than_a_target_bounds_it(self):
        target = ct.Target("a", "a", 0, 0, 10, 10)
        self.assertEqual(ct.target_box(target, 1.0, 0, 20, 12), (0, 0, 20, 12))


def _rows(*rows, padding=0):
    """RGBA rows as the bytes a texture download gives, `padding` spare bytes per row."""
    width = len(rows[0])
    data = bytearray()
    for row in rows:
        for red, green, blue in row:
            data += bytes((red, green, blue, 255))
        data += bytes(padding)
    return bytes(data), width, len(rows), width * 4 + padding


class BodyStopsTests(unittest.TestCase):
    """The body colour down each side of the art, for the card around it."""

    def test_each_slice_answers_its_average_at_its_centre(self):
        # 32 rows in 16 slices of two: the first slice averages 4 and 8.
        rows = [[(4 * (y + 1), 0, 200)] * 6 for y in range(32)]
        pixels, width, height, stride = _rows(*rows)
        stops = ct.body_stops(pixels, width, height, stride)
        self.assertEqual(len(stops), ct.BODY_STOPS)
        self.assertEqual(stops[0], (1 / 32, (6, 0, 200)))
        self.assertEqual(stops[-1], (31 / 32, (126, 0, 200)))
        self.assertEqual([offset for offset, _c in stops], sorted(offset for offset, _c in stops))

    def test_the_left_and_the_right_edge_are_read_apart(self):
        left, right, middle = (10, 20, 30), (200, 210, 220), (99, 99, 99)
        rows = [[left, left, middle, middle, right, right]] * 16
        pixels, width, height, stride = _rows(*rows)
        self.assertEqual({c for _o, c in ct.body_stops(pixels, width, height, stride)}, {left})
        self.assertEqual(
            {c for _o, c in ct.body_stops(pixels, width, height, stride, right=True)}, {right}
        )

    def test_only_the_band_at_the_edge_counts(self):
        # A control's shadow a few pixels in must not tint the body.
        rows = [[(50, 50, 50)] * ct.BODY_BAND + [(0, 0, 0)] * 4] * 16
        pixels, width, height, stride = _rows(*rows)
        self.assertEqual({c for _o, c in ct.body_stops(pixels, width, height, stride)}, {(50, 50, 50)})

    def test_rows_padded_past_their_pixels_are_read_by_stride(self):
        rows = [[(1, 2, 3)] * 3, [(101, 102, 103)] * 3]
        pixels, width, height, stride = _rows(*rows, padding=5)
        self.assertEqual(
            ct.body_stops(pixels, width, height, stride, right=True),
            [(0.25, (1, 2, 3)), (0.75, (101, 102, 103))],
        )

    def test_art_shorter_than_the_stops_gets_one_per_row_and_a_pixel_wide_one_is_read(self):
        pixels, width, height, stride = _rows([(7, 8, 9)], [(17, 18, 19)], [(27, 28, 29)])
        self.assertEqual(
            ct.body_stops(pixels, width, height, stride),
            [(1 / 6, (7, 8, 9)), (0.5, (17, 18, 19)), (5 / 6, (27, 28, 29))],
        )


if __name__ == "__main__":
    unittest.main()
