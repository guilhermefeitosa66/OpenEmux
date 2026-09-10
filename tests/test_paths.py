import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from openemux.core import paths
from openemux.core.paths import (
    get_project_root,
    is_running_in_appimage,
    resolve_project_path,
)


class PathsTests(unittest.TestCase):
    def test_get_project_root_prefers_environment_override(self):
        with TemporaryDirectory() as tmp_dir:
            with patch.dict(os.environ, {"OPENEMUX_PROJECT_ROOT": tmp_dir}, clear=False):
                self.assertEqual(get_project_root(), Path(tmp_dir).resolve())

    def test_is_running_in_appimage_checks_standard_vars(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(is_running_in_appimage())
        with patch.dict(os.environ, {"APPDIR": "/tmp/AppDir"}, clear=True):
            self.assertTrue(is_running_in_appimage())

    def test_resolve_project_path_uses_project_root_for_relative_values(self):
        with TemporaryDirectory() as tmp_dir:
            with patch.dict(os.environ, {"OPENEMUX_PROJECT_ROOT": tmp_dir}, clear=False):
                resolved = resolve_project_path(
                    "vendors/RetroArch-Linux-x86_64/usr/bin/retroarch"
                )
        self.assertEqual(
            resolved,
            (
                Path(tmp_dir)
                / "vendors"
                / "RetroArch-Linux-x86_64"
                / "usr"
                / "bin"
                / "retroarch"
            ).resolve(),
        )

    def test_get_project_root_uses_appdir_layout_when_available(self):
        with TemporaryDirectory() as tmp_dir:
            bundled_root = Path(tmp_dir) / "usr" / "lib" / "openemux"
            bundled_root.mkdir(parents=True, exist_ok=True)
            with patch.dict(os.environ, {"APPDIR": tmp_dir}, clear=True):
                self.assertEqual(get_project_root(), bundled_root.resolve())


if __name__ == "__main__":
    unittest.main()


class TheBytecodeCacheDirectoryTests(unittest.TestCase):
    """Derived data: rebuilt when missing, correct to delete, worthless to back up."""

    def test_it_follows_the_xdg_cache_home_when_one_is_set(self):
        with patch.object(paths, "IS_WINDOWS", False):
            with patch.dict(os.environ, {"XDG_CACHE_HOME": "/tmp/cache"}, clear=False):
                self.assertEqual(
                    paths.bytecode_cache_dir(),
                    Path("/tmp/cache/openemux/bytecode"),
                )

    def test_without_one_it_falls_back_to_the_conventional_place(self):
        environment = {k: v for k, v in os.environ.items() if k != "XDG_CACHE_HOME"}
        with patch.object(paths, "IS_WINDOWS", False):
            with patch.dict(os.environ, environment, clear=True):
                with patch.object(Path, "home", classmethod(lambda _cls: Path("/home/x"))):
                    self.assertEqual(
                        paths.bytecode_cache_dir(),
                        Path("/home/x/.cache/openemux/bytecode"),
                    )

    def test_on_windows_it_follows_localappdata(self):
        with patch.object(paths, "IS_WINDOWS", True):
            with patch.dict(os.environ, {"LOCALAPPDATA": r"C:\cache"}, clear=False):
                self.assertEqual(
                    paths.bytecode_cache_dir().parts[-2:], ("openemux", "bytecode")
                )

    def test_on_windows_without_it_the_conventional_place_is_used(self):
        environment = {k: v for k, v in os.environ.items() if k != "LOCALAPPDATA"}
        with patch.object(paths, "IS_WINDOWS", True):
            with patch.dict(os.environ, environment, clear=True):
                with patch.object(Path, "home", classmethod(lambda _cls: Path("/home/x"))):
                    self.assertEqual(
                        paths.bytecode_cache_dir(),
                        Path("/home/x/AppData/Local/openemux/bytecode"),
                    )


class TheLegacyConfigDirMigrationTests(unittest.TestCase):
    """An install that predates the OpenEmux rename keeps everything it had."""

    def setUp(self):
        self.tmp = Path(TemporaryDirectory().name)
        self._dir = TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.home = Path(self._dir.name)
        patcher = patch.object(Path, "home", classmethod(lambda _cls: self.home))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.legacy = self.home / paths.LEGACY_CONFIG_DIR_NAME
        self.current = self.home / paths.CONFIG_DIR_NAME

    def test_a_legacy_directory_is_moved_across(self):
        (self.legacy / "playlists").mkdir(parents=True)
        (self.legacy / "config.yaml").write_text("roms_path: /roms\n", encoding="utf-8")
        paths.migrate_legacy_config_dir()
        self.assertTrue((self.current / "playlists").is_dir())
        self.assertFalse(self.legacy.exists())

    def test_a_rename_the_filesystem_refuses_falls_back_to_a_copy(self):
        # Across filesystems rename() fails and the move has to be a copy.
        (self.legacy / "playlists").mkdir(parents=True)
        with patch.object(Path, "rename", side_effect=OSError("EXDEV")):
            paths.migrate_legacy_config_dir()
        self.assertTrue((self.current / "playlists").is_dir())

    def test_an_install_that_already_moved_is_left_alone(self):
        self.legacy.mkdir()
        self.current.mkdir()
        paths.migrate_legacy_config_dir()
        self.assertTrue(self.legacy.is_dir())

    def test_an_install_that_never_had_a_legacy_directory_is_left_alone(self):
        paths.migrate_legacy_config_dir()
        self.assertFalse(self.current.exists())

    def test_paths_baked_into_the_config_are_repaired(self):
        # ".opemux" is not a substring of ".openemux", so the replace is
        # unambiguous and doing it twice changes nothing.
        (self.legacy).mkdir()
        (self.legacy / "config.yaml").write_text(
            f"library:\n  playlists_dir: {self.legacy}/playlists\n", encoding="utf-8"
        )
        paths.migrate_legacy_config_dir()
        text = (self.current / "config.yaml").read_text(encoding="utf-8")
        self.assertIn(str(self.current), text)
        self.assertNotIn(str(self.legacy), text)
        paths.migrate_legacy_config_dir()
        self.assertEqual(
            (self.current / "config.yaml").read_text(encoding="utf-8"), text
        )

    def test_a_config_that_names_no_legacy_path_is_not_rewritten(self):
        self.current.mkdir()
        config = self.current / "config.yaml"
        config.write_text("roms_path: /roms\n", encoding="utf-8")
        before = config.stat().st_mtime_ns
        paths.migrate_legacy_config_dir()
        self.assertEqual(config.stat().st_mtime_ns, before)

    def test_a_config_that_cannot_be_read_is_left_alone(self):
        self.current.mkdir()
        (self.current / "config.yaml").write_text("x", encoding="utf-8")
        with patch.object(Path, "read_text", side_effect=OSError("permission denied")):
            paths.migrate_legacy_config_dir()

    def test_an_install_with_no_config_file_at_all_is_left_alone(self):
        self.current.mkdir()
        paths.migrate_legacy_config_dir()


class TheFlatpakSandboxTests(unittest.TestCase):
    def test_a_flatpak_id_says_we_are_sandboxed(self):
        with patch.dict(os.environ, {"FLATPAK_ID": "io.github.x"}, clear=True):
            self.assertTrue(paths.is_running_in_flatpak())

    def test_outside_a_sandbox_the_real_home_is_the_home(self):
        with patch.object(paths, "is_running_in_flatpak", return_value=False):
            self.assertEqual(paths.get_real_home(), Path.home())

    def test_inside_one_the_real_home_comes_from_the_passwd_entry(self):
        # $HOME points at the per-app private dir; the ROM library does not.
        entry = type("Entry", (), {"pw_dir": "/home/real"})()
        with patch.object(paths, "is_running_in_flatpak", return_value=True):
            with patch("pwd.getpwuid", return_value=entry):
                self.assertEqual(paths.get_real_home(), Path("/home/real"))

    def test_a_passwd_entry_that_cannot_be_read_falls_back_to_home(self):
        with patch.object(paths, "is_running_in_flatpak", return_value=True):
            with patch("pwd.getpwuid", side_effect=KeyError("no such uid")):
                self.assertEqual(paths.get_real_home(), Path.home())

    def test_a_passwd_entry_with_no_directory_falls_back_too(self):
        entry = type("Entry", (), {"pw_dir": ""})()
        with patch.object(paths, "is_running_in_flatpak", return_value=True):
            with patch("pwd.getpwuid", return_value=entry):
                self.assertEqual(paths.get_real_home(), Path.home())


class WhereTheProjectRootIsTests(unittest.TestCase):
    def test_an_appimage_uses_the_tree_it_bundled(self):
        with TemporaryDirectory() as tmp_dir:
            bundled = Path(tmp_dir) / "usr" / "lib" / "openemux"
            bundled.mkdir(parents=True)
            environment = {"APPDIR": tmp_dir}
            with patch.dict(os.environ, environment, clear=True):
                self.assertEqual(get_project_root(), bundled.resolve())

    def test_an_appdir_with_no_bundled_tree_falls_through(self):
        with TemporaryDirectory() as tmp_dir:
            with patch.dict(os.environ, {"APPDIR": tmp_dir}, clear=True):
                with patch.object(paths, "is_running_in_flatpak", return_value=False):
                    self.assertTrue(get_project_root().is_dir())

    def test_a_flatpak_install_lives_under_app(self):
        with patch.dict(os.environ, {}, clear=True):
            with patch.object(paths, "is_running_in_flatpak", return_value=True):
                self.assertEqual(get_project_root(), Path("/app"))

    def test_an_absolute_path_is_returned_as_it_is(self):
        self.assertEqual(resolve_project_path("/opt/openemux"), Path("/opt/openemux"))


class DisplayingANonUtf8NameTests(unittest.TestCase):
    """Issue #214: a lone surrogate raises deep inside PyGObject."""

    def test_a_plain_name_is_returned_unchanged(self):
        self.assertEqual(paths.display_text("Chrono Trigger"), "Chrono Trigger")

    def test_a_lone_surrogate_is_shown_escaped_rather_than_raising(self):
        escaped = paths.display_text("Game\udcff.sfc")
        self.assertNotIn("\udcff", escaped)
        self.assertIn("Game", escaped)


class WhereAStoreLivesTests(unittest.TestCase):
    def test_a_store_sits_beside_the_config_file_it_is_given(self):
        self.assertEqual(
            paths.store_path("config", "/tmp/openemux"),
            Path("/tmp/openemux") / paths.STORE_FILENAMES["config"],
        )

    def test_without_one_it_falls_back_to_the_app_directory(self):
        with patch.object(Path, "home", classmethod(lambda _cls: Path("/home/x"))):
            self.assertEqual(paths.default_config_dir(), Path("/home/x/.openemux"))
            self.assertEqual(
                paths.store_path("config").parent, Path("/home/x/.openemux")
            )

    def test_a_store_name_that_is_a_typo_raises_rather_than_guessing(self):
        with self.assertRaises(KeyError):
            paths.store_path("not-a-store")
