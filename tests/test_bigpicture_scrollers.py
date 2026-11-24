"""Big Picture's scrollers: no scrollbar, and room for the focus mat (issue 999).

The pad drives the mode on a TV, so no scroller in it may draw a scrollbar,
while the desktop keeps its own. And the focus mat, drawn outside its item,
must not be cut where a scroller clips: the content gets a gutter inside it.
"""

# Builds real windows through tests.window_harness (via BigPictureCase): CI runs this
# module in the windowed process, with the other window tests.

import unittest
from unittest import mock

from tests.bigpicture_harness import BigPictureCase
from tests.gtk_display import HAVE_DISPLAY, needs_display

if HAVE_DISPLAY:
    import gi

    gi.require_version("Graphene", "1.0")
    from gi.repository import Graphene, Gtk

    from openemux.ui.bigpicture import widgets

# Pure Python: the stylesheet's tests run with no display at all.
from openemux.ui.bigpicture import theme  # noqa: E402


def scrollers_under(root):
    """Every ``Gtk.ScrolledWindow`` in ``root``'s widget tree, ``root`` included."""
    found = []
    pending = [root]
    while pending:
        widget = pending.pop()
        if isinstance(widget, Gtk.ScrolledWindow):
            found.append(widget)
        child = widget.get_first_child()
        while child is not None:
            pending.append(child)
            child = child.get_next_sibling()
    return found


def bar_thickness(scroller):
    """How much room each of ``scroller``'s bars asks for across itself, in px."""
    vertical = scroller.get_vscrollbar().measure(Gtk.Orientation.HORIZONTAL, -1)
    horizontal = scroller.get_hscrollbar().measure(Gtk.Orientation.VERTICAL, -1)
    return max(vertical[0], vertical[1], horizontal[0], horizontal[1])


class TheStylesheet(unittest.TestCase):
    def test_scrollbars_are_hidden_only_in_the_mode(self):
        css = theme.stylesheet(1.0)
        rule = css.split(".big-picture scrollbar,", 1)[1].split("}", 1)[0]
        for declaration in ("opacity: 0;", "min-width: 0;", "min-height: 0;", "margin: 0;", "padding: 0;"):
            self.assertIn(declaration, rule)
        # Every scrollbar selector is scoped: the desktop keeps its scrollbars.
        selectors = [line for line in css.splitlines() if "scrollbar" in line and line[:1] not in (" ", "/")]
        self.assertEqual(len(selectors), 3)
        for line in selectors:
            self.assertTrue(line.startswith(".big-picture "), line)

    def test_the_gutter_is_the_focus_mat_at_scale(self):
        for scale in (1.0, 0.667, 2.0):
            mat = theme.px("focus_mat", scale)
            css = theme.stylesheet(scale)
            self.assertIn(f"margin-left: -{mat}px;", css)
            self.assertIn(f"margin-right: -{mat}px;", css)
            self.assertIn(f"min-width: {2 * mat}px;", css)
            self.assertIn(f".big-picture .bp-scroller > viewport > * {{\n    margin-left: {mat}px;", css)
            # Room below the last item only: the top of a page stays where it was.
            self.assertIn(f".big-picture .bp-scroller-vertical > viewport > * {{\n    margin-bottom: {mat}px;\n}}", css)
            self.assertNotIn(".bp-scroller-vertical {", css)
        # The games grid's cells keep their size: a dormant grid reports the
        # rows it will take from the card alone (grid.py, _dormant_height).
        self.assertNotIn("gridview > child {", theme.stylesheet(1.0))


@needs_display
class TheHelper(unittest.TestCase):
    def test_a_row_scrolls_sideways_and_hugs_its_content(self):
        box = Gtk.Box()
        scroller = widgets.bp_scroller(box, horizontal=True)
        self.assertIs(scroller.get_child().get_child(), box)
        self.assertEqual(scroller.get_policy(), (Gtk.PolicyType.EXTERNAL, Gtk.PolicyType.NEVER))
        self.assertTrue(scroller.get_propagate_natural_height())
        self.assertTrue(scroller.has_css_class("bp-scroller"))
        self.assertFalse(scroller.has_css_class("bp-scroller-vertical"))
        self.assertFalse(scroller.get_vexpand())

    def test_a_page_scrolls_down_and_fills_the_body(self):
        box = Gtk.Box()
        scroller = widgets.bp_scroller(box)
        self.assertIs(scroller.get_child().get_child(), box)
        self.assertEqual(scroller.get_policy(), (Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC))
        self.assertTrue(scroller.has_css_class("bp-scroller"))
        self.assertTrue(scroller.has_css_class("bp-scroller-vertical"))
        self.assertTrue(scroller.get_vexpand())


