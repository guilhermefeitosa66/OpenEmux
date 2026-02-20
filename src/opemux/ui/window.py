import os
import subprocess
import logging
from threading import Thread
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Gdk, GLib, Gio

from opemux.core.bios_manager import get_console_bios_dir, scan_all_bios_status
from opemux.core.cover_sync import sync_covers_async
from opemux.core.input_actions import ACTION_ORDER, get_actions_for_console
from opemux.core.playlist_manager import PlaylistManager
from opemux.core.runtime_manager import RuntimeManager
from opemux.core.scraper import SUPPORTED_COVER_EXTS, find_local_cover, remove_local_covers, save_local_cover
from opemux.core.scanner import RomScanner
from opemux.core.shaders import ShaderCatalog, normalize_shader_id
from opemux.core.systems import SYSTEM_IDS, get_icon_name, get_system_display_name
from opemux.i18n import LANGUAGE_META, SUPPORTED_LOCALES, normalize_locale, tr
from opemux.ui.grid import RomGrid
from opemux.ui.settings_grid import SettingsGrid

logger = logging.getLogger(__name__)

SETTINGS_ITEMS = [
    ("roms", "folder-symbolic"),
    ("bios", "media-floppy-symbolic"),
    ("input", "input-gaming-symbolic"),
    ("ui", "preferences-desktop-theme-symbolic"),
    ("shaders", "applications-graphics-symbolic"),
    ("system", "applications-system-symbolic"),
]
ALL_CONSOLES_ID = "__all__"
FAVORITES_ID = "__favorites__"
CONSOLE_ICON_FILES = {
    "A2600": "atari_2600__atari2600_library@2x.png",
    "A5200": "atari_5200__atari5200_library@2x.png",
    "A7800": "atari_7800__atari7800_library@2x.png",
    "LYNX": "lynx__lynx_library@2x.png",
    "CV": "colecovision__colecovision_library@2x.png",
    "FDS": "nintendo_fds__famicom_library@2x.png",
    "FC": "nintendo_fds__famicom_library@2x.png",
    "GB": "gameboy__gameboy_library@2x.png",
    "GBC": "gameboy__gameboy_library@2x.png",
    "GBA": "gameboy_advance__gba_library@2x.png",
    "GG": "gamegear__gamegear_library@2x.png",
    "INTV": "intellivision__intellivision_library@2x.png",
    "NGP": "neogeopocket__neogeopocket_library@2x.png",
    "N64": "n64__n64_library@2x.png",
    "NDS": "nds__nds_library@2x.png",
    "GC": "gamecube__gamecube_library@2x.png",
    "O2": "odyssey2__odyssey2_library@2x.png",
    "SG1000": "sg_1000__sg1000_library@2x.png",
    "S32X": "sega_32x__32x_na_library@2x.png",
    "MCD": "sega_cd__segacd_library@2x.png",
    "MD": "genesis__megadrive_library@2x.png",
    "SMS": "segamastersystem__sms_library@2x.png",
    "SATURN": "saturn__saturn_library@2x.png",
    "PS": "playstation__psx_library@2x.png",
    "PSP": "psp__psp_library@2x.png",
    "SFC": "supernes__snes_usa_library@2x.png",
    "PCE": "pc_engine__pcengine_library@2x.png",
    "PCECD": "pc_engine_cd__pcenginecd_library@2x.png",
    "VECTREX": "vectrex__vectrex_library@2x.png",
    "VB": "virtual_boy__vb_library@2x.png",
    "WS": "wonderswan__wonderswan_library@2x.png",
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
        self._scan_running = False
        self._task_seq = 0
        self._tasks = {}

        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
        self.runtime_manager = RuntimeManager(project_root, self.config_manager)
        self.project_root = Path(project_root)
        self.shader_catalog = ShaderCatalog(runtime_dir=self.config_manager.get_runtime_dir())

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
        self._bios_status_by_console = {}

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
        self.content_stack.connect("notify::visible-child-name", self._on_visible_child_changed)
        self.content_box.append(self.content_stack)
        self.status_bar = self._build_status_bar()
        self.content_box.append(self.status_bar)
        self.main_box.append(self.content_box)

        self._click_debug_controller = Gtk.GestureClick()
        self._click_debug_controller.set_button(0)
        self._click_debug_controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        self._click_debug_controller.connect("pressed", self._on_global_click_pressed)
        self.add_controller(self._click_debug_controller)

        self.refresh_library()
        self._start_startup_scan()
        self._maybe_show_bootstrap_warning()
        GLib.timeout_add_seconds(1, self._poll_runtime_state)

    def _on_global_click_pressed(self, gesture, n_press, x, y):
        button = gesture.get_current_button()
        # Avoid Gtk.Widget.pick() here: dropdown/popover interactions may trigger
        # compute_point assertions while transient widgets are being recycled.
        target = self.get_focus()
        logger.info(
            "ui click: button=%s presses=%s target=%s view=%s current_console=%s x=%.1f y=%.1f",
            button,
            n_press,
            self._describe_widget(target),
            self.content_stack.get_visible_child_name(),
            self.current_console,
            x,
            y,
        )

    def _describe_widget(self, widget):
        if widget is None:
            return "None"
        name = widget.__class__.__name__
        if isinstance(widget, Gtk.Button):
            child = widget.get_child()
            if isinstance(child, Gtk.Label):
                return f"{name}(label={child.get_text()})"
            return f"{name}(button)"
        if isinstance(widget, Gtk.Label):
            return f"{name}(text={widget.get_text()})"
        if isinstance(widget, Gtk.Image):
            return f"{name}(icon={widget.get_icon_name()})"
        return name

    def _on_visible_child_changed(self, _stack, _param):
        logger.info(
            "ui view changed: visible_view=%s current_console=%s",
            self.content_stack.get_visible_child_name(),
            self.current_console,
        )

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

    def _build_language_dropdown(self):
        model = Gtk.StringList.new(SUPPORTED_LOCALES)
        dropdown = Gtk.DropDown.new(model, None)
        dropdown._locale_ids = list(SUPPORTED_LOCALES)

        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._on_language_dropdown_setup)
        factory.connect("bind", self._on_language_dropdown_bind)
        dropdown.set_factory(factory)

        list_factory = Gtk.SignalListItemFactory()
        list_factory.connect("setup", self._on_language_dropdown_setup)
        list_factory.connect("bind", self._on_language_dropdown_bind)
        dropdown.set_list_factory(list_factory)

        self._set_language_dropdown_active_id(dropdown, self.locale)
        return dropdown

    def _on_language_dropdown_setup(self, _factory, list_item):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.set_margin_top(4)
        row.set_margin_bottom(4)
        row.set_margin_start(4)
        row.set_margin_end(4)
        list_item.set_child(row)

    def _on_language_dropdown_bind(self, _factory, list_item):
        row = list_item.get_child()
        while child := row.get_first_child():
            row.remove(child)
        item = list_item.get_item()
        locale_id = item.get_string() if item else "en"
        meta = LANGUAGE_META.get(locale_id, LANGUAGE_META["en"])
        label = Gtk.Label(label=f"{meta['flag']} {meta['native_name']}")
        label.set_halign(Gtk.Align.START)
        label.set_xalign(0)
        row.append(label)

    def _get_language_dropdown_active_id(self, dropdown):
        idx = int(dropdown.get_selected())
        ids = getattr(dropdown, "_locale_ids", [])
        if idx < 0 or idx >= len(ids):
            return "en"
        return normalize_locale(ids[idx])

    def _set_language_dropdown_active_id(self, dropdown, locale):
        locale = normalize_locale(locale)
        ids = getattr(dropdown, "_locale_ids", [])
        if locale in ids:
            dropdown.set_selected(ids.index(locale))
            return
        dropdown.set_selected(0)

    def _on_language_changed(self, *_args):
        if not hasattr(self, "language_dropdown"):
            return
        selected = self._get_language_dropdown_active_id(self.language_dropdown)
        if selected == self.locale:
            return
        self.config_manager.set_locale(selected)
        self.locale = selected
        language_name = LANGUAGE_META.get(selected, LANGUAGE_META["en"])["native_name"]
        self._reload_ui_texts_after_locale_change(language_name)

    def _reload_ui_texts_after_locale_change(self, language_name):
        visible = self.content_stack.get_visible_child_name()
        self.search_entry.set_placeholder_text(self.t("header.search"))
        self.search_entry.set_tooltip_text(self.t("header.search"))
        self.stop_btn.set_tooltip_text(self.t("header.stop"))
        self.refresh_library(preferred_view=visible or "settings-system")
        toast = Adw.Toast(title=self.t("toast.language.updated", language=language_name))
        toast.set_timeout(3)
        self.toast_overlay.add_toast(toast)

    def _build_console_dropdown(self, console_ids, default_id=None, include_all=False, all_label_key=None):
        ids = []
        if include_all:
            ids.append(ALL_CONSOLES_ID)
        ids.extend(console_ids)

        model = Gtk.StringList.new(ids)
        dropdown = Gtk.DropDown.new(model, None)
        dropdown._console_ids = ids
        dropdown._all_label_key = all_label_key

        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._on_console_dropdown_setup)
        factory.connect("bind", self._on_console_dropdown_bind)
        dropdown.set_factory(factory)

        list_factory = Gtk.SignalListItemFactory()
        list_factory.connect("setup", self._on_console_dropdown_setup)
        list_factory.connect("bind", self._on_console_dropdown_bind)
        dropdown.set_list_factory(list_factory)

        self._set_console_dropdown_active_id(dropdown, default_id or (ALL_CONSOLES_ID if include_all else ids[0]))
        return dropdown

    def _on_console_dropdown_setup(self, _factory, list_item):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        row.set_margin_top(4)
        row.set_margin_bottom(4)
        row.set_margin_start(4)
        row.set_margin_end(4)
        list_item.set_child(row)

    def _on_console_dropdown_bind(self, _factory, list_item):
        row = list_item.get_child()
        while child := row.get_first_child():
            row.remove(child)

        item = list_item.get_item()
        console_id = item.get_string() if item else ""

        icon = self._build_console_icon(console_id)
        row.append(icon)

        if console_id == ALL_CONSOLES_ID:
            label_text = self.t("sidebar.all")
        else:
            label_text = f"{console_id} - {get_system_display_name(console_id)}"

        label = Gtk.Label(label=label_text)
        label.set_halign(Gtk.Align.START)
        label.set_xalign(0)
        row.append(label)

    def _get_console_dropdown_active_id(self, dropdown):
        idx = int(dropdown.get_selected())
        ids = getattr(dropdown, "_console_ids", [])
        if idx < 0 or idx >= len(ids):
            return None
        return ids[idx]

    def _set_console_dropdown_active_id(self, dropdown, console_id):
        ids = getattr(dropdown, "_console_ids", [])
        if not ids:
            return
        if console_id not in ids:
            dropdown.set_selected(0)
            return
        dropdown.set_selected(ids.index(console_id))

    def _build_status_bar(self):
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        box.add_css_class("status-bar")
        box.set_margin_start(12)
        box.set_margin_end(12)
        box.set_margin_top(6)
        box.set_margin_bottom(8)

        self.status_spinner = Gtk.Spinner()
        self.status_spinner.set_halign(Gtk.Align.START)
        box.append(self.status_spinner)

        self.status_label = Gtk.Label(label=self.t("status.idle"))
        self.status_label.set_halign(Gtk.Align.START)
        self.status_label.set_hexpand(True)
        self.status_label.set_xalign(0)
        self.status_label.add_css_class("dim-label")
        box.append(self.status_label)

        self.status_progress = Gtk.ProgressBar()
        self.status_progress.set_hexpand(True)
        self.status_progress.set_fraction(0.0)
        self.status_progress.set_text("")
        self.status_progress.set_show_text(True)
        box.append(self.status_progress)
        self._refresh_status_bar()
        return box

    def _begin_task(self, kind, label, total=0):
        self._task_seq += 1
        task_id = f"{kind}-{self._task_seq}"
        self._tasks[task_id] = {
            "id": task_id,
            "kind": kind,
            "label": label,
            "current": 0,
            "total": int(total or 0),
            "pending": True,
        }
        self._refresh_status_bar()
        return task_id

    def _update_task(self, task_id, current=None, total=None, label=None):
        task = self._tasks.get(task_id)
        if not task:
            return
        if current is not None:
            task["current"] = int(max(0, current))
        if total is not None:
            task["total"] = int(max(0, total))
        if label is not None:
            task["label"] = label
        self._refresh_status_bar()

    def _finish_task(self, task_id):
        if task_id in self._tasks:
            self._tasks.pop(task_id, None)
        self._refresh_status_bar()

    def _refresh_status_bar(self):
        if not hasattr(self, "status_label"):
            return
        if not self._tasks:
            self.status_spinner.stop()
            self.status_label.set_text(self.t("status.idle"))
            self.status_progress.set_visible(False)
            self.status_progress.set_fraction(0.0)
            self.status_progress.set_text("")
            return

        self.status_progress.set_visible(True)
        task = next(iter(self._tasks.values()))
        pending = max(0, len(self._tasks) - 1)
        label = task["label"]
        if pending:
            label = f"{label} (+{pending})"
        self.status_label.set_text(label)
        self.status_spinner.start()

        total = int(task.get("total") or 0)
        current = int(task.get("current") or 0)
        if total > 0:
            progress = min(1.0, max(0.0, current / total))
            self.status_progress.set_fraction(progress)
            self.status_progress.set_text(f"{current}/{total}")
        else:
            self.status_progress.set_fraction(0.0)
            self.status_progress.pulse()
            self.status_progress.set_text(self.t("status.running"))

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
        if console_id == FAVORITES_ID:
            return self.t("sidebar.favorites")
        return f"{console_id} - {get_system_display_name(console_id)}"

    def _build_console_icon(self, console_id):
        if console_id == ALL_CONSOLES_ID:
            return Gtk.Image.new_from_icon_name("view-grid-symbolic")
        if console_id == FAVORITES_ID:
            icon = Gtk.Image.new_from_icon_name("starred-symbolic")
            icon.add_css_class("favorites-sidebar-icon")
            return icon
        candidates = []
        preferred = CONSOLE_ICON_FILES.get(console_id)
        if preferred:
            candidates.append(preferred)
            if preferred.endswith("@2x.png"):
                candidates.append(preferred.replace("@2x.png", ".png"))

        for icon_filename in candidates:
            icon_path = self._asset_path("systems", icon_filename)
            if not icon_path.exists():
                continue
            img = Gtk.Image.new_from_file(str(icon_path))
            img.set_size_request(22, 22)
            return img
        return Gtk.Image.new_from_icon_name(get_icon_name(console_id))

    def _rebuild_console_sidebar(self, consoles):
        while child := self.console_list.get_first_child():
            self.console_list.remove(child)

        if consoles:
            self._append_console_sidebar_row(ALL_CONSOLES_ID)
        self._append_console_sidebar_row(FAVORITES_ID)
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

    def refresh_library(self, preferred_view=None):
        previous_visible = self.content_stack.get_visible_child_name() if hasattr(self, "content_stack") else None
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

        favorites_scroll = Gtk.ScrolledWindow()
        favorites_scroll.set_vexpand(True)
        self._console_pages[FAVORITES_ID] = favorites_scroll
        self._console_loaded[FAVORITES_ID] = False
        self.content_stack.add_titled(favorites_scroll, FAVORITES_ID, self.t("sidebar.favorites"))

        if self.visible_consoles:
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
        target_view = preferred_view
        if target_view is None:
            target_view = previous_visible or self.current_console

        if target_view and str(target_view).startswith("settings-"):
            self.current_console = None
            self._set_search_enabled(False)
            self.console_list.unselect_all()
            self.content_stack.set_visible_child_name(target_view)
            return

        if self.visible_consoles:
            desired = target_view if target_view in (set(self.visible_consoles) | {ALL_CONSOLES_ID, FAVORITES_ID}) else None
            if desired is None:
                desired = FAVORITES_ID
            row = self._find_console_row(desired)
            if row:
                self.console_list.select_row(row)
            else:
                first_row = self.console_list.get_row_at_index(0)
                if first_row:
                    self.console_list.select_row(first_row)
            return

        row = self._find_console_row(FAVORITES_ID)
        if row:
            self.console_list.select_row(row)
            return

        self.current_console = None
        self._set_search_enabled(False)
        self.content_stack.set_visible_child_name("library-empty")

    def _find_console_row(self, console_id):
        row = self.console_list.get_first_child()
        while row:
            if getattr(row, "id", None) == console_id:
                return row
            row = row.get_next_sibling()
        return None

    def _discover_visible_consoles(self):
        visible = []
        for console in SYSTEM_IDS:
            if self.playlist_manager.playlist_exists(console):
                roms = self.playlist_manager.load_playlist(console)
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
            "bios": self._open_settings_bios,
            "input": self._open_settings_input,
            "ui": self._open_settings_ui,
            "shaders": self._open_settings_shaders,
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

        bios_scroll = Gtk.ScrolledWindow()
        bios_scroll.set_vexpand(True)
        bios_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)

        bios_breadcrumb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        bios_breadcrumb.set_margin_top(14)
        bios_breadcrumb.set_margin_start(20)
        bios_breadcrumb.set_margin_end(20)
        bios_breadcrumb.set_margin_bottom(6)

        bios_back_btn = Gtk.Button()
        bios_back_btn.set_icon_name("go-previous-symbolic")
        bios_back_btn.set_tooltip_text(self.t("settings.back.subtitle"))
        bios_back_btn.connect("clicked", lambda _: self._open_settings_main())
        bios_breadcrumb.append(bios_back_btn)

        bios_crumb_label = Gtk.Label(label=f"{self.t('settings.title')} / {self.t('settings.bios.title')}")
        bios_crumb_label.set_halign(Gtk.Align.START)
        bios_crumb_label.add_css_class("dim-label")
        bios_breadcrumb.append(bios_crumb_label)
        bios_container.append(bios_breadcrumb)

        bios_header = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        bios_header.set_margin_start(20)
        bios_header.set_margin_end(20)
        bios_header.set_margin_bottom(8)

        bios_intro = Gtk.Label(label=self.t("bios.instructions"))
        bios_intro.set_wrap(True)
        bios_intro.set_halign(Gtk.Align.START)
        bios_intro.add_css_class("dim-label")
        bios_header.append(bios_intro)

        bios_actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        open_roms_btn = Gtk.Button(label=self.t("bios.open_roms_folder"))
        open_roms_btn.connect("clicked", lambda _: self._open_roms_folder())
        bios_actions.append(open_roms_btn)

        reload_bios_btn = Gtk.Button(label=self.t("bios.reload"))
        reload_bios_btn.connect("clicked", lambda _: self._reload_bios_status(show_toast=True))
        bios_actions.append(reload_bios_btn)
        bios_header.append(bios_actions)
        bios_container.append(bios_header)

        self.bios_groups_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.bios_groups_box.set_margin_start(20)
        self.bios_groups_box.set_margin_end(20)
        self.bios_groups_box.set_margin_bottom(24)
        bios_container.append(self.bios_groups_box)

        bios_scroll.set_child(bios_container)
        self.content_stack.add_titled(bios_scroll, "settings-bios", self.t("settings.bios.title"))

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

        self.input_console_combo = self._build_console_dropdown(SYSTEM_IDS, default_id=SYSTEM_IDS[0])
        self.input_console_combo.connect("notify::selected", self._on_input_console_changed)
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

        shaders_scroll = Gtk.ScrolledWindow()
        shaders_scroll.set_vexpand(True)
        shaders_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)

        shaders_breadcrumb = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        shaders_breadcrumb.set_margin_top(14)
        shaders_breadcrumb.set_margin_start(20)
        shaders_breadcrumb.set_margin_end(20)
        shaders_breadcrumb.set_margin_bottom(6)

        shaders_back_btn = Gtk.Button()
        shaders_back_btn.set_icon_name("go-previous-symbolic")
        shaders_back_btn.set_tooltip_text(self.t("settings.back.subtitle"))
        shaders_back_btn.connect("clicked", lambda _: self._open_settings_main())
        shaders_breadcrumb.append(shaders_back_btn)

        shaders_crumb_label = Gtk.Label(label=f"{self.t('settings.title')} / {self.t('settings.shaders.title')}")
        shaders_crumb_label.set_halign(Gtk.Align.START)
        shaders_crumb_label.add_css_class("dim-label")
        shaders_breadcrumb.append(shaders_crumb_label)
        shaders_container.append(shaders_breadcrumb)

        shaders_toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        shaders_toolbar.set_margin_start(20)
        shaders_toolbar.set_margin_end(20)
        shaders_toolbar.set_margin_top(8)
        shaders_toolbar.set_margin_bottom(4)

        self.shaders_show_all_check = Gtk.CheckButton(label=self.t("settings.shaders.show_all"))
        self.shaders_show_all_check.set_active(self.config_manager.get_shader_settings().get("show_all_shaders", False))
        self.shaders_show_all_check.connect("toggled", self._on_shader_show_all_toggled)
        shaders_toolbar.append(self.shaders_show_all_check)

        restore_btn = Gtk.Button(label=self.t("settings.shaders.restore_defaults"))
        restore_btn.connect("clicked", self._on_restore_shader_defaults_clicked)
        shaders_toolbar.append(restore_btn)
        shaders_container.append(shaders_toolbar)

        self.shaders_list_box = Gtk.ListBox()
        self.shaders_list_box.set_selection_mode(Gtk.SelectionMode.NONE)
        self.shaders_list_box.set_margin_start(20)
        self.shaders_list_box.set_margin_end(20)
        self.shaders_list_box.set_margin_bottom(24)
        shaders_container.append(self.shaders_list_box)

        shaders_scroll.set_child(shaders_container)
        self.content_stack.add_titled(shaders_scroll, "settings-shaders", self.t("settings.shaders.title"))

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

        language_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        language_row.set_margin_start(20)
        language_row.set_margin_end(20)
        language_row.set_margin_top(8)
        language_row.set_margin_bottom(4)

        language_labels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        language_labels.set_hexpand(True)
        language_title = Gtk.Label(label=self.t("settings.system.language.title"))
        language_title.set_halign(Gtk.Align.START)
        language_labels.append(language_title)
        language_subtitle = Gtk.Label(label=self.t("settings.system.language.subtitle"))
        language_subtitle.set_halign(Gtk.Align.START)
        language_subtitle.add_css_class("dim-label")
        language_labels.append(language_subtitle)
        language_row.append(language_labels)

        self.language_dropdown = self._build_language_dropdown()
        self.language_dropdown.connect("notify::selected", self._on_language_changed)
        language_row.append(self.language_dropdown)
        system_container.append(language_row)

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

        self._set_console_dropdown_active_id(
            self.input_console_combo,
            self.current_console if self.current_console in SYSTEM_IDS else SYSTEM_IDS[0],
        )
        self.input_device_combo.set_active_id("keyboard")
        self._refresh_input_bindings()
        self._reload_bios_status(show_toast=False)
        self._reload_shader_rows()

    def _on_console_selected(self, _listbox, row):
        if not row:
            return
        self.current_console = row.id
        logger.info("ui sidebar select: console_id=%s", self.current_console)
        self._set_search_enabled(True)
        if self.current_console == ALL_CONSOLES_ID:
            self._ensure_all_loaded()
        elif self.current_console == FAVORITES_ID:
            self._ensure_favorites_loaded()
        else:
            self._ensure_console_loaded(self.current_console)
        self.content_stack.set_visible_child_name(self.current_console)
        self.search_entry.set_text("")

    def _set_search_enabled(self, enabled):
        if not enabled:
            self.search_entry.set_text("")
        self.search_entry.set_sensitive(enabled)

    def _open_settings_main(self):
        logger.info("ui action: open settings main")
        self._set_search_enabled(False)
        self.console_list.unselect_all()
        self.content_stack.set_visible_child_name("settings-main")

    def _open_settings_roms(self):
        logger.info("ui action: open settings roms")
        self._set_search_enabled(False)
        self.console_list.unselect_all()
        self.content_stack.set_visible_child_name("settings-roms")

    def _open_settings_bios(self):
        logger.info("ui action: open settings bios")
        self._set_search_enabled(False)
        self.console_list.unselect_all()
        self.content_stack.set_visible_child_name("settings-bios")
        self._reload_bios_status(show_toast=False)

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
        logger.info("ui action: open settings ui")
        self._set_search_enabled(False)
        self.console_list.unselect_all()
        self.content_stack.set_visible_child_name("settings-ui")

    def _open_settings_shaders(self):
        logger.info("ui action: open settings shaders")
        self._set_search_enabled(False)
        self.console_list.unselect_all()
        self._reload_shader_rows()
        self.content_stack.set_visible_child_name("settings-shaders")

    def _open_settings_input(self):
        logger.info("ui action: open settings input")
        self._set_search_enabled(False)
        self.console_list.unselect_all()
        self.content_stack.set_visible_child_name("settings-input")
        self._refresh_input_bindings()

    def _open_settings_system(self):
        logger.info("ui action: open settings system")
        self._set_search_enabled(False)
        self.console_list.unselect_all()
        self.content_stack.set_visible_child_name("settings-system")

    def _open_roms_folder(self):
        self._open_path_in_file_manager(self.config_manager.get_roms_path())

    def _open_console_bios_folder(self, console):
        bios_dir = get_console_bios_dir(self.config_manager, console)
        bios_dir.mkdir(parents=True, exist_ok=True)
        self._open_path_in_file_manager(bios_dir)

    def _open_path_in_file_manager(self, path):
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)
        try:
            Gio.AppInfo.launch_default_for_uri(path.as_uri(), None)
            return
        except Exception:
            pass
        try:
            subprocess.Popen(["xdg-open", str(path)])
            return
        except Exception as exc:
            toast = Adw.Toast(title=self.t("bios.open_path_failed", path=str(path), error=str(exc)))
            toast.set_timeout(4)
            self.toast_overlay.add_toast(toast)

    def _reload_bios_status(self, show_toast=False):
        if not hasattr(self, "bios_groups_box"):
            return
        self._bios_status_by_console = scan_all_bios_status(self.config_manager)
        while child := self.bios_groups_box.get_first_child():
            self.bios_groups_box.remove(child)

        if not self._bios_status_by_console:
            label = Gtk.Label(label=self.t("bios.no_requirements"))
            label.set_halign(Gtk.Align.START)
            label.add_css_class("dim-label")
            self.bios_groups_box.append(label)
            return

        for console_id in sorted(self._bios_status_by_console.keys()):
            status = self._bios_status_by_console[console_id]
            group = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            group.add_css_class("bios-group")

            header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            title = Gtk.Label(label=f"{console_id} - {status['display_name']}")
            title.set_halign(Gtk.Align.START)
            title.set_hexpand(True)
            title.add_css_class("heading")
            header.append(title)

            open_btn = Gtk.Button(label=self.t("bios.open_console_folder"))
            open_btn.connect("clicked", lambda _btn, cid=console_id: self._open_console_bios_folder(cid))
            header.append(open_btn)
            group.append(header)

            group.append(self._build_bios_section(self.t("bios.section.required"), status["required"]))
            group.append(self._build_bios_section(self.t("bios.section.optional"), status["optional"]))
            self.bios_groups_box.append(group)

        if show_toast:
            toast = Adw.Toast(title=self.t("bios.reloaded"))
            toast.set_timeout(3)
            self.toast_overlay.add_toast(toast)

    def _build_bios_section(self, section_title, entries):
        container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        title = Gtk.Label(label=section_title)
        title.set_halign(Gtk.Align.START)
        title.add_css_class("dim-label")
        container.append(title)

        if not entries:
            empty = Gtk.Label(label=self.t("bios.none"))
            empty.set_halign(Gtk.Align.START)
            empty.add_css_class("dim-label")
            container.append(empty)
            return container

        for entry in entries:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            icon = Gtk.Image.new_from_icon_name("emblem-ok-symbolic" if entry["present"] else "dialog-error-symbolic")
            icon.add_css_class("bios-ok" if entry["present"] else "bios-missing")
            row.append(icon)

            label_text = entry["label"]
            if entry.get("kind") == "any_of" and label_text:
                label_text = self.t("bios.one_of", names=label_text)
            label = Gtk.Label(label=label_text)
            label.set_halign(Gtk.Align.START)
            label.set_hexpand(True)
            row.append(label)
            container.append(row)
        return container

    def _on_input_console_changed(self, *_args):
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
        console_id = self._get_console_dropdown_active_id(self.input_console_combo) or SYSTEM_IDS[0]
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
        console_id = self._get_console_dropdown_active_id(self.input_console_combo) or SYSTEM_IDS[0]
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
        console_id = self._get_console_dropdown_active_id(self.input_console_combo) or SYSTEM_IDS[0]
        profile = self.config_manager.reset_input_profile(console_id)
        self._input_loaded_profile = profile
        self._cancel_input_capture()
        self._refresh_input_bindings()
        toast = Adw.Toast(title=self.t("toast.input_reset", console=console_id))
        toast.set_timeout(3)
        self.toast_overlay.add_toast(toast)

    def _build_shader_dropdown(self, options, selected_id):
        labels = [label for _shader_id, label in options]
        ids = [shader_id for shader_id, _label in options]
        model = Gtk.StringList.new(labels)
        dropdown = Gtk.DropDown.new(model, None)
        dropdown._shader_ids = ids
        dropdown.set_enable_search(True)
        dropdown.set_hexpand(True)
        if selected_id in ids:
            dropdown.set_selected(ids.index(selected_id))
        else:
            dropdown.set_selected(0)
        return dropdown

    def _get_shader_dropdown_active_id(self, dropdown):
        idx = int(dropdown.get_selected())
        ids = getattr(dropdown, "_shader_ids", [])
        if idx < 0 or idx >= len(ids):
            return "disabled"
        return normalize_shader_id(ids[idx])

    def _shader_options_for_console(self, console_id):
        show_all = bool(self.shaders_show_all_check.get_active())
        selected = normalize_shader_id(self.config_manager.get_shader_for_console(console_id))
        options = self.shader_catalog.get_options(show_all=show_all)
        option_ids = [shader_id for shader_id, _label in options]
        if selected not in option_ids:
            options.append((selected, self.shader_catalog.label_for_shader(selected)))
        return options, selected

    def _reload_shader_rows(self):
        if not hasattr(self, "shaders_list_box"):
            return
        while child := self.shaders_list_box.get_first_child():
            self.shaders_list_box.remove(child)

        for console_id in SYSTEM_IDS:
            row = Gtk.ListBoxRow()
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            box.set_margin_top(8)
            box.set_margin_bottom(8)
            box.set_margin_start(8)
            box.set_margin_end(8)

            icon = self._build_console_icon(console_id)
            box.append(icon)

            title = Gtk.Label(label=f"{console_id} - {get_system_display_name(console_id)}")
            title.set_halign(Gtk.Align.START)
            title.set_hexpand(True)
            box.append(title)

            options, selected = self._shader_options_for_console(console_id)
            dropdown = self._build_shader_dropdown(options, selected)
            dropdown.connect("notify::selected", self._on_shader_dropdown_changed, console_id)
            box.append(dropdown)

            row.set_child(box)
            self.shaders_list_box.append(row)

    def _on_shader_dropdown_changed(self, dropdown, _param, console_id):
        shader_id = self._get_shader_dropdown_active_id(dropdown)
        self.config_manager.set_shader_for_console(console_id, shader_id)

    def _on_shader_show_all_toggled(self, button):
        self.config_manager.set_show_all_shaders(button.get_active())
        self._reload_shader_rows()

    def _on_restore_shader_defaults_clicked(self, _button):
        self.config_manager.reset_shader_defaults()
        self._reload_shader_rows()
        toast = Adw.Toast(title=self.t("toast.shaders.defaults_restored"))
        toast.set_timeout(3)
        self.toast_overlay.add_toast(toast)

    def _on_toggle_render_cartridge(self, button):
        self.config_manager.set_render_cartridge_overlay(button.get_active())
        if self.current_console == ALL_CONSOLES_ID:
            self._ensure_all_loaded()
        elif self.current_console == FAVORITES_ID:
            self._ensure_favorites_loaded()
        elif self.current_console in self._console_pages:
            self._ensure_console_loaded(self.current_console)

    def _ensure_console_loaded(self, console, force_rescan=False):
        if console == ALL_CONSOLES_ID:
            self._ensure_all_loaded(force_rescan=force_rescan)
            return
        if console == FAVORITES_ID:
            self._ensure_favorites_loaded()
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

    def _ensure_favorites_loaded(self):
        if FAVORITES_ID not in self._console_pages:
            return
        self.playlist_manager.remove_missing_favorites()
        favorites = self.playlist_manager.load_favorites_playlist()
        self._render_console_page(FAVORITES_ID, favorites)
        self._console_loaded[FAVORITES_ID] = True

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
            elif console == FAVORITES_ID:
                empty_label = Gtk.Label(label=self.t("favorites.empty"))
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
            self._toggle_favorite_from_ui,
            self._choose_cover_for_rom,
            self._remove_cover_for_rom,
            self._is_favorite_rom,
            self._has_local_cover,
            self.t,
            self.roms_path,
            ui_settings=self.config_manager.get_ui_settings(),
        )
        self._grids[console] = grid
        scroll.set_child(grid)

    def _is_favorite_rom(self, rom):
        return self.playlist_manager.is_favorite(rom["path"])

    def _has_local_cover(self, rom):
        return bool(find_local_cover(Path(self.roms_path), rom["console"], rom["name"]))

    def _toggle_favorite_from_ui(self, rom):
        is_now_favorite = self.playlist_manager.toggle_favorite(rom)
        toast_key = "toast.favorite.added" if is_now_favorite else "toast.favorite.removed"
        toast = Adw.Toast(title=self.t(toast_key, name=rom["name"]))
        toast.set_timeout(3)
        self.toast_overlay.add_toast(toast)
        if self.current_console == FAVORITES_ID:
            self._ensure_favorites_loaded()
        elif FAVORITES_ID in self._grids:
            self._ensure_favorites_loaded()
        return is_now_favorite

    def _choose_cover_for_rom(self, rom, on_done=None):
        chooser = Gtk.FileChooserDialog(
            title=self.t("dialog.cover.choose.title"),
            transient_for=self,
            modal=True,
            action=Gtk.FileChooserAction.OPEN,
        )
        chooser.add_button(self.t("dialog.cancel"), Gtk.ResponseType.CANCEL)
        chooser.add_button(self.t("dialog.start"), Gtk.ResponseType.ACCEPT)
        filter_img = Gtk.FileFilter()
        filter_img.set_name("Images")
        for ext in SUPPORTED_COVER_EXTS:
            filter_img.add_pattern(f"*.{ext}")
            filter_img.add_pattern(f"*.{ext.upper()}")
        chooser.add_filter(filter_img)

        def _on_response(dialog, response):
            if response != Gtk.ResponseType.ACCEPT:
                dialog.destroy()
                return
            selected = dialog.get_file()
            dialog.destroy()
            if not selected:
                return
            path = selected.get_path()
            if not path:
                return
            suffix = Path(path).suffix.lower().lstrip(".")
            if suffix not in SUPPORTED_COVER_EXTS:
                toast = Adw.Toast(title=self.t("toast.cover.invalid_extension"))
                toast.set_timeout(4)
                self.toast_overlay.add_toast(toast)
                return
            save_local_cover(Path(self.roms_path), rom["console"], rom["name"], path)
            toast = Adw.Toast(title=self.t("toast.cover.updated", name=rom["name"]))
            toast.set_timeout(3)
            self.toast_overlay.add_toast(toast)
            if callable(on_done):
                on_done()

        chooser.connect("response", _on_response)
        chooser.show()

    def _remove_cover_for_rom(self, rom, on_done=None):
        removed = remove_local_covers(Path(self.roms_path), rom["console"], rom["name"])
        if removed:
            toast = Adw.Toast(title=self.t("toast.cover.removed", name=rom["name"]))
            toast.set_timeout(3)
            self.toast_overlay.add_toast(toast)
            if callable(on_done):
                on_done()

    def _scan_current_console(self):
        self._show_scan_roms_dialog()

    def _rescan_single_console(self, console, show_toast=False):
        if not console or console == ALL_CONSOLES_ID:
            return self._rescan_all_consoles(show_toast=show_toast)
        if self._scan_running:
            if show_toast:
                toast = Adw.Toast(title=self.t("toast.scan_running"))
                toast.set_timeout(3)
                self.toast_overlay.add_toast(toast)
            return None

        origin_view = self.content_stack.get_visible_child_name()
        self._scan_running = True
        task_id = self._begin_task("scan", self.t("status.scan.starting"), total=1)

        def _worker():
            roms = self.playlist_manager.scan_and_rebuild_playlist(console)
            summary = {"console": console, "roms": len(roms)}
            GLib.idle_add(self._on_rescan_single_done_ui, task_id, summary, show_toast, origin_view)

        Thread(target=_worker, daemon=True).start()
        return {"started": True}

    def _rescan_all_consoles(self, show_toast=False):
        if self._scan_running:
            if show_toast:
                toast = Adw.Toast(title=self.t("toast.scan_running"))
                toast.set_timeout(3)
                self.toast_overlay.add_toast(toast)
            return None
        origin_view = self.content_stack.get_visible_child_name()
        self._scan_running = True
        task_id = self._begin_task("scan", self.t("status.scan.starting"))

        def _on_progress(evt):
            GLib.idle_add(
                self._update_task,
                task_id,
                evt.get("current", 0),
                evt.get("total", 0),
                self.t("status.scan.progress", current=evt.get("current", 0), total=evt.get("total", 0)),
            )

        def _worker():
            summary = self.playlist_manager.scan_and_rebuild_all_playlists(on_progress=_on_progress)
            GLib.idle_add(self._on_rescan_all_done_ui, task_id, summary, show_toast, origin_view)

        Thread(target=_worker, daemon=True).start()
        return {"started": True}

    def _on_rescan_single_done_ui(self, task_id, summary, show_toast, origin_view):
        self._scan_running = False
        self._update_task(task_id, current=1, total=1)
        self._finish_task(task_id)
        self.refresh_library(preferred_view=origin_view or summary.get("console"))
        self._on_search_changed(self.search_entry)
        if show_toast:
            toast = Adw.Toast(title=self.t("toast.playlist_rebuilt", console=summary.get("console")))
            toast.set_timeout(4)
            self.toast_overlay.add_toast(toast)
        return False

    def _on_rescan_all_done_ui(self, task_id, summary, show_toast, origin_view):
        self._scan_running = False
        self._finish_task(task_id)
        self.refresh_library(preferred_view=origin_view)
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
        return False

    def _start_startup_scan(self):
        self._rescan_all_consoles(show_toast=False)

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

        combo = self._build_console_dropdown(
            self.visible_consoles,
            default_id=None,
            include_all=True,
        )
        default_scope = "all"
        if self.current_console in self.visible_consoles:
            default_scope = self.current_console
        elif self.current_console == ALL_CONSOLES_ID:
            default_scope = ALL_CONSOLES_ID
        elif self.visible_consoles:
            default_scope = self.visible_consoles[0]
        if default_scope == "all":
            default_scope = ALL_CONSOLES_ID
        self._set_console_dropdown_active_id(combo, default_scope)
        content.append(combo)

        def _on_response(_dlg, response):
            if response == Gtk.ResponseType.OK:
                selected = self._get_console_dropdown_active_id(combo) or self.current_console or self.visible_consoles[0]
                if selected == ALL_CONSOLES_ID:
                    self._start_cover_sync(scope="all", selected_console=None)
                else:
                    self._start_cover_sync(scope="console", selected_console=selected)
            dialog.close()

        dialog.connect("response", _on_response)
        dialog.show()

    def _show_scan_roms_dialog(self):
        dialog = Gtk.Dialog(transient_for=self, modal=True)
        dialog.set_title(self.t("dialog.scan.title"))
        dialog.set_default_size(380, 120)
        dialog.add_button(self.t("dialog.cancel"), Gtk.ResponseType.CANCEL)
        dialog.add_button(self.t("dialog.start"), Gtk.ResponseType.OK)

        content = dialog.get_content_area()
        content.set_spacing(10)
        content.set_margin_top(12)
        content.set_margin_bottom(12)
        content.set_margin_start(12)
        content.set_margin_end(12)

        label = Gtk.Label(label=self.t("dialog.scan.scope"))
        label.set_halign(Gtk.Align.START)
        content.append(label)

        combo = self._build_console_dropdown(
            SYSTEM_IDS,
            default_id=None,
            include_all=True,
        )

        default_scope = self.current_console if self.current_console in SYSTEM_IDS else ALL_CONSOLES_ID
        self._set_console_dropdown_active_id(combo, default_scope)
        content.append(combo)

        def _on_response(_dlg, response):
            if response == Gtk.ResponseType.OK:
                selected = self._get_console_dropdown_active_id(combo) or ALL_CONSOLES_ID
                if selected == ALL_CONSOLES_ID:
                    self._rescan_all_consoles(show_toast=True)
                else:
                    self._rescan_single_console(selected, show_toast=True)
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
        task_id = self._begin_task("covers", self.t("status.covers.starting"))
        toast = Adw.Toast(title=self.t("toast.sync_started"))
        toast.set_timeout(3)
        self.toast_overlay.add_toast(toast)

        def _on_progress(evt):
            GLib.idle_add(
                self._update_task,
                task_id,
                evt.get("processed", 0),
                evt.get("total", 0),
                self.t("status.covers.progress", current=evt.get("processed", 0), total=evt.get("total", 0)),
            )

        def _on_done(summary):
            GLib.idle_add(self._on_cover_sync_done_ui, task_id, summary)

        sync_covers_async(
            library_by_console=library,
            covers_dir=self.roms_path,
            scope=scope,
            selected_console=selected_console,
            on_done=_on_done,
            sync_settings=self.config_manager.get_cover_sync_settings(),
            on_progress=_on_progress,
        )

    def _on_cover_sync_done_ui(self, task_id, summary):
        self._cover_sync_running = False
        self._finish_task(task_id)
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
        elif self.current_console == FAVORITES_ID:
            self._ensure_favorites_loaded()
        elif self.current_console in self._grids:
            self._ensure_console_loaded(self.current_console)
        return False

    def _on_refresh_clicked(self, _button):
        selected_row = self.console_list.get_selected_row()
        selected_console = getattr(selected_row, "id", None) if selected_row else self.current_console
        if selected_console == ALL_CONSOLES_ID:
            self._rescan_all_consoles(show_toast=False)
            return
        if selected_console == FAVORITES_ID:
            self._ensure_favorites_loaded()
            return
        if selected_console in SYSTEM_IDS:
            self._rescan_single_console(selected_console, show_toast=False)

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
