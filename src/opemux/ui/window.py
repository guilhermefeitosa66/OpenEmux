import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, Gio, Gdk, GLib
from opemux.ui.grid import RomGrid
from opemux.core.scanner import RomScanner
from opemux.core.runtime_manager import RuntimeManager

CONSOLE_LABELS = {
    "nes": "NES",
    "snes": "SNES",
    "gba": "GBA",
}

CONSOLE_ICONS = {
    "nes": "applications-games-symbolic",
    "snes": "applications-games-symbolic",
    "gba": "phone-symbolic",
}


class OpemuxWindow(Adw.ApplicationWindow):
    def __init__(self, application, **kwargs):
        super().__init__(application=application, **kwargs)

        self.set_title("Opemux")
        self.set_default_size(1200, 800)

        self.load_css()

        self.config_manager = application.config_manager
        self.scanner = RomScanner(self.config_manager.get_roms_path())
        self.covers_dir = self.config_manager.get_covers_dir()

        import os
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
        self.runtime_manager = RuntimeManager(project_root, self.config_manager)

        # Root layout: horizontal split
        self.main_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)

        # Toast overlay wraps the entire content area
        self.toast_overlay = Adw.ToastOverlay()
        self.toast_overlay.set_child(self.main_box)
        self.set_content(self.toast_overlay)

        # Sidebar
        self.sidebar = self._build_sidebar()
        self.main_box.append(self.sidebar)
        self.main_box.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))

        # Right side: header + search + content stack
        self.content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.content_box.set_hexpand(True)

        self.header_bar = Adw.HeaderBar()
        self._build_header(self.header_bar)
        self.content_box.append(self.header_bar)

        # Search bar (hidden by default, toggled by search button)
        self.search_bar = Gtk.SearchBar()
        self.search_entry = Gtk.SearchEntry()
        self.search_entry.set_hexpand(True)
        self.search_entry.connect("search-changed", self._on_search_changed)
        self.search_bar.set_child(self.search_entry)
        self.search_bar.set_show_close_button(True)
        self.content_box.append(self.search_bar)

        self.content_stack = Adw.ViewStack()
        self.content_box.append(self.content_stack)

        self.main_box.append(self.content_box)

        self.refresh_library()
        GLib.timeout_add_seconds(1, self._poll_runtime_state)

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

    def _build_header(self, header_bar):
        self.stop_btn = Gtk.Button()
        self.stop_btn.set_icon_name("media-playback-stop-symbolic")
        self.stop_btn.set_tooltip_text("Stop running game")
        self.stop_btn.set_sensitive(False)
        self.stop_btn.connect("clicked", self._on_stop_game_clicked)
        header_bar.pack_end(self.stop_btn)

        # Search toggle button
        self.search_button = Gtk.ToggleButton()
        self.search_button.set_icon_name("system-search-symbolic")
        self.search_button.set_tooltip_text("Search ROMs")
        self.search_button.connect("toggled", self._on_search_toggled)
        header_bar.pack_end(self.search_button)

        # Refresh button
        refresh_btn = Gtk.Button()
        refresh_btn.set_icon_name("view-refresh-symbolic")
        refresh_btn.set_tooltip_text("Refresh library")
        refresh_btn.connect("clicked", lambda _: self.refresh_library())
        header_bar.pack_end(refresh_btn)

    def _build_sidebar(self):
        sidebar_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        sidebar_box.set_size_request(210, -1)
        sidebar_box.add_css_class("sidebar")

        label = Gtk.Label(label="Library")
        label.set_halign(Gtk.Align.START)
        label.set_margin_top(18)
        label.set_margin_bottom(12)
        label.set_margin_start(20)
        label.add_css_class("heading")
        sidebar_box.append(label)

        self.console_list = Gtk.ListBox()
        self.console_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.console_list.connect("row-selected", self._on_console_selected)
        self.console_list.add_css_class("navigation-sidebar")

        for console_id in ["nes", "snes", "gba"]:
            row = Gtk.ListBoxRow()
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            box.set_margin_top(10)
            box.set_margin_bottom(10)
            box.set_margin_start(16)
            box.set_margin_end(16)

            icon = Gtk.Image.new_from_icon_name(CONSOLE_ICONS[console_id])
            box.append(icon)

            name = Gtk.Label(label=CONSOLE_LABELS[console_id])
            name.set_halign(Gtk.Align.START)
            name.set_hexpand(True)
            box.append(name)

            row.set_child(box)
            row.id = console_id
            self.console_list.append(row)

        sidebar_box.append(self.console_list)
        return sidebar_box

    def refresh_library(self):
        # Clear existing views
        while child := self.content_stack.get_first_child():
            self.content_stack.remove(child)

        self._grids = {}
        library = self.scanner.scan_all()

        for console, roms in library.items():
            scroll = Gtk.ScrolledWindow()
            scroll.set_vexpand(True)

            if not roms:
                empty_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
                empty_box.set_valign(Gtk.Align.CENTER)
                empty_box.set_halign(Gtk.Align.CENTER)

                empty_icon = Gtk.Image.new_from_icon_name("folder-open-symbolic")
                empty_icon.set_pixel_size(64)
                empty_icon.set_opacity(0.4)
                empty_box.append(empty_icon)

                empty_label = Gtk.Label(
                    label=f"No {CONSOLE_LABELS.get(console, console.upper())} ROMs found"
                )
                empty_label.add_css_class("dim-label")
                empty_box.append(empty_label)

                path_label = Gtk.Label(
                    label=str(self.config_manager.get_roms_path() / console)
                )
                path_label.add_css_class("caption")
                path_label.add_css_class("dim-label")
                empty_box.append(path_label)

                scroll.set_child(empty_box)
            else:
                grid = RomGrid(console, roms, self.on_launch_game, self.covers_dir)
                self._grids[console] = grid
                scroll.set_child(grid)

            self.content_stack.add_titled(scroll, console, CONSOLE_LABELS.get(console, console.upper()))

        # Select first console by default
        first_row = self.console_list.get_row_at_index(0)
        if first_row:
            self.console_list.select_row(first_row)

    def on_launch_game(self, rom):
        success, error_msg = self.runtime_manager.launch(rom["path"], rom["console"])
        self._sync_runtime_controls()
        if not success and error_msg:
            toast = Adw.Toast(title=error_msg)
            toast.set_timeout(5)
            self.toast_overlay.add_toast(toast)
        elif success:
            toast = Adw.Toast(title=f"Running {rom['name']} ({rom['console'].upper()})")
            toast.set_timeout(3)
            self.toast_overlay.add_toast(toast)

    def _on_console_selected(self, listbox, row):
        if row:
            self.content_stack.set_visible_child_name(row.id)
            # Reset search when switching consoles
            self.search_entry.set_text("")

    def _on_search_toggled(self, button):
        self.search_bar.set_search_mode(button.get_active())
        if button.get_active():
            self.search_entry.grab_focus()

    def _on_search_changed(self, entry):
        query = entry.get_text().lower()
        # Get current console
        visible = self.content_stack.get_visible_child_name()
        if not visible or visible not in self._grids:
            return
        grid = self._grids[visible]
        # Filter: show/hide children based on name match
        child = grid.get_first_child()
        while child:
            flow_child = child  # FlowBoxChild
            inner = flow_child.get_child()  # RomItem
            if inner and hasattr(inner, "rom"):
                matches = query in inner.rom["name"].lower()
                flow_child.set_visible(matches or not query)
            child = child.get_next_sibling()

    def _on_stop_game_clicked(self, _button):
        success, error_msg = self.runtime_manager.stop_active()
        self._sync_runtime_controls()
        if not success and error_msg:
            toast = Adw.Toast(title=error_msg)
            toast.set_timeout(4)
            self.toast_overlay.add_toast(toast)

    def _poll_runtime_state(self):
        result = self.runtime_manager.poll_active()
        if result is not None:
            rom = result.get("rom") or {}
            rom_name = rom.get("path", "Game").split("/")[-1]
            title = f"{rom_name} finished (code {result['exit_code']})"
            toast = Adw.Toast(title=title)
            toast.set_timeout(4)
            self.toast_overlay.add_toast(toast)
        self._sync_runtime_controls()
        return True

    def _sync_runtime_controls(self):
        is_running = self.runtime_manager.is_running()
        self.stop_btn.set_sensitive(is_running)
