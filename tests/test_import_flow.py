"""Getting ROMs into the library, from the first click to the artwork sync.

`ui/import_flow.py` sat at 21%: the flow is four steps -- ask which console
when there is no context for one, resolve the extensions more than one console
claims, import, then rescan and fetch the artwork the new files arrived
without -- and every one of them is a dialog or a background run, so none of
it ever executed here.

The import itself never runs: `import_roms_async` is replaced, and the summary
it would have produced is handed to the flow directly. The dialogs are caught
at `present` and answered by emitting their own response.
"""

import unittest
from unittest import mock

from tests.gtk_display import HAVE_DISPLAY, needs_display
from tests.window_harness import WindowCase

if HAVE_DISPLAY:
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Gdk, Gio, GLib, Gtk

    from openemux.ui import import_flow as import_module
    from openemux.ui.scopes import ALL_CONSOLES_ID, FAVORITES_ID


def _summary(imported=(), skipped=(), unknown=(), errors=(), extracted=()):
    return {
        "imported": list(imported),
        "skipped": list(skipped),
        "unknown": list(unknown),
        "errors": list(errors),
        "extracted": list(extracted),
    }


class _ImportCase(WindowCase):
    def setUp(self):
        super().setUp()
        self.flow = self.win.imports
        self.win.sidebar.select("SFC")
        patcher = mock.patch.object(import_module, "import_roms_async")
        self.import_async = patcher.start()
        self.addCleanup(patcher.stop)

    def run_args(self):
        return self.import_async.call_args.kwargs


@needs_display
class StartingAnImportTests(_ImportCase):
    def test_a_console_page_imports_straight_into_that_console(self):
        self.flow.begin(["/tmp/a.sfc"])
        self.assertEqual(self.run_args()["paths"], ["/tmp/a.sfc"])
        self.assertTrue(self.flow.running)

    def test_the_configured_import_mode_is_what_the_run_uses(self):
        self.flow.begin(["/tmp/a.sfc"])
        self.assertEqual(
            self.run_args()["mode"], self.config.get_import_mode()
        )

    def test_a_second_import_is_refused_rather_than_queued(self):
        # Two runs writing into the same library would race.
        self.flow.running = True
        self.flow.begin(["/tmp/a.sfc"])
        self.import_async.assert_not_called()
        self.assertEqual(self.toasts, [self.said("import.running")])

    def test_a_mixed_page_asks_which_console_to_import_into(self):
        for scope in (ALL_CONSOLES_ID, FAVORITES_ID, None):
            self.win.current_console = scope
            with mock.patch.object(self.flow, "_ask_target_console") as ask:
                self.flow.begin(["/tmp/a.sfc"])
            ask.assert_called_once()

    def test_the_console_question_defaults_to_detecting_it(self):
        self.win.current_console = ALL_CONSOLES_ID
        with self.caught_dialog() as caught:
            self.flow.begin(["/tmp/a.sfc"])
        dropdown = caught[-1].get_extra_child().get_first_child()
        self.assertEqual(
            self.win._get_console_dropdown_active_id(dropdown), ALL_CONSOLES_ID
        )

    def test_answering_the_question_with_a_console_forces_it(self):
        self.win.current_console = ALL_CONSOLES_ID
        with self.caught_dialog() as caught:
            self.flow.begin(["/tmp/a.sfc"])
        dialog = caught[-1]
        dropdown = dialog.get_extra_child().get_first_child()
        self.win._set_console_dropdown_active_id(dropdown, "FC")
        dialog.emit("response", "import")
        self.assertEqual(self.run_args()["forced_console"], "FC")

    def test_answering_it_with_detect_leaves_the_console_to_the_extension(self):
        self.win.current_console = ALL_CONSOLES_ID
        with self.caught_dialog() as caught:
            self.flow.begin(["/tmp/a.sfc"])
        caught[-1].emit("response", "import")
        self.assertIsNone(self.run_args()["forced_console"])

    def test_cancelling_the_question_imports_nothing(self):
        self.win.current_console = ALL_CONSOLES_ID
        with self.caught_dialog() as caught:
            self.flow.begin(["/tmp/a.sfc"])
        caught[-1].emit("response", "cancel")
        self.import_async.assert_not_called()


