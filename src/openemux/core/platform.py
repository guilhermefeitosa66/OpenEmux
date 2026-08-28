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
import platform
import subprocess
import sys
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"


def _machine(raw=None):
    """The CPU architecture, spelled the way the artifacts spell it.

    ``platform.machine()`` answers with whatever the OS calls it -- ``AMD64``
    on Windows, ``x86_64`` on Linux, ``arm64`` on macOS and on some ARM
    distributions -- and every one of those means one of two things here.
    Normalising once is what lets a URL, a filename and a library directory all
    be built from the same token instead of each carrying its own spelling.
    """
    name = (raw if raw is not None else platform.machine()).strip().lower()
    if name in ("amd64", "x86_64", "x64"):
        return "x86_64"
    if name in ("arm64", "aarch64", "armv8l"):
        return "aarch64"
    return name or "x86_64"


#: This machine's architecture: ``x86_64`` or ``aarch64`` (issue #119).
MACHINE = _machine()

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
#: https://buildbot.libretro.com/nightly/<BUILDBOT_OS>/<BUILDBOT_ARCH>/latest/
BUILDBOT_OS = "windows" if IS_WINDOWS else "linux"

#: The other half of that path. The buildbot serves 217 cores for x86_64 and
#: 153 for aarch64, so an ARM install pointed at the x86_64 tree downloads
#: cores that can never load -- and says nothing, because they download fine.
BUILDBOT_ARCH = MACHINE

#: Every buildbot path OpenEmux might have written into a config, so a config
#: carrying another platform's default can be recognised as *a default* rather
#: than as a choice the user made (see config.migrate_cores_base_url).
BUILDBOT_OSES = ("linux", "windows")
BUILDBOT_ARCHES = ("x86_64", "aarch64")

#: Relative path, from the project root, of the vendored RetroArch. Managed by
#: scripts/vendor_retroarch.py -- see vendors/manifest.json.
#:
#: A binary inside a portable directory on both platforms. RetroArch dlopens its
#: cores and resolves libGL and the host's audio stack from the host, so neither
#: build is a single file: the Windows one is retroarch.exe plus its DLLs, and
#: the Linux one is this binary plus 56 libraries it finds through
#: RUNPATH=$ORIGIN/../lib. Vendoring the Linux tree rather than the AppImage
#: upstream wraps it in is what freed the packages from FUSE (issue #328).
#:
#: Architecture-aware on Linux: an x86_64 build on an ARM machine is not a
#: RetroArch that failed to launch, it is a file the kernel refuses to execute,
#: and the launcher has a fallback chain for the case where none is vendored
#: (retroarch_launcher._resolve_retroarch_binary).
VENDORED_RETROARCH = (
    "vendors/RetroArch-Win64/retroarch.exe"
    if IS_WINDOWS
    else f"vendors/RetroArch-Linux-{MACHINE}/usr/bin/retroarch"
)

#: What ``VENDORED_RETROARCH`` used to be, for a config.yaml written before
#: issue #328. Both architectures, because a config carried between machines
#: names whichever one wrote it; see config.migrate_retroarch_binary.
LEGACY_VENDORED_RETROARCH = (
    ()
    if IS_WINDOWS
    else tuple(
        f"vendors/RetroArch-Linux-{arch}.AppImage" for arch in ("x86_64", "aarch64")
    )
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
