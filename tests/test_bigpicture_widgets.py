"""The pieces Big Picture's pages are made of (issue 914)."""

import time
import unittest
from unittest import mock

from tests.gtk_display import HAVE_DISPLAY, needs_display

if HAVE_DISPLAY:
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gdk, GLib, Gtk

    Adw.init()

    from openemux.ui.bigpicture import widgets
    from openemux.ui.bigpicture.widgets import (
        ROW_ACTION,
        ROW_CHOICE,
        ROW_INFO,
        ROW_NUMBER,
        ROW_SWITCH,
        ROW_TEXT,
        HintBar,
        Rail,
        RailTile,
        Row,
        Tile,
    )
    from openemux.ui.scopes import ALL_CONSOLES_ID, FAVORITES_ID, RECENT_ID


def _pump():
    context = GLib.MainContext.default()
    while context.pending():
        context.iteration(False)


@needs_display
class RowTests(unittest.TestCase):
    def test_an_action_row_reports_its_activation(self):
        calls = []
        row = Row("Title", "Subtitle", kind=ROW_ACTION, value="v", on_activate=lambda: calls.append(1),
                  icon_name="folder-symbolic")
        row.emit("clicked")
        self.assertEqual(calls, [1])
        self.assertEqual(row.value_label.get_label(), "v")
        row.set_value(None)
        self.assertEqual(row.value_label.get_label(), "")
        row.set_subtitle("")
        self.assertFalse(row.subtitle_label.get_visible())
        row.set_subtitle("again")
        self.assertTrue(row.subtitle_label.get_visible())
        self.assertFalse(row.step(1))
        self.assertFalse(row.get_active())
        row.set_active(True)  # not a switch row: nothing to set

    def test_a_row_with_no_handler_is_harmless(self):
        Row("Title", kind=ROW_ACTION).emit("clicked")
        Row("Title", kind=ROW_CHOICE, destructive=True, primary=True).emit("clicked")

    def test_a_switch_row_flips_and_reports(self):
        states = []
        row = Row("Tips", kind=ROW_SWITCH, active=False, on_activate=states.append)
        self.assertFalse(row.get_active())
        row.emit("clicked")
        self.assertEqual(states, [True])
        self.assertTrue(row.get_active())
        row.set_active(False)
        self.assertFalse(row.get_active())
        Row("Quiet", kind=ROW_SWITCH).emit("clicked")

    def test_a_number_row_steps_with_left_and_right(self):
        steps = []
        row = Row("Deadzone", kind=ROW_NUMBER, value=0.15, on_step=steps.append)
        self.assertEqual(row.number_label.get_label(), "0.15")
        self.assertTrue(row.step(1))
        self.assertTrue(row._on_key_pressed(None, Gdk.KEY_Left, 0, 0))
        self.assertTrue(row._on_key_pressed(None, Gdk.KEY_Right, 0, 0))
        self.assertFalse(row._on_key_pressed(None, Gdk.KEY_a, 0, 0))
        self.assertEqual(steps, [1, -1, 1])
        row.set_value("0.2")
        self.assertEqual(row.number_label.get_label(), "0.2")
        self.assertFalse(Row("Quiet", kind=ROW_NUMBER).step(1))

    def test_text_and_info_rows(self):
        row = Row("Name", kind=ROW_TEXT, value="Sala")
        self.assertEqual(row.value_label.get_label(), "Sala")
        info = Row("Status", "ok", kind=ROW_INFO)
        self.assertFalse(info.get_can_focus())
        self.assertFalse(info.get_sensitive())


