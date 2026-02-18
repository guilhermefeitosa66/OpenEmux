import sys
import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw
from opemux.ui.window import OpemuxWindow
from opemux.core.config import ConfigManager

class OpemuxApplication(Adw.Application):
    def __init__(self):
        super().__init__(application_id='org.opemux.Opemux',
                         flags=gi.repository.Gio.ApplicationFlags.FLAGS_NONE)
        self.config_manager = ConfigManager()

    def do_activate(self):
        # Ensure default directories exist
        self.config_manager.ensure_rom_directories()
        
        # Create and show the main window
        win = self.main_window = OpemuxWindow(application=self)
        win.present()

def main():
    app = OpemuxApplication()
    return app.run(sys.argv)

if __name__ == "__main__":
    main()
