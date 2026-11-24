"""Saved colors and palettes in the Custom Color dialog (issue 983)."""

import unittest
from unittest import mock

from tests.gtk_display import HAVE_DISPLAY, needs_display
from tests.window_harness import WindowCase

if HAVE_DISPLAY:
    from gi.repository import Gdk, GLib, Gtk

    from openemux.core import cartridge_colors
    from openemux.ui import cartridge_palettes
    from openemux.ui.cartridge_color_dialog import CartridgeColorDialog


def _now(work):
    work()


@needs_display
class _PaletteCase(WindowCase):
    def setUp(self):
        super().setUp()
        self.game = self.rom("SFC")
        self.store = self.win.config_manager.cartridge_colors

    def dialog(self, present=True):
        dialog = CartridgeColorDialog(self.win, self.game, spawn=_now)
        self.addCleanup(dialog.force_close)
        if present:
            dialog.present(self.win)
        self.pump()
        return dialog

    def area(self):
        return self.dialog().palettes

    def colors(self, buttons):
        return [color for color, _button in buttons]


@needs_display
class SavedColorsTests(_PaletteCase):
    def test_the_row_is_hidden_while_nothing_is_saved(self):
        area = self.area()
        self.assertFalse(area.saved_box.get_visible())

    def test_saved_colors_most_recent_first_and_a_click_picks(self):
        self.store.remember_color("#111111")
        self.store.remember_color("#222222")
        dialog = self.dialog()
        area = dialog.palettes
        self.assertTrue(area.saved_box.get_visible())
        self.assertEqual(self.colors(area.saved_buttons), ["#222222", "#111111"])
        area.saved_buttons[1][1].emit("clicked")
        self.assertEqual(dialog.color, "#111111")

    def test_applying_saves_the_color(self):
        dialog = self.dialog()
        dialog.hex_entry.set_text("#abcdef")
        with mock.patch.object(dialog_render(), "custom_frame_for", return_value="frame.svg"):
            dialog._on_apply(None)
            self.pump()
        self.assertEqual(self.store.saved_colors(), ["#abcdef"])

    def test_a_named_color_is_not_saved(self):
        self.win.set_rom_cartridge_color(self.game, "red")
        self.assertEqual(self.store.saved_colors(), [])

    def test_remove_from_the_menu_keeps_the_game_s_color(self):
        self.store.set_rom_color(self.game["path"], "SFC", "#111111")
        self.store.remember_color("#111111")
        self.store.remember_color("#222222")
        area = self.area()
        color, button = area.saved_buttons[1]
        area.open_menu(button, area._saved_menu(color))
        self.assertEqual(area._menu_target[0][0], self.said("cartridge_color.dialog.remove"))
        area._on_swatch_action(None, GLib.Variant("s", "0"))
        self.assertEqual(self.store.saved_colors(), ["#222222"])
        self.assertEqual(self.colors(area.saved_buttons), ["#222222"])
        self.assertEqual(self.store.get_rom_color(self.game["path"]), "#111111")

    def test_delete_key_removes_and_the_last_hides_the_row(self):
        self.store.remember_color("#111111")
        area = self.area()
        color, button = area.saved_buttons[0]
        self.assertTrue(
            area._on_swatch_key(None, Gdk.KEY_Delete, 0, 0, button, color, area._saved_menu, None)
        )
        self.assertEqual(self.store.saved_colors(), [])
        self.assertFalse(area.saved_box.get_visible())


def dialog_render():
    from openemux.ui import cartridge_color_dialog

    return cartridge_color_dialog.cartridge_render


