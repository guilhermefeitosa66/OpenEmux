"""Tell the Windows shell that the Python process is OpenEmux (issue #509).

``OpenEmux.exe`` is only a launcher: it sets up the bundle's environment and
starts ``bin\\pythonw.exe -m openemux.main``. Every window the app opens
therefore belongs to ``pythonw.exe``, and the shell treats it that way -- the
taskbar shows Python's icon, groups OpenEmux with any other ``pythonw`` window,
and "Pin to taskbar" pins bare ``pythonw.exe``, which relaunches without the
launcher's environment and fails to start.

The fix is three declarations the shell honours, all made from this process:

* one explicit AppUserModelID for the process, set before the first window
  exists -- the same id the installer writes on its Start Menu shortcut, so a
  pinned shortcut and the running window are one taskbar button;
* the window icons, taken from ``OpenEmux.exe``'s own icon resource;
* relaunch properties on every window, pointing at ``OpenEmux.exe``, so a
  button pinned from the running window starts the app through the launcher.

Only active in the packaged bundle: the launcher exports its own path as
``OPENEMUX_LAUNCHER``, and without it there is nothing to relaunch. Everything
is best-effort -- a failed call logs a warning and the app runs exactly as it
did before. No dependency either: ``ctypes`` against ``shell32`` and
``user32``, which every Windows has.
"""

import ctypes
import functools
import logging
import os
from ctypes import wintypes
from pathlib import Path
from types import SimpleNamespace

from openemux.core.platform import IS_WINDOWS

logger = logging.getLogger(__name__)

#: Set by ``packaging/windows/openemux-launcher.c`` to the full path of the
#: running ``OpenEmux.exe``.
LAUNCHER_ENV = "OPENEMUX_LAUNCHER"

#: What the shell labels a pinned button with. The product name, untranslated,
#: like the version resource of the launcher.
RELAUNCH_DISPLAY_NAME = "OpenEmux"

# ----- Win32 constants -------------------------------------------------------
#: ``SendMessageW`` message that sets a window's title-bar/taskbar icon.
WM_SETICON = 0x0080
#: ``WM_SETICON`` slots: the Alt-Tab/taskbar icon and the title-bar one.
ICON_SMALL = 0
ICON_BIG = 1

#: PROPVARIANT types used here: nothing (clears a key) and a wide string.
VT_EMPTY = 0
VT_LPWSTR = 31

#: ``IPropertyStore`` vtable slots, in the documented order (IUnknown first).
_RELEASE = 2
_SET_VALUE = 6
_COMMIT = 7

#: Errors a ctypes call into the shell can raise on its way out: a DLL or an
#: export that is not there, a bad argument, or a failing HRESULT turned into
#: ``OSError`` by ``_check``.
_SHELL_ERRORS = (OSError, AttributeError, ctypes.ArgumentError)

# COM methods use the stdcall convention on 32-bit Windows; on x86_64 -- the
# only architecture the bundle is built for -- there is one convention, and on
# Linux, where the tests drive these prototypes against fake objects, there is
# no WINFUNCTYPE at all.
_COMFUNCTYPE = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)

HRESULT = ctypes.c_long


# The two structures below spell their widths out instead of using wintypes:
# ``wintypes.DWORD`` is a C ``unsigned long``, which is 4 bytes on Windows and
# 8 on Linux, and the tests drive these exact layouts there.
class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_uint32),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_ubyte * 8),
    ]

    @classmethod
    def parse(cls, text):
        """``"{XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX}"`` -> ``GUID``."""
        parts = text.strip("{}").split("-")
        tail = bytes.fromhex(parts[3] + parts[4])
        return cls(
            int(parts[0], 16),
            int(parts[1], 16),
            int(parts[2], 16),
            (ctypes.c_ubyte * 8)(*tail),
        )


class PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", GUID), ("pid", ctypes.c_uint32)]


class PROPVARIANT(ctypes.Structure):
    """The two shapes used here: ``VT_EMPTY`` and ``VT_LPWSTR``.

    The real one is a 16-byte union after the type and three reserved words;
    a string pointer is its first member, and the trailing pointer pads it to
    the native size (24 bytes on x86_64).
    """

    _fields_ = [
        ("vt", ctypes.c_ushort),
        ("wReserved1", ctypes.c_ushort),
        ("wReserved2", ctypes.c_ushort),
        ("wReserved3", ctypes.c_ushort),
        ("pwszVal", ctypes.c_void_p),
        ("_padding", ctypes.c_void_p),
    ]


#: ``IID_IPropertyStore``.
IID_IPROPERTYSTORE = GUID.parse("{886D8EEB-8CF2-4446-8D02-CDBA1DBDCF99}")

