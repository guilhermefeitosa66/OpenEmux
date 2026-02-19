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
from opemux.core.systems import SYSTEM_IDS, get_icon_name, get_system_display_name
from opemux.i18n import tr
from opemux.ui.grid import RomGrid
from opemux.ui.settings_grid import SettingsGrid

SETTINGS_ITEMS = [
    ("roms", "folder-symbolic"),
    ("bios", "media-floppy-symbolic"),
    ("input", "input-gaming-symbolic"),
    ("ui", "preferences-desktop-theme-symbolic"),
    ("shaders", "applications-graphics-symbolic"),
    ("system", "applications-system-symbolic"),
]
ALL_CONSOLES_ID = "__all__"


class OpemuxWindow(Adw.ApplicationWindow):
    def __init__(self, application, **kwargs):
        super().__init__(application=application, **kwargs)

        self.config_manager = application.config_manager
        self.locale = self.config_manager.get_locale()
        self.set_title("Opemux")
        self._setup_window_icon()
        self.set_default_size(1200, 800)
        self.load_css()

        self.roms_path = self.config_manager.get_roms_path()
        self.scanner = RomScanner(self.roms_path)
        self.playlist_manager = PlaylistManager(self.config_manager, self.scanner)
        self.current_console = None
        self.visible_consoles = []
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

        self.content_stack = Adw.ViewStack()
        self.content_box.append(self.content_stack)
        self.main_box.append(self.content_box)

        self.refresh_library()
        GLib.timeout_add_seconds(1, self._poll_runtime_state)

    def t(self, key, **kwargs):
        return tr(self.locale, key, **kwargs)

    def _setup_window_icon(self):
        images_dir = Path(__file__).parent / "assets" / "images"
        icon_theme = Gtk.IconTheme.get_for_display(self.get_display())
        icon_theme.add_search_path(str(images_dir))
        icon_name = self.get_application().get_application_id() or "logo"
        if hasattr(Gtk.Window, "set_default_icon_name"):
            Gtk.Window.set_default_icon_name(icon_name)
        if hasattr(self, "set_icon_name"):
            self.set_icon_name(icon_name)

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
        self.search_entry = Gtk.SearchEntry()
        self.search_entry.set_hexpand(True)
        self.search_entry.set_placeholder_text(self.t("header.search"))
        self.search_entry.set_tooltip_text(self.t("header.search"))
        self.search_entry.connect("search-changed", self._on_search_changed)
        header_bar.set_title_widget(self.search_entry)

        self.stop_btn = Gtk.Button()
        self.stop_btn.set_icon_name("media-playback-stop-symbolic")
        self.stop_btn.set_tooltip_text(self.t("header.stop"))
        self.stop_btn.set_sensitive(False)
        self.stop_btn.connect("clicked", self._on_stop_game_clicked)
        header_bar.pack_end(self.stop_btn)

        refresh_btn = Gtk.Button()
        refresh_btn.set_icon_name("view-refresh-symbolic")
        refresh_btn.set_tooltip_text(self.t("header.refresh"))
        refresh_btn.connect("clicked", self._on_refresh_clicked)
        header_bar.pack_end(refresh_btn)

    def _build_sidebar(self):
        sidebar_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        sidebar_box.set_size_request(360, -1)
        sidebar_box.add_css_class("sidebar")

        label = Gtk.Label(label=self.t("sidebar.library"))
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
        sidebar_box.append(self.console_list)

        spacer = Gtk.Box()
        spacer.set_vexpand(True)
        sidebar_box.append(spacer)

        settings_btn = Gtk.Button()
        settings_btn.add_css_class("pill")
        settings_btn.set_margin_start(12)
        settings_btn.set_margin_end(12)
        settings_btn.set_margin_bottom(12)

        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        btn_box.set_halign(Gtk.Align.CENTER)
        btn_box.set_margin_top(6)
        btn_box.set_margin_bottom(6)

        gear_icon = Gtk.Image.new_from_icon_name("preferences-system-symbolic")
        gear_icon.set_pixel_size(18)
        btn_box.append(gear_icon)
        btn_box.append(Gtk.Label(label=self.t("sidebar.settings")))

        settings_btn.set_child(btn_box)
        settings_btn.connect("clicked", lambda _: self._open_settings_main())
        sidebar_box.append(settings_btn)
        self._rebuild_console_sidebar([])
        return sidebar_box

    def _console_sidebar_label(self, console_id):
        if console_id == ALL_CONSOLES_ID:
            return self.t("sidebar.all")
        return f"{console_id} - {get_system_display_name(console_id)}"

    def _build_console_icon(self, console_id):
        if console_id == ALL_CONSOLES_ID:
            return Gtk.Image.new_from_icon_name("view-grid-symbolic")
        icon_path = self._asset_path("systems", f"{console_id.lower()}.png")
        if icon_path.exists():
            pic = Gtk.Picture.new_for_filename(str(icon_path))
            pic.set_size_request(22, 22)
            return pic
        return Gtk.Image.new_from_icon_name(get_icon_name(console_id))

    def _rebuild_console_sidebar(self, consoles):
        while child := self.console_list.get_first_child():
            self.console_list.remove(child)

        if consoles:
            self._append_console_sidebar_row(ALL_CONSOLES_ID)
        for console_id in consoles:
            self._append_console_sidebar_row(console_id)

    def _append_console_sidebar_row(self, console_id):
        row = Gtk.ListBoxRow()
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        box.set_margin_top(10)
        box.set_margin_bottom(10)
        box.set_margin_start(16)
        box.set_margin_end(16)

        icon_widget = self._build_console_icon(console_id)
        box.append(icon_widget)

        name = Gtk.Label(label=self._console_sidebar_label(console_id))
        name.set_halign(Gtk.Align.START)
        name.set_hexpand(True)
        box.append(name)

        row.set_child(box)
        row.id = console_id
        self.console_list.append(row)

    def _asset_path(self, category, filename):
        return Path(__file__).parent / "assets" / "icons" / category / filename

    def refresh_library(self):
        while child := self.content_stack.get_first_child():
            self.content_stack.remove(child)

        self._grids = {}
        self._console_pages = {}
        self._console_loaded = {}
        self._initial_roms = {}

        self.visible_consoles = self._discover_visible_consoles()
        self._rebuild_console_sidebar(self.visible_consoles)

        if self.visible_consoles:
            all_scroll = Gtk.ScrolledWindow()
            all_scroll.set_vexpand(True)
            self._console_pages[ALL_CONSOLES_ID] = all_scroll
            self._console_loaded[ALL_CONSOLES_ID] = False
            self.content_stack.add_titled(all_scroll, ALL_CONSOLES_ID, self.t("sidebar.all"))

            for console in self.visible_consoles:
                scroll = Gtk.ScrolledWindow()
                scroll.set_vexpand(True)
                placeholder = Gtk.Label(label=self.t("empty.select_console", console=console))
                placeholder.add_css_class("dim-label")
                placeholder.set_margin_top(32)
                scroll.set_child(placeholder)
                self._console_pages[console] = scroll
                self._console_loaded[console] = False
                self.content_stack.add_titled(scroll, console, console)

        if not self.visible_consoles:
            empty = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
            empty.set_valign(Gtk.Align.CENTER)
            empty.set_halign(Gtk.Align.CENTER)
            icon = Gtk.Image.new_from_icon_name("folder-open-symbolic")
            icon.set_pixel_size(64)
            icon.set_opacity(0.4)
            empty.append(icon)
            label = Gtk.Label(label="No ROMs found in configured system folders.")
            label.add_css_class("dim-label")
            empty.append(label)
            self.content_stack.add_titled(empty, "library-empty", "Library")

        self._build_settings_views()

        if self.visible_consoles:
            first_row = self.console_list.get_row_at_index(0)
            if first_row:
                self.console_list.select_row(first_row)
        else:
            self.current_console = None
            self._set_search_enabled(False)
            self.content_stack.set_visible_child_name("library-empty")

    def _discover_visible_consoles(self):
        visible = []
        for console in SYSTEM_IDS:
            if self.playlist_manager.playlist_exists(console):
                roms = self.playlist_manager.load_playlist(console)
            elif self.config_manager.auto_scan_on_first_open():
                roms = self.playlist_manager.scan_and_rebuild_playlist(console)
            else:
                roms = []

            if roms:
                visible.append(console)
                self._initial_roms[console] = roms
        return visible

    def _build_settings_views(self):
        settings_scroll = Gtk.ScrolledWindow()
        settings_scroll.set_vexpand(True)
        settings_grid = SettingsGrid()
        settings_callbacks = {
            "roms": self._open_settings_roms,
            "ui": self._open_settings_ui,
        }
        for item_id, fallback_icon in SETTINGS_ITEMS:
            icon_path = self._asset_path("settings", f"{item_id}.png")
            settings_grid.add_card(
                title=self.t(f"settings.{item_id}.title"),
                subtitle=self.t(f"settings.{item_id}.subtitle"),
                icon_path=str(icon_path) if icon_path.exists() else None,
                icon_name=fallback_icon,
                on_click=settings_callbacks.get(item_id),
            )
        settings_scroll.set_child(settings_grid)
        self.content_stack.add_titled(settings_scroll, "settings-main", self.t("settings.title"))

        roms_scroll = Gtk.ScrolledWindow()
        roms_scroll.set_vexpand(True)
        roms_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        breadcrumb_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        breadcrumb_bar.set_margin_top(14)
        breadcrumb_bar.set_margin_start(20)
        breadcrumb_bar.set_margin_end(20)
        breadcrumb_bar.set_margin_bottom(6)

        back_btn = Gtk.Button()
        back_btn.set_icon_name("go-previous-symbolic")
        back_btn.set_tooltip_text(self.t("settings.back.subtitle"))
        back_btn.connect("clicked", lambda _: self._open_settings_main())
        breadcrumb_bar.append(back_btn)

        crumb_label = Gtk.Label(label=f"{self.t('settings.title')} / {self.t('settings.roms.title')}")
        crumb_label.set_halign(Gtk.Align.START)
        crumb_label.add_css_class("dim-label")
        breadcrumb_bar.append(crumb_label)
        roms_container.append(breadcrumb_bar)

        roms_grid = SettingsGrid()
        roms_grid.add_card(
            title=self.t("settings.path.title"),
            subtitle=str(self.config_manager.get_roms_path()),
            icon_name="folder-symbolic",
        )
        roms_grid.add_card(
            title=self.t("settings.scan.title"),
            subtitle=self.t("settings.scan.subtitle"),
            icon_name="view-refresh-symbolic",
            on_click=self._scan_current_console,
        )
        roms_grid.add_card(
            title=self.t("settings.sync.title"),
            subtitle=self.t("settings.sync.subtitle"),
            icon_name="folder-download-symbolic",
            on_click=self._show_sync_covers_dialog,
        )

        roms_container.append(roms_grid)
        roms_scroll.set_child(roms_container)
        self.content_stack.add_titled(roms_scroll, "settings-roms", self.t("settings.roms.title"))

        ui_scroll = Gtk.ScrolledWindow()
        ui_scroll.set_vexpand(True)
        ui_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)

        ui_breadcrumb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        ui_breadcrumb.set_margin_top(14)
        ui_breadcrumb.set_margin_start(20)
        ui_breadcrumb.set_margin_end(20)
        ui_breadcrumb.set_margin_bottom(6)

        ui_back_btn = Gtk.Button()
        ui_back_btn.set_icon_name("go-previous-symbolic")
        ui_back_btn.set_tooltip_text(self.t("settings.back.subtitle"))
        ui_back_btn.connect("clicked", lambda _: self._open_settings_main())
        ui_breadcrumb.append(ui_back_btn)

        ui_crumb_label = Gtk.Label(label=f"{self.t('settings.title')} / {self.t('settings.ui.title')}")
        ui_crumb_label.set_halign(Gtk.Align.START)
        ui_crumb_label.add_css_class("dim-label")
        ui_breadcrumb.append(ui_crumb_label)
        ui_container.append(ui_breadcrumb)

        ui_panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        ui_panel.set_margin_top(12)
        ui_panel.set_margin_start(24)
        ui_panel.set_margin_end(24)
        ui_panel.set_margin_bottom(24)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.set_halign(Gtk.Align.FILL)
        row.set_hexpand(True)

        labels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        labels.set_halign(Gtk.Align.START)
        labels.set_hexpand(True)
        title = Gtk.Label(label=self.t("settings.ui.render_cartridge.title"))
        title.set_halign(Gtk.Align.START)
        labels.append(title)
        subtitle = Gtk.Label(label=self.t("settings.ui.render_cartridge.subtitle"))
        subtitle.set_halign(Gtk.Align.START)
        subtitle.add_css_class("dim-label")
        labels.append(subtitle)
        row.append(labels)

        self.render_cartridge_check = Gtk.CheckButton()
        self.render_cartridge_check.set_halign(Gtk.Align.END)
        self.render_cartridge_check.set_active(
            self.config_manager.get_ui_settings().get("render_cartridge_overlay", False)
        )
        self.render_cartridge_check.connect("toggled", self._on_toggle_render_cartridge)
        row.append(self.render_cartridge_check)

        ui_panel.append(row)
        ui_container.append(ui_panel)
        ui_scroll.set_child(ui_container)
        self.content_stack.add_titled(ui_scroll, "settings-ui", self.t("settings.ui.title"))

    def _on_console_selected(self, _listbox, row):
        if not row:
            return
        self.current_console = row.id
        self._set_search_enabled(True)
        if self.current_console == ALL_CONSOLES_ID:
            self._ensure_all_loaded()
        else:
            self._ensure_console_loaded(self.current_console)
        self.content_stack.set_visible_child_name(self.current_console)
        self.search_entry.set_text("")

    def _set_search_enabled(self, enabled):
        if not enabled:
            self.search_entry.set_text("")
        self.search_entry.set_sensitive(enabled)

    def _open_settings_main(self):
        self._set_search_enabled(False)
        self.console_list.unselect_all()
        self.content_stack.set_visible_child_name("settings-main")

    def _open_settings_roms(self):
        self._set_search_enabled(False)
        self.console_list.unselect_all()
        self.content_stack.set_visible_child_name("settings-roms")

    def _open_settings_ui(self):
        self._set_search_enabled(False)
        self.console_list.unselect_all()
        self.content_stack.set_visible_child_name("settings-ui")

    def _on_toggle_render_cartridge(self, button):
        self.config_manager.set_render_cartridge_overlay(button.get_active())
        if self.current_console == ALL_CONSOLES_ID:
            self._ensure_all_loaded()
        elif self.current_console in self._console_pages:
            self._ensure_console_loaded(self.current_console)

    def _ensure_console_loaded(self, console, force_rescan=False):
        if console == ALL_CONSOLES_ID:
            self._ensure_all_loaded(force_rescan=force_rescan)
            return
        if console not in self._console_pages:
            return

        created_playlist = False
        if force_rescan:
            roms = self.playlist_manager.scan_and_rebuild_playlist(console)
            created_playlist = True
        elif not self._console_loaded.get(console) and console in self._initial_roms:
            roms = self._initial_roms[console]
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

    def _ensure_all_loaded(self, force_rescan=False):
        if ALL_CONSOLES_ID not in self._console_pages:
            return

        all_roms = []
        for console in self.visible_consoles:
            if force_rescan:
                roms = self.playlist_manager.scan_and_rebuild_playlist(console)
                self._console_loaded[console] = True
            elif not self._console_loaded.get(console) and console in self._initial_roms:
                roms = self._initial_roms[console]
            else:
                roms = self.playlist_manager.load_playlist(console)
            all_roms.extend(roms)

        all_roms.sort(key=lambda rom: (rom.get("console", ""), rom.get("name", "").lower()))
        self._render_console_page(ALL_CONSOLES_ID, all_roms)
        self._console_loaded[ALL_CONSOLES_ID] = True

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

            if console == ALL_CONSOLES_ID:
                empty_label = Gtk.Label(label=self.t("empty.all_indexed"))
            else:
                empty_label = Gtk.Label(label=self.t("empty.indexed", console=console))
            empty_label.add_css_class("dim-label")
            empty_box.append(empty_label)

            if console != ALL_CONSOLES_ID:
                path_label = Gtk.Label(label=str(self.playlist_manager.get_playlist_path(console)))
                path_label.add_css_class("caption")
                path_label.add_css_class("dim-label")
                empty_box.append(path_label)
            scroll.set_child(empty_box)
            self._grids.pop(console, None)
            return

        grid = RomGrid(
            console,
            roms,
            self.on_launch_game,
            self.roms_path,
            ui_settings=self.config_manager.get_ui_settings(),
        )
        self._grids[console] = grid
        scroll.set_child(grid)

    def _scan_current_console(self):
        if not self.current_console or self.current_console == ALL_CONSOLES_ID:
            return
        self._ensure_console_loaded(self.current_console, force_rescan=True)
        toast = Adw.Toast(title=self.t("toast.playlist_rebuilt", console=self.current_console))
        toast.set_timeout(4)
        self.toast_overlay.add_toast(toast)

    def _show_sync_covers_dialog(self):
        if not self.visible_consoles:
            toast = Adw.Toast(title="No indexed consoles to sync covers.")
            toast.set_timeout(3)
            self.toast_overlay.add_toast(toast)
            return

        dialog = Gtk.Dialog(transient_for=self, modal=True)
        dialog.set_title(self.t("dialog.sync.title"))
        dialog.set_default_size(360, 120)
        dialog.add_button(self.t("dialog.cancel"), Gtk.ResponseType.CANCEL)
        dialog.add_button(self.t("dialog.start"), Gtk.ResponseType.OK)

        content = dialog.get_content_area()
        content.set_spacing(10)
        content.set_margin_top(12)
        content.set_margin_bottom(12)
        content.set_margin_start(12)
        content.set_margin_end(12)

        label = Gtk.Label(label=self.t("dialog.sync.scope"))
        label.set_halign(Gtk.Align.START)
        content.append(label)

        combo = Gtk.ComboBoxText()
        combo.append("all", self.t("dialog.sync.all"))
        for console in self.visible_consoles:
            combo.append(console, self.t("dialog.sync.console", console=console))
        default_scope = "all" if self.current_console == ALL_CONSOLES_ID else (self.current_console or self.visible_consoles[0])
        combo.set_active_id(default_scope)
        content.append(combo)

        def _on_response(_dlg, response):
            if response == Gtk.ResponseType.OK:
                selected = combo.get_active_id() or self.current_console or self.visible_consoles[0]
                if selected == "all":
                    self._start_cover_sync(scope="all", selected_console=None)
                else:
                    self._start_cover_sync(scope="console", selected_console=selected)
            dialog.close()

        dialog.connect("response", _on_response)
        dialog.show()

    def _start_cover_sync(self, scope, selected_console):
        if self._cover_sync_running:
            toast = Adw.Toast(title=self.t("toast.sync_running"))
            toast.set_timeout(3)
            self.toast_overlay.add_toast(toast)
            return

        library = {}
        if scope == "console" and selected_console in self.visible_consoles:
            library[selected_console] = self.playlist_manager.load_playlist(selected_console)
        else:
            for console in self.visible_consoles:
                library[console] = self.playlist_manager.load_playlist(console)

        self._cover_sync_running = True
        toast = Adw.Toast(title=self.t("toast.sync_started"))
        toast.set_timeout(3)
        self.toast_overlay.add_toast(toast)

        def _on_done(summary):
            GLib.idle_add(self._on_cover_sync_done_ui, summary)

        sync_covers_async(
            library_by_console=library,
            covers_dir=self.roms_path,
            scope=scope,
            selected_console=selected_console,
            on_done=_on_done,
            sync_settings=self.config_manager.get_cover_sync_settings(),
        )

    def _on_cover_sync_done_ui(self, summary):
        self._cover_sync_running = False
        toast = Adw.Toast(
            title=self.t(
                "toast.sync_done",
                downloaded=summary["downloaded"],
                skipped=summary["skipped"],
                errors=summary["errors"],
            )
        )
        toast.set_timeout(6)
        self.toast_overlay.add_toast(toast)
        if self.current_console == ALL_CONSOLES_ID:
            self._ensure_all_loaded()
        elif self.current_console in self._grids:
            self._ensure_console_loaded(self.current_console)
        return False

    def _on_refresh_clicked(self, _button):
        visible = self.content_stack.get_visible_child_name()
        if visible == ALL_CONSOLES_ID:
            self._ensure_all_loaded()
            self._on_search_changed(self.search_entry)
            return
        if visible in set(self.visible_consoles):
            self._ensure_console_loaded(visible)
            self._on_search_changed(self.search_entry)
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
            toast = Adw.Toast(
                title=self.t("toast.running", name=rom["name"], console=rom["console"])
            )
            toast.set_timeout(3)
            self.toast_overlay.add_toast(toast)

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
            toast = Adw.Toast(title=self.t("toast.finished", name=rom_name, code=result["exit_code"]))
            toast.set_timeout(4)
            self.toast_overlay.add_toast(toast)
        self._sync_runtime_controls()
        return True

    def _sync_runtime_controls(self):
        is_running = self.runtime_manager.is_running()
        self.stop_btn.set_sensitive(is_running)
