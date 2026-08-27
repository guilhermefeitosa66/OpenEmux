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
from openemux.core.platform import IS_WINDOWS
from openemux.core.play_history import PlayHistory
from openemux.core import cartridge_render
from openemux.core import game_window_support
from openemux.core.config import COVER_ART_TYPE_CARTRIDGE_LABEL
from openemux.core.cover_sync import (
    build_artwork_passes,
    sync_artwork_async,
)
from openemux.core.collections import CollectionManager
from openemux.core.playlist_manager import PlaylistManager
from openemux.core.paths import display_text, get_project_root
from openemux.core.rom_actions import RomActionError, delete_rom, rename_rom
from openemux.core.runtime_manager import RuntimeManager
from openemux.core.theme import toggled_theme
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
from openemux.core.state_recovery import quarantined_files, reset_quarantine_log
from openemux.core.tips import TIP_ICON, TIP_KEYS, pick_next_tip, render_tip
from openemux import __version__
from openemux.core.systems import SYSTEM_IDS, get_system_display_name
from openemux.i18n import LANGUAGE_META, tr
from openemux.core.ui_gamepad import GamepadNavigator
from openemux.ui.grid import RomGrid
from openemux.ui.game_session import GameSession
from openemux.ui.import_flow import ImportFlow
from openemux.ui.library_pages import LibraryPages
from openemux.ui.retranslate import RetranslateRegistry
from openemux.ui.console_icons import console_icon
from openemux.ui.console_sidebar import ConsoleSidebar
from openemux.ui.file_dialogs import image_filters
# Re-exported: `from openemux.ui.window import FAVORITES_ID` is what the tests
# and the test book already say, and the vocabulary is shared, not the
# window's (issue #237).
from openemux.ui.scopes import (  # noqa: F401
    ALL_CONSOLES_ID,
    COLLECTION_ID_PREFIX,
    FAVORITES_ID,
    LIBRARY_EMPTY_ID,
    collection_scope,
    collection_slug,
    is_collection_scope,
    landing_view,
    sidebar_row_ids,
)
from openemux.ui.rom_context import RomContextMenuServices
from openemux.ui.task_banner import TaskBanner
from openemux.ui.navigation import NavigationController
from openemux.ui.preferences import OpenEmuxPreferences
from openemux.ui import theming
from openemux.ui.welcome import WelcomeAssistant

logger = logging.getLogger(__name__)

#: Slots reserved in the bottom bar for input hints (see set_hints).
MAX_INPUT_HINTS = 6



