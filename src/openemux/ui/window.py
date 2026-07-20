import os
import subprocess
import logging
from threading import Event, Thread
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Gdk, GLib, Gio, GObject, Pango

from openemux.core.bios_manager import get_console_bios_dir
from openemux.core.cover_sync import sync_covers_async
from openemux.core.playlist_manager import PlaylistManager
from openemux.core.paths import get_project_root
from openemux.core.rom_importer import (
    IMPORTABLE_EXTENSIONS,
    collect_ambiguous_extensions,
    import_roms_async,
)
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
from openemux.ui.grid import RomGrid
from openemux.ui.context_menu import SEPARATOR, build_context_popover
from openemux.ui.preferences import OpenEmuxPreferences

logger = logging.getLogger(__name__)

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

        toolbar.add_bottom_bar(self._build_tip_bar())

        page = Adw.NavigationPage.new(toolbar, self.t("app.title"))
        page.set_tag("content")
        self.content_page = page
        return page

    def _build_tip_bar(self):
        """A quiet single-line hint bar at the bottom of the content pane.

        Deliberately not an Adw.Banner: banners are for things that need acting
        on, and the progress/update banners already own the top of the pane.
        """
        self.tip_label = Gtk.Label()
        self.tip_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.tip_label.set_single_line_mode(True)
        self.tip_label.set_hexpand(True)
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

        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        bar.add_css_class("tip-bar")
        bar.append(bulb)
        bar.append(self.tip_label)

        self.tip_bar = bar
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
        bar.set_visible(bool(enabled))
        if enabled:
            if not getattr(self, "_tip_timeout_id", 0):
                self._rotate_tip()
                self._tip_timeout_id = GLib.timeout_add_seconds(15, self._on_tip_timeout)
        else:
            self._stop_tip_rotation()

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
        return button

    def _install_actions(self):
        for name, handler, accels in (
            ("preferences", lambda *_: self._open_preferences(), ["<Ctrl>comma"]),
            ("shortcuts", lambda *_: self._show_shortcuts(), ["<Ctrl>question"]),
            ("about", lambda *_: self._show_about(), None),
            ("search", lambda *_: self._toggle_search(), ["<Ctrl>f"]),
        ):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", handler)
            self.add_action(action)
            app = self.get_application()
            if accels and app is not None:
                app.set_accels_for_action(f"win.{name}", accels)

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
        section = Gtk.ShortcutsSection(section_name="general", visible=True)
        group = Gtk.ShortcutsGroup(title=self.t("shortcuts.group.general"))
        for accel, key in (
            ("<Ctrl>f", "shortcuts.search"),
            ("<Ctrl>comma", "shortcuts.preferences"),
        ):
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

    def _apply_render_cartridge(self, active):
        self.config_manager.set_render_cartridge_overlay(active)
        if self.current_console == ALL_CONSOLES_ID:
            self._ensure_all_loaded()
        elif self.current_console == FAVORITES_ID:
            self._ensure_favorites_loaded()
        elif self.current_console in getattr(self, "_console_pages", {}):
            self._ensure_console_loaded(self.current_console)

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

        all_roms.sort(key=lambda rom: (rom.get("console", ""), rom.get("name", "").lower()))
        self._render_console_page(ALL_CONSOLES_ID, all_roms)
        self._console_loaded[ALL_CONSOLES_ID] = True

    def _render_console_page(self, console, roms):
        scroll = self._console_pages[console]
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
        )
        self._grids[console] = grid
        scroll.set_child(grid)
        if console == self.current_console:
            self._update_window_title(console)

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