@needs_display
class TileAndRailTests(unittest.TestCase):
    def test_a_tile_shows_a_badge_an_icon_or_a_picture(self):
        calls = []
        tile = Tile("All games", "3 games", badge="ALL", style="bp-all", on_activate=lambda: calls.append(1))
        tile.emit("clicked")
        self.assertEqual(calls, [1])
        self.assertTrue(tile.has_css_class("bp-all"))
        tile.set_count(None)
        self.assertFalse(tile.count_label.get_visible())
        tile.set_count("1 game")
        self.assertTrue(tile.count_label.get_visible())
        Tile("Search", icon_name="system-search-symbolic", wide=True).emit("clicked")
        texture = Gdk.Texture.new_for_pixbuf(
            __import__("gi.repository", fromlist=["GdkPixbuf"]).GdkPixbuf.Pixbuf.new(
                __import__("gi.repository", fromlist=["GdkPixbuf"]).GdkPixbuf.Colorspace.RGB, True, 8, 4, 4
            )
        )
        picture = widgets.make_badge(texture=texture)
        self.assertIsInstance(picture, Gtk.Picture)
        self.assertEqual(widgets.console_badge_text("vectrex"), "VECT")
        self.assertEqual(widgets.console_badge_text(None), "")

    def test_rail_entries_by_scope_kind(self):
        self.assertEqual(widgets.rail_entry_for_scope(ALL_CONSOLES_ID, "All", "all")[5], "bp-all")
        self.assertEqual(widgets.rail_entry_for_scope(FAVORITES_ID, "Fav", "favorites")[2], "★")
        self.assertEqual(widgets.rail_entry_for_scope(RECENT_ID, "Recent", "recent")[4], "document-open-recent-symbolic")
        self.assertEqual(widgets.rail_entry_for_scope("col:x", "X", "collection")[4], "user-bookmarks-symbolic")
        with_texture = widgets.rail_entry_for_scope("SFC", "Super Nintendo", "console")
        self.assertIsNotNone(with_texture[3])
        without = widgets.rail_entry_for_scope("ZZZ", "Nothing", "console")
        self.assertEqual(without[2], "ZZZ")

    def test_the_rail_selects_steps_and_wraps(self):
        picked = []
        rail = Rail(picked.append)
        rail.set_entries([
            widgets.rail_entry_for_scope(ALL_CONSOLES_ID, "All", "all"),
            widgets.rail_entry_for_scope("FC", "NES", "console"),
            widgets.rail_entry_for_scope("SFC", "SNES", "console"),
        ])
        self.assertEqual(rail.ids(), [ALL_CONSOLES_ID, "FC", "SFC"])
        self.assertFalse(rail.move(1) and False)  # nothing current yet: lands on the first + 1
        self.assertEqual(picked, ["FC"])
        self.assertTrue(rail.select("SFC"))
        self.assertFalse(rail.select("SFC"))
        self.assertFalse(rail.select(None))
        self.assertFalse(rail.select("nope"))
        self.assertTrue(rail.move(1))
        self.assertEqual(rail.current_id, ALL_CONSOLES_ID)
        self.assertTrue(rail.move(-1))
        self.assertEqual(rail.current_id, "SFC")
        self.assertIsNone(rail.tile_for("nope"))
        rail.set_shoulder_labels("L", "R")
        self.assertEqual(rail.left_shoulder.get_label(), "L")
        rail.tiles[0].emit("clicked")
        self.assertEqual(rail.current_id, ALL_CONSOLES_ID)
        # Not laid out yet: nothing to scroll to.
        with mock.patch.object(rail.tiles[0], "get_allocation", return_value=mock.Mock(width=0)):
            self.assertEqual(rail._scroll_to(rail.tiles[0]), GLib.SOURCE_REMOVE)
        rail.set_entries([])
        self.assertFalse(rail.move(1))
        self.assertFalse(rail.focus_current())

    def test_the_rail_scrolls_the_current_tile_into_view(self):
        rail = Rail(lambda _id: None)
        rail.set_entries([widgets.rail_entry_for_scope(f"C{i}", f"Console {i}", "console") for i in range(12)])
        window = Gtk.Window()
        window.set_default_size(400, 200)
        window.set_child(rail)
        window.present()
        adjustment = rail.scroller.get_hadjustment()
        # The strip is only measured once the window is laid out, which
        # happens on the frame clock, not on present(): wait for it.
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline and adjustment.get_upper() <= adjustment.get_page_size():
            _pump()
            time.sleep(0.01)
        self.assertGreater(adjustment.get_upper(), adjustment.get_page_size())
        rail.mark_current("C11")
        _pump()
        self.assertGreater(adjustment.get_value(), 0)
        rail.mark_current("C0")
        _pump()
        self.assertEqual(adjustment.get_value(), 0)
        self.assertTrue(rail.focus_current())
        window.destroy()

    def test_a_rail_tile_marks_current(self):
        tile = RailTile("FC", "NES", badge_text="FC")
        tile.set_current(True)
        self.assertTrue(tile.has_css_class("bp-current"))
        tile.set_current(False)
        self.assertFalse(tile.has_css_class("bp-current"))


