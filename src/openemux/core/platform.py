"""Where OpenEmux answers "which operating system is this?".

Before issue #118 the codebase had no platform branching at all -- every OS
assumption was inlined at the point of use. This module is the single place
those questions get answered, so a port does not mean scattering ``sys.platform``
checks through the core.

It imports nothing from ``openemux`` on purpose. ``paths``, ``config`` and the
pre-``gi`` section of ``main`` all need it, and a dependency in the other
direction would make that a cycle.
"""

import os
import subprocess
import sys
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"

#: File extension of a libretro core on this platform. The catalogs in
#: ``systems.py`` and ``bios_catalog.py`` spell every core ``.so`` -- that stays
#: the canonical form, and the extension is resolved at lookup time instead
#: (see :func:`normalize_core_filename`). Editing 50+ data literals per platform
#: would be the same information written twice.
CORE_SUFFIX = ".dll" if IS_WINDOWS else ".so"

#: Every core extension we recognize, regardless of the host. A user can point
#: the app at a directory holding either, so parsing must accept both even
#: though only one is ever downloaded.
CORE_SUFFIXES = (".so", ".dll")

#: Path segment of the RetroArch buildbot that serves cores for this platform:
#: https://buildbot.libretro.com/nightly/<BUILDBOT_OS>/x86_64/latest/
BUILDBOT_OS = "windows" if IS_WINDOWS else "linux"

#: Relative path, from the project root, of the vendored RetroArch. Managed by
#: scripts/vendor_retroarch.py -- see vendors/manifest.json.
VENDORED_RETROARCH = (
    "vendors/RetroArch-Win64/retroarch.exe"
    if IS_WINDOWS
    else "vendors/RetroArch-Linux-x86_64.AppImage"
)


def normalize_core_filename(filename):
    """``filename`` with its core extension corrected for this platform.

    ``"snes9x_libretro.so"`` becomes ``"snes9x_libretro.dll"`` on Windows and is
    returned unchanged on Linux. Anything that does not already end in a known
    core extension passes through untouched, so an absolute path a user chose,
    or a name we do not recognize, is never rewritten behind their back.
    """
    if not filename:
        return filename
    for suffix in CORE_SUFFIXES:
        if filename.endswith(suffix):
            return filename[: -len(suffix)] + CORE_SUFFIX
    return filename


def core_stem(filename):
    """``filename`` without its core extension.

    Replaces the ``filename[:-3]`` arithmetic that predates Windows support:
    that hard-codes the length of ``".so"`` and silently truncates a character
    too few from ``".dll"``, which would key every core's ``.info`` lookup off
    ``"snes9x_libretro."``.
    """
    if not filename:
        return filename
    for suffix in CORE_SUFFIXES:
        if filename.endswith(suffix):
            return filename[: -len(suffix)]
    return filename


def cfg_path(value):
    """``value`` as RetroArch wants a path inside a ``.cfg`` file: forward slashes.

    RetroArch treats a backslash inside a quoted config value as an escape, so
    ``savestate_directory = "C:\\Users\\me\\.openemux\\states"`` is read with
    ``\\U``, ``\\m`` and ``\\.`` consumed as escapes and the directory silently
    lands somewhere else. Saves go missing and the app looks like it lost them.

    Converted on every platform, not just Windows. A backslash in a cfg value is
    wrong everywhere for the same reason, and an unconditional rule is one the
    Linux test suite can actually verify.
    """
    return str(value).replace("\\", "/")


def default_config_dir():
    """The user's OpenEmux data directory.

    Stays ``~/.openemux`` on Windows too (``C:\\Users\\<user>\\.openemux``).
    ``%APPDATA%`` is the native convention and may be worth moving to later, but
    that is a migration with real risk to existing libraries, and it buys
    nothing for a first Windows release.
    """
    return Path.home() / ".openemux"


def user_retroarch_dirs():
    """Directories where a *user-installed* RetroArch keeps its cores.

    Search only -- OpenEmux never writes here. A Windows user who already has
    RetroArch must find their install untouched after trying OpenEmux, which is
    an acceptance criterion of issue #118; downloaded cores go to the bundled
    copy instead (see :func:`bundled_core_dir`).
    """
    if IS_WINDOWS:
        appdata = os.environ.get("APPDATA")
        if not appdata:
            return []
        return [Path(appdata) / "RetroArch" / "cores"]
    # Linux keeps its equivalents in retroarch_launcher/cores, which know about
    # the Flatpak layout as well; nothing to add here.
    return []


def bundled_core_dir(project_root):
    """Where cores for the vendored RetroArch live, or ``None`` when not bundled.

    The Windows build runs in portable mode -- a ``retroarch.cfg`` beside
    ``retroarch.exe`` -- so it reads its cores from its own directory rather
    than from ``%APPDATA%``. That is what keeps a user's own install out of it.
    """
    if not IS_WINDOWS:
        return None
    return Path(project_root) / "vendors" / "RetroArch-Win64" / "cores"


def popen_kwargs():
    """Extra ``subprocess.Popen`` keywords for launching RetroArch.

    ``CREATE_NO_WINDOW`` stops a console window from flashing up behind the
    game every time a ROM starts.
    """
    if not IS_WINDOWS:
        return {}
    return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)}
