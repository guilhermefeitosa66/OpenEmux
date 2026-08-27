import os
import sys
import logging
import traceback
from pathlib import Path
import shutil

from openemux.core.paths import (
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


def _configure_game_window_backend():
    """Run as an X11 client when the game window is on (issue #199).

    The wrapper adopts RetroArch's window by re-parenting it, which only
    works between two X clients -- on a Wayland session that means putting
    both on XWayland. Has to happen before the first ``gi`` import, hence a
    module-level call rather than something the app decides later.

    Three ways out, all of them leaving GTK to pick its own backend: a
    GDK_BACKEND is already set, which is an explicit choice we do not
    override; the session cannot host an embed at all (no python-xlib, no X
    display -- forcing x11 there would leave GTK with no display and the app
    would not start); or the user turned the game window off.
    """
    # Windows has no X server and no reparenting equivalent, so the game
    # window is off there and RetroArch opens its own. game_window_support
    # already reaches the same conclusion via the absent DISPLAY; returning
    # here says so outright and skips importing the X11 machinery to find out.
    if IS_WINDOWS:
        return
    if os.environ.get("GDK_BACKEND"):
        return
    # Imported here rather than at module scope: this runs before the GTK
    # stack is even importable, so the pre-GTK section stays as small as it
    # can be.
    from openemux.core import game_window_support
    from openemux.core.config import read_game_window_setting

    if not game_window_support.embedding_possible():
        return
    if not read_game_window_setting():
        return
    os.environ["GDK_BACKEND"] = "x11"


#: Whether prepare_process() has already run in this process.
_prepared = False


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
    _configure_gtk_renderer()
    # Before the backend pick: the setting is read straight off the config
    # file, which a legacy config dir may still be on its way to.
    migrate_legacy_config_dir()
    _configure_game_window_backend()
    configure_startup_logging()
    _ensure_gtk_typelibs()


def build_application():
    """Prepare the process, then hand back the application object.

    The GTK import and the application class live in ``openemux.app``, reached
    only from here: importing ``gi.repository.Gtk`` runs ``Gtk.init()``, which
    *opens the display*, so ``GDK_BACKEND`` -- which
    ``_configure_game_window_backend`` sets -- has to be in the environment
    before that import rather than after it.
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

if __name__ == "__main__":
    sys.exit(main())