@needs_display
class HintBarAndHelpersTests(unittest.TestCase):
    def test_the_hint_bar_fills_its_slots_and_marks_confirm(self):
        bar = HintBar()
        bar.set_hints([("A", "Open"), ("B", "Back")], confirm_glyph="A")
        slots = [slot for slot in bar.slots if slot[0].get_visible()]
        self.assertEqual(len(slots), 2)
        self.assertTrue(slots[0][1].has_css_class("bp-confirm"))
        self.assertFalse(slots[1][1].has_css_class("bp-confirm"))
        bar.set_hints([("B", "Back")])
        self.assertFalse(bar.slots[0][1].has_css_class("bp-confirm"))
        bar.set_hints([(str(i), "x") for i in range(12)])
        self.assertEqual(sum(1 for slot in bar.slots if slot[0].get_visible()), widgets.MAX_HINTS)
        bar.set_context("Row 1 of 6")
        self.assertEqual(bar.context_label.get_label(), "Row 1 of 6")
        bar.set_context(None)
        self.assertEqual(bar.context_label.get_label(), "")

    def test_the_crumb_and_the_text_helpers(self):
        crumb = widgets.crumb(["Library", "", "Super Nintendo"])
        labels = []
        child = crumb.get_first_child()
        while child is not None:
            labels.append(child.get_label())
            child = child.get_next_sibling()
        self.assertEqual(labels, ["Library", "›", "Super Nintendo"])
        self.assertTrue(widgets.eyebrow("E").has_css_class("bp-eyebrow"))
        self.assertTrue(widgets.note("N").has_css_class("bp-note"))
        self.assertTrue(widgets.body("B").has_css_class("bp-body"))
        calls = []
        button = widgets.button("Go", lambda: calls.append(1), suggested=True, destructive=True)
        button.emit("clicked")
        self.assertEqual(calls, [1])
        self.assertTrue(button.has_css_class("suggested-action"))
        widgets.button("Quiet").emit("clicked")

    def test_once_runs_a_callback_one_time(self):
        calls = []
        runner = widgets.once(lambda value: calls.append(value) or True, 7)
        self.assertEqual(runner(), GLib.SOURCE_REMOVE)
        self.assertEqual(calls, [7])

    def test_a_big_page_frames_its_body(self):
        shell = mock.Mock()
        shell.win.t = lambda key, **kw: key
        shell.make_status_box = lambda: Gtk.Box()
        page = widgets.BigPage(shell, "Title", crumbs=["A", "B"], tag="bp-x")
        self.assertEqual(page.get_tag(), "bp-x")
        page.set_crumbs(["C"])
        self.assertIsInstance(page.scrolled(Gtk.Box()), Gtk.ScrolledWindow)
        self.assertEqual(page.hints({"confirm": "A", "back": "B"}, shell.win.t), [("A", "hints.confirm"), ("B", "hints.back")])
        self.assertFalse(page.focus_default())
        self.assertFalse(page.on_shown())
        self.assertEqual(page.context, "bp-page")


if __name__ == "__main__":
    unittest.main()
