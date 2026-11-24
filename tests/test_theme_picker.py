"""Preferences' theme picker and the user's themes (issue 1011)."""

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.gtk_display import HAVE_DISPLAY, needs_display

if HAVE_DISPLAY:
    from gi.repository import Adw

    from openemux.core.config import ConfigManager
    from openemux.ui import theme_picker as picker_module
    from openemux.ui.theme_picker import ThemePicker, copy_name, theme_choices, theme_label


class _Window:
    def __init__(self):
        self.synced = 0

    def t(self, key, **kwargs):
        return key + ("|" + kwargs["name"] if "name" in kwargs else "")

    def _sync_theme_button(self):
        self.synced += 1


class _Prefs:
    def __init__(self, config):
        self.win = _Window()
        self.config = config
        self.t = self.win.t
        self.toasts = []

    def _toast(self, text):
        self.toasts.append(text)


@needs_display
class _PickerCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.config = ConfigManager(self.tmp / "config.yaml")
        self.store = self.config.themes
        self.night = self.store.create("Night", "dark", {"card_bg": "#101010"})
        self.paper = self.store.create("Paper", "light")
        self.prefs = _Prefs(self.config)
        apply = mock.patch.object(picker_module.theming, "apply_theme")
        self.apply = apply.start()
        self.addCleanup(apply.stop)
        editor = mock.patch.object(picker_module, "open_theme_editor")
        self.open_editor = editor.start()
        self.addCleanup(editor.stop)
        self.dialogs = []
        present = mock.patch.object(
            Adw.AlertDialog, "present", lambda dialog, *a: self.dialogs.append(dialog)
        )
        present.start()
        self.addCleanup(present.stop)

    def picker(self):
        return ThemePicker(self.prefs)

    def select(self, picker, theme_id):
        picker.combo.set_selected(picker.ids.index(theme_id))


@needs_display
class ListTests(_PickerCase):
    def test_built_ins_first_then_the_users_themes_by_name(self):
        picker = self.picker()
        ready = ["pastel", "dracula", "kitty", "neon", "tokyo-night"]
        self.assertEqual(picker.ids, ["system", "light", "dark", *ready, "night", "paper"])
        model = picker.combo.get_model()
        self.assertEqual(model.get_string(8), "Night")
        self.assertEqual(picker.selected_id(), "system")

    def test_the_stored_theme_is_selected(self):
        self.config.set_theme("paper")
        self.assertEqual(self.picker().selected_id(), "paper")

    def test_a_missing_stored_theme_shows_system_without_rewriting_it(self):
        self.config.set_theme("gone")
        picker = self.picker()
        self.assertEqual(picker.selected_id(), "system")
        self.assertEqual(self.config.get_ui_settings()["theme"], "gone")
        self.apply.assert_not_called()

    def test_edit_and_the_menu_show_only_for_the_users_themes(self):
        picker = self.picker()
        self.assertFalse(picker.edit_button.get_visible())
        self.assertFalse(picker.menu_button.get_visible())
        self.select(picker, "night")
        self.assertTrue(picker.edit_button.get_visible())
        self.assertTrue(picker.menu_button.get_visible())

    def test_picking_a_theme_stores_and_applies_it(self):
        picker = self.picker()
        self.select(picker, "night")
        self.assertEqual(self.config.get_ui_settings()["theme"], "night")
        self.apply.assert_called_once_with("night", store=self.store)
        self.assertEqual(self.prefs.win.synced, 1)

    def test_an_impossible_index_changes_nothing(self):
        picker = self.picker()
        row = mock.Mock()
        row.get_selected.return_value = 99
        picker.on_selected(row)
        self.apply.assert_not_called()
        with mock.patch.object(picker.combo, "get_selected", return_value=99):
            self.assertIsNone(picker.selected_id())

    def test_the_menu_actions_are_wired(self):
        picker = self.picker()
        self.select(picker, "night")
        group = picker.actions
        group.activate_action("rename", None)
        group.activate_action("delete", None)
        self.assertEqual(len(self.dialogs), 2)
        group.activate_action("duplicate", None)
        self.assertEqual(len(self.store.list()), 3)

    def test_the_new_row_and_edit_button_open_their_dialogs(self):
        picker = self.picker()
        picker.new_row.emit("activated")
        self.assertEqual(len(self.dialogs), 1)
        self.select(picker, "night")
        picker.edit_button.emit("clicked")
        self.open_editor.assert_called_once()


