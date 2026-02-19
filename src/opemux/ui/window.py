import os
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Gdk, GLib

from opemux.core.cover_sync import sync_covers_async
from opemux.core.playlist_manager import PlaylistManager
from opemux.core.runtime_manager import RuntimeManager
from opemux.core.scanner import RomScanner
from opemux.ui.grid import RomGrid
from opemux.ui.settings_grid import SettingsGrid

CONSOLE_LABELS = {
    "nes": "NES",
    "snes": "SNES",
    "gba": "GBA",
}

FALLBACK_CONSOLE_ICONS = {
    "nes": "applications-games-symbolic",
    "snes": "applications-games-symbolic",
    "gba": "phone-symbolic",
}

SETTINGS_ITEMS = [
    ("roms", "ROMS", "Library paths and sync jobs", "folder-symbolic"),
    ("bios", "BIOS", "Core BIOS management", "media-floppy-symbolic"),
    ("input", "Input", "Keyboard and gamepad mapping", "input-gaming-symbolic"),
    ("shaders", "Shaders", "Visual filters and presets", "applications-graphics-symbolic"),
    ("system", "System", "Runtime and backend settings", "applications-system-symbolic"),
]


class OpemuxWindow(Adw.ApplicationWindow):
    def __init__(self, application, **kwargs):
        super().__init__(application=application, **kwargs)

        self.set_title("Opemux")
        self.set_default_size(1200, 800)
        self.load_css()

        self.config_manager = application.config_manager
        self.scanner = RomScanner(self.config_manager.get_roms_path())
        self.playlist_manager = PlaylistManager(self.config_manager, self.scanner)
        self.covers_dir = self.config_manager.get_covers_dir()
        self.current_console = "nes"
        self._cover_sync_running = False

        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
        self.runtime_manager = RuntimeManager(project_root, self.config_manager)
        self.project_root = Path(project_root)

        self.main_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self.toast_overlay = Adw.ToastOverlay()
        self.toast_overlay.set_child(self.main_box)
        self.set_content(self.toast_overlay)

        self.sidebar = self._build_sidebar()
        self.main_box.append(self.sidebar)
        self.main_box.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))

        self.content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.content_box.set_hexpand(True)

        self.header_bar = Adw.HeaderBar()
        self._build_header(self.header_bar)
        self.content_box.append(self.header_bar)

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
        css_path = os.path.join(os.path.dirname(__file__), "style.css")
        css_provider.load_from_path(css_path)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )

    def _build_header(self, header_bar):
        self.stop_btn = Gtk.Button()
        self.stop_btn.set_icon_name("media-playback-stop-symbolic")
        self.stop_btn.set_tooltip_text("Stop running game")
        self.stop_btn.set_sensitive(False)
        self.stop_btn.connect("clicked", self._on_stop_game_clicked)
        header_bar.pack_end(self.stop_btn)

        self.search_button = Gtk.ToggleButton()
        self.search_button.set_icon_name("system-search-symbolic")
        self.search_button.set_tooltip_text("Search ROMs")
        self.search_button.connect("toggled", self._on_search_toggled)
        header_bar.pack_end(self.search_button)

        refresh_btn = Gtk.Button()
        refresh_btn.set_icon_name("view-refresh-symbolic")
        refresh_btn.set_tooltip_text("Reload visible page")
        refresh_btn.connect("clicked", self._on_refresh_clicked)
        header_bar.pack_end(refresh_btn)

    def _build_sidebar(self):
        sidebar_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        sidebar_box.set_size_request(220, -1)
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

            icon_widget = self._build_console_icon(console_id)
            box.append(icon_widget)

            name = Gtk.Label(label=CONSOLE_LABELS[console_id])
            name.set_halign(Gtk.Align.START)
            name.set_hexpand(True)
            box.append(name)

            row.set_child(box)
            row.id = console_id
            self.console_list.append(row)

        sidebar_box.append(self.console_list)

        spacer = Gtk.Box()
        spacer.set_vexpand(True)
        sidebar_box.append(spacer)

        settings_btn = Gtk.Button(label="Configurações")
        settings_btn.set_icon_name("emblem-system-symbolic")
        settings_btn.add_css_class("pill")
        settings_btn.set_margin_start(12)
        settings_btn.set_margin_end(12)
        settings_btn.set_margin_bottom(12)
        settings_btn.connect("clicked", lambda _: self._open_settings_main())
        sidebar_box.append(settings_btn)
        return sidebar_box

    def _build_console_icon(self, console_id):
        icon_path = self._asset_path("systems", f"{console_id}.png")
        if icon_path.exists():
            pic = Gtk.Picture.new_for_filename(str(icon_path))
            pic.set_size_request(22, 22)
            return pic
        return Gtk.Image.new_from_icon_name(FALLBACK_CONSOLE_ICONS[console_id])

    def _asset_path(self, category, filename):
        return Path(__file__).parent / "assets" / "icons" / category / filename

    def refresh_library(self):
        while child := self.content_stack.get_first_child():
            self.content_stack.remove(child)

        self._grids = {}
        self._console_pages = {}
        self._console_loaded = {}

        for console in ["nes", "snes", "gba"]:
            scroll = Gtk.ScrolledWindow()
            scroll.set_vexpand(True)
            placeholder = Gtk.Label(label=f"Select {CONSOLE_LABELS[console]} to load playlist")
            placeholder.add_css_class("dim-label")
            placeholder.set_margin_top(32)
            scroll.set_child(placeholder)
            self._console_pages[console] = scroll
            self._console_loaded[console] = False
            self.content_stack.add_titled(scroll, console, CONSOLE_LABELS[console])

        self._build_settings_views()

        first_row = self.console_list.get_row_at_index(0)
        if first_row:
            self.console_list.select_row(first_row)

    def _build_settings_views(self):
        settings_scroll = Gtk.ScrolledWindow()
        settings_scroll.set_vexpand(True)
        settings_grid = SettingsGrid()
        for item_id, title, subtitle, fallback_icon in SETTINGS_ITEMS:
            icon_path = self._asset_path("settings", f"{item_id}.png")
            settings_grid.add_card(
                title=title,
                subtitle=subtitle,
                icon_path=str(icon_path) if icon_path.exists() else None,
                icon_name=fallback_icon,
                on_click=(self._open_settings_roms if item_id == "roms" else None),
            )
        settings_scroll.set_child(settings_grid)
        self.content_stack.add_titled(settings_scroll, "settings-main", "Configurações")

        roms_scroll = Gtk.ScrolledWindow()
        roms_scroll.set_vexpand(True)
        roms_grid = SettingsGrid()
        roms_grid.add_card(
            title="Path",
            subtitle=str(self.config_manager.get_roms_path()),
            icon_name="folder-symbolic",
        )
        roms_grid.add_card(
            title="Scan ROMs",
            subtitle="Rebuild playlist for selected console",
            icon_name="view-refresh-symbolic",
            on_click=self._scan_current_console,
        )
        roms_grid.add_card(
            title="Sync Covers",
            subtitle="Download missing covers in background",
            icon_name="folder-download-symbolic",
            on_click=self._show_sync_covers_dialog,
        )
        roms_grid.add_card(
            title="Back",
            subtitle="Return to settings categories",
            icon_name="go-previous-symbolic",
            on_click=self._open_settings_main,
        )
        roms_scroll.set_child(roms_grid)
        self.content_stack.add_titled(roms_scroll, "settings-roms", "ROMS")

    def _on_console_selected(self, _listbox, row):
        if not row:
            return
        self.current_console = row.id
        self._set_search_enabled(True)
        self._ensure_console_loaded(self.current_console)
        self.content_stack.set_visible_child_name(self.current_console)
        self.search_entry.set_text("")

    def _set_search_enabled(self, enabled):
        if not enabled:
            self.search_button.set_active(False)
        self.search_button.set_sensitive(enabled)
        self.search_entry.set_sensitive(enabled)

    def _open_settings_main(self):
        self._set_search_enabled(False)
        self.console_list.unselect_all()
        self.content_stack.set_visible_child_name("settings-main")

    def _open_settings_roms(self):
        self._set_search_enabled(False)
        self.console_list.unselect_all()
        self.content_stack.set_visible_child_name("settings-roms")

    def _ensure_console_loaded(self, console, force_rescan=False):
        created_playlist = False
        if force_rescan:
            roms = self.playlist_manager.scan_and_rebuild_playlist(console)
            created_playlist = True
        else:
            if not self.playlist_manager.playlist_exists(console):
                if self.config_manager.auto_scan_on_first_open():
                    created_playlist = True
                    roms = self.playlist_manager.scan_and_rebuild_playlist(console)
                else:
                    roms = []
            else:
                roms = self.playlist_manager.load_playlist(console)

        self._render_console_page(console, roms)
        self._console_loaded[console] = True

        if created_playlist and roms and not self._cover_sync_running:
            self._start_cover_sync(scope="console", selected_console=console)

    def _render_console_page(self, console, roms):
        scroll = self._console_pages[console]
        if not roms:
            empty_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
            empty_box.set_valign(Gtk.Align.CENTER)
            empty_box.set_halign(Gtk.Align.CENTER)

            empty_icon = Gtk.Image.new_from_icon_name("folder-open-symbolic")
            empty_icon.set_pixel_size(64)
            empty_icon.set_opacity(0.4)
            empty_box.append(empty_icon)

            empty_label = Gtk.Label(label=f"No {CONSOLE_LABELS.get(console, console.upper())} ROMs indexed")
            empty_label.add_css_class("dim-label")
            empty_box.append(empty_label)

            path_label = Gtk.Label(label=str(self.playlist_manager.get_playlist_path(console)))
            path_label.add_css_class("caption")
            path_label.add_css_class("dim-label")
            empty_box.append(path_label)
            scroll.set_child(empty_box)
            self._grids.pop(console, None)
            return

        grid = RomGrid(console, roms, self.on_launch_game, self.covers_dir)
        self._grids[console] = grid
        scroll.set_child(grid)

    def _scan_current_console(self):
        self._ensure_console_loaded(self.current_console, force_rescan=True)
        toast = Adw.Toast(title=f"Playlist rebuilt for {self.current_console.upper()}")
        toast.set_timeout(4)
        self.toast_overlay.add_toast(toast)

    def _show_sync_covers_dialog(self):
        dialog = Gtk.Dialog(transient_for=self, modal=True)
        dialog.set_title("Sync Covers")
        dialog.set_default_size(360, 120)
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("Start", Gtk.ResponseType.OK)

        content = dialog.get_content_area()
        content.set_spacing(10)
        content.set_margin_top(12)
        content.set_margin_bottom(12)
        content.set_margin_start(12)
        content.set_margin_end(12)

        label = Gtk.Label(label="Scope")
        label.set_halign(Gtk.Align.START)
        content.append(label)

        combo = Gtk.ComboBoxText()
        combo.append("console", f"Current console ({self.current_console.upper()})")
        combo.append("all", "All consoles")
        combo.set_active_id("console")
        content.append(combo)

        def _on_response(_dlg, response):
            if response == Gtk.ResponseType.OK:
                scope = combo.get_active_id() or "console"
                self._start_cover_sync(scope=scope, selected_console=self.current_console)
            dialog.close()

        dialog.connect("response", _on_response)
        dialog.show()

    def _start_cover_sync(self, scope, selected_console):
        if self._cover_sync_running:
            toast = Adw.Toast(title="Cover sync already running")
            toast.set_timeout(3)
            self.toast_overlay.add_toast(toast)
            return

        library = {}
        if scope == "console":
            library[selected_console] = self.playlist_manager.load_playlist(selected_console)
        else:
            for console in ["nes", "snes", "gba"]:
                if not self.playlist_manager.playlist_exists(console) and self.config_manager.auto_scan_on_first_open():
                    self.playlist_manager.scan_and_rebuild_playlist(console)
                library[console] = self.playlist_manager.load_playlist(console)

        self._cover_sync_running = True
        toast = Adw.Toast(title="Cover sync started in background")
        toast.set_timeout(3)
        self.toast_overlay.add_toast(toast)

        def _on_done(summary):
            GLib.idle_add(self._on_cover_sync_done_ui, summary)

        sync_covers_async(
            library_by_console=library,
            covers_dir=self.covers_dir,
            scope=scope,
            selected_console=selected_console,
            on_done=_on_done,
        )

    def _on_cover_sync_done_ui(self, summary):
        self._cover_sync_running = False
        title = (
            f"Cover sync done: {summary['downloaded']} downloaded, "
            f"{summary['skipped']} skipped, {summary['errors']} missed"
        )
        toast = Adw.Toast(title=title)
        toast.set_timeout(6)
        self.toast_overlay.add_toast(toast)
        if self.current_console in self._grids:
            self._ensure_console_loaded(self.current_console)
        return False

    def _on_refresh_clicked(self, _button):
        visible = self.content_stack.get_visible_child_name()
        if visible in ("nes", "snes", "gba"):
            self._ensure_console_loaded(visible)
        elif visible == "settings-roms":
            self._scan_current_console()

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

    def _on_search_toggled(self, button):
        self.search_bar.set_search_mode(button.get_active())
        if button.get_active():
            self.search_entry.grab_focus()

    def _on_search_changed(self, entry):
        query = entry.get_text().lower()
        visible = self.content_stack.get_visible_child_name()
        if not visible or visible not in self._grids:
            return
        grid = self._grids[visible]
        child = grid.get_first_child()
        while child:
            flow_child = child
            inner = flow_child.get_child()
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
