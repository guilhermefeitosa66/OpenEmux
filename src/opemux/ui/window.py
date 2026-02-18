import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, Gio, Gdk
from opemux.ui.grid import RomGrid
from opemux.core.scanner import RomScanner
from opemux.core.launcher import Launcher

class OpemuxWindow(Adw.ApplicationWindow):
    def __init__(self, application, **kwargs):
        super().__init__(application=application, **kwargs)

        self.set_title("Opemux")
        self.set_default_size(1100, 800)
        
        # Load CSS
        self.load_css()

        self.config_manager = application.config_manager
        self.scanner = RomScanner(self.config_manager.get_roms_path())
        
        # Initialize Launcher
        import os
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
        self.launcher = Launcher(project_root)

        # Main box
        self.main_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)

        self.set_content(self.main_box)

        # Sidebar
        self.sidebar = self.create_sidebar()
        self.main_box.append(self.sidebar)

        # Separator
        self.main_box.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))

        # Right side content
        self.content_stack = Adw.ViewStack()
        
        # Header bar for the content area
        self.content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.content_box.set_hexpand(True)
        
        self.header_bar = Adw.HeaderBar()
        self.content_box.append(self.header_bar)
        
        self.content_box.append(self.content_stack)
        self.main_box.append(self.content_box)

        # Build views
        self.refresh_library()

    def load_css(self):
        css_provider = Gtk.CssProvider()
        import os
        css_path = os.path.join(os.path.dirname(__file__), "style.css")
        css_provider.load_from_path(css_path)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def create_sidebar(self):
        sidebar_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        sidebar_box.set_size_request(200, -1)
        sidebar_box.add_css_class("sidebar")

        label = Gtk.Label(label="Consoles")
        label.set_halign(Gtk.Align.START)
        label.set_margin_top(15)
        label.set_margin_bottom(10)
        label.set_margin_start(20)
        label.add_css_class("heading")
        sidebar_box.append(label)

        self.console_list = Gtk.ListBox()
        self.console_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.console_list.connect("row-selected", self.on_console_selected)
        
        # Add consoles to sidebar
        for console in ["NES", "SNES", "GBA"]:
            row = Gtk.ListBoxRow()
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            box.set_margin_top(10)
            box.set_margin_bottom(10)
            box.set_margin_start(15)
            
            icon = Gtk.Image.new_from_icon_name("input-gaming-symbolic")
            box.append(icon)
            
            name = Gtk.Label(label=console)
            box.append(name)
            
            row.set_child(box)
            row.id = console.lower()
            self.console_list.append(row)

        sidebar_box.append(self.console_list)
        
        return sidebar_box

    def refresh_library(self):
        # Clear existing views
        while child := self.content_stack.get_first_child():
            self.content_stack.remove(child)

        library = self.scanner.scan_all()
        for console, roms in library.items():
            scroll = Gtk.ScrolledWindow()
            scroll.set_vexpand(True)
            
            if not roms:
                # Show empty state
                empty_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
                empty_box.set_valign(Gtk.Align.CENTER)
                empty_box.set_halign(Gtk.Align.CENTER)
                
                empty_icon = Gtk.Image.new_from_icon_name("folder-open-symbolic")
                empty_icon.set_pixel_size(64)
                empty_box.append(empty_icon)
                
                empty_label = Gtk.Label(label=f"No {console.upper()} ROMs found in {self.config_manager.get_roms_path() / console}")
                empty_box.append(empty_label)
                scroll.set_child(empty_box)
            else:
                grid = RomGrid(console, roms, self.on_launch_game)
                scroll.set_child(grid)
            
            self.content_stack.add_titled(scroll, console, console.upper())

    def on_launch_game(self, rom):
        success, error_msg = self.launcher.launch(rom["path"], rom["console"])
        if not success and error_msg:
            # Show error as a toast notification
            toast = Adw.Toast(title=error_msg)
            toast.set_timeout(5)
            # Add toast overlay if not already present
            if not hasattr(self, '_toast_overlay'):
                self._toast_overlay = Adw.ToastOverlay()
                self.content_box.remove(self.content_stack)
                self._toast_overlay.set_child(self.content_stack)
                self.content_box.append(self._toast_overlay)
            self._toast_overlay.add_toast(toast)

    def on_console_selected(self, listbox, row):

        if row:
            self.content_stack.set_visible_child_name(row.id)

