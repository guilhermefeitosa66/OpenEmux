import os
import sys
import logging
import importlib.util
import traceback
from pathlib import Path
import shutil

from openemux.core.paths import (
    bytecode_cache_dir,
    get_project_root,
    is_running_in_appimage,
    is_running_in_flatpak,
    migrate_legacy_config_dir,
)
from openemux.core.platform import IS_WINDOWS
from openemux.core.startup_logging import append_startup_error, configure_startup_logging


def _ensure_gtk_typelibs():
    """Make GTK4/Adwaita typelibs resolvable when the host ships the runtime
    libraries but not the GObject-introspection typelibs.

    Some distros (e.g. Linux Mint) install ``libgtk-4-1`` / ``libadwaita-1-0``
    yet leave ``gir1.2-gtk-4.0`` / ``gir1.2-adw-1`` out, so ``gi.require_version``
    fails even though the shared libraries are present. When that happens, fall
    back to the typelibs vendored in ``AppDir/`` (same GTK/Adw versions), pointed
    to via ``GI_TYPELIB_PATH`` which GObject-introspection reads at lookup time.

    No-op inside the AppImage and when the system already provides the typelibs.
    Installing ``gir1.2-gtk-4.0`` / ``gir1.2-adw-1`` (``make install-sys-deps``)
    remains the recommended system-wide setup.

    Linux-only. On Windows the typelibs sit inside the MSYS2 prefix (or the
    shipped bundle, where the launcher sets GI_TYPELIB_PATH), and every path
    probed below is meaningless.
    """
    if IS_WINDOWS or is_running_in_appimage():
        return

    system_dirs = [
        "/usr/lib/x86_64-linux-gnu/girepository-1.0",
        "/usr/lib64/girepository-1.0",
        "/usr/lib/girepository-1.0",
    ]
    if any(os.path.exists(os.path.join(d, "Gtk-4.0.typelib")) for d in system_dirs):
        return  # system typelibs already available

    try:
        project_root = Path(get_project_root())
    except Exception:
        return

    candidate = project_root / "AppDir" / "usr" / "lib" / "x86_64-linux-gnu" / "girepository-1.0"
    if (candidate / "Gtk-4.0.typelib").exists() and (candidate / "Adw-1.typelib").exists():
        existing = os.environ.get("GI_TYPELIB_PATH", "")
        parts = [str(candidate)] + ([existing] if existing else [])
        os.environ["GI_TYPELIB_PATH"] = os.pathsep.join(parts)
        logging.getLogger(__name__).info(
            "Using vendored GTK typelibs from %s (install gir1.2-gtk-4.0 / "
            "gir1.2-adw-1 for a system-wide setup)",
            candidate,
        )


def _configure_gtk_renderer():
    """Pick a crash-safe GSK renderer default for fragile graphics stacks.

    GTK4's default GL/Vulkan (ngl) renderer can hard-crash (SIGSEGV, no Python
    traceback) at window realization when the AppImage's bundled GTK stack runs
    against the host's own GL/Vulkan drivers -- a common failure on fresh
    Debian/Mesa combos. The Cairo software renderer sidesteps every GPU-driver
    mismatch and is more than adequate for OpenEmux's 2D cover-grid UI.

    Only applied inside the AppImage and only when the user has not already
    chosen a renderer, so a working setup can still opt back in with, e.g.,
    GSK_RENDERER=ngl (or gl / vulkan).
    """
    if is_running_in_appimage() and not os.environ.get("GSK_RENDERER"):
        os.environ["GSK_RENDERER"] = "cairo"


def _ensure_pixbuf_loaders():
    """Windows: build gdk-pixbuf's loader cache before anything decodes an image.

    Has to happen before ``gi.repository`` is imported -- gdk-pixbuf reads
    GDK_PIXBUF_MODULE_FILE once, when it initialises -- which is what puts it
    in this function rather than in the application. See
    ``core/pixbuf_loaders`` for why the cache cannot be written at build time.
    """
    if not IS_WINDOWS:
        return
    from openemux.core.pixbuf_loaders import ensure_loaders_cache

    try:
        ensure_loaders_cache(get_project_root())
    except Exception:  # noqa: BLE001 - a blank cover must not stop start-up
        logging.getLogger(__name__).warning(
            "gdk-pixbuf: preparing the loader cache failed", exc_info=True
        )


