"""The dialogs that import a profile into a portable folder (issue #768).

The copy itself is ``test_portable_import``'s; here the questions, the
progress and the messages, built for real and answered by emitting the
response a click would.
"""

import unittest
from pathlib import Path
from unittest import mock

from tests.gtk_display import HAVE_DISPLAY, needs_display

if HAVE_DISPLAY:
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, GLib, Gtk

    Adw.init()

    from openemux.core.portable_import import PortableImportError
    from openemux.ui import portable_import_dialog as dialogs


def _pump():
    context = GLib.MainContext.default()
    while context.iteration(False):
        pass


class _FakeWindow(Gtk.Window if HAVE_DISPLAY else object):
    """What the first-start offer touches of the first-boot window."""

    def __init__(self):
        super().__init__()
        self.progress = Gtk.ProgressBar()
        self.subtitle_label = Gtk.Label()


@needs_display
class BuildingTheQuestionTests(unittest.TestCase):
    def test_the_first_start_offer_without_a_rom_folder(self):
        dialog, check = dialogs.build_import_dialog("en", Path("/h/.openemux"), None, 0)
        self.assertIsNone(check)
        self.assertEqual(dialog.get_heading(), "Bring your existing data?")
        self.assertIn("/h/.openemux", dialog.get_body())
        self.assertTrue(dialog.has_response("fresh"))
        self.assertEqual(dialog.get_close_response(), "fresh")
        self.assertEqual(dialog.get_default_response(), "copy")
        self.assertEqual(
            dialog.get_response_appearance("copy"), Adw.ResponseAppearance.SUGGESTED
        )

    def test_the_rom_folder_check_shows_its_size_and_starts_unticked(self):
        dialog, check = dialogs.build_import_dialog("en", Path("/h/.openemux"), Path("/h/r"), 2048)
        self.assertIs(dialog.get_extra_child(), check)
        self.assertFalse(check.get_active())
        self.assertIn(GLib.format_size(2048), check.get_label())

    def test_the_preferences_wording_replaces_and_defaults_to_cancel(self):
        dialog, _check = dialogs.build_import_dialog(
            "en", Path("/h/.openemux"), None, 0, replace=True
        )
        self.assertEqual(dialog.get_heading(), "Replace this portable copy's data?")
        self.assertEqual(dialog.get_close_response(), "cancel")
        self.assertEqual(
            dialog.get_response_appearance("import"), Adw.ResponseAppearance.DESTRUCTIVE
        )

    def test_the_error_says_how_much_space_is_missing(self):
        text = dialogs.error_message(
            "en", PortableImportError("no_space", needed=4096, free=1024)
        )
        self.assertIn(GLib.format_size(4096), text)
        self.assertIn(GLib.format_size(1024), text)
        self.assertEqual(
            dialogs.error_message("en", OSError("denied")), "The copy stopped: denied"
        )


