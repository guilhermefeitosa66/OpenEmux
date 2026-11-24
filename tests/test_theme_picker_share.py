"""Exporting and importing a theme from Preferences (issue 1012)."""

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.gtk_display import HAVE_DISPLAY, needs_display

if HAVE_DISPLAY:
    from gi.repository import GLib, Gtk

    from openemux.core.config import ConfigManager
    from openemux.ui import theme_picker as picker_module
    from openemux.ui.theme_picker import ThemePicker, export_name


class _Window:
    def t(self, key, **kwargs):
        return key + ("|" + kwargs["name"] if "name" in kwargs else "")

    def _sync_theme_button(self):
        pass


class _Prefs:
    def __init__(self, config, root=None):
        self.win = _Window()
        self.config = config
        self.t = self.win.t
        self.toasts = []
        self.root = root

    def _toast(self, text):
        self.toasts.append(text)

    def get_root(self):
        return self.root


def _now(target):
    target()


@needs_display
class ShareTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.config = ConfigManager(self.tmp / "config.yaml")
        self.store = self.config.themes
        self.night = self.store.create("Night", "dark", {"card_bg": "#101010", "corner_radius": 20})
        self.prefs = _Prefs(self.config)
        apply = mock.patch.object(picker_module.theming, "apply_theme")
        self.apply = apply.start()
        self.addCleanup(apply.stop)
        idle = mock.patch.object(picker_module.GLib, "idle_add", lambda fn, *a: fn(*a))
        idle.start()
        self.addCleanup(idle.stop)
        self.picker = ThemePicker(self.prefs, spawn=_now)

    def select(self, theme_id):
        self.picker.combo.set_selected(self.picker.ids.index(theme_id))

    def test_export_name(self):
        self.assertEqual(export_name("Night"), "Night.openemux-theme")
        self.assertEqual(export_name('a/b:c*"'), "abc.openemux-theme")
        self.assertEqual(export_name("..."), "theme.openemux-theme")

    def test_export_writes_the_file_and_says_so(self):
        target = self.tmp / "out.openemux-theme"
        self.assertTrue(self.picker.export_to(self.night.id, str(target)))
        self.assertTrue(target.is_file())
        self.assertEqual(self.prefs.toasts, ["theme.custom.exported"])

    def test_export_failure_says_so(self):
        self.assertFalse(self.picker.export_to("gone", str(self.tmp / "x.openemux-theme")))
        self.assertEqual(self.prefs.toasts, ["theme.custom.failed"])

    def test_import_adds_selects_and_names_it(self):
        target = self.tmp / "night.openemux-theme"
        self.picker.export_to(self.night.id, str(target))
        self.picker.import_from(str(target))
        imported = [t for t in self.store.list() if t.id != self.night.id]
        self.assertEqual(imported[0].name, "Night (2)")
        self.assertEqual(imported[0].values["corner_radius"], 20)
        self.assertEqual(self.config.get_ui_settings()["theme"], imported[0].id)
        self.assertEqual(self.prefs.toasts[-1], "theme.custom.imported|Night (2)")

    def test_a_bad_file_is_refused_with_a_toast(self):
        bad = self.tmp / "bad.openemux-theme"
        bad.write_text("not a zip")
        self.picker.import_from(str(bad))
        self.assertEqual(self.prefs.toasts, ["theme.custom.import_failed"])
        self.assertEqual(len(self.store.list()), 1)

    def test_the_menu_has_export_and_the_import_row(self):
        self.assertIsNotNone(self.picker.actions.lookup_action("export"))
        with mock.patch.object(self.picker, "ask_import") as ask:
            self.picker.import_row.emit("activated")
        ask.assert_called_once()

    def test_the_export_dialog(self):
        self.select(self.night.id)
        with mock.patch.object(Gtk.FileDialog, "save") as save:
            dialog = self.picker.ask_export()
        save.assert_called_once()
        self.assertEqual(dialog.get_initial_name(), "Night.openemux-theme")
        with mock.patch.object(self.picker, "export_to") as export:
            self.picker._on_export_chosen(
                mock.Mock(save_finish=mock.Mock(side_effect=GLib.Error("x"))), None, "night")
            self.picker._on_export_chosen(
                mock.Mock(save_finish=mock.Mock(return_value=None)), None, "night")
            self.picker._on_export_chosen(
                mock.Mock(save_finish=mock.Mock(
                    return_value=mock.Mock(get_path=lambda: "/x.openemux-theme"))), None, "night")
        export.assert_called_once_with("night", "/x.openemux-theme")

    def test_export_of_a_theme_gone_meanwhile_reloads(self):
        self.select(self.night.id)
        self.store.delete(self.night.id)
        self.assertIsNone(self.picker.ask_export())

    def test_the_import_dialog(self):
        window = Gtk.Window()
        self.addCleanup(window.destroy)
        self.prefs.root = window
        with mock.patch.object(Gtk.FileDialog, "open") as opened:
            self.picker.ask_import()
        self.assertIs(opened.call_args[0][0], window)
        with mock.patch.object(self.picker, "import_from") as import_from:
            self.picker._on_import_chosen(
                mock.Mock(open_finish=mock.Mock(side_effect=GLib.Error("x"))), None)
            self.picker._on_import_chosen(mock.Mock(open_finish=mock.Mock(return_value=None)), None)
            self.picker._on_import_chosen(mock.Mock(open_finish=mock.Mock(
                return_value=mock.Mock(get_path=lambda: "/in.openemux-theme"))), None)
        import_from.assert_called_once_with("/in.openemux-theme")


