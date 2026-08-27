"""The environment a child gets when OpenEmux runs from its AppImage (#249).

The vendored RetroArch AppImage lives inside our own AppDir, and
appimage-builder's AppRun hooks decide by path: anything under ``$APPDIR``
is handed this bundle's loader path, ``LD_PRELOAD``, ``PYTHONHOME`` and
GTK/GI/pixbuf caches. RetroArch is a self-contained bundle of its own and
has to see the session instead.
"""

import unittest

from openemux.core.appimage_env import FALLBACK_PATH, host_env
from tests.platform_marks import linux_only

#: The environment measured inside the built bundle, trimmed to the names
#: that matter. Every one of these reached a process started from
#: ``$APPDIR/usr/lib/openemux/vendors/`` -- which is where RetroArch is.
BUNDLE_ENV = {
    "HOME": "/home/u",
    "DISPLAY": ":0",
    "APPDIR": "/tmp/.mount_OpenEmXYZ",
    "APPIMAGE": "/home/u/Downloads/OpenEmux-x86_64.AppImage",
    "APPIMAGE_UUID": "TGXJBn2",
    "APPDIR_LIBRARY_PATH": "/tmp/.mount_OpenEmXYZ/usr/lib/x86_64-linux-gnu",
    "APPDIR_LIBC_VERSION": "2.39",
    "APPRUN_STARTUP_PATH": "/tmp/.mount_OpenEmXYZ/usr/bin",
    "LD_LIBRARY_PATH": "/tmp/.mount_OpenEmXYZ/usr/lib/x86_64-linux-gnu",
    "LD_PRELOAD": "libapprun_hooks.so",
    "PYTHONHOME": "/tmp/.mount_OpenEmXYZ/usr",
    "PYTHONPATH": "/tmp/.mount_OpenEmXYZ/usr/lib/openemux/src",
    "GI_TYPELIB_PATH": "/tmp/.mount_OpenEmXYZ/usr/lib/x86_64-linux-gnu/girepository-1.0",
    "GDK_PIXBUF_MODULEDIR": "/tmp/.mount_OpenEmXYZ/usr/lib/gdk-pixbuf-2.0/2.10.0/loaders",
    "GDK_PIXBUF_MODULE_FILE": "/tmp/.mount_OpenEmXYZ/usr/lib/gdk-pixbuf-2.0/2.10.0/loaders.cache",
    "GIO_MODULE_DIR": "/tmp/.mount_OpenEmXYZ/usr/lib/gio/modules",
    "GSETTINGS_SCHEMA_DIR": "/tmp/.mount_OpenEmXYZ/usr/share/glib-2.0/schemas",
    "GTK_PATH": "/tmp/.mount_OpenEmXYZ/usr/lib/gtk-4.0",
    "GTK_EXE_PREFIX": "/tmp/.mount_OpenEmXYZ/usr",
    "GTK_DATA_PREFIX": "/tmp/.mount_OpenEmXYZ/usr",
    "OPENEMUX_PROJECT_ROOT": "/tmp/.mount_OpenEmXYZ/usr/lib/openemux",
    "PATH": "/tmp/.mount_OpenEmXYZ/usr/bin:/usr/bin:/bin",
    "XDG_DATA_DIRS": "/tmp/.mount_OpenEmXYZ/usr/share:/usr/local/share:/usr/share",
    "XDG_CONFIG_DIRS": "/tmp/.mount_OpenEmXYZ/etc/xdg:/etc/xdg",
}

#: What AppRun parked before it overwrote each of those. LD_PRELOAD and
#: XDG_CONFIG_DIRS are recorded empty on purpose: the session had none, and
#: that is an answer.
HOST_RECORD = {
    "APPRUN_ORIGINAL_PATH": "/home/u/.local/bin:/usr/bin:/bin",
    "APPRUN_ORIGINAL_XDG_DATA_DIRS": "/usr/share/cinnamon:/usr/local/share:/usr/share",
    "APPRUN_ORIGINAL_XDG_CONFIG_DIRS": "",
    "APPRUN_ORIGINAL_LD_LIBRARY_PATH": "",
    "APPRUN_ORIGINAL_LD_PRELOAD": "/usr/lib/mangohud.so",
}


def _bundle(**extra):
    env = dict(BUNDLE_ENV)
    env.update(extra)
    return env


