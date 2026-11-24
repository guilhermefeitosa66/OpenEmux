"""The Custom Color dialog (issue 983), built against the real window."""

import threading
import unittest
from unittest import mock

import cairo

from tests.gtk_display import HAVE_DISPLAY, needs_display
from tests.window_harness import WindowCase

if HAVE_DISPLAY:
    from gi.repository import Gdk

    from openemux.core import cartridge_colors
    from openemux.ui import cartridge_color_dialog as dialog_module
    from openemux.ui.cartridge_color_dialog import CartridgeColorDialog, start_color, surface_texture


def _now(work):
    work()


@needs_display
class _DialogCase(WindowCase):
    def setUp(self):
        super().setUp()
        self.game = self.rom("SFC")
        self.config = self.win.config_manager

    def dialog(self):
        dialog = CartridgeColorDialog(self.win, self.game, spawn=_now)
        self.addCleanup(dialog.force_close)
        self.pump()
        return dialog


@needs_display
class WhereItStartsTests(_DialogCase):
    def test_the_authored_shell_starts_from_white(self):
        self.assertEqual(start_color(self.config, self.game), "#e8e4da")

    def test_a_named_shell_starts_from_its_swatch(self):
        self.config.set_rom_cartridge_color(self.game["path"], "SFC", "red")
        self.assertEqual(start_color(self.config, self.game), "#b23a34")

    def test_a_custom_shell_starts_from_itself(self):
        self.config.set_rom_cartridge_color(self.game["path"], "SFC", "#123456")
        dialog = self.dialog()
        self.assertEqual(dialog.color, "#123456")
        self.assertEqual(dialog.hex_entry.get_text(), "#123456".upper())


@needs_display
class PickingTests(_DialogCase):
    def test_the_controls_follow_each_other(self):
        dialog = self.dialog()
        dialog.hex_entry.set_text("#d23c2a")
        self.assertEqual(dialog.color, "#d23c2a")
        hue, _s, _v = cartridge_colors.hex_to_hsv("#d23c2a")
        self.assertEqual(round(dialog.hue_scale.get_value()), round(hue))
        dialog.hue_scale.set_value(120)
        self.assertEqual(round(cartridge_colors.hex_to_hsv(dialog.color)[0]), 120)
        self.assertEqual(dialog.hex_entry.get_text(), dialog.color.upper())
        dialog.swatch_buttons["blue"].emit("clicked")
        self.assertEqual(dialog.color, "#3167b0")

    def test_a_bad_hex_marks_the_field_and_keeps_the_color(self):
        dialog = self.dialog()
        before = dialog.color
        dialog.hex_entry.set_text("zz")
        self.assertTrue(dialog.hex_entry.has_css_class("error"))
        self.assertFalse(dialog.apply_button.get_sensitive())
        self.assertEqual(dialog.color, before)
        with mock.patch.object(self.win, "set_rom_cartridge_color") as set_color:
            dialog._on_apply(None)
        set_color.assert_not_called()
        dialog.hex_entry.set_text(before)
        self.assertFalse(dialog.hex_entry.has_css_class("error"))
        self.assertTrue(dialog.apply_button.get_sensitive())

    def test_a_grey_keeps_the_hue(self):
        dialog = self.dialog()
        dialog.hue_scale.set_value(200)
        dialog.set_color("#808080")
        self.assertEqual(round(dialog.hue), 200)

    def test_the_plane_by_pointer_and_by_keyboard(self):
        dialog = self.dialog()
        plane = dialog.plane
        plane.set_size_request(100, 100)
        with mock.patch.object(plane, "get_width", return_value=100), \
                mock.patch.object(plane, "get_height", return_value=100):
            plane._on_drag_begin(None, 25, 25)
            self.assertAlmostEqual(dialog.saturation, 0.25)
            self.assertAlmostEqual(dialog.value, 0.75)
            plane._on_drag_update(None, 500, -500)
            self.assertEqual((dialog.saturation, dialog.value), (1.0, 1.0))
        self.assertTrue(plane._on_key(None, Gdk.KEY_Left, 0, 0))
        self.assertTrue(plane._on_key(None, Gdk.KEY_Down, 0, 0))
        self.assertTrue(plane._on_key(None, Gdk.KEY_Up, 0, 0))
        self.assertTrue(plane._on_key(None, Gdk.KEY_Right, 0, 0))
        self.assertFalse(plane._on_key(None, Gdk.KEY_a, 0, 0))
        self.assertEqual(
            dialog.color, cartridge_colors.hsv_to_hex(dialog.hue, dialog.saturation, dialog.value)
        )

    def test_the_plane_draws(self):
        dialog = self.dialog()
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 60, 40)
        dialog.plane._draw(None, cairo.Context(surface), 60, 40)
        surface.flush()
        self.assertTrue(any(bytes(surface.get_data())))


