"""The theme editor (issue 1011), built against the real window."""

import unittest
from unittest import mock

import cairo

from tests.gtk_display import HAVE_DISPLAY, needs_display
from tests.window_harness import WindowCase

if HAVE_DISPLAY:
    from openemux.core.custom_themes import SECTIONS, THEME_KEYS, Theme
    from openemux.ui import theme_editor as editor_module
    from openemux.ui.theme_editor import Swatch, ThemeEditorDialog, open_theme_editor


@needs_display
class _EditorCase(WindowCase):
    def setUp(self):
        super().setUp()
        self.store = self.config.themes
        paint = mock.patch.object(editor_module.theming, "paint")
        restore = mock.patch.object(editor_module.theming, "restore")
        self.paint = paint.start()
        self.restore = restore.start()
        self.addCleanup(paint.stop)
        self.addCleanup(restore.stop)

    def editor(self, theme=None, is_new=True, on_saved=None):
        theme = theme or Theme("", "Midnight", "dark")
        dialog = ThemeEditorDialog(self.win, self.store, theme, is_new, on_saved=on_saved)
        self.addCleanup(dialog.force_close)
        self.pump()
        return dialog


@needs_display
class LayoutTests(_EditorCase):
    def test_a_row_per_key_and_the_first_section_shown(self):
        dialog = self.editor()
        self.assertEqual(set(dialog.rows), {spec.key for spec in THEME_KEYS})
        self.assertEqual(dialog.stack.get_visible_child_name(), SECTIONS[0])
        self.assertEqual(dialog.get_title(), self.said("theme_editor.title.new"))
        self.assertEqual(
            dialog.window_title.get_subtitle(),
            self.said("theme_editor.subtitle.dark", name="Midnight"),
        )

    def test_an_edit_says_so(self):
        dialog = self.editor(Theme("night", "Night", "light"), is_new=False)
        self.assertEqual(dialog.get_title(), self.said("theme_editor.title.edit"))

    def test_nothing_changed_reads_same_as_base(self):
        dialog = self.editor()
        for row in dialog.rows.values():
            self.assertEqual(row.get_subtitle(), self.said("theme_editor.same_as_base"))
            self.assertFalse(row.reset_button.get_sensitive())
            self.assertFalse(row.warning_icon.get_visible())
        self.assertFalse(dialog.reset_all_button.get_sensitive())

    def test_sections_switch_from_the_list_and_from_the_narrow_row(self):
        dialog = self.editor()
        dialog.section_list.select_row(dialog.section_rows["text"])
        self.assertEqual(dialog.stack.get_visible_child_name(), "text")
        self.assertEqual(dialog.section_combo.get_selected(), SECTIONS.index("text"))
        dialog.section_combo.set_selected(SECTIONS.index("accent"))
        self.assertEqual(dialog.current_section, "accent")
        self.assertIs(dialog.section_list.get_selected_row(), dialog.section_rows["accent"])
        # Nothing selected, or the same section again: nothing moves.
        dialog._on_section_row_selected(dialog.section_list, None)
        dialog._on_section_row_selected(dialog.section_list, dialog.section_rows["accent"])
        with mock.patch.object(dialog.section_combo, "get_selected", return_value=99):
            dialog._on_section_combo_changed(dialog.section_combo, None)
        self.assertEqual(dialog.current_section, "accent")

    def test_narrow_stacks_the_preview_over_the_controls(self):
        dialog = self.editor()
        dialog.set_narrow(True)
        dialog.set_narrow(True)
        self.assertFalse(dialog.sidebar.get_visible())
        self.assertTrue(dialog.section_combo_list.get_visible())
        self.assertIs(dialog.controls.get_first_child(), dialog.preview_column)
        self.assertIs(dialog.reset_all_button.get_parent(), dialog.controls)
        self.assertEqual(dialog.preview.get_content_height(), editor_module.NARROW_PREVIEW_HEIGHT)
        dialog.set_narrow(False)
        self.assertTrue(dialog.sidebar.get_visible())
        self.assertIs(dialog.preview_column.get_parent(), dialog.body)
        self.assertIs(dialog.reset_all_button.get_parent(), dialog.sidebar)
        self.assertEqual(dialog.preview.get_content_height(), editor_module.PREVIEW_HEIGHT)

    def test_the_breakpoint_drives_the_narrow_layout(self):
        dialog = self.editor()
        dialog.narrow_breakpoint.emit("apply")
        self.assertTrue(dialog.narrow)
        dialog.narrow_breakpoint.emit("unapply")
        self.assertFalse(dialog.narrow)

    def test_the_swatch_draws_its_color(self):
        swatch = Swatch("#ff0000")
        swatch.set_color("#00ff00")
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 40, 26)
        swatch._draw(None, cairo.Context(surface), 40, 26)
        surface.flush()
        data = surface.get_data()
        offset = 13 * surface.get_stride() + 20 * 4
        self.assertEqual((data[offset + 2], data[offset + 1], data[offset]), (0, 255, 0))


