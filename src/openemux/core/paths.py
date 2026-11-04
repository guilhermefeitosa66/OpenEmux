import functools
import os
import shutil
from pathlib import Path

from openemux.core.atomic_write import atomic_write_text
from openemux.core.platform import IS_WINDOWS

#: How the ``.list`` files encode a ROM path.
#:
#: A filename is bytes, not text. Old dumps routinely carry cp437 or Shift-JIS
#: names, and Python hands those back decoded with ``surrogateescape`` --
#: ``'bad\udcffname.nes'``. Writing that through a strict UTF-8 encoder raises
#: ``UnicodeEncodeError: surrogates not allowed`` *mid-file*, which is what
#: killed the scan worker outright and left scanning disabled for the rest of
#: the session (issue #214). The same handler on the way back out turns the
#: bytes into exactly the name the filesystem has, so such a ROM round-trips
#: and plays like any other.
PATH_ERRORS = "surrogateescape"


def display_text(value):
    """``value`` rendered as text GTK can actually take.

    GTK strings must be valid UTF-8. A filename carrying a non-UTF-8 byte
    reaches us as a lone surrogate, and handing that to a label or a tooltip
    raises ``UnicodeEncodeError`` deep inside PyGObject -- which took the whole
    console page down with it: selecting the console rendered nothing at all
    (issue #214). The offending bytes are shown escaped instead. The name stays
    recognisable, and the path itself is never touched, so the game launches.
    """
    return str(value).encode("utf-8", "backslashreplace").decode("utf-8")

# Pre-rename data dir. The app was renamed Opemux -> OpenEmux; existing installs
# keep their config, library index, playlists and input profiles under this path.
LEGACY_CONFIG_DIR_NAME = ".opemux"
CONFIG_DIR_NAME = ".openemux"

#: Names of the per-store files that sit beside ``config.yaml``. Every one of
#: them used to be spelled out as ``Path.home() / ".openemux" / ...`` in the
#: module that owned it -- nine independent derivations of the same directory
#: (issue #239). A ``ConfigManager`` pointed elsewhere, as the tests point it,
#: still read and wrote play history and per-ROM core overrides under the
#: *real* home; they follow the chosen config dir now.
STORE_FILENAMES = {
    "config": "config.yaml",
    "playlists": "playlists",
    "input": "input",
    "runtime": "runtime",
    "states": "states",
    "bios": "bios",
    "shaders": "shaders.config",
    "cores": "cores.config",
    "cartridge_colors": "cartridge_colors.config",
    "core_options": "core_options.config",
    "achievements": "cheevos.config",
    "play_history": "play_history.json",
    # Where the library was left (issue #383). Its own file because it is
    # written on every view change; config.yaml is not.
    "session": "session.json",
    "artwork_index": "artwork-index",
    "cartridge_cache": "cache/cartridges",
    # Custom bezel images, one per console (issue #507).
    "bezels": "bezels",
    # Share nearby's device identity: id, key and certificate (issue #587).
    "share": "share",
}


#: The file the Windows portable ``.zip`` ships beside ``OpenEmux.exe`` and the
#: installer never does (issue #766). Its presence is the whole question.
PORTABLE_MARKER = "portable.txt"

#: The folder, beside the marker, that holds everything a portable install
#: writes. One name so a user can see -- and back up, or wipe -- all of it.
PORTABLE_DATA_DIR = "data"


def portable_root():
    """The folder of a portable Windows install, or ``None``.

    Portable means the ``.zip``: :data:`PORTABLE_MARKER` sits in the project
    root, which the launcher exports as the folder holding ``OpenEmux.exe``.
    Without it -- the installer, a source checkout under MSYS2 -- the app keeps
    the user-profile paths it always had. Linux never asks the disk at all.
    """
    if not IS_WINDOWS:
        return None
    return _portable_root_at(str(get_project_root()))


@functools.lru_cache(maxsize=None)
def _portable_root_at(root):
    """Looked up once per process: the marker does not come and go mid-run."""
    root = Path(root)
    return root if (root / PORTABLE_MARKER).is_file() else None


def portable_data_dir(name):
    """``<portable root>/data/<name>``, or ``None`` off a portable install."""
    root = portable_root()
    if root is None:
        return None
    return root / PORTABLE_DATA_DIR / name


def default_config_dir():
    """Where the app keeps its own data.

    The one place that answers it. ``XDG_CONFIG_HOME`` and ``XDG_DATA_HOME``
    are deliberately *not* consulted yet -- moving an existing install's data
    is a migration, not a rename -- but when they are, this is the single site
    that changes, and ``migrate_legacy_config_dir`` above is the pattern. A
    portable Windows install keeps it inside its own folder (issue #766).
    """
    portable = portable_data_dir("openemux")
    if portable is not None:
        return portable
    return Path.home() / CONFIG_DIR_NAME


def default_roms_path():
    """The ROM folder a fresh config starts with.

    ``~/games/roms`` in the *real* home (a Flatpak's ``$HOME`` is its sandbox),
    or the portable folder's own ``data/roms``.
    """
    portable = portable_data_dir("roms")
    if portable is not None:
        return portable
    return get_real_home() / "games" / "roms"