class OpenEmuxWindow(Adw.ApplicationWindow):
    def __init__(self, application, **kwargs):
        super().__init__(application=application, **kwargs)

        self.config_manager = application.config_manager
        self.locale = self.config_manager.get_locale()
        self.set_title("OpenEmux")
        self._setup_window_icon()
        self.set_default_size(*self._default_window_size())
        # Minimum size required for the adaptive breakpoint to compute layout.
        self.set_size_request(360, 420)
        self.load_css()

        self.roms_path = self.config_manager.get_roms_path()
        self.scanner = RomScanner(self.roms_path)
        self.playlist_manager = PlaylistManager(self.config_manager, self.scanner)
        self.collection_manager = CollectionManager(
            self.config_manager.get_playlists_dir() / "collections",
            entries_loader=self.playlist_manager.entries_for_paths,
        )
        self.current_console = None
        # Every content-stack page, its grid and its load state: one owner
        # for the four dictionaries that used to move separately (issue #237).
        self.pages = LibraryPages(self)
        self.play_history = PlayHistory(self.config_manager.get_play_history_file())
        self.visible_consoles = []
        self._cover_sync_running = False
        self._scan_running = False
        # A rescan asked for while one was running, to run when it ends (#225).
        self._rescan_pending = None
        self.imports = ImportFlow(self)
        # Callbacks that re-apply translated text, registered where each
        # widget is built -- see _translatable.
        self._retranslate = RetranslateRegistry()
        # "Show only ROMs without artwork" (issue #127). Session-only: a way
        # to work through the gaps, not a mode to leave the library in.
        self._filter_missing_artwork = False
        # The progress banner's registry. Created before the header bars, so
        # a task begun during construction is remembered until there is a
        # banner to draw it on (issue #237).
        self.tasks = TaskBanner(self.t)

        project_root = str(get_project_root())
        self.runtime_manager = RuntimeManager(
            project_root, self.config_manager, dispatch=GLib.idle_add
        )
        # GTK is up by now, so the one authority on whether this process can
        # host an embed -- the display it actually opened -- can finally be
        # asked, and published where the launcher will see it before it
        # writes a single override. Guessing from the environment is what let
        # a Wayland session get RetroArch's decorations stripped with no
        # wrapper to hold the window (issues #212, #267).
        from openemux.ui.game_window import display_supports_embedding

        game_window_support.set_display_embeddable(display_supports_embedding())

        # Launch, the wrapper window, the relaunch dance and the runtime
        # poll: one collaborator, because they only make sense together
        # (issue #237).
        self.game = GameSession(self)
        # Covers downloaded by a running sync, waiting for a batched reveal
        # (issue #187): flushed by size, by time, or when the sync moves on
        # to another console.
        self._reveal_pending = []
        self._reveal_timer = None
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
        self.sidebar = ConsoleSidebar(self)
        # navigation.py steers the list directly, so it keeps a plain name.
        self.console_list = self.sidebar.list_box
        self.split_view.set_sidebar(self.sidebar.page)
        self.split_view.set_content(self._build_content())
        self.toast_overlay.set_child(self.split_view)

        breakpoint = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 550sp"))
        breakpoint.add_setter(self.split_view, "collapsed", True)
        # The content header is dense at full width. At this breakpoint the
        # sidebar collapses onto the content anyway, so the hamburger is one
        # navigation away regardless and the settings pair is the right thing
        # to drop first (issue #131).
        breakpoint.add_setter(self.settings_box, "visible", False)
        self.add_breakpoint(breakpoint)

        # Below this width the header cannot hold the segmented view switcher;
        # the layout menu (which lists the same modes) remains the way in.
        segment_breakpoint = Adw.Breakpoint.new(
            Adw.BreakpointCondition.parse("max-width: 700sp")
        )
        segment_breakpoint.add_setter(self.view_mode_segment, "visible", False)
        self.add_breakpoint(segment_breakpoint)

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
        self.connect("close-request", self._on_close_stop_game)

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
        GLib.timeout_add_seconds(1, self.game.poll)

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
        # DEBUG on purpose: this fires on every mouse press anywhere in the
        # window, which at INFO buried the log in click traces (issue #221).
        # It is a debugging aid -- run with the root logger at DEBUG to get it.
        logger.debug(
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
        self._sync_console_header_controls()

    def _console_scope_id(self):
        """The console this page is showing, or None.

        All, Favourites and a collection each span several consoles, so there
        is no single input profile to jump to from them.
        """
        scope = self.current_console
        return scope if scope in SYSTEM_IDS else None

    def _sync_console_header_controls(self):
        """Show the header controls that only make sense on a console page."""
        button = getattr(self, "console_input_btn", None)
        if button is None:
            return  # called before the header exists
        button.set_visible(self._console_scope_id() is not None)

    def t(self, key, **kwargs):
        # Escaped on the way out: these strings become GTK labels, tooltips
        # and toasts, and the ones interpolating a ROM name can carry a lone
        # surrogate from a non-UTF-8 filename. GTK cannot take one -- it
        # raises inside PyGObject and takes the whole render with it (#214).
        return display_text(tr(self.locale, key, **kwargs))

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
        self._translatable(lambda: self.search_button.set_tooltip_text(self.t("header.search.toggle")))
        header.pack_end(self.search_button)

        header.pack_end(self._build_theme_button())

        header.pack_end(self._build_view_mode_button())
        header.pack_end(self._build_view_mode_segment())

        # The two settings buttons ride in one box so the narrow breakpoint
        # can drop them together, without fighting the per-scope visibility
        # of the controller one.
        self.settings_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

        # Straight to this console's controller mapping. Only shown on a
        # console's own page: on All, Favourites or a collection there is no
        # single console to configure.
        self.console_input_btn = Gtk.Button()
        self.console_input_btn.set_icon_name("input-gaming-symbolic")
        self._translatable(lambda: self.console_input_btn.set_tooltip_text(self.t("header.console_input")))
        self.console_input_btn.set_visible(False)
        self.console_input_btn.connect(
            "clicked", lambda _b: self._open_preferences(page="input")
        )
        self.settings_box.append(self.console_input_btn)

        # The primary menu lives only in the sidebar header, so Preferences
        # cost a trip through the hamburger -- and once the split view
        # collapses, a back-navigation first. The action already exists, so
        # this is only a second way in (issue #131).
        self.preferences_btn = Gtk.Button()
        # preferences-system-symbolic, not emblem-system-symbolic: several
        # common icon themes draw the latter as a hamburger, which would put
        # two identical menu glyphs in adjacent header bars.
        self.preferences_btn.set_icon_name("preferences-system-symbolic")
        self._translatable(lambda: self.preferences_btn.set_tooltip_text(self.t("header.preferences")))
        self.preferences_btn.set_action_name("win.preferences")
        self.settings_box.append(self.preferences_btn)
        header.pack_end(self.settings_box)

        refresh_btn = Gtk.Button()
        refresh_btn.set_icon_name("view-refresh-symbolic")
        self._translatable(lambda: refresh_btn.set_tooltip_text(self.t("header.refresh")))
        refresh_btn.connect("clicked", self._on_refresh_clicked)
        header.pack_start(refresh_btn)

        self.import_btn = Gtk.Button()
        self.import_btn.set_icon_name("folder-download-symbolic")
        self._translatable(lambda: self.import_btn.set_tooltip_text(self.t("header.import")))
        self.import_btn.connect("clicked", self.imports.open_picker)
        header.pack_start(self.import_btn)

        self.covers_btn = Gtk.Button()
        self.covers_btn.set_icon_name("emblem-photos-symbolic")
        self._translatable(lambda: self.covers_btn.set_tooltip_text(self.t("header.sync_covers")))
        self.covers_btn.connect("clicked", self._on_sync_covers_clicked)
        header.pack_start(self.covers_btn)

        toolbar.add_top_bar(header)

        # Search revealed on demand (HIG: search is a mode, not a permanent field).
        self.search_entry = Gtk.SearchEntry()
        self.search_entry.set_hexpand(True)
        self._translatable(lambda: self.search_entry.set_placeholder_text(self.t("header.search")))
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
        self.tasks.attach(self.banner)
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
        self.imports.install_drop_target(self.content_stack)

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

    #: Segmented-control icon per view mode. Unlike the menu-button icon these
    #: three sit side by side, so each mode needs its own glyph. Adwaita only:
    #: an icon from another installed theme renders as a broken image on a
    #: stock GNOME system (`make icons` browses the safe set).
    VIEW_MODE_SEGMENT_ICONS = {
        # A tighter, fuller 2x2 than view-grid, which reads better against the
        # other two at 16px.
        "cover": "preferences-desktop-apps-symbolic",
        # A Zip-disk glyph: the closest thing Adwaita has to a cartridge, and
        # far more on-the-nose than the gamepad this used to be.
        "cartridge": "media-zip-symbolic",
        "list": "view-list-symbolic",
    }

    def _build_view_mode_segment(self):
        """Cover / Cartridge / List as one visible click each (issue #70).

        Linked toggle buttons bound to the stateful ``win.view-mode`` action:
        GTK keeps them radio-exclusive and in sync with the menu entries for
        free, so per-scope persistence is untouched. On narrow windows the
        segment hides (a breakpoint below) and the menu remains the way in.
        """
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        box.add_css_class("linked")
        self._view_segment_buttons = {}
        for mode in VIEW_MODES:
            button = Gtk.ToggleButton()
            button.set_icon_name(self.VIEW_MODE_SEGMENT_ICONS.get(mode, "view-grid-symbolic"))
            self._translatable(
                lambda b=button, m=mode: b.set_tooltip_text(self.t(f"view_mode.{m}"))
            )
            button.set_action_name("win.view-mode")
            button.set_action_target_value(GLib.Variant("s", mode))
            box.append(button)
            self._view_segment_buttons[mode] = button
        self.view_mode_segment = box
        return box

    def _build_theme_button(self):
        """One click between light and dark (issue #198).

        The icon shows what the click *gives* you -- a sun while the app is
        dark, a moon while it is light -- rather than what is on screen, so
        the button reads as an action instead of a status light. The full
        three-way choice, "System" included, lives in Preferences > System.
        """
        self.theme_btn = Gtk.Button()
        self.theme_btn.connect("clicked", self._on_theme_toggle_clicked)
        # Under "System" the desktop can flip the appearance while the app is
        # open, and the icon has to follow it.
        #
        # Adw.StyleManager.get_default() lives as long as the process, so a
        # handler left connected to it keeps this window alive after it is
        # closed -- the closure holds `self`. The id is kept and dropped on
        # close-request (issue #237).
        self._style_manager = Adw.StyleManager.get_default()
        self._style_manager_handler = self._style_manager.connect(
            "notify::dark", lambda *_: self._sync_theme_button()
        )
        self.connect("close-request", self._on_close_disconnect_style_manager)
        self._translatable(self._sync_theme_button)
        self._sync_theme_button()
        return self.theme_btn

    def _sync_theme_button(self):
        button = getattr(self, "theme_btn", None)
        if button is None:
            return  # a retranslate that ran before the header was built
        dark = theming.is_dark()
        button.set_icon_name(
            "weather-clear-symbolic" if dark else "weather-clear-night-symbolic"
        )
        button.set_tooltip_text(
            self.t("header.theme.to_light" if dark else "header.theme.to_dark")
        )

    def _on_close_disconnect_style_manager(self, *_args):
        """Let go of the process-lifetime style manager on the way out."""
        handler = getattr(self, "_style_manager_handler", None)
        if handler is not None:
            self._style_manager.disconnect(handler)
            self._style_manager_handler = None
        return False

    def _on_theme_toggle_clicked(self, _button):
        theme = toggled_theme(theming.is_dark())
        self.config_manager.set_theme(theme)
        theming.apply_theme(theme)
        self._sync_theme_button()

    def _build_view_mode_button(self):
        """The layout switcher, in the header where the user browses.

        It used to be a switch buried in Preferences, which is the wrong place
        for something people flip while looking at their library. The zoom
        controls live in the same menu, as they do in GNOME Files.
        """
        self.view_mode_button = Gtk.MenuButton()
        self._translatable(lambda: self.view_mode_button.set_tooltip_text(self.t("header.view_mode")))
        self._populate_view_mode_menu()
        return self.view_mode_button

    def _populate_view_mode_menu(self):
        """(Re)build the layout menu so it acts on the page in view.

        The menu is scope-aware: its heading names the scope being edited and
        the "Use the global layout" item reflects whether this page follows the
        global default or carries its own layout. It is rebuilt when the scope
        changes so both stay honest.
        """
        scope_label = self.sidebar.label_for(self._current_scope())
        menu = Gio.Menu()

        # The scope banner, and the toggle between global and this page's own.
        scope_section = Gio.Menu()
        scope_section.append(self.t("layout.follow_global"), "win.layout-follow-global")
        menu.append_section(self.t("layout.scope_header", scope=scope_label), scope_section)

        mode_section = Gio.Menu()
        for mode in VIEW_MODES:
            mode_section.append(self.t(f"view_mode.{mode}"), f"win.view-mode::{mode}")
        menu.append_section(None, mode_section)

        # Sorting sits behind a submenu: six orders as a flat list would bury
        # the three view modes above them.
        sort_menu = Gio.Menu()
        for order in SORT_ORDERS:
            sort_menu.append(self.t(f"sort_order.{order}"), f"win.sort-order::{order}")
        sort_section = Gio.Menu()
        sort_section.append_submenu(self.t("header.sort_by"), sort_menu)
        menu.append_section(None, sort_section)

        # A filter, not a layout -- but this is the menu people already open
        # to change what the library shows them (issue #127).
        filter_section = Gio.Menu()
        filter_section.append(
            self.t("filter.missing_artwork"), "win.filter-missing-artwork"
        )
        menu.append_section(None, filter_section)

        zoom_section = Gio.Menu()
        zoom_item = Gio.MenuItem.new(None, None)
        # A custom item: a menu model cannot express a -/+ stepper, and
        # Gtk.PopoverMenu fills the slot with whatever widget is registered
        # under this id.
        zoom_item.set_attribute_value("custom", GLib.Variant("s", "zoom"))
        zoom_section.append_item(zoom_item)
        menu.append_section(None, zoom_section)

        self.view_mode_button.set_menu_model(menu)
        self.view_mode_button.set_icon_name(
            self.VIEW_MODE_ICONS.get(self._view_mode, "view-grid-symbolic")
        )
        # Re-setting the model rebuilds the popover, so the zoom stepper has to
        # be registered against the fresh one every time.
        popover = self.view_mode_button.get_popover()
        if popover is not None:
            popover.add_child(self._build_zoom_controls(), "zoom")

    def _build_zoom_controls(self):
        """A -/+ stepper with the current percentage between the buttons."""
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        box.add_css_class("zoom-controls")

        self.zoom_out_button = Gtk.Button.new_from_icon_name("zoom-out-symbolic")
        self.zoom_out_button.add_css_class("circular")
        self.zoom_out_button.add_css_class("flat")
        # Owned by the stepper, not by the window: this whole box is built
        # again every time the layout menu is repopulated, which is every
        # sidebar click. Registering unowned left two closures behind per
        # click, replayed in full on the next language change (issue #237).
        self._translatable(
            lambda: self.zoom_out_button.set_tooltip_text(self.t("header.zoom.out")),
            owner=box,
        )
        self.zoom_out_button.connect("clicked", lambda _b: self._step_zoom(-1))

        self.zoom_label = Gtk.Label()
        self.zoom_label.set_hexpand(True)
        self.zoom_label.add_css_class("numeric")

        self.zoom_in_button = Gtk.Button.new_from_icon_name("zoom-in-symbolic")
        self.zoom_in_button.add_css_class("circular")
        self.zoom_in_button.add_css_class("flat")
        self._translatable(
            lambda: self.zoom_in_button.set_tooltip_text(self.t("header.zoom.in")),
            owner=box,
        )
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
        self._write_scope_display("zoom", zoom)
        self._sync_zoom_controls()
        self._reload_current_page()
        self._toast(self.t("toast.zoom", percent=zoom_percent(zoom)), timeout=1)

    def _current_scope(self):
        """The page whose layout the controls edit: a console, All or Favorites."""
        return self.current_console or ALL_CONSOLES_ID

    # ----- the layout of the page being looked at -------------------------
    #
    # Read from the config for the current scope, never stored. These used to
    # be three fields kept in step by hand with the stateful actions and the
    # per-scope overrides -- three copies of one fact, and every path that
    # changed the layout had to remember all three (issue #237). The config is
    # the owner; the actions are a view of it, synced in one place
    # (_refresh_scope_settings); nothing else holds a copy.

    @property
    def _display_settings(self):
        return self.config_manager.get_display_settings(self._current_scope())

    @property
    def _view_mode(self):
        return self._display_settings["view_mode"]

    @property
    def _zoom(self):
        return self._display_settings["zoom"]

    @property
    def _sort_order(self):
        return self._display_settings["sort_order"]

    def _write_scope_display(self, key, value):
        """Persist a layout change against the right level.

        A page that carries its own layout keeps the change to itself; a page
        following the global default edits the global default -- which is how
        the global can be changed from any page, and why no control here is
        ever a silent no-op.
        """
        scope = self._current_scope()
        if self.config_manager.has_scope_override(scope):
            self.config_manager.set_scope_display(scope, key, value)
        else:
            setter = {
                "view_mode": self.config_manager.set_view_mode,
                "sort_order": self.config_manager.set_sort_order,
                "zoom": self.config_manager.set_zoom,
            }[key]
            setter(value)

    def _refresh_scope_settings(self):
        """Re-read the layout for the current scope and sync every control."""
        settings = self._display_settings

        view_action = self.lookup_action("view-mode")
        if view_action is not None and view_action.get_state().get_string() != settings["view_mode"]:
            view_action.set_state(GLib.Variant("s", settings["view_mode"]))
        sort_action = self.lookup_action("sort-order")
        if sort_action is not None and sort_action.get_state().get_string() != settings["sort_order"]:
            sort_action.set_state(GLib.Variant("s", settings["sort_order"]))
        follow_action = self.lookup_action("layout-follow-global")
        if follow_action is not None:
            follows = not self.config_manager.has_scope_override(self._current_scope())
            if follow_action.get_state().get_boolean() != follows:
                follow_action.set_state(GLib.Variant("b", follows))

        if hasattr(self, "view_mode_button"):
            self._populate_view_mode_menu()
        self._sync_zoom_controls()

    def _on_layout_follow_global_action(self, action, _param):
        follow = not action.get_state().get_boolean()
        action.set_state(GLib.Variant("b", follow))
        scope = self._current_scope()
        if follow:
            self.config_manager.clear_scope_override(scope)
        else:
            # Seed the page's own layout from what it shows now, so unchecking
            # changes nothing until the user actually picks something different.
            self.config_manager.enable_scope_override(scope)
        self._refresh_scope_settings()
        self._reload_current_page()
        key = "toast.layout.global" if follow else "toast.layout.scoped"
        self._toast(self.t(key, scope=self.sidebar.label_for(scope)), timeout=2)

    def _on_view_mode_action(self, action, value):
        mode = normalize_view_mode(value.get_string())
        action.set_state(GLib.Variant("s", mode))
        self._apply_view_mode(mode)

    def _apply_view_mode(self, mode):
        """Switch the library layout and re-render the page being looked at."""
        mode = normalize_view_mode(mode)
        if mode == self._view_mode:
            return
        self._write_scope_display("view_mode", mode)
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
        self._write_scope_display("sort_order", order)
        self._reload_current_page()
        self._toast(self.t("toast.sorted", order=self.t(f"sort_order.{order}")), timeout=2)

    def _sorted_roms(self, roms, order=None):
        """Apply the chosen order, reading the disk only when it is needed.

        ``order`` defaults to the current scope's; a page rendered for another
        scope (Favorites refreshed while a console is on screen) passes its own.

        Stat-ing a whole library costs real time on a slow disk, so the lookups
        are wired up only for the orders that actually use them.
        """
        order = order or self._sort_order
        needs_stat = order in SORT_ORDERS_NEEDING_FILE_STAT
        needs_history = order in SORT_ORDERS_NEEDING_HISTORY
        return sort_roms(
            roms,
            order,
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

        select_all_button = Gtk.Button(label=self.t("selection.select_all"))
        select_all_button.connect("clicked", lambda _b: self._select_all_visible())

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
        for child in (self.selection_label, select_all_button, sync_button, delete_button, clear_button):
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
        self.pages.update_master_check()

    def _clear_selection(self):
        grid = self.pages.grid_for(self.current_console)
        if grid:
            grid.clear_selection()
        self._on_selection_changed([])
        self.leave_selection_mode(clear=False)

    def _select_all_visible(self):
        """Ctrl+A / the master checkbox: every ROM the search still shows."""
        grid = self.pages.grid_for(self.current_console)
        if grid:
            grid.select_all()

    # -- gamepad selection mode (issue #78) ----------------------------------

    @property
    def selection_mode_active(self):
        return getattr(self, "_selection_mode", False)

    def enter_selection_mode(self):
        if self.selection_mode_active:
            return
        self._selection_mode = True
        self.navigation.refresh_hints()
        self._toast(self.t("toast.selection_mode.entered"), timeout=3)

    def leave_selection_mode(self, clear=True):
        if not self.selection_mode_active:
            return
        self._selection_mode = False
        if clear:
            self._clear_selection()
        self.navigation.refresh_hints()

    def focus_selection_actions(self):
        """Gamepad Ⓧ in selection mode: put focus on the selection bar."""
        if self._selected_roms and self.selection_bar.get_reveal_child():
            self.selection_bar.get_child().child_focus(Gtk.DirectionType.TAB_FORWARD)

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
        menu.append(self.t("menu.welcome"), "win.welcome")
        menu.append(self.t("menu.about"), "win.about")
        button = Gtk.MenuButton()
        button.set_icon_name("open-menu-symbolic")
        button.set_menu_model(menu)
        self._translatable(lambda: button.set_tooltip_text(self.t("menu.primary")))
        button.set_primary(True)
        # Held for the gamepad's Select button, which opens this menu from
        # wherever the focus happens to be.
        self.primary_menu_button = button
        return button

    def _install_actions(self):
        # Plain-key accels (Delete, F2, F5) are safe next to the search entry:
        # a focused entry consumes the key press before window accels run.
        for name, handler, accels in (
            ("welcome", lambda *_: self._open_welcome(), None),
            ("preferences", lambda *_: self._open_preferences(), ["<Ctrl>comma"]),
            ("shortcuts", lambda *_: self._show_shortcuts(), ["<Ctrl>question"]),
            ("about", lambda *_: self._show_about(), None),
            ("search", lambda *_: self._toggle_search(), ["<Ctrl>f"]),
            ("rescan", lambda *_: self._on_refresh_clicked(None), ["F5", "<Ctrl>r"]),
            ("import", lambda *_: self.imports.open_picker(), ["<Ctrl>o"]),
            ("sync-covers", lambda *_: self._sync_covers_for_current_scope(), ["<Ctrl><Shift>s"]),
            ("delete-rom", lambda *_: self._delete_selected_or_focused(), ["Delete"]),
            ("select-all", lambda *_: self._select_all_visible(), ["<Ctrl>a"]),
            ("select-none", lambda *_: self._clear_selection(), ["<Ctrl><Shift>a"]),
            ("rename-rom", lambda *_: self._rename_focused_rom(), ["F2"]),
            ("toggle-favorite", lambda *_: self._favorite_focused_rom(), ["<Ctrl>d"]),
            ("focus-pane", lambda *_: self.navigation.toggle_pane_focus(), ["F6"]),
            # Both the main-row and keypad forms: on many layouts Ctrl+"+"
            # arrives as Ctrl+= (no shift), which is why that one is listed too.
            ("zoom-in", lambda *_: self._step_zoom(1), ["<Ctrl>plus", "<Ctrl>equal", "<Ctrl>KP_Add"]),
            ("zoom-out", lambda *_: self._step_zoom(-1), ["<Ctrl>minus", "<Ctrl>KP_Subtract"]),
            ("zoom-reset", lambda *_: self._apply_zoom(DEFAULT_ZOOM), ["<Ctrl>0"]),
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

        # Whether the page in view follows the global layout or has its own.
        follow_global_action = Gio.SimpleAction.new_stateful(
            "layout-follow-global",
            None,
            GLib.Variant("b", not self.config_manager.has_scope_override(self._current_scope())),
        )
        follow_global_action.connect("activate", self._on_layout_follow_global_action)
        self.add_action(follow_global_action)

        # "Show only ROMs without artwork" (issue #127): a view filter, so it
        # sits with the other view controls rather than in Preferences, and
        # it is deliberately not persisted -- it is a way to work through the
        # gaps, not a mode to leave the library in.
        missing_artwork_action = Gio.SimpleAction.new_stateful(
            "filter-missing-artwork", None, GLib.Variant("b", False)
        )
        missing_artwork_action.connect("activate", self._on_missing_artwork_action)
        self.add_action(missing_artwork_action)

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
            item.toggle_favorite()

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

    def _on_close_stop_game(self, *_args):
        """Closing the library takes the running game with it.

        A game OpenEmux started must never outlive the app: the wrapper
        window is a window of this app and would keep it alive with no
        library behind it, and a standalone RetroArch left running is a
        process only a process manager can reach. The wait is bounded by the
        stop escalation and normally over in milliseconds -- RetroArch
        answers the QUIT command -- but it is deliberately synchronous, since
        after this the app is on its way out and no worker would survive it.
        """
        self.game.close_now()
        # Asked again on purpose rather than as an else: a wrapper the user
        # closed a moment ago has already done its (non-blocking) cleanup, so
        # a game still shrugging off that stop would ride out on a worker
        # thread this exit is about to take down with it.
        if self.runtime_manager.is_running():
            self.runtime_manager.stop_active(block=True)
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

    def _open_preferences(self, page=None, console=None):
        self._preferences_dialog = OpenEmuxPreferences(self)
        if page:
            self._preferences_dialog.show_page(page)
        if console is not None:
            # Reached from a console's own context menu: the Input page would
            # otherwise open on whatever the library is showing, which is not
            # necessarily the console that was right-clicked.
            self._preferences_dialog.select_input_console(console)
        self._preferences_dialog.present(self)

    def _open_welcome(self):
        WelcomeAssistant(self).present(self)

    def maybe_show_welcome(self):
        """Show the onboarding tour on startup unless the user opted out.

        Deferred to the idle loop so the main window paints first and the
        assistant lands on top of a ready-to-use library.
        """
        if self.config_manager.get_show_welcome_on_startup():
            GLib.idle_add(self._open_welcome)

    def maybe_report_recovered_state(self):
        """Tell the user when a state file was set aside on the way in.

        The stores keep an unreadable file as ``<name>.broken-<timestamp>``
        and fall back to defaults (issue #209). Without this the app would
        still just look like it had forgotten everything -- which is exactly
        the experience the quarantine exists to end.
        """
        recovered = quarantined_files()
        if not recovered:
            return
        reset_quarantine_log()
        if len(recovered) == 1:
            text = self.t(
                "toast.state_recovered.one", name=Path(recovered[0]["kept_as"]).name
            )
        else:
            text = self.t("toast.state_recovered.many", count=len(recovered))
        # Longer than a normal toast: it is the only notice the user gets,
        # and the welcome tour may be painting over the window right now.
        GLib.idle_add(self._toast, text, 10)

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
                ("<Ctrl>a", "shortcuts.select_all"),
                ("<Ctrl><Shift>a", "shortcuts.select_none"),
                ("<Shift>Up", "shortcuts.select_range"),
                ("<Ctrl>space", "shortcuts.select_toggle"),
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

    #: Share of the monitor the window opens at, and the size used when the
    #: monitor cannot be read (headless, or a display with no monitor yet).
    DEFAULT_SCREEN_SHARE = 0.8
    FALLBACK_WINDOW_SIZE = (1200, 800)

    @classmethod
    def _size_for_monitor(cls, geometry):
        """80% of a monitor, never larger than the monitor itself."""
        if geometry is None or geometry.width <= 0 or geometry.height <= 0:
            return cls.FALLBACK_WINDOW_SIZE
        return (
            min(geometry.width, int(geometry.width * cls.DEFAULT_SCREEN_SHARE)),
            min(geometry.height, int(geometry.height * cls.DEFAULT_SCREEN_SHARE)),
        )

    def _default_window_size(self):
        """Open at a share of the screen rather than a fixed box.

        The fixed 1200x800 was *taller* than a 720p monitor, so those users
        got a window the compositor had to clamp -- opening cut off before
        anyone touched it. GTK reports geometry in logical pixels, so a HiDPI
        screen reports its scaled size and needs no special case.
        """
        display = Gdk.Display.get_default()
        if display is None:
            return self.FALLBACK_WINDOW_SIZE
        monitors = display.get_monitors()
        if monitors is None or monitors.get_n_items() == 0:
            return self.FALLBACK_WINDOW_SIZE
        monitor = monitors.get_item(0)
        return self._size_for_monitor(monitor.get_geometry() if monitor else None)

    def _translatable(self, apply, owner=None):
        """Apply translated text now, and again on every language change.

        Registered next to the widget it belongs to; see
        :mod:`openemux.ui.retranslate` for why, and for what ``owner`` is for.
        """
        self._retranslate.add(apply, owner)

    def _apply_language_change(self, locale):
        self.config_manager.set_locale(locale)
        self.locale = locale
        language_name = LANGUAGE_META.get(locale, LANGUAGE_META["en"])["native_name"]
        visible = self.content_stack.get_visible_child_name()
        self._retranslate.apply_all()
        self._render_tip()
        # Every label in the stack and the sidebar has to be built again.
        self.refresh_library(preferred_view=visible, force=True)
        self._toast(self.t("toast.language.updated", language=language_name))

    def _update_window_title(self, console_id):
        if console_id == ALL_CONSOLES_ID:
            title = self.t("sidebar.all")
        elif console_id == FAVORITES_ID:
            title = self.t("sidebar.favorites")
        elif is_collection_scope(console_id):
            title = self.sidebar.label_for(console_id)
        elif console_id:
            title = f"{console_id} — {get_system_display_name(console_id)}"
        else:
            title = self.t("app.title")
        subtitle = ""
        grid = self.pages.grid_for(console_id)
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

        icon = console_icon(console_id)
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

    # ----- collections ----------------------------------------------------
    def _prompt_new_collection(self, on_created=None):
        """Ask for a name, create the collection, then call ``on_created(slug)``."""
        dialog = Adw.AlertDialog(
            heading=self.t("collections.new.heading"),
            body=self.t("collections.new.body"),
        )
        entry = Gtk.Entry()
        entry.set_text(self.t("collections.new.default"))
        dialog.set_extra_child(entry)
        dialog.add_response("cancel", self.t("dialog.cancel"))
        dialog.add_response("create", self.t("collections.new.confirm"))
        dialog.set_response_appearance("create", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("create")
        dialog.set_close_response("cancel")

        def _on_response(_dlg, response):
            if response != "create":
                return
            name = entry.get_text().strip()
            try:
                slug = self.collection_manager.create(name)
            except ValueError:
                self._toast(self.t("collections.toast.invalid"), timeout=4)
                return
            self.sidebar.rebuild(self.visible_consoles)
            self.sidebar.reselect_current()
            self.pages.ensure_collection_page(slug)
            self._toast(self.t("collections.toast.created", name=name))
            if on_created is not None:
                on_created(slug)

        dialog.connect("response", _on_response)
        dialog.present(self)
        GLib.idle_add(lambda: (dialog.set_focus(entry), entry.select_region(0, -1), False)[-1])

    def _prompt_rename_collection(self, slug):
        current = self.collection_manager.get_name(slug) or ""
        dialog = Adw.AlertDialog(
            heading=self.t("collections.rename.heading"),
            body=self.t("collections.rename.body"),
        )
        entry = Gtk.Entry()
        entry.set_text(current)
        dialog.set_extra_child(entry)
        dialog.add_response("cancel", self.t("dialog.cancel"))
        dialog.add_response("rename", self.t("dialog.rename.confirm"))
        dialog.set_response_appearance("rename", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("rename")
        dialog.set_close_response("cancel")

        def _on_response(_dlg, response):
            if response != "rename":
                return
            try:
                self.collection_manager.rename(slug, entry.get_text().strip())
            except ValueError:
                self._toast(self.t("collections.toast.invalid"), timeout=4)
                return
            self.sidebar.rebuild(self.visible_consoles)
            self.sidebar.reselect_current()
            if self.current_console == collection_scope(slug):
                self._update_window_title(self.current_console)

        dialog.connect("response", _on_response)
        dialog.present(self)
        GLib.idle_add(lambda: (dialog.set_focus(entry), entry.select_region(0, -1), False)[-1])

    def _confirm_delete_collection(self, slug):
        name = self.collection_manager.get_name(slug) or ""
        dialog = Adw.AlertDialog(
            heading=self.t("collections.delete.heading", name=name),
            body=self.t("collections.delete.body"),
        )
        dialog.add_response("cancel", self.t("dialog.cancel"))
        dialog.add_response("delete", self.t("collections.delete.confirm"))
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")

        def _on_response(_dlg, response):
            if response != "delete":
                return
            was_current = self.current_console == collection_scope(slug)
            self.collection_manager.delete(slug)
            scope = collection_scope(slug)
            # forget() drops the grid too. Popping the pages and the load
            # flags but not _grids left the deleted collection's grid
            # receiving artwork refreshes for a page nobody could reach
            # (issue #237).
            page = self.pages.forget(scope)
            if page is not None:
                self.content_stack.remove(page)
            self.sidebar.rebuild(self.visible_consoles)
            self._toast(self.t("collections.toast.deleted", name=name))
            if was_current:
                self.sidebar.select(FAVORITES_ID)

        dialog.connect("response", _on_response)
        dialog.present(self)

    def _target_roms_for(self, rom):
        """The roms an action applies to: the selection if it holds ``rom``."""
        selected = list(getattr(self, "_selected_roms", []) or [])
        paths = {r["path"] for r in selected}
        if rom["path"] in paths and len(selected) > 1:
            return selected
        return [rom]

    def toggle_rom_in_collection(self, rom, slug):
        """Add the target roms to a collection, or remove a lone one already in."""
        targets = self._target_roms_for(rom)
        if len(targets) == 1 and self.collection_manager.contains(slug, rom["path"]):
            self.collection_manager.remove(slug, [rom["path"]])
            self._toast(self.t("collections.toast.removed_one", name=rom["name"]))
        else:
            added = self.collection_manager.add(slug, [r["path"] for r in targets])
            name = self.collection_manager.get_name(slug) or ""
            self._toast(self.t("collections.toast.added", count=added, name=name))
        self._after_collection_changed(slug)

    def create_collection_and_add(self, rom):
        targets = self._target_roms_for(rom)
        self._prompt_new_collection(
            on_created=lambda slug: (
                self.collection_manager.add(slug, [r["path"] for r in targets]),
                self._after_collection_changed(slug),
            )
        )

    def remove_rom_from_current_collection(self, rom):
        if not is_collection_scope(self.current_console):
            return
        slug = collection_slug(self.current_console)
        targets = self._target_roms_for(rom)
        self.collection_manager.remove(slug, [r["path"] for r in targets])
        self._after_collection_changed(slug)

    def _after_collection_changed(self, slug):
        scope = collection_scope(slug)
        if self.pages.has(scope):
            self.pages.ensure_collection_loaded(slug)

    def _maybe_show_bootstrap_warning(self):
        state = self.config_manager.get_bootstrap_state()
        if state.get("status") != "failed":
            return
        failed_step = state.get("failed_step", "-")
        toast = Adw.Toast(title=self.t("toast.bootstrap.failed", step=failed_step))
        toast.set_timeout(6)
        self.toast_overlay.add_toast(toast)

    def refresh_library(self, preferred_view=None, force=False):
        """Rediscover the library and rebuild whatever the change affects.

        A rescan or an import usually finds the same consoles it found before,
        and tearing the whole stack and sidebar down for that meant every page
        was thrown away and rebuilt -- twice at startup, since the launch
        builds the library and the startup scan finishes seconds later and
        does it again (#230). When the visible set has not moved, the pages
        stay and only their contents are invalidated; ``force`` is for the
        language change, where every label has to be built again.
        """
        previous_visible = self.content_stack.get_visible_child_name() if hasattr(self, "content_stack") else None
        # Discovery fills _initial_roms, so the reset has to come first or the
        # snapshots it just took are thrown away and every page re-reads its
        # playlist on the first visit.
        self._initial_roms = {}
        discovered = self._discover_visible_consoles()
        if (
            not force
            and self.pages.any_page()
            and discovered == getattr(self, "visible_consoles", None)
        ):
            self.visible_consoles = discovered
            # The pages are still the right pages; their contents may not be.
            self.pages.invalidate_contents()
            self.sidebar.sync_footer()
            target = preferred_view or previous_visible or self.current_console
            if self.pages.has(target):
                self.current_console = target
                self.pages.ensure_loaded(target)
                self.content_stack.set_visible_child_name(target)
                self._update_window_title(target)
            return

        while child := self.content_stack.get_first_child():
            self.content_stack.remove(child)

        self.pages.reset()

        self.visible_consoles = discovered
        self.sidebar.sync_footer()
        self.sidebar.rebuild(self.visible_consoles)

        if self.visible_consoles:
            self.pages.add(ALL_CONSOLES_ID, self.t("sidebar.all"))

        self.pages.add(FAVORITES_ID, self.t("sidebar.favorites"))

        for collection in self.collection_manager.list_collections():
            self.pages.ensure_collection_page(collection["slug"])

        if self.visible_consoles:
            for console in self.visible_consoles:
                page = self.pages.add(console, console)
                placeholder = Gtk.Label(label=self.t("empty.select_console", console=console))
                placeholder.add_css_class("dim-label")
                placeholder.set_margin_top(32)
                page.scroll.set_child(placeholder)

        if not self.visible_consoles:
            # Drag-and-drop is the fastest way in and used to go unmentioned
            # here: the page only offered "choose a folder", so the one thing
            # someone with a folder of ROMs open would try was undocumented.
            empty = Adw.StatusPage(
                icon_name="folder-download-symbolic",
                title=self.t("library.empty.title"),
                description=self.t("library.empty.body"),
            )
            actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            actions.set_halign(Gtk.Align.CENTER)
            import_btn = Gtk.Button(label=self.t("library.empty.action"))
            import_btn.add_css_class("suggested-action")
            import_btn.add_css_class("pill")
            import_btn.connect("clicked", lambda _b: self.imports.open_picker())
            actions.append(import_btn)
            choose = Gtk.Button(label=self.t("library.empty.choose"))
            choose.add_css_class("pill")
            choose.connect("clicked", lambda _b: self._choose_roms_path())
            actions.append(choose)
            empty.set_child(actions)
            self.content_stack.add_titled(empty, LIBRARY_EMPTY_ID, "Library")

        target_view = preferred_view
        if target_view is None:
            target_view = previous_visible or self.current_console

        desired = landing_view(
            self.visible_consoles,
            target_view,
            [c["slug"] for c in self.collection_manager.list_collections()],
        )
        if desired != LIBRARY_EMPTY_ID:
            if not self.sidebar.select(desired):
                first_row = self.console_list.get_row_at_index(0)
                if first_row:
                    self.console_list.select_row(first_row)
            return

        self.console_list.unselect_all()
        self.current_console = None
        self._set_search_enabled(False)
        self.content_stack.set_visible_child_name(LIBRARY_EMPTY_ID)
        self._update_window_title(None)

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
        # The layout controls follow the page you are on, so re-sync them to
        # this scope before its page is (re)rendered.
        self._refresh_scope_settings()
        self._set_search_enabled(True)
        if self.current_console == ALL_CONSOLES_ID:
            self.pages.ensure_all_loaded()
        elif self.current_console == FAVORITES_ID:
            self.pages.ensure_favorites_loaded()
        elif is_collection_scope(self.current_console):
            self.pages.ensure_collection_loaded(collection_slug(self.current_console))
        else:
            self.pages.ensure_loaded(self.current_console)
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
        # Gtk.FileDialog, not the deprecated Gtk.FileChooserDialog: the
        # in-process widget never goes through the XDG portal, so under Flatpak
        # it could only ever show what the sandbox already had -- while the
        # import dialog beside it, already ported, could reach removable media
        # and /mnt. Two pickers, two behaviours (issue #235).
        dialog = Gtk.FileDialog()
        dialog.set_title(self.t("settings.path.dialog_title"))
        dialog.set_accept_label(self.t("settings.path.select_button"))
        dialog.set_modal(True)
        current = self.config_manager.get_roms_path()
        if current.exists():
            dialog.set_initial_folder(Gio.File.new_for_path(str(current)))
        dialog.select_folder(self, None, self._on_roms_path_chosen)

    def _on_roms_path_chosen(self, dialog, result):
        try:
            selected_file = dialog.select_folder_finish(result)
        except GLib.Error:
            # Dismissed by the user; nothing to report.
            return
        if selected_file is None:
            return

        selected_path = selected_file.get_path()
        if not selected_path:
            toast = Adw.Toast(title=self.t("toast.path_invalid"))
            toast.set_timeout(3)
            self.toast_overlay.add_toast(toast)
            return

        self.config_manager.set_roms_path(selected_path)
        # Returns what it could not create rather than raising into the GTK
        # main loop, which is where an unwritable folder used to take this
        # handler down mid-way (issue #234).
        unwritable = self.config_manager.ensure_rom_directories()
        self.roms_path = self.config_manager.get_roms_path()
        self.scanner = RomScanner(self.roms_path)
        self.playlist_manager = PlaylistManager(self.config_manager, self.scanner)
        # Rebind the collection loader to the fresh playlist manager.
        self.collection_manager = CollectionManager(
            self.config_manager.get_playlists_dir() / "collections",
            entries_loader=self.playlist_manager.entries_for_paths,
        )
        self._rescan_all_consoles(show_toast=False)

        if unwritable:
            self._toast(
                self.t("toast.path_not_writable", path=str(self.roms_path)), timeout=6
            )
        else:
            toast = Adw.Toast(title=self.t("toast.path_updated", path=str(self.roms_path)))
            toast.set_timeout(4)
            self.toast_overlay.add_toast(toast)

    def _open_roms_folder(self):
        self._open_path_in_file_manager(self.config_manager.get_roms_path())

    def _open_console_bios_folder(self, console):
        # Creating it is _open_path_in_file_manager's business, where the
        # failure has a toast to land in (issue #234).
        self._open_path_in_file_manager(
            get_console_bios_dir(self.config_manager, console)
        )

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

        if IS_WINDOWS:
            # Explorer's own equivalent of ShowItems. There is no session bus
            # here, so the D-Bus call below could only ever fail.
            #
            # The comma is part of the switch -- `/select,<path>` -- and must be
            # passed as its own argv element or Explorer opens the parent
            # instead of selecting. Explorer also exits non-zero on success, so
            # the return code is deliberately not checked.
            try:
                subprocess.Popen(["explorer", "/select,", str(path)])
                logger.info("reveal in explorer: path=%s", path)
                return
            except OSError as exc:
                logger.info("explorer /select failed (%s); opening parent folder", exc)
            self._open_path_in_file_manager(path.parent)
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
        if IS_WINDOWS:
            # Neither branch below works here: GIO's Windows backend answers
            # "No application is registered as handling this file" for a
            # file:// directory URI, and there is no xdg-open -- so without
            # this the button only ever produced an error toast.
            try:
                # mkdir inside the try for the same reason as the branch
                # below (issue #234): on an unmounted or read-only path it
                # raises, and outside the try that raise escapes past the
                # error toast, leaving the button doing nothing with no
                # explanation.
                path.mkdir(parents=True, exist_ok=True)
                os.startfile(path)  # noqa: S606 - a directory the user chose
                return
            except OSError as exc:
                self._toast_open_failed(path, exc)
                return
        try:
            # Inside the try on purpose: this used to sit above it, so "Open
            # folder" on an unmounted or read-only path raised past every
            # fallback and past the error toast at the bottom -- the button
            # simply did nothing, with no explanation (issue #234).
            path.mkdir(parents=True, exist_ok=True)
            Gio.AppInfo.launch_default_for_uri(path.as_uri(), None)
            return
        except Exception:
            pass
        try:
            subprocess.Popen(["xdg-open", str(path)])
            return
        except Exception as exc:
            self._toast_open_failed(path, exc)

    def _toast_open_failed(self, path, exc):
        toast = Adw.Toast(title=self.t("bios.open_path_failed", path=str(path), error=str(exc)))
        toast.set_timeout(4)
        self.toast_overlay.add_toast(toast)

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

    @property
    def current_view_mode(self):
        """The active library view mode (context menus gate entries on it)."""
        return self._view_mode

    def _cartridge_color_for_rom(self, rom):
        """The shell color a card should draw with: per-ROM, then per-console."""
        return self.config_manager.get_cartridge_color_for_rom(rom["path"], rom["console"])

    def set_rom_cartridge_color(self, rom, color_id):
        """Persist a per-ROM shell color (``color_id=None`` clears it).

        Only the picked card is re-composed; the rest of the shelf is
        untouched. The card may live on more than one loaded page (console
        page plus Favorites), so every grid gets a chance to refresh it.
        """
        self.config_manager.set_rom_cartridge_color(rom["path"], rom["console"], color_id)
        for grid in self.pages.grids():
            grid.refresh_rom_frame(rom)

    def sync_rom_artwork(self, rom, art_kind):
        """Fetch one ROM's artwork of ``art_kind`` right away, in the background.

        The context menu's sync entries are a quick single-ROM action: no
        window, no picking -- the same provider chain the library-wide sync
        uses, aimed at one game. Art already on disk is replaced, because the
        reason to sync one game by hand is usually that what it has is wrong.
        """
        if self._cover_sync_running:
            self._toast(self.t("toast.sync_running"), timeout=3)
            return
        passes = [(art_kind, {rom["console"]: [rom]})]
        logger.info(
            "rom artwork sync: rom=%s console=%s kind=%s", rom["name"], rom["console"], art_kind
        )
        self._start_artwork_sync(
            passes,
            replace_existing=True,
            on_finished=lambda: self.refresh_rom_artwork(rom),
        )

    def open_artwork_manager(self, rom, art_dir=COVER_ART):
        """The per-ROM artwork manager (issue #77), on the tab for ``art_dir``."""
        from openemux.ui.artwork_manager import ArtworkManagerWindow

        window = ArtworkManagerWindow(
            self,
            rom,
            art_dir=art_dir,
            label_supported=cartridge_render.has_frame(rom["console"]),
        )
        window.present()

    def refresh_rom_artwork(self, rom, fade=False):
        """Re-fetch one ROM's card artwork after the manager saved a file."""
        for grid in self.pages.grids():
            grid.refresh_rom_artwork(rom, fade=fade)

    def launch_rom_at_state(self, rom, slot):
        """Launch ``rom`` and load the state parked on ``slot`` (issue #180)."""
        self.game.launch_at_state(rom, slot)

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
            self.pages.ensure_favorites_loaded()
        elif self.pages.grid_for(FAVORITES_ID) is not None:
            self.pages.ensure_favorites_loaded()
        return is_now_favorite

    def _choose_cover_for_rom(self, rom, on_done=None, kind=COVER_ART):
        title_key = "dialog.label.choose.title" if kind == LABEL_ART else "dialog.cover.choose.title"
        dialog = Gtk.FileDialog()
        dialog.set_title(self.t(title_key))
        dialog.set_accept_label(self.t("dialog.start"))
        dialog.set_modal(True)
        filters, default_filter = image_filters()
        dialog.set_filters(filters)
        dialog.set_default_filter(default_filter)

        def _on_chosen(dlg, result):
            try:
                selected = dlg.open_finish(result)
            except GLib.Error:
                # Dismissed by the user; nothing to report.
                return
            if selected is None:
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

        dialog.open(self, None, _on_chosen)

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
        entry.set_text(display_text(rom["name"]))
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
            renamed = rename_rom(
                Path(self.roms_path),
                rom,
                new_name,
                states_dir=self.config_manager.get_console_states_dir(rom["console"]),
            )
        except RomActionError as exc:
            self._toast(self.t("toast.rom.rename_failed", error=str(exc)), timeout=6)
            return
        self.playlist_manager.repath_rom(rom["console"], rom["path"], renamed["path"])
        self.play_history.repath(rom["path"], renamed["path"])
        self.config_manager.repath_rom_shader(rom["path"], renamed["path"])
        self.config_manager.repath_rom_core(rom["path"], renamed["path"])
        self.config_manager.repath_rom_cartridge_color(rom["path"], renamed["path"])
        self.collection_manager.repath_rom(rom["path"], renamed["path"])
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
            self.config_manager.forget_rom_cartridge_color(rom["path"])
            self.collection_manager.forget_rom(rom["path"])
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
            self.pages.ensure_all_loaded()
        elif console == FAVORITES_ID:
            self.pages.ensure_favorites_loaded()
        elif is_collection_scope(console):
            self.pages.ensure_collection_loaded(collection_slug(console))
        else:
            self.pages.ensure_loaded(console)

    def _scan_current_console(self):
        self._show_scan_roms_dialog()

    def _rescan_single_console(self, console, show_toast=False):
        if not console or console == ALL_CONSOLES_ID:
            return self._rescan_all_consoles(show_toast=show_toast)
        if self._scan_running:
            self._queue_rescan(console=console, show_toast=show_toast)
            if show_toast:
                toast = Adw.Toast(title=self.t("toast.scan_running"))
                toast.set_timeout(3)
                self.toast_overlay.add_toast(toast)
            return None

        origin_view = self.content_stack.get_visible_child_name()
        self._scan_running = True
        task_id = self.tasks.begin("scan", self.t("status.scan.starting"), total=1)

        def _worker():
            summary = {"console": console, "roms": 0}
            try:
                summary["roms"] = len(
                    self.playlist_manager.scan_and_rebuild_playlist(console)
                )
            except Exception as exc:
                # _on_rescan_*_done_ui is what clears _scan_running. A worker
                # that dies without reaching it leaves the flag set for the
                # rest of the session, and every later scan is refused with
                # "a scan is already running" (issue #214).
                logger.exception("rescan crashed: console=%s", console)
                summary["error"] = str(exc)
            GLib.idle_add(self._on_rescan_single_done_ui, task_id, summary, show_toast, origin_view)

        Thread(target=_worker, daemon=True).start()
        return {"started": True}

    def _rescan_all_consoles(self, show_toast=False):
        if self._scan_running:
            self._queue_rescan(console=None, show_toast=show_toast)
            if show_toast:
                toast = Adw.Toast(title=self.t("toast.scan_running"))
                toast.set_timeout(3)
                self.toast_overlay.add_toast(toast)
            return None
        origin_view = self.content_stack.get_visible_child_name()
        self._scan_running = True
        task_id = self.tasks.begin("scan", self.t("status.scan.starting"))

        def _on_progress(evt):
            GLib.idle_add(
                self.tasks.update,
                task_id,
                evt.get("current", 0),
                evt.get("total", 0),
                self.t("status.scan.progress", current=evt.get("current", 0), total=evt.get("total", 0)),
            )

        def _worker():
            try:
                summary = self.playlist_manager.scan_and_rebuild_all_playlists(
                    on_progress=_on_progress
                )
            except Exception as exc:
                logger.exception("rescan crashed")
                summary = {
                    "consoles": {},
                    "total_consoles": 0,
                    "total_roms": 0,
                    "failed": {},
                    "error": str(exc),
                }
            GLib.idle_add(self._on_rescan_all_done_ui, task_id, summary, show_toast, origin_view)

        Thread(target=_worker, daemon=True).start()
        return {"started": True}

    def _queue_rescan(self, console, show_toast):
        """Remember a rescan that could not start, to run when this one ends.

        Two callers hand in ``show_toast=False`` and depend on the rescan
        actually happening: the one after an import ("new files on disk:
        rebuild the playlists so they show up") and the one after the ROM
        folder changes. Imports are gated only by ``ImportFlow.running``, so one
        can finish while the always-on startup scan is still in flight -- and
        the request was dropped with no retry and no message. The user saw
        "imported" and then no new games, which reads as a failed import
        (issue #225).
        """
        pending = self._rescan_pending
        if pending is not None and pending["console"] is None:
            # A whole-library rescan already queued covers any single console.
            pending["show_toast"] = pending["show_toast"] or show_toast
            return
        if pending is not None and console is not None and pending["console"] != console:
            # Two different consoles asked: only the whole library covers both.
            console = None
        self._rescan_pending = {
            "console": console,
            "show_toast": bool(show_toast or (pending or {}).get("show_toast")),
        }
        logger.info("rescan queued: console=%s", console or "all")

    def _run_pending_rescan(self):
        """Start the rescan that was asked for while one was already running."""
        pending = self._rescan_pending
        self._rescan_pending = None
        if pending is None:
            return False
        logger.info("rescan queued run: console=%s", pending["console"] or "all")
        if pending["console"] is None:
            self._rescan_all_consoles(show_toast=pending["show_toast"])
        else:
            self._rescan_single_console(pending["console"], show_toast=pending["show_toast"])
        return False

    def _on_rescan_single_done_ui(self, task_id, summary, show_toast, origin_view):
        self._scan_running = False
        # After this handler, so its own toast lands first and the queued run
        # starts against a library that has already been refreshed.
        GLib.idle_add(self._run_pending_rescan)
        self.tasks.update(task_id, current=1, total=1)
        self.tasks.finish(task_id)
        self.refresh_library(preferred_view=origin_view or summary.get("console"))
        self._on_search_changed(self.search_entry)
        if summary.get("error"):
            self._toast(self.t("toast.scan_failed", error=summary["error"]), timeout=6)
            return False
        if show_toast:
            toast = Adw.Toast(title=self.t("toast.playlist_rebuilt", console=summary.get("console")))
            toast.set_timeout(4)
            self.toast_overlay.add_toast(toast)
        return False

    def _on_rescan_all_done_ui(self, task_id, summary, show_toast, origin_view):
        self._scan_running = False
        GLib.idle_add(self._run_pending_rescan)
        self.tasks.finish(task_id)
        self.refresh_library(preferred_view=origin_view)
        self._on_search_changed(self.search_entry)
        if summary.get("error"):
            self._toast(self.t("toast.scan_failed", error=summary["error"]), timeout=6)
            return False
        failed = summary.get("failed") or {}
        if failed:
            # The rest of the library did scan; say which consoles did not
            # instead of reporting a clean run (issue #214).
            self._toast(
                self.t("toast.scan_partial", consoles=", ".join(sorted(failed))),
                timeout=6,
            )
            return False
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

        # Adw.AlertDialog with an extra child, the same shape the import flow's
        # console prompt uses -- Gtk.Dialog and get_content_area() are both
        # deprecated, and the hand-built content area was reimplementing the
        # margins Adwaita already applies (issue #235).
        dialog = self._scope_dialog("dialog.sync.title", "dialog.sync.scope", combo)

        def _on_response(_dlg, response):
            if response != "start":
                return
            selected = self._get_console_dropdown_active_id(combo) or self.current_console or self.visible_consoles[0]
            if selected == ALL_CONSOLES_ID:
                self._start_cover_sync(scope="all", selected_console=None)
            else:
                self._start_cover_sync(scope="console", selected_console=selected)

        dialog.connect("response", _on_response)
        dialog.present(self)

    def _show_scan_roms_dialog(self):
        combo = self._build_console_dropdown(
            SYSTEM_IDS,
            default_id=None,
            include_all=True,
        )

        default_scope = self.current_console if self.current_console in SYSTEM_IDS else ALL_CONSOLES_ID
        self._set_console_dropdown_active_id(combo, default_scope)

        dialog = self._scope_dialog("dialog.scan.title", "dialog.scan.scope", combo)

        def _on_response(_dlg, response):
            if response != "start":
                return
            selected = self._get_console_dropdown_active_id(combo) or ALL_CONSOLES_ID
            if selected == ALL_CONSOLES_ID:
                self._rescan_all_consoles(show_toast=True)
            else:
                self._rescan_single_console(selected, show_toast=True)

        dialog.connect("response", _on_response)
        dialog.present(self)

    def _scope_dialog(self, heading_key, body_key, child):
        """An ``Adw.AlertDialog`` asking for a console, with ``child`` inside.

        The scan and sync prompts differ only in their two strings, so they
        share the assembly rather than each hand-building a content area.
        """
        dialog = Adw.AlertDialog(
            heading=self.t(heading_key),
            body=self.t(body_key),
        )
        dialog.set_extra_child(child)
        dialog.add_response("cancel", self.t("dialog.cancel"))
        dialog.add_response("start", self.t("dialog.start"))
        dialog.set_response_appearance("start", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("start")
        dialog.set_close_response("cancel")
        return dialog

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

        # Every sync is multi-kind now (issue #76): box art everywhere, labels
        # where a frame exists -- each pass skips per kind, and passes no
        # enabled provider serves are dropped inside the sync itself.
        passes = build_artwork_passes(library, cartridge_render.consoles_with_frames())
        if not passes:
            self._toast(self.t("toast.sync_no_consoles"))
            return
        self._start_artwork_sync(passes)

    def _start_post_import_artwork_sync(self, imported_paths):
        """Fetch artwork for the ROMs an import just added.

        Box art for every console involved, plus cartridge labels for the ones
        that have a frame to composite a label into -- a label scraped for a
        console with no frame has nothing to sit in and would be served as box
        art on the card instead. Only the imported ROMs are covered, and the
        artwork type configured in Preferences is left alone: both kinds are
        wanted here regardless of which one the user picked for manual syncs.
        """
        if not imported_paths:
            return

        library = {}
        for entry in self.playlist_manager.entries_for_paths(imported_paths):
            library.setdefault(entry["console"], []).append(entry)
        passes = build_artwork_passes(library, cartridge_render.consoles_with_frames())
        if not passes:
            return

        if self._cover_sync_running:
            # A sync the user started explicitly is already in flight. Don't
            # fight it, and don't nag with "sync already running" on a path the
            # user did not ask for -- the next manual sync picks these up.
            logger.info("post-import artwork sync skipped: a sync is already running")
            return

        logger.info(
            "post-import artwork sync: passes=%s",
            [(kind, sorted(lib)) for kind, lib in passes],
        )
        self._start_artwork_sync(passes)

    def _start_artwork_sync(self, passes, replace_existing=False, on_finished=None):
        """Run a multi-kind artwork sync as a single cancellable task.

        ``on_finished`` runs on the UI thread once the sync is done, for the
        callers whose view the generic reload does not cover (a single ROM
        synced while a collection is on screen).
        """
        self._cover_sync_running = True
        cancel_event = Event()
        self._cover_sync_cancel = cancel_event
        task_id = self.tasks.begin(
            "covers",
            self.t("status.covers.starting"),
            on_cancel=cancel_event.set,
        )
        toast = Adw.Toast(title=self.t("toast.sync_started"))
        toast.set_timeout(3)
        self.toast_overlay.add_toast(toast)

        def _on_progress(evt):
            # One task spans both kinds, so the label follows what is in flight.
            label = (
                "status.labels.progress"
                if evt.get("art_kind") == COVER_ART_TYPE_CARTRIDGE_LABEL
                else "status.covers.progress"
            )
            GLib.idle_add(
                self.tasks.update,
                task_id,
                evt.get("processed", 0),
                evt.get("total", 0),
                self.t(label),
            )
            # Batched incremental reveal (issue #187): box art that just
            # landed shows up while the run is still going. Labels wait for
            # the final reload -- a label alone re-composites the cartridge
            # anyway when the grid reloads.
            if (
                evt.get("result") == "downloaded"
                and evt.get("rom_path")
                and evt.get("art_kind") != COVER_ART_TYPE_CARTRIDGE_LABEL
            ):
                GLib.idle_add(
                    self._queue_cover_reveal,
                    {
                        "console": evt.get("console"),
                        "name": evt.get("rom_name"),
                        "path": evt.get("rom_path"),
                    },
                )

        def _on_done(summary):
            GLib.idle_add(self._on_cover_sync_done_ui, task_id, summary, on_finished)

        sync_artwork_async(
            passes=passes,
            covers_dir=self.roms_path,
            on_done=_on_done,
            sync_settings=self.config_manager.get_cover_sync_settings(),
            on_progress=_on_progress,
            should_cancel=cancel_event.is_set,
            replace_existing=replace_existing,
        )

    # -- incremental cover reveal (issue #187) ------------------------------
    #: Flush the pending reveals after this many downloads...
    COVER_REVEAL_BATCH = 8
    #: ...or after this long, whichever comes first: visible, intentional
    #: steps instead of per-file flicker.
    COVER_REVEAL_FLUSH_MS = 2500

    def _queue_cover_reveal(self, rom):
        """Collect one downloaded cover for the next batched reveal (UI thread)."""
        pending = self._reveal_pending
        console_changed = bool(pending) and pending[-1]["console"] != rom["console"]
        if console_changed:
            # The sync moved on: everything gathered for the previous console
            # is complete, so reveal it now rather than on the next timeout.
            self._flush_cover_reveal()
        self._reveal_pending.append(rom)
        if len(self._reveal_pending) >= self.COVER_REVEAL_BATCH:
            self._flush_cover_reveal()
        elif self._reveal_timer is None:
            self._reveal_timer = GLib.timeout_add(
                self.COVER_REVEAL_FLUSH_MS, self._flush_cover_reveal_from_timer
            )
        return False

    def _flush_cover_reveal_from_timer(self):
        self._reveal_timer = None
        self._flush_cover_reveal()
        return False

    def _flush_cover_reveal(self):
        if self._reveal_timer is not None:
            GLib.source_remove(self._reveal_timer)
            self._reveal_timer = None
        pending, self._reveal_pending = self._reveal_pending, []
        for rom in pending:
            # Only the scope on screen updates mid-run: targeted card
            # refreshes, never a full grid reload. Everything else waits for
            # the end-of-run reload, which stays as the consistency backstop.
            if self.current_console in (ALL_CONSOLES_ID, FAVORITES_ID) or (
                self.current_console == rom["console"]
            ):
                self.refresh_rom_artwork(rom, fade=True)

    def _on_cover_sync_done_ui(self, task_id, summary, on_finished=None):
        self._cover_sync_running = False
        self._cover_sync_cancel = None
        # Whatever is still queued reveals before the final reload takes
        # over; a cancelled run's grid then matches exactly what is on disk.
        self._flush_cover_reveal()
        self.tasks.finish(task_id)
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
            self.pages.ensure_all_loaded()
        elif self.current_console == FAVORITES_ID:
            self.pages.ensure_favorites_loaded()
        elif self.pages.grid_for(self.current_console) is not None:
            self.pages.ensure_loaded(self.current_console)
        if on_finished:
            on_finished()
        return False

    def _on_refresh_clicked(self, _button):
        selected_console = self.sidebar.selected_id() or self.current_console
        if selected_console == ALL_CONSOLES_ID:
            self._rescan_all_consoles(show_toast=False)
            return
        if selected_console == FAVORITES_ID:
            self.pages.ensure_favorites_loaded()
            return
        if selected_console in SYSTEM_IDS:
            self._rescan_single_console(selected_console, show_toast=False)

    def on_launch_game(self, rom):
        self.game.launch(rom)

    def apply_input_changes_to_running_game(self):
        """Carry a saved remap into the running game (issue #129).

        Called from the preferences dialog, which is why it stays on the
        window: the session behind it is what does the work.
        """
        return self.game.apply_input_changes()

    def _on_search_changed(self, _entry):
        self.apply_library_filters()

    def apply_library_filters(self):
        """Decide card visibility from the search query and the artwork filter.

        One place owns it. Filtering used to be an ad-hoc loop inside the
        search handler; adding a second independent loop for the artwork
        filter would let the two fight over the same visibility flag (#127).

        Public because the grid calls back into it when a card's artwork
        state settles, which happens after the filter first ran.
        """
        visible = self.content_stack.get_visible_child_name()
        grid = self.pages.grid_for(visible) if visible else None
        if grid is None:
            return
        self._apply_filters_to(grid)

    def _apply_filters_to(self, grid):
        """The same decision, for a page that is not the visible one yet.

        A page whose rebuild was skipped keeps the filter it had when it was
        last on screen, so it has to be re-filtered before it is shown again
        (#230).

        The grid does the matching. It used to be a walk over the cards,
        hiding the ones that did not match -- which needs a widget per ROM,
        the thing virtualization takes away (#219). The window still decides
        *what* the filter is.
        """
        grid.set_filter(
            self.search_entry.get_text(),
            only_missing_artwork=self._filter_missing_artwork,
        )

    def _on_missing_artwork_action(self, action, _param):
        enabled = not action.get_state().get_boolean()
        action.set_state(GLib.Variant("b", enabled))
        self._filter_missing_artwork = enabled
        self.apply_library_filters()

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
        failed_step = result.get("failed_step")
        if failed_step:
            title = self.t("toast.bootstrap.failed", step=failed_step)
        else:
            # No step to name: the run died around the loop rather than inside
            # it (issue #215). "step: None" told the user nothing; the error
            # itself is the only thing here worth reading.
            title = self.t(
                "toast.bootstrap.crashed",
                error=result.get("error") or self.t("toast.bootstrap.unknown_error"),
            )
        toast = Adw.Toast(title=title)
        toast.set_timeout(6)
        self.toast_overlay.add_toast(toast)
