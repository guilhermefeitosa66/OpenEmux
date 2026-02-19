import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, Gdk, GdkPixbuf, GLib, Pango
from pathlib import Path

from opemux.core.scraper import fetch_cover

DEFAULT_ITEM_SIZE = (200, 200)
FIXED_ITEM_WIDTH = 200

CONSOLE_COVER_SIZES = {
    # Width fixed at 200px. Heights keep cartridge image proportions:
    # FC: 698x784 -> 200x225
    # SFC: 811x518 -> 200x128
    # GBA: 1000x574 -> 200x115
    "FC": (200, 225),
    "SFC": (200, 128),
    "GBA": (200, 115),
}

CARTRIDGE_COVER_FRAMES = {
    # x, y, width, height for cover placement when cartridge overlay is enabled
    "GBA": (26.6, 25.7, 147, 75.3),
    "FC": (80.9, 0, 93.1, 153),
    "SFC": (38.6, 0, 122.5, 57.2),
}


class RomItem(Gtk.Box):
    def __init__(
        self,
        rom,
        on_launch_callback,
        roms_dir,
        cover_size,
        cartridge_overlay_path=None,
        cover_frame=None,
    ):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.rom = rom
        self.on_launch_callback = on_launch_callback
        self.roms_dir = roms_dir
        self.cover_width, self.cover_height = cover_size
        self.cover_frame = cover_frame
        self.add_css_class("rom-card")
        self.set_size_request(self.cover_width, self.cover_height + 44)
        self.set_halign(Gtk.Align.START)
        self.set_valign(Gtk.Align.START)
        self.set_hexpand(False)
        self.set_vexpand(False)

        # Click gesture
        gesture = Gtk.GestureClick()
        gesture.connect("released", self.on_click)
        self.add_controller(gesture)

        # Hover effects
        motion = Gtk.EventControllerMotion()
        motion.connect("enter", self._on_hover_enter)
        motion.connect("leave", self._on_hover_leave)
        self.add_controller(motion)

        # Cover art overlay (image + play button on hover)
        self.cover_overlay = Gtk.Overlay()
        self.cover_overlay.set_size_request(self.cover_width, self.cover_height)

        # Cover image (placeholder initially)
        self.cover_image = Gtk.Picture()
        self.cover_image.set_size_request(*self._cover_target_size())
        self.cover_image.set_content_fit(Gtk.ContentFit.COVER)
        self.cover_image.set_can_shrink(True)
        self.cover_image.add_css_class("rom-cover")
        self._setup_cover_host()
        self._set_placeholder()

        # Play button overlay (hidden by default)
        self.play_overlay = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.play_overlay.set_valign(Gtk.Align.CENTER)
        self.play_overlay.set_halign(Gtk.Align.CENTER)
        self.play_overlay.set_size_request(self.cover_width, self.cover_height)
        self.play_overlay.add_css_class("play-overlay")
        self.play_overlay.set_visible(False)

        play_icon = Gtk.Image.new_from_icon_name("media-playback-start-symbolic")
        play_icon.set_pixel_size(40)
        play_icon.add_css_class("play-icon")
        self.play_overlay.append(play_icon)

        self.cartridge_overlay = None
        if cartridge_overlay_path:
            self.cartridge_overlay = Gtk.Picture.new_for_filename(str(cartridge_overlay_path))
            self.cartridge_overlay.set_size_request(self.cover_width, self.cover_height)
            # Preserve cartridge image ratio to avoid distortion.
            self.cartridge_overlay.set_content_fit(Gtk.ContentFit.CONTAIN)
            self.cartridge_overlay.set_can_shrink(True)
            self.cover_overlay.add_overlay(self.cartridge_overlay)
        self.cover_overlay.add_overlay(self.play_overlay)

        self.append(self.cover_overlay)

        # ROM Name
        self.name_label = Gtk.Label(label=rom["name"])
        self.name_label.set_halign(Gtk.Align.CENTER)
        self.name_label.set_max_width_chars(16)
        self.name_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.name_label.add_css_class("rom-title")
        self.append(self.name_label)

        # Trigger async cover art fetch
        fetch_cover(rom, self.roms_dir, self._on_cover_fetched)

    def _set_placeholder(self):
        """Show a styled placeholder with console-specific icon."""
        console_icons = {
            "FC": "applications-games-symbolic",
            "SFC": "applications-games-symbolic",
            "GBA": "phone-symbolic",
        }
        icon_name = console_icons.get(self.rom.get("console", ""), "package-x-generic-symbolic")

        placeholder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        placeholder.set_valign(Gtk.Align.CENTER)
        placeholder.set_halign(Gtk.Align.CENTER)
        placeholder.set_hexpand(True)
        placeholder.set_vexpand(True)
        placeholder.set_size_request(*self._cover_target_size())
        placeholder.add_css_class("rom-cover-placeholder")

        icon = Gtk.Image.new_from_icon_name(icon_name)
        icon.set_pixel_size(48)
        icon.add_css_class("placeholder-icon")
        placeholder.append(icon)

        # Replace cover image with placeholder in the configured cover area.
        self.cover_image.set_visible(False)
        self._set_cover_widget(placeholder)
        self._placeholder_widget = placeholder

    def _on_cover_fetched(self, rom, cover_path):
        """Called from background thread when cover art is ready."""
        if cover_path:
            # Schedule UI update on the main thread
            GLib.idle_add(self._load_cover_image, cover_path)

    def _load_cover_image(self, cover_path):
        """Load cover image into the widget (must run on main thread)."""
        try:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(
                cover_path,
                self._cover_target_size()[0],
                self._cover_target_size()[1],
                True,
            )
            self.cover_image.set_pixbuf(pixbuf)
            self.cover_image.set_visible(True)
            # Remove placeholder if present
            if hasattr(self, "_placeholder_widget"):
                self._set_cover_widget(self.cover_image)
                del self._placeholder_widget
        except Exception:
            pass  # Keep placeholder on error
        return False  # Don't repeat idle callback

    def _cover_target_size(self):
        if self.cover_frame:
            _, _, width, height = self.cover_frame
            return int(round(width)), int(round(height))
        return self.cover_width, self.cover_height

    def _cover_target_position(self):
        if self.cover_frame:
            x, y, _, _ = self.cover_frame
            return int(round(x)), int(round(y))
        return 0, 0

    def _setup_cover_host(self):
        if self.cover_frame:
            self._cover_host = Gtk.Fixed()
            self._cover_host.set_size_request(self.cover_width, self.cover_height)
            self.cover_overlay.set_child(self._cover_host)
            self._set_cover_widget(self.cover_image)
        else:
            self._cover_host = None
            self.cover_overlay.set_child(self.cover_image)

    def _set_cover_widget(self, widget):
        if self._cover_host is None:
            self.cover_overlay.set_child(widget)
            return
        child = self._cover_host.get_first_child()
        if child:
            self._cover_host.remove(child)
        x, y = self._cover_target_position()
        self._cover_host.put(widget, x, y)

    def _on_hover_enter(self, controller, x, y):
        self.play_overlay.set_visible(True)
        self.add_css_class("rom-card-hover")

    def _on_hover_leave(self, controller):
        self.play_overlay.set_visible(False)
        self.remove_css_class("rom-card-hover")

    def on_click(self, gesture, n_press, x, y):
        if self.on_launch_callback:
            self.on_launch_callback(self.rom)


