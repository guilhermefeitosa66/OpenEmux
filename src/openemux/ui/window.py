import os
import subprocess
import logging
from threading import Event, Thread
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Gdk, GLib, Gio, GObject, Pango

from openemux.core.bios_manager import find_missing_required_for_core, get_console_bios_dir
from openemux.core.cores import CoreCatalog
from openemux.core.library_view import (
    DEFAULT_ZOOM,
    SORT_ORDERS,
    SORT_ORDERS_NEEDING_FILE_STAT,
    SORT_ORDERS_NEEDING_HISTORY,
    VIEW_MODES,
    can_zoom,
    normalize_sort_order,
    normalize_view_mode,
    normalize_zoom,
    sort_roms,
    zoom_percent,
    zoom_step,
)
from openemux.core.play_history import PlayHistory
from openemux.core.cover_sync import sync_covers_async
from openemux.core.playlist_manager import PlaylistManager
from openemux.core.paths import get_project_root
from openemux.core.rom_importer import (
    IMPORTABLE_EXTENSIONS,
    collect_ambiguous_extensions,
    import_roms_async,
)
from openemux.core.rom_actions import RomActionError, delete_rom, rename_rom
from openemux.core.runtime_manager import RuntimeManager
from openemux.core.update_checker import DEFAULT_DOWNLOAD_URL, check_for_update_async
from openemux.core.scraper import (
    COVER_ART,
    LABEL_ART,
    SUPPORTED_COVER_EXTS,
    find_local_art,
    remove_local_art,
    save_local_art,
)
from openemux.core.scanner import RomScanner
from openemux.core.shaders import ShaderCatalog
from openemux.core.tips import TIP_ICON, TIP_KEYS, pick_next_tip, render_tip
from openemux import __version__
from openemux.core.systems import SYSTEM_IDS, get_icon_name, get_system_display_name
from openemux.i18n import LANGUAGE_META, tr
from openemux.core.ui_gamepad import GamepadNavigator
from openemux.ui.grid import RomGrid
from openemux.ui.context_menu import SEPARATOR, build_context_popover
from openemux.ui.rom_context import RomContextMenuServices
from openemux.ui.navigation import NavigationController
from openemux.ui.preferences import OpenEmuxPreferences

logger = logging.getLogger(__name__)

ALL_CONSOLES_ID = "__all__"
FAVORITES_ID = "__favorites__"
#: Slots reserved in the bottom bar for input hints (see set_hints).
MAX_INPUT_HINTS = 6
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


