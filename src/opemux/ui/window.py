import os
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Gdk, GLib, Gio

from opemux.core.cover_sync import sync_covers_async
from opemux.core.input_actions import ACTION_ORDER, get_actions_for_console
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
SIDEBAR_ICON_FILES = {
    "FC": "nintendo_fds__famicom_library@2x.png",
    "SFC": "supernes__snes_usa_library@2x.png",
    "GBA": "gameboy_advance__gba_library@2x.png",
}


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
        self._input_buttons = {}
        self._input_rows = {}
        self._input_loaded_profile = None
        self._input_bindings_buffer = {}
        self._capture_active_action = None
        self._capture_sequence_mode = False
        self._capture_sequence_index = -1
        self._capture_sequence_actions = list(ACTION_ORDER)
        self._visible_input_actions = list(ACTION_ORDER)

        self._input_key_controller = Gtk.EventControllerKey()
        self._input_key_controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        self._input_key_controller.connect("key-pressed", self._on_input_key_pressed)
        self.add_controller(self._input_key_controller)

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
        self._maybe_show_bootstrap_warning()
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
        icon_filename = SIDEBAR_ICON_FILES.get(console_id, f"{console_id.lower()}.png")
        icon_path = self._asset_path("systems", icon_filename)
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

    def _maybe_show_bootstrap_warning(self):
        state = self.config_manager.get_bootstrap_state()
        if state.get("status") != "failed":
            return
        failed_step = state.get("failed_step", "-")
        toast = Adw.Toast(title=self.t("toast.bootstrap.failed", step=failed_step))
        toast.set_timeout(6)
        self.toast_overlay.add_toast(toast)

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
            "input": self._open_settings_input,
            "ui": self._open_settings_ui,
            "system": self._open_settings_system,
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
            on_click=self._choose_roms_path,
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

        input_scroll = Gtk.ScrolledWindow()
        input_scroll.set_vexpand(True)
        input_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)

        input_breadcrumb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        input_breadcrumb.set_margin_top(14)
        input_breadcrumb.set_margin_start(20)
        input_breadcrumb.set_margin_end(20)
        input_breadcrumb.set_margin_bottom(6)

        input_back_btn = Gtk.Button()
        input_back_btn.set_icon_name("go-previous-symbolic")
        input_back_btn.set_tooltip_text(self.t("settings.back.subtitle"))
        input_back_btn.connect("clicked", lambda _: self._open_settings_main())
        input_breadcrumb.append(input_back_btn)

        input_crumb_label = Gtk.Label(label=f"{self.t('settings.title')} / {self.t('settings.input.title')}")
        input_crumb_label.set_halign(Gtk.Align.START)
        input_crumb_label.add_css_class("dim-label")
        input_breadcrumb.append(input_crumb_label)
        input_container.append(input_breadcrumb)

        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        toolbar.set_margin_start(20)
        toolbar.set_margin_end(20)
        toolbar.set_margin_top(4)
        toolbar.set_margin_bottom(6)

        console_label = Gtk.Label(label=self.t("input.console"))
        console_label.set_halign(Gtk.Align.START)
        toolbar.append(console_label)

        self.input_console_combo = Gtk.ComboBoxText()
        for console_id in SYSTEM_IDS:
            self.input_console_combo.append(console_id, f"{console_id} - {get_system_display_name(console_id)}")
        self.input_console_combo.connect("changed", self._on_input_console_changed)
        toolbar.append(self.input_console_combo)

        device_label = Gtk.Label(label=self.t("input.device"))
        device_label.set_halign(Gtk.Align.START)
        toolbar.append(device_label)

        self.input_device_combo = Gtk.ComboBoxText()
        self.input_device_combo.append("keyboard", self.t("input.device.keyboard"))
        self.input_device_combo.append("gamepad_p1", self.t("input.device.gamepad_p1"))
        self.input_device_combo.connect("changed", self._on_input_device_changed)
        toolbar.append(self.input_device_combo)

        save_btn = Gtk.Button(label=self.t("input.save"))
        save_btn.connect("clicked", lambda _: self._save_input_settings())
        toolbar.append(save_btn)

        reset_btn = Gtk.Button(label=self.t("input.reset"))
        reset_btn.connect("clicked", lambda _: self._reset_input_defaults())
        toolbar.append(reset_btn)

        self.input_map_all_btn = Gtk.Button(label=self.t("input.map_all"))
        self.input_map_all_btn.connect("clicked", lambda _: self._start_map_all_sequence())
        toolbar.append(self.input_map_all_btn)

        self.input_capture_status = Gtk.Label(label="")
        self.input_capture_status.set_halign(Gtk.Align.START)
        self.input_capture_status.add_css_class("dim-label")
        self.input_capture_status.set_hexpand(True)
        toolbar.append(self.input_capture_status)

        input_container.append(toolbar)

        self.input_bindings_list = Gtk.ListBox()
        self.input_bindings_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self.input_bindings_list.set_margin_start(20)
        self.input_bindings_list.set_margin_end(20)
        self.input_bindings_list.set_margin_bottom(24)
        input_container.append(self.input_bindings_list)

        input_scroll.set_child(input_container)
        self.content_stack.add_titled(input_scroll, "settings-input", self.t("settings.input.title"))

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

        system_scroll = Gtk.ScrolledWindow()
        system_scroll.set_vexpand(True)
        system_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)

        system_breadcrumb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        system_breadcrumb.set_margin_top(14)
        system_breadcrumb.set_margin_start(20)
        system_breadcrumb.set_margin_end(20)
        system_breadcrumb.set_margin_bottom(6)

        system_back_btn = Gtk.Button()
        system_back_btn.set_icon_name("go-previous-symbolic")
        system_back_btn.set_tooltip_text(self.t("settings.back.subtitle"))
        system_back_btn.connect("clicked", lambda _: self._open_settings_main())
        system_breadcrumb.append(system_back_btn)

        system_crumb_label = Gtk.Label(label=f"{self.t('settings.title')} / {self.t('settings.system.title')}")
        system_crumb_label.set_halign(Gtk.Align.START)
        system_crumb_label.add_css_class("dim-label")
        system_breadcrumb.append(system_crumb_label)
        system_container.append(system_breadcrumb)

        system_grid = SettingsGrid()
        state = self.config_manager.get_bootstrap_state()
        status = state.get("status", "pending")
        failed_step = state.get("failed_step")
        if status == "completed":
            setup_subtitle = self.t("settings.system.bootstrap.ok")
        elif status == "failed":
            setup_subtitle = self.t("settings.system.bootstrap.failed", step=failed_step or "-")
        else:
            setup_subtitle = self.t("settings.system.bootstrap.pending")

        system_grid.add_card(
            title=self.t("settings.system.bootstrap.title"),
            subtitle=setup_subtitle,
            icon_name="system-software-update-symbolic",
        )
        system_grid.add_card(
            title=self.t("settings.system.bootstrap.retry.title"),
            subtitle=self.t("settings.system.bootstrap.retry.subtitle"),
            icon_name="view-refresh-symbolic",
            on_click=self._trigger_bootstrap_retry,
        )
        system_container.append(system_grid)
        system_scroll.set_child(system_container)
        self.content_stack.add_titled(system_scroll, "settings-system", self.t("settings.system.title"))

        self.input_console_combo.set_active_id(self.current_console if self.current_console in SYSTEM_IDS else SYSTEM_IDS[0])
        self.input_device_combo.set_active_id("keyboard")
        self._refresh_input_bindings()

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

    def _choose_roms_path(self):
        chooser = Gtk.FileChooserDialog(
            title=self.t("settings.path.dialog_title"),
            transient_for=self,
            modal=True,
            action=Gtk.FileChooserAction.SELECT_FOLDER,
        )
        chooser.add_button(self.t("dialog.cancel"), Gtk.ResponseType.CANCEL)
        chooser.add_button(self.t("settings.path.select_button"), Gtk.ResponseType.ACCEPT)
        current = self.config_manager.get_roms_path()
        if current.exists():
            chooser.set_current_folder(Gio.File.new_for_path(str(current)))
        chooser.connect("response", self._on_choose_roms_path_response)
        chooser.show()

    def _on_choose_roms_path_response(self, chooser, response):
        if response != Gtk.ResponseType.ACCEPT:
            chooser.destroy()
            return

        selected_file = chooser.get_file()
        chooser.destroy()
        if not selected_file:
            return

        selected_path = selected_file.get_path()
        if not selected_path:
            toast = Adw.Toast(title=self.t("toast.path_invalid"))
            toast.set_timeout(3)
            self.toast_overlay.add_toast(toast)
            return

        self.config_manager.set_roms_path(selected_path)
        self.config_manager.ensure_rom_directories()
        self.roms_path = self.config_manager.get_roms_path()
        self.scanner = RomScanner(self.roms_path)
        self.playlist_manager = PlaylistManager(self.config_manager, self.scanner)
        self._rescan_all_consoles(show_toast=False)

        toast = Adw.Toast(title=self.t("toast.path_updated", path=str(self.roms_path)))
        toast.set_timeout(4)
        self.toast_overlay.add_toast(toast)

    def _open_settings_ui(self):
        self._set_search_enabled(False)
        self.console_list.unselect_all()
        self.content_stack.set_visible_child_name("settings-ui")

    def _open_settings_input(self):
        self._set_search_enabled(False)
        self.console_list.unselect_all()
        self.content_stack.set_visible_child_name("settings-input")
        self._refresh_input_bindings()

    def _open_settings_system(self):
        self._set_search_enabled(False)
        self.console_list.unselect_all()
        self.content_stack.set_visible_child_name("settings-system")

    def _on_input_console_changed(self, _combo):
        self._cancel_input_capture()
        self._refresh_input_bindings()

    def _on_input_device_changed(self, _combo):
        self._cancel_input_capture()
        self._refresh_input_bindings()

    def _input_action_label(self, action):
        return self.t(f"input.action.{action}")

    def _clear_input_bindings_rows(self):
        while child := self.input_bindings_list.get_first_child():
            self.input_bindings_list.remove(child)
        self._input_buttons = {}
        self._input_rows = {}

    def _set_active_input_row(self, action=None):
        for row_action, row in self._input_rows.items():
            if row_action == action:
                row.add_css_class("input-mapping-current")
            else:
                row.remove_css_class("input-mapping-current")

    def _refresh_input_bindings(self):
        if not hasattr(self, "input_bindings_list"):
            return
        console_id = self.input_console_combo.get_active_id() or SYSTEM_IDS[0]
        device_id = self.input_device_combo.get_active_id() or "keyboard"
        profile = self.config_manager.get_input_profile(console_id)
        if device_id not in profile.get("devices", {}):
            device_id = "keyboard"
            self.input_device_combo.set_active_id(device_id)
        device = profile.get("devices", {}).get(device_id, {})
        bindings = device.get("bindings", {})
        visible_actions = get_actions_for_console(console_id)

        self._input_loaded_profile = profile
        self._visible_input_actions = list(visible_actions)
        self._capture_sequence_actions = list(visible_actions)
        self._input_bindings_buffer = {
            action: str(bindings.get(action, "")).strip().lower() for action in visible_actions
        }
        self._clear_input_bindings_rows()
        self.input_map_all_btn.set_sensitive(device_id == "keyboard")
        self.input_capture_status.set_text("")

        for action in visible_actions:
            row = Gtk.ListBoxRow()
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            box.set_margin_top(6)
            box.set_margin_bottom(6)
            box.set_margin_start(8)
            box.set_margin_end(8)

            label = Gtk.Label(label=self._input_action_label(action))
            label.set_halign(Gtk.Align.START)
            label.set_hexpand(True)
            box.append(label)

            button = Gtk.Button(label=self._binding_display_text(self._input_bindings_buffer.get(action, "")))
            button.set_hexpand(False)
            button.set_size_request(180, -1)
            button.connect("clicked", self._on_binding_button_clicked, action)
            box.append(button)
            self._input_buttons[action] = button

            row.set_child(box)
            self.input_bindings_list.append(row)
            self._input_rows[action] = row

    def _binding_display_text(self, value):
        if not value:
            return self.t("input.binding.empty")
        return value

    def _set_binding_value(self, action, value):
        value = (value or "").strip().lower()

        # Enforce unique mapping per visible action list.
        if value:
            for other_action, other_value in list(self._input_bindings_buffer.items()):
                if other_action == action:
                    continue
                if other_value == value:
                    self._input_bindings_buffer[other_action] = ""
                    if other_action in self._input_buttons:
                        self._input_buttons[other_action].set_label(self._binding_display_text(""))

        self._input_bindings_buffer[action] = value
        if action in self._input_buttons:
            self._input_buttons[action].set_label(self._binding_display_text(value))

    def _set_capture_status(self, text=""):
        if hasattr(self, "input_capture_status"):
            self.input_capture_status.set_text(text)

    def _on_binding_button_clicked(self, _button, action):
        device_id = self.input_device_combo.get_active_id() or "keyboard"
        if device_id != "keyboard":
            toast = Adw.Toast(title=self.t("input.capture.keyboard_only"))
            toast.set_timeout(3)
            self.toast_overlay.add_toast(toast)
            return
        self._start_action_capture(action, sequence_mode=False)

    def _start_action_capture(self, action, sequence_mode):
        if action not in self._input_buttons:
            return
        self._capture_active_action = action
        self._capture_sequence_mode = sequence_mode
        self._input_buttons[action].set_label(self.t("input.capture.waiting"))
        self._set_active_input_row(action)
        self._set_capture_status(self.t("input.capture.waiting_for", action=self._input_action_label(action)))

    def _cancel_input_capture(self, show_toast=False):
        if self._capture_active_action in self._input_buttons:
            action = self._capture_active_action
            self._input_buttons[action].set_label(self._binding_display_text(self._input_bindings_buffer.get(action, "")))
        self._capture_active_action = None
        was_sequence = self._capture_sequence_mode
        self._capture_sequence_mode = False
        self._capture_sequence_index = -1
        self._set_active_input_row(None)
        self._set_capture_status("")
        if show_toast and was_sequence:
            toast = Adw.Toast(title=self.t("input.capture.cancelled"))
            toast.set_timeout(3)
            self.toast_overlay.add_toast(toast)

    def _start_map_all_sequence(self):
        device_id = self.input_device_combo.get_active_id() or "keyboard"
        if device_id != "keyboard":
            toast = Adw.Toast(title=self.t("input.capture.keyboard_only"))
            toast.set_timeout(3)
            self.toast_overlay.add_toast(toast)
            return
        if not self._capture_sequence_actions:
            return
        self._cancel_input_capture()
        self._capture_sequence_mode = True
        self._capture_sequence_index = 0
        self._start_action_capture(self._capture_sequence_actions[0], sequence_mode=True)

    def _normalize_captured_key(self, keyval):
        key_name = Gdk.keyval_name(keyval)
        if not key_name:
            return ""
        special = {
            "Return": "enter",
            "KP_Enter": "enter",
            "Escape": "escape",
            "space": "space",
            "Up": "up",
            "Down": "down",
            "Left": "left",
            "Right": "right",
            "Shift_L": "left shift",
            "Shift_R": "right shift",
            "Control_L": "left ctrl",
            "Control_R": "right ctrl",
            "Alt_L": "left alt",
            "Alt_R": "right alt",
            "Super_L": "left super",
            "Super_R": "right super",
        }
        if key_name in special:
            return special[key_name]
        return key_name.lower()

    def _on_input_key_pressed(self, _controller, keyval, _keycode, _state):
        visible = self.content_stack.get_visible_child_name()
        if visible != "settings-input":
            return False
        if not self._capture_active_action:
            return False
        device_id = self.input_device_combo.get_active_id() or "keyboard"
        if device_id != "keyboard":
            return False

        key_name = self._normalize_captured_key(keyval)
        action = self._capture_active_action
        if key_name == "escape":
            if self._capture_sequence_mode:
                self._cancel_input_capture(show_toast=True)
            else:
                self._set_binding_value(action, "")
                self._cancel_input_capture()
            return True

        if not key_name:
            return True

        self._set_binding_value(action, key_name)

        if not self._capture_sequence_mode:
            self._cancel_input_capture()
            return True

        self._capture_sequence_index += 1
        if self._capture_sequence_index >= len(self._capture_sequence_actions):
            self._cancel_input_capture()
            toast = Adw.Toast(title=self.t("input.capture.completed"))
            toast.set_timeout(3)
            self.toast_overlay.add_toast(toast)
            return True

        next_action = self._capture_sequence_actions[self._capture_sequence_index]
        self._start_action_capture(next_action, sequence_mode=True)
        return True

    def _save_input_settings(self):
        console_id = self.input_console_combo.get_active_id() or SYSTEM_IDS[0]
        device_id = self.input_device_combo.get_active_id() or "keyboard"
        profile = self._input_loaded_profile or self.config_manager.get_input_profile(console_id)
        devices = profile.setdefault("devices", {})
        device = devices.setdefault(device_id, {"type": "keyboard" if device_id == "keyboard" else "gamepad", "bindings": {}})
        bindings = device.setdefault("bindings", {})
        valid_actions = get_actions_for_console(console_id)
        new_bindings = {}
        for action in valid_actions:
            new_bindings[action] = self._input_bindings_buffer.get(action, "")
        device["bindings"] = new_bindings
        profile["active_device"] = device_id
        self.config_manager.save_input_profile(console_id, profile)
        self._input_loaded_profile = profile
        toast = Adw.Toast(title=self.t("toast.input_saved", console=console_id))
        toast.set_timeout(3)
        self.toast_overlay.add_toast(toast)

    def _reset_input_defaults(self):
        console_id = self.input_console_combo.get_active_id() or SYSTEM_IDS[0]
        profile = self.config_manager.reset_input_profile(console_id)
        self._input_loaded_profile = profile
        self._cancel_input_capture()
        self._refresh_input_bindings()
        toast = Adw.Toast(title=self.t("toast.input_reset", console=console_id))
        toast.set_timeout(3)
        self.toast_overlay.add_toast(toast)

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
        # Settings > ROMs > Scan ROMs now performs a global library rebuild.
        self._rescan_all_consoles(show_toast=True)

    def _rescan_single_console(self, console, show_toast=False):
        if not console or console == ALL_CONSOLES_ID:
            return self._rescan_all_consoles(show_toast=show_toast)
        self._ensure_console_loaded(console, force_rescan=True)
        self._on_search_changed(self.search_entry)
        if show_toast:
            toast = Adw.Toast(title=self.t("toast.playlist_rebuilt", console=console))
            toast.set_timeout(4)
            self.toast_overlay.add_toast(toast)
        return {"console": console}

    def _rescan_all_consoles(self, show_toast=False):
        summary = self.playlist_manager.scan_and_rebuild_all_playlists()
        self.refresh_library()
        self._on_search_changed(self.search_entry)
        if show_toast:
            toast = Adw.Toast(
                title=self.t(
                    "toast.playlists_rebuilt_all",
                    consoles=summary["total_consoles"],
                    roms=summary["total_roms"],
                )
            )
            toast.set_timeout(4)
            self.toast_overlay.add_toast(toast)
        return summary

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
            self._rescan_all_consoles(show_toast=False)
            return
        if visible in set(self.visible_consoles):
            self._rescan_single_console(visible, show_toast=False)
        elif visible == "settings-roms":
            self._rescan_all_consoles(show_toast=False)

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

    def _trigger_bootstrap_retry(self):
        app = self.get_application()
        if not hasattr(app, "request_bootstrap_retry_from_ui"):
            return
        started = app.request_bootstrap_retry_from_ui(self)
        if not started:
            toast = Adw.Toast(title=self.t("toast.bootstrap.already_running"))
            toast.set_timeout(3)
            self.toast_overlay.add_toast(toast)
            return
        toast = Adw.Toast(title=self.t("toast.bootstrap.retry_started"))
        toast.set_timeout(3)
        self.toast_overlay.add_toast(toast)

    def on_bootstrap_finished(self, result):
        if result.get("success"):
            toast = Adw.Toast(title=self.t("toast.bootstrap.completed"))
            toast.set_timeout(4)
            self.toast_overlay.add_toast(toast)
            return
        failed_step = result.get("failed_step", "-")
        toast = Adw.Toast(title=self.t("toast.bootstrap.failed", step=failed_step))
        toast.set_timeout(6)
        self.toast_overlay.add_toast(toast)
