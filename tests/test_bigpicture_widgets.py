"""The pieces Big Picture's pages are made of (issues 914, 957)."""

import unittest
from unittest import mock

from tests.gtk_display import HAVE_DISPLAY, needs_display

if HAVE_DISPLAY:
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gdk, GLib, Gtk, Pango

    Adw.init()

    from openemux.ui.bigpicture import widgets
    from openemux.ui.bigpicture.widgets import (
        ROW_ACTION,
        ROW_CHOICE,
        ROW_INFO,
        ROW_NUMBER,
        ROW_SWITCH,
        ROW_TEXT,
        Banner,
        Chip,
        HintBar,
        PixelIcon,
        Row,
        Segments,
        Tile,
        pick_pixel_art,
        pixel_icon_geometry,
    )
    from openemux.ui.bigpicture.rail import NavRail


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
class TileTests(unittest.TestCase):
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

    def test_a_tile_name_stays_on_one_line_and_never_breaks_a_word(self):
        # Issue 955: wrapped names were squeezed to a few characters and
        # Pango hyphenated them ("Bu-scar", "Compartilh-ar por perto").
        wide = Tile("Compartilhar por perto", icon_name="send-to-symbolic", wide=True)
        tall = Tile("Jogados recentemente", "3 jogos", badge="REC")
        for tile in (wide, tall):
            label = tile.name_label
            self.assertFalse(label.get_wrap())
            self.assertTrue(label.get_single_line_mode())
            self.assertEqual(tile.count_label.get_ellipsize(), Pango.EllipsizeMode.END)
        # A wide tile's minimum is its whole name, so a strip cannot squeeze it...
        self.assertEqual(wide.name_label.get_ellipsize(), Pango.EllipsizeMode.NONE)
        name_min, name_nat, _b, _bb = wide.name_label.measure(Gtk.Orientation.HORIZONTAL, -1)
        tile_min, _n, _b, _bb = wide.measure(Gtk.Orientation.HORIZONTAL, -1)
        self.assertEqual(name_min, name_nat)
        self.assertGreater(tile_min, name_min)
        # ... up to a cap, past which it ellipsizes.
        capped = Tile("x" * (widgets.TILE_NAME_CHARS + 10), wide=True)
        self.assertEqual(capped.name_label.get_ellipsize(), Pango.EllipsizeMode.END)
        self.assertEqual(capped.name_label.get_width_chars(), widgets.TILE_NAME_CHARS)
        self.assertEqual(capped.name_label.get_max_width_chars(), widgets.TILE_NAME_CHARS)
        self.assertEqual(Tile(None, wide=True).name_label.get_ellipsize(), Pango.EllipsizeMode.NONE)
        self.assertEqual(tall.name_label.get_ellipsize(), Pango.EllipsizeMode.END)
        # In a fixed grid (the quick menu) the grid sets the width instead.
        gridded = Tile("Synchroniser les jaquettes", "x", wide=True, fit_name=False)
        self.assertEqual(gridded.name_label.get_ellipsize(), Pango.EllipsizeMode.END)
        self.assertEqual(gridded.name_label.get_max_width_chars(), 1)
        # A gridded tile with no count fills its cell instead of shrinking
        # its name to the ellipsis ("Quit OpenEmux" in the quick menu).
        alone = Tile("Quitter OpenEmux", wide=True, fit_name=False)
        self.assertEqual(alone.get_child().get_halign(), Gtk.Align.FILL)
        self.assertEqual(wide.get_child().get_halign(), Gtk.Align.START)
        # A tall tile's name never widens it: every console tile is one width.
        self.assertEqual(tall.name_label.get_max_width_chars(), 1)
        self.assertEqual(tall.count_label.get_max_width_chars(), 1)
        # ... and never stretches it: a short Consoles row keeps 240 px tiles.
        self.assertFalse(tall.compute_expand(Gtk.Orientation.HORIZONTAL))
        self.assertFalse(wide.compute_expand(Gtk.Orientation.HORIZONTAL))
        self.assertEqual(tall.badge.get_halign(), Gtk.Align.CENTER)
        self.assertEqual(wide.badge.get_halign(), Gtk.Align.START)
        short_min, _n, _b, _bb = Tile("Todos", badge="REC").measure(Gtk.Orientation.HORIZONTAL, -1)
        long_min, _n, _b, _bb = tall.measure(Gtk.Orientation.HORIZONTAL, -1)
        self.assertEqual(short_min, long_min)

    def test_a_row_shows_a_tag_before_its_value(self):
        row = Row("Core", kind=ROW_CHOICE, value="Snes9x")
        self.assertFalse(row.tag_label.get_visible())
        row.set_tag("DEFAULT")
        self.assertTrue(row.tag_label.get_visible())
        self.assertEqual(row.tag_label.get_label(), "DEFAULT")
        row.set_tag(None)
        self.assertFalse(row.tag_label.get_visible())


