"""The Windows shell identity of the Python process (issue #509).

The packaged app's windows belong to ``pythonw.exe``; ``core/win32_shell``
tells the shell they are OpenEmux. Most of it is ctypes plumbing that only means
anything on Windows, so on Linux the DLLs are replaced by fakes -- but the COM
side is driven for real: the fake property store is a genuine vtable of ctypes
callbacks, so the slot numbers, the prototypes and the PROPVARIANT layout the
module uses are the ones these tests read back.

The last class runs only on Windows (the "Unit tests (Windows / MSYS2)" job)
and talks to the real shell, which is what proves the layout against the real
``IPropertyStore`` rather than against a fake built to agree with it.
"""

import ctypes
import os
import sys
import tempfile
import unittest
from ctypes import wintypes
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from openemux.core import win32_shell as ws
from tests.platform_marks import windows_only

APP_ID = "io.github.guilhermefeitosa66.OpenEmux"
LAUNCHER = Path("C:/Users/someone/OpenEmux/OpenEmux.exe")


class FakePropertyStore:
    """An ``IPropertyStore`` at a real address, with a real vtable."""

    def __init__(self, set_value_hr=0, commit_hr=0):
        self.values = []
        self.fmtids = set()
        self.commits = 0
        self.releases = 0

        def release(this):
            self.releases += 1
            return 0

        def set_value(this, key, variant):
            v = variant.contents
            text = ctypes.wstring_at(v.pwszVal) if v.vt == ws.VT_LPWSTR else None
            self.values.append((key.contents.pid, v.vt, text))
            fmtid = key.contents.fmtid
            self.fmtids.add((fmtid.Data1, fmtid.Data2, fmtid.Data3, bytes(fmtid.Data4)))
            return set_value_hr

        def commit(this):
            self.commits += 1
            return commit_hr

        self._methods = {
            2: ws.RELEASE_PROTOTYPE(release),
            6: ws.SET_VALUE_PROTOTYPE(set_value),
            7: ws.COMMIT_PROTOTYPE(commit),
        }
        self._vtable = (ctypes.c_void_p * 8)(*[
            ctypes.cast(self._methods[slot], ctypes.c_void_p) if slot in self._methods else None
            for slot in range(8)
        ])
        self._object = (ctypes.c_void_p * 1)(ctypes.addressof(self._vtable))
        self.address = ctypes.addressof(self._object)


class _FakeDllCase(unittest.TestCase):
    """``_dlls()`` answers with mocks; the icon registry starts empty."""

    def setUp(self):
        self.shell32 = mock.Mock()
        self.user32 = mock.Mock()
        self.dlls = SimpleNamespace(shell32=self.shell32, user32=self.user32)
        patcher = mock.patch.object(ws, "_dlls", return_value=self.dlls)
        patcher.start()
        self.addCleanup(patcher.stop)
        icons = mock.patch.dict(ws._window_icons, clear=True)
        icons.start()
        self.addCleanup(icons.stop)

    def give_store(self, store, hresult=0):
        def _get(hwnd, riid, out):
            self.assertIs(riid._obj, ws.IID_IPROPERTYSTORE)
            out.contents.value = store.address if store else None
            return hresult

        self.shell32.SHGetPropertyStoreForWindow.side_effect = _get

    def give_icons(self, large, small):
        def _extract(path, index, large_out, small_out, count):
            self.extracted_from = (path, index, count)
            large_out.contents.value = large
            small_out.contents.value = small
            return int(bool(large)) + int(bool(small))

        self.shell32.ExtractIconExW.side_effect = _extract


class TheLauncherGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.exe = Path(self.tmp.name) / "OpenEmux.exe"
        self.exe.write_bytes(b"MZ")

    def test_the_packaged_bundle_names_its_launcher(self):
        with mock.patch.object(ws, "IS_WINDOWS", True):
            self.assertEqual(ws.launcher_path({ws.LAUNCHER_ENV: str(self.exe)}), self.exe)

    def test_it_reads_the_process_environment_by_default(self):
        with mock.patch.object(ws, "IS_WINDOWS", True), mock.patch.dict(
            os.environ, {ws.LAUNCHER_ENV: str(self.exe)}
        ):
            self.assertEqual(ws.launcher_path(), self.exe)

    def test_a_source_run_has_no_launcher(self):
        with mock.patch.object(ws, "IS_WINDOWS", True):
            self.assertIsNone(ws.launcher_path({}))
            self.assertIsNone(ws.launcher_path({ws.LAUNCHER_ENV: ""}))

    def test_a_launcher_that_is_not_there_is_ignored(self):
        with mock.patch.object(ws, "IS_WINDOWS", True):
            missing = str(self.exe.with_name("Gone.exe"))
            self.assertIsNone(ws.launcher_path({ws.LAUNCHER_ENV: missing}))

    def test_off_windows_it_is_off_even_with_the_variable_set(self):
        with mock.patch.object(ws, "IS_WINDOWS", False), mock.patch.object(ws, "_dlls") as dlls:
            self.assertIsNone(ws.launcher_path({ws.LAUNCHER_ENV: str(self.exe)}))
        dlls.assert_not_called()


class TheProcessAppIdTests(_FakeDllCase):
    def test_a_successful_call_is_reported(self):
        self.shell32.SetCurrentProcessExplicitAppUserModelID.return_value = 0
        self.assertTrue(ws.set_process_app_id(APP_ID))
        self.shell32.SetCurrentProcessExplicitAppUserModelID.assert_called_once_with(APP_ID)

    def test_a_failing_hresult_is_logged_not_raised(self):
        self.shell32.SetCurrentProcessExplicitAppUserModelID.return_value = -2147024809
        with self.assertLogs(ws.logger, "WARNING") as logs:
            self.assertFalse(ws.set_process_app_id(APP_ID))
        self.assertIn("0x80070057", logs.output[0])

    def test_a_missing_dll_is_logged_not_raised(self):
        for error in (OSError("no shell32"), AttributeError("no export")):
            with self.subTest(error=error), mock.patch.object(ws, "_dlls", side_effect=error):
                with self.assertLogs(ws.logger, "WARNING"):
                    self.assertFalse(ws.set_process_app_id(APP_ID))


