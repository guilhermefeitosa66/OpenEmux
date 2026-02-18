import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, Gdk, GdkPixbuf

class RomItem(Gtk.Box):
    def __init__(self, rom, on_launch_callback):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        self.rom = rom
        self.on_launch_callback = on_launch_callback
        
        # Click gesture
        gesture = Gtk.GestureClick()
        gesture.connect("released", self.on_click)
        self.add_controller(gesture)

        # Cover Art Placeholder
        self.cover_image = Gtk.Box()

        self.cover_image.set_size_request(120, 160)
        self.cover_image.add_css_class("rom-cover-placeholder")
        
        # In a real app, we would load the actual cover here
        # For now, just a colored box or an icon
        icon = Gtk.Image.new_from_icon_name("package-x-generic-symbolic")
        icon.set_pixel_size(64)
        icon.set_valign(Gtk.Align.CENTER)
        icon.set_halign(Gtk.Align.CENTER)
        icon.set_hexpand(True)
        icon.set_vexpand(True)
        self.cover_image.append(icon)
        
        self.append(self.cover_image)
        
        # ROM Name
        self.name_label = Gtk.Label(label=rom["name"])
        self.name_label.set_halign(Gtk.Align.CENTER)
        self.name_label.set_max_width_chars(15)

        self.name_label.set_ellipsize(gi.repository.Pango.EllipsizeMode.END)
        self.name_label.add_css_class("rom-title")
        self.append(self.name_label)

    def on_click(self, gesture, n_press, x, y):
        if self.on_launch_callback:
            self.on_launch_callback(self.rom)

class RomGrid(Gtk.FlowBox):
    def __init__(self, console, roms, on_launch_callback):
        super().__init__()
        self.console = console
        self.on_launch_callback = on_launch_callback
        self.set_valign(Gtk.Align.START)

        self.set_max_children_per_line(15)
        self.set_min_children_per_line(2)
        self.set_row_spacing(20)
        self.set_column_spacing(20)
        self.set_selection_mode(Gtk.SelectionMode.NONE)
        self.set_margin_top(24)
        self.set_margin_bottom(24)
        self.set_margin_start(24)
        self.set_margin_end(24)

        for rom in roms:
            item = RomItem(rom, self.on_launch_callback)
            self.append(item)