class RomGrid(Gtk.FlowBox):
    def __init__(self, console, roms, on_launch_callback, roms_dir, ui_settings=None):
        super().__init__()
        self.console = console
        self.on_launch_callback = on_launch_callback
        self.roms_dir = roms_dir
        self.ui_settings = ui_settings or {}
        self.set_valign(Gtk.Align.START)
        self.set_row_spacing(24)
        self.set_column_spacing(24)
        self.set_selection_mode(Gtk.SelectionMode.NONE)
        self.set_margin_top(28)
        self.set_margin_bottom(28)
        self.set_margin_start(28)
        self.set_margin_end(28)
        self.set_homogeneous(False)

        cartridge_overlay_path = None
        cover_size = CONSOLE_COVER_SIZES.get(console, DEFAULT_ITEM_SIZE)
        if self.ui_settings.get("render_cartridge_overlay", False):
            candidate = Path(__file__).parent / "assets" / "images" / "cartridges" / f"{console}.png"
            if candidate.exists():
                cartridge_overlay_path = candidate
                size_info = GdkPixbuf.Pixbuf.get_file_info(str(candidate))
                if size_info:
                    _, width, height = size_info
                    if width and height:
                        proportional_height = int(round((FIXED_ITEM_WIDTH * height) / width))
                        cover_size = (FIXED_ITEM_WIDTH, max(1, proportional_height))
        cover_frame = CARTRIDGE_COVER_FRAMES.get(console) if cartridge_overlay_path else None

        for rom in roms:
            item = RomItem(
                rom,
                self.on_launch_callback,
                self.roms_dir,
                cover_size,
                cartridge_overlay_path=cartridge_overlay_path,
                cover_frame=cover_frame,
            )
            self.append(item)