@needs_display
class ValueTests(_EditorCase):
    def test_a_picked_color_is_shown_and_can_be_reset(self):
        dialog = self.editor()
        row = dialog.rows["library_bg"]
        row.picker.set_color("#24283b")
        self.assertEqual(dialog.draft.values, {"library_bg": "#24283b"})
        self.assertEqual(row.get_subtitle(), "#24283B")
        self.assertTrue(row.reset_button.get_sensitive())
        self.assertTrue(dialog.reset_all_button.get_sensitive())
        self.assertEqual(dialog.preview.colors["library_bg"], "#24283b")
        row.reset_button.emit("clicked")
        self.assertEqual(dialog.draft.values, {})
        # Moving the picker back to the base color does not count as a pick.
        self.assertEqual(row.picker.color, dialog.draft.effective("library_bg"))
        self.assertEqual(row.get_subtitle(), self.said("theme_editor.same_as_base"))

    def test_reset_all(self):
        dialog = self.editor()
        dialog.set_value("card_bg", "#101010")
        dialog.set_value("accent", "#ff7800")
        dialog.reset_all_button.emit("clicked")
        self.assertEqual(dialog.draft.values, {})

    def test_the_original_theme_is_left_alone(self):
        theme = Theme("night", "Night", "dark", {"card_bg": "#101010"})
        dialog = self.editor(theme, is_new=False)
        dialog.set_value("card_bg", "#202020")
        self.assertEqual(theme.values, {"card_bg": "#101010"})

    def test_low_contrast_warns_on_the_row_and_the_section(self):
        dialog = self.editor(Theme("", "Paper", "light"))
        dialog.set_value("text_secondary", "#d0d0d0")
        row = dialog.rows["text_secondary"]
        self.assertTrue(row.warning_icon.get_visible())
        self.assertIn(":1", row.get_subtitle())
        self.assertIn("4.5", row.get_subtitle())
        self.assertTrue(dialog.section_icons["text"].get_visible())
        self.assertFalse(dialog.section_icons["accent"].get_visible())
        # The surface on the other side of the pair warns too.
        self.assertTrue(dialog.section_icons["colors"].get_visible())
        dialog.reset_value("text_secondary")
        self.assertFalse(row.warning_icon.get_visible())
        self.assertFalse(dialog.section_icons["text"].get_visible())


@needs_display
class LiveTests(_EditorCase):
    def test_the_switch_paints_the_app_and_turning_it_off_restores(self):
        dialog = self.editor()
        dialog.live_row.set_active(True)
        self.paint.assert_called_with("dark", {})
        dialog.set_value("card_bg", "#101010")
        self.paint.assert_called_with("dark", {"card_bg": "#101010"})
        dialog.live_row.set_active(False)
        self.restore.assert_called_once()
        dialog.set_live(False)
        self.restore.assert_called_once()

    def test_cancel_restores_what_the_switch_painted(self):
        dialog = self.editor()
        dialog.present(self.win)
        dialog.live_row.set_active(True)
        dialog.cancel_button.emit("clicked")
        self.pump_until(lambda: self.restore.called)
        self.restore.assert_called_once()

    def test_closing_without_the_switch_restores_nothing(self):
        dialog = self.editor()
        dialog._on_closed()
        self.restore.assert_not_called()


@needs_display
class SaveTests(_EditorCase):
    def test_saving_a_new_theme_creates_it(self):
        saved = []
        dialog = self.editor(on_saved=saved.append)
        dialog.set_value("card_bg", "#2f3549")
        dialog.save_button.emit("clicked")
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0].id, "midnight")
        self.assertEqual(self.store.get("midnight").values, {"card_bg": "#2f3549"})
        self.assertTrue(dialog.saved)

    def test_saving_with_the_switch_on_leaves_the_repaint_to_the_caller(self):
        dialog = self.editor()
        dialog.live_row.set_active(True)
        dialog.save()
        dialog._on_closed()
        self.restore.assert_not_called()

    def test_saving_an_edit_overwrites_it(self):
        theme = self.store.create("Night", "dark", {"card_bg": "#101010"})
        dialog = self.editor(theme, is_new=False)
        dialog.set_value("accent", "#ff7800")
        self.assertEqual(dialog.save().id, "night")
        self.assertEqual(self.store.get("night").values,
                         {"card_bg": "#101010", "accent": "#ff7800"})

    def test_a_failed_save_says_so_and_keeps_the_dialog(self):
        dialog = self.editor()
        with mock.patch.object(self.store, "create", side_effect=OSError("read-only")), \
                self.assertLogs("openemux.ui.theme_editor", level="WARNING"):
            self.assertIsNone(dialog.save())
        self.assertTrue(dialog.error_label.get_visible())
        self.assertFalse(dialog.saved)

    def test_open_theme_editor_presents_it(self):
        with mock.patch.object(ThemeEditorDialog, "present") as present:
            dialog = open_theme_editor(self.win, self.win, self.store,
                                       Theme("", "X", "light"), True)
        self.addCleanup(dialog.force_close)
        present.assert_called_once_with(self.win)


if __name__ == "__main__":
    unittest.main()