def _adjustment(value=0.0, upper=1000.0, page=100.0):
    return Gtk.Adjustment(value=value, lower=0.0, upper=upper, step_increment=10.0,
                          page_increment=page, page_size=page)


@needs_display
class TheWheelOnARow(unittest.TestCase):
    def test_the_wheel_moves_a_row_sideways(self):
        row = widgets.bp_scroller(Gtk.Box(), horizontal=True)
        row.set_hadjustment(_adjustment())
        self.assertTrue(widgets.wheel_sideways(row, 1.0))
        self.assertEqual(row.get_hadjustment().get_value(), 25.0)
        self.assertTrue(widgets.wheel_sideways(row, -4.0))
        self.assertEqual(row.get_hadjustment().get_value(), 0.0)
        row.get_hadjustment().set_value(890.0)
        widgets.wheel_sideways(row, 2.0)
        self.assertEqual(row.get_hadjustment().get_value(), 900.0)
        self.assertFalse(widgets.wheel_sideways(row, 0.0))
        controllers = [c for c in row.observe_controllers() if isinstance(c, Gtk.EventControllerScroll)]
        self.assertTrue(any(c.emit("scroll", 0.0, 1.0) for c in controllers))
        self.assertEqual(row.get_hadjustment().get_value(), 900.0)

    def test_no_adjustment_no_wheel(self):
        row = mock.Mock()
        row.get_hadjustment.return_value = None
        self.assertFalse(widgets.wheel_sideways(row, 1.0))

    def test_a_page_has_no_sideways_wheel(self):
        page = widgets.bp_scroller(Gtk.Box())
        self.assertFalse([c for c in page.observe_controllers() if isinstance(c, Gtk.EventControllerScroll)
                          and c.get_flags() == Gtk.EventControllerScrollFlags.VERTICAL])


class _Bounds:
    def __init__(self, x, y, w, h):
        self.x, self.y, self.w, self.h = x, y, w, h

    def get_x(self):
        return self.x

    def get_y(self):
        return self.y

    def get_width(self):
        return self.w

    def get_height(self):
        return self.h


@needs_display
class RevealingTheMat(unittest.TestCase):
    def scroller(self, width=100, height=100, hadj=None, vadj=None):
        scroller = mock.Mock()
        scroller.get_width.return_value = width
        scroller.get_height.return_value = height
        scroller.get_hadjustment.return_value = hadj
        scroller.get_vadjustment.return_value = vadj
        return scroller

    def item(self, scroller, bounds):
        item = mock.Mock()
        item.get_ancestor.return_value = scroller
        item.compute_bounds.return_value = (bounds is not None, bounds)
        return item

    def test_an_item_outside_any_scroller_is_left_alone(self):
        self.assertFalse(widgets.reveal_whole(self.item(None, None), 9))

    def test_an_item_with_no_bounds_is_left_alone(self):
        self.assertFalse(widgets.reveal_whole(self.item(self.scroller(), None), 9))

    def test_the_mat_below_the_fold_scrolls_in(self):
        vadj = _adjustment(value=100.0)
        scroller = self.scroller(vadj=vadj)
        self.assertTrue(widgets.reveal_whole(self.item(scroller, _Bounds(0, 50, 50, 45)), 9))
        self.assertEqual(vadj.get_value(), 104.0)

    def test_the_mat_above_the_fold_scrolls_in(self):
        hadj = _adjustment(value=100.0)
        scroller = self.scroller(hadj=hadj)
        self.assertTrue(widgets.reveal_whole(self.item(scroller, _Bounds(3, 20, 40, 40)), 9))
        self.assertEqual(hadj.get_value(), 94.0)

    def test_an_item_with_room_or_too_big_or_at_the_end_stays(self):
        vadj = _adjustment(value=0.0)
        scroller = self.scroller(vadj=vadj, hadj=_adjustment())
        self.assertFalse(widgets.reveal_whole(self.item(scroller, _Bounds(20, 20, 40, 40)), 9))
        self.assertFalse(widgets.reveal_whole(self.item(scroller, _Bounds(20, 0, 40, 95)), 9))
        # Already at the top: there is nothing above to scroll to.
        self.assertFalse(widgets.reveal_whole(self.item(scroller, _Bounds(20, 2, 40, 40)), 9))
        self.assertFalse(widgets.reveal_whole(self.item(self.scroller(width=0, hadj=_adjustment()), _Bounds(20, 2, 40, 40)), 9))


