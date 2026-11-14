"""The Settings page of Big Picture, driven the way a pad drives it.

Every row here mirrors a row of the desktop's Preferences dialog and must
write the same config the same way, so each test flips, picks or types on
a row and reads the config (or the window call) back. The pickers, the
network and the threads are replaced, as in ``test_preferences.py``.
"""

# Builds real windows through tests.window_harness (via BigPictureCase): CI runs this
# module in the windowed process, with the other window tests.

import sys
import types
import unittest
from unittest import mock

from tests.bigpicture_harness import BigPictureCase
from tests.gtk_display import HAVE_DISPLAY, needs_display

if HAVE_DISPLAY:
    import gi

    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import Gdk, GdkPixbuf, GLib, Gtk

    from openemux.core import bezels, retroachievements, save_backup
    from openemux.core.bios_importer import console_bios_names
    from openemux.core.bios_manager import get_console_bios_dir
    from openemux.core.systems import SYSTEM_IDS
    from openemux.ui.bigpicture import settings as settings_module
    from openemux.ui.bigpicture.widgets import ROW_INFO, ROW_NUMBER, ROW_SWITCH, Row

INPUT_MODULE = "openemux.ui.bigpicture.settings_input"


class _Core:
    def __init__(self, filename, display_name):
        self.filename = filename
        self.display_name = display_name


class _FakeInputSection:
    """What the real section promises the page: a widget and four calls."""

    instances = []

    def __init__(self, shell, page):
        self.shell = shell
        self.page = page
        self.widget = Gtk.Button(label="input")
        self.calls = []
        _FakeInputSection.instances.append(self)

    def focus_default(self):
        self.calls.append("focus")
        return self.widget.grab_focus()

    def select_console(self, console_id):
        self.calls.append(("select", console_id))

    def refresh(self):
        self.calls.append("refresh")

    def has_unsaved(self):
        return False


class _SyncThread:
    """A thread that runs its target on start, so a test sees the end."""

    def __init__(self, target=None, daemon=None):
        self.target = target

    def start(self):
        self.target()


class SettingsCase(BigPictureCase):
    def open_settings(self, section=None, console=None):
        self.show()
        page = self.shell.open_settings(section, console=console)
        self.pump()
        return page

    def pick(self, option_id):
        chooser = self.shell._chooser
        self.assertIs(self.visible_page(), chooser)
        row = next(row for row in chooser.rows if row.option_id == option_id)
        row.emit("clicked")
        self.pump()

    def chooser_ids(self):
        return [row.option_id for row in self.shell._chooser.rows]

    def type_text(self, text):
        entry = self.shell._text_entry
        self.assertIs(self.visible_page(), entry)
        entry.osk.set_text(text)
        entry.osk.done()
        self.pump()

    def ask(self, row, response="confirm"):
        """Click a row that asks first, and answer."""
        with self.caught_dialog() as dialogs:
            row.emit("clicked")
        self.assertEqual(len(dialogs), 1)
        dialogs[0].emit("response", response)
        self.pump()
        return dialogs[0]

    def swap_input_module(self, module):
        had = INPUT_MODULE in sys.modules
        old = sys.modules.get(INPUT_MODULE)
        sys.modules[INPUT_MODULE] = module

        def _restore():
            if had:
                sys.modules[INPUT_MODULE] = old
            else:
                sys.modules.pop(INPUT_MODULE, None)

        self.addCleanup(_restore)

    def fake_input_module(self):
        module = types.ModuleType(INPUT_MODULE)
        module.InputSection = _FakeInputSection
        _FakeInputSection.instances = []
        self.swap_input_module(module)

    def file_dialogs(self):
        dialogs = []

        def _factory():
            dialog = mock.Mock()
            dialogs.append(dialog)
            return dialog

        patcher = mock.patch.object(settings_module.Gtk, "FileDialog", _factory)
        patcher.start()
        self.addCleanup(patcher.stop)
        return dialogs

    @staticmethod
    def chosen(path):
        dialog = mock.Mock()
        source = mock.Mock()
        source.get_path.return_value = path
        dialog.open_finish.return_value = source
        dialog.save_finish.return_value = source
        return dialog

    @staticmethod
    def dismissed():
        dialog = mock.Mock()
        dialog.open_finish.side_effect = GLib.Error("dismissed")
        dialog.save_finish.side_effect = GLib.Error("dismissed")
        dialog.open_multiple_finish.side_effect = GLib.Error("dismissed")
        return dialog


