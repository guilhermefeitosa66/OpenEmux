"""The controller drawing widget (issue 815), built for real on the test display."""

import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.gtk_display import HAVE_DISPLAY, needs_display

if HAVE_DISPLAY:
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Gsk", "4.0")
    from gi.repository import Gsk, Gtk

    from openemux.core.controller_layouts import ControllerElement, ControllerLayout, layout_for
    from openemux.core.controller_targets import target_box
    from openemux.ui.controller_drawing import ControllerDrawing


def _controllers(widget, kind):
    model = widget.observe_controllers()
    return [model.get_item(i) for i in range(model.get_n_items()) if isinstance(model.get_item(i), kind)]


@needs_display
class ControllerDrawingTests(unittest.TestCase):
    def setUp(self):
        self.activated = []
        self.highlighted = []
        self.drawing = ControllerDrawing(
            layout_for("SFC"),
            on_activate=self.activated.append,
            on_highlight=self.highlighted.append,
            not_remappable_text="not remappable",
        )

    def test_every_remappable_control_gets_a_button(self):
        self.assertEqual(
            set(self.drawing.buttons),
            {"l1", "r1", "menu_toggle", "up", "down", "left", "right", "x", "y", "a", "b", "select", "start"},
        )
        self.assertTrue(self.drawing.buttons["a"][0].has_css_class("round"))
        self.assertFalse(self.drawing.buttons["start"][0].has_css_class("round"))

    def test_clicking_a_button_hands_its_action_over(self):
        self.drawing.buttons["b"][0].emit("clicked")
        self.assertEqual(self.activated, ["b"])

    def test_hover_and_focus_say_which_action_is_under_them(self):
        button = self.drawing.buttons["a"][0]
        for kind in (Gtk.EventControllerMotion, Gtk.EventControllerFocus):
            (controller,) = _controllers(button, kind)
            if kind is Gtk.EventControllerMotion:
                controller.emit("enter", 1.0, 1.0)
            else:
                controller.emit("enter")
            controller.emit("leave")
        self.assertEqual(self.highlighted, ["a", None, "a", None])

    def test_with_no_highlight_callback_hovering_is_harmless(self):
        drawing = ControllerDrawing(layout_for("SFC"), on_activate=lambda _a: None)
        (motion,) = _controllers(drawing.buttons["a"][0], Gtk.EventControllerMotion)
        motion.emit("enter", 1.0, 1.0)

    def test_action_state_sets_tooltip_and_sensitivity(self):
        self.drawing.set_action_state("a", "A: x", True)
        button = self.drawing.buttons["a"][0]
        self.assertEqual(button.get_tooltip_text(), "A: x")
        self.assertTrue(button.get_sensitive())
        self.drawing.set_action_state("menu_toggle", "not remappable", False)
        menu = self.drawing.buttons["menu_toggle"][0]
        self.assertFalse(menu.get_sensitive())
        self.assertFalse(menu.get_focusable())
        # An action the drawing does not have is ignored.
        self.drawing.set_action_state("turbo", "x", True)

    def test_the_current_action_is_marked_and_unmarked(self):
        self.drawing.set_current("up")
        self.assertTrue(self.drawing.buttons["up"][0].has_css_class("current"))
        self.assertFalse(self.drawing.buttons["down"][0].has_css_class("current"))
        self.drawing.set_current(None)
        self.assertFalse(self.drawing.buttons["up"][0].has_css_class("current"))

    def test_it_asks_for_height_for_width_capped_at_360(self):
        self.assertEqual(self.drawing.get_request_mode(), Gtk.SizeRequestMode.HEIGHT_FOR_WIDTH)
        minimum, natural, _b1, _b2 = self.drawing.measure(Gtk.Orientation.HORIZONTAL, -1)
        self.assertEqual((minimum, natural), (120, 360))
        self.assertEqual(self.drawing.measure(Gtk.Orientation.VERTICAL, 270)[:2], (335, 335))
        self.assertEqual(self.drawing.measure(Gtk.Orientation.VERTICAL, -1)[:2], (447, 447))

    def test_allocating_places_the_targets_and_snapshot_draws(self):
        window = Gtk.Window()
        window.set_child(self.drawing)
        self.addCleanup(window.destroy)
        self.drawing.do_size_allocate(400, 447, -1)
        start = self.drawing.buttons["start"][0]
        bounds = start.compute_bounds(self.drawing)[1]
        # 20 px of centring on each side of the 360 px art.
        self.assertGreaterEqual(bounds.get_x(), 20)
        self.assertEqual(round(bounds.get_height()), 24)
        snapshot = Gtk.Snapshot()
        self.drawing.do_snapshot(snapshot)
        self.assertIsNotNone(snapshot.to_node())

    def test_the_body_beside_the_art_is_read_from_the_arts_own_edges(self):
        # The SNES pad: light grey, lighter at the top than at the bottom, and
        # the same on both sides.
        left, right = self.drawing._body
        self.assertEqual(len(left), 16)
        self.assertEqual(len(right), 16)
        self.assertEqual(round(left[0].color.red * 255), 197)
        self.assertEqual(round(left[-1].color.red * 255), 185)
        self.assertEqual(left[0].color.alpha, 1.0)
        self.assertLess(left[0].offset, left[-1].offset)
        for ours, theirs in zip(left, right):
            self.assertAlmostEqual(ours.color.red, theirs.color.red, delta=2 / 255)

    def test_the_body_fills_the_width_the_art_leaves(self):
        window = Gtk.Window()
        window.set_child(self.drawing)
        self.addCleanup(window.destroy)
        self.drawing.allocate(600, 447, -1, None)
        snapshot = Gtk.Snapshot()
        self.drawing.do_snapshot(snapshot)
        node = snapshot.to_node()
        # Wider than the 360 px art: the body's gradients take it edge to edge.
        self.assertEqual(round(node.get_bounds().get_x()), 0)
        self.assertEqual(round(node.get_bounds().get_width()), 600)
        gradients = [
            node.get_child(i) for i in range(node.get_n_children())
            if isinstance(node.get_child(i), Gsk.LinearGradientNode)
        ]
        self.assertEqual(len(gradients), 2)
        left, right = gradients
        # Each side's shade runs to the middle of the art, where they meet.
        self.assertEqual(round(left.get_bounds().get_width()), 300)
        self.assertEqual(round(right.get_bounds().get_x()), 300)
        self.assertEqual(round(right.get_bounds().get_width()), 300)
        self.assertEqual(round(left.get_bounds().get_height()), 447)

    def test_lighting_marks_the_targets_and_only_those(self):
        self.drawing.set_lit({"a", "up"})
        self.assertEqual(self.drawing.lit, frozenset({"a", "up"}))
        self.assertTrue(self.drawing.buttons["a"][0].has_css_class("lit"))
        self.assertTrue(self.drawing.buttons["up"][0].has_css_class("lit"))
        self.assertFalse(self.drawing.buttons["b"][0].has_css_class("lit"))
        self.drawing.set_lit({"b"})
        self.assertFalse(self.drawing.buttons["a"][0].has_css_class("lit"))
        self.assertTrue(self.drawing.buttons["b"][0].has_css_class("lit"))
        self.drawing.set_lit(())
        self.assertEqual(self.drawing.lit, frozenset())
        self.assertFalse(self.drawing.buttons["b"][0].has_css_class("lit"))

    def test_an_action_with_no_target_is_not_lit_and_the_same_set_redraws_nothing(self):
        self.drawing.set_lit({"turbo", "save_state"})
        self.assertEqual(self.drawing.lit, frozenset())
        self.drawing.set_lit({"a"})
        with mock.patch.object(self.drawing, "queue_draw") as queue_draw:
            self.drawing.set_lit({"a", "turbo"})
            queue_draw.assert_not_called()
            self.drawing.set_lit({"a", "b"})
            queue_draw.assert_called_once()

    def _clips(self, drawing, width, height):
        """The rounded clips in the drawing's snapshot: what lighting adds to it.

        Each as ``(child node, (x, y, width, height, radius))``. The shape is
        read from the node's own serialization: reading ``GskRoundedRect``'s
        ``corner`` array through PyGObject crashes the interpreter on the
        versions the packages are built against.
        """
        if drawing.get_parent() is None:
            window = Gtk.Window()
            window.set_child(drawing)
            self.addCleanup(window.destroy)
        drawing.allocate(width, height, -1, None)
        snapshot = Gtk.Snapshot()
        drawing.do_snapshot(snapshot)
        node = snapshot.to_node()
        clips = []
        for index in range(node.get_n_children()):
            child = node.get_child(index)
            if not isinstance(child, Gsk.RoundedClipNode):
                continue
            text = child.serialize().get_data().decode()
            shape = re.search(r"clip: ([-\d.]+) ([-\d.]+) ([-\d.]+) ([-\d.]+) / ([-\d.]+);", text)
            clips.append((child.get_child(), tuple(round(float(v)) for v in shape.groups())))
        return clips

    def test_a_lit_control_is_drawn_again_brighter_inside_its_target(self):
        self.assertEqual(self._clips(self.drawing, 360, 447), [])
        self.drawing.set_lit({"a", "start", "up"})
        clips = self._clips(self.drawing, 360, 447)
        # The control's own image, through a colour matrix: one per lit target.
        images = {shape[:2]: shape for child, shape in clips if isinstance(child, Gsk.ColorMatrixNode)}
        self.assertEqual(len(images), 3)
        scale = 360 / 540
        boxes = {}
        for action, radius in (("up", 8), ("start", 8), ("a", None)):
            target = next(t for t in self.drawing.targets if t.action == action)
            x, y, w, h = boxes[action] = target_box(target, scale, 0, 360, 447)
            # Exactly the target (one arm of the D-pad, not the whole pad); a
            # round button is clipped to a circle, the rest to rounded boxes.
            self.assertEqual(images[(x, y)], (x, y, w, h, radius if radius else round(min(w, h) / 2)))
        pad = next(e for e in layout_for("SFC").elements if e.type == "dpad")
        self.assertLess(boxes["up"][2], pad.width * scale / 2)

    def test_a_lit_control_glows_in_the_widgets_colour(self):
        self.drawing.set_lit({"a"})
        clips = self._clips(self.drawing, 360, 447)
        halos = [(child, shape) for child, shape in clips if isinstance(child, Gsk.ColorNode)]
        # Two shapes around the target, the wider one fainter, in the colour
        # the stylesheet gives the drawing (the accent).
        self.assertEqual(len(halos), 2)
        target = next(t for t in self.drawing.targets if t.action == "a")
        x, y, w, h = target_box(target, 360 / 540, 0, 360, 447)
        radius = round(min(w, h) / 2)
        self.assertEqual(
            [shape for _child, shape in halos],
            # Round like the button they are around, 13 and 9 px past it.
            [(x - 13, y - 13, w + 26, h + 26, radius + 13), (x - 9, y - 9, w + 18, h + 18, radius + 9)],
        )
        alphas = [child.get_color().alpha for child, _shape in halos]
        self.assertLess(alphas[0], alphas[1])
        accent = self.drawing.get_color()
        for child, _shape in halos:
            color = child.get_color()
            self.assertAlmostEqual(color.red, accent.red, places=3)
            self.assertAlmostEqual(color.blue, accent.blue, places=3)

    def test_a_control_with_no_action_gets_an_inert_area_with_a_tooltip(self):
        drawing = ControllerDrawing(
            # The keypad switch of the Android skin: the only kind of control
            # left with nothing to remap on the desktop (issue 816).
            layout_for("CV"), on_activate=lambda _a: None, not_remappable_text="not remappable"
        )
        inert = [c for c in _children(drawing) if c.has_css_class("controller-inert")]
        self.assertEqual(len(inert), 1)
        self.assertEqual(inert[0].get_tooltip_text(), "not remappable")
        self.assertFalse(inert[0].get_focusable())

    def _focused_actions(self, window, direction):
        order = []
        while self.drawing.child_focus(direction):
            focused = window.get_focus()
            order.append(next(t.action for t, c in self.drawing._children if c is focused))
        return order

    def test_tab_walks_the_targets_in_reading_order(self):
        window = Gtk.Window()
        window.set_child(self.drawing)
        self.addCleanup(window.destroy)
        self.drawing.do_size_allocate(360, 447, -1)
        expected = [t.action for t in self.drawing.targets if t.action is not None]
        self.assertEqual(self._focused_actions(window, Gtk.DirectionType.TAB_FORWARD), expected)
        window.set_focus(None)
        self.assertEqual(
            self._focused_actions(window, Gtk.DirectionType.TAB_BACKWARD), list(reversed(expected))
        )

    def test_arrow_keys_keep_gtks_own_focus_chain(self):
        window = Gtk.Window()
        window.set_child(self.drawing)
        self.addCleanup(window.destroy)
        self.drawing.do_size_allocate(360, 447, -1)
        self.drawing.buttons["up"][0].grab_focus()
        # Whatever GTK decides for an arrow, it is GTK's call, not the Tab order's.
        self.assertIsInstance(self.drawing.child_focus(Gtk.DirectionType.DOWN), bool)

    def test_its_handlers_do_not_hold_it(self):
        import gc
        import weakref

        ref = weakref.ref(self.drawing)
        self.drawing.run_dispose()
        self.drawing = None
        gc.collect()
        self.assertIsNone(ref())

    def test_disposing_it_lets_go_of_its_children(self):
        button = self.drawing.buttons["a"][0]
        self.drawing.run_dispose()
        self.assertIsNone(button.get_parent())
        self.assertEqual(self.drawing.buttons, {})


