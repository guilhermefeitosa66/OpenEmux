"""What a bug report needs to know about the machine it came from.

Every value comes from a source that exists on every system it runs on, so a
report never depends on a tool the user may not have: on Linux the
distribution is read from ``/etc/os-release`` (the freedesktop standard every
systemd-era distribution ships), with ``/usr/lib/os-release`` and
``lsb_release`` behind it; neofetch and fastfetch are deliberately not used.
On Windows ``platform`` says everything.

Each probe is guarded: a report with one "unknown" is still a report, and
building one must never be the thing that crashes.
"""

import locale
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

from openemux import __version__
from openemux.core.paths import get_project_root, is_running_in_flatpak
from openemux.core.privacy import redact_home

OS_RELEASE_PATHS = (Path("/etc/os-release"), Path("/usr/lib/os-release"))

UNKNOWN = "unknown"


def _parse_os_release(text):
    fields = {}
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            fields[key.strip()] = value.strip().strip('"').strip("'")
    return fields


def distribution(paths=OS_RELEASE_PATHS, run=subprocess.run):
    """The distribution's own name for itself, version included."""
    if sys.platform == "win32":
        return f"Windows {platform.release()} ({platform.version()})"
    for path in paths:
        try:
            fields = _parse_os_release(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        name = fields.get("PRETTY_NAME") or " ".join(
            part for part in (fields.get("NAME"), fields.get("VERSION")) if part
        )
        if name:
            return name
    if shutil.which("lsb_release"):
        try:
            result = run(["lsb_release", "-ds"], capture_output=True, text=True, timeout=3)
            if result.stdout.strip():
                return result.stdout.strip().strip('"')
        except (OSError, subprocess.SubprocessError):
            pass
    return UNKNOWN


def desktop(environ=os.environ):
    """Desktop environment and session type, as the session announces them."""
    if sys.platform == "win32":
        return "Windows"
    name = environ.get("XDG_CURRENT_DESKTOP") or environ.get("DESKTOP_SESSION") or UNKNOWN
    session = environ.get("XDG_SESSION_TYPE") or (
        "wayland" if environ.get("WAYLAND_DISPLAY") else "x11" if environ.get("DISPLAY") else UNKNOWN
    )
    return f"{name} · {session.capitalize() if session != UNKNOWN else session}"


def install_format(environ=os.environ, project_root=None):
    """How this copy of OpenEmux was installed: the bugs differ by format."""
    if sys.platform == "win32":
        return "Windows"
    if is_running_in_flatpak():
        return "Flatpak"
    if environ.get("APPIMAGE"):
        return "AppImage"
    root = Path(project_root or get_project_root())
    if str(root).startswith("/opt/openemux"):
        return "Package (.deb / .rpm)"
    if str(root).startswith("/usr/"):
        return "Distribution package"
    if (root / ".git").exists():
        return "Built from source"
    return UNKNOWN


def toolkit_versions(gtk=None, adwaita=None):
    """The toolkit line. The UI passes the versions it loaded: core never imports GTK."""
    parts = []
    if gtk:
        parts.append(f"GTK {gtk}")
    if adwaita:
        parts.append(f"libadwaita {adwaita}")
    parts.append(f"Python {platform.python_version()}")
    return " · ".join(parts)


def retroarch(binary=None, run=subprocess.run):
    """RetroArch's own version line, and where it was found."""
    binary = binary or shutil.which("retroarch")
    if not binary:
        return "not found on PATH"
    try:
        result = run([binary, "--version"], capture_output=True, text=True, timeout=5)
        # The first line varies by build ("Frontend for libretro -- v1.19.1"
        # on one, "Version: 1.19.1" on another); the version number does not.
        match = re.search(r"\bv?(\d+\.\d+\.\d+)", (result.stdout or "") + (result.stderr or ""))
        if match:
            return f"{match.group(1)} · {binary}"
    except (OSError, subprocess.SubprocessError):
        pass
    return f"version {UNKNOWN} · {binary}"


def language():
    try:
        return locale.getlocale()[0] or os.environ.get("LANG") or UNKNOWN
    except ValueError:
        return os.environ.get("LANG") or UNKNOWN


def collect(gtk=None, adwaita=None, retroarch_binary=None):
    """Every fact as ordered (label, value) pairs, for the dialog and the copy.

    Each value has the home directory written as ``~`` -- a RetroArch the user
    keeps under their home would otherwise put their name in the report.
    """
    facts = [
        ("OpenEmux", f"{__version__} · {install_format()}"),
        ("System", distribution()),
        ("Kernel", f"{platform.system()} {platform.release()} · {platform.machine()}"),
        ("Desktop", desktop()),
        ("Toolkit", toolkit_versions(gtk, adwaita)),
        ("RetroArch", retroarch(retroarch_binary)),
        ("Language", language()),
    ]
    return [(label, redact_home(value)) for label, value in facts]


def as_text(facts):
    width = max(len(label) for label, _ in facts)
    return "\n".join(f"{label.ljust(width)}  {value}" for label, value in facts)