@needs_display
class ThePage(SettingsCase):
    def test_opens_on_library_with_the_sections_on_the_left(self):
        page = self.open_settings()
        self.assertIs(self.visible_page(), page)
        self.assertIs(page, self.shell._settings)
        self.assertEqual(page.get_tag(), "bp-settings")
        self.assertEqual(page.current, "library")
        self.assertEqual(list(page.buttons), list(settings_module.SECTION_NAMES))
        self.assertTrue(page.buttons["library"].has_css_class("bp-current"))
        self.assertTrue(page.buttons["library"].has_css_class("bp-section"))
        self.assertFalse(page.buttons["video"].has_css_class("bp-current"))
        self.assertEqual(page.stack.get_visible_child_name(), "library")
        self.assertTrue(page.sections["library"].built)
        self.assertFalse(page.sections["video"].built)
        self.assertIs(self.focus_widget(), page.sections["library"].rows["roms_path"])
        glyphs = self.win.navigation.glyphs()
        hints = page.hints(glyphs, self.win.t)
        self.assertEqual(hints[0], (glyphs["confirm"], self.said("big_picture.hints.change")))
        self.assertEqual(hints[2], (glyphs["consoles"], self.said("big_picture.hints.section")))
        self.assertFalse(page.show_section("nonsense"))

        # The shoulders walk the sections, wrapping, and land on the first row.
        self.assertTrue(self.shell.step_console(1))
        self.pump()
        self.assertEqual(page.current, "bios")
        self.assertTrue(page.sections["bios"].built)
        self.assertIs(self.focus_widget(), page.sections["bios"].rows["reload"])
        self.assertTrue(self.shell.step_console(-1))
        self.pump()
        self.assertEqual(page.current, "library")
        self.assertTrue(self.shell.step_console(-1))
        self.pump()
        self.assertEqual(page.current, "system")
        # So does A on a section button.
        page.buttons["video"].emit("clicked")
        self.pump()
        self.assertEqual(page.current, "video")
        self.assertIs(self.focus_widget(), page.sections["video"].rows["view_mode"])
        # B leaves Settings, never the mode.
        self.press("back")
        self.assertIs(self.visible_page(), self.shell.home)
        self.assertTrue(self.win.big_picture)

    def test_opening_on_a_section_builds_that_one_and_reopening_reads_everything_again(self):
        page = self.open_settings("video")
        self.assertEqual(page.current, "video")
        self.assertTrue(page.sections["video"].built)
        self.assertFalse(page.sections["library"].built)
        row = page.sections["video"].rows["view_mode"]
        self.press("back")
        # Changed on the desktop meanwhile: the rows are built again on the way in.
        self.config.set_import_mode("link")
        self.open_settings("library")
        self.assertIsNot(page.sections["video"].rows.get("view_mode"), None)
        self.assertEqual(
            page.sections["library"].rows["import_mode"].value_label.get_label(),
            self.said("import_mode.link"),
        )
        self.shell.step_console(-1)
        self.pump()
        self.assertEqual(page.current, "system")
        self.assertTrue(page.sections["system"].built)
        page.show_section("video")
        self.pump()
        self.assertEqual(page.current, "video")
        self.assertIsNot(page.sections["video"].rows["view_mode"], row)

    def test_coming_back_from_a_chooser_keeps_the_rows_and_the_focus(self):
        page = self.open_settings("video")
        row = page.sections["video"].rows["view_mode"]
        row.emit("clicked")
        self.pump()
        self.assertTrue(page._returning)
        chooser = self.shell._chooser
        self.assertIs(self.visible_page(), chooser)
        self.assertEqual(chooser.get_title(), self.said("settings.ui.view_mode.title"))
        with mock.patch.object(self.win, "_apply_view_mode") as apply_mode:
            self.pick("list")
        apply_mode.assert_called_once_with("list")
        self.assertIs(self.visible_page(), page)
        self.assertFalse(page._returning)
        self.assertIs(page.sections["video"].rows["view_mode"], row)
        self.assertEqual(row.value_label.get_label(), self.said("view_mode.list"))
        self.assertIs(self.focus_widget(), row)
        # Home while a chooser is open: the pending return is void.
        row.emit("clicked")
        self.pump()
        self.assertTrue(page._returning)
        self.shell.go_home()
        self.pump()
        self.assertFalse(page._returning)
        # A row that is gone is no place to land: the section's first row is.
        page._focus_row = Row("gone")
        self.open_settings()
        self.assertIs(self.focus_widget(), page.sections["video"].rows["view_mode"])

    def test_the_input_section_is_placed_pointed_at_a_console_and_refreshed(self):
        self.fake_input_module()
        page = self.open_settings("input", console="SFC")
        self.assertEqual(len(_FakeInputSection.instances), 1)
        section = _FakeInputSection.instances[0]
        self.assertIs(section.shell, self.shell)
        self.assertIs(section.page, page)
        self.assertIs(page.input, section)
        self.assertIs(page.stack.get_child_by_name("input"), section.widget)
        self.assertIn(("select", "SFC"), section.calls)
        self.assertIn("focus", section.calls)
        self.assertIs(self.focus_widget(), section.widget)
        self.assertNotIn("refresh", section.calls)
        # Pointed at another console while on screen.
        page.show_section("input", console="FC")
        self.assertEqual(section.calls[-1], ("select", "FC"))
        # Reopened from home: refreshed, not rebuilt.
        self.press("back")
        self.open_settings()
        self.assertEqual(len(_FakeInputSection.instances), 1)
        self.assertIn("refresh", section.calls)
        self.assertFalse(section.has_unsaved())

    def test_without_its_module_the_input_section_says_so(self):
        self.swap_input_module(None)
        page = self.open_settings("input")
        self.assertIsNone(page.input)
        section = page.sections["input"]
        self.assertIsInstance(section, settings_module.UnavailableSection)
        self.assertEqual(section.rows["unavailable"].kind, ROW_INFO)
        self.assertEqual(
            section.rows["unavailable"].title_label.get_label(),
            self.said("big_picture.settings.input.unavailable.title"),
        )
        self.assertIsNone(section.first_row())
        # Nothing to land on in the column: the pad lands on the section button.
        self.assertTrue(page.focus_default())
        self.assertIs(self.focus_widget(), page.buttons["input"])
        page.show_section("input")
        self.assertEqual(page.stack.get_visible_child_name(), "input")

    def test_the_roms_path_row_follows_the_window(self):
        page = self.open_settings()
        self.config.set_roms_path(str(self.tmp / "elsewhere"))
        page.refresh_roms_path()
        self.assertEqual(
            page.sections["library"].rows["roms_path"].value_label.get_label(),
            str(self.config.get_roms_path()),
        )
        fresh = settings_module.SettingsPage(self.shell)
        fresh.refresh_roms_path()  # not built yet: nothing to refresh
        self.assertFalse(fresh.sections["library"].built)


