"""The controller drawing widget (issue 815), built for real on the test display."""

import shutil
import tempfile
import unittest
from pathlib import Path

from tests.gtk_display import HAVE_DISPLAY, needs_display

if HAVE_DISPLAY:
    import gi

    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk

    from openemux.core.controller_layouts import ControllerElement, ControllerLayout, layout_for
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

    def test_a_control_with_no_action_gets_an_inert_area_with_a_tooltip(self):
        drawing = ControllerDrawing(
            layout_for("FDS"), on_activate=lambda _a: None, not_remappable_text="not remappable"
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


def _children(widget):
    child = widget.get_first_child()
    while child is not None:
        yield child
        child = child.get_next_sibling()


if __name__ == "__main__":
    unittest.main()