@needs_display
class SpawnTests(unittest.TestCase):
    def test_the_default_spawn_runs_in_a_thread(self):
        done = []
        picker_module._spawn(lambda: done.append(1))
        for _ in range(100):
            if done:
                break
            import time
            time.sleep(0.01)
        self.assertEqual(done, [1])


if __name__ == "__main__":
    unittest.main()


@needs_display
class ReadyMadeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.config = ConfigManager(self.tmp / "config.yaml")
        self.store = self.config.themes
        self.mine = self.store.create("Mine", "dark")
        self.prefs = _Prefs(self.config)
        apply = mock.patch.object(picker_module.theming, "apply_theme")
        self.apply = apply.start()
        self.addCleanup(apply.stop)
        self.picker = ThemePicker(self.prefs, spawn=_now)

    def select(self, theme_id):
        self.picker.combo.set_selected(self.picker.ids.index(theme_id))

    def test_listed_after_the_built_ins_and_before_the_users(self):
        self.assertEqual(self.picker.ids[:8], ["system", "light", "dark", "pastel", "dracula",
                                               "kitty", "neon", "tokyo-night"])
        self.assertEqual(self.picker.ids[8], self.mine.id)
        self.assertEqual(picker_module.theme_label(self.prefs.t, self.store, "neon"),
                         "theme.ready.neon")

    def test_read_only_duplicate_and_export_only(self):
        self.select("dracula")
        self.assertFalse(self.picker.edit_button.get_visible())
        self.assertTrue(self.picker.menu_button.get_visible())
        actions = self.picker.actions
        self.assertFalse(actions.lookup_action("rename").get_enabled())
        self.assertFalse(actions.lookup_action("delete").get_enabled())
        self.assertTrue(actions.lookup_action("duplicate").get_enabled())
        self.assertTrue(actions.lookup_action("export").get_enabled())
        self.select(self.mine.id)
        self.assertTrue(actions.lookup_action("rename").get_enabled())
        self.select("system")
        self.assertFalse(self.picker.menu_button.get_visible())

    def test_duplicating_one_makes_an_editable_copy_and_picks_it(self):
        self.select("kitty")
        copy = self.picker.duplicate()
        self.assertEqual(copy.name, "theme.custom.copy_name|theme.ready.kitty")
        self.assertEqual(self.config.get_ui_settings()["theme"], copy.id)
        self.assertTrue(self.store.get(copy.id).image_path("library"))

    def test_a_card_per_theme_and_a_click_applies_it(self):
        self.assertEqual(list(self.picker.card_buttons), ["pastel", "dracula", "kitty", "neon",
                                                          "tokyo-night"])
        self.picker.card_buttons["neon"].emit("clicked")
        self.assertEqual(self.config.get_ui_settings()["theme"], "neon")
        self.apply.assert_called_with("neon", store=self.store)
        self.assertTrue(self.picker.card_buttons["neon"].has_css_class("ready-theme-current"))
        self.assertFalse(self.picker.card_buttons["kitty"].has_css_class("ready-theme-current"))
        self.select("system")
        self.assertFalse(self.picker.card_buttons["neon"].has_css_class("ready-theme-current"))
        self.assertTrue(self.picker.card_buttons["neon"].get_child() is not None)