@needs_display
class TheLibrarySection(SettingsCase):
    def test_the_folder_rows_and_the_import_mode(self):
        page = self.open_settings("library")
        rows = page.sections["library"].rows
        self.assertEqual(rows["roms_path"].value_label.get_label(), str(self.config.get_roms_path()))
        with mock.patch.object(self.win, "_choose_roms_path") as choose:
            rows["roms_path"].emit("clicked")
        choose.assert_called_once()
        with mock.patch.object(self.win, "_open_roms_folder") as open_folder:
            rows["open_folder"].emit("clicked")
        open_folder.assert_called_once()
        rows["import_mode"].emit("clicked")
        self.pump()
        self.assertEqual(self.chooser_ids(), ["copy", "link"])
        self.assertEqual(self.shell._chooser.current, "copy")
        self.pick("link")
        self.assertEqual(self.config.get_import_mode(), "link")
        self.assertEqual(rows["import_mode"].value_label.get_label(), self.said("import_mode.link"))

    def test_scan_asks_for_a_scope_and_sync_opens_the_covers_page(self):
        page = self.open_settings("library")
        rows = page.sections["library"].rows
        self.win.sidebar.select("SFC")
        self.pump()
        rows["scan"].emit("clicked")
        self.pump()
        ids = self.chooser_ids()
        self.assertEqual(ids[0], settings_module.ALL_CONSOLES_ID)
        self.assertEqual(ids[1:], list(SYSTEM_IDS))
        self.assertEqual(self.shell._chooser.current, "SFC")
        with mock.patch.object(self.win, "_rescan_single_console") as rescan:
            self.pick("FC")
        rescan.assert_called_once_with("FC", show_toast=True)
        self.win.sidebar.select(settings_module.ALL_CONSOLES_ID)
        self.pump()
        rows["scan"].emit("clicked")
        self.pump()
        self.assertEqual(self.shell._chooser.current, settings_module.ALL_CONSOLES_ID)
        with mock.patch.object(self.win, "_rescan_all_consoles") as rescan:
            self.pick(settings_module.ALL_CONSOLES_ID)
        rescan.assert_called_once_with(show_toast=True)
        rows["sync"].emit("clicked")
        self.pump()
        self.assertIs(self.visible_page(), self.shell._covers)

    def test_the_console_order_moves_with_left_and_right(self):
        page = self.open_settings("library")
        library = page.sections["library"]
        consoles, present = library._console_order_list()
        self.assertEqual(set(consoles), set(self.win.visible_consoles))
        first, second = consoles[0], consoles[1]
        rows = library.rows
        self.assertEqual(rows[f"order:{first}"].kind, ROW_NUMBER)
        self.assertEqual(rows[f"order:{first}"].number_label.get_label(), "1")
        self.assertFalse(rows[f"order:{first}"].subtitle_label.get_visible())
        # The top row cannot go up.
        self.assertTrue(rows[f"order:{first}"].step(-1))
        self.assertEqual(library._console_order_list()[0], consoles)
        self.assertIs(library.rows[f"order:{first}"], rows[f"order:{first}"])
        # Down it goes, the rows are rebuilt and the pad stays on it.
        self.assertTrue(rows[f"order:{first}"].step(1))
        self.pump()
        self.assertEqual(library._console_order_list()[0][:2], [second, first])
        self.assertEqual(self.win.visible_consoles[:2], [second, first])
        moved = library.rows[f"order:{first}"]
        self.assertIsNot(moved, rows[f"order:{first}"])
        self.assertEqual(moved.number_label.get_label(), "2")
        self.assertIs(self.focus_widget(), moved)
        # A console the order remembers with no games keeps its row.
        self.config.set_console_order(["GBA", second, first])
        library._build_order_rows()
        self.assertEqual(
            library.rows["order:GBA"].subtitle_label.get_label(), self.said("prefs.console_order.no_games")
        )
        self.assertEqual(library.rows["order:GBA"].number_label.get_label(), "1")
        # Restore asks first; Cancel changes nothing.
        self.ask(library.rows["restore_order"], "cancel")
        self.assertEqual(self.config.get_console_order(), ["GBA", second, first])
        self.ask(library.rows["restore_order"])
        self.assertEqual(self.config.get_console_order(), [])
        self.assertNotIn("order:GBA", library.rows)
        # With no library at all the group says so.
        with mock.patch.object(self.win, "visible_consoles", []):
            library._build_order_rows()
        self.assertEqual(library.rows["order:empty"].kind, ROW_INFO)

    def test_the_artwork_providers_reorder_toggle_and_show_the_account_rows(self):
        page = self.open_settings("library")
        library = page.sections["library"]
        ids = [entry["id"] for entry in self.config.get_artwork_providers()]
        rows = library.rows
        self.assertIsInstance(rows[f"provider:{ids[0]}"], settings_module.OrderedRow)
        self.assertEqual(rows[f"provider:{ids[0]}"].kind, ROW_SWITCH)
        self.assertTrue(rows[f"provider:{ids[0]}"].title_label.get_label().startswith("1. "))
        # Right (or Down on the desktop) moves it under the next one.
        self.assertTrue(rows[f"provider:{ids[0]}"].step(1))
        self.pump()
        now = [entry["id"] for entry in self.config.get_artwork_providers()]
        self.assertEqual(now[:2], [ids[1], ids[0]])
        moved = library.rows[f"provider:{ids[0]}"]
        self.assertTrue(moved.title_label.get_label().startswith("2. "))
        self.assertIs(self.focus_widget(), moved)
        # The last one cannot go further down.
        library.rows[f"provider:{now[-1]}"].step(1)
        self.pump()
        self.assertEqual([entry["id"] for entry in self.config.get_artwork_providers()], now)
        # The keyboard's arrows do the same; other keys are left alone.
        row = library.rows[f"provider:{now[0]}"]
        self.assertTrue(row._on_key_pressed(None, Gdk.KEY_Right, 0, 0))
        self.assertEqual([entry["id"] for entry in self.config.get_artwork_providers()][1], now[0])
        row = library.rows[f"provider:{now[0]}"]
        self.assertTrue(row._on_key_pressed(None, Gdk.KEY_Left, 0, 0))
        self.assertFalse(row._on_key_pressed(None, Gdk.KEY_a, 0, 0))
        self.assertEqual([entry["id"] for entry in self.config.get_artwork_providers()], now)

        # The switch enables or disables; ScreenScraper's account rows follow it.
        self.assertTrue(library.rows["ss_user"].get_visible())
        self.assertFalse(library.rows["ss_devid"].get_visible())
        library.rows["provider:screenscraper"].emit("clicked")
        self.assertFalse(
            next(e for e in self.config.get_artwork_providers() if e["id"] == "screenscraper")["enabled"]
        )
        self.assertFalse(library.rows["ss_user"].get_visible())
        self.assertFalse(library.rows["ss_advanced"].get_visible())
        self.assertFalse(library.rows["ss_hint"].get_visible())
        library.rows["provider:screenscraper"].emit("clicked")
        self.assertTrue(library.rows["ss_user"].get_visible())
        # Advanced opens the developer credential rows.
        library.rows["ss_advanced"].emit("clicked")
        self.assertTrue(library.rows["ss_devid"].get_visible())
        self.assertTrue(library.rows["ss_devpassword"].get_visible())
        library.rows["ss_advanced"].emit("clicked")
        self.assertFalse(library.rows["ss_devid"].get_visible())
        # Official builds carry the credential and say so instead of asking.
        self.assertTrue(library.rows["ss_hint"].get_visible())
        self.assertFalse(library.rows["ss_hint_embedded"].get_visible())
        with mock.patch.object(settings_module, "has_embedded_dev_credentials", return_value=True):
            library.build()
        self.assertFalse(library.rows["ss_hint"].get_visible())
        self.assertTrue(library.rows["ss_hint_embedded"].get_visible())

    def test_the_screenscraper_account_is_typed_on_the_keyboard(self):
        page = self.open_settings("library")
        rows = page.sections["library"].rows
        self.assertEqual(rows["ss_user"].value_label.get_label(), self.said("big_picture.settings.empty"))
        rows["ss_user"].emit("clicked")
        self.pump()
        self.assertFalse(self.shell._text_entry.osk.password)
        self.type_text("player1")
        self.assertEqual(self.config.get_cover_sync_settings()["screenscraper_user"], "player1")
        self.assertEqual(rows["ss_user"].value_label.get_label(), "player1")
        self.assertIs(self.focus_widget(), rows["ss_user"])
        rows["ss_password"].emit("clicked")
        self.pump()
        self.assertTrue(self.shell._text_entry.osk.password)
        self.type_text("secret")
        self.assertEqual(self.config.get_cover_sync_settings()["screenscraper_password"], "secret")
        self.assertEqual(rows["ss_password"].value_label.get_label(), settings_module.PASSWORD_MASK)
        rows["ss_advanced"].emit("clicked")
        rows["ss_devid"].emit("clicked")
        self.pump()
        self.type_text("")
        self.assertEqual(self.config.get_cover_sync_settings()["screenscraper_devid"], "")
        self.assertEqual(rows["ss_devid"].value_label.get_label(), self.said("big_picture.settings.empty"))


