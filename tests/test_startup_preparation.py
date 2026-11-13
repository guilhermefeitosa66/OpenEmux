"""Everything `main` does before the GTK stack is imported.

`main.py` sat at 40%. What was covered is the parts other tests reach on their
way past -- the bytecode redirect, the desktop-entry content. What was not is
the preparation itself: the renderer pick, the vendored typelibs a distro without the introspection
packages falls back on, and the desktop integration that has to stand down for
a packaged install.

None of it may run for real here: `prepare_process` migrates the config
directory, hijacks the root logger and replaces `sys.excepthook` for the whole
process (issue #244), and `tests/test_import_side_effects.py` exists because
that once happened merely by importing a helper. Every step is therefore
driven on its own, with the environment and the home directory redirected.
"""

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from openemux import main as main_module
from tests.platform_marks import posix_only


class _EnvironmentCase(unittest.TestCase):
    """A test that may set environment variables without leaking them."""

    def setUp(self):
        patcher = mock.patch.dict(os.environ, {}, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in ("GDK_BACKEND", "GSK_RENDERER", "GI_TYPELIB_PATH"):
            os.environ.pop(name, None)


class TheRendererPickTests(_EnvironmentCase):
    """GTK4's GL renderer can hard-crash on a mismatched host driver (issue 903).

    The AppImage tries it anyway, behind a probe file: written before GTK
    comes up, removed after the first frame, and found at the next start when
    the attempt crashed -- then, and only then, the software renderer.
    """

    def setUp(self):
        super().setUp()
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.addCleanup(setattr, main_module, "_renderer_probe", None)

    def _in_appimage(self):
        return mock.patch.object(main_module, "is_running_in_appimage", return_value=True)

    def test_the_appimage_tries_gtks_own_renderer_and_leaves_a_probe(self):
        with self._in_appimage():
            main_module._configure_gtk_renderer(self.tmp)
        self.assertNotIn("GSK_RENDERER", os.environ)
        probe = main_module.renderer_probe_path(self.tmp)
        self.assertTrue(probe.exists())
        self.assertIn(str(os.getpid()), probe.read_text(encoding="utf-8"))

    def test_a_probe_left_by_a_crashed_start_means_the_software_renderer(self):
        probe = main_module.renderer_probe_path(self.tmp)
        probe.parent.mkdir(parents=True)
        probe.write_text("pid=1\n", encoding="utf-8")
        with self._in_appimage(), self.assertLogs("openemux.main", level="WARNING") as logs:
            main_module._configure_gtk_renderer(self.tmp)
        self.assertEqual(os.environ["GSK_RENDERER"], "cairo")
        self.assertTrue(any("did not reach its first frame" in line for line in logs.output))
        self.assertIsNone(main_module._renderer_probe)

    def test_a_probe_that_cannot_be_written_means_the_software_renderer(self):
        unwritable = self.tmp / "file-not-a-dir"
        unwritable.write_text("x", encoding="utf-8")
        with self._in_appimage(), self.assertLogs("openemux.main", level="WARNING"):
            main_module._configure_gtk_renderer(unwritable)
        self.assertEqual(os.environ["GSK_RENDERER"], "cairo")

    def test_the_first_frame_drawn_removes_the_probe_and_names_the_renderer(self):
        with self._in_appimage():
            main_module._configure_gtk_renderer(self.tmp)
        window = mock.Mock()
        window.get_renderer.return_value = mock.Mock(spec=[])
        with self.assertLogs("openemux.main", level="INFO") as logs:
            self.assertTrue(main_module.clear_renderer_probe(window))
        self.assertFalse(main_module.renderer_probe_path(self.tmp).exists())
        self.assertTrue(any("gsk renderer in use: Mock" in line for line in logs.output))
        self.assertIsNone(main_module._renderer_probe)

    def test_clearing_with_no_probe_and_no_window_is_harmless(self):
        main_module._renderer_probe = None
        self.assertFalse(main_module.clear_renderer_probe())
        window = mock.Mock()
        window.get_renderer.return_value = None
        self.assertFalse(main_module.clear_renderer_probe(window))
        window.get_renderer.side_effect = RuntimeError("not realized")
        self.assertIsNone(main_module._renderer_name(window))

    def test_a_probe_that_will_not_delete_is_reported(self):
        with self._in_appimage():
            main_module._configure_gtk_renderer(self.tmp)
        with mock.patch.object(Path, "unlink", side_effect=OSError("busy")), self.assertLogs(
            "openemux.main", level="WARNING"
        ):
            self.assertFalse(main_module.clear_renderer_probe())

    def test_a_source_run_leaves_gtk_to_pick_for_itself(self):
        with mock.patch.object(
            main_module, "is_running_in_appimage", return_value=False
        ):
            main_module._configure_gtk_renderer(self.tmp)
        self.assertNotIn("GSK_RENDERER", os.environ)
        self.assertFalse(main_module.renderer_probe_path(self.tmp).exists())

    def test_a_renderer_the_user_chose_is_never_overridden(self):
        os.environ["GSK_RENDERER"] = "ngl"
        with self._in_appimage(), self.assertLogs("openemux.main", level="INFO"):
            main_module._configure_gtk_renderer(self.tmp)
        self.assertEqual(os.environ["GSK_RENDERER"], "ngl")
        self.assertFalse(main_module.renderer_probe_path(self.tmp).exists())

    def test_the_probe_lives_under_the_apps_own_config_directory(self):
        with mock.patch.object(main_module, "default_config_dir", return_value=self.tmp):
            self.assertEqual(
                main_module.renderer_probe_path(),
                self.tmp / "runtime" / main_module.RENDERER_PROBE_NAME,
            )


class TheVendoredTypelibsTests(_EnvironmentCase):
    """A distro that ships the GTK libraries but not the typelibs."""

    def setUp(self):
        super().setUp()
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.vendored = (
            self.tmp / "AppDir" / "usr" / "lib" / "x86_64-linux-gnu" / "girepository-1.0"
        )

    def _vendor(self):
        self.vendored.mkdir(parents=True, exist_ok=True)
        (self.vendored / "Gtk-4.0.typelib").write_bytes(b"")
        (self.vendored / "Adw-1.typelib").write_bytes(b"")

    def _system_probe(self, has_them):
        """Answer only the three ``/usr`` probes, and leave the rest alone.

        `os.path.exists` cannot be blanket-patched here: from Python 3.13 on
        `Path.exists` is itself implemented on top of it, so a `lambda: False`
        also hides the vendored typelibs the test just wrote.
        """
        real = os.path.exists

        def _exists(path):
            return has_them if str(path).startswith("/usr/lib") else real(path)

        return mock.patch.object(main_module.os.path, "exists", _exists)

    def _ensure(self, system_has_them=False, project_root=None):
        with mock.patch.object(main_module, "IS_WINDOWS", False), mock.patch.object(
            main_module, "is_running_in_appimage", return_value=False
        ), self._system_probe(system_has_them), mock.patch.object(
            main_module,
            "get_project_root",
            lambda: project_root if project_root is not None else self.tmp,
        ):
            main_module._ensure_gtk_typelibs()

    def test_a_system_that_ships_the_typelibs_needs_no_fallback(self):
        self._vendor()
        self._ensure(system_has_them=True)
        self.assertNotIn("GI_TYPELIB_PATH", os.environ)

    def test_a_system_without_them_falls_back_to_the_vendored_pair(self):
        self._vendor()
        with mock.patch.object(main_module, "IS_WINDOWS", False), mock.patch.object(
            main_module, "is_running_in_appimage", return_value=False
        ), self._system_probe(False), mock.patch.object(
            main_module, "get_project_root", lambda: self.tmp
        ):
            main_module._ensure_gtk_typelibs()
        self.assertEqual(os.environ["GI_TYPELIB_PATH"], str(self.vendored))

    def test_an_existing_search_path_is_kept_behind_the_vendored_one(self):
        self._vendor()
        os.environ["GI_TYPELIB_PATH"] = "/somewhere/else"
        with mock.patch.object(main_module, "IS_WINDOWS", False), mock.patch.object(
            main_module, "is_running_in_appimage", return_value=False
        ), self._system_probe(False), mock.patch.object(
            main_module, "get_project_root", lambda: self.tmp
        ):
            main_module._ensure_gtk_typelibs()
        self.assertEqual(
            os.environ["GI_TYPELIB_PATH"],
            os.pathsep.join([str(self.vendored), "/somewhere/else"]),
        )

    def test_a_tree_with_no_vendored_typelibs_changes_nothing(self):
        with mock.patch.object(main_module, "IS_WINDOWS", False), mock.patch.object(
            main_module, "is_running_in_appimage", return_value=False
        ), self._system_probe(False), mock.patch.object(
            main_module, "get_project_root", lambda: self.tmp
        ):
            main_module._ensure_gtk_typelibs()
        self.assertNotIn("GI_TYPELIB_PATH", os.environ)

    def test_a_project_root_that_cannot_be_resolved_changes_nothing(self):
        with mock.patch.object(main_module, "IS_WINDOWS", False), mock.patch.object(
            main_module, "is_running_in_appimage", return_value=False
        ), self._system_probe(False), mock.patch.object(
            main_module, "get_project_root", side_effect=RuntimeError("no root")
        ):
            main_module._ensure_gtk_typelibs()
        self.assertNotIn("GI_TYPELIB_PATH", os.environ)

    def test_the_appimage_carries_its_own_and_needs_no_fallback(self):
        with mock.patch.object(main_module, "IS_WINDOWS", False), mock.patch.object(
            main_module, "is_running_in_appimage", return_value=True
        ):
            main_module._ensure_gtk_typelibs()
        self.assertNotIn("GI_TYPELIB_PATH", os.environ)

    def test_windows_keeps_its_typelibs_inside_the_msys2_prefix(self):
        with mock.patch.object(main_module, "IS_WINDOWS", True):
            main_module._ensure_gtk_typelibs()
        self.assertNotIn("GI_TYPELIB_PATH", os.environ)


class ThePixbufLoaderCacheTests(unittest.TestCase):
    """Windows only: gdk-pixbuf reads its module file once, at init."""

    def test_linux_needs_no_loader_cache(self):
        with mock.patch.object(main_module, "IS_WINDOWS", False):
            main_module._ensure_pixbuf_loaders()

    def test_windows_builds_the_cache_before_anything_decodes_an_image(self):
        with mock.patch.object(main_module, "IS_WINDOWS", True), mock.patch(
            "openemux.core.pixbuf_loaders.ensure_loaders_cache"
        ) as ensure:
            main_module._ensure_pixbuf_loaders()
        ensure.assert_called_once()

    def test_a_cache_that_cannot_be_built_does_not_stop_start_up(self):
        # A blank cover is better than an app that will not start.
        with mock.patch.object(main_module, "IS_WINDOWS", True), mock.patch(
            "openemux.core.pixbuf_loaders.ensure_loaders_cache",
            side_effect=OSError("read-only"),
        ):
            main_module._ensure_pixbuf_loaders()


class TheWindowsAppIdTests(unittest.TestCase):
    """Issue #509: the packaged process tells the shell it is OpenEmux."""

    def test_linux_never_reaches_the_shell(self):
        with mock.patch.object(main_module, "IS_WINDOWS", False), mock.patch(
            "openemux.core.win32_shell.set_process_app_id"
        ) as declare:
            main_module._declare_windows_app_id()
        declare.assert_not_called()

    def test_the_packaged_bundle_declares_the_app_id(self):
        with mock.patch.object(main_module, "IS_WINDOWS", True), mock.patch(
            "openemux.core.win32_shell.launcher_path", return_value=Path("OpenEmux.exe")
        ), mock.patch("openemux.core.win32_shell.set_process_app_id") as declare:
            main_module._declare_windows_app_id()
        declare.assert_called_once_with(main_module.APP_ID)

    def test_a_windows_source_run_has_nothing_to_declare(self):
        # No launcher means nothing a pinned button could start.
        with mock.patch.object(main_module, "IS_WINDOWS", True), mock.patch(
            "openemux.core.win32_shell.launcher_path", return_value=None
        ), mock.patch("openemux.core.win32_shell.set_process_app_id") as declare:
            main_module._declare_windows_app_id()
        declare.assert_not_called()


class ThePreparationRunsOnceTests(unittest.TestCase):
    """Issue #244: it used to be five bare calls at module level."""

    def setUp(self):
        self.calls = []
        for name in (
            "apply_portable_environment",
            "_apply_pending_portable_import",
            "_redirect_bytecode_cache",
            "_configure_gtk_renderer",
            "migrate_legacy_config_dir",
            "configure_startup_logging",
            "_declare_windows_app_id",
            "_ensure_gtk_typelibs",
            "_ensure_pixbuf_loaders",
        ):
            patcher = mock.patch.object(
                main_module, name, lambda n=name: self.calls.append(n)
            )
            patcher.start()
            self.addCleanup(patcher.stop)
        prepared = mock.patch.object(main_module, "_prepared", False)
        prepared.start()
        self.addCleanup(prepared.stop)

    def test_every_step_runs_in_the_order_the_next_one_depends_on(self):
        main_module.prepare_process()
        self.assertEqual(
            self.calls,
            [
                "apply_portable_environment",
                "_redirect_bytecode_cache",
                "_apply_pending_portable_import",
                "migrate_legacy_config_dir",
                "configure_startup_logging",
                # After the migration and the log: the renderer probe lives in
                # the config dir and the pick goes on record (issue 903).
                "_configure_gtk_renderer",
                "_declare_windows_app_id",
                "_ensure_gtk_typelibs",
                "_ensure_pixbuf_loaders",
            ],
        )

    def test_a_second_call_does_nothing(self):
        # configure_startup_logging uses force=True, so a second call would
        # swap the root handlers out from under the running app.
        main_module.prepare_process()
        main_module.prepare_process()
        self.assertEqual(len(self.calls), 9)

    def test_an_import_swapped_in_at_start_up_is_logged(self):
        with mock.patch.object(
            main_module, "_apply_pending_portable_import", return_value="applied"
        ), self.assertLogs(level="INFO") as logs:
            main_module.prepare_process()
        self.assertIn("portable import at start-up: applied", "\n".join(logs.output))

    def test_the_application_is_built_only_after_the_preparation(self):
        # Importing gi.repository.Gtk runs Gtk.init(), which opens the
        # display, so GDK_BACKEND has to be set before that import.
        application = object()
        with mock.patch.object(
            main_module, "prepare_process", lambda: self.calls.append("prepare")
        ), mock.patch.dict(
            "sys.modules",
            {"openemux.app": mock.Mock(OpenEmuxApplication=lambda: application)},
        ):
            self.assertIs(main_module.build_application(), application)
        self.assertEqual(self.calls, ["prepare"])


class ThePendingPortableImportTests(unittest.TestCase):
    """Issue #768: a staged import is swapped in before anything opens the folder."""

    def apply(self, **behaviour):
        with mock.patch.object(main_module, "portable_root", return_value=Path("/p")), \
                mock.patch(
                    "openemux.core.portable_import.apply_pending_import", **behaviour
                ) as apply:
            return main_module._apply_pending_portable_import(), apply

    def test_the_result_is_passed_on(self):
        self.assertEqual(self.apply(return_value="applied")[0], "applied")

    def test_off_a_portable_install_nothing_is_even_imported(self):
        with mock.patch.object(main_module, "portable_root", return_value=None), \
                mock.patch("openemux.core.portable_import.apply_pending_import") as apply:
            self.assertIsNone(main_module._apply_pending_portable_import())
        apply.assert_not_called()

    def test_a_failure_is_written_to_the_start_up_log_and_is_not_fatal(self):
        with mock.patch.object(main_module, "append_startup_error") as record:
            result, _apply = self.apply(side_effect=RuntimeError("boom"))
        self.assertEqual(result, "error")
        record.assert_called_once()
        self.assertIn("boom", record.call_args.kwargs["exc_text"])


@posix_only("freedesktop .desktop entries and ~/.local/share")
class DesktopIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        home_patch = mock.patch.object(
            main_module.Path, "home", classmethod(lambda _cls: self.home)
        )
        home_patch.start()
        self.addCleanup(home_patch.stop)
        self.project = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.project, ignore_errors=True)
        self.logo = (
            self.project / "src" / "openemux" / "ui" / "assets" / "images" / "logo.png"
        )
        self.logo.parent.mkdir(parents=True, exist_ok=True)
        self.logo.write_bytes(b"\x89PNG\r\n\x1a\n")
        root_patch = mock.patch.object(
            main_module, "get_project_root", lambda: self.project
        )
        root_patch.start()
        self.addCleanup(root_patch.stop)
        for name, value in (
            ("is_running_in_appimage", False),
            ("is_running_in_flatpak", False),
        ):
            patcher = mock.patch.object(main_module, name, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        packaged = mock.patch.object(
            main_module, "_is_packaged_install", return_value=False
        )
        packaged.start()
        self.addCleanup(packaged.stop)

    def entry(self):
        return (
            self.home
            / ".local"
            / "share"
            / "applications"
            / f"{main_module.APP_ID}.desktop"
        )

    def icon(self):
        return (
            self.home
            / ".local"
            / "share"
            / "icons"
            / "hicolor"
            / "512x512"
            / "apps"
            / f"{main_module.APP_ID}.png"
        )

    def test_a_source_run_writes_its_own_entry_and_icon(self):
        main_module._ensure_desktop_integration()
        self.assertTrue(self.entry().is_file())
        self.assertTrue(self.icon().is_file())
        self.assertIn("Name=OpenEmux", self.entry().read_text(encoding="utf-8"))

    def test_an_unchanged_entry_is_not_rewritten(self):
        main_module._ensure_desktop_integration()
        before = self.entry().stat().st_mtime_ns
        main_module._ensure_desktop_integration()
        self.assertEqual(self.entry().stat().st_mtime_ns, before)

    def test_a_tree_with_no_logo_writes_nothing(self):
        self.logo.unlink()
        main_module._ensure_desktop_integration()
        self.assertFalse(self.entry().exists())

    def test_a_packaged_install_owns_its_own_entry(self):
        # Writing a user-level copy would shadow the package's entry with one
        # pointing at this interpreter.
        main_module._ensure_desktop_integration()
        with mock.patch.object(
            main_module, "_is_packaged_install", return_value=True
        ):
            main_module._ensure_desktop_integration()
        self.assertFalse(self.entry().exists())

    def test_the_appimage_and_the_flatpak_do_the_same(self):
        for name in ("is_running_in_appimage", "is_running_in_flatpak"):
            main_module._ensure_desktop_integration()
            with mock.patch.object(main_module, name, return_value=True):
                main_module._ensure_desktop_integration()
            self.assertFalse(self.entry().exists(), name)

    def test_a_hand_written_entry_is_never_removed(self):
        target = self.entry()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("[Desktop Entry]\nName=Something else\n", encoding="utf-8")
        main_module._remove_generated_desktop_entry()
        self.assertTrue(target.exists())

    def test_no_entry_at_all_is_nothing_to_remove(self):
        main_module._remove_generated_desktop_entry()

    def test_an_entry_that_cannot_be_read_is_left_alone(self):
        target = self.entry()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("[Desktop Entry]\n", encoding="utf-8")
        with mock.patch.object(
            main_module.Path, "read_text", side_effect=OSError("gone")
        ):
            main_module._remove_generated_desktop_entry()
        self.assertTrue(target.exists())

    def test_windows_writes_no_desktop_entry_at_all(self):
        with mock.patch.object(main_module, "IS_WINDOWS", True):
            main_module._ensure_desktop_integration()
        self.assertFalse(self.entry().exists())


class TheEntryPointTests(unittest.TestCase):
    def test_it_names_the_program_before_anything_reads_it(self):
        # The WM_CLASS of the first window is read from it.
        application = mock.Mock()
        application.run.return_value = 0
        glib = mock.Mock()
        with mock.patch.object(main_module, "prepare_process"), mock.patch.object(
            main_module, "_ensure_desktop_integration"
        ), mock.patch.object(
            main_module, "build_application", return_value=application
        ), mock.patch.dict("sys.modules", {"gi.repository": glib}):
            self.assertEqual(main_module.main(), 0)
        glib.GLib.set_prgname.assert_called_once_with(main_module.APP_ID)

    def test_a_start_up_that_dies_is_written_to_the_start_up_log(self):
        # Nothing else is up yet to report it: no window, no toast overlay.
        with mock.patch.object(
            main_module, "prepare_process", side_effect=RuntimeError("boom")
        ), mock.patch.object(main_module, "append_startup_error") as record:
            with self.assertRaises(RuntimeError):
                main_module.main()
        record.assert_called_once()


if __name__ == "__main__":
    unittest.main()
