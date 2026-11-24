"""The theme editor's issue 1012 rows: numbers, choices, font, images, palettes."""

import unittest
from pathlib import Path
from unittest import mock

from tests.gtk_display import HAVE_DISPLAY, needs_display
from tests.window_harness import WindowCase

if HAVE_DISPLAY:
    import gi

    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf, GLib, Gtk

    from openemux.core.custom_themes import Theme
    from openemux.ui import theme_editor as editor_module
    from openemux.ui.theme_editor import (
        ChoiceRow,
        DensityRow,
        FontRow,
        ImageRow,
        NumberRow,
        ThemeEditorDialog,
        installed_fonts,
    )


def write_png(path, width=40, height=20, color=0x101010FF):
    pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, width, height)
    pixbuf.fill(color)
    pixbuf.savev(str(path), "png", [], [])
    return Path(path)


def _now(target):
    target()


@needs_display
class _RowsCase(WindowCase):
    def setUp(self):
        super().setUp()
        self.store = self.config.themes
        for name in ("paint", "restore"):
            patcher = mock.patch.object(editor_module.theming, name)
            patcher.start()
            self.addCleanup(patcher.stop)
        fonts = mock.patch.object(editor_module, "installed_fonts",
                                  return_value=["Cantarell", "Noto Sans"])
        fonts.start()
        self.addCleanup(fonts.stop)
        theming = editor_module.theming
        theming.set_cache_dir(self.tmp / "cache")
        self.addCleanup(theming.set_cache_dir, None)
        spawn = mock.patch.object(theming, "_spawn", _now)
        spawn.start()
        self.addCleanup(spawn.stop)

    def editor(self, theme=None, is_new=True, on_saved=None):
        theme = theme or Theme("", "Midnight", "dark")
        dialog = ThemeEditorDialog(self.win, self.store, theme, is_new,
                                   on_saved=on_saved, spawn=_now)
        dialog.present(self.win)
        self.addCleanup(dialog.force_close)
        self.pump()
        return dialog


@needs_display
class RowKindTests(_RowsCase):
    def test_every_key_has_the_row_its_kind_asks_for(self):
        dialog = self.editor()
        self.assertIsInstance(dialog.rows["corner_radius"], NumberRow)
        self.assertIsInstance(dialog.rows["corner_radius"].control, Gtk.Scale)
        self.assertIsInstance(dialog.rows["border_width"].control, Gtk.SpinButton)
        self.assertIsInstance(dialog.rows["sidebar_icon_size"], ChoiceRow)
        self.assertIsInstance(dialog.rows["library_image_fit"], ChoiceRow)
        self.assertIsInstance(dialog.rows["font_family"], FontRow)
        self.assertIsInstance(dialog.rows["library_image"], ImageRow)
        self.assertTrue(any(isinstance(row, DensityRow) for row in dialog.extra_rows))

    def test_a_number_moves_shows_its_unit_and_resets(self):
        dialog = self.editor()
        row = dialog.rows["corner_radius"]
        row.control.set_value(20)
        self.assertEqual(dialog.draft.values["corner_radius"], 20)
        self.assertEqual(row.get_subtitle(), self.said("theme_editor.unit.px", value=20))
        dialog.rows["font_scale"].control.set_value(120)
        self.assertEqual(dialog.rows["font_scale"].get_subtitle(),
                         self.said("theme_editor.unit.percent", value=120))
        dialog.reset_value("corner_radius")
        self.assertEqual(row.control.get_value(), 12)
        self.assertEqual(row.get_subtitle(), self.said("theme_editor.same_as_base"))

    def test_a_choice_picks_and_follows_a_reset(self):
        dialog = self.editor()
        row = dialog.rows["sidebar_icon_size"]
        row.buttons[24].set_active(True)
        self.assertEqual(dialog.draft.values["sidebar_icon_size"], 24)
        self.assertEqual(row.get_subtitle(), "")
        dialog.reset_all()
        self.assertTrue(row.buttons[16].get_active())
        self.assertEqual(row.buttons[16].get_label(), "16")
        fit = dialog.rows["library_image_fit"]
        self.assertEqual(fit.buttons["tile"].get_label(), self.said("theme_editor.fit.tile"))

    def test_density_presets_and_the_fine_slider(self):
        dialog = self.editor()
        presets = next(row for row in dialog.extra_rows if isinstance(row, DensityRow))
        presets.buttons[80].set_active(True)
        self.assertEqual(dialog.draft.values["density"], 80)
        self.assertEqual(dialog.rows["density"].control.get_value(), 80)
        # Clicking the active preset keeps it on.
        presets.buttons[80].set_active(False)
        self.assertTrue(presets.buttons[80].get_active())
        dialog.rows["density"].control.set_value(90)
        self.assertFalse(any(button.get_active() for button in presets.buttons.values()))

    def test_the_font_list_and_a_family_from_elsewhere(self):
        dialog = self.editor(Theme("", "X", "dark", {"font_family": "Elsewhere Sans"}))
        row = dialog.rows["font_family"]
        self.assertEqual(row.choices, ["", "Cantarell", "Elsewhere Sans", "Noto Sans"])
        self.assertEqual(row.dropdown.get_selected(), 2)
        row.dropdown.set_selected(1)
        self.assertEqual(dialog.draft.values["font_family"], "Cantarell")
        row.dropdown.set_selected(0)
        self.assertNotIn("font_family", dialog.draft.values)
        row._on_selected(mock.Mock(get_selected=lambda: 99), None)
        dialog.draft.values["font_family"] = "Gone"
        dialog.refresh()
        self.assertEqual(row.dropdown.get_selected(), 0)

    def test_the_font_list_is_read_once(self):
        dialog = self.editor()
        self.assertEqual(dialog.fonts(), ["Cantarell", "Noto Sans"])
        self.assertEqual(editor_module.installed_fonts.call_count, 1)


