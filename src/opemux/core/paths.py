import os
from pathlib import Path


def is_running_in_appimage():
    return bool(os.environ.get("APPIMAGE") or os.environ.get("APPDIR"))


def is_running_in_flatpak():
    """True when running inside a Flatpak sandbox."""
    return bool(os.environ.get("FLATPAK_ID")) or os.path.exists("/.flatpak-info")


def get_real_home():
    """The user's real home directory.

    Inside a Flatpak sandbox ``$HOME`` points at the per-app private dir
    (``~/.var/app/<id>``), while the user's real home — where the ROM library and
    the RetroArch Flatpak's data live — is the passwd entry, reachable because the
    manifest grants ``--filesystem=home``. Outside Flatpak this equals
    ``Path.home()``.
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
    env_root = os.environ.get("OPEMUX_PROJECT_ROOT")
    if env_root:
        return Path(env_root).expanduser().resolve()

    appdir = os.environ.get("APPDIR")
    if appdir:
        bundled_root = Path(appdir) / "usr" / "lib" / "opemux"
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
