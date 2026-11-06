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


if __name__ == "__main__":
    unittest.main()