@needs_display
class TheBiosSection(SettingsCase):
    def test_a_console_row_opens_its_files_and_the_status_reloads(self):
        page = self.open_settings("bios")
        bios = page.sections["bios"]
        keys = [key for key in bios.rows if key.startswith("bios:")]
        self.assertEqual(keys, sorted(keys))
        row = bios.rows["bios:PS"]
        self.assertEqual(row.title_label.get_label(), settings_module.console_title("PS"))
        self.assertTrue(row.subtitle_label.get_label().startswith("0/"))
        row.emit("clicked")
        self.pump()
        console_page = bios.console_page
        self.assertIs(self.visible_page(), console_page)
        self.assertEqual(console_page.get_tag(), "bp-bios-console")
        self.assertIs(self.focus_widget(), console_page.import_row)
        titles = [child.title_label.get_label() for child in _children(console_page.column) if isinstance(child, Row)]
        self.assertTrue(all(title.startswith("⚠") for title in titles[:-2]))
        self.assertTrue(any(self.said("bios.one_of", names="") .split(":")[0] in title for title in titles))
        with mock.patch.object(self.win, "_open_console_bios_folder") as open_folder:
            titles_rows = [child for child in _children(console_page.column) if isinstance(child, Row)]
            titles_rows[-1].emit("clicked")
        open_folder.assert_called_once_with("PS")
        # A file copied in by hand shows once the status is reloaded.
        name = console_bios_names("PS")[0]
        (get_console_bios_dir(self.config, "PS") / name).write_bytes(b"bios")
        bios.reload(show_toast=True)
        self.assertIn(self.said("bios.reloaded"), self.toasts)
        self.assertTrue(bios.rows["bios:PS"].subtitle_label.get_label().startswith("1/"))
        titles = [child.title_label.get_label() for child in _children(console_page.column) if isinstance(child, Row)]
        self.assertTrue(any(title.startswith("✓") and name in title for title in titles))
        # B returns to the list, on the console's row.
        self.press("back")
        self.assertIs(self.visible_page(), page)
        self.assertIs(self.focus_widget(), bios.rows["bios:PS"])
        # No requirements at all: one line says so.
        with mock.patch.object(settings_module, "scan_all_bios_status", return_value={}):
            bios.build()
        self.assertEqual(bios.rows["bios:none"].kind, ROW_INFO)

    def test_import_goes_through_the_picker_and_reports(self):
        page = self.open_settings("bios")
        bios = page.sections["bios"]
        dialogs = self.file_dialogs()
        with mock.patch.object(settings_module, "import_bios_files_async") as run:
            bios._on_files_chosen(self.dismissed(), None, "PS")
            none = mock.Mock()
            none.open_multiple_finish.return_value = None
            bios._on_files_chosen(none, None, "PS")
            empty = mock.Mock()
            files = mock.Mock()
            files.get_n_items.return_value = 1
            item = mock.Mock()
            item.get_path.return_value = ""
            files.get_item.return_value = item
            empty.open_multiple_finish.return_value = files
            bios._on_files_chosen(empty, None, "PS")
        run.assert_not_called()

        bios.rows["bios:PS"].emit("clicked")
        self.pump()
        console_page = bios.console_page
        console_page.import_row.emit("clicked")
        dialog = dialogs[-1]
        dialog.set_title.assert_called_once_with(
            self.said("bios.import.dialog_title", console=settings_module.get_system_display_name("PS"))
        )
        args = dialog.open_multiple.call_args.args
        self.assertIs(args[0], self.win)
        self.assertEqual(args[2], bios._on_files_chosen)
        self.assertEqual(args[3], "PS")

        chosen = mock.Mock()
        files = mock.Mock()
        files.get_n_items.return_value = 1
        item = mock.Mock()
        item.get_path.return_value = "/tmp/scph5501.bin"
        files.get_item.return_value = item
        chosen.open_multiple_finish.return_value = files
        with mock.patch.object(settings_module, "import_bios_files_async") as run:
            bios._on_files_chosen(chosen, None, "PS")
        self.assertTrue(bios.import_running)
        self.assertFalse(console_page.import_row.get_sensitive())
        self.assertEqual(run.call_args.args[0], ["/tmp/scph5501.bin"])
        self.assertEqual(run.call_args.args[2], "PS")
        summary = {
            "console": "PS",
            "imported": [{"name": "scph5501.bin", "replaced": False}],
            "rejected": [],
        }
        with mock.patch.object(self.win, "sync_bios_warnings") as sync, self.caught_dialog() as shown:
            run.call_args.args[3](summary)
            self.pump()
        sync.assert_called_once_with(["PS"])
        self.assertEqual(len(shown), 1)
        self.assertEqual(shown[0].get_heading(), self.said("bios.import.heading_one"))
        self.assertFalse(bios.import_running)
        self.assertTrue(console_page.import_row.get_sensitive())

    def test_the_summary_dialog_explains_every_outcome(self):
        t = self.win.t
        imported = [{"name": "a.bin", "replaced": True}, {"name": "b.bin", "replaced": False}]
        rejected = [
            {"name": "c.bin", "reason": settings_module.REASON_ERROR, "error": "disk full"},
            {"name": "d.bin", "reason": settings_module.REASON_OTHER_CONSOLE, "consoles": ["SATURN"]},
            {"name": "e.bin", "reason": "unknown"},
        ]
        dialog = settings_module.bios_import_summary(t, {"console": "PS", "imported": imported, "rejected": []})
        self.assertEqual(dialog.get_heading(), t("bios.import.heading_all", count=2))
        self.assertEqual(dialog.get_body(), "")
        self.assertTrue(dialog.has_css_class("bp-dialog"))
        dialog = settings_module.bios_import_summary(t, {"console": "PS", "imported": imported, "rejected": rejected})
        self.assertEqual(dialog.get_heading(), t("bios.import.heading_some", imported=2, total=5))
        self.assertIn(settings_module.get_system_display_name("PS"), dialog.get_body())
        subtitles = [
            row.get_subtitle() for row in _descendants(dialog.get_extra_child())
            if isinstance(row, settings_module.Adw.ActionRow)
        ]
        self.assertEqual(subtitles[0], t("bios.import.replaced"))
        self.assertEqual(subtitles[1], "")
        self.assertEqual(subtitles[2], t("bios.import.reason_error", error="disk full"))
        self.assertEqual(
            subtitles[3],
            t("bios.import.reason_other_console", owners="Sega Saturn", console=settings_module.get_system_display_name("PS")),
        )
        self.assertEqual(subtitles[4], t("bios.import.reason_unknown", console=settings_module.get_system_display_name("PS")))
        dialog = settings_module.bios_import_summary(t, {"console": "PS", "imported": [], "rejected": rejected[:1]})
        self.assertEqual(dialog.get_heading(), t("bios.import.heading_none"))