@needs_display
class TheAndroidPiecesTests(unittest.TestCase):
    def test_chips_mark_current_and_on(self):
        calls = []
        chip = Chip("NES", on_activate=lambda: calls.append(1))
        self.assertTrue(chip.has_css_class("bp-chip"))
        chip.emit("clicked")
        self.assertEqual(calls, [1])
        chip.set_current(True)
        self.assertTrue(chip.has_css_class("bp-current"))
        chip.set_current(False)
        self.assertFalse(chip.has_css_class("bp-current"))
        chip.set_on(True)
        self.assertTrue(chip.is_on())
        chip.set_on(False)
        self.assertFalse(chip.is_on())
        Chip("quiet").emit("clicked")

    def test_a_chip_with_an_icon_keeps_its_label(self):
        icon = Gtk.Image.new_from_icon_name("starred-symbolic")
        chip = Chip("Favorites", icon=icon)
        self.assertTrue(chip.has_css_class("bp-chip-icon"))
        self.assertIs(chip.icon, icon)
        self.assertIs(icon.get_next_sibling(), chip.text)
        self.assertEqual(chip.get_label(), "Favorites")
        chip.set_label("Stars")
        self.assertEqual(chip.get_label(), "Stars")
        self.assertEqual(chip.text.get_label(), "Stars")
        plain = Chip("NES")
        self.assertFalse(plain.has_css_class("bp-chip-icon"))
        plain.set_label("SNES")
        self.assertEqual(plain.get_label(), "SNES")

    def test_pixel_art_stays_on_whole_multiples(self):
        # A slot the art's size: 1x, crisp.
        self.assertEqual(pixel_icon_geometry(32, 32, 32), (0, 0, 32, True))
        # Bigger, but not twice: still 1x, centred.
        self.assertEqual(pixel_icon_geometry(40, 40, 32), (4, 4, 32, True))
        # Twice or more: the whole multiple that fits.
        self.assertEqual(pixel_icon_geometry(70, 64, 32), (3, 0, 64, True))
        # Smaller than the art: drawn at the slot, smooth.
        self.assertEqual(pixel_icon_geometry(21, 25, 32), (0, 2, 21, False))
        # Nothing to draw into; no art.
        self.assertEqual(pixel_icon_geometry(0, 0, 32), (0, 0, 0, False))
        self.assertEqual(pixel_icon_geometry(32, 32, 0), (16, 16, 0, True))

    def test_the_art_size_that_fills_the_slot_crisply_wins(self):
        # 1080p: both fill 32 px; the 32-px art has the detail.
        self.assertEqual(pick_pixel_art(32, 32, [32, 16]), (0, 0, 0, 32, True))
        # 720p: the 32-px art would shrink; the 16-px one stays crisp at 1x.
        self.assertEqual(pick_pixel_art(21, 21, [32, 16]), (1, 2, 2, 16, True))
        # A bigger text size: the 16-px art at 3x is bigger than the 32-px at 1x.
        self.assertEqual(pick_pixel_art(48, 48, [32, 16]), (1, 0, 0, 48, True))
        # Smaller than every size: the biggest art, smooth.
        self.assertEqual(pick_pixel_art(12, 12, [16, 32]), (1, 0, 0, 12, False))

    def _texture(self, side=32):
        data = GLib.Bytes.new(bytes([255, 0, 0, 255]) * side * side)
        return Gdk.MemoryTexture.new(side, side, Gdk.MemoryFormat.R8G8B8A8, data, side * 4)

    def test_a_pixel_icon_draws_its_texture(self):
        icon = PixelIcon([self._texture()])
        self.assertTrue(icon.has_css_class("bp-chip-art"))
        snapshot = Gtk.Snapshot()
        with mock.patch.object(icon, "get_width", return_value=32), \
                mock.patch.object(icon, "get_height", return_value=32):
            icon.do_snapshot(snapshot)
        node = snapshot.to_node()
        self.assertIsNotNone(node)
        self.assertEqual(node.get_bounds().get_width(), 32)
        # Smaller than the art: still drawn, with the smooth filter.
        snapshot = Gtk.Snapshot()
        with mock.patch.object(icon, "get_width", return_value=20), \
                mock.patch.object(icon, "get_height", return_value=20):
            icon.do_snapshot(snapshot)
        self.assertEqual(snapshot.to_node().get_bounds().get_width(), 20)

    def test_a_pixel_icon_with_no_room_draws_nothing(self):
        icon = PixelIcon([self._texture()])
        snapshot = Gtk.Snapshot()
        icon.do_snapshot(snapshot)  # unallocated: 0 x 0
        self.assertIsNone(snapshot.to_node())

    def test_segments_pick_and_mark(self):
        picked = []
        segments = Segments([("a", "view-grid-symbolic", "A"), ("b", "view-list-symbolic", "B")], picked.append)
        segments.buttons["b"].emit("clicked")
        self.assertEqual(picked, ["b"])
        segments.set_current("a")
        self.assertEqual(segments.current, "a")
        self.assertTrue(segments.buttons["a"].has_css_class("bp-current"))
        self.assertFalse(segments.buttons["b"].has_css_class("bp-current"))

    def test_a_banner_shows_its_task_and_progress(self):
        calls = []
        banner = Banner(on_activate=lambda: calls.append(1))
        banner.show("Fetching labels", "19 of 133", 19 / 133)
        self.assertEqual(banner.title_label.get_label(), "Fetching labels")
        self.assertEqual(banner.detail_label.get_label(), "· 19 of 133")
        self.assertTrue(banner.progress.get_visible())
        banner.show("Scanning", None, 4.0)
        self.assertEqual(banner.progress.get_fraction(), 1.0)
        banner.show("Waiting")
        self.assertFalse(banner.progress.get_visible())
        self.assertEqual(banner.detail_label.get_label(), "")
        banner.emit("clicked")
        self.assertEqual(calls, [1])
        Banner().emit("clicked")

    def test_the_small_helpers(self):
        state = widgets.empty_state("view-reveal-symbolic", "Nothing here")
        self.assertEqual(state.label.get_label(), "Nothing here")
        heading = widgets.page_heading("Shelf", "3 games")
        self.assertTrue(heading.subtitle_label.get_visible())
        self.assertFalse(widgets.page_heading("Shelf").subtitle_label.get_visible())
        self.assertEqual(widgets.caps("Appearance").get_label(), "APPEARANCE")
        calls = []
        button = widgets.icon_button("starred-symbolic", "Favorite", lambda: calls.append(1))
        button.emit("clicked")
        self.assertEqual(calls, [1])
        self.assertIsNone(widgets.icon_button("starred-symbolic").get_tooltip_text())
        self.assertEqual(widgets.console_badge_text("sfcxyz"), "SFCX")

    def test_the_navigation_rail(self):
        picked = []
        rail = NavRail(lambda key: key, picked.append)
        self.assertEqual(rail.current, "library")
        self.assertFalse(rail.get_hexpand())
        rail.buttons["import"].emit("clicked")
        self.assertEqual(picked, ["import"])
        rail.mark("settings")
        self.assertTrue(rail.buttons["settings"].has_css_class("bp-current"))
        self.assertFalse(rail.buttons["library"].has_css_class("bp-current"))
        self.assertEqual(rail.neighbour(1), "library")
        rail.current = "nowhere"
        self.assertEqual(rail.neighbour(1), "recent")

    def test_the_rail_ends_with_back_to_desktop(self):
        # Issue 978: after Settings, drawn like a tab, but an action.
        left = []
        rail = NavRail(lambda key: key, lambda _tab: None, lambda: left.append(True))
        children = []
        child = rail.get_first_child()
        while child is not None:
            children.append(child)
            child = child.get_next_sibling()
        self.assertIs(children[-1], rail.desktop)
        self.assertIs(children[-2], rail.buttons["settings"])
        self.assertEqual(rail.desktop.label.get_label(), "big_picture.tab.desktop")
        self.assertTrue(rail.desktop.label.get_wrap())
        self.assertNotIn("desktop", rail.buttons)
        rail.desktop.emit("clicked")
        self.assertEqual(left, [True])
        rail.mark("desktop")
        self.assertFalse(rail.desktop.has_css_class("bp-current"))
        rail.mark("settings")
        self.assertEqual(rail.neighbour(1), "library")
        rail.retranslate(lambda key: key.upper())
        self.assertEqual(rail.desktop.label.get_label(), "BIG_PICTURE.TAB.DESKTOP")
        # With nobody to tell, a click does nothing.
        NavRail(lambda key: key, lambda _tab: None).desktop.emit("clicked")


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
        # Centered, as on Android.
        self.assertEqual(bar.row.get_halign(), Gtk.Align.CENTER)
        # The clock at the right end, balanced by a spacer as wide on the left
        # so the hints stay centred on the bar (issue 977).
        center = bar.get_first_child()
        self.assertIsInstance(center, Gtk.CenterBox)
        self.assertIs(center.get_center_widget(), bar.row)
        self.assertIs(center.get_end_widget(), bar.clock)
        self.assertTrue(bar.clock.has_css_class("bp-clock"))
        self.assertTrue(bar.clock.has_css_class("bp-hint"))
        self.assertIn(center.get_start_widget(), bar._balance.get_widgets())
        self.assertIn(bar.clock, bar._balance.get_widgets())

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
        page = widgets.BigPage(shell, "Title", crumbs=["A", "B"], tag="bp-x")
        self.assertEqual(page.get_tag(), "bp-x")
        self.assertTrue(page.top_bar.get_visible())
        # The top bar holds the crumb and nothing else: the clock is in the
        # hint bar now (issue 977).
        self.assertIs(page.top_bar.get_first_child(), page.crumb_host)
        self.assertIsNone(page.crumb_host.get_next_sibling())
        # No crumbs at all: a tab's first page has its own big title, and no
        # strip above it.
        bare = widgets.BigPage(shell, "Shelf", crumbs=[])
        self.assertIsNone(bare.crumb_host.get_first_child().get_first_child())
        self.assertFalse(bare.top_bar.get_visible())
        bare.set_crumbs(["", None])
        self.assertFalse(bare.top_bar.get_visible())
        bare.set_crumbs(["Later"])
        self.assertTrue(bare.top_bar.get_visible())
        page.set_crumbs(["C"])
        self.assertIsInstance(page.scrolled(Gtk.Box()), Gtk.ScrolledWindow)
        self.assertEqual(page.hints({"confirm": "A", "back": "B"}, shell.win.t), [("A", "hints.confirm"), ("B", "hints.back")])
        self.assertFalse(page.focus_default())
        self.assertFalse(page.on_shown())
        self.assertEqual(page.context, "bp-page")


if __name__ == "__main__":
    unittest.main()