@needs_display
class RunningTheCopyTests(unittest.TestCase):
    def run_import(self, plan=object(), run=None):
        seen = {"progress": [], "done": 0, "error": None}
        with mock.patch.object(dialogs.portable_import, "plan_import", return_value=plan), \
                mock.patch.object(dialogs.portable_import, "run_import", run or (lambda p, cb: None)):
            thread = dialogs.start_import(
                False,
                seen["progress"].append,
                lambda: seen.__setitem__("done", seen["done"] + 1),
                lambda exc: seen.__setitem__("error", exc),
            )
            thread.join(5)
        _pump()
        return seen

    def test_progress_comes_once_per_percent(self):
        def run(_plan, progress):
            for copied in (0, 1, 1, 50, 100):
                progress(copied, 100)
            progress(0, 0)

        seen = self.run_import(run=run)
        self.assertEqual(seen["progress"], [0.0, 0.01, 0.5, 1.0])
        self.assertEqual(seen["done"], 1)
        self.assertIsNone(seen["error"])

    def test_the_callbacks_arrive_while_a_redraw_is_always_pending(self):
        # A spinning spinner keeps a redraw ready above the idle priority: a
        # plain idle_add would never run, and the row stayed at 0%.
        redraw = GLib.idle_add(lambda: True, priority=GLib.PRIORITY_HIGH_IDLE + 20)
        self.addCleanup(GLib.source_remove, redraw)
        seen = {"progress": [], "done": 0}

        def run(_plan, progress):
            progress(100, 100)

        with mock.patch.object(dialogs.portable_import, "plan_import", return_value=object()), \
                mock.patch.object(dialogs.portable_import, "run_import", run):
            thread = dialogs.start_import(
                False,
                seen["progress"].append,
                lambda: seen.__setitem__("done", seen["done"] + 1),
                print,
            )
            thread.join(5)
        context = GLib.MainContext.default()
        for _ in range(50):
            context.iteration(False)
        self.assertEqual(seen["progress"], [1.0])
        self.assertEqual(seen["done"], 1)

    def test_a_second_copy_is_refused_while_one_runs(self):
        dialogs._RUNNING.set()
        self.addCleanup(dialogs._RUNNING.clear)
        self.assertTrue(dialogs.import_running())
        self.assertIsNone(dialogs.start_import(False, print, print, print))

    def test_the_guard_is_released_after_a_copy_either_way(self):
        self.run_import()
        self.assertFalse(dialogs.import_running())
        self.run_import(plan=None)
        self.assertFalse(dialogs.import_running())

    def test_nothing_left_to_import_is_an_error(self):
        seen = self.run_import(plan=None)
        self.assertEqual(seen["done"], 0)
        self.assertEqual(seen["error"].reason, "failed")

    def test_a_failed_copy_reaches_the_error_callback(self):
        def run(_plan, _progress):
            raise PortableImportError("no_space", needed=2, free=1)

        seen = self.run_import(run=run)
        self.assertEqual(seen["error"].reason, "no_space")