@needs_display
class SwatchMenuTests(_PaletteCase):
    def test_menu_keys_and_other_keys(self):
        self.store.remember_color("#111111")
        area = self.area()
        color, button = area.saved_buttons[0]
        menu = area._saved_menu
        with mock.patch.object(area, "open_menu") as open_menu:
            self.assertTrue(area._on_swatch_key(None, Gdk.KEY_Menu, 0, 0, button, color, menu, None))
            self.assertTrue(area._on_swatch_key(
                None, Gdk.KEY_F10, 0, Gdk.ModifierType.SHIFT_MASK, button, color, menu, None
            ))
        self.assertEqual(open_menu.call_count, 2)
        self.assertFalse(area._on_swatch_key(None, Gdk.KEY_F10, 0, 0, button, color, menu, None))
        self.assertFalse(area._on_swatch_key(
            None, Gdk.KEY_Left, 0, Gdk.ModifierType.ALT_MASK, button, color, menu, None
        ))
        self.assertFalse(area._on_swatch_key(None, Gdk.KEY_a, 0, 0, button, color, menu, None))

    def test_a_right_click_opens_the_menu(self):
        self.store.remember_color("#111111")
        area = self.area()
        _color, button = area.saved_buttons[0]
        clicks = [
            controller for controller in list(button.observe_controllers())
            if isinstance(controller, Gtk.GestureClick)
        ]
        with mock.patch.object(area, "open_menu") as open_menu:
            clicks[0].emit("pressed", 1, 4.0, 4.0)
        open_menu.assert_called_once()

    def test_no_popup_off_screen(self):
        self.store.remember_color("#111111")
        area = self.dialog(present=False).palettes
        color, button = area.saved_buttons[0]
        with mock.patch.object(area.swatch_menu, "popup") as popup:
            area.open_menu(button, area._saved_menu(color))
        popup.assert_not_called()
        self.assertIsNotNone(area._menu_target)

    def test_a_stale_action_index_does_nothing(self):
        area = self.area()
        area._menu_target = None
        area._on_swatch_action(None, GLib.Variant("s", "3"))

    def test_the_menu_points_at_the_swatch_it_is_for(self):
        self.store.remember_color("#111111")
        area = self.area()
        color, button = area.saved_buttons[0]
        with mock.patch.object(area.swatch_menu, "popup") as popup, \
                mock.patch.object(area.swatch_menu, "set_pointing_to") as point:
            area.open_menu(button, area._saved_menu(color))
            with mock.patch.object(button, "compute_bounds", return_value=(False, None)):
                area.open_menu(button, area._saved_menu(color))
        self.assertEqual(popup.call_count, 2)
        self.assertEqual(point.call_count, 1)


@needs_display
class PaletteListTests(_PaletteCase):
    def test_shell_colors_by_default(self):
        dialog = self.dialog()
        area = dialog.palettes
        self.assertEqual(area.palette_label.get_label(), self.said("cartridge_color.palette.shell"))
        self.assertEqual(len(dialog.swatch_buttons), 12)
        self.assertIsNone(area.add_button)

    def test_the_list_has_every_palette_with_headings(self):
        self.store.create_palette("Mine")
        self.store.select_palette("shell")
        area = self.area()
        area.palette_popover.emit("show")
        self.assertEqual(
            list(area.list_rows),
            ["shell"] + [pid for pid, _c in cartridge_colors.PRESET_PALETTES]
            + [self.store.user_palettes()[0]["id"]],
        )
        headings = []
        row = area.palette_list.get_first_child()
        while row is not None:
            if not row.get_activatable():
                headings.append(row.get_child().get_label())
            row = row.get_next_sibling()
        self.assertEqual(headings, [
            self.said("cartridge_color.dialog.presets"),
            self.said("cartridge_color.dialog.your_palettes"),
        ])

    def test_picking_a_preset_replaces_the_row_and_is_remembered(self):
        dialog = self.dialog()
        area = dialog.palettes
        area.refresh_list()
        area._on_row_activated(None, area.list_rows["nord"])
        self.assertEqual(self.colors(area.palette_buttons),
                         cartridge_colors.builtin_palette_colors("nord"))
        self.assertEqual(dialog.swatch_buttons, {})
        self.assertEqual(self.store.selected_palette(), "nord")
        area.palette_buttons[2][1].emit("clicked")
        self.assertEqual(dialog.color, "#88c0d0")
        self.assertEqual(self.area().palette_label.get_label(),
                         self.said("cartridge_color.palette.nord"))

    def test_an_unknown_palette_is_not_selected(self):
        area = self.area()
        area.select("nope")
        self.assertEqual(area.palette_id, "shell")

    def test_options_for_a_preset_and_for_a_user_palette(self):
        area = self.area()
        model = area.options_button.get_menu_model()
        self.assertEqual(model.get_n_items(), 1)
        self.store.create_palette("Mine")
        area.refresh_palette()
        self.assertEqual(area.options_button.get_menu_model().get_n_items(), 3)

    def test_the_actions_are_wired(self):
        area = self.area()
        self.assertTrue(area.widget.activate_action("palette.duplicate", None))
        self.assertEqual(len(self.store.user_palettes()), 1)