@needs_display
class InstalledFontsTests(unittest.TestCase):
    def test_only_names_a_theme_can_store(self):
        fonts = installed_fonts()
        self.assertTrue(fonts)
        self.assertEqual(fonts, sorted(fonts, key=str.casefold))


@needs_display
class ImageRowTests(_RowsCase):
    def picture(self, name="pic.png", width=40, height=20):
        return write_png(self.tmp / name, width, height)

    def test_a_picked_image_is_staged_shown_and_saved(self):
        saved = []
        dialog = self.editor(on_saved=saved.append)
        row = dialog.rows["library_image"]
        self.assertFalse(dialog.rows["library_image_dim"].get_sensitive())
        row.take(str(self.picture()))
        self.pump()
        self.assertEqual(dialog.draft.values["library_image"], "library.png")
        self.assertTrue((dialog.staging / "library.png").is_file())
        self.assertEqual(row.get_subtitle(), self.said("theme_editor.image.size", width=40, height=20))
        self.assertTrue(dialog.rows["library_image_dim"].get_sensitive())
        self.assertTrue(row.remove_button.get_sensitive())
        staging = dialog.staging
        dialog.save()
        self.assertFalse(staging.exists())
        theme = saved[0]
        self.assertTrue(self.store.get(theme.id).image_path("library"))

    def test_a_bad_file_says_so_and_changes_nothing(self):
        dialog = self.editor()
        bad = self.tmp / "bad.png"
        bad.write_text("not a picture")
        row = dialog.rows["library_image"]
        row.take(str(bad))
        self.pump()
        self.assertNotIn("library_image", dialog.draft.values)
        self.assertEqual(row.get_subtitle(), self.said("theme_editor.image.error"))
        self.assertTrue(row.has_css_class("error"))
        row.remove()
        self.assertFalse(row.has_css_class("error"))
        self.assertEqual(row.get_subtitle(), self.said("theme_editor.image.none"))

    def test_cancel_leaves_nothing_behind(self):
        dialog = self.editor()
        dialog.rows["sidebar_image"].take(str(self.picture()))
        self.pump()
        staging = dialog.staging
        dialog.close()
        self.pump()
        self.assertFalse(staging.exists())
        self.assertEqual(self.store.list(), [])

    def test_editing_keeps_the_themes_images_until_save(self):
        images = self.tmp / "src"
        images.mkdir()
        write_png(images / "library.png")
        theme = self.store.create("Pics", "dark", {"library_image": "library.png"},
                                  images_from=images)
        dialog = self.editor(self.store.get(theme.id), is_new=False)
        dialog.rows["library_image"].remove()
        dialog.close()
        self.pump()
        self.assertTrue(self.store.get(theme.id).image_path("library"))

    def test_a_dim_image_under_light_text_warns_on_the_image_row(self):
        dialog = self.editor()
        with mock.patch.object(editor_module.theme_images, "average_color",
                               return_value="#f0f0f0"):
            dialog.rows["library_image"].take(str(self.picture()))
            self.pump()
            self.assertTrue(self.pump_until(
                lambda: dialog.section_icons["backgrounds"].get_visible()))
        subtitle = dialog.rows["library_image"].get_subtitle()
        self.assertIn(self.said("theme_editor.key.text_primary"), subtitle)

    def test_an_unreadable_average_or_preview_is_skipped(self):
        dialog = self.editor()
        with mock.patch.object(editor_module.theme_images, "average_color", return_value=None), \
             mock.patch.object(editor_module.GdkPixbuf.Pixbuf, "new_from_file_at_scale",
                               side_effect=GLib.Error("nope")):
            dialog.rows["library_image"].take(str(self.picture()))
            self.pump()
            self.pump_until(lambda: not dialog.preview.images and dialog._averages)
        self.assertEqual(dialog.preview.images, {})

    def test_a_background_landing_after_close_is_ignored(self):
        dialog = self.editor()
        dialog.close()
        self.pump()
        with mock.patch.object(dialog, "refresh") as refresh:
            dialog._on_background_ready()
        refresh.assert_not_called()

    def test_the_file_dialog(self):
        dialog = self.editor()
        row = dialog.rows["library_image"]
        with mock.patch.object(Gtk.FileDialog, "open") as opened:
            file_dialog = row.choose()
        self.assertIsNotNone(file_dialog)
        opened.assert_called_once()
        with mock.patch.object(row, "take") as take:
            dismissed = mock.Mock(open_finish=mock.Mock(side_effect=GLib.Error("x")))
            row._on_chosen(dismissed, None)
            empty = mock.Mock(open_finish=mock.Mock(return_value=None))
            row._on_chosen(empty, None)
            chosen = mock.Mock(open_finish=mock.Mock(
                return_value=mock.Mock(get_path=lambda: "/x.png")))
            row._on_chosen(chosen, None)
        take.assert_called_once_with("/x.png")