class ApplyingTheWindowIdentityTests(_FakeDllCase):
    def test_the_icons_and_the_four_keys_land(self):
        store = FakePropertyStore()
        self.give_store(store)
        self.give_icons(0x111, 0x222)

        self.assertTrue(ws.apply_window_identity(0x42, APP_ID, LAUNCHER))

        self.assertEqual(self.extracted_from, (str(LAUNCHER), 0, 1))
        self.user32.SendMessageW.assert_has_calls([
            mock.call(0x42, ws.WM_SETICON, ws.ICON_BIG, 0x111),
            mock.call(0x42, ws.WM_SETICON, ws.ICON_SMALL, 0x222),
        ])
        self.assertEqual(ws._window_icons[0x42], [0x111, 0x222])
        self.assertEqual(sorted(store.values), [
            (ws.PID_RELAUNCH_COMMAND, ws.VT_LPWSTR, f'"{LAUNCHER}"'),
            (ws.PID_RELAUNCH_ICON_RESOURCE, ws.VT_LPWSTR, f"{LAUNCHER},0"),
            (ws.PID_RELAUNCH_DISPLAY_NAME_RESOURCE, ws.VT_LPWSTR, "OpenEmux"),
            (ws.PID_APP_USER_MODEL_ID, ws.VT_LPWSTR, APP_ID),
        ])
        # PKEY_AppUserModel_*: {9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3}.
        self.assertEqual(store.fmtids, {
            (0x9F4C2855, 0x9F79, 0x4B39, bytes.fromhex("A8D0E1D42DE1D5F3")),
        })
        self.assertEqual((store.commits, store.releases), (1, 1))

    def test_reapplying_frees_the_icons_handed_out_before(self):
        self.give_store(FakePropertyStore())
        self.give_icons(0x111, 0x222)
        ws.apply_window_identity(0x42, APP_ID, LAUNCHER)
        self.give_icons(0x333, 0)
        ws.apply_window_identity(0x42, APP_ID, LAUNCHER)
        self.assertEqual(
            self.user32.DestroyIcon.call_args_list, [mock.call(0x111), mock.call(0x222)]
        )
        self.assertEqual(ws._window_icons[0x42], [0x333])
        self.user32.SendMessageW.assert_called_with(0x42, ws.WM_SETICON, ws.ICON_BIG, 0x333)

    def test_a_launcher_with_no_icon_sends_nothing_but_still_sets_the_keys(self):
        store = FakePropertyStore()
        self.give_store(store)
        self.give_icons(0, 0)
        with self.assertLogs(ws.logger, "WARNING") as logs:
            self.assertFalse(ws.apply_window_identity(0x42, APP_ID, LAUNCHER))
        self.assertIn("window icon", logs.output[0])
        self.user32.SendMessageW.assert_not_called()
        self.assertNotIn(0x42, ws._window_icons)
        self.assertEqual(len(store.values), 4)

    def test_a_window_with_no_store_still_gets_its_icon(self):
        self.give_store(None, hresult=-2147467259)
        self.give_icons(0x111, 0x222)
        with self.assertLogs(ws.logger, "WARNING") as logs:
            self.assertFalse(ws.apply_window_identity(0x42, APP_ID, LAUNCHER))
        self.assertIn("0x80004005", logs.output[0])
        self.assertEqual(self.user32.SendMessageW.call_count, 2)

    def test_a_store_call_that_succeeds_with_no_store_is_a_failure(self):
        self.give_store(None)
        self.give_icons(0x111, 0x222)
        with self.assertLogs(ws.logger, "WARNING") as logs:
            self.assertFalse(ws.apply_window_identity(0x42, APP_ID, LAUNCHER))
        self.assertIn("no store", logs.output[0])

    def test_a_failing_set_value_still_releases_the_store(self):
        store = FakePropertyStore(set_value_hr=-2147024809)
        self.give_store(store)
        self.give_icons(0x111, 0x222)
        with self.assertLogs(ws.logger, "WARNING") as logs:
            self.assertFalse(ws.apply_window_identity(0x42, APP_ID, LAUNCHER))
        self.assertIn("SetValue", logs.output[0])
        self.assertEqual((store.commits, store.releases), (0, 1))

    def test_a_failing_commit_still_releases_the_store(self):
        store = FakePropertyStore(commit_hr=-2147024809)
        self.give_store(store)
        self.give_icons(0x111, 0x222)
        with self.assertLogs(ws.logger, "WARNING") as logs:
            self.assertFalse(ws.apply_window_identity(0x42, APP_ID, LAUNCHER))
        self.assertIn("Commit", logs.output[0])
        self.assertEqual((store.commits, store.releases), (1, 1))


