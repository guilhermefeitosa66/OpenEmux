"""The Windows portable mode: everything inside the unzipped folder (issue #766).

Driven on Linux with the platform flag faked, the way ``test_pixbuf_loaders``
drives the rest of the Windows start-up: the question is which path each
function hands back, and that is the same logic on every OS.
"""

import os
import tempfile
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from openemux.core import artwork_search, paths, pixbuf_loaders, portable


class _PortableCase(unittest.TestCase):
    """A fake install root, with or without the marker, on a faked Windows."""

    marker = True

    def setUp(self):
        self._dir = TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.root = Path(self._dir.name).resolve()
        if self.marker:
            (self.root / paths.PORTABLE_MARKER).write_text("portable\n", encoding="utf-8")
        for patcher in (
            patch.object(paths, "IS_WINDOWS", True),
            patch.dict(os.environ, {"OPENEMUX_PROJECT_ROOT": str(self.root)}),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        paths._portable_root_at.cache_clear()
        self.addCleanup(paths._portable_root_at.cache_clear)
        self.data = self.root / paths.PORTABLE_DATA_DIR


class DetectingAPortableInstallTests(_PortableCase):
    def test_the_marker_beside_the_launcher_makes_it_portable(self):
        self.assertEqual(paths.portable_root(), self.root)
        self.assertEqual(paths.portable_data_dir("roms"), self.data / "roms")

    def test_linux_is_never_portable_and_never_looks(self):
        with patch.object(paths, "IS_WINDOWS", False), patch.object(
            paths, "_portable_root_at"
        ) as lookup:
            self.assertIsNone(paths.portable_root())
            self.assertIsNone(paths.portable_data_dir("roms"))
        lookup.assert_not_called()

    def test_the_answer_is_read_once(self):
        self.assertEqual(paths.portable_root(), self.root)
        (self.root / paths.PORTABLE_MARKER).unlink()
        self.assertEqual(paths.portable_root(), self.root)


class EveryDataRootFollowsTheMarkerTests(_PortableCase):
    def test_the_config_dir_is_inside_the_folder(self):
        self.assertEqual(paths.default_config_dir(), self.data / "openemux")
        self.assertEqual(paths.store_path("config"), self.data / "openemux" / "config.yaml")

    def test_the_default_rom_folder_is_inside_the_folder(self):
        self.assertEqual(paths.default_roms_path(), self.data / "roms")

    def test_the_caches_are_inside_the_folder(self):
        self.assertEqual(paths.user_cache_dir(), self.data / "cache")
        self.assertEqual(
            paths.bytecode_cache_dir(), self.data / "cache" / "openemux" / "bytecode"
        )
        self.assertEqual(
            artwork_search.artwork_temp_root(),
            self.data / "cache" / "openemux" / "artwork-manager",
        )

    def test_the_legacy_migration_never_touches_the_profile(self):
        with TemporaryDirectory() as home:
            legacy = Path(home) / paths.LEGACY_CONFIG_DIR_NAME
            legacy.mkdir()
            with patch.object(Path, "home", classmethod(lambda _cls: Path(home))):
                paths.migrate_legacy_config_dir()
            self.assertTrue(legacy.is_dir())
            self.assertFalse((Path(home) / paths.CONFIG_DIR_NAME).exists())

    def test_the_pixbuf_fallback_is_inside_the_folder_not_localappdata(self):
        cache = Path("C:/bundle/lib/gdk-pixbuf-2.0/2.10.0/loaders.cache")
        self.assertEqual(
            list(pixbuf_loaders._candidate_paths(cache, {"LOCALAPPDATA": "C:/profile"})),
            [cache, self.data / "cache" / "openemux" / pixbuf_loaders.CACHE_NAME],
        )


class WithoutTheMarkerNothingMovesTests(_PortableCase):
    """The installer: the paths every existing Windows install already uses."""

    marker = False

    def test_the_config_dir_stays_in_the_user_home(self):
        with patch.object(Path, "home", classmethod(lambda _cls: Path("/home/x"))):
            self.assertEqual(paths.default_config_dir(), Path("/home/x/.openemux"))

    def test_the_rom_folder_stays_in_the_real_home(self):
        with patch.object(paths, "get_real_home", return_value=Path("/home/x")):
            self.assertEqual(paths.default_roms_path(), Path("/home/x/games/roms"))

    def test_the_pixbuf_fallback_stays_in_localappdata(self):
        cache = Path("C:/bundle/loaders.cache")
        self.assertEqual(
            list(pixbuf_loaders._candidate_paths(cache, {"LOCALAPPDATA": "/profile"})),
            [cache, Path("/profile") / "OpenEmux" / pixbuf_loaders.CACHE_NAME],
        )

    def test_the_environment_is_left_alone(self):
        env = {}
        self.assertIsNone(portable.apply_portable_environment(env))
        self.assertEqual(env, {})


class ThePortableEnvironmentTests(_PortableCase):
    def setUp(self):
        super().setUp()
        saved = tempfile.tempdir
        self.addCleanup(setattr, tempfile, "tempdir", saved)

    def _fonts_conf(self):
        bundled = self.root / "etc" / "fonts" / "fonts.conf"
        bundled.parent.mkdir(parents=True)
        bundled.write_text("<fontconfig/>", encoding="utf-8")
        return bundled

    def test_glib_and_temp_files_are_pointed_inside_the_folder(self):
        env = {}
        tempfile.tempdir = "/profile/Temp"
        self.assertEqual(portable.apply_portable_environment(env), self.root)
        self.assertEqual(
            env,
            {
                "XDG_CONFIG_HOME": str(self.data / "config"),
                "XDG_DATA_HOME": str(self.data / "share"),
                "XDG_CACHE_HOME": str(self.data / "cache"),
                "XDG_STATE_HOME": str(self.data / "state"),
                "TEMP": str(self.data / "tmp"),
                "TMP": str(self.data / "tmp"),
            },
        )
        for value in env.values():
            self.assertTrue(Path(value).is_dir())
        self.assertIsNone(tempfile.tempdir)

    def test_it_defaults_to_the_process_environment(self):
        with patch.dict(os.environ, {}):
            portable.apply_portable_environment()
            self.assertEqual(os.environ["TEMP"], str(self.data / "tmp"))

    def test_fontconfig_caches_inside_the_folder_and_keeps_the_bundle_config(self):
        bundled = self._fonts_conf()
        env = {}
        portable.apply_portable_environment(env)
        wrapper = self.data / "cache" / "fonts.conf"
        self.assertEqual(env["FONTCONFIG_FILE"], str(wrapper))
        text = wrapper.read_text(encoding="utf-8")
        self.assertIn(f"<cachedir>{self.data / 'cache' / 'fontconfig'}</cachedir>", text)
        self.assertIn(f">{bundled}</include>", text)
        self.assertLess(text.index("<cachedir>"), text.index("<include"))

    def test_an_unchanged_wrapper_is_not_rewritten(self):
        self._fonts_conf()
        portable.apply_portable_environment({})
        with patch.object(portable, "atomic_write_text") as write:
            portable.apply_portable_environment({})
        write.assert_not_called()

    def test_a_folder_that_moved_gets_its_wrapper_refreshed(self):
        self._fonts_conf()
        wrapper = self.data / "cache" / "fonts.conf"
        wrapper.parent.mkdir(parents=True)
        wrapper.write_text("<fontconfig><cachedir>E:\\old</cachedir></fontconfig>", encoding="utf-8")
        portable.apply_portable_environment({})
        self.assertNotIn("E:\\old", wrapper.read_text(encoding="utf-8"))

    def test_a_bundle_without_fontconfig_gets_no_wrapper(self):
        env = {}
        portable.apply_portable_environment(env)
        self.assertNotIn("FONTCONFIG_FILE", env)
        self.assertFalse((self.data / "cache" / "fonts.conf").exists())

    def test_an_unwritable_folder_leaves_the_environment_as_it_was(self):
        env = {"TEMP": "C:/profile/Temp"}
        with patch.object(Path, "mkdir", side_effect=PermissionError("read-only")):
            self.assertIsNone(portable.apply_portable_environment(env))
        self.assertEqual(env, {"TEMP": "C:/profile/Temp"})


class TheZipAloneCarriesTheMarkerTests(unittest.TestCase):
    """``build.sh`` puts the marker in the zip and keeps it out of the installer."""

    REPO = Path(__file__).resolve().parents[1]

    def setUp(self):
        self.script = (self.REPO / "packaging" / "windows" / "build.sh").read_text(
            encoding="utf-8"
        )

    def test_the_marker_ships_with_the_packaging(self):
        marker = self.REPO / "packaging" / "windows" / paths.PORTABLE_MARKER
        self.assertIn("portable", marker.read_text(encoding="utf-8"))

    def test_it_is_added_for_the_zip_and_removed_before_the_installer(self):
        add = self.script.index('cp packaging/windows/portable.txt "$BUNDLE/portable.txt"')
        zip_ = self.script.index('zip -q -r -9 "../../dist/$ZIP"')
        remove = self.script.index('rm -f "$BUNDLE/portable.txt"')
        installer = self.script.index("makensis")
        self.assertLess(add, zip_)
        self.assertLess(zip_, remove)
        self.assertLess(remove, installer)

    def test_the_build_fails_when_either_artifact_is_wrong(self):
        self.assertIn("has no OpenEmux/portable.txt", self.script)
        self.assertIn("the installer bundle carries portable.txt", self.script)


if __name__ == "__main__":
    unittest.main()
