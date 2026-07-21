import os
import shutil
from pathlib import Path

# Pre-rename data dir. The app was renamed Opemux -> OpenEmux; existing installs
# keep their config, library index, playlists and input profiles under this path.
LEGACY_CONFIG_DIR_NAME = ".opemux"
CONFIG_DIR_NAME = ".openemux"


def migrate_legacy_config_dir():
    """One-time migration of the pre-rename ``~/.opemux`` data dir to ``~/.openemux``.

    Runs on startup before anything touches the config directory, so an install
    that predates the OpenEmux rename keeps its library, playlists, input
    profiles and config. Uses ``Path.home()`` to match ``DEFAULT_CONFIG_DIR``.

    Two steps: (1) move the whole data dir when only the legacy one exists;
    (2) repair absolute paths baked into ``config.yaml`` that still point at the
    legacy dir (e.g. ``library.playlists_dir``), so a moved install resolves its
    data under the new location instead of recreating an empty legacy dir.
    """
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
    config_file.write_text(text.replace(needle, str(current)), encoding="utf-8")


def is_running_in_appimage():
    return bool(os.environ.get("APPIMAGE") or os.environ.get("APPDIR"))


def get_real_home():
    """The user's real home directory.

    Kept as its own helper (rather than inlining ``Path.home()``) because the
    ROM library and RetroArch data are resolved against it from several
    modules, and ``$HOME`` is not always the passwd entry.
    """
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

    return Path(__file__).resolve().parents[3]


def resolve_project_path(path_value):
    path = Path(path_value).expanduser()
    if path.is_absolute():
        return path
    return get_project_root() / path
