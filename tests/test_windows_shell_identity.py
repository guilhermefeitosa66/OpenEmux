"""The packaging half of the Windows shell identity (issue #509).

``core/win32_shell`` does its work in the Python process, but it leans on two
things only the Windows build produces: the launcher exporting its own path,
and the installer stamping the same AppUserModelID on its Start Menu shortcut.
Neither can run here, so they are read as text -- in the style of
``test_windows_bundle_prune``'s reading of ``build.sh``.
"""

import re
import unittest
from pathlib import Path

from openemux.core import win32_shell
from openemux.main import APP_ID

REPO_ROOT = Path(__file__).resolve().parents[1]
WINDOWS = REPO_ROOT / "packaging/windows"


def _read(name):
    return (WINDOWS / name).read_text(encoding="utf-8")


class TheLauncherTests(unittest.TestCase):
    def test_it_exports_its_own_full_path_before_cutting_it_down(self):
        source = _read("openemux-launcher.c")
        export = source.index(f'SetEnvironmentVariableW(L"{win32_shell.LAUNCHER_ENV}", self);')
        strip = source.index("*separator = L'\\0';")
        # After the strip, `self` is the install directory, not the exe.
        self.assertLess(export, strip)

    def test_the_build_gates_on_the_export(self):
        build = _read("build.sh")
        phase5 = build.split("phase 5", 1)[1].split("phase 6", 1)[0]
        self.assertIn(f'"{win32_shell.LAUNCHER_ENV}".encode("utf-16-le")', phase5)


class TheInstallerTests(unittest.TestCase):
    def setUp(self):
        self.nsi = _read("openemux.nsi")

    def test_the_shortcut_carries_the_apps_own_id(self):
        defined = re.search(r'^!define APP_USER_MODEL_ID "([^"]+)"', self.nsi, re.M)
        self.assertIsNotNone(defined)
        self.assertEqual(defined.group(1), APP_ID)

    def test_the_id_is_written_right_after_the_shortcut_is_made(self):
        lines = [line.strip() for line in self.nsi.splitlines()]
        create = next(
            i for i, line in enumerate(lines)
            if line.startswith('CreateShortCut "$SMPROGRAMS\\OpenEmux\\OpenEmux.lnk"')
        )
        # The CreateShortCut call continues on the next line.
        self.assertEqual(
            lines[create + 2],
            '!insertmacro SetShortcutAppId "$SMPROGRAMS\\OpenEmux\\OpenEmux.lnk"',
        )
        self.assertNotIn('SetShortcutAppId "$SMPROGRAMS\\OpenEmux\\Uninstall', self.nsi)

    def test_the_macro_writes_the_app_user_model_id_key(self):
        macro = self.nsi.split("!macro SetShortcutAppId", 1)[1].split("!macroend", 1)[0]
        # IID_IPropertyStore, then PKEY_AppUserModel_ID (fmtid, pid 5).
        self.assertIn("{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}", macro)
        self.assertIn('{9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3}", i 5', macro)
        self.assertIn("${APP_USER_MODEL_ID}", macro)
        # SetValue, Commit, Release -- the IPropertyStore slots the app uses.
        for slot in (win32_shell._SET_VALUE, win32_shell._COMMIT, win32_shell._RELEASE):
            self.assertIn(f"$1->{slot}(", macro)

    def test_logiclib_is_included_for_the_macro(self):
        self.assertIn('!include "LogicLib.nsh"', self.nsi)


if __name__ == "__main__":
    unittest.main()