#: ``PKEY_AppUserModel_*`` all share this format id.
_APP_USER_MODEL_FMTID = "{9F4C2855-9F79-4B39-A8D0-E1D42DE1D5F3}"

#: The four keys, by property id.
PID_RELAUNCH_COMMAND = 2
PID_RELAUNCH_ICON_RESOURCE = 3
PID_RELAUNCH_DISPLAY_NAME_RESOURCE = 4
PID_APP_USER_MODEL_ID = 5

#: ``IPropertyStore::Release``, ``SetValue`` and ``Commit``.
RELEASE_PROTOTYPE = _COMFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)
SET_VALUE_PROTOTYPE = _COMFUNCTYPE(
    HRESULT, ctypes.c_void_p, ctypes.POINTER(PROPERTYKEY), ctypes.POINTER(PROPVARIANT)
)
COMMIT_PROTOTYPE = _COMFUNCTYPE(HRESULT, ctypes.c_void_p)

#: ``EnumWindows``' callback.
WNDENUMPROC = _COMFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

#: Icons handed to a window with ``WM_SETICON``, by window handle. The window
#: does not own them, so they must outlive it on the screen and be destroyed
#: once it is gone.
_window_icons = {}


def _key(pid):
    return PROPERTYKEY(GUID.parse(_APP_USER_MODEL_FMTID), pid)


def _check(hresult, what):
    """Turn a failing HRESULT into ``OSError``."""
    if hresult < 0:
        raise OSError(f"{what} failed with HRESULT 0x{hresult & 0xFFFFFFFF:08X}")


@functools.cache
def _dlls():
    """``shell32`` and ``user32`` with the signatures this module calls.

    The signatures are not decoration: without them ctypes passes and returns
    every handle as a 32-bit int, and an ``HWND`` or ``HICON`` above 4 GB is
    truncated into somebody else's handle.
    """
    shell32 = ctypes.WinDLL("shell32")
    user32 = ctypes.WinDLL("user32")

    shell32.SetCurrentProcessExplicitAppUserModelID.argtypes = [wintypes.LPCWSTR]
    shell32.SetCurrentProcessExplicitAppUserModelID.restype = HRESULT
    shell32.SHGetPropertyStoreForWindow.argtypes = [
        wintypes.HWND, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p),
    ]
    shell32.SHGetPropertyStoreForWindow.restype = HRESULT
    shell32.ExtractIconExW.argtypes = [
        wintypes.LPCWSTR, ctypes.c_int,
        ctypes.POINTER(wintypes.HICON), ctypes.POINTER(wintypes.HICON), wintypes.UINT,
    ]
    shell32.ExtractIconExW.restype = wintypes.UINT

    user32.SendMessageW.argtypes = [
        wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
    ]
    user32.SendMessageW.restype = wintypes.LPARAM
    user32.DestroyIcon.argtypes = [wintypes.HICON]
    user32.DestroyIcon.restype = wintypes.BOOL
    user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND, ctypes.POINTER(wintypes.DWORD),
    ]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    return SimpleNamespace(shell32=shell32, user32=user32)


def launcher_path(environ=None):
    """``OpenEmux.exe``, when this process was started by it; else ``None``."""
    if not IS_WINDOWS:
        return None
    raw = (os.environ if environ is None else environ).get(LAUNCHER_ENV)
    if not raw:
        return None
    path = Path(raw)
    return path if path.is_file() else None


def set_process_app_id(app_id):
    """Give the whole process an explicit AppUserModelID.

    Must run before the first window is created: the shell reads it when a
    window first appears on the taskbar and never again.
    """
    try:
        _check(
            _dlls().shell32.SetCurrentProcessExplicitAppUserModelID(app_id),
            "SetCurrentProcessExplicitAppUserModelID",
        )
    except _SHELL_ERRORS as exc:
        logger.warning("Could not set the Windows AppUserModelID: %s", exc)
        return False
    return True


def _com_method(obj, slot, prototype):
    """The method in ``slot`` of the COM object at address ``obj``."""
    vtable = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
    return prototype(vtable[slot])


def _property_store_for(hwnd):
    """The window's ``IPropertyStore``, as an address. The caller releases it."""
    store = ctypes.c_void_p()
    _check(
        _dlls().shell32.SHGetPropertyStoreForWindow(
            hwnd, ctypes.byref(IID_IPROPERTYSTORE), ctypes.pointer(store)
        ),
        "SHGetPropertyStoreForWindow",
    )
    if not store.value:
        raise OSError("SHGetPropertyStoreForWindow returned no store")
    return store.value