@needs_display
class PaletteTests(_RowsCase):
    def test_the_palette_menu_lists_presets_then_the_users(self):
        self.config.cartridge_colors.create_palette("Mine", ["#101010", "#f0f0f0", "#ff0000"])
        self.config.cartridge_colors.create_palette("Lonely", ["#101010"])
        dialog = self.editor()
        dialog.refresh_palettes()
        names = [name for name, _colors in dialog.palettes()]
        self.assertEqual(names[-2:], ["Mine", "Lonely"])
        rows = []
        child = dialog.palette_list.get_first_child()
        while child is not None:
            rows.append(child)
            child = child.get_next_sibling()
        self.assertEqual(len(rows), len(names))
        self.assertFalse(rows[-1].get_sensitive())  # one color: nothing to seed
        dialog.refresh_palettes()  # rebuilt, not appended
        self.assertEqual(sum(1 for _ in self._children(dialog.palette_list)), len(names))

    def _children(self, widget):
        child = widget.get_first_child()
        while child is not None:
            yield child
            child = child.get_next_sibling()

    def test_starting_from_a_palette_seeds_and_reset_all_undoes(self):
        dialog = self.editor()
        dialog.apply_palette(["#2E3440", "#4C566A", "#88C0D0", "#81A1C1"])
        self.assertIn("window_bg", dialog.draft.values)
        self.assertTrue(dialog.reset_all_button.get_sensitive())
        before = dict(dialog.draft.values)
        dialog.apply_palette(["#ffffff"])
        self.assertEqual(dialog.draft.values, before)
        dialog.reset_all()
        self.assertEqual(dialog.draft.values, {})

    def test_without_a_color_store_only_presets(self):
        dialog = self.editor()
        dialog.color_store = None
        self.assertEqual(len(dialog.palettes()), 8)
        row = dialog.rows["card_bg"]
        self.assertIsNone(row.ensure_palettes())

    def test_a_color_popover_holds_the_saved_colors_and_palettes(self):
        self.config.cartridge_colors.remember_color("#123456")
        dialog = self.editor()
        row = dialog.rows["card_bg"]
        area = row.ensure_palettes()
        self.assertIs(row.ensure_palettes(), area)
        self.assertIs(area.store, self.config.cartridge_colors)
        self.assertIn("#123456", [color for color in area.store.saved_colors()])
        # Every color field offers the 8 palettes shared with Android (issue
        # 1012, maintainer's Android test), the user's and the saved colors.
        from openemux.core.cartridge_colors import PRESET_PALETTES
        ids = [row[0] for row in area._palettes()]
        for palette_id, _colors in PRESET_PALETTES:
            self.assertIn(palette_id, ids)
        for row in dialog.rows.values():
            if hasattr(row, "ensure_palettes"):
                self.assertIsNotNone(row.ensure_palettes(), row.key)
        area.on_pick("#654321")
        self.assertEqual(dialog.draft.values["card_bg"], "#654321")
        dialog.reset_value("card_bg")


if __name__ == "__main__":
    unittest.main()