@needs_display
class PreviewTests(_DialogCase):
    def test_the_preview_shows_the_game_in_the_picked_color(self):
        dialog = self.dialog()
        self.assertTrue(self.pump_until(lambda: dialog.preview.get_paintable() is not None))
        first = dialog.preview.get_paintable()
        dialog.hex_entry.set_text("#00ff00")
        self.pump()
        self.assertIsNot(dialog.preview.get_paintable(), first)

    def test_a_change_during_a_mix_is_mixed_next(self):
        queued = []
        dialog = CartridgeColorDialog(self.win, self.game, spawn=queued.append)
        self.addCleanup(dialog.force_close)
        queued.pop(0)()  # the sources
        self.pump()
        self.assertTrue(dialog._preview_busy)
        dialog.set_color("#00ff00")  # while the first mix is out
        self.assertEqual(len(queued), 1)
        queued.pop(0)()
        self.pump()
        self.assertEqual(len(queued), 1)  # the newer color, queued after
        queued.pop(0)()
        self.pump()
        self.assertEqual(dialog._preview_color, "#00ff00")
        self.assertFalse(dialog._preview_busy)

    def test_no_preview_when_the_shells_cannot_be_rendered(self):
        with mock.patch.object(dialog_module.cartridge_render, "custom_preview_sources", return_value=None):
            dialog = self.dialog()
        self.pump()
        self.assertIsNone(dialog.preview.get_paintable())

    def test_a_texture_in_either_byte_order(self):
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 3, 2)
        for order in ("little", "big"):
            texture = surface_texture(surface, byteorder=order)
            self.assertEqual((texture.get_width(), texture.get_height()), (3, 2))


@needs_display
class ApplyTests(_DialogCase):
    def test_apply_makes_the_shell_then_stores_the_color(self):
        dialog = self.dialog()
        dialog.hex_entry.set_text("#2e7dd1")
        with mock.patch.object(dialog_module.cartridge_render, "custom_frame_for") as make, \
                mock.patch.object(self.win, "set_rom_cartridge_color") as set_color, \
                mock.patch.object(dialog, "close") as close:
            dialog.apply_button.emit("clicked")
            self.pump()
            dialog._on_apply(None)  # a second Apply does nothing
            self.pump()
        make.assert_called_once_with("SFC", "#2e7dd1")
        set_color.assert_called_once_with(self.game, "#2e7dd1")
        close.assert_called_once()

    def test_a_shell_that_cannot_be_made_is_not_stored(self):
        dialog = self.dialog()
        with mock.patch.object(dialog_module.cartridge_render, "custom_frame_for", return_value=None), \
                mock.patch.object(self.win, "set_rom_cartridge_color") as set_color:
            dialog._on_apply(None)
            self.pump()
        set_color.assert_not_called()
        self.assertTrue(dialog.error_label.get_visible())
        self.assertTrue(dialog.apply_button.get_sensitive())
        self.assertTrue(dialog.cancel_button.get_sensitive())
        self.assertFalse(dialog.applied)

    def test_nothing_can_close_it_while_the_shell_is_made(self):
        queued = []
        dialog = CartridgeColorDialog(self.win, self.game, spawn=queued.append)
        self.addCleanup(dialog.force_close)
        dialog._on_apply(None)
        self.assertFalse(dialog.cancel_button.get_sensitive())
        self.assertFalse(dialog.get_can_close())
        with mock.patch.object(dialog_module.cartridge_render, "custom_frame_for", return_value="x"), \
                mock.patch.object(self.win, "set_rom_cartridge_color"):
            queued[-1]()
            self.pump()
        self.assertTrue(dialog.get_can_close())

    def test_enter_in_the_hex_field_applies(self):
        dialog = self.dialog()
        with mock.patch.object(dialog, "_on_apply") as apply:
            dialog.hex_entry.emit("activate")
        apply.assert_called_once()

    def test_cancel_closes_without_storing(self):
        dialog = self.dialog()
        with mock.patch.object(self.win, "set_rom_cartridge_color") as set_color, \
                mock.patch.object(dialog, "close") as close:
            dialog.cancel_button.emit("clicked")
        close.assert_called_once()
        set_color.assert_not_called()

    def test_the_window_redraws_cards_when_a_shell_is_ready(self):
        grid = mock.Mock()
        with mock.patch.object(self.win.pages, "grids", return_value=[grid]):
            self.win._custom_frame_listener("SFC", "#d23c2a")
            self.pump()
        grid.custom_frame_ready.assert_called_once_with("SFC", "#d23c2a")
        self.assertIn(self.win._custom_frame_listener, dialog_module.cartridge_render._CUSTOM_FRAME_LISTENERS)
        self.win._on_close_drop_frame_listener()
        self.assertNotIn(self.win._custom_frame_listener, dialog_module.cartridge_render._CUSTOM_FRAME_LISTENERS)

    def test_a_closed_window_ignores_the_listener(self):
        import weakref

        from openemux.ui import window as window_module

        class _Gone:
            pass

        gone = _Gone()
        listener = window_module._custom_frame_listener(weakref.ref(gone))
        del gone
        with mock.patch.object(window_module.GLib, "idle_add") as idle:
            listener("SFC", "#d23c2a")
        idle.assert_not_called()

    def test_the_window_presents_it(self):
        with mock.patch.object(dialog_module, "_spawn", _now):
            dialog = self.win.open_cartridge_color_dialog(self.game)
        self.addCleanup(dialog.force_close)
        self.assertIsInstance(dialog, CartridgeColorDialog)


@needs_display
class SpawnTests(unittest.TestCase):
    def test_work_runs_on_another_thread(self):
        done = threading.Event()
        seen = []

        def work():
            seen.append(threading.current_thread() is threading.main_thread())
            done.set()

        dialog_module._spawn(work)
        self.assertTrue(done.wait(5))
        self.assertEqual(seen, [False])


if __name__ == "__main__":
    unittest.main()