class OpenEmuxWindow(Adw.ApplicationWindow):
    def __init__(self, application, **kwargs):
        super().__init__(application=application, **kwargs)

        self.config_manager = application.config_manager
        self.locale = self.config_manager.get_locale()
        self.set_title("OpenEmux")
        self._setup_window_icon()
        self.set_default_size(1200, 800)
        # Minimum size required for the adaptive breakpoint to compute layout.
        self.set_size_request(360, 420)
        self.load_css()

        self.roms_path = self.config_manager.get_roms_path()
        self.scanner = RomScanner(self.roms_path)
        self.playlist_manager = PlaylistManager(self.config_manager, self.scanner)
        self.current_console = None
        # Read before the header is built: the view-mode button shows both.
        _ui = self.config_manager.get_ui_settings()
        self._view_mode = _ui["view_mode"]
        self._zoom = _ui["zoom"]
        self._sort_order = _ui["sort_order"]
        self.play_history = PlayHistory()
        self.visible_consoles = []
        self._cover_sync_running = False
        self._scan_running = False
        self._import_running = False
        self._task_seq = 0
        self._tasks = {}
        # console_id -> Gdk.Texture (or None when the console ships no asset)
        self._console_texture_cache = {}

        project_root = str(get_project_root())
        self.runtime_manager = RuntimeManager(project_root, self.config_manager)
        self.project_root = Path(project_root)
        self.shader_catalog = ShaderCatalog(runtime_dir=self.config_manager.get_runtime_dir())
        self.core_catalog = CoreCatalog(project_root=self.project_root)
        self._rom_context_services = RomContextMenuServices(self)

        self.toast_overlay = Adw.ToastOverlay()
        self.set_content(self.toast_overlay)

        self._preferences_dialog = None
        self._update_download_url = DEFAULT_DOWNLOAD_URL

        # ----- Navigation split view (sidebar + content), HIG-adaptive -----
        self.content_stack = Adw.ViewStack()
        self.content_stack.connect("notify::visible-child-name", self._on_visible_child_changed)

        self.split_view = Adw.NavigationSplitView()
        self.split_view.set_min_sidebar_width(260)
        self.split_view.set_max_sidebar_width(360)
        self.split_view.set_sidebar_width_fraction(0.28)
        self.split_view.set_sidebar(self._build_sidebar())
        self.split_view.set_content(self._build_content())
        self.toast_overlay.set_child(self.split_view)

        breakpoint = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 550sp"))
        breakpoint.add_setter(self.split_view, "collapsed", True)
        self.add_breakpoint(breakpoint)

        self._install_actions()

        # ----- Gamepad / keyboard UI navigation -----
        self.navigation = NavigationController(self)
        ui_settings = self.config_manager.get_ui_settings()
        self._gamepad_nav_enabled = ui_settings.get("gamepad_navigation", True)
        # True while the preferences dialog waits for a button/key to bind.
        self.input_capture_active = False
        self.gamepad_navigator = GamepadNavigator(
            on_action=lambda action: GLib.idle_add(self.navigation.on_gamepad_action, action),
            on_connected=lambda name: GLib.idle_add(self.navigation.on_gamepad_connected, name),
            on_disconnected=lambda: GLib.idle_add(self.navigation.on_gamepad_disconnected),
            # A running game owns the pad; so does the remapping dialog. The
            # preferences switch pauses the reader without tearing the thread
            # down.
            should_suspend=lambda: (
                not self._gamepad_nav_enabled
                or self.input_capture_active
                or self.runtime_manager.is_running()
            ),
        )
        self.gamepad_navigator.start()
        self.connect("close-request", self._on_close_stop_gamepad)

        self._install_escape_handler()

        self._click_debug_controller = Gtk.GestureClick()
        self._click_debug_controller.set_button(0)
        self._click_debug_controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        self._click_debug_controller.connect("pressed", self._on_global_click_pressed)
        self.add_controller(self._click_debug_controller)

        self.refresh_library()
        self._start_startup_scan()
        self._maybe_show_bootstrap_warning()
        self._start_update_check()
        GLib.timeout_add_seconds(1, self._poll_runtime_state)

    def _start_update_check(self):
        settings = self.config_manager.get_update_settings()
        self._update_download_url = settings["download_url"]
        if not settings["check_on_startup"]:
            logger.info("update check: disabled by config")
            return

        def _on_done(release):
            GLib.idle_add(self._on_update_check_done, release)

        check_for_update_async(
            __version__,
            _on_done,
            api_url=settings["api_url"],
            timeout=settings["timeout_seconds"],
        )

    def _on_update_check_done(self, release):
        # No release, a failed check or already up to date: stay quiet.
        if not release:
            return False
        self._update_download_url = release.get("url") or self._update_download_url
        self.update_banner.set_title(
            self.t("banner.update.available", version=release["version"])
        )
        self.update_banner.set_revealed(True)
        return False

    def _on_update_banner_clicked(self, _banner):
        logger.info("update banner: opening %s", self._update_download_url)
        self.update_banner.set_revealed(False)
        self._open_uri(self._update_download_url)

    def _open_uri(self, uri):
        launcher = Gtk.UriLauncher.new(uri)
        launcher.launch(self, None, self._on_uri_launched)

    def _on_uri_launched(self, launcher, result):
        try:
            launcher.launch_finish(result)
        except GLib.Error as exc:
            logger.info("failed to open uri: %s", exc)
            self._toast(self.t("toast.update.open_failed"), timeout=4)

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

    def _build_content(self):
        """Build the content pane: an Adw.NavigationPage with a toolbar view."""
        toolbar = Adw.ToolbarView()

        header = Adw.HeaderBar()
        self.window_title = Adw.WindowTitle.new(self.t("app.title"), "")
        header.set_title_widget(self.window_title)

        self.search_button = Gtk.ToggleButton()
        self.search_button.set_icon_name("system-search-symbolic")
        self.search_button.set_tooltip_text(self.t("header.search.toggle"))
        header.pack_end(self.search_button)

        header.pack_end(self._build_view_mode_button())

        self.stop_btn = Gtk.Button()
        self.stop_btn.set_icon_name("media-playback-stop-symbolic")
        self.stop_btn.set_tooltip_text(self.t("header.stop"))
        self.stop_btn.set_sensitive(False)
        self.stop_btn.connect("clicked", self._on_stop_game_clicked)
        header.pack_end(self.stop_btn)

        refresh_btn = Gtk.Button()
        refresh_btn.set_icon_name("view-refresh-symbolic")
        refresh_btn.set_tooltip_text(self.t("header.refresh"))
        refresh_btn.connect("clicked", self._on_refresh_clicked)
        header.pack_start(refresh_btn)

        self.import_btn = Gtk.Button()
        self.import_btn.set_icon_name("folder-download-symbolic")
        self.import_btn.set_tooltip_text(self.t("header.import"))
        self.import_btn.connect("clicked", self._on_import_clicked)
        header.pack_start(self.import_btn)

        self.covers_btn = Gtk.Button()
        self.covers_btn.set_icon_name("emblem-photos-symbolic")
        self.covers_btn.set_tooltip_text(self.t("header.sync_covers"))
        self.covers_btn.connect("clicked", self._on_sync_covers_clicked)
        header.pack_start(self.covers_btn)

        toolbar.add_top_bar(header)

        # Search revealed on demand (HIG: search is a mode, not a permanent field).
        self.search_entry = Gtk.SearchEntry()
        self.search_entry.set_hexpand(True)
        self.search_entry.set_placeholder_text(self.t("header.search"))
        self.search_entry.connect("search-changed", self._on_search_changed)
        self.search_bar = Gtk.SearchBar()
        self.search_bar.set_key_capture_widget(self)
        self.search_bar.connect_entry(self.search_entry)
        self.search_bar.set_child(self.search_entry)
        self.search_button.bind_property(
            "active", self.search_bar, "search-mode-enabled",
            GObject.BindingFlags.BIDIRECTIONAL,
        )
        toolbar.add_top_bar(self.search_bar)

        # Progress banner replaces the former custom status bar (HIG feedback).
        self.banner = Adw.Banner()
        self.banner.set_revealed(False)
        self._banner_cancel_task_id = None
        self.banner.connect("button-clicked", self._on_banner_button_clicked)
        toolbar.add_top_bar(self.banner)

        # Kept separate from the progress banner: that one is driven by the task
        # registry and shows one task at a time, so it has no room for a notice
        # that stays up until acted on.
        self.update_banner = Adw.Banner()
        self.update_banner.set_revealed(False)
        self.update_banner.set_button_label(self.t("banner.update.action"))
        self.update_banner.connect("button-clicked", self._on_update_banner_clicked)
        toolbar.add_top_bar(self.update_banner)

        toolbar.set_content(self.content_stack)
        # Installed on the stack rather than on each grid so that every page —
        # including the empty-library Adw.StatusPage — accepts dropped ROMs.
        self._install_drop_target(self.content_stack)

        toolbar.add_bottom_bar(self._build_selection_bar())
        toolbar.add_bottom_bar(self._build_tip_bar())

        page = Adw.NavigationPage.new(toolbar, self.t("app.title"))
        page.set_tag("content")
        self.content_page = page
        return page

    #: Toolbar icon per view mode. The two grid modes share one: the popover's
    #: radio marks which of them is on, and swapping the button's icon between
    #: two near-identical grids reads as noise.
    VIEW_MODE_ICONS = {
        "cover": "view-grid-symbolic",
        "cartridge": "view-grid-symbolic",
        "list": "view-list-symbolic",
    }

    def _build_view_mode_button(self):
        """The layout switcher, in the header where the user browses.

        It used to be a switch buried in Preferences, which is the wrong place
        for something people flip while looking at their library. The zoom
        controls live in the same menu, as they do in GNOME Files.
        """
        menu = Gio.Menu()
        for mode in VIEW_MODES:
            menu.append(self.t(f"view_mode.{mode}"), f"win.view-mode::{mode}")

        # Sorting sits behind a submenu: six orders as a flat list would bury
        # the three view modes above them.
        sort_menu = Gio.Menu()
        for order in SORT_ORDERS:
            sort_menu.append(self.t(f"sort_order.{order}"), f"win.sort-order::{order}")
        sort_section = Gio.Menu()
        sort_section.append_submenu(self.t("header.sort_by"), sort_menu)
        menu.append_section(None, sort_section)

        zoom_section = Gio.Menu()
        zoom_item = Gio.MenuItem.new(None, None)
        # A custom item: a menu model cannot express a -/+ stepper, and
        # Gtk.PopoverMenu fills the slot with whatever widget is registered
        # under this id.
        zoom_item.set_attribute_value("custom", GLib.Variant("s", "zoom"))
        zoom_section.append_item(zoom_item)
        menu.append_section(None, zoom_section)

        self.view_mode_button = Gtk.MenuButton()
        self.view_mode_button.set_menu_model(menu)
        self.view_mode_button.set_tooltip_text(self.t("header.view_mode"))
        self.view_mode_button.set_icon_name(
            self.VIEW_MODE_ICONS.get(self._view_mode, "view-grid-symbolic")
        )
        popover = self.view_mode_button.get_popover()
        if popover is not None:
            popover.add_child(self._build_zoom_controls(), "zoom")
        return self.view_mode_button

    def _build_zoom_controls(self):
        """A -/+ stepper with the current percentage between the buttons."""
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        box.add_css_class("zoom-controls")

        self.zoom_out_button = Gtk.Button.new_from_icon_name("zoom-out-symbolic")
        self.zoom_out_button.add_css_class("circular")
        self.zoom_out_button.add_css_class("flat")
        self.zoom_out_button.set_tooltip_text(self.t("header.zoom.out"))
        self.zoom_out_button.connect("clicked", lambda _b: self._step_zoom(-1))

        self.zoom_label = Gtk.Label()
        self.zoom_label.set_hexpand(True)
        self.zoom_label.add_css_class("numeric")

        self.zoom_in_button = Gtk.Button.new_from_icon_name("zoom-in-symbolic")
        self.zoom_in_button.add_css_class("circular")
        self.zoom_in_button.add_css_class("flat")
        self.zoom_in_button.set_tooltip_text(self.t("header.zoom.in"))
        self.zoom_in_button.connect("clicked", lambda _b: self._step_zoom(1))

        for child in (self.zoom_out_button, self.zoom_label, self.zoom_in_button):
            box.append(child)
        self._sync_zoom_controls()
        return box

    def _sync_zoom_controls(self):
        if not hasattr(self, "zoom_label"):
            return
        self.zoom_label.set_label(f"{zoom_percent(self._zoom)}%")
        self.zoom_out_button.set_sensitive(can_zoom(self._zoom, -1))
        self.zoom_in_button.set_sensitive(can_zoom(self._zoom, 1))

    def _step_zoom(self, delta):
        self._apply_zoom(zoom_step(self._zoom, delta))

    def _apply_zoom(self, zoom):
        """Resize the artwork on every grid-based layout and remember it."""
        zoom = normalize_zoom(zoom)
        if zoom == self._zoom:
            return
        self._zoom = zoom
        self.config_manager.set_zoom(zoom)
        self._sync_zoom_controls()
        self._reload_current_page()
        self._toast(self.t("toast.zoom", percent=zoom_percent(zoom)), timeout=1)

    def _on_view_mode_action(self, action, value):
        mode = normalize_view_mode(value.get_string())
        action.set_state(GLib.Variant("s", mode))
        self._apply_view_mode(mode)

    def _apply_view_mode(self, mode):
        """Switch the library layout and re-render the page being looked at."""
        mode = normalize_view_mode(mode)
        if mode == self._view_mode:
            return
        self._view_mode = mode
        self.config_manager.set_view_mode(mode)
        if hasattr(self, "view_mode_button"):
            self.view_mode_button.set_icon_name(
                self.VIEW_MODE_ICONS.get(mode, "view-grid-symbolic")
            )
        action = self.lookup_action("view-mode")
        if action is not None and action.get_state().get_string() != mode:
            action.set_state(GLib.Variant("s", mode))
        self._reload_current_page()

    def _on_sort_order_action(self, action, value):
        order = normalize_sort_order(value.get_string())
        action.set_state(GLib.Variant("s", order))
        self._apply_sort_order(order)

    def _apply_sort_order(self, order):
        order = normalize_sort_order(order)
        if order == self._sort_order:
            return
        self._sort_order = order
        self.config_manager.set_sort_order(order)
        self._reload_current_page()
        self._toast(self.t("toast.sorted", order=self.t(f"sort_order.{order}")), timeout=2)

    def _sorted_roms(self, roms):
        """Apply the chosen order, reading the disk only when it is needed.

        Stat-ing a whole library costs real time on a slow disk, so the lookups
        are wired up only for the orders that actually use them.
        """
        needs_stat = self._sort_order in SORT_ORDERS_NEEDING_FILE_STAT
        needs_history = self._sort_order in SORT_ORDERS_NEEDING_HISTORY
        return sort_roms(
            roms,
            self._sort_order,
            file_stat=self._rom_file_stat if needs_stat else None,
            last_played=self.play_history.last_played if needs_history else None,
        )

    @staticmethod
    def _rom_file_stat(path):
        """``(size, added)`` for a ROM. A file that is gone sorts as unknown."""
        try:
            info = os.stat(path)
        except OSError:
            return 0, 0.0
        # st_ctime, not st_mtime: copying a ROM in preserves the original file's
        # modification time, so "recently added" has to mean when *this* copy
        # appeared, which is what the inode change time records.
        return info.st_size, info.st_ctime

    def _build_selection_bar(self):
        """Actions for a multi-ROM selection, revealed only while one exists.

        Lives below the content next to the tip bar rather than in the header:
        it belongs to what is selected on the page, not to the window.
        """
        self._selected_roms = []

        self.selection_label = Gtk.Label()
        self.selection_label.add_css_class("heading")
        self.selection_label.set_hexpand(True)
        self.selection_label.set_xalign(0)

        sync_button = Gtk.Button(label=self.t("selection.sync_covers"))
        sync_button.connect("clicked", lambda _b: self._sync_covers_for_selection())

        delete_button = Gtk.Button(label=self.t("selection.delete"))
        delete_button.add_css_class("destructive-action")
        delete_button.connect("clicked", lambda _b: self._confirm_delete_roms(self._selected_roms))

        clear_button = Gtk.Button.new_from_icon_name("window-close-symbolic")
        clear_button.add_css_class("flat")
        clear_button.set_tooltip_text(self.t("selection.clear"))
        clear_button.connect("clicked", lambda _b: self._clear_selection())

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        box.add_css_class("toolbar")
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        box.set_margin_start(12)
        box.set_margin_end(12)
        for child in (self.selection_label, sync_button, delete_button, clear_button):
            box.append(child)

        self.selection_bar = Gtk.Revealer()
        self.selection_bar.set_child(box)
        self.selection_bar.set_reveal_child(False)
        return self.selection_bar

    def _on_selection_changed(self, roms):
        self._selected_roms = list(roms)
        count = len(self._selected_roms)
        if count:
            self.selection_label.set_label(self.t("selection.count", count=count))
        self.selection_bar.set_reveal_child(bool(count))

    def _clear_selection(self):
        grid = self._grids.get(self.current_console)
        if grid:
            grid.clear_selection()
        self._on_selection_changed([])

    def _build_tip_bar(self):
        """A quiet single-line hint bar at the bottom of the content pane.

        Deliberately not an Adw.Banner: banners are for things that need acting
        on, and the progress/update banners already own the top of the pane.
        """
        self.tip_label = Gtk.Label()
        self.tip_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.tip_label.set_single_line_mode(True)
        # Without this the label centres itself across the whole bar and reads as
        # detached from the bulb sitting at the far left.
        self.tip_label.set_xalign(0)
        self.tip_label.set_halign(Gtk.Align.START)
        self.tip_label.add_css_class("caption")
        self.tip_label.add_css_class("dim-label")

        # Adwaita ships no lightbulb icon (checked against the live icon theme),
        # so the emoji stands in as the "this is a hint" marker.
        bulb = Gtk.Label(label=TIP_ICON)
        bulb.add_css_class("caption")
        bulb.add_css_class("tip-bar-icon")
        self._tip_bulb = bulb

        tip_side = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        tip_side.append(bulb)
        tip_side.append(self.tip_label)
        self._tip_side = tip_side

        # Input hints (gamepad glyphs or key names) on the right; filled by the
        # NavigationController through set_hints().
        #
        # The slots are built once and only ever have their text swapped.
        # Appending/removing them per update left the box measuring 0 even with
        # visible children, so it was allocated no width and the keycaps spilled
        # off the right edge of the window.
        self.hint_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.hint_box.set_halign(Gtk.Align.END)
        self._hint_slots = []
        for _ in range(MAX_INPUT_HINTS):
            key = Gtk.Label()
            key.add_css_class("caption")
            key.add_css_class("hint-key")
            text = Gtk.Label()
            text.add_css_class("caption")
            text.add_css_class("dim-label")
            slot = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
            slot.append(key)
            slot.append(text)
            slot.set_visible(False)
            self.hint_box.append(slot)
            self._hint_slots.append((slot, key, text))

        # A CenterBox, not a plain Box: the end widget is guaranteed its natural
        # width and the tip ellipsizes into what is left. In a Box the tip's
        # hexpand won the negotiation and pushed the hints off the right edge.
        bar = Gtk.CenterBox()
        bar.add_css_class("tip-bar")
        bar.set_start_widget(tip_side)
        bar.set_end_widget(self.hint_box)

        self.tip_bar = bar
        self._has_hints = False
        self._current_tip_key = None
        self._tip_timeout_id = 0
        self._rotate_tip()
        self.connect("close-request", self._on_close_stop_tips)
        self._apply_tips_visibility(self.config_manager.get_ui_settings()["show_tips"])
        return bar

    def _apply_tips_visibility(self, enabled):
        """Show or hide the tip bar, keeping the timer in step.

        Rotating while hidden would burn a wakeup every 15s for nothing, so the
        timer is torn down rather than left running behind an invisible widget.
        """
        bar = getattr(self, "tip_bar", None)
        if bar is None:
            return
        # Only the tip half goes away: the bar itself stays whenever input
        # hints are being shown on its right side.
        self._tips_enabled = bool(enabled)
        self._tip_side.set_visible(self._tips_enabled)
        self._update_tip_bar_visibility()
        if enabled:
            if not getattr(self, "_tip_timeout_id", 0):
                self._rotate_tip()
                self._tip_timeout_id = GLib.timeout_add_seconds(15, self._on_tip_timeout)
        else:
            self._stop_tip_rotation()

    def _update_tip_bar_visibility(self):
        self.tip_bar.set_visible(getattr(self, "_tips_enabled", True) or self._has_hints)

    def set_hints(self, pairs):
        """Fill the right side of the bottom bar with (glyph, label) hints."""
        pairs = list(pairs)[:MAX_INPUT_HINTS]
        for index, (slot, key, text) in enumerate(self._hint_slots):
            if index < len(pairs):
                glyph, label = pairs[index]
                key.set_label(glyph)
                text.set_label(label)
                slot.set_visible(True)
            else:
                slot.set_visible(False)
        self._has_hints = bool(pairs)
        self.hint_box.set_visible(self._has_hints)
        self._update_tip_bar_visibility()

    def _render_tip(self):
        """Re-render the current tip (used on language change too)."""
        label = getattr(self, "tip_label", None)
        if label is None:
            return
        label.set_text(render_tip(self.t, self._current_tip_key))

    def _rotate_tip(self):
        self._current_tip_key = pick_next_tip(TIP_KEYS, self._current_tip_key)
        self._render_tip()

    def _on_tip_timeout(self):
        self._rotate_tip()
        return GLib.SOURCE_CONTINUE

    def _stop_tip_rotation(self):
        if getattr(self, "_tip_timeout_id", 0):
            GLib.source_remove(self._tip_timeout_id)
            self._tip_timeout_id = 0

    def _on_close_stop_tips(self, *_args):
        self._stop_tip_rotation()
        return False

    def _build_primary_menu(self):
        menu = Gio.Menu()
        menu.append(self.t("menu.preferences"), "win.preferences")
        menu.append(self.t("menu.shortcuts"), "win.shortcuts")
        menu.append(self.t("menu.about"), "win.about")
        button = Gtk.MenuButton()
        button.set_icon_name("open-menu-symbolic")
        button.set_menu_model(menu)
        button.set_tooltip_text(self.t("menu.primary"))
        button.set_primary(True)
        # Held for the gamepad's Select button, which opens this menu from
        # wherever the focus happens to be.
        self.primary_menu_button = button
        return button

    def _install_actions(self):
        # Plain-key accels (Delete, F2, F5) are safe next to the search entry:
        # a focused entry consumes the key press before window accels run.
        for name, handler, accels in (
            ("preferences", lambda *_: self._open_preferences(), ["<Ctrl>comma"]),
            ("shortcuts", lambda *_: self._show_shortcuts(), ["<Ctrl>question"]),
            ("about", lambda *_: self._show_about(), None),
            ("search", lambda *_: self._toggle_search(), ["<Ctrl>f"]),
            ("rescan", lambda *_: self._on_refresh_clicked(None), ["F5", "<Ctrl>r"]),
            ("import", lambda *_: self._on_import_clicked(None), ["<Ctrl>o"]),
            ("sync-covers", lambda *_: self._sync_covers_for_current_scope(), ["<Ctrl><Shift>s"]),
            ("delete-rom", lambda *_: self._delete_selected_or_focused(), ["Delete"]),
            ("rename-rom", lambda *_: self._rename_focused_rom(), ["F2"]),
            ("toggle-favorite", lambda *_: self._favorite_focused_rom(), ["<Ctrl>d"]),
            ("focus-pane", lambda *_: self.navigation.toggle_pane_focus(), ["F6"]),
            # Both the main-row and keypad forms: on many layouts Ctrl+"+"
            # arrives as Ctrl+= (no shift), which is why that one is listed too.
            ("zoom-in", lambda *_: self._step_zoom(1), ["<Ctrl>plus", "<Ctrl>equal", "<Ctrl>KP_Add"]),
            ("zoom-out", lambda *_: self._step_zoom(-1), ["<Ctrl>minus", "<Ctrl>KP_Subtract"]),
            ("zoom-reset", lambda *_: self._apply_zoom(DEFAULT_ZOOM), ["<Ctrl>0"]),
            ("stop-game", lambda *_: self._on_stop_game_clicked(None), ["<Ctrl>Escape"]),
            ("quit", lambda *_: self.get_application().quit(), ["<Ctrl>q"]),
        ):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", handler)
            self.add_action(action)
            app = self.get_application()
            if accels and app is not None:
                app.set_accels_for_action(f"win.{name}", accels)

        # Stateful, so the header menu draws the current layout as the selected
        # radio entry instead of three identical rows.
        view_mode_action = Gio.SimpleAction.new_stateful(
            "view-mode",
            GLib.VariantType.new("s"),
            GLib.Variant("s", self._view_mode),
        )
        view_mode_action.connect("activate", self._on_view_mode_action)
        self.add_action(view_mode_action)

        sort_order_action = Gio.SimpleAction.new_stateful(
            "sort-order",
            GLib.VariantType.new("s"),
            GLib.Variant("s", self._sort_order),
        )
        sort_order_action.connect("activate", self._on_sort_order_action)
        self.add_action(sort_order_action)

    def _focused_rom_item(self):
        return RomGrid.item_for_widget(self.get_focus())

    def _delete_selected_or_focused(self):
        if self._selected_roms:
            self._confirm_delete_roms(self._selected_roms)
            return
        item = self._focused_rom_item()
        if item is not None:
            self._confirm_delete_roms([item.rom])

    def _rename_focused_rom(self):
        item = self._focused_rom_item()
        if item is not None:
            self._rename_rom_from_ui(item.rom)

    def _favorite_focused_rom(self):
        item = self._focused_rom_item()
        if item is not None:
            # Through the card so its star badge stays in sync.
            item._act_toggle_favorite(None, None)

    def _install_escape_handler(self):
        """Escape clears the selection, else steps back from grid to sidebar.

        Bubble phase on the window: dialogs, popovers and the search bar all
        consume their own Escape first, so this only sees the leftovers.
        """
        controller = Gtk.EventControllerKey()
        controller.connect("key-pressed", self._on_window_escape)
        self.add_controller(controller)

    def _on_window_escape(self, _controller, keyval, _keycode, _state):
        if keyval != Gdk.KEY_Escape:
            return False
        if self._selected_roms:
            self._clear_selection()
            return True
        return self.navigation.escape_to_sidebar()

    def _on_close_stop_gamepad(self, *_args):
        self.gamepad_navigator.stop()
        return False

    def set_input_capture_active(self, active):
        """Give the remapping dialog exclusive ownership of the controller.

        While this is set the navigator thread suspends (so no held direction
        keeps repeating) and every action that still reaches the main loop is
        resolved as a no-op, which is what stops B from closing the dialog
        instead of being stored as a binding.
        """
        active = bool(active)
        if active == self.input_capture_active:
            return
        self.input_capture_active = active
        self.navigation.refresh_hints()

    def _apply_gamepad_navigation(self, enabled):
        self.config_manager.set_gamepad_navigation(enabled)
        self._gamepad_nav_enabled = bool(enabled)

    def _toggle_search(self):
        if not self.search_button.get_sensitive():
            return
        self.search_button.set_active(not self.search_button.get_active())

    def _open_preferences(self):
        self._preferences_dialog = OpenEmuxPreferences(self)
        self._preferences_dialog.present(self)

    def _show_about(self):
        about = Adw.AboutDialog()
        about.set_application_name(self.t("app.title"))
        about.set_application_icon(self.get_application().get_application_id() or "io.github.guilhermefeitosa66.OpenEmux")
        about.set_developer_name("OpenEmux")
        about.set_version(__version__)
        about.set_comments(self.t("about.comments"))
        about.set_website("https://github.com/guilhermefeitosa66/OpenEmux")
        about.set_license_type(Gtk.License.MIT_X11)
        about.present(self)

    def _show_shortcuts(self):
        # Gamepad controls are deliberately absent: the hint bar at the bottom
        # documents them live, in context.
        groups = (
            ("shortcuts.group.general", (
                ("<Ctrl>f", "shortcuts.search"),
                ("<Ctrl>comma", "shortcuts.preferences"),
                ("<Ctrl>Escape", "shortcuts.stop"),
                ("<Ctrl>q", "shortcuts.quit"),
            )),
            ("shortcuts.group.library", (
                ("F5", "shortcuts.rescan"),
                ("<Ctrl>o", "shortcuts.import"),
                ("<Ctrl><Shift>s", "shortcuts.sync_covers"),
                ("Tab", "shortcuts.focus_pane"),
                ("F6", "shortcuts.focus_pane"),
                ("Right", "shortcuts.enter_grid"),
                ("BackSpace", "shortcuts.back_to_sidebar"),
                ("<Ctrl>plus", "shortcuts.zoom_in"),
                ("<Ctrl>minus", "shortcuts.zoom_out"),
                ("<Ctrl>0", "shortcuts.zoom_reset"),
            )),
            ("shortcuts.group.rom", (
                ("Return", "shortcuts.open_rom"),
                ("Menu", "shortcuts.context_menu"),
                ("<Ctrl>d", "shortcuts.favorite"),
                ("F2", "shortcuts.rename"),
                ("Delete", "shortcuts.delete"),
            )),
        )
        section = Gtk.ShortcutsSection(section_name="general", visible=True)
        for group_key, entries in groups:
            group = Gtk.ShortcutsGroup(title=self.t(group_key))
            for accel, key in entries:
                group.add_shortcut(
                    Gtk.ShortcutsShortcut(accelerator=accel, title=self.t(key))
                )
            section.add_group(group)
        window = Gtk.ShortcutsWindow(modal=True, transient_for=self)
        window.add_section(section)
        window.present()

    def _toast(self, text, timeout=3):
        toast = Adw.Toast(title=text)
        toast.set_timeout(timeout)
        self.toast_overlay.add_toast(toast)

    def _apply_language_change(self, locale):
        self.config_manager.set_locale(locale)
        self.locale = locale
        language_name = LANGUAGE_META.get(locale, LANGUAGE_META["en"])["native_name"]
        visible = self.content_stack.get_visible_child_name()
        self.search_entry.set_placeholder_text(self.t("header.search"))
        self.search_button.set_tooltip_text(self.t("header.search.toggle"))
        self.stop_btn.set_tooltip_text(self.t("header.stop"))
        self.import_btn.set_tooltip_text(self.t("header.import"))
        self.covers_btn.set_tooltip_text(self.t("header.sync_covers"))
        self.sidebar_title.set_title(self.t("sidebar.header"))
        self._render_tip()
        self.refresh_library(preferred_view=visible)
        self._toast(self.t("toast.language.updated", language=language_name))

    def _update_window_title(self, console_id):
        if console_id == ALL_CONSOLES_ID:
            title = self.t("sidebar.all")
        elif console_id == FAVORITES_ID:
            title = self.t("sidebar.favorites")
        elif console_id:
            title = f"{console_id} — {get_system_display_name(console_id)}"
        else:
            title = self.t("app.title")
        subtitle = ""
        grid = getattr(self, "_grids", {}).get(console_id)
        if grid is not None:
            count = 0
            child = grid.get_first_child()
            while child:
                count += 1
                child = child.get_next_sibling()
            if count == 0:
                subtitle = self.t("header.subtitle.no_games")
            elif count == 1:
                subtitle = self.t("header.subtitle.one_game")
            else:
                subtitle = self.t("header.subtitle.games", count=count)
        self.window_title.set_title(title)
        self.window_title.set_subtitle(subtitle)
        if hasattr(self, "content_page"):
            self.content_page.set_title(title)

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
        factory._all_label_key = all_label_key
        factory.connect("setup", self._on_console_dropdown_setup)
        factory.connect("bind", self._on_console_dropdown_bind)
        dropdown.set_factory(factory)

        list_factory = Gtk.SignalListItemFactory()
        list_factory._all_label_key = all_label_key
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
            # The factory carries the caller's label override, so the import
            # picker can render this entry as "detect automatically".
            label_text = self.t(getattr(_factory, "_all_label_key", None) or "sidebar.all")
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

    def _begin_task(self, kind, label, total=0, on_cancel=None):
        """Register a background task. ``on_cancel`` makes it interruptible.

        A cancellable task gets a Cancel button on the progress banner; the
        callback is expected to signal the worker, not to block waiting for it.
        """
        self._task_seq += 1
        task_id = f"{kind}-{self._task_seq}"
        self._tasks[task_id] = {
            "id": task_id,
            "kind": kind,
            "label": label,
            "current": 0,
            "total": int(total or 0),
            "pending": True,
            "on_cancel": on_cancel,
            "cancelling": False,
        }
        self._refresh_banner()
        return task_id

    def _on_banner_button_clicked(self, _banner):
        if self._banner_cancel_task_id:
            self._cancel_task(self._banner_cancel_task_id)

    def _cancel_task(self, task_id):
        task = self._tasks.get(task_id)
        if not task or task.get("cancelling") or not task.get("on_cancel"):
            return
        # Mark first: the worker stops at its next checkpoint, so the banner has
        # to show "stopping" rather than pretending it is already done.
        task["cancelling"] = True
        logger.info("task cancel requested: id=%s kind=%s", task_id, task["kind"])
        self._refresh_banner()
        task["on_cancel"]()

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
        self._refresh_banner()

    def _finish_task(self, task_id):
        if task_id in self._tasks:
            self._tasks.pop(task_id, None)
        self._refresh_banner()

    def _refresh_banner(self):
        if not hasattr(self, "banner"):
            return
        if not self._tasks:
            self.banner.set_revealed(False)
            return

        task = next(iter(self._tasks.values()))
        pending = max(0, len(self._tasks) - 1)
        label = task["label"]
        total = int(task.get("total") or 0)
        current = int(task.get("current") or 0)
        if task.get("cancelling"):
            label = self.t("banner.stopping")
        else:
            if total > 0:
                label = f"{label} ({current}/{total})"
            if pending:
                label = f"{label} (+{pending})"
        self.banner.set_title(label)

        # Offer Cancel only while the task is actually interruptible.
        if task.get("on_cancel") and not task.get("cancelling"):
            self.banner.set_button_label(self.t("banner.cancel"))
            self._banner_cancel_task_id = task["id"]
        else:
            self.banner.set_button_label(None)
            self._banner_cancel_task_id = None
        self.banner.set_revealed(True)

    def _build_sidebar(self):
        toolbar = Adw.ToolbarView()

        header = Adw.HeaderBar()
        self.sidebar_title = Adw.WindowTitle.new(self.t("sidebar.header"), "")
        header.set_title_widget(self.sidebar_title)
        header.pack_end(self._build_primary_menu())
        toolbar.add_top_bar(header)

        self.console_list = Gtk.ListBox()
        self.console_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.console_list.connect("row-selected", self._on_console_selected)
        self.console_list.add_css_class("navigation-sidebar")

        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_vexpand(True)
        scroll.set_child(self.console_list)
        toolbar.set_content(scroll)

        page = Adw.NavigationPage.new(toolbar, self.t("sidebar.header"))
        page.set_tag("sidebar")
        self._rebuild_console_sidebar([])
        return page

    def _console_sidebar_label(self, console_id):
        if console_id == ALL_CONSOLES_ID:
            return self.t("sidebar.all")
        if console_id == FAVORITES_ID:
            return self.t("sidebar.favorites")
        return f"{console_id} - {get_system_display_name(console_id)}"

    def _console_icon_texture(self, console_id):
        """Load (once) the console's PNG as a texture, or None if it has no asset.

        Dropdown list factories rebuild their rows on every scroll frame, so the
        decode has to happen once per console and not once per bind -- reading
        and decoding the PNG inline made those lists stutter badly.
        """
        cache = self._console_texture_cache
        if console_id in cache:
            return cache[console_id]

        candidates = []
        preferred = CONSOLE_ICON_FILES.get(console_id)
        if preferred:
            candidates.append(preferred)
            if preferred.endswith("@2x.png"):
                candidates.append(preferred.replace("@2x.png", ".png"))

        texture = None
        for icon_filename in candidates:
            icon_path = self._asset_path("systems", icon_filename)
            if not icon_path.exists():
                continue
            try:
                texture = Gdk.Texture.new_from_filename(str(icon_path))
            except GLib.Error as exc:
                logger.info("console icon failed to load: %s (%s)", icon_path, exc)
                continue
            break

        # Cache misses too, so a console without an asset does not re-stat on
        # every bind either.
        cache[console_id] = texture
        return texture

    def _build_console_icon(self, console_id):
        if console_id == ALL_CONSOLES_ID:
            return Gtk.Image.new_from_icon_name("view-grid-symbolic")
        if console_id == FAVORITES_ID:
            icon = Gtk.Image.new_from_icon_name("starred-symbolic")
            icon.add_css_class("favorites-sidebar-icon")
            return icon

        texture = self._console_icon_texture(console_id)
        if texture is None:
            return Gtk.Image.new_from_icon_name(get_icon_name(console_id))
        img = Gtk.Image.new_from_paintable(texture)
        img.set_size_request(22, 22)
        return img

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

        # All and Favorites are virtual views: no per-console actions apply, so
        # they get neither the button nor the right-click menu.
        if console_id not in (ALL_CONSOLES_ID, FAVORITES_ID):
            menu_button = Gtk.Button.new_from_icon_name("view-more-symbolic")
            menu_button.add_css_class("flat")
            menu_button.add_css_class("sidebar-menu-button")
            menu_button.set_valign(Gtk.Align.CENTER)
            menu_button.set_tooltip_text(self.t("context.more_options"))
            menu_button.set_visible(False)
            menu_button.connect(
                "clicked", lambda b, cid=console_id, r=row: self._on_sidebar_menu_button(b, r, cid)
            )
            box.append(menu_button)

            motion = Gtk.EventControllerMotion()
            motion.connect("enter", lambda _c, _x, _y, b=menu_button: b.set_visible(True))
            motion.connect("leave", lambda _c, b=menu_button, r=row: self._hide_sidebar_menu_button(b, r))
            row.add_controller(motion)
            row.menu_button = menu_button

        row.set_child(box)
        row.id = console_id
        self._install_sidebar_context_menu(row, console_id)
        self.console_list.append(row)

    def _hide_sidebar_menu_button(self, button, row):
        # Keep it while its own menu is open, so it does not vanish mid-click.
        if getattr(self, "_sidebar_menu_row", None) is not row:
            button.set_visible(False)

    def _on_sidebar_menu_button(self, button, row, console_id):
        # Coordinates are relative to the row, which the popover is parented to.
        ok, bounds = button.compute_bounds(row)
        x, y = (bounds.get_x(), bounds.get_y() + bounds.get_height()) if ok else (0, 0)
        self._show_sidebar_menu(row, console_id, x, y)

    def _install_sidebar_context_menu(self, row, console_id):
        # "All" and "Favorites" are virtual views: none of the actions apply.
        if console_id in (ALL_CONSOLES_ID, FAVORITES_ID):
            return
        gesture = Gtk.GestureClick()
        gesture.set_button(Gdk.BUTTON_SECONDARY)
        # Popping up on "pressed" makes the matching release close the popover
        # again, so the menu only stays while the button is held. Wait for the
        # release, and claim the sequence so the row does not also react.
        gesture.connect(
            "released",
            lambda g, _n, x, y, cid=console_id, r=row: (
                g.set_state(Gtk.EventSequenceState.CLAIMED),
                self._show_sidebar_menu(r, cid, x, y),
            ),
        )
        row.add_controller(gesture)

    def _show_sidebar_menu(self, row, console_id, x, y):
        """Right-click actions for a sidebar console.

        The first three mirror the header-bar buttons; "open folder" is the one
        thing that only makes sense per console.
        """
        self._sidebar_menu_console = console_id
        self._ensure_sidebar_action_group()

        popover = build_context_popover([
            # Not the header button's wording: there the action is "reload what
            # is on screen", here it is "rescan this console's folder".
            (self.t("context.rescan.console"), "sidebar.refresh", "view-refresh-symbolic"),
            (self.t("header.import"), "sidebar.import", "document-open-symbolic"),
            (self.t("header.sync_covers"), "sidebar.sync-covers", "image-x-generic-symbolic"),
            SEPARATOR,
            (self.t("context.open_folder"), "sidebar.open-folder", "folder-open-symbolic"),
        ])
        popover.set_parent(row)
        popover.set_pointing_to(Gdk.Rectangle(x=int(x), y=int(y), width=1, height=1))
        self._sidebar_menu_row = row
        popover.connect("closed", lambda p, r=row: self._on_sidebar_popover_closed(p, r))
        popover.popup()

    def _on_sidebar_popover_closed(self, popover, row):
        if getattr(self, "_sidebar_menu_row", None) is row:
            self._sidebar_menu_row = None
        button = getattr(row, "menu_button", None)
        # The pointer may have left the row while the menu was up; the button
        # only belongs on the hovered row.
        if button is not None and not row.get_state_flags() & Gtk.StateFlags.PRELIGHT:
            button.set_visible(False)
        GLib.idle_add(popover.unparent)

    def _ensure_sidebar_action_group(self):
        if getattr(self, "_sidebar_action_group", None) is not None:
            return
        group = Gio.SimpleActionGroup()
        for name, handler in (
            ("refresh", self._act_sidebar_refresh),
            ("import", self._act_sidebar_import),
            ("sync-covers", self._act_sidebar_sync_covers),
            ("open-folder", self._act_sidebar_open_folder),
        ):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", handler)
            group.add_action(action)
        self.insert_action_group("sidebar", group)
        self._sidebar_action_group = group

    def _act_sidebar_refresh(self, _action, _param):
        console = self._sidebar_menu_console
        logger.info("sidebar context action: refresh console=%s", console)
        if console in (ALL_CONSOLES_ID, FAVORITES_ID):
            self._rescan_all_consoles(show_toast=True)
        else:
            self._rescan_single_console(console, show_toast=True)

    def _act_sidebar_import(self, _action, _param):
        logger.info("sidebar context action: import console=%s", self._sidebar_menu_console)
        self._on_import_clicked(None)

    def _act_sidebar_sync_covers(self, _action, _param):
        console = self._sidebar_menu_console
        logger.info("sidebar context action: sync_covers console=%s", console)
        if console in (ALL_CONSOLES_ID, FAVORITES_ID):
            self._start_cover_sync(scope="all", selected_console=None)
        else:
            self._start_cover_sync(scope="console", selected_console=console)

    def _act_sidebar_open_folder(self, _action, _param):
        console = self._sidebar_menu_console
        logger.info("sidebar context action: open_folder console=%s", console)
        self._open_path_in_file_manager(self.roms_path / console)

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
            empty = Adw.StatusPage(
                icon_name="folder-open-symbolic",
                title=self.t("library.empty.title"),
                description=self.t("library.empty.body"),
            )
            choose = Gtk.Button(label=self.t("library.empty.action"))
            choose.add_css_class("suggested-action")
            choose.add_css_class("pill")
            choose.set_halign(Gtk.Align.CENTER)
            choose.connect("clicked", lambda _b: self._choose_roms_path())
            empty.set_child(choose)
            self.content_stack.add_titled(empty, "library-empty", "Library")

        target_view = preferred_view
        if target_view is None:
            target_view = previous_visible or self.current_console

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
        self._update_window_title(None)

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

    def _on_console_selected(self, _listbox, row):
        if not row:
            return
        # A selection belongs to the page it was made on, so leaving drops it.
        self._clear_selection()
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
        self._update_window_title(self.current_console)
        # On a collapsed (narrow) layout, reveal the content pane.
        if self.split_view.get_collapsed():
            self.split_view.set_show_content(True)

    def _set_search_enabled(self, enabled):
        if not enabled:
            self.search_entry.set_text("")
            if hasattr(self, "search_button"):
                self.search_button.set_active(False)
        if hasattr(self, "search_button"):
            self.search_button.set_sensitive(enabled)
        self.search_entry.set_sensitive(enabled)

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

    def _open_roms_folder(self):
        self._open_path_in_file_manager(self.config_manager.get_roms_path())

    def _open_console_bios_folder(self, console):
        bios_dir = get_console_bios_dir(self.config_manager, console)
        bios_dir.mkdir(parents=True, exist_ok=True)
        self._open_path_in_file_manager(bios_dir)

    def _reveal_rom_in_files(self, rom):
        self._reveal_in_file_manager(rom.get("path", ""))

    def _reveal_in_file_manager(self, path):
        """Open the file manager with ``path`` selected, not just its folder.

        Uses the freedesktop FileManager1 interface, which Nautilus, Nemo,
        Dolphin and Thunar all implement. If no such service is on the bus we
        fall back to opening the containing folder -- worse, but not nothing.
        """
        path = Path(path)
        if not path.exists():
            self._toast(self.t("context.reveal.missing", name=path.name), timeout=4)
            return

        try:
            connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            connection.call_sync(
                "org.freedesktop.FileManager1",
                "/org/freedesktop/FileManager1",
                "org.freedesktop.FileManager1",
                "ShowItems",
                GLib.Variant("(ass)", ([path.as_uri()], "")),
                None,
                Gio.DBusCallFlags.NONE,
                5000,
                None,
            )
            logger.info("reveal in file manager: path=%s", path)
            return
        except GLib.Error as exc:
            logger.info("FileManager1 unavailable (%s); opening parent folder", exc)

        self._open_path_in_file_manager(path.parent)

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

        # Ordering is _render_console_page's job now: it applies whichever sort
        # order the user picked, to every page alike.
        self._render_console_page(ALL_CONSOLES_ID, all_roms)
        self._console_loaded[ALL_CONSOLES_ID] = True

    def _render_console_page(self, console, roms):
        scroll = self._console_pages[console]
        roms = self._sorted_roms(roms)
        if not roms:
            if console == FAVORITES_ID:
                status = Adw.StatusPage(
                    icon_name="starred-symbolic",
                    title=self.t("favorites.empty.title"),
                    description=self.t("favorites.empty.body"),
                )
            elif console == ALL_CONSOLES_ID:
                status = Adw.StatusPage(
                    icon_name="folder-open-symbolic",
                    title=self.t("console.empty.title"),
                    description=self.t("empty.all_indexed"),
                )
            else:
                status = Adw.StatusPage(
                    icon_name="applications-games-symbolic",
                    title=self.t("console.empty.title"),
                    description=str(self.playlist_manager.get_playlist_path(console)),
                )
            scroll.set_child(status)
            self._grids.pop(console, None)
            if console == self.current_console:
                self._update_window_title(console)
            return

        grid = RomGrid(
            console,
            roms,
            self.on_launch_game,
            self._toggle_favorite_from_ui,
            self._reveal_rom_in_files,
            self._choose_cover_for_rom,
            self._remove_cover_for_rom,
            self._is_favorite_rom,
            self._has_local_cover,
            self.t,
            self.roms_path,
            ui_settings=self.config_manager.get_ui_settings(),
            mixed_consoles=console in (ALL_CONSOLES_ID, FAVORITES_ID),
            on_rename_rom=self._rename_rom_from_ui,
            on_delete_rom=self._confirm_delete_roms,
            on_selection_changed=self._on_selection_changed,
            context_services=self._rom_context_services,
        )
        self._grids[console] = grid
        # The page was rebuilt, so whatever was selected on it is gone.
        self._on_selection_changed([])
        scroll.set_child(grid)
        if console == self.current_console:
            self._update_window_title(console)

    def set_rom_core(self, rom, core_filename):
        """Persist a per-ROM core override (``core_filename=None`` clears it)."""
        self.config_manager.set_rom_core(rom["path"], core_filename)
        if core_filename is None:
            self._toast(self.t("toast.core.rom_auto", name=rom["name"]))
            return
        label = self.core_catalog.display_name_for(core_filename)
        self._toast(self.t("toast.core.rom_set", name=rom["name"], core=label))
        self._warn_missing_bios_for_core(rom["console"], core_filename)

    def _warn_missing_bios_for_core(self, console, core_filename):
        missing = find_missing_required_for_core(self.config_manager, console, core_filename)
        if missing:
            self._toast(
                self.t("toast.core.bios_warning", core=core_filename, bios=", ".join(missing)),
                timeout=6,
            )

    def set_rom_shader(self, rom, shader_id):
        """Persist a per-ROM shader override (``shader_id=None`` clears it)."""
        self.config_manager.set_rom_shader(rom["path"], rom["console"], shader_id)
        if shader_id is None:
            label = self.t("context.shader.use_console_short")
        else:
            label = self.shader_catalog.label_for_shader(shader_id)
        self._toast(self.t("toast.shader.rom_set", name=rom["name"], shader=label))

    def _is_favorite_rom(self, rom):
        return self.playlist_manager.is_favorite(rom["path"])

    def _has_local_cover(self, rom, kind=COVER_ART):
        return bool(find_local_art(Path(self.roms_path), rom["console"], rom["name"], kind))

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

    def _choose_cover_for_rom(self, rom, on_done=None, kind=COVER_ART):
        title_key = "dialog.label.choose.title" if kind == LABEL_ART else "dialog.cover.choose.title"
        chooser = Gtk.FileChooserDialog(
            title=self.t(title_key),
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
            save_local_art(Path(self.roms_path), rom["console"], rom["name"], path, kind)
            updated_key = "toast.label.updated" if kind == LABEL_ART else "toast.cover.updated"
            toast = Adw.Toast(title=self.t(updated_key, name=rom["name"]))
            toast.set_timeout(3)
            self.toast_overlay.add_toast(toast)
            if callable(on_done):
                on_done()

        chooser.connect("response", _on_response)
        chooser.show()

    def _remove_cover_for_rom(self, rom, on_done=None, kind=COVER_ART):
        removed = remove_local_art(Path(self.roms_path), rom["console"], rom["name"], kind)
        if removed:
            removed_key = "toast.label.removed" if kind == LABEL_ART else "toast.cover.removed"
            toast = Adw.Toast(title=self.t(removed_key, name=rom["name"]))
            toast.set_timeout(3)
            self.toast_overlay.add_toast(toast)
            if callable(on_done):
                on_done()

    def _rename_rom_from_ui(self, rom):
        entry = Gtk.Entry()
        entry.set_text(rom["name"])
        entry.set_activates_default(True)

        dialog = Adw.AlertDialog(
            heading=self.t("dialog.rename.heading"),
            body=self.t("dialog.rename.body"),
        )
        dialog.set_extra_child(entry)
        dialog.add_response("cancel", self.t("dialog.cancel"))
        dialog.add_response("rename", self.t("dialog.rename.confirm"))
        dialog.set_response_appearance("rename", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("rename")
        dialog.set_close_response("cancel")

        def _on_response(_dlg, response):
            if response != "rename":
                return
            self._apply_rename(rom, entry.get_text())

        dialog.connect("response", _on_response)
        dialog.present(self)

        def _focus_entry():
            # After present(), and through the dialog: AdwAlertDialog picks its
            # own focus while mapping (the default response), so a plain
            # grab_focus here loses the race. Selecting the name means typing
            # replaces it and Enter confirms, so renaming never needs the mouse.
            dialog.set_focus(entry)
            entry.select_region(0, -1)
            return False

        GLib.idle_add(_focus_entry)

    def _apply_rename(self, rom, new_name):
        try:
            renamed = rename_rom(Path(self.roms_path), rom, new_name)
        except RomActionError as exc:
            self._toast(self.t("toast.rom.rename_failed", error=str(exc)), timeout=6)
            return
        self.playlist_manager.repath_rom(rom["console"], rom["path"], renamed["path"])
        self.play_history.repath(rom["path"], renamed["path"])
        self.config_manager.repath_rom_shader(rom["path"], renamed["path"])
        self.config_manager.repath_rom_core(rom["path"], renamed["path"])
        self._toast(self.t("toast.rom.renamed", name=renamed["name"]))
        self._reload_current_page()

    def _confirm_delete_roms(self, roms):
        roms = [rom for rom in roms or [] if rom]
        if not roms:
            return
        heading = (
            self.t("dialog.delete.heading", name=roms[0]["name"])
            if len(roms) == 1
            else self.t("dialog.delete.heading.many", count=len(roms))
        )
        dialog = Adw.AlertDialog(heading=heading, body=self.t("dialog.delete.body"))
        dialog.add_response("cancel", self.t("dialog.cancel"))
        dialog.add_response("delete", self.t("dialog.delete.confirm"))
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")

        def _on_response(_dlg, response):
            if response == "delete":
                self._delete_roms(roms)

        dialog.connect("response", _on_response)
        dialog.present(self)

    def _delete_roms(self, roms):
        deleted = 0
        for rom in roms:
            try:
                delete_rom(Path(self.roms_path), rom)
            except RomActionError as exc:
                logger.warning("rom delete failed: rom=%s error=%s", rom.get("name"), exc)
                self._toast(self.t("toast.rom.delete_failed", name=rom["name"]), timeout=6)
                continue
            self.playlist_manager.forget_rom(rom["console"], rom["path"])
            self.play_history.forget(rom["path"])
            self.config_manager.forget_rom_shader(rom["path"])
            self.config_manager.forget_rom_core(rom["path"])
            deleted += 1

        if deleted:
            self._toast(self.t("toast.rom.deleted", count=deleted))
        self._on_selection_changed([])
        self._reload_current_page()

    def _sync_covers_for_selection(self):
        selected = list(self._selected_roms)
        if not selected:
            return
        by_console = {}
        for rom in selected:
            by_console.setdefault(rom["console"], []).append(rom)
        self._clear_selection()
        self._start_cover_sync(scope="selection", selected_console=None, library=by_console)

    def _reload_current_page(self):
        """Re-read the page the user is looking at after the library changed."""
        console = self.current_console
        if console == ALL_CONSOLES_ID:
            self._ensure_all_loaded()
        elif console == FAVORITES_ID:
            self._ensure_favorites_loaded()
        else:
            self._ensure_console_loaded(console)

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
            self._toast(self.t("toast.sync_no_consoles"))
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

    # ----- ROM import (header button + drag and drop) -----

    def _install_drop_target(self, widget):
        drop_target = Gtk.DropTarget.new(Gdk.FileList, Gdk.DragAction.COPY)
        drop_target.connect("enter", self._on_drop_enter)
        drop_target.connect("leave", self._on_drop_leave)
        drop_target.connect("drop", self._on_drop)
        widget.add_controller(drop_target)

    def _on_drop_enter(self, _target, _x, _y):
        self.content_stack.add_css_class("rom-drop-active")
        self.banner.set_title(self.t("import.drop_hint"))
        self.banner.set_revealed(True)
        return Gdk.DragAction.COPY

    def _on_drop_leave(self, _target):
        self.content_stack.remove_css_class("rom-drop-active")
        self._refresh_banner()

    def _on_drop(self, _target, value, _x, _y):
        self.content_stack.remove_css_class("rom-drop-active")
        self._refresh_banner()
        paths = [f.get_path() for f in value.get_files() if f.get_path()]
        if not paths:
            return False
        logger.info("rom import: dropped %d path(s)", len(paths))
        self._begin_import(paths)
        return True

    def _on_import_clicked(self, _button):
        dialog = Gtk.FileDialog()
        dialog.set_title(self.t("import.dialog.title"))
        dialog.set_modal(True)

        rom_filter = Gtk.FileFilter()
        rom_filter.set_name(self.t("import.dialog.filter"))
        for ext in IMPORTABLE_EXTENSIONS:
            suffix = ext.lstrip(".")
            rom_filter.add_pattern(f"*.{suffix}")
            rom_filter.add_pattern(f"*.{suffix.upper()}")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(rom_filter)
        dialog.set_filters(filters)
        dialog.set_default_filter(rom_filter)

        dialog.open_multiple(self, None, self._on_import_files_chosen)

    def _on_import_files_chosen(self, dialog, result):
        try:
            files = dialog.open_multiple_finish(result)
        except GLib.Error:
            # Dismissed by the user; nothing to report.
            return
        if files is None:
            return
        paths = []
        for index in range(files.get_n_items()):
            path = files.get_item(index).get_path()
            if path:
                paths.append(path)
        if paths:
            self._begin_import(paths)

    def _begin_import(self, paths):
        """Resolve ambiguous extensions, then run the import in the background."""
        if getattr(self, "_import_running", False):
            self._toast(self.t("import.running"))
            return

        # In "All" or "Favorites" there is no console context to import into, so
        # ask outright instead of silently guessing from the file extension.
        if self.current_console in (None, ALL_CONSOLES_ID, FAVORITES_ID):
            self._ask_target_console(paths)
            return

        self._continue_import(paths, forced_console=None)

    def _ask_target_console(self, paths):
        """Ask which console to import into, defaulting to auto-detection."""
        dropdown = self._build_console_dropdown(
            SYSTEM_IDS,
            default_id=ALL_CONSOLES_ID,
            include_all=True,
            all_label_key="import.console.auto",
        )

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.append(dropdown)

        dialog = Adw.AlertDialog(
            heading=self.t("import.console.heading"),
            body=self.t("import.console.body"),
        )
        dialog.set_extra_child(box)
        dialog.add_response("cancel", self.t("dialog.cancel"))
        dialog.add_response("import", self.t("import.console.confirm"))
        dialog.set_response_appearance("import", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("import")
        dialog.set_close_response("cancel")

        def _on_response(_dlg, response):
            if response != "import":
                return
            chosen = self._get_console_dropdown_active_id(dropdown)
            # The "detect automatically" entry reuses the ALL sentinel id.
            forced = None if chosen == ALL_CONSOLES_ID else chosen
            self._continue_import(paths, forced_console=forced)

        dialog.connect("response", _on_response)
        dialog.present(self)

    def _continue_import(self, paths, forced_console):
        """Run the import, forcing a console or falling back to detection."""
        if forced_console:
            # One console for the whole batch: no per-extension question needed.
            self._run_import(paths, {}, forced_console=forced_console)
            return

        ambiguous = collect_ambiguous_extensions(paths)
        self._resolve_ambiguous_then_import(paths, list(ambiguous.items()), {})

    def _resolve_ambiguous_then_import(self, paths, pending, overrides):
        if not pending:
            self._run_import(paths, overrides)
            return

        extension, candidates = pending[0]
        remaining = pending[1:]

        dialog = Adw.AlertDialog(
            heading=self.t("import.unknown_console"),
            body=self.t("import.choose_console.body", extension=extension),
        )
        dialog.add_response("cancel", self.t("dialog.cancel"))
        for console in candidates:
            dialog.add_response(console, f"{console} — {get_system_display_name(console)}")
        dialog.set_default_response(candidates[0])
        dialog.set_close_response("cancel")

        def _on_response(_dlg, response):
            if response == "cancel":
                return
            overrides[extension] = response
            self._resolve_ambiguous_then_import(paths, remaining, overrides)

        dialog.connect("response", _on_response)
        dialog.present(self)

    def _run_import(self, paths, overrides, forced_console=None):
        self._import_running = True
        task_id = self._begin_task("import", self.t("import.progress.starting"))

        def _on_progress(evt):
            GLib.idle_add(
                self._update_task,
                task_id,
                evt.get("current", 0),
                evt.get("total", 0),
                # The counter is rendered by _refresh_banner; don't repeat it here.
                self.t("import.progress"),
            )

        def _on_done(summary):
            GLib.idle_add(self._on_import_done_ui, task_id, summary)

        import_roms_async(
            paths=paths,
            roms_dir=self.roms_path,
            on_done=_on_done,
            on_progress=_on_progress,
            console_overrides=overrides,
            forced_console=forced_console,
        )

    def _on_import_done_ui(self, task_id, summary):
        self._import_running = False
        self._finish_task(task_id)

        imported = len(summary["imported"])
        skipped = len(summary["skipped"])
        unknown = len(summary["unknown"])
        errors = len(summary["errors"])
        extracted = len(summary.get("extracted", []))
        logger.info(
            "rom import done: imported=%d extracted=%d skipped=%d unknown=%d errors=%d",
            imported, extracted, skipped, unknown, errors,
        )

        if imported:
            message = self.t("import.done", imported=imported, skipped=skipped)
            if extracted:
                # Say so explicitly: the user chose a .zip and got loose files.
                message = f"{message} — {self.t('import.extracted', count=extracted)}"
            self._toast(message, timeout=6 if extracted else 5)
            # New files on disk: rebuild the playlists so they show up.
            self._rescan_all_consoles(show_toast=False)
        elif unknown or errors:
            self._toast(self.t("import.failed", unknown=unknown + errors), timeout=5)
        else:
            self._toast(self.t("import.nothing_new"), timeout=4)
        return False

    def _on_sync_covers_clicked(self, _button):
        self._sync_covers_for_current_scope()

    def _sync_covers_for_current_scope(self):
        """Sync covers for the selected console, or all of them when 'All' is on."""
        if not self.visible_consoles:
            self._toast(self.t("toast.sync_no_consoles"))
            return
        selected = self.current_console
        if selected in self.visible_consoles:
            self._start_cover_sync(scope="console", selected_console=selected)
        else:
            self._start_cover_sync(scope="all", selected_console=None)

    def _start_cover_sync(self, scope, selected_console, library=None):
        if self._cover_sync_running:
            toast = Adw.Toast(title=self.t("toast.sync_running"))
            toast.set_timeout(3)
            self.toast_overlay.add_toast(toast)
            return

        # A caller can hand in the exact ROMs to cover (a selection); otherwise
        # the scope decides how much of the library is read.
        if library is None:
            library = {}
            if scope == "console" and selected_console in self.visible_consoles:
                library[selected_console] = self.playlist_manager.load_playlist(selected_console)
            else:
                for console in self.visible_consoles:
                    library[console] = self.playlist_manager.load_playlist(console)

        self._cover_sync_running = True
        # Cooperative cancel: the worker polls this between ROMs and between
        # candidate URLs, so stopping takes at most one HTTP request.
        cancel_event = Event()
        self._cover_sync_cancel = cancel_event
        task_id = self._begin_task(
            "covers",
            self.t("status.covers.starting"),
            on_cancel=cancel_event.set,
        )
        toast = Adw.Toast(title=self.t("toast.sync_started"))
        toast.set_timeout(3)
        self.toast_overlay.add_toast(toast)

        def _on_progress(evt):
            GLib.idle_add(
                self._update_task,
                task_id,
                evt.get("processed", 0),
                evt.get("total", 0),
                # The counter is rendered by _refresh_banner; don't repeat it here.
                self.t("status.covers.progress"),
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
            should_cancel=cancel_event.is_set,
        )

    def _on_cover_sync_done_ui(self, task_id, summary):
        self._cover_sync_running = False
        self._cover_sync_cancel = None
        self._finish_task(task_id)
        # Covers already downloaded are kept -- each is an independent file, so
        # a stopped run leaves useful work rather than a half-written state.
        done_key = "toast.sync_cancelled" if summary.get("cancelled") else "toast.sync_done"
        toast = Adw.Toast(
            title=self.t(
                done_key,
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
        if success:
            # Stamped here rather than on exit: a game that fails to close
            # cleanly was still played, and this is the only point that knows
            # which ROM was asked for.
            self.play_history.record_launch(rom["path"])
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