def _set_string(store, key, value):
    """Set ``key`` to the string ``value``, or clear it when ``value`` is None.

    The store copies the value, so the buffer only has to live for the call.
    """
    variant = PROPVARIANT()
    if value is not None:
        buffer = ctypes.create_unicode_buffer(value)
        variant.vt = VT_LPWSTR
        variant.pwszVal = ctypes.cast(buffer, ctypes.c_void_p).value
    set_value = _com_method(store, _SET_VALUE, SET_VALUE_PROTOTYPE)
    _check(
        set_value(store, ctypes.byref(key), ctypes.byref(variant)),
        f"IPropertyStore::SetValue({key.pid})",
    )


def _write_properties(hwnd, values):
    """Write ``{pid: value}`` into the window's store and commit it."""
    store = _property_store_for(hwnd)
    try:
        for pid, value in values.items():
            _set_string(store, _key(pid), value)
        _check(_com_method(store, _COMMIT, COMMIT_PROTOTYPE)(store), "IPropertyStore::Commit")
    finally:
        _com_method(store, _RELEASE, RELEASE_PROTOTYPE)(store)


def _destroy_icons(hwnd):
    user32 = _dlls().user32
    for icon in _window_icons.pop(hwnd, ()):
        user32.DestroyIcon(icon)


def _set_icons(hwnd, launcher):
    """Hand the window the icons out of ``OpenEmux.exe``'s resources."""
    dlls = _dlls()
    large = wintypes.HICON()
    small = wintypes.HICON()
    dlls.shell32.ExtractIconExW(
        str(launcher), 0, ctypes.pointer(large), ctypes.pointer(small), 1
    )
    icons = [icon for icon in (large.value, small.value) if icon]
    if not icons:
        raise OSError(f"no icon in {launcher}")
    _destroy_icons(hwnd)
    _window_icons[hwnd] = icons
    for slot, icon in ((ICON_BIG, large.value), (ICON_SMALL, small.value)):
        if icon:
            dlls.user32.SendMessageW(hwnd, WM_SETICON, slot, icon)


def apply_window_identity(hwnd, app_id, launcher):
    """Make ``hwnd`` an OpenEmux window as far as the shell is concerned.

    The icon and the properties are independent: a window that gets only one
    of them is still better off, so a failure in one does not skip the other.
    Returns whether both landed.
    """
    ok = True
    try:
        _set_icons(hwnd, launcher)
    except _SHELL_ERRORS as exc:
        logger.warning("Could not set the window icon from %s: %s", launcher, exc)
        ok = False
    try:
        _write_properties(hwnd, {
            PID_APP_USER_MODEL_ID: app_id,
            PID_RELAUNCH_COMMAND: f'"{launcher}"',
            PID_RELAUNCH_DISPLAY_NAME_RESOURCE: RELAUNCH_DISPLAY_NAME,
            PID_RELAUNCH_ICON_RESOURCE: f"{launcher},0",
        })
    except _SHELL_ERRORS as exc:
        logger.warning("Could not set the window's shell properties: %s", exc)
        ok = False
    return ok


def clear_window_identity(hwnd):
    """Undo :func:`apply_window_identity` before the window is destroyed.

    Microsoft requires the relaunch keys to be cleared while the window still
    exists, or the shell keeps stale entries for it.
    """
    ok = True
    try:
        _write_properties(hwnd, {
            PID_APP_USER_MODEL_ID: None,
            PID_RELAUNCH_COMMAND: None,
            PID_RELAUNCH_DISPLAY_NAME_RESOURCE: None,
            PID_RELAUNCH_ICON_RESOURCE: None,
        })
    except _SHELL_ERRORS as exc:
        logger.warning("Could not clear the window's shell properties: %s", exc)
        ok = False
    try:
        _destroy_icons(hwnd)
    except _SHELL_ERRORS as exc:
        logger.warning("Could not free the window icons: %s", exc)
        ok = False
    return ok


def find_toplevel_hwnds(pid):
    """The visible top-level windows of process ``pid``, in z-order.

    Read from the window manager rather than from GDK: PyGObject hands
    ``GdkWin32.Win32Surface.get_handle()`` back as an opaque pointer, and the
    ``GdkWin32`` typelib is one more thing the bundle's prune could drop.
    The hidden helper windows GDK keeps for itself are never visible.
    """
    try:
        user32 = _dlls().user32
        found = []

        def _collect(hwnd, _lparam):
            owner = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.pointer(owner))
            if owner.value == pid and user32.IsWindowVisible(hwnd):
                found.append(hwnd)
            return True

        user32.EnumWindows(WNDENUMPROC(_collect), 0)
    except _SHELL_ERRORS as exc:
        logger.warning("Could not list the app's windows: %s", exc)
        return []
    return found