@needs_display
class NoScrollbarInTheMode(BigPictureCase):
    def setUp(self):
        super().setUp()
        self.show()

    def open_every_page(self):
        """Each Big Picture page with a scroller, pushed one after the other."""
        shell = self.shell
        game = self.rom("SFC")
        shell.open_library("SFC")
        self.pump()
        with mock.patch("openemux.ui.bigpicture.details.cover_cache.submit", side_effect=lambda fn, *a, **k: fn()):
            shell.open_details(game)
            self.pump()
        shell.open_recent()
        shell.open_import()
        shell.open_browser("files", lambda _path: None)
        shell.open_chooser("Pick", [{"id": "a", "label": "A"}], "a", lambda _id: None)
        shell.open_settings()
        shell.open_settings("input", console="SFC")
        self.pump()

    def test_no_scroller_in_the_mode_takes_room_for_a_bar(self):
        self.open_every_page()
        found = scrollers_under(self.win)
        # The pages above, the chips and the borrowed desktop grid at least.
        self.assertGreater(len(found), 8)
        for scroller in found:
            self.assertEqual(bar_thickness(scroller), 0, scroller)

    def test_the_mode_builds_every_scroller_with_the_gutter(self):
        self.open_every_page()
        content = self.win.content_overlay
        for scroller in scrollers_under(self.shell):
            if scroller.is_ancestor(content):
                continue  # the desktop's own page, borrowed
            self.assertTrue(scroller.has_css_class("bp-scroller"), scroller)

    def test_the_focus_mat_of_a_card_at_the_row_end_is_inside_the_clip(self):
        page = self.shell.shelf
        self.assertTrue(self.pump_until(lambda: page.scroller.get_width() > 0))
        mat = theme.px("focus_mat", self.shell.scale())
        viewport = page.scroller.get_child()
        width = viewport.get_width()
        for card in page.cards:
            ok, bounds = card.compute_bounds(viewport)
            self.assertTrue(ok)
            self.assertGreaterEqual(bounds.get_x(), mat)
            self.assertLessEqual(bounds.get_x() + bounds.get_width(), width - mat)
        # The cards still sit on the page margin: the gutter is given back.
        ok, origin = page.grid.compute_point(page, Graphene.Point())
        self.assertTrue(ok)
        ok, body = page.body.compute_point(page, Graphene.Point())
        self.assertTrue(ok)
        self.assertEqual(origin.x, body.x)
        self.assertEqual(page.grid.get_width(), page.body.get_width())

    def test_the_shell_reveals_the_mat_of_the_new_focus(self):
        page = self.shell.shelf
        card = page.cards[-1]
        with mock.patch("openemux.ui.bigpicture.shell.reveal_whole") as reveal:
            card.grab_focus()
            self.pump()
            self.assertTrue(reveal.called)
            self.assertIs(reveal.call_args.args[0], card)
            self.assertEqual(reveal.call_args.args[1], theme.px("focus_mat", self.shell._scale or self.shell.scale()))
            reveal.reset_mock()
            # The focus moved on before the idle ran: nothing for the old one.
            self.shell._reveal_focus(page.cards[0])
            reveal.assert_not_called()
            # Out of the mode, the shell leaves the desktop's focus alone.
            self.leave()
            reveal.reset_mock()
            self.win.set_focus(None)
            self.shell._on_focus_moved(self.win, None)
            self.pump()
            reveal.assert_not_called()

    def test_the_desktop_keeps_its_scrollbars(self):
        self.leave()
        desktop = [s for s in scrollers_under(self.win.content_overlay) if s.get_mapped()]
        self.assertTrue(desktop)
        self.assertTrue(any(bar_thickness(s) > 0 for s in desktop))


if __name__ == "__main__":
    unittest.main()