@needs_display
class UnreadableArtTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_art_that_does_not_load_is_skipped_and_logged(self):
        broken = self.tmp / "broken.png"
        broken.write_text("not a png")
        good = layout_for("SFC").elements[0].images["button"]
        layout = ControllerLayout(
            console="SFC", width=100, height=100, background=broken,
            elements=(
                ControllerElement(
                    id="a", type="button", bind="a", x=0, y=0, width=50, height=50,
                    images={"button": good}, actions=("a",),
                ),
                ControllerElement(
                    id="b", type="button", bind="b", x=50, y=0, width=50, height=50,
                    images={"button": broken}, actions=("b",),
                ),
            ),
        )
        with self.assertLogs("openemux.ui.controller_drawing", level="WARNING") as logs:
            drawing = ControllerDrawing(layout, on_activate=lambda _a: None)
        self.assertEqual(len(logs.output), 2)
        self.assertEqual(len(drawing._layers), 1)
        self.assertEqual(set(drawing.buttons), {"a", "b"})
        # No background, no body to carry on beside it: the card's own colour
        # shows there, and drawing it is still harmless.
        self.assertIsNone(drawing._body)
        window = Gtk.Window()
        window.set_child(drawing)
        self.addCleanup(window.destroy)
        drawing.allocate(300, 100, -1, None)
        snapshot = Gtk.Snapshot()
        drawing.do_snapshot(snapshot)
        node = snapshot.to_node()
        self.assertNotIsInstance(node, Gsk.LinearGradientNode)
        # Lighting a control whose image did not load is harmless: the target
        # still takes its glow, there is just no image to brighten under it.
        drawing.set_lit({"b"})
        self.assertTrue(drawing.buttons["b"][0].has_css_class("lit"))
        drawing.do_snapshot(Gtk.Snapshot())


def _children(widget):
    child = widget.get_first_child()
    while child is not None:
        yield child
        child = child.get_next_sibling()


if __name__ == "__main__":
    unittest.main()