class ClearingTheWindowIdentityTests(_FakeDllCase):
    def test_every_key_is_emptied_and_the_icons_freed(self):
        store = FakePropertyStore()
        self.give_store(store)
        ws._window_icons[0x42] = [0x111, 0x222]

        self.assertTrue(ws.clear_window_identity(0x42))

        self.assertEqual(sorted(store.values), [
            (ws.PID_RELAUNCH_COMMAND, ws.VT_EMPTY, None),
            (ws.PID_RELAUNCH_ICON_RESOURCE, ws.VT_EMPTY, None),
            (ws.PID_RELAUNCH_DISPLAY_NAME_RESOURCE, ws.VT_EMPTY, None),
            (ws.PID_APP_USER_MODEL_ID, ws.VT_EMPTY, None),
        ])
        self.assertEqual((store.commits, store.releases), (1, 1))
        self.assertEqual(
            self.user32.DestroyIcon.call_args_list, [mock.call(0x111), mock.call(0x222)]
        )
        self.assertNotIn(0x42, ws._window_icons)

    def test_a_window_that_never_got_icons_is_cleared_all_the_same(self):
        store = FakePropertyStore()
        self.give_store(store)
        self.assertTrue(ws.clear_window_identity(0x42))
        self.user32.DestroyIcon.assert_not_called()
        self.assertEqual(len(store.values), 4)

    def test_a_store_failure_still_frees_the_icons(self):
        self.give_store(None, hresult=-2147467259)
        ws._window_icons[0x42] = [0x111]
        with self.assertLogs(ws.logger, "WARNING"):
            self.assertFalse(ws.clear_window_identity(0x42))
        self.user32.DestroyIcon.assert_called_once_with(0x111)

    def test_an_icon_that_will_not_free_is_logged_not_raised(self):
        self.give_store(FakePropertyStore())
        ws._window_icons[0x42] = [0x111]
        self.user32.DestroyIcon.side_effect = ctypes.ArgumentError("bad handle")
        with self.assertLogs(ws.logger, "WARNING") as logs:
            self.assertFalse(ws.clear_window_identity(0x42))
        self.assertIn("free the window icons", logs.output[0])


class FindingTheAppsWindowsTests(_FakeDllCase):
    def setUp(self):
        super().setUp()
        # hwnd -> (owning pid, visible)
        self.windows = {
            0x10: (700, True),
            0x20: (999, True),    # another process: RetroArch, say
            0x30: (700, False),   # one of GDK's hidden helper windows
            0x40: (700, True),
        }

        def _enum(callback, lparam):
            for hwnd in self.windows:
                if not callback(hwnd, lparam):
                    break
            return 1

        def _owner(hwnd, out):
            out.contents.value = self.windows[hwnd][0]
            return 1

        self.user32.EnumWindows.side_effect = _enum
        self.user32.GetWindowThreadProcessId.side_effect = _owner
        self.user32.IsWindowVisible.side_effect = lambda hwnd: self.windows[hwnd][1]

    def test_only_this_processes_visible_windows_are_returned(self):
        self.assertEqual(ws.find_toplevel_hwnds(700), [0x10, 0x40])

    def test_a_process_with_no_window_gets_an_empty_list(self):
        self.assertEqual(ws.find_toplevel_hwnds(1234), [])

    def test_a_failing_enumeration_is_logged_not_raised(self):
        self.user32.EnumWindows.side_effect = OSError("access denied")
        with self.assertLogs(ws.logger, "WARNING"):
            self.assertEqual(ws.find_toplevel_hwnds(700), [])


class LoadingTheDllsTests(unittest.TestCase):
    def test_both_dlls_are_loaded_with_their_signatures(self):
        loaded = {}

        def _load(name):
            loaded[name] = mock.Mock()
            return loaded[name]

        with mock.patch("ctypes.WinDLL", side_effect=_load, create=True):
            dlls = ws._dlls.__wrapped__()

        self.assertIs(dlls.shell32, loaded["shell32"])
        self.assertIs(dlls.user32, loaded["user32"])
        # A handle-returning or handle-taking call without a pointer-sized
        # signature is truncated to 32 bits by ctypes.
        self.assertEqual(dlls.user32.SendMessageW.argtypes[0], wintypes.HWND)
        self.assertEqual(dlls.user32.EnumWindows.argtypes[0], ws.WNDENUMPROC)
        self.assertEqual(dlls.shell32.SHGetPropertyStoreForWindow.restype, ws.HRESULT)
        for function in (
            dlls.shell32.SetCurrentProcessExplicitAppUserModelID,
            dlls.shell32.ExtractIconExW,
            dlls.user32.DestroyIcon,
            dlls.user32.GetWindowThreadProcessId,
            dlls.user32.IsWindowVisible,
        ):
            self.assertIsInstance(function.argtypes, list)