@needs_display
class TheVideoSection(SettingsCase):
    def test_appearance_launch_and_bar_rows(self):
        page = self.open_settings("video")
        video = page.sections["video"]
        rows = video.rows
        rows["sort_order"].emit("clicked")
        self.pump()
        self.assertEqual(self.chooser_ids(), list(settings_module.SORT_ORDERS))
        with mock.patch.object(self.win, "_apply_sort_order") as apply_sort:
            self.pick("name_desc")
        apply_sort.assert_called_once_with("name_desc")
        self.assertEqual(rows["sort_order"].value_label.get_label(), self.said("sort_order.name_desc"))

        shader_row = rows["shader:SFC"]
        rows["show_all_shaders"].emit("clicked")
        self.assertTrue(self.config.get_shader_settings()["show_all_shaders"])
        self.assertIsNot(video.rows["shader:SFC"], shader_row)
        rows["fullscreen"].emit("clicked")
        self.assertTrue(self.config.get_ui_settings()["start_games_fullscreen"])
        with mock.patch.object(self.win, "_reload_current_page") as reload:
            rows["resume"].emit("clicked")
        self.assertTrue(self.config.get_auto_resume())
        reload.assert_called_once()
        rows["translucent"].emit("clicked")
        self.assertTrue(self.config.get_ui_settings()["translucent_game_bar"])

        # Restore asks first.
        self.config.set_shader_for_console("SFC", "crt_easymode")
        self.ask(rows["restore_shaders"], "cancel")
        self.assertEqual(self.config.get_shader_for_console("SFC"), "crt_easymode")
        self.ask(rows["restore_shaders"])
        self.assertNotEqual(self.config.get_shader_for_console("SFC"), "crt_easymode")
        self.assertIn(self.said("toast.shaders.defaults_restored"), self.toasts)

    def test_a_shader_per_console_including_one_the_catalog_does_not_list(self):
        page = self.open_settings("video")
        video = page.sections["video"]
        self.assertEqual(
            [key for key in video.rows if key.startswith("shader:")], [f"shader:{c}" for c in SYSTEM_IDS]
        )
        video.rows["shader:SFC"].emit("clicked")
        self.pump()
        options, selected = video._shader_options("SFC")
        self.assertEqual(self.chooser_ids(), [shader_id for shader_id, _label in options])
        self.assertEqual(self.shell._chooser.current, selected)
        other = next(shader_id for shader_id, _label in options if shader_id != selected)
        self.pick(other)
        self.assertEqual(self.config.get_shader_for_console("SFC"), other)
        self.assertEqual(
            video.rows["shader:SFC"].value_label.get_label(), self.win.shader_catalog.label_for_shader(other)
        )
        # A stored id the short list does not know is offered anyway.
        self.config.set_shader_for_console("FC", "some_unknown_preset")
        video._build_shader_rows()
        options, selected = video._shader_options("FC")
        self.assertEqual(selected, "some_unknown_preset")
        self.assertIn("some_unknown_preset", [shader_id for shader_id, _label in options])
        self.assertEqual(
            video.rows["shader:FC"].value_label.get_label(),
            self.win.shader_catalog.label_for_shader("some_unknown_preset"),
        )

    def png(self, name="Frame.png", width=960, height=540):
        path = self.tmp / name
        pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, width, height)
        pixbuf.fill(0x204060FF)
        pixbuf.savev(str(path), "png", [], [])
        return path

    def test_bezels_per_4_3_console_with_the_picker_for_a_custom_image(self):
        page = self.open_settings("video")
        video = page.sections["video"]
        rows = video.rows
        self.assertEqual(
            {key.split(":")[1] for key in rows if key.startswith("bezel:")}, set(bezels.BEZEL_CONSOLES)
        )
        self.assertEqual(rows["bezel:MD"].value_label.get_label(), self.said("bezel.none"))
        rows["bezel:MD"].emit("clicked")
        self.pump()
        self.assertEqual(self.chooser_ids(), list(bezels.BEZEL_MODES))
        self.pick("simple")
        self.assertEqual(self.config.get_bezel_for_console("MD"), "simple")
        self.assertEqual(rows["bezel:MD"].value_label.get_label(), self.said("bezel.simple"))
        # The same mode again writes nothing.
        with mock.patch.object(self.config, "set_bezel_for_console") as store:
            video._set_bezel("MD", "simple")
        store.assert_not_called()

        dialogs = self.file_dialogs()
        # Custom with no image stored yet: the picker decides.
        video._set_bezel("MD", "custom")
        self.assertEqual(len(dialogs), 1)
        dialogs[0].open.assert_called_once()
        self.assertIs(dialogs[0].open.call_args.args[0], self.win)
        self.assertEqual(self.config.get_bezel_for_console("MD"), "simple")
        # Dismissed: the row shows what is still stored.
        video._on_bezel_image_chosen(self.dismissed(), None, "MD")
        self.assertEqual(rows["bezel:MD"].value_label.get_label(), self.said("bezel.simple"))
        # Not a PNG: refused, with the reason.
        bad = self.tmp / "bad.png"
        bad.write_text("nope")
        video._on_bezel_image_chosen(self.chosen(str(bad)), None, "MD")
        self.assertIn(self.said("toast.bezels.not_png"), self.toasts)
        self.assertEqual(self.config.get_bezel_for_console("MD"), "simple")
        # A real image: stored, selected, named on the row.
        video._on_bezel_image_chosen(self.chosen(str(self.png())), None, "MD")
        self.assertEqual(self.config.get_bezel_for_console("MD"), "custom")
        self.assertEqual(rows["bezel:MD"].value_label.get_label(), self.said("bezel.custom"))
        self.assertEqual(rows["bezel:MD"].subtitle_label.get_label(), "Frame.png")
        # Custom again while custom: a new image is what is meant.
        video._set_bezel("MD", "custom")
        self.assertEqual(len(dialogs), 2)
        # Back to none, then custom with an image on disk: no picker needed.
        video._set_bezel("MD", "none")
        self.assertEqual(self.config.get_bezel_for_console("MD"), "none")
        self.assertFalse(rows["bezel:MD"].subtitle_label.get_visible())
        video._set_bezel("MD", "custom")
        self.assertEqual(len(dialogs), 2)
        self.assertEqual(self.config.get_bezel_for_console("MD"), "custom")