class NothingOfTheBundleSurvivesTests(unittest.TestCase):
    def setUp(self):
        self.cleaned = host_env(_bundle(**HOST_RECORD), in_appimage=True)

    def test_the_loader_pointers_are_gone(self):
        # The dangerous half: RetroArch resolving its libraries against the
        # Ubuntu-noble stack bundled for a GTK4 app.
        self.assertNotIn("LD_LIBRARY_PATH", self.cleaned)
        self.assertNotIn("PYTHONHOME", self.cleaned)
        self.assertNotIn("PYTHONPATH", self.cleaned)

    def test_the_toolkit_caches_are_gone(self):
        for name in (
            "GI_TYPELIB_PATH",
            "GDK_PIXBUF_MODULEDIR",
            "GDK_PIXBUF_MODULE_FILE",
            "GIO_MODULE_DIR",
            "GSETTINGS_SCHEMA_DIR",
            "GTK_PATH",
            "GTK_EXE_PREFIX",
            "GTK_DATA_PREFIX",
        ):
            self.assertNotIn(name, self.cleaned)

    def test_the_bundles_own_bookkeeping_is_gone(self):
        for name in ("APPDIR", "APPIMAGE", "APPIMAGE_UUID", "OPENEMUX_PROJECT_ROOT"):
            self.assertNotIn(name, self.cleaned)
        self.assertFalse(
            [name for name in self.cleaned if name.startswith(("APPDIR_", "APPRUN_"))]
        )

    def test_no_value_still_points_inside_the_mount(self):
        leaked = {
            name: value
            for name, value in self.cleaned.items()
            if BUNDLE_ENV["APPDIR"] in value
        }
        self.assertEqual(leaked, {})

    def test_the_session_itself_is_untouched(self):
        self.assertEqual(self.cleaned["HOME"], "/home/u")
        self.assertEqual(self.cleaned["DISPLAY"], ":0")


class TheSessionIsRestoredExactlyTests(unittest.TestCase):
    """Not "a plausible value" -- the one the session had."""

    def setUp(self):
        self.cleaned = host_env(_bundle(**HOST_RECORD), in_appimage=True)

    def test_path_comes_back_as_the_user_had_it(self):
        self.assertEqual(self.cleaned["PATH"], HOST_RECORD["APPRUN_ORIGINAL_PATH"])

    def test_xdg_data_dirs_comes_back_with_the_desktops_own_entries(self):
        # AppRun replaces this one outright rather than prepending, so the
        # desktop's entries are not in the bundle's value to be trimmed --
        # only the record can bring them back.
        self.assertEqual(
            self.cleaned["XDG_DATA_DIRS"],
            HOST_RECORD["APPRUN_ORIGINAL_XDG_DATA_DIRS"],
        )

    def test_a_preload_the_user_chose_is_restored(self):
        # mangohud, gamemode and friends: the bundle overwrote LD_PRELOAD,
        # and dropping it would silently disable them for the game.
        self.assertEqual(self.cleaned["LD_PRELOAD"], "/usr/lib/mangohud.so")

    def test_a_variable_the_session_did_not_have_is_not_invented(self):
        # XDG_CONFIG_DIRS is recorded empty: the host had none, so the child
        # gets none rather than a trimmed version of the bundle's.
        self.assertNotIn("XDG_CONFIG_DIRS", self.cleaned)


class WithoutARecordTests(unittest.TestCase):
    """An AppRun that stopped keeping the originals still gets a clean child."""

    @linux_only("an AppImage mount, and a PATH joined with ':'")
    def test_with_no_record_at_all_the_appdir_parts_are_swept_out(self):
        # The host half of each list survives; only what points into the
        # mount goes. Losing PATH entirely would be the worse failure.
        cleaned = host_env(_bundle(), in_appimage=True)
        self.assertEqual(cleaned["PATH"], "/usr/bin:/bin")
        self.assertEqual(cleaned["XDG_DATA_DIRS"], "/usr/local/share:/usr/share")
        self.assertEqual(cleaned["XDG_CONFIG_DIRS"], "/etc/xdg")
        self.assertNotIn("LD_LIBRARY_PATH", cleaned)

    def test_a_path_that_was_nothing_but_bundle_falls_back_to_a_usable_one(self):
        cleaned = host_env(
            _bundle(PATH="/tmp/.mount_OpenEmXYZ/usr/bin"), in_appimage=True
        )
        self.assertEqual(cleaned["PATH"], FALLBACK_PATH)


class OutsideAnAppImageTests(unittest.TestCase):
    """A native or Flatpak install has no bundle to strip, and the user's own
    LD_PRELOAD/PYTHONPATH are theirs."""

    def test_the_environment_passes_through_untouched(self):
        session = {
            "PATH": "/usr/bin",
            "LD_PRELOAD": "/usr/lib/mangohud.so",
            "PYTHONPATH": "/home/u/lib",
            "GI_TYPELIB_PATH": "/usr/lib/girepository-1.0",
        }
        self.assertEqual(host_env(session, in_appimage=False), session)

    def test_it_is_a_copy_not_the_caller_s_dict(self):
        session = {"PATH": "/usr/bin"}
        cleaned = host_env(session, in_appimage=False)
        cleaned["PATH"] = "/nowhere"
        self.assertEqual(session["PATH"], "/usr/bin")


if __name__ == "__main__":
    unittest.main()