class TheStructuresTests(unittest.TestCase):
    def test_a_guid_parses_to_its_fields(self):
        guid = ws.GUID.parse("{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}")
        self.assertEqual((guid.Data1, guid.Data2, guid.Data3), (0x886D8EEB, 0x8CF2, 0x4446))
        self.assertEqual(bytes(guid.Data4), bytes.fromhex("8D02CDBA1DBDCF99"))
        self.assertEqual(ctypes.sizeof(guid), 16)

    def test_a_propvariant_has_the_native_size(self):
        # 8 bytes of type and reserved words, then a 16-byte union on x86_64.
        self.assertEqual(ctypes.sizeof(ws.PROPVARIANT), 8 + 2 * ctypes.sizeof(ctypes.c_void_p))
        self.assertEqual(ws.PROPVARIANT.pwszVal.offset, 8)


@windows_only("round trips through the real shell32/user32 and IPropertyStore")
class TheRealWindowsShellTests(unittest.TestCase):
    """Round trips through the real shell, so the layout is proven, not assumed."""

    def setUp(self):
        ws._dlls.cache_clear()
        self.ole32 = ctypes.WinDLL("ole32")
        self.ole32.CoInitialize(None)
        self.addCleanup(self.ole32.CoUninitialize)

    def test_the_process_app_id_reads_back(self):
        shell32 = ctypes.WinDLL("shell32")
        get = shell32.GetCurrentProcessExplicitAppUserModelID
        get.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
        get.restype = ws.HRESULT

        self.assertTrue(ws.set_process_app_id(APP_ID))

        value = ctypes.c_void_p()
        self.assertEqual(get(ctypes.byref(value)), 0)
        try:
            self.assertEqual(ctypes.wstring_at(value.value), APP_ID)
        finally:
            self.ole32.CoTaskMemFree(value)

    def test_a_real_window_takes_the_identity_and_gives_it_back(self):
        user32 = ctypes.WinDLL("user32")
        user32.CreateWindowExW.argtypes = [
            wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
        ]
        user32.CreateWindowExW.restype = wintypes.HWND
        user32.DestroyWindow.argtypes = [wintypes.HWND]
        hwnd = user32.CreateWindowExW(
            0, "STATIC", "openemux-test", 0, 0, 0, 10, 10, None, None, None, None
        )
        self.assertTrue(hwnd)
        self.addCleanup(user32.DestroyWindow, hwnd)

        # Any executable with an icon resource: the interpreter running this.
        launcher = Path(sys.executable)
        self.assertTrue(ws.apply_window_identity(hwnd, APP_ID, launcher))

        get_value = ws._COMFUNCTYPE(
            ws.HRESULT, ctypes.c_void_p,
            ctypes.POINTER(ws.PROPERTYKEY), ctypes.POINTER(ws.PROPVARIANT),
        )
        store = ws._property_store_for(hwnd)
        try:
            variant = ws.PROPVARIANT()
            key = ws._key(ws.PID_APP_USER_MODEL_ID)
            hr = ws._com_method(store, 5, get_value)(store, ctypes.byref(key), ctypes.byref(variant))
            self.assertEqual(hr, 0)
            self.assertEqual(variant.vt, ws.VT_LPWSTR)
            self.assertEqual(ctypes.wstring_at(variant.pwszVal), APP_ID)
            self.ole32.PropVariantClear(ctypes.byref(variant))
        finally:
            ws._com_method(store, ws._RELEASE, ws.RELEASE_PROTOTYPE)(store)

        self.assertTrue(ws.clear_window_identity(hwnd))
        self.assertNotIn(hwnd, ws._window_icons)


if __name__ == "__main__":
    unittest.main()