@needs_display
class ResolvingAmbiguousExtensionsTests(_ImportCase):
    def test_an_extension_only_one_console_claims_needs_no_question(self):
        with mock.patch.object(
            import_module, "collect_ambiguous_extensions", return_value={}
        ), self.caught_dialog() as caught:
            self.flow._continue(["/tmp/a.sfc"], forced_console=None)
        self.assertEqual(caught, [])
        self.assertEqual(self.run_args()["console_overrides"], {})

    def test_a_forced_console_skips_the_question_for_the_whole_batch(self):
        with mock.patch.object(
            import_module, "collect_ambiguous_extensions"
        ) as collect:
            self.flow._continue(["/tmp/a.bin"], forced_console="PS")
        collect.assert_not_called()
        self.assertEqual(self.run_args()["forced_console"], "PS")

    def test_a_shared_extension_is_asked_about_and_the_answer_carried(self):
        with mock.patch.object(
            import_module,
            "collect_ambiguous_extensions",
            return_value={".bin": ["MD", "PS"]},
        ), self.caught_dialog() as caught:
            self.flow._continue(["/tmp/a.bin"], forced_console=None)
        caught[-1].emit("response", "PS")
        self.assertEqual(self.run_args()["console_overrides"], {".bin": "PS"})

    def test_two_shared_extensions_are_asked_about_one_after_the_other(self):
        with mock.patch.object(
            import_module,
            "collect_ambiguous_extensions",
            return_value={".bin": ["MD", "PS"], ".iso": ["PS", "PS2"]},
        ), self.caught_dialog() as caught:
            self.flow._continue(["/tmp/a.bin", "/tmp/b.iso"], forced_console=None)
            caught[-1].emit("response", "PS")
            caught[-1].emit("response", "PS2")
        self.assertEqual(
            self.run_args()["console_overrides"], {".bin": "PS", ".iso": "PS2"}
        )

    def test_cancelling_the_question_abandons_the_whole_import(self):
        with mock.patch.object(
            import_module,
            "collect_ambiguous_extensions",
            return_value={".bin": ["MD", "PS"]},
        ), self.caught_dialog() as caught:
            self.flow._continue(["/tmp/a.bin"], forced_console=None)
        caught[-1].emit("response", "cancel")
        self.import_async.assert_not_called()


@needs_display
class DroppingFilesTests(_ImportCase):
    def _file_list(self, *paths):
        return Gdk.FileList.new_from_array(
            [Gio.File.new_for_path(path) for path in paths]
        )

    def _remote_file_list(self):
        """A drop from somewhere with no local path behind it."""
        value = mock.Mock()
        value.get_files.return_value = [
            Gio.File.new_for_uri("https://example.invalid/a.sfc")
        ]
        return value

    def test_the_drop_target_is_installed_on_the_widget_it_is_given(self):
        widget = Gtk.Box()
        before = widget.observe_controllers().get_n_items()
        self.flow.install_drop_target(widget)
        self.assertGreater(widget.observe_controllers().get_n_items(), before)

    def test_dragging_over_the_library_says_what_a_drop_would_do(self):
        self.assertEqual(
            self.flow._on_drop_enter(None, 0, 0), Gdk.DragAction.COPY
        )
        self.assertTrue(self.win.content_stack.has_css_class("rom-drop-active"))

    def test_dragging_away_again_takes_the_hint_back_down(self):
        self.flow._on_drop_enter(None, 0, 0)
        self.flow._on_drop_leave(None)
        self.assertFalse(self.win.content_stack.has_css_class("rom-drop-active"))

    def test_dropped_files_start_an_import(self):
        self.assertTrue(
            self.flow._on_drop(None, self._file_list("/tmp/a.sfc"), 0, 0)
        )
        self.assertEqual(self.run_args()["paths"], ["/tmp/a.sfc"])
        self.assertFalse(self.win.content_stack.has_css_class("rom-drop-active"))

    def test_a_drop_carrying_no_local_path_imports_nothing(self):
        # A drop from a remote location: the files have URIs and no path.
        self.assertFalse(self.flow._on_drop(None, self._remote_file_list(), 0, 0))
        self.import_async.assert_not_called()


