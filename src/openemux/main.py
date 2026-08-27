import os
import sys
import logging
import traceback
from threading import Thread
from pathlib import Path
import shutil

from openemux.core.paths import (
    get_project_root,
    is_running_in_appimage,
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


_configure_gtk_renderer()
# Before the backend pick: the setting is read straight off the config file,
# which a legacy config dir may still be on its way to.
migrate_legacy_config_dir()
_configure_game_window_backend()
configure_startup_logging()
_ensure_gtk_typelibs()

try:
    import gi
    gi.require_version('Gtk', '4.0')
    gi.require_version('Adw', '1')
except Exception:
    append_startup_error(
        "Failed to import GTK stack (gi/Gtk/Adw). On Debian/Ubuntu/Mint install "
        "the introspection typelibs: sudo apt install gir1.2-gtk-4.0 gir1.2-adw-1 "
        "(or run 'make install-sys-deps').",
        exc_text=traceback.format_exc(),
    )
    raise

# Gtk is not referenced here, and is imported anyway: importing it is what
# runs Gtk.init(), which opens the display. Adw pulls it in too, but leaving
# that implicit would make the app's initialisation depend on an import inside
# libadwaita's overrides.
from gi.repository import Gtk  # noqa: F401
from gi.repository import Adw, GLib
from openemux.ui.window import OpenEmuxWindow
from openemux.ui.first_boot_window import FirstBootWindow
from openemux.core.config import ConfigManager
from openemux.core.first_boot import FirstBootBootstrapper
from openemux.core.housekeeping import run_startup_housekeeping
from openemux.core.paths import is_running_in_flatpak

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


class OpenEmuxApplication(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID,
                         flags=gi.repository.Gio.ApplicationFlags.FLAGS_NONE)
        self.config_manager = ConfigManager()
        self._bootstrap_running = False
        self._bootstrap_window = None
        self._housekeeping_done = False
        self.main_window = None

    def do_activate(self):
        # Register the vendored symbolic icons before any window exists, so
        # every lookup can fall back to them when the host theme lacks a name.
        from openemux.ui.icons import register_bundled_icons
        register_bundled_icons()

        # Before the first window is drawn: setting the scheme afterwards
        # repaints a window the user is already looking at (issue #198).
        from openemux.ui.theming import apply_theme
        apply_theme(self.config_manager.get_ui_settings()["theme"])

        if self._bootstrap_running:
            if self._bootstrap_window:
                self._bootstrap_window.present()
            return

        # Retention for everything the app writes and never reads back: the
        # per-launch runtime files, the buildbot download cache and the
        # artwork-manager temp directories (issue #221). Cheap -- a couple of
        # directory listings -- and best-effort, so it cannot delay or block
        # the first window. Before the bootstrap check on purpose: a first boot
        # is exactly when a previous failed one may have left a cache behind.
        # Once per process: a re-activation must not sweep under a download or
        # an artwork window this same process still has open.
        if not self._housekeeping_done:
            self._housekeeping_done = True
            run_startup_housekeeping(self.config_manager)

        bootstrapper = FirstBootBootstrapper(self.config_manager)
        if bootstrapper.needs_bootstrap():
            self._start_bootstrap_flow(initial_boot=True, parent=None)
            return

        self._present_main_window()

    def do_shutdown(self):
        # Last line of defence against a game outliving the app. Closing the
        # library window already stops it; this covers every other way the
        # app can end (Ctrl+Q, a quit action, the session going away), where
        # nothing else is left running to notice the process.
        runtime = getattr(self.main_window, "runtime_manager", None)
        if runtime is not None and runtime.is_running():
            runtime.stop_active(block=True)
        Adw.Application.do_shutdown(self)

    def _present_main_window(self):
        if self.main_window:
            self.main_window.present()
            return
        self.config_manager.ensure_rom_directories()
        self.main_window = OpenEmuxWindow(application=self)
        self.main_window.present()
        self.main_window.maybe_show_welcome()
        self.main_window.maybe_report_recovered_state()

    def request_bootstrap_retry_from_ui(self, parent_window):
        if self._bootstrap_running:
            return False
        self.config_manager.request_bootstrap_retry()
        self._start_bootstrap_flow(initial_boot=False, parent=parent_window)
        return True

    def _start_bootstrap_flow(self, initial_boot, parent=None):
        self._bootstrap_running = True
        locale = self.config_manager.get_locale()
        self._bootstrap_window = FirstBootWindow(
            application=self,
            locale=locale,
            parent=parent,
        )
        self._bootstrap_window.present()
        bootstrapper = FirstBootBootstrapper(self.config_manager)
        window = self._bootstrap_window

        def _emit(evt):
            GLib.idle_add(self._deliver_bootstrap_event, window, evt)

        def _worker():
            result = self._run_bootstrap_guarded(bootstrapper, _emit)
            GLib.idle_add(self._finish_bootstrap_flow, result, initial_boot)

        Thread(target=_worker, daemon=True).start()

    @staticmethod
    def _run_bootstrap_guarded(bootstrapper, on_event):
        """Run the bootstrap and always come back with a result.

        ``FirstBootBootstrapper.run`` guards each step handler, but not the
        config reads and writes around the loop -- and those touch the disk, so
        a full disk or an unwritable ``~/.openemux`` raises right past them. The
        worker thread then died silently: ``_finish_bootstrap_flow`` was never
        queued, ``_bootstrap_running`` stayed True, and the first-boot window
        sat there forever with no error and no way out. Relaunching just
        re-presented the same frozen window (issue #215).

        A crash here is still a failed bootstrap, and a failed bootstrap has a
        screen. It has to arrive shaped like one.
        """
        try:
            return bootstrapper.run(on_event=on_event)
        except Exception as exc:
            logging.getLogger(__name__).exception("bootstrap worker crashed")
            return {"success": False, "failed_step": None, "error": str(exc)}

    def _deliver_bootstrap_event(self, window, event):
        """Hand a worker event to the window, if that window is still ours.

        The worker outlives a closed window by design (it is a daemon thread),
        and reaching through ``self._bootstrap_window`` after the flow ended
        raised inside the worker -- taking the thread, and the flow, with it.
        """
        if window is not None and window is self._bootstrap_window:
            window.handle_event(event)
        return False

    def _finish_bootstrap_flow(self, result, initial_boot):
        self._bootstrap_running = False
        if self._bootstrap_window:
            # The window asks for confirmation before closing mid-run; this
            # close is the run being over, so it must not ask.
            self._bootstrap_window.finish()
            self._bootstrap_window.close()
            self._bootstrap_window = None

        if initial_boot:
            self._present_main_window()

        if self.main_window and hasattr(self.main_window, "on_bootstrap_finished"):
            self.main_window.on_bootstrap_finished(result)
        return False

def main():
    try:
        GLib.set_prgname(APP_ID)
        _ensure_desktop_integration()
        app = OpenEmuxApplication()
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
