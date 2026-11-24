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
            self.assertIn(f".big-picture .bp-scroller > viewport > * {{\n    margin-left: {mat}px;", css)
            self.assertIn(f".big-picture .bp-scroller-vertical > viewport > * {{\n    margin-top: {mat}px;", css)
            self.assertIn(f".big-picture gridview > child {{\n    padding-top: {mat}px;", css)


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

    def test_the_desktop_keeps_its_scrollbars(self):
        self.leave()
        desktop = [s for s in scrollers_under(self.win.content_overlay) if s.get_mapped()]
        self.assertTrue(desktop)
        self.assertTrue(any(bar_thickness(s) > 0 for s in desktop))


if __name__ == "__main__":
    unittest.main()