@needs_display
class HelperTests(_PickerCase):
    def test_choices_and_labels(self):
        t = self.prefs.t
        self.assertEqual(
            theme_choices(t, self.store),
            [("system", "theme.system"), ("light", "theme.light"), ("dark", "theme.dark"),
             ("pastel", "theme.ready.pastel"), ("dracula", "theme.ready.dracula"),
             ("kitty", "theme.ready.kitty"), ("neon", "theme.ready.neon"),
             ("tokyo-night", "theme.ready.tokyo-night"),
             ("night", "Night"), ("paper", "Paper")],
        )
        self.assertEqual(theme_label(t, self.store, "dark"), "theme.dark")
        self.assertEqual(theme_label(t, self.store, "night"), "Night")
        self.assertEqual(theme_label(t, self.store, "gone"), "theme.system")

    def test_a_copys_suffix_always_fits(self):
        def t(key, name):
            return f"{name} (copy)"
        self.assertEqual(copy_name(t, "Night"), "Night (copy)")
        long_name = "x" * 64
        made = copy_name(t, long_name)
        self.assertEqual(len(made), 64)
        self.assertTrue(made.endswith(" (copy)"))


@needs_display
class NewThemeTests(_PickerCase):
    def test_create_is_enabled_by_a_name(self):
        picker = self.picker()
        dialog = picker.ask_new()
        self.assertFalse(dialog.get_response_enabled("create"))
        dialog.entry.set_text("Midnight")
        self.assertTrue(dialog.get_response_enabled("create"))
        dialog.entry.set_text("   ")
        self.assertFalse(dialog.get_response_enabled("create"))

    def test_the_base_starts_from_what_is_on_screen(self):
        picker = self.picker()
        with mock.patch.object(picker_module.theming, "is_dark", return_value=True):
            dialog = picker.ask_new()
        self.assertTrue(dialog.dark.get_active())
        with mock.patch.object(picker_module.theming, "is_dark", return_value=False):
            dialog = picker.ask_new()
        self.assertTrue(dialog.light.get_active())

    def test_create_opens_the_editor_on_an_unsaved_draft(self):
        picker = self.picker()
        with mock.patch.object(picker_module.theming, "is_dark", return_value=False):
            dialog = picker.ask_new()
        dialog.entry.set_text(" Midnight ")
        dialog.dark.set_active(True)
        dialog.emit("response", "create")
        args = self.open_editor.call_args
        draft = args.args[3]
        self.assertEqual((draft.name, draft.base, draft.id), ("Midnight", "dark", ""))
        self.assertTrue(args.args[4])
        self.assertEqual([t.id for t in self.store.list()], ["night", "paper"])

    def test_cancel_or_an_empty_name_opens_nothing(self):
        picker = self.picker()
        dialog = picker.ask_new()
        dialog.emit("response", "cancel")
        dialog.emit("response", "create")
        self.open_editor.assert_not_called()

    def test_a_saved_new_theme_becomes_the_apps_theme(self):
        picker = self.picker()
        picker.open_editor(picker_module.Theme("", "Midnight", "dark"), is_new=True)
        on_saved = self.open_editor.call_args.kwargs["on_saved"]
        made = self.store.create("Midnight", "dark")
        on_saved(made)
        self.assertEqual(self.config.get_ui_settings()["theme"], "midnight")
        self.assertEqual(picker.selected_id(), "midnight")
        self.apply.assert_called_with("midnight", store=self.store)


@needs_display
class EditTests(_PickerCase):
    def test_edit_opens_the_picked_theme(self):
        picker = self.picker()
        self.select(picker, "night")
        picker.edit()
        args = self.open_editor.call_args.args
        self.assertEqual((args[3].id, args[4]), ("night", False))

    def test_a_saved_edit_repaints_the_theme_in_use(self):
        self.config.set_theme("paper")
        picker = self.picker()
        self.select(picker, "night")
        self.apply.reset_mock()
        picker.edit()
        self.open_editor.call_args.kwargs["on_saved"](self.night)
        self.assertEqual(self.config.get_ui_settings()["theme"], "night")
        self.apply.assert_called_with("night", store=self.store)

    def test_a_theme_that_vanished_is_reported_and_the_list_reloaded(self):
        picker = self.picker()
        self.select(picker, "night")
        self.store.delete("night")
        with self.assertLogs("openemux.ui.theme_picker", level="WARNING"):
            self.assertIsNone(picker.edit())
        self.assertEqual(self.prefs.toasts, ["theme.custom.failed"])
        self.assertNotIn("night", picker.ids)


