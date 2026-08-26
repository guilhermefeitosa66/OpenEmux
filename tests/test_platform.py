"""Tests for openemux.core.platform, the OS-difference layer added by issue #118.

Everything here runs on both platforms. Where a Windows-specific answer is
under test, the platform flag is patched rather than the host being asked, so
Linux CI covers the Windows behaviour too -- otherwise the Windows paths would
only ever be exercised on a Windows machine, which is exactly where nobody is
looking when a Linux release goes out.
"""

import unittest
from unittest import mock

from openemux.core import platform
from openemux.core.platform import cfg_path, core_stem, normalize_core_filename


class CoreFilenameTests(unittest.TestCase):
    def test_extension_is_rewritten_to_this_platform(self):
        # The catalogs spell every core ".so"; the resolved name follows the host.
        self.assertEqual(
            normalize_core_filename("snes9x_libretro.so"),
            f"snes9x_libretro{platform.CORE_SUFFIX}",
        )

    def test_both_spellings_normalize_to_the_same_name(self):
        # A user pointing at a directory of cores may have either spelling.
        self.assertEqual(
            normalize_core_filename("mgba_libretro.so"),
            normalize_core_filename("mgba_libretro.dll"),
        )

    def test_names_without_a_core_extension_pass_through(self):
        # Never rewrite something we do not recognise: a path the user chose,
        # or a name with an unfamiliar suffix, must survive untouched.
        for value in ("retroarch", "core.bin", "C:/games/cores/thing.exe", ""):
            with self.subTest(value=value):
                self.assertEqual(normalize_core_filename(value), value)

    def test_none_is_returned_unchanged(self):
        # Callers pass a configured value straight through, and "not configured"
        # is None -- it must not become the string "None" or raise.
        self.assertIsNone(normalize_core_filename(None))
        self.assertIsNone(core_stem(None))

    def test_stem_drops_either_extension(self):
        # The predecessor of this function was filename[:-3], which is one
        # character short for ".dll" and would key the .info lookup off
        # "snes9x_libretro." -- matching nothing, silently.
        self.assertEqual(core_stem("snes9x_libretro.so"), "snes9x_libretro")
        self.assertEqual(core_stem("snes9x_libretro.dll"), "snes9x_libretro")

    def test_stem_leaves_an_unknown_suffix_alone(self):
        self.assertEqual(core_stem("mame2003_plus_libretro"), "mame2003_plus_libretro")
        self.assertEqual(core_stem("core.bin"), "core.bin")


class CfgPathTests(unittest.TestCase):
    """RetroArch reads a backslash inside a quoted .cfg value as an escape.

    ``savestate_directory = "C:\\Users\\me\\.openemux\\states"`` is parsed with
    ``\\U``, ``\\m`` and ``\\.`` consumed, so the directory silently becomes
    something else and the saves appear to vanish. Nothing errors; the user
    just loses data and blames the app.
    """

    def test_backslashes_become_forward_slashes(self):
        self.assertEqual(cfg_path(r"C:\Users\me\.openemux\states"), "C:/Users/me/.openemux/states")

    def test_a_posix_path_is_untouched(self):
        self.assertEqual(cfg_path("/home/me/.openemux/states"), "/home/me/.openemux/states")

    def test_is_idempotent(self):
        once = cfg_path(r"C:\Users\me\states")
        self.assertEqual(cfg_path(once), once)

    def test_accepts_a_path_object(self):
        from pathlib import PurePosixPath

        self.assertEqual(cfg_path(PurePosixPath("/a/b")), "/a/b")


class PlatformDefaultsTests(unittest.TestCase):
    def test_windows_downloads_cores_beside_the_bundled_retroarch(self):
        # Not %APPDATA%\RetroArch: issue #118 requires a RetroArch the user
        # installed themselves to be left untouched.
        with mock.patch.object(platform, "IS_WINDOWS", True):
            resolved = platform.bundled_core_dir("C:/app")
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.name, "cores")
        self.assertIn("RetroArch-Win64", resolved.as_posix())

    def test_linux_has_no_bundled_core_dir(self):
        with mock.patch.object(platform, "IS_WINDOWS", False):
            self.assertIsNone(platform.bundled_core_dir("/app"))

    def test_a_user_install_is_searched_only_on_windows(self):
        with mock.patch.object(platform, "IS_WINDOWS", False):
            self.assertEqual(platform.user_retroarch_dirs(), [])
        with mock.patch.object(platform, "IS_WINDOWS", True):
            with mock.patch.dict("os.environ", {"APPDATA": "C:/Users/me/AppData/Roaming"}):
                dirs = platform.user_retroarch_dirs()
        self.assertEqual([d.as_posix() for d in dirs], ["C:/Users/me/AppData/Roaming/RetroArch/cores"])

    def test_a_missing_appdata_is_not_an_error(self):
        # A service account or a stripped environment has no APPDATA; that
        # means "no user install to find", not a crash on startup.
        with mock.patch.object(platform, "IS_WINDOWS", True):
            with mock.patch.dict("os.environ", {}, clear=True):
                self.assertEqual(platform.user_retroarch_dirs(), [])

    def test_popen_kwargs_hide_the_console_only_on_windows(self):
        with mock.patch.object(platform, "IS_WINDOWS", False):
            self.assertEqual(platform.popen_kwargs(), {})
        with mock.patch.object(platform, "IS_WINDOWS", True):
            self.assertIn("creationflags", platform.popen_kwargs())

    def test_buildbot_os_matches_the_core_extension(self):
        # These two travel together: a Windows URL serving .dll and a .so
        # filter would download 223 archives and extract nothing from any.
        self.assertEqual(
            (platform.BUILDBOT_OS, platform.CORE_SUFFIX) in {("windows", ".dll"), ("linux", ".so")},
            True,
        )


if __name__ == "__main__":
    unittest.main()