def store_path(name, config_dir=None):
    """The default path of one store, under ``config_dir`` or the app's own.

    ``name`` is a key of :data:`STORE_FILENAMES`; an unknown one is a typo,
    and raising beats silently writing to a path nobody meant.
    """
    base = Path(config_dir) if config_dir is not None else default_config_dir()
    return base / STORE_FILENAMES[name]


def bytecode_cache_dir():
    """Where an install that cannot write beside its own sources caches bytecode.

    Deliberately not under :func:`default_config_dir`, and deliberately not
    under :func:`get_real_home`. This is derived data: rebuilt from the sources
    whenever it is missing, correct to delete at any moment, and worthless to
    back up -- which is the definition of ``XDG_CACHE_HOME``. Inside a Flatpak
    that resolves to the sandbox's own cache, so ``flatpak uninstall
    --delete-data`` takes it away with everything else the app left behind,
    and no bytecode of a sandboxed install is left sitting in the real home.
    """
    return user_cache_dir() / "openemux" / "bytecode"


def user_cache_dir():
    """The per-user cache root: ``%LOCALAPPDATA%``, ``$XDG_CACHE_HOME`` or ``~/.cache``.

    A portable install's is ``data/cache`` inside its folder, which is also
    what ``main.prepare_process`` points ``XDG_CACHE_HOME`` at, so GLib's
    answer and this one agree.
    """
    portable = portable_data_dir("cache")
    if portable is not None:
        return portable
    if IS_WINDOWS:
        base = os.environ.get("LOCALAPPDATA")
        return Path(base) if base else Path.home() / "AppData" / "Local"
    base = os.environ.get("XDG_CACHE_HOME")
    return Path(base) if base else Path.home() / ".cache"


def migrate_legacy_config_dir():
    """One-time migration of the pre-rename ``~/.opemux`` data dir to ``~/.openemux``.

    Runs on startup before anything touches the config directory, so an install
    that predates the OpenEmux rename keeps its library, playlists, input
    profiles and config. Uses ``Path.home()`` to match
    :func:`default_config_dir`.

    Two steps: (1) move the whole data dir when only the legacy one exists;
    (2) repair absolute paths baked into ``config.yaml`` that still point at the
    legacy dir (e.g. ``library.playlists_dir``), so a moved install resolves its
    data under the new location instead of recreating an empty legacy dir.

    Not for a portable install: its data was never in the profile, and moving
    a folder there is exactly what it promises not to do (issue #766).
    """
    if portable_root() is not None:
        return
    home = Path.home()
    legacy = home / LEGACY_CONFIG_DIR_NAME
    current = home / CONFIG_DIR_NAME
    if legacy.is_dir() and not current.exists():
        try:
            legacy.rename(current)
        except OSError:
            shutil.move(str(legacy), str(current))
    _repair_legacy_paths_in_config(legacy, current)


def _repair_legacy_paths_in_config(legacy, current):
    """Rewrite absolute ``legacy`` paths stored inside ``current/config.yaml``.

    ``.opemux`` is not a substring of ``.openemux``, so a plain text replace of
    the legacy dir prefix is unambiguous and idempotent (no-op once repaired).
    """
    config_file = current / "config.yaml"
    if not config_file.is_file():
        return
    try:
        text = config_file.read_text(encoding="utf-8")
    except OSError:
        return
    needle = str(legacy)
    if needle not in text:
        return
    atomic_write_text(config_file, text.replace(needle, str(current)))


def is_running_in_appimage():
    return bool(os.environ.get("APPIMAGE") or os.environ.get("APPDIR"))


def is_running_in_flatpak():
    """True when running inside a Flatpak sandbox."""
    return bool(os.environ.get("FLATPAK_ID")) or os.path.exists("/.flatpak-info")


def get_real_home():
    """The user's real home directory.

    Inside a Flatpak sandbox ``$HOME`` points at the per-app private dir
    (``~/.var/app/<id>``), while the user's real home — where the ROM library
    and the RetroArch Flatpak's data live — is the passwd entry, reachable
    because the manifest grants ``--filesystem=home``. Outside Flatpak this
    equals ``Path.home()``.
    """
    if is_running_in_flatpak():
        try:
            import pwd

            pw = pwd.getpwuid(os.getuid())
            if pw and pw.pw_dir:
                return Path(pw.pw_dir)
        except Exception:
            pass
    return Path.home()


def get_project_root():
    env_root = os.environ.get("OPENEMUX_PROJECT_ROOT")
    if env_root:
        return Path(env_root).expanduser().resolve()

    appdir = os.environ.get("APPDIR")
    if appdir:
        bundled_root = Path(appdir) / "usr" / "lib" / "openemux"
        if bundled_root.exists():
            return bundled_root.resolve()

    if is_running_in_flatpak():
        return Path("/app")

    return Path(__file__).resolve().parents[3]


def resolve_project_path(path_value):
    path = Path(path_value).expanduser()
    if path.is_absolute():
        return path
    return get_project_root() / path
