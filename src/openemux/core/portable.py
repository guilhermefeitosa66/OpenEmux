"""Keep everything a portable Windows install writes inside its own folder.

The ``.zip`` ships a marker beside ``OpenEmux.exe`` (see
:func:`openemux.core.paths.portable_root`). OpenEmux's own data roots follow
the marker in ``core.paths``; this module covers what the app does not decide
itself -- where GLib, GTK, fontconfig and ``tempfile`` write. Each of them
resolves a per-user directory in the profile unless the environment says
otherwise, so the environment says otherwise (issue #766).

Applied by ``main.prepare_process()``, before the GTK stack is imported: GLib
reads these variables once, when it first needs them. RetroArch inherits them
too, which is harmless -- the bundled copy runs portable and keeps its own
paths.
"""

import os
import tempfile
from html import escape

from openemux.core.atomic_write import atomic_write_text
from openemux.core.paths import PORTABLE_DATA_DIR, portable_root

#: ``environment variable -> folder under data/``. GLib honours the four XDG
#: variables on Windows as well, ahead of the shell's own folders.
XDG_DIRS = {
    "XDG_CONFIG_HOME": "config",
    "XDG_DATA_HOME": "share",
    "XDG_CACHE_HOME": "cache",
    "XDG_STATE_HOME": "state",
}

#: ``%TEMP%`` is ``%LOCALAPPDATA%\\Temp``; Python's ``tempfile`` and GLib's
#: ``g_get_tmp_dir()`` both read these two.
TEMP_VARIABLES = ("TEMP", "TMP")
TEMP_DIR = "tmp"

#: The bundle's own fontconfig configuration, relative to the install root.
BUNDLE_FONTS_CONF = os.path.join("etc", "fonts", "fonts.conf")

#: MSYS2's ``fonts.conf`` names ``LOCAL_APPDATA_FONTCONFIG_CACHE`` as its first
#: ``<cachedir>`` -- resolved through the shell API, not an environment
#: variable -- and fontconfig writes to the first one it can. A wrapper that
#: lists the portable cache first and then includes the bundle's file keeps
#: every font, rule and directory the bundle had while moving the writes.
FONTS_CONF_TEMPLATE = """<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "urn:fontconfig:fonts.dtd">
<!-- Written by OpenEmux for its portable mode; refreshed when the folder moves. -->
<fontconfig>
  <cachedir>{cache}</cachedir>
  <include ignore_missing="yes">{include}</include>
</fontconfig>
"""


def apply_portable_environment(environ=None):
    """Point every per-user directory the runtime resolves at ``data/``.

    Returns the portable root, or ``None`` when this is not a portable install
    or its folder cannot be written -- in which case the environment is left
    exactly as it was, and the app starts the way it always has.
    """
    root = portable_root()
    if root is None:
        return None
    environ = os.environ if environ is None else environ
    data = root / PORTABLE_DATA_DIR
    wanted = {name: data / folder for name, folder in XDG_DIRS.items()}
    for name in TEMP_VARIABLES:
        wanted[name] = data / TEMP_DIR
    try:
        for directory in set(wanted.values()):
            directory.mkdir(parents=True, exist_ok=True)
        fonts_conf = _write_fonts_conf(root, wanted["XDG_CACHE_HOME"])
    except OSError:
        # A read-only stick or a zip opened in place. Logging is not set up
        # yet, and refusing to start over a cache location would be worse.
        return None
    for name, directory in wanted.items():
        environ[name] = str(directory)
    if fonts_conf is not None:
        environ["FONTCONFIG_FILE"] = str(fonts_conf)
    # tempfile resolves its directory once and keeps it; anything that asked
    # before this point would otherwise go on writing to the profile.
    tempfile.tempdir = None
    return root


def _write_fonts_conf(root, cache_home):
    """The fontconfig wrapper, or ``None`` when the bundle has no fontconfig."""
    bundled = root / BUNDLE_FONTS_CONF
    if not bundled.is_file():
        return None
    target = cache_home / "fonts.conf"
    contents = FONTS_CONF_TEMPLATE.format(
        cache=escape(str(cache_home / "fontconfig"), quote=False),
        include=escape(str(bundled), quote=False),
    )
    try:
        current = target.read_text(encoding="utf-8")
    except OSError:
        current = None
    if current != contents:
        atomic_write_text(target, contents)
    return target