#: Whether prepare_process() has already run in this process.
_prepared = False


def _redirect_bytecode_cache(package_dir=None):
    """Give the interpreter somewhere writable to keep this install's bytecode.

    The .deb and .rpm install to ``/opt/openemux``, which the user running the
    app cannot write. CPython still tries to put ``__pycache__`` beside the
    sources, fails, and silently falls back to compiling in memory -- so every
    launch reparses and recompiles the whole app, roughly 36k lines across 98
    modules, and throws the result away at exit (issue #364). Pointing
    ``sys.pycache_prefix`` at the user's cache directory gives that work a
    place to land, and it is paid once instead of always.

    Redirecting is per-interpreter for free: CPython names each file
    ``<module>.cpython-<version>.pyc``, so a machine that moves from Python
    3.12 to 3.13 recompiles once and the two caches sit side by side without
    ever being mistaken for each other. That is the whole reason the packages
    cannot simply ship bytecode: one .deb serves Ubuntu 24.04 through 26.04,
    whose interpreters do not agree on the magic number.

    Deliberately narrow -- it stands down in three cases:

    * **The tree is writable.** A source checkout, `make run` and the devbox
      cache beside the sources the way every Python developer expects, and no
      surprise directory appears under ``~/.cache``.
    * **The install already carries bytecode for this interpreter.** The
      AppImage, the Flatpak and the Windows bundle each pin the interpreter
      they run, so their builds compile ahead of time and the cache is valid
      before the first launch -- there is nothing left to redirect, and
      redirecting would *hide* what the build produced.
    * **The user has already decided**, through ``PYTHONPYCACHEPREFIX`` or
      ``PYTHONDONTWRITEBYTECODE``.
    """
    if sys.dont_write_bytecode or sys.pycache_prefix is not None:
        return
    # ``package_dir`` is the seam the tests use; nothing else passes it.
    package_dir = Path(package_dir) if package_dir else Path(__file__).resolve().parent
    if os.access(package_dir, os.W_OK):
        return
    try:
        if os.path.exists(importlib.util.cache_from_source(str(package_dir / "main.py"))):
            return
    except (NotImplementedError, ValueError):
        # No bytecode path for this source (a frozen or namespace loader).
        # Nothing to look for, and nothing that says the redirect is wrong.
        pass
    try:
        cache_dir = bytecode_cache_dir()
        cache_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        # A read-only home, a full disk, an unusual sandbox. Recompiling every
        # launch is slow; refusing to start over a *cache* would be worse.
        return
    sys.pycache_prefix = str(cache_dir)


def prepare_process():
    """Everything that has to happen before the GTK stack is imported.

    Deliberately *not* run at import time. It used to be five bare calls at
    module level, so importing anything at all out of ``main`` -- which two
    test files do -- migrated the developer's real config directory, read
    their real config, redirected the root logger into a FileHandler on
    ``~/.openemux/runtime/openemux_startup.log`` and replaced
    ``sys.excepthook`` and ``threading.excepthook`` for the whole process
    (issue #244).

    Runs once per process. ``configure_startup_logging`` uses
    ``force=True``, so a second call would swap the root handlers out and log
    the start-up context line again -- and calling it after GTK is imported is
    too late for the two environment variables set here anyway.
    """
    global _prepared
    if _prepared:
        return
    _prepared = True
    # First: everything below this line imports, and each import that lands
    # before the redirect is one more module the packaged install recompiles
    # on every launch.
    _redirect_bytecode_cache()
    _configure_gtk_renderer()
    # Before logging: the start-up log lives in the config dir, which a legacy
    # one may still be on its way to.
    migrate_legacy_config_dir()
    configure_startup_logging()
    _ensure_gtk_typelibs()
    _ensure_pixbuf_loaders()


def build_application():
    """Prepare the process, then hand back the application object.

    The GTK import and the application class live in ``openemux.app``, reached
    only from here: importing ``gi.repository.Gtk`` runs ``Gtk.init()``, which
    *opens the display*, so what the preparation puts in the environment
    (``GSK_RENDERER``) has to be there before that import rather than after.
    """
    prepare_process()
    from openemux.app import OpenEmuxApplication

    return OpenEmuxApplication()


