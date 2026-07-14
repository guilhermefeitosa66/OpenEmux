import os
import sys
import logging
import traceback
from threading import Thread
from pathlib import Path
import shutil

from opemux.core.paths import is_running_in_appimage
from opemux.core.startup_logging import append_startup_error, configure_startup_logging


def _configure_gtk_renderer():
    """Pick a crash-safe GSK renderer default for fragile graphics stacks.

    GTK4's default GL/Vulkan (ngl) renderer can hard-crash (SIGSEGV, no Python
    traceback) at window realization when the AppImage's bundled GTK stack runs
    against the host's own GL/Vulkan drivers -- a common failure on fresh
    Debian/Mesa combos. The Cairo software renderer sidesteps every GPU-driver
    mismatch and is more than adequate for Opemux's 2D cover-grid UI.

    Only applied inside the AppImage and only when the user has not already
    chosen a renderer, so a working setup can still opt back in with, e.g.,
    GSK_RENDERER=ngl (or gl / vulkan).
    """
    if is_running_in_appimage() and not os.environ.get("GSK_RENDERER"):
        os.environ["GSK_RENDERER"] = "cairo"


_configure_gtk_renderer()
configure_startup_logging()

try:
    import gi
    gi.require_version('Gtk', '4.0')
    gi.require_version('Adw', '1')
except Exception:
    append_startup_error(
        "Failed to import GTK stack (gi/Gtk/Adw)",
        exc_text=traceback.format_exc(),
    )
    raise

from gi.repository import Gtk, Adw, GLib
from opemux.ui.window import OpemuxWindow
from opemux.ui.first_boot_window import FirstBootWindow
from opemux.core.config import ConfigManager
from opemux.core.first_boot import FirstBootBootstrapper
from opemux.core.paths import get_project_root, is_running_in_appimage

APP_ID = "org.opemux.Opemux"


def _ensure_desktop_integration():
    if is_running_in_appimage():
        return

    project_root = get_project_root()
    logo_path = project_root / "src" / "opemux" / "ui" / "assets" / "images" / "logo.png"
    if not logo_path.exists():
        return

    icon_target = Path.home() / ".local" / "share" / "icons" / "hicolor" / "512x512" / "apps" / f"{APP_ID}.png"
    icon_target.parent.mkdir(parents=True, exist_ok=True)
    if not icon_target.exists() or icon_target.stat().st_mtime < logo_path.stat().st_mtime:
        shutil.copy2(logo_path, icon_target)

    desktop_target = Path.home() / ".local" / "share" / "applications" / f"{APP_ID}.desktop"
    desktop_target.parent.mkdir(parents=True, exist_ok=True)
    exec_cmd = f'{sys.executable} {project_root / "src" / "opemux" / "main.py"}'
    desktop_content = (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Version=1.0\n"
        "Name=Opemux\n"
        f"Exec={exec_cmd}\n"
        f"Icon={APP_ID}\n"
        "Terminal=false\n"
        "Categories=Game;\n"
        f"StartupWMClass={APP_ID}\n"
    )
    if not desktop_target.exists() or desktop_target.read_text(encoding="utf-8") != desktop_content:
        desktop_target.write_text(desktop_content, encoding="utf-8")


class OpemuxApplication(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID,
                         flags=gi.repository.Gio.ApplicationFlags.FLAGS_NONE)
        self.config_manager = ConfigManager()
        self._bootstrap_running = False
        self._bootstrap_window = None
        self.main_window = None

    def do_activate(self):
        if self._bootstrap_running:
            if self._bootstrap_window:
                self._bootstrap_window.present()
            return

        bootstrapper = FirstBootBootstrapper(self.config_manager)
        if bootstrapper.needs_bootstrap():
            self._start_bootstrap_flow(initial_boot=True, parent=None)
            return

        self._present_main_window()

    def _present_main_window(self):
        if self.main_window:
            self.main_window.present()
            return
        self.config_manager.ensure_rom_directories()
        self.main_window = OpemuxWindow(application=self)
        self.main_window.present()

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

        def _emit(evt):
            GLib.idle_add(self._bootstrap_window.handle_event, evt)

        def _worker():
            result = bootstrapper.run(on_event=_emit)
            GLib.idle_add(self._finish_bootstrap_flow, result, initial_boot)

        Thread(target=_worker, daemon=True).start()

    def _finish_bootstrap_flow(self, result, initial_boot):
        self._bootstrap_running = False
        if self._bootstrap_window:
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
        app = OpemuxApplication()
        return app.run(sys.argv)
    except Exception:
        append_startup_error(
            "Unhandled startup exception in opemux.main",
            exc_text=traceback.format_exc(),
        )
        logging.exception("Unhandled startup exception")
        raise

if __name__ == "__main__":
    sys.exit(main())