@needs_display
class UserPaletteTests(_PaletteCase):
    def make(self, colors=("#111111", "#222222", "#333333")):
        palette_id = self.store.create_palette("Mine", list(colors))
        dialog = self.dialog()
        return dialog, dialog.palettes, palette_id

    def test_a_user_palette_has_a_plus_that_adds_the_current_color(self):
        dialog, area, palette_id = self.make()
        self.assertTrue(area.add_button.get_sensitive())
        area.add_button.emit("clicked")
        self.assertEqual(self.store.palette_colors(palette_id)[-1], dialog.color)
        self.assertFalse(area.add_button.get_sensitive())
        dialog.set_color("#444444")
        self.assertTrue(area.add_button.get_sensitive())

    def test_a_full_palette_has_no_room(self):
        colors = [f"#0000{i:02x}" for i in range(cartridge_colors.PALETTE_COLORS_MAX)]
        _dialog, area, _palette_id = self.make(colors)
        self.assertFalse(area.add_button.get_sensitive())
        area.add_current()

    def test_move_and_remove_from_the_menu_and_the_keyboard(self):
        _dialog, area, palette_id = self.make()
        color, button = area.palette_buttons[0]
        items = area._palette_menu_items(color)
        self.assertEqual([label for label, _cb in items], [
            self.said("cartridge_color.dialog.move_left"),
            self.said("cartridge_color.dialog.move_right"),
            self.said("cartridge_color.dialog.remove"),
        ])
        items[1][1]()
        self.assertEqual(self.store.palette_colors(palette_id), ["#222222", "#111111", "#333333"])
        color, button = area.palette_buttons[1]
        self.assertTrue(area._on_swatch_key(
            None, Gdk.KEY_Left, 0, Gdk.ModifierType.ALT_MASK, button, color,
            area._palette_menu_items, area.move,
        ))
        self.assertEqual(self.store.palette_colors(palette_id), ["#111111", "#222222", "#333333"])
        area.move("#111111", -1)
        self.assertFalse(area._on_swatch_key(
            None, Gdk.KEY_Up, 0, Gdk.ModifierType.ALT_MASK, button, color,
            area._palette_menu_items, area.move,
        ))
        area._palette_menu_items("#333333")[2][1]()
        area.remove("#333333")
        self.assertEqual(self.colors(area.palette_buttons), ["#111111", "#222222"])

    def test_new_palette_starts_with_the_current_color(self):
        dialog, area, _palette_id = self.make()
        prompt = area.new_palette()
        self.assertIs(area.prompt, prompt)
        self.assertFalse(prompt.get_response_enabled("ok"))
        prompt.entry.set_text("Pokémon carts")
        self.assertTrue(prompt.get_response_enabled("ok"))
        prompt.emit("response", "ok")
        self.assertIsNone(area.prompt)
        self.assertEqual(area.palette_label.get_label(), "Pokémon carts")
        self.assertEqual(self.colors(area.palette_buttons), [dialog.color])
        prompt.force_close()

    def test_a_cancelled_or_refused_name_creates_nothing(self):
        _dialog, area, _palette_id = self.make()
        prompt = area.new_palette()
        prompt.entry.set_text("Other")
        prompt.emit("response", "cancel")
        prompt.force_close()
        prompt = area.new_palette()
        prompt.entry.set_text("Other")
        with mock.patch.object(self.store, "create_palette", return_value=None):
            prompt.emit("response", "ok")
        prompt.force_close()
        self.assertEqual(len(self.store.user_palettes()), 1)

    def test_rename(self):
        _dialog, area, palette_id = self.make()
        prompt = area.rename_palette()
        self.assertEqual(prompt.entry.get_text(), "Mine")
        prompt.entry.set_text("Pokémon")
        prompt.emit("response", "ok")
        prompt.force_close()
        self.assertEqual(self.store.user_palette(palette_id)["name"], "Pokémon")
        self.assertEqual(area.palette_label.get_label(), "Pokémon")
        prompt = area.rename_palette()
        prompt.emit("response", "ok")
        prompt.force_close()

    def test_duplicate_a_preset_and_a_user_palette(self):
        area = self.area()
        area.select("dracula")
        area.duplicate_palette()
        copy = self.store.user_palette(area.palette_id)
        self.assertEqual(copy["name"], self.said(
            "cartridge_color.dialog.palette_copy", name=self.said("cartridge_color.palette.dracula")
        ))
        self.assertEqual(copy["colors"], cartridge_colors.builtin_palette_colors("dracula"))
        area.duplicate_palette()
        self.assertEqual(len(self.store.user_palettes()), 2)

    def test_delete_asks_first(self):
        _dialog, area, palette_id = self.make()
        prompt = area.delete_palette()
        prompt.emit("response", "cancel")
        prompt.force_close()
        self.assertIsNotNone(self.store.user_palette(palette_id))
        prompt = area.delete_palette()
        prompt.emit("response", "delete")
        prompt.force_close()
        self.assertIsNone(self.store.user_palette(palette_id))
        self.assertEqual(area.palette_id, "shell")
        self.assertEqual(len(area.swatch_buttons), 12)

    def test_a_palette_survives_a_new_dialog(self):
        _dialog, _area, palette_id = self.make()
        area = self.area()
        self.assertEqual(area.palette_id, palette_id)
        self.assertEqual(self.colors(area.palette_buttons), ["#111111", "#222222", "#333333"])


@needs_display
class PaletteMenuModelTests(unittest.TestCase):
    def test_items_with_and_without_a_target(self):
        menu = cartridge_palettes._palette_menu([("A", "x.y", None), ("B", "x.z", "1")])
        self.assertEqual(menu.get_n_items(), 2)