@needs_display
class TheFirstStartOfferTests(unittest.TestCase):
    def setUp(self):
        for name, value in (
            ("importable_profile", Path("/h/.openemux")),
            ("profile_roms_folder", Path("/h/games/roms")),
            ("folder_size", 10),
        ):
            patcher = mock.patch.object(dialogs.portable_import, name, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        starter = mock.patch.object(dialogs, "start_import")
        self.start_import = starter.start()
        self.addCleanup(starter.stop)
        self.window = _FakeWindow()
        self.addCleanup(self.window.destroy)
        self.outcomes = []
        self.dialog = dialogs.run_first_start_offer(self.window, "en", self.outcomes.append)

    def test_start_fresh_is_a_decline(self):
        self.dialog.emit("response", "fresh")
        self.assertEqual(self.outcomes, ["declined"])
        self.start_import.assert_not_called()

    def test_copy_shows_the_progress_and_finishes_as_imported(self):
        self.dialog.get_extra_child().set_active(True)
        self.dialog.emit("response", "copy")
        include, on_progress, on_done, _on_error = self.start_import.call_args.args
        self.assertTrue(include)
        self.assertEqual(self.window.subtitle_label.get_text(), "Copying your data…")
        on_progress(0.42)
        self.assertEqual(self.window.progress.get_text(), "42%")
        on_done()
        self.assertEqual(self.outcomes, ["imported"])

    def test_a_failure_is_shown_and_continue_goes_on(self):
        self.dialog.emit("response", "copy")
        on_error = self.start_import.call_args.args[3]
        shown = []
        with mock.patch.object(Adw.AlertDialog, "present", lambda d, _w: shown.append(d)):
            on_error(OSError("denied"))
        self.assertEqual(shown[0].get_heading(), "Could not copy your data")
        self.assertIn("denied", shown[0].get_body())
        shown[0].emit("response", "continue")
        self.assertEqual(self.outcomes, ["failed"])

    def test_without_a_rom_folder_there_is_no_check(self):
        with mock.patch.object(dialogs.portable_import, "profile_roms_folder", return_value=None):
            dialog = dialogs.run_first_start_offer(self.window, "en", self.outcomes.append)
        self.assertIsNone(dialog.get_extra_child())
        dialog.emit("response", "copy")
        self.assertFalse(self.start_import.call_args.args[0])


@needs_display
class ThePreferencesGroupTests(unittest.TestCase):
    def setUp(self):
        self.toasts = []
        self.source = mock.patch.object(
            dialogs.portable_import, "importable_profile", return_value=Path("/h/.openemux")
        )
        self.importable = self.source.start()
        self.addCleanup(self.source.stop)
        for name, value in (("profile_roms_folder", None), ("folder_size", 0)):
            patcher = mock.patch.object(dialogs.portable_import, name, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(dialogs, "profile_config_dir", return_value=Path("/h/.openemux"))
        patcher.start()
        self.addCleanup(patcher.stop)
        starter = mock.patch.object(dialogs, "start_import")
        self.start_import = starter.start()
        self.addCleanup(starter.stop)
        self.group = dialogs.PortableImportGroup(
            "en", lambda text, timeout=3: self.toasts.append((text, timeout))
        )

    def test_there_is_no_group_off_a_portable_install(self):
        with mock.patch.object(dialogs, "portable_root", return_value=None):
            self.assertIsNone(dialogs.PortableImportGroup.build("en", print))
        with mock.patch.object(dialogs, "portable_root", return_value=Path("/p")):
            self.assertIsInstance(
                dialogs.PortableImportGroup.build("en", print), dialogs.PortableImportGroup
            )

    def test_the_row_names_the_profile_and_is_off_without_one(self):
        self.assertTrue(self.group.row.get_sensitive())
        self.assertIn("/h/.openemux", self.group.row.get_subtitle())
        self.importable.return_value = None
        self.group.refresh()
        self.assertFalse(self.group.row.get_sensitive())
        self.assertEqual(self.group.row.get_subtitle(), "No data found in /h/.openemux.")

    def test_a_profile_gone_since_the_page_opened_only_refreshes(self):
        self.importable.return_value = None
        self.group._on_clicked(self.group.button)
        self.assertIsNone(self.group._dialog)
        self.assertFalse(self.group.row.get_sensitive())

    def open_dialog(self):
        with mock.patch.object(Adw.AlertDialog, "present"):
            self.group._on_clicked(self.group.button)
        return self.group._dialog

    def test_a_copy_from_an_earlier_window_keeps_the_row_off(self):
        dialogs._RUNNING.set()
        self.addCleanup(dialogs._RUNNING.clear)
        self.group.refresh()
        self.assertFalse(self.group.row.get_sensitive())
        self.group._on_clicked(self.group.button)
        self.assertIsNone(self.group._dialog)

    def test_a_copy_started_while_the_question_was_open_wins(self):
        dialog = self.open_dialog()
        dialogs._RUNNING.set()
        self.addCleanup(dialogs._RUNNING.clear)
        dialog.emit("response", "import")
        self.start_import.assert_not_called()

    def test_cancel_changes_nothing(self):
        self.open_dialog().emit("response", "cancel")
        self.start_import.assert_not_called()

    def test_import_runs_with_a_spinner_and_ends_with_the_restart_toast(self):
        with mock.patch.object(dialogs.portable_import, "profile_roms_folder", return_value=Path("/r")):
            dialog = self.open_dialog()
        dialog.emit("response", "import")
        self.assertFalse(self.start_import.call_args.args[0])
        self.assertTrue(self.group.spinner.get_visible())
        self.assertFalse(self.group.button.get_visible())
        self.assertEqual(self.group.row.get_subtitle(), "Copying… 0%")
        self.group._on_progress(0.5)
        self.assertEqual(self.group.row.get_subtitle(), "Copying… 50%")
        self.group._on_done()
        self.assertTrue(self.group.button.get_visible())
        self.assertEqual(self.toasts, [("Import ready. Restart OpenEmux to finish.", 0)])

    def test_import_without_a_rom_folder_and_a_failure_toast(self):
        self.open_dialog().emit("response", "import")
        self.assertFalse(self.start_import.call_args.args[0])
        self.group._on_error(OSError("denied"))
        self.assertFalse(self.group.spinner.get_visible())
        self.assertEqual(self.toasts, [("Import failed. The copy stopped: denied", 0)])


if __name__ == "__main__":
    unittest.main()
