"""Everything `main` does before the GTK stack is imported.

`main.py` sat at 40%. What was covered is the parts other tests reach on their
way past -- the bytecode redirect, the desktop-entry content. What was not is
the preparation itself: the renderer pick, the X11 backend the embedded game
window needs, the vendored typelibs a distro without the introspection
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
    """GTK4's GL renderer can hard-crash on a mismatched host driver."""

    def test_the_appimage_falls_back_to_the_software_renderer(self):
        with mock.patch.object(
            main_module, "is_running_in_appimage", return_value=True
        ):
            main_module._configure_gtk_renderer()
        self.assertEqual(os.environ["GSK_RENDERER"], "cairo")

    def test_a_source_run_leaves_gtk_to_pick_for_itself(self):
        with mock.patch.object(
            main_module, "is_running_in_appimage", return_value=False
        ):
            main_module._configure_gtk_renderer()
        self.assertNotIn("GSK_RENDERER", os.environ)

    def test_a_renderer_the_user_chose_is_never_overridden(self):
        os.environ["GSK_RENDERER"] = "ngl"
        with mock.patch.object(
            main_module, "is_running_in_appimage", return_value=True
        ):
            main_module._configure_gtk_renderer()
        self.assertEqual(os.environ["GSK_RENDERER"], "ngl")


class TheGameWindowBackendTests(_EnvironmentCase):
    """Issue #199: the embed is X11 reparenting between two X clients."""

    def _configure(self, embeddable=True, setting=True, windows=False):
        with mock.patch.object(main_module, "IS_WINDOWS", windows), mock.patch(
            "openemux.core.game_window_support.embedding_possible",
            return_value=embeddable,
        ), mock.patch(
            "openemux.core.config.read_game_window_setting", return_value=setting
        ):
            main_module._configure_game_window_backend()

    def test_a_session_that_can_embed_is_put_on_x11(self):
        self._configure()
        self.assertEqual(os.environ["GDK_BACKEND"], "x11")

    def test_a_backend_the_user_chose_is_never_overridden(self):
        os.environ["GDK_BACKEND"] = "wayland"
        self._configure()
        self.assertEqual(os.environ["GDK_BACKEND"], "wayland")

    def test_a_session_that_cannot_embed_is_left_to_gtk(self):
        # Forcing x11 there would leave GTK with no display at all.
        self._configure(embeddable=False)
        self.assertNotIn("GDK_BACKEND", os.environ)

    def test_a_user_who_turned_the_game_window_off_is_left_to_gtk(self):
        self._configure(setting=False)
        self.assertNotIn("GDK_BACKEND", os.environ)

    def test_windows_has_no_x_server_to_be_put_on(self):
        self._configure(windows=True)
        self.assertNotIn("GDK_BACKEND", os.environ)


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


class ThePreparationRunsOnceTests(unittest.TestCase):
    """Issue #244: it used to be five bare calls at module level."""

    def setUp(self):
        self.calls = []
        for name in (
            "_redirect_bytecode_cache",
            "_configure_gtk_renderer",
            "migrate_legacy_config_dir",
            "_configure_game_window_backend",
            "configure_startup_logging",
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
                "_redirect_bytecode_cache",
                "_configure_gtk_renderer",
                "migrate_legacy_config_dir",
                "_configure_game_window_backend",
                "configure_startup_logging",
                "_ensure_gtk_typelibs",
                "_ensure_pixbuf_loaders",
            ],
        )

    def test_a_second_call_does_nothing(self):
        # configure_startup_logging uses force=True, so a second call would
        # swap the root handlers out from under the running app.
        main_module.prepare_process()
        main_module.prepare_process()
        self.assertEqual(len(self.calls), 7)

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