APP_ID = "io.github.guilhermefeitosa66.OpenEmux"

#: Prefixes the .deb/.rpm install into. A project root under one of these means
#: the app is running from a package rather than from a source checkout.
SYSTEM_INSTALL_PREFIXES = ("/opt/", "/usr/")


def _is_packaged_install(project_root):
    # SYSTEM_INSTALL_PREFIXES are POSIX paths, and the string concat below
    # assumes a "/" separator, so neither means anything on Windows. There the
    # bundle launcher says so explicitly instead.
    if IS_WINDOWS:
        return bool(os.environ.get("OPENEMUX_PACKAGED"))
    root = f"{Path(project_root).resolve()}/"
    return root.startswith(SYSTEM_INSTALL_PREFIXES)


def _remove_generated_desktop_entry():
    """Drop a user-level entry a previous source run wrote, if it is still ours.

    ``~/.local/share/applications`` takes precedence over
    ``/usr/share/applications``, so an entry left behind by running from a
    checkout shadows the one a .deb/.rpm installs -- the menu then points at
    the developer tree (or at nothing, once that tree moves) instead of the
    installed app. Only a file that still matches what we generate is removed,
    so a hand-written entry is never touched.
    """
    desktop_target = Path.home() / ".local" / "share" / "applications" / f"{APP_ID}.desktop"
    try:
        if not desktop_target.exists():
            return
        content = desktop_target.read_text(encoding="utf-8")
        if "Name=OpenEmux" in content and "main.py" in content:
            desktop_target.unlink()
            logging.getLogger(__name__).info(
                "removed stale user desktop entry %s (packaged install owns it now)",
                desktop_target,
            )
    except OSError:
        pass


def _ensure_desktop_integration():
    # freedesktop .desktop entries mean nothing on Windows, and a Start Menu
    # shortcut is the installer's job -- an app run from a source checkout has
    # no business writing one.
    if IS_WINDOWS:
        return

    project_root = get_project_root()

    # A packaged install ships its own desktop file and icon. Writing a
    # user-level copy would shadow the package's entry with one pointing at
    # this interpreter, which is exactly how an installed app ends up
    # unreachable from the menu.
    if is_running_in_appimage() or is_running_in_flatpak() or _is_packaged_install(project_root):
        _remove_generated_desktop_entry()
        return

    logo_path = project_root / "src" / "openemux" / "ui" / "assets" / "images" / "logo.png"
    if not logo_path.exists():
        return

    icon_target = Path.home() / ".local" / "share" / "icons" / "hicolor" / "512x512" / "apps" / f"{APP_ID}.png"
    icon_target.parent.mkdir(parents=True, exist_ok=True)
    if not icon_target.exists() or icon_target.stat().st_mtime < logo_path.stat().st_mtime:
        shutil.copy2(logo_path, icon_target)

    desktop_target = Path.home() / ".local" / "share" / "applications" / f"{APP_ID}.desktop"
    desktop_target.parent.mkdir(parents=True, exist_ok=True)
    exec_cmd = f'{sys.executable} {project_root / "src" / "openemux" / "main.py"}'
    desktop_content = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Version=1.0\n"
        "Name=OpenEmux\n"
        f"Exec={exec_cmd}\n"
        f"Icon={APP_ID}\n"
        "Terminal=false\n"
        "Categories=Game;\n"
        f"StartupWMClass={APP_ID}\n"
    )
    if not desktop_target.exists() or desktop_target.read_text(encoding="utf-8") != desktop_content:
        desktop_target.write_text(desktop_content, encoding="utf-8")


def main():
    try:
        prepare_process()
        # GLib on its own, before the application object exists: it pulls in no
        # GTK and opens no display, so the program name is set before anything
        # can read it for a window's WM_CLASS. main.py imports nothing from
        # gi at module level any more.
        from gi.repository import GLib

        GLib.set_prgname(APP_ID)
        _ensure_desktop_integration()
        app = build_application()
        return app.run(sys.argv)
    except Exception:
        append_startup_error(
            "Unhandled startup exception in openemux.main",
            exc_text=traceback.format_exc(),
        )
        logging.exception("Unhandled startup exception")
        raise

if __name__ == "__main__":  # pragma: no cover - the console-script entry point
    sys.exit(main())
