import sys
import logging
from pathlib import Path
import shutil
import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw, GLib
from opemux.ui.window import OpemuxWindow
from opemux.core.config import ConfigManager


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)

APP_ID = "org.opemux.Opemux"


def _ensure_desktop_integration():
    project_root = Path(__file__).resolve().parents[2]
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

    def do_activate(self):
        # Ensure default directories exist
        self.config_manager.ensure_rom_directories()
        
        # Create and show the main window
        win = self.main_window = OpemuxWindow(application=self)
        win.present()

def main():
    GLib.set_prgname(APP_ID)
    _ensure_desktop_integration()
    app = OpemuxApplication()
    return app.run(sys.argv)

if __name__ == "__main__":
    main()