@needs_display
class TheCoresSection(SettingsCase):
    def test_without_installed_cores_every_console_says_so(self):
        # The devbox may have RetroArch's own cores on disk: this test is about none.
        patcher = mock.patch.object(self.win.core_catalog, "cores_for_console", return_value=[])
        patcher.start()
        self.addCleanup(patcher.stop)
        page = self.open_settings("cores")
        cores = page.sections["cores"]
        self.assertTrue(all(cores.rows[f"core:{c}"].kind == ROW_INFO for c in SYSTEM_IDS))
        self.assertFalse(cores.options_group.get_visible())
        self.assertIs(self.focus_widget(), cores.rows["download_all"])
        with mock.patch.object(self.win, "_start_deferred_asset_download") as start:
            cores.rows["download_all"].emit("clicked")
            self.assertTrue(self.config.get_retroarch_updater_settings()["download_all_cores"])
            start.assert_called_once()
            cores.rows["download_all"].emit("clicked")
            self.assertFalse(self.config.get_retroarch_updater_settings()["download_all_cores"])
            start.assert_called_once()

    def test_a_console_with_cores_gets_a_picker_and_its_core_options(self):
        installed = [_Core("mednafen_psx_hw_libretro.so", "Beetle PSX HW"), _Core("pcsx_rearmed_libretro.so", "PCSX")]
        patcher = mock.patch.object(
            self.win.core_catalog, "cores_for_console", side_effect=lambda c: list(installed) if c == "PS" else []
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        page = self.open_settings("cores")
        cores = page.sections["cores"]
        row = cores.rows["core:PS"]
        self.assertEqual(row.value_label.get_label(), self.said("settings.cores.automatic", core="Beetle PSX HW"))
        self.assertEqual(row.subtitle_label.get_label(), self.said("settings.cores.auto_resolves", core="Beetle PSX HW"))
        # Automatic resolves to Beetle, which has options: they are offered.
        self.assertTrue(cores.options_group.get_visible())
        option_keys = [key for key in cores.rows if key.startswith("option:PS:")]
        self.assertTrue(option_keys)
        option_row = cores.rows[option_keys[0]]
        option_row.emit("clicked")
        self.pump()
        ids = self.chooser_ids()
        self.assertEqual(self.shell._chooser.current, ids[0])
        self.pick(ids[1])
        key = option_keys[0].split(":", 2)[2]
        self.assertEqual(
            self.config.core_options.get_for_console("PS", "mednafen_psx_hw_libretro.so")[key], ids[1]
        )
        self.assertEqual(cores.rows[option_keys[0]].value_label.get_label(), settings_module.core_options.value_label(ids[1]))
        # A stored value the core no longer knows falls back to the first.
        self.config.core_options.set_for_console("PS", "mednafen_psx_hw_libretro.so", key, "bogus")
        cores._build_option_rows()
        self.assertEqual(cores.rows[option_keys[0]].value_label.get_label(), settings_module.core_options.value_label(ids[0]))

        # Picking PCSX: stored, the BIOS warning asked for, and no options left.
        row.emit("clicked")
        self.pump()
        self.assertEqual(self.chooser_ids(), ["", "mednafen_psx_hw_libretro.so", "pcsx_rearmed_libretro.so"])
        self.assertEqual(self.shell._chooser.current, "")
        with mock.patch.object(self.win, "_warn_missing_bios_for_core") as warn:
            self.pick("pcsx_rearmed_libretro.so")
        warn.assert_called_once_with("PS", "pcsx_rearmed_libretro.so")
        self.assertEqual(self.config.get_console_core_override("PS"), "pcsx_rearmed_libretro.so")
        self.assertEqual(row.value_label.get_label(), "PCSX")
        self.assertFalse(cores.options_group.get_visible())
        # Back to Automatic: nothing to warn about.
        row.emit("clicked")
        self.pump()
        self.assertEqual(self.shell._chooser.current, "pcsx_rearmed_libretro.so")
        with mock.patch.object(self.win, "_warn_missing_bios_for_core") as warn:
            self.pick("")
        warn.assert_not_called()
        self.assertFalse(self.config.get_console_core_override("PS"))
        self.assertTrue(cores.options_group.get_visible())


@needs_display
class TheSystemSection(SettingsCase):
    def test_language_theme_and_the_interface_rows(self):
        page = self.open_settings("system")
        system = page.sections["system"]
        rows = system.rows
        self.assertIs(self.focus_widget(), rows["language"])
        rows["language"].emit("clicked")
        self.pump()
        self.assertEqual(self.chooser_ids(), list(settings_module.SUPPORTED_LOCALES))
        self.assertEqual(self.shell._chooser.current, "en")
        with mock.patch.object(self.win, "_apply_language_change") as apply_language:
            self.pick("en")
        apply_language.assert_not_called()
        self.assertIs(system.rows["language"], rows["language"])
        rows["language"].emit("clicked")
        self.pump()
        with mock.patch.object(self.win, "_apply_language_change") as apply_language:
            self.pick("pt_BR")
        apply_language.assert_called_once_with("pt_BR")
        # Every label is built again once the chooser has popped.
        self.assertIsNot(system.rows["language"], rows["language"])
        self.assertEqual(page.buttons["system"].get_label(), self.said("prefs.page.system"))
        self.assertIs(self.focus_widget(), system.rows["language"])
        rows = system.rows

        rows["theme"].emit("clicked")
        self.pump()
        self.assertEqual(self.chooser_ids(), list(settings_module.THEMES))
        with mock.patch.object(settings_module.theming, "apply_theme") as apply_theme, mock.patch.object(
            self.win, "_sync_theme_button"
        ) as sync_button:
            self.pick("dark")
        apply_theme.assert_called_once_with("dark")
        sync_button.assert_called_once()
        self.assertEqual(self.config.get_ui_settings()["theme"], "dark")
        self.assertEqual(rows["theme"].value_label.get_label(), self.said("theme.dark"))

        with mock.patch.object(self.win, "_apply_tips_visibility") as tips:
            rows["tips"].emit("clicked")
        self.assertFalse(self.config.get_ui_settings()["show_tips"])
        tips.assert_called_once_with(False)
        rows["gamepad_nav"].emit("clicked")
        self.assertFalse(self.config.get_ui_settings()["gamepad_navigation"])
        rows["glyphs"].emit("clicked")
        self.pump()
        self.assertEqual(self.chooser_ids(), list(settings_module.GLYPH_FAMILIES))
        self.pick("playstation")
        self.assertEqual(self.config.get_controller_glyph_family(), "playstation")
        self.assertEqual(rows["glyphs"].value_label.get_label(), self.said("controller.family.playstation"))
        rows["swap"].emit("clicked")
        self.assertTrue(self.config.get_swap_confirm_cancel())

    def test_the_big_picture_rows_apply_live(self):
        page = self.open_settings("system")
        rows = page.sections["system"].rows
        rows["bp_start"].emit("clicked")
        self.assertTrue(self.config.get_big_picture_settings()["start"])
        self.assertEqual(rows["bp_text_size"].number_label.get_label(), "100%")
        with mock.patch.object(self.shell, "apply_scale") as apply_scale:
            self.assertTrue(rows["bp_text_size"].step(1))
        apply_scale.assert_called_once()
        self.assertEqual(self.config.get_big_picture_settings()["text_size"], 110)
        self.assertEqual(rows["bp_text_size"].number_label.get_label(), "110%")
        for _ in range(6):
            rows["bp_text_size"].step(1)
        self.assertEqual(self.config.get_big_picture_settings()["text_size"], 150)
        for _ in range(9):
            rows["bp_text_size"].step(-1)
        self.assertEqual(self.config.get_big_picture_settings()["text_size"], 80)
        self.assertEqual(rows["bp_text_size"].number_label.get_label(), "80%")
        # Left and Right on the focused row, through the navigator.
        rows["bp_text_size"].grab_focus()
        self.pump()
        self.win.navigation._cmd_move("right")
        self.assertEqual(self.config.get_big_picture_settings()["text_size"], 90)

    def test_welcome_troubleshooting_and_share(self):
        page = self.open_settings("system")
        rows = page.sections["system"].rows
        rows["welcome_startup"].emit("clicked")
        self.assertFalse(self.config.get_show_welcome_on_startup())
        with mock.patch.object(self.win, "_open_welcome") as welcome:
            rows["welcome_open"].emit("clicked")
        welcome.assert_called_once()
        rows["log_panel"].emit("clicked")
        self.assertTrue(self.config.get_ui_settings()["show_log_panel"])
        self.assertTrue(self.win.log_toggle.get_active())
        rows["log_panel"].emit("clicked")
        self.assertFalse(self.config.get_ui_settings()["show_log_panel"])
        with mock.patch.object(self.win, "show_bug_report") as report:
            rows["report"].emit("clicked")
        report.assert_called_once()
        rows["device_name"].emit("clicked")
        self.pump()
        self.assertEqual(self.shell._text_entry.get_title(), self.said("prefs.share.device_name"))
        self.type_text("Couch")
        self.assertEqual(self.config.get_share_device_name(), "Couch")
        self.assertEqual(rows["device_name"].value_label.get_label(), "Couch")

    def test_saves_are_exported_and_imported_through_the_picker(self):
        page = self.open_settings("system")
        system = page.sections["system"]
        rows = system.rows
        dialogs = self.file_dialogs()
        rows["export_saves"].emit("clicked")
        dialogs[0].set_initial_name.assert_called_once_with(save_backup.default_backup_name())
        self.assertIs(dialogs[0].save.call_args.args[0], self.win)
        with mock.patch.object(settings_module.save_backup, "export_saves_async") as export:
            system._on_export_target_chosen(self.dismissed(), None)
            system._on_export_target_chosen(self.chosen(""), None)
            export.assert_not_called()
            system._on_export_target_chosen(self.chosen(str(self.tmp / "backup.zip")), None)
        self.assertEqual(export.call_args.args[0], str(self.tmp / "backup.zip"))
        export.call_args.kwargs["on_done"]({"states": 3, "saves": 4})
        self.pump()
        self.assertIn(self.said("toast.saves.exported", states=3, saves=4), self.toasts)
        self.assertEqual(system._on_export_done({"error": "disk full"}), GLib.SOURCE_REMOVE)
        self.assertIn(self.said("toast.saves.failed", error="disk full"), self.toasts)

        # Import asks first; Cancel opens no picker.
        self.ask(rows["import_saves"], "cancel")
        self.assertEqual(len(dialogs), 1)
        dialog = self.ask(rows["import_saves"])
        self.assertEqual(dialog.get_heading(), self.said("big_picture.settings.saves.import.heading"))
        self.assertEqual(len(dialogs), 2)
        self.assertIs(dialogs[1].open.call_args.args[0], self.win)
        with mock.patch.object(settings_module.save_backup, "import_saves_async") as restore:
            system._on_import_source_chosen(self.dismissed(), None)
            system._on_import_source_chosen(self.chosen(""), None)
            restore.assert_not_called()
            system._on_import_source_chosen(self.chosen(str(self.tmp / "backup.zip")), None)
        self.assertEqual(restore.call_args.args[0], str(self.tmp / "backup.zip"))
        restore.call_args.kwargs["on_done"]({"restored": 2, "skipped": 1, "errors": []})
        self.pump()
        self.assertIn(self.said("toast.saves.imported", restored=2, skipped=1), self.toasts)
        self.assertEqual(
            system._on_import_done({"restored": 0, "errors": [{"error": "corrupt"}]}), GLib.SOURCE_REMOVE
        )
        self.assertIn(self.said("toast.saves.failed", error="corrupt"), self.toasts)

    def test_retroachievements_sign_in_and_out(self):
        page = self.open_settings("system")
        system = page.sections["system"]
        store = self.config.achievements
        self.assertFalse(store.is_signed_in())
        rows = system.rows
        self.assertEqual(rows["cheevos:signin"].subtitle_label.get_label(), self.said("settings.achievements.signed_out"))
        rows["cheevos:user"].emit("clicked")
        self.pump()
        self.type_text(" player ")
        self.assertEqual(rows["cheevos:user"].value_label.get_label(), "player")
        rows["cheevos:password"].emit("clicked")
        self.pump()
        self.assertTrue(self.shell._text_entry.osk.password)
        self.type_text("hunter2")
        self.assertEqual(rows["cheevos:password"].value_label.get_label(), settings_module.PASSWORD_MASK)

        with mock.patch.object(settings_module, "Thread", _SyncThread), mock.patch.object(
            settings_module.retroachievements, "login", side_effect=retroachievements.LoginError("wrong")
        ) as login:
            rows["cheevos:signin"].emit("clicked")
            self.pump()
        login.assert_called_once_with("player", "hunter2")
        self.assertTrue(rows["cheevos:signin"].get_sensitive())
        self.assertIn(self.said("toast.achievements.failed", error="wrong"), self.toasts)
        self.assertFalse(store.is_signed_in())

        with mock.patch.object(settings_module, "Thread", _SyncThread), mock.patch.object(
            settings_module.retroachievements, "login", return_value="token"
        ):
            rows["cheevos:signin"].emit("clicked")
            self.pump()
        self.assertTrue(store.is_signed_in())
        self.assertEqual(store.get_username(), "player")
        self.assertTrue(store.get_enabled())
        self.assertIn(self.said("toast.achievements.signed_in", user="player"), self.toasts)
        rows = system.rows
        self.assertIn("cheevos:account", rows)
        self.assertNotIn("cheevos:signin", rows)
        self.assertIs(self.focus_widget(), rows["cheevos:enable"])
        rows["cheevos:enable"].emit("clicked")
        self.assertFalse(store.get_enabled())
        rows["cheevos:hardcore"].emit("clicked")
        self.assertTrue(store.get_hardcore())

        self.ask(rows["cheevos:signout"], "cancel")
        self.assertTrue(store.is_signed_in())
        self.ask(rows["cheevos:signout"])
        self.assertFalse(store.is_signed_in())
        self.assertIn(self.said("toast.achievements.signed_out"), self.toasts)
        self.assertIn("cheevos:signin", system.rows)
        self.assertIs(self.focus_widget(), system.rows["cheevos:user"])

    def test_the_initial_setup_rows(self):
        page = self.open_settings("system")
        system = page.sections["system"]
        rows = system.rows
        self.assertEqual(rows["bootstrap_status"].subtitle_label.get_label(), self.said("settings.system.bootstrap.ok"))
        with mock.patch.object(self.win, "_trigger_bootstrap_retry") as retry:
            rows["bootstrap_retry"].emit("clicked")
        retry.assert_called_once()
        self.assertTrue(rows["verify_cores"].get_visible())
        self.assertTrue(rows["verify_cores"].get_sensitive())
        self.assertEqual(
            rows["verify_cores"].subtitle_label.get_label(), self.said("settings.system.cores.verify.subtitle")
        )
        rows["verify_cores"].emit("clicked")
        self.win._start_core_repair.assert_called_with(manual=True)

        with mock.patch.object(self.config, "get_bootstrap_state", return_value={"status": "failed", "failed_step": "cores"}):
            system.build()
        self.assertEqual(
            system.rows["bootstrap_status"].subtitle_label.get_label(),
            self.said("settings.system.bootstrap.failed", step="cores"),
        )
        with mock.patch.object(self.config, "get_bootstrap_state", return_value={}):
            system.build()
        self.assertEqual(
            system.rows["bootstrap_status"].subtitle_label.get_label(), self.said("settings.system.bootstrap.pending")
        )
        self.win._core_repair_running = True
        system.build()
        self.assertFalse(system.rows["verify_cores"].get_sensitive())
        self.assertEqual(
            system.rows["verify_cores"].subtitle_label.get_label(), self.said("settings.system.cores.verify.running")
        )
        self.win._core_repair_running = False
        with mock.patch.object(settings_module, "is_running_in_flatpak", return_value=True):
            system.build()
        self.assertFalse(system.rows["verify_cores"].get_visible())


def _children(box):
    child = box.get_first_child()
    while child is not None:
        yield child
        child = child.get_next_sibling()


def _descendants(root):
    stack = [root]
    while stack:
        widget = stack.pop()
        yield widget
        children = list(_children(widget))
        stack.extend(reversed(children))


if __name__ == "__main__":
    unittest.main()