@needs_display
class TheFilePickerTests(_ImportCase):
    def setUp(self):
        super().setUp()
        self.dialogs = []
        patcher = mock.patch.object(
            import_module.Gtk, "FileDialog", self._make_dialog
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _make_dialog(self):
        dialog = mock.Mock()
        self.dialogs.append(dialog)
        return dialog

    def _answer(self, *paths):
        files = Gio.ListStore.new(Gio.File)
        for path in paths:
            files.append(Gio.File.new_for_path(path))
        source = mock.Mock()
        source.open_multiple_finish.return_value = files
        self.flow._on_files_chosen(source, None)

    def test_the_picker_offers_the_importable_extensions(self):
        self.flow.open_picker()
        self.dialogs[0].set_filters.assert_called_once()
        self.dialogs[0].open_multiple.assert_called_once()

    def test_chosen_files_start_an_import(self):
        self._answer("/tmp/a.sfc", "/tmp/b.nes")
        self.assertEqual(self.run_args()["paths"], ["/tmp/a.sfc", "/tmp/b.nes"])

    def test_a_dismissed_picker_imports_nothing(self):
        source = mock.Mock()
        source.open_multiple_finish.side_effect = GLib.Error("dismissed")
        self.flow._on_files_chosen(source, None)
        self.import_async.assert_not_called()

    def test_a_picker_that_returns_nothing_imports_nothing(self):
        source = mock.Mock()
        source.open_multiple_finish.return_value = None
        self.flow._on_files_chosen(source, None)
        self.import_async.assert_not_called()

    def test_a_selection_with_no_local_paths_imports_nothing(self):
        files = Gio.ListStore.new(Gio.File)
        files.append(Gio.File.new_for_uri("https://example.invalid/a.sfc"))
        source = mock.Mock()
        source.open_multiple_finish.return_value = files
        self.flow._on_files_chosen(source, None)
        self.import_async.assert_not_called()


@needs_display
class WhenTheImportFinishesTests(_ImportCase):
    def setUp(self):
        super().setUp()
        rescan_patch = mock.patch.object(self.win, "_rescan_all_consoles")
        self.rescan = rescan_patch.start()
        self.addCleanup(rescan_patch.stop)
        sync_patch = mock.patch.object(self.win, "_start_post_import_artwork_sync")
        self.artwork_sync = sync_patch.start()
        self.addCleanup(sync_patch.stop)
        self.task_id = self.win.tasks.begin("import", "importing")

    def finish(self, summary):
        return self.flow._on_done_ui(self.task_id, summary)

    def test_a_successful_import_rescans_and_fetches_the_missing_artwork(self):
        # An import is exactly when the library gained ROMs with no artwork.
        self.assertFalse(self.finish(_summary(imported=["/roms/SFC/a.sfc"])))
        self.rescan.assert_called_once_with(show_toast=False)
        self.artwork_sync.assert_called_once_with(["/roms/SFC/a.sfc"])
        self.assertFalse(self.flow.running)
        self.assertIn(self.said("import.done", imported=1, skipped=0), self.toasts)

    def test_an_archive_that_was_unpacked_says_so_explicitly(self):
        # The user chose a .zip and got loose files.
        self.finish(_summary(imported=["/roms/SFC/a.sfc"], extracted=["a.sfc"]))
        self.assertTrue(
            any(self.said("import.extracted", count=1) in text for text in self.toasts)
        )

    def test_an_import_that_brought_nothing_in_says_which_files_failed(self):
        self.finish(_summary(unknown=["/tmp/x.bin"], errors=["/tmp/y.bin"]))
        self.assertEqual(self.toasts, [self.said("import.failed", unknown=2)])
        self.rescan.assert_not_called()

    def test_an_import_of_files_already_in_the_library_says_so(self):
        self.finish(_summary(skipped=["/roms/SFC/a.sfc"]))
        self.assertEqual(self.toasts, [self.said("import.nothing_new")])
        self.artwork_sync.assert_not_called()


@needs_display
class TheProgressBannerTests(_ImportCase):
    def test_the_run_reports_progress_through_the_banner(self):
        self.flow.begin(["/tmp/a.sfc"])
        on_progress = self.run_args()["on_progress"]
        with mock.patch.object(import_module.GLib, "idle_add") as idle_add:
            on_progress({"current": 2, "total": 5})
        self.assertEqual(idle_add.call_args[0][0], self.win.tasks.update)

    def test_the_run_reports_its_summary_back_on_the_main_thread(self):
        self.flow.begin(["/tmp/a.sfc"])
        on_done = self.run_args()["on_done"]
        with mock.patch.object(import_module.GLib, "idle_add") as idle_add:
            on_done(_summary())
        self.assertEqual(idle_add.call_args[0][0], self.flow._on_done_ui)


if __name__ == "__main__":
    unittest.main()