@needs_display
class DuplicateRenameDeleteTests(_PickerCase):
    def test_duplicate_makes_a_picked_copy(self):
        picker = self.picker()
        self.select(picker, "night")
        copy = picker.duplicate()
        self.assertEqual(copy.name, "theme.custom.copy_name|Night")
        self.assertEqual(copy.values, {"card_bg": "#101010"})
        self.assertEqual(picker.selected_id(), copy.id)
        self.assertEqual(self.config.get_ui_settings()["theme"], copy.id)

    def test_duplicate_of_a_vanished_theme_or_a_failing_disk(self):
        picker = self.picker()
        self.select(picker, "night")
        with mock.patch.object(self.store, "duplicate", side_effect=OSError("full")), \
                self.assertLogs("openemux.ui.theme_picker", level="WARNING"):
            self.assertIsNone(picker.duplicate())
        self.assertEqual(self.prefs.toasts, ["theme.custom.failed"])
        self.store.delete("night")
        self.assertIsNone(picker.duplicate())

    def test_rename(self):
        picker = self.picker()
        self.select(picker, "night")
        dialog = picker.ask_rename()
        self.assertEqual(dialog.entry.get_text(), "Night")
        dialog.entry.set_text("")
        self.assertFalse(dialog.get_response_enabled("rename"))
        dialog.entry.set_text("Late Night")
        self.assertTrue(dialog.get_response_enabled("rename"))
        dialog.emit("response", "cancel")
        self.assertEqual(self.store.get("night").name, "Night")
        dialog.emit("response", "rename")
        self.assertEqual(self.store.get("night").name, "Late Night")
        self.assertEqual(picker.combo.get_model().get_string(picker.ids.index("night")),
                         "Late Night")
        self.assertEqual(picker.selected_id(), "night")

    def test_a_failed_rename_is_reported(self):
        picker = self.picker()
        self.select(picker, "night")
        dialog = picker.ask_rename()
        dialog.entry.set_text("   ")
        with self.assertLogs("openemux.ui.theme_picker", level="WARNING"):
            dialog.emit("response", "rename")
        self.assertEqual(self.prefs.toasts, ["theme.custom.failed"])

    def test_rename_or_delete_a_vanished_theme(self):
        picker = self.picker()
        self.select(picker, "night")
        self.store.delete("night")
        self.assertIsNone(picker.ask_rename())
        self.select(picker, "paper")
        self.store.delete("paper")
        self.assertIsNone(picker.ask_delete())

    def test_deleting_the_theme_in_use_falls_back_to_system(self):
        picker = self.picker()
        self.select(picker, "night")
        dialog = picker.ask_delete()
        dialog.emit("response", "cancel")
        self.assertIsNotNone(self.store.get("night"))
        dialog.emit("response", "delete")
        self.assertIsNone(self.store.get("night"))
        self.assertEqual(self.config.get_ui_settings()["theme"], "system")
        self.assertEqual(picker.selected_id(), "system")
        self.apply.assert_called_with("system", store=self.store)

    def test_deleting_another_theme_keeps_the_one_in_use(self):
        picker = self.picker()
        self.select(picker, "night")
        dialog = picker.ask_delete()
        self.config.set_theme("paper")
        dialog.emit("response", "delete")
        self.assertEqual(self.config.get_ui_settings()["theme"], "paper")
        self.assertNotIn("night", picker.ids)

    def test_a_failed_delete_is_reported(self):
        picker = self.picker()
        self.select(picker, "night")
        dialog = picker.ask_delete()
        with mock.patch.object(self.store, "delete", side_effect=OSError("busy")), \
                self.assertLogs("openemux.ui.theme_picker", level="WARNING"):
            dialog.emit("response", "delete")
        self.assertEqual(self.prefs.toasts, ["theme.custom.failed"])


if __name__ == "__main__":
    unittest.main()
