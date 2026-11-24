"""Issue 1012 on screen: backgrounds, listeners, sizes, Big Picture, preview."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import cairo

from tests.bigpicture_harness import BigPictureCase
from tests.gtk_display import HAVE_DISPLAY, needs_display
from tests.window_harness import WindowCase

if HAVE_DISPLAY:
    import gi

    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import Adw, Gdk, GdkPixbuf, Gtk

    from openemux.core.custom_themes import THEME_KEYS, ThemeStore
    from openemux.ui import theming
    from openemux.ui.theme_preview import ThemePreview, draw_preview


def write_png(path, width=40, height=20):
    pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, width, height)
    pixbuf.fill(0x3366CCFF)
    pixbuf.savev(str(path), "png", [], [])
    return Path(path)


def _reset():
    if theming._provider is not None:
        Gtk.StyleContext.remove_provider_for_display(Gdk.Display.get_default(), theming._provider)
    theming._provider = None
    theming._suspended = False
    theming._applied = ("system", None, {}, None)
    theming._paint = theming.Paint()
    theming._cache_dir = None
    Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.DEFAULT)


def _now(target):
    target()


@needs_display
class _Case(unittest.TestCase):
    def setUp(self):
        _reset()
        self.addCleanup(_reset)
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.images = self.tmp / "images"
        self.images.mkdir()
        write_png(self.images / "library.png")
        self.cache = self.tmp / "cache"
        theming.set_cache_dir(self.cache)
        spawn = mock.patch.object(theming, "_spawn", _now)
        spawn.start()
        self.addCleanup(spawn.stop)
        self.idle = []
        idle = mock.patch.object(theming.GLib, "idle_add",
                                 lambda fn, *args: self.idle.append((fn, args)))
        idle.start()
        self.addCleanup(idle.stop)

    def run_idle(self):
        while self.idle:
            fn, args = self.idle.pop(0)
            fn(*args)

    def css(self):
        # GTK prints a url() back as "none /* FIXME */": what was loaded is
        # read from the text theming loads, while its provider holds any.
        loaded = theming._provider is not None and theming._provider.to_string()
        return theming._stylesheet() if loaded else ""


@needs_display
class BackgroundTests(_Case):
    def test_a_background_lands_after_its_render_and_then_shows(self):
        theming.paint("dark", {"library_image": "library.png"}, self.images)
        self.assertNotIn("background-image", self.css())
        self.run_idle()
        self.assertIn(".library-area { background-image: url(\"file://", self.css())
        self.assertIn("library", theming.current_paint().backgrounds)

    def test_a_cached_background_shows_at_once(self):
        theming.paint("dark", {"library_image": "library.png"}, self.images)
        self.run_idle()
        theming.paint("light", {"library_image": "library.png"}, self.images)
        self.run_idle()
        theming.paint("light", {"library_image": "library.png"}, self.images)
        self.assertIn("background-image", self.css())
        self.assertEqual(self.idle, [])

    def test_a_late_background_does_not_paint_over_a_newer_theme(self):
        theming.paint("dark", {"library_image": "library.png"}, self.images)
        theming.paint("dark", {"card_bg": "#101010"})
        self.run_idle()
        self.assertNotIn("background-image", self.css())

    def test_failed_render_lands_nothing(self):
        with mock.patch.object(theming.theme_images, "render", return_value=None):
            theming.paint("dark", {"library_image": "library.png"}, self.images)
        self.assertEqual(self.idle, [])

    def test_no_cache_dir_no_image_dir_or_missing_file_no_background(self):
        self.assertEqual(theming.prepare_backgrounds("dark", {"library_image": "library.png"}, None), {})
        self.assertEqual(theming.prepare_backgrounds("dark", {"sidebar_image": "sidebar.png"},
                                                     self.images), {})
        theming.set_cache_dir(None)
        self.assertEqual(theming.prepare_backgrounds("dark", {"library_image": "library.png"},
                                                     self.images), {})

    def test_without_on_ready_the_render_still_happens(self):
        theming.prepare_backgrounds("dark", {"library_image": "library.png"}, self.images)
        self.assertEqual(self.idle, [])
        ready = theming.prepare_backgrounds("dark", {"library_image": "library.png"}, self.images)
        self.assertEqual(ready["library"]["fit"], "cover")

    def test_background_settings_take_the_bases_defaults(self):
        self.assertEqual(theming.background_settings("dark", {}, "library"),
                         (40, 0, "#1e1e1e", "cover"))
        self.assertEqual(
            theming.background_settings("light", {"sidebar_image_fit": "tile",
                                                  "sidebar_image_dim": 0}, "sidebar"),
            (0, 0, "#ebebeb", "tile"),
        )

    def test_restore_brings_back_the_images(self):
        store = ThemeStore(self.tmp / "themes")
        theme = store.create("Pics", "dark", {"library_image": "library.png"},
                             images_from=self.images)
        theming.apply_theme(theme.id, store=store)
        self.run_idle()
        theming.paint("dark", {})
        theming.restore()
        self.assertIn("background-image", self.css())

    def test_suspension_keeps_backgrounds_for_after(self):
        theming.paint("dark", {"library_image": "library.png"}, self.images)
        self.run_idle()
        theming.set_suspended(True)
        self.assertEqual(self.css(), "")
        theming.set_suspended(False)
        self.assertIn("background-image", self.css())

    def test_paint_effective(self):
        paint = theming.Paint("light", {"grid_gap": 8})
        self.assertEqual(paint.effective("grid_gap"), 8)
        self.assertEqual(paint.effective("window_bg"), "#fafafa")
        self.assertEqual(theming.Paint().effective("window_bg"), "#242424")


@needs_display
class ListenerTests(_Case):
    def test_listeners_hear_every_paint_and_can_leave(self):
        heard = []

        def listener():
            heard.append(theming.current_paint().base)

        theming.add_listener(listener)
        theming.add_listener(listener)  # once only
        theming.paint("dark", {})
        theming.apply_theme("light")
        theming.restore()
        self.assertEqual(heard, ["dark", None, None])
        theming.remove_listener(listener)
        theming.paint("dark", {})
        self.assertEqual(len(heard), 3)

    def test_a_methods_owner_going_away_drops_it(self):
        class Owner:
            def __init__(self):
                self.calls = 0

            def heard(self):
                self.calls += 1

        owner = Owner()
        theming.add_listener(owner.heard)
        theming.paint("dark", {})
        self.assertEqual(owner.calls, 1)
        del owner
        theming.paint("dark", {})  # nothing to call, nothing raised
        theming.remove_listener(lambda: None)

    def test_a_failing_listener_is_logged_and_the_rest_run(self):
        heard = []

        def broken():
            raise RuntimeError("boom")

        theming.add_listener(broken)
        theming.add_listener(lambda: heard.append(1))
        with self.assertLogs("openemux.ui.theming", level="ERROR"):
            theming.paint("dark", {})
        self.assertEqual(heard, [1])
        theming.remove_listener(broken)


@needs_display
class WindowSizeTests(WindowCase):
    def setUp(self):
        super().setUp()
        _reset()
        self.addCleanup(_reset)

    def test_the_sidebar_follows_a_themes_width_and_back(self):
        theming.paint("dark", {"sidebar_width": 400})
        split = self.win.split_view
        self.assertEqual(split.get_max_sidebar_width(), 400)
        self.assertEqual(split.get_min_sidebar_width(), 200)
        theming.paint("dark", {"sidebar_width": 150})  # clamped to 200
        self.assertEqual(split.get_max_sidebar_width(), 200)
        self.assertEqual(split.get_min_sidebar_width(), 200)
        theming.apply_theme("dark")
        self.assertEqual(split.get_max_sidebar_width(), 360)
        self.assertEqual(split.get_min_sidebar_width(), 260)

    def test_the_grid_rebuilds_only_when_its_sizes_change(self):
        with mock.patch.object(self.win, "_reload_current_page") as reload:
            theming.paint("dark", {"card_bg": "#101010"})
            reload.assert_not_called()
            theming.paint("dark", {"grid_gap": 8, "card_scale": 150})
            reload.assert_called_once()
            theming.paint("dark", {"grid_gap": 8, "card_scale": 150, "window_bg": "#000000"})
            reload.assert_called_once()

    def test_the_grid_reads_the_themes_sizes(self):
        theming.paint("dark", {"grid_gap": 8, "card_scale": 150})
        self.win.pages.ensure_loaded("SFC")
        self.pump()
        grid = self.win.pages.grid_for("SFC")
        self.assertEqual(grid._card_scale, 1.5)
        theming.paint("dark", {})
        self.win.pages.ensure_loaded("SFC")
        self.pump()
        self.assertEqual(self.win.pages.grid_for("SFC")._card_scale, 1.0)

    def test_a_mixed_page_scales_its_slot(self):
        theming.paint("dark", {"card_scale": 150})
        self.win.pages.ensure_all_loaded()
        self.pump()
        for grid in self.win.pages.grids():
            if grid.mixed_consoles:
                width, _height = grid._cover_size_for(None, grid._base_artwork_width)
                self.assertGreater(width, 200)

    def test_closing_the_window_stops_listening(self):
        self.win._on_close_disconnect_style_manager()
        with mock.patch.object(self.win, "_reload_current_page") as reload:
            theming.paint("dark", {"grid_gap": 8})
        reload.assert_not_called()


@needs_display
class BigPictureThemeTests(BigPictureCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(_reset)

    def test_built_ins_leave_big_picture_as_it_was(self):
        theming.apply_theme("dark")
        self.assertEqual(self.shell.theme_args(), {})

    def test_a_custom_theme_gives_its_palette_font_background_and_size(self):
        base_scale = self.shell.scale()
        theming.paint("light", {"font_family": "Sans", "font_scale": 150,
                                "library_bg": "#fafafa"})
        theming._paint.backgrounds = {"library": {"uri": "file:///x.png", "fit": "tile",
                                                  "path": Path("/x.png")}}
        args = self.shell.theme_args()
        self.assertEqual(args["font_family"], "Sans")
        self.assertEqual(args["background"], {"uri": "file:///x.png", "fit": "tile"})
        self.assertEqual(args["palette"]["bg"].lower(), "#fafafa")
        self.assertGreater(self.shell.scale(), base_scale)
        self.shell.apply_scale()
        self.assertIn("file:///x.png", self.shell._sheet_key[1])

    def test_entering_with_a_light_theme_is_light_and_leaving_gives_back(self):
        self.win.toggle_big_picture()
        theming.paint("light", {"card_bg": "#ffffff"})
        manager = Adw.StyleManager.get_default()
        before = manager.get_color_scheme()
        self.win.toggle_big_picture()
        self.assertEqual(manager.get_color_scheme(), Adw.ColorScheme.FORCE_LIGHT)
        self.win.toggle_big_picture()
        self.assertEqual(manager.get_color_scheme(), before)

    def test_a_theme_change_while_open_regenerates(self):
        with mock.patch.object(self.shell, "apply_scale") as apply:
            theming.paint("dark", {"card_bg": "#123456"})
        apply.assert_called()
        self.win.toggle_big_picture()
        with mock.patch.object(self.shell, "apply_scale") as apply:
            theming.paint("dark", {"card_bg": "#654321"})
        apply.assert_not_called()


@needs_display
class PreviewDrawingTests(unittest.TestCase):
    LABELS = {
        "title": "Super Nintendo", "consoles": ["A", "B", "C"], "favorites": "Fav",
        "games": ["One", "Two", "Three"], "console": "SNES", "played": "Yesterday",
        "play": "Play",
    }

    def colors(self, **changes):
        values = {spec.key: spec.default("dark") for spec in THEME_KEYS}
        values.update(changes)
        return values

    def draw(self, width, colors, images=None):
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, 300)
        draw_preview(cairo.Context(surface), width, 300, colors, self.LABELS, images)
        return surface

    def test_every_shape_setting_draws(self):
        pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, 50, 30)
        pixbuf.fill(0xFF0000FF)
        for fit in ("cover", "contain", "tile"):
            self.draw(640, self.colors(border_width=2, corner_radius=24, shadow_strength=80,
                                       font_family="Sans", font_scale=150, density=60,
                                       grid_gap=4, card_scale=150, sidebar_width=420),
                      {"library": (pixbuf, fit), "sidebar": (pixbuf, fit)})

    def test_no_shadow_and_a_narrow_preview(self):
        self.draw(300, self.colors(shadow_strength=0, card_scale=70, sidebar_width=200))

    def test_part_one_callers_give_only_colors(self):
        colors = {spec.key: spec.default("light") for spec in THEME_KEYS if spec.kind == "color"}
        self.draw(500, colors)

    def test_a_ready_made_card_draws_with_and_without_its_picture(self):
        from openemux.ui.theme_preview import ThemeCard, draw_card
        pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, 50, 30)
        pixbuf.fill(0x00FF00FF)
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 140, 88)
        draw_card(cairo.Context(surface), 140, 88, self.colors(), (pixbuf, "cover"))
        draw_card(cairo.Context(surface), 140, 88, {"library_bg": "#000000", "headerbar_bg": "#111111",
                                                     "sidebar_bg": "#222222", "selection_bg": "#333333",
                                                     "sidebar_text_secondary": "#999999",
                                                     "accent": "#ff0000", "card_bg": "#444444",
                                                     "text_primary": "#ffffff"})
        card = ThemeCard(self.colors(), None, 120, 70)
        self.assertEqual(card.get_content_width(), 120)
        card._draw(None, cairo.Context(surface), 120, 70)

    def test_the_widget_keeps_images_across_a_color_change(self):
        preview = ThemePreview(self.LABELS, self.colors())
        preview.set_theme(self.colors(), {"library": ("x", "cover")})
        preview.set_colors(self.colors(card_bg="#000000"))
        self.assertEqual(preview.images, {"library": ("x", "cover")})


if __name__ == "__main__":
    unittest.main()
