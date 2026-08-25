"""GNOME HIG-compliant preferences dialog for OpenEmux.

Replaces the former card-grid settings views (settings_grid.py + the
`_build_settings_views` monolith in window.py) with an ``Adw.PreferencesDialog``
built from boxed lists (``AdwPreferencesGroup`` + Adwaita rows), per the GNOME
Human Interface Guidelines.

The dialog owns all settings widgets and its own keyboard-capture controller for
input mapping; it delegates data operations to the owning window and its
``ConfigManager``.
"""
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, Gtk, Gdk, GLib

from openemux.core import game_window_support, save_backup
from openemux.core.embedded_credentials import has_embedded_dev_credentials
from openemux.core.gamepad_reader import GamepadCaptureReader, describe_token, list_gamepads
from openemux.core.library_view import SORT_ORDERS, VIEW_MODES
from openemux.core.input_actions import (
    ACTION_ORDER,
    GLOBAL_HOTKEY_ACTIONS,
    OPTIONAL_ACTIONS,
    get_actions_for_console,
    retroarch_key_token,
)
from openemux.core.input_profiles import (
    ANALOG_DPAD_MODES,
    TURBO_DUTY_RANGE,
    TURBO_MODES,
    TURBO_PERIOD_RANGE,
    DEVICE_IDS,
    EXTRA_PORT_DEVICE_IDS,
    controller_types_for,
    device_type_for,
    player_for_device,
)
from openemux.core.input_tuning import INPUT_TUNING
from openemux.core.shaders import normalize_shader_id
from openemux.core.theme import THEMES
from openemux.ui import theming
from openemux.core.systems import SYSTEM_IDS, get_system_display_name, resolve_system_id
from openemux.core.bios_manager import scan_all_bios_status
from openemux.i18n import LANGUAGE_META, SUPPORTED_LOCALES, normalize_locale


class OpenEmuxPreferences(Adw.PreferencesDialog):
    """Settings dialog. Instantiated fresh each time it is opened."""

    def __init__(self, window):
        super().__init__()
        self.win = window
        self.config = window.config_manager
        self.t = window.t

        self.set_title(self.t("prefs.title"))
        self.set_search_enabled(True)

        # Input-capture state (self-contained; mirrors the old window logic).
        self._input_buttons = {}
        self._input_rows = {}
        self._bindings_buffer = {}
        self._loaded_profile = None
        self._visible_actions = list(ACTION_ORDER)
        self._capture_sequence_actions = list(ACTION_ORDER)
        self._capture_active_action = None
        self._capture_sequence_mode = False
        self._capture_sequence_index = -1
        self._gamepad_reader = None

        self._key_controller = Gtk.EventControllerKey()
        self._key_controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        self._key_controller.connect("key-pressed", self._on_key_pressed)
        self.add_controller(self._key_controller)

        # Never leave a reader thread behind -- nor the window stuck in
        # exclusive-capture mode -- when the dialog goes away.
        self.connect("closed", lambda _d: self._on_closed())

        # Kept by name so a caller can open the dialog straight on one of
        # them -- the header's controller button lands on "input".
        self._pages = {
            "library": self._build_library_page(),
            "bios": self._build_bios_page(),
            "input": self._build_input_page(),
            "video": self._build_video_page(),
            "cores": self._build_cores_page(),
            "system": self._build_system_page(),
        }
        for page in self._pages.values():
            self.add(page)

    def show_page(self, name):
        """Open on a named page. Unknown names leave the dialog as it is."""
        page = self._pages.get(name)
        if page is not None:
            self.set_visible_page(page)

    def select_input_console(self, console_id):
        """Point the Input page at a console, whatever the library is showing.

        The combo defaults to the console on screen; opened from a console's
        context menu, the console the user right-clicked is the one they mean.
        Setting it emits notify::selected, which rebuilds the rows.
        """
        if console_id in self._console_ids:
            self._console_combo.set_selected(self._console_ids.index(console_id))

    # ----- shared helpers -------------------------------------------------
    def _on_closed(self):
        self._stop_gamepad_reader()
        self._set_exclusive_input(False)

    def _toast(self, text, timeout=3):
        toast = Adw.Toast(title=text)
        toast.set_timeout(timeout)
        self.add_toast(toast)

    # ----- Library page ---------------------------------------------------
    def _build_library_page(self):
        page = Adw.PreferencesPage(
            title=self.t("prefs.page.library"), icon_name="folder-symbolic"
        )

        folder_group = Adw.PreferencesGroup(title=self.t("prefs.group.roms_folder"))
        self._roms_path_row = Adw.ActionRow(
            title=self.t("settings.path.title"),
            subtitle=str(self.config.get_roms_path()),
        )
        self._roms_path_row.set_subtitle_selectable(True)
        choose_btn = Gtk.Button(label=self.t("prefs.roms.choose"))
        choose_btn.set_valign(Gtk.Align.CENTER)
        choose_btn.add_css_class("flat")
        choose_btn.connect("clicked", lambda _b: self.win._choose_roms_path())
        self._roms_path_row.add_suffix(choose_btn)
        open_btn = Gtk.Button(icon_name="folder-open-symbolic")
        open_btn.set_valign(Gtk.Align.CENTER)
        open_btn.add_css_class("flat")
        open_btn.set_tooltip_text(self.t("prefs.roms.open"))
        open_btn.connect("clicked", lambda _b: self.win._open_roms_folder())
        self._roms_path_row.add_suffix(open_btn)
        folder_group.add(self._roms_path_row)
        page.add(folder_group)

        maint_group = Adw.PreferencesGroup(title=self.t("prefs.group.maintenance"))
        scan_row = Adw.ActionRow(
            title=self.t("settings.scan.title"),
            subtitle=self.t("settings.scan.subtitle"),
        )
        scan_row.set_activatable(True)
        scan_row.add_prefix(Gtk.Image.new_from_icon_name("view-refresh-symbolic"))
        scan_row.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
        scan_row.connect("activated", lambda _r: self.win._show_scan_roms_dialog())
        maint_group.add(scan_row)

        sync_row = Adw.ActionRow(
            title=self.t("settings.sync.title"),
            subtitle=self.t("settings.sync.subtitle"),
        )
        sync_row.set_activatable(True)
        sync_row.add_prefix(Gtk.Image.new_from_icon_name("folder-download-symbolic"))
        sync_row.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
        sync_row.connect("activated", lambda _r: self.win._show_sync_covers_dialog())
        maint_group.add(sync_row)
        page.add(maint_group)
        page.add(self._build_artwork_providers_group())
        page.add(self._build_screenscraper_group())
        return page

    # ----- Artwork providers ----------------------------------------------
    def _build_artwork_providers_group(self):
        """The ordered provider list (issue #76).

        One uniform row per provider so the right-side controls line up:
        move up/down first, then the enable switch. No per-kind options: an
        enabled provider fetches every artwork kind it serves.
        """
        self._providers_group = Adw.PreferencesGroup(
            title=self.t("prefs.group.artwork_providers"),
            description=self.t("prefs.artwork_providers.description"),
        )
        self._provider_rows = []
        self._rebuild_provider_rows()
        return self._providers_group

    def _rebuild_provider_rows(self):
        for row in self._provider_rows:
            self._providers_group.remove(row)
        self._provider_rows = []
        providers = self.config.get_artwork_providers()
        for index, entry in enumerate(providers):
            row = self._make_provider_row(entry, index, len(providers))
            self._providers_group.add(row)
            self._provider_rows.append(row)
        if hasattr(self, "_ss_user_row"):
            self._update_screenscraper_rows_visibility()

    def _make_provider_row(self, entry, index, count):
        provider_id = entry["id"]
        row = Adw.ActionRow(
            title=self.t(f"prefs.provider.{provider_id}"),
            subtitle=self.t(f"prefs.provider.{provider_id}.subtitle"),
        )

        up = Gtk.Button(icon_name="go-up-symbolic")
        up.set_tooltip_text(self.t("prefs.provider.move_up"))
        up.set_valign(Gtk.Align.CENTER)
        up.add_css_class("flat")
        up.set_sensitive(index > 0)
        up.connect("clicked", lambda _b, i=index: self._move_provider(i, -1))
        row.add_suffix(up)

        down = Gtk.Button(icon_name="go-down-symbolic")
        down.set_tooltip_text(self.t("prefs.provider.move_down"))
        down.set_valign(Gtk.Align.CENTER)
        down.add_css_class("flat")
        down.set_sensitive(index < count - 1)
        down.connect("clicked", lambda _b, i=index: self._move_provider(i, +1))
        row.add_suffix(down)

        switch = Gtk.Switch(active=bool(entry.get("enabled", True)))
        switch.set_valign(Gtk.Align.CENTER)
        switch.connect(
            "notify::active",
            lambda sw, _p, pid=provider_id: self._set_provider_enabled(pid, sw.get_active()),
        )
        row.add_suffix(switch)
        return row

    def _mutate_providers(self, mutate):
        providers = self.config.get_artwork_providers()
        mutate(providers)
        self.config.set_artwork_providers(providers)

    def _move_provider(self, index, delta):
        def _mutate(providers):
            other = index + delta
            if 0 <= other < len(providers):
                providers[index], providers[other] = providers[other], providers[index]

        self._mutate_providers(_mutate)
        self._rebuild_provider_rows()

    def _set_provider_enabled(self, provider_id, enabled):
        def _mutate(providers):
            for entry in providers:
                if entry["id"] == provider_id:
                    entry["enabled"] = bool(enabled)

        self._mutate_providers(_mutate)
        self._update_screenscraper_rows_visibility()

    def _build_screenscraper_group(self):
        """ScreenScraper account rows, shown while that provider is enabled."""
        settings = self.config.get_cover_sync_settings()
        group = Adw.PreferencesGroup(
            title=self.t("prefs.group.screenscraper"),
            description=self.t("prefs.screenscraper.description"),
        )

        self._ss_user_row = Adw.EntryRow(title=self.t("prefs.screenscraper.user"))
        self._ss_user_row.set_text(settings.get("screenscraper_user", ""))
        self._ss_user_row.connect(
            "changed",
            lambda row: self.config.set_cover_sync_setting("screenscraper_user", row.get_text()),
        )
        group.add(self._ss_user_row)

        self._ss_password_row = Adw.PasswordEntryRow(title=self.t("prefs.screenscraper.password"))
        self._ss_password_row.set_text(settings.get("screenscraper_password", ""))
        self._ss_password_row.connect(
            "changed",
            lambda row: self.config.set_cover_sync_setting("screenscraper_password", row.get_text()),
        )
        group.add(self._ss_password_row)

        # The developer credential is the project's own account, baked into
        # official builds (or supplied via a local .env in development). It is not
        # a normal setting, so it lives behind a collapsed "Advanced" disclosure
        # rather than sitting in plain sight -- only an advanced user overriding
        # it with their own ScreenScraper developer account ever needs it.
        self._ss_devid_row = Adw.EntryRow(title=self.t("prefs.screenscraper.devid"))
        self._ss_devid_row.set_text(settings.get("screenscraper_devid", ""))
        self._ss_devid_row.connect(
            "changed",
            lambda row: self.config.set_cover_sync_setting("screenscraper_devid", row.get_text()),
        )

        self._ss_devpassword_row = Adw.PasswordEntryRow(
            title=self.t("prefs.screenscraper.devpassword")
        )
        self._ss_devpassword_row.set_text(settings.get("screenscraper_devpassword", ""))
        self._ss_devpassword_row.connect(
            "changed",
            lambda row: self.config.set_cover_sync_setting("screenscraper_devpassword", row.get_text()),
        )

        self._ss_advanced_row = Adw.ExpanderRow(
            title=self.t("prefs.screenscraper.advanced.title"),
            subtitle=self.t("prefs.screenscraper.advanced.subtitle"),
        )
        self._ss_advanced_row.set_expanded(False)
        self._ss_advanced_row.add_row(self._ss_devid_row)
        self._ss_advanced_row.add_row(self._ss_devpassword_row)
        group.add(self._ss_advanced_row)

        # Official builds embed the project's developer credential; when present
        # a friendlier "ready to use" note replaces the "credentials needed" hint.
        self._ss_embedded = has_embedded_dev_credentials()
        self._ss_hint_row = Adw.ActionRow(
            title=self.t("prefs.screenscraper.hint.title"),
            subtitle=self.t("prefs.screenscraper.hint.subtitle"),
        )
        self._ss_hint_row.set_subtitle_lines(0)
        group.add(self._ss_hint_row)

        self._ss_embedded_hint_row = Adw.ActionRow(
            title=self.t("prefs.screenscraper.hint.embedded.title"),
            subtitle=self.t("prefs.screenscraper.hint.embedded.subtitle"),
        )
        self._ss_embedded_hint_row.set_subtitle_lines(0)
        group.add(self._ss_embedded_hint_row)

        self._update_screenscraper_rows_visibility()
        return group

    def _update_screenscraper_rows_visibility(self):
        uses_screenscraper = any(
            entry["id"] == "screenscraper" and entry.get("enabled", True)
            for entry in self.config.get_artwork_providers()
        )
        # The dev credential lives inside the collapsed "Advanced" expander, so
        # the group just shows/hides the normal user-account rows, the expander,
        # and the matching hint.
        for row in (
            self._ss_user_row,
            self._ss_password_row,
            self._ss_advanced_row,
        ):
            row.set_visible(uses_screenscraper)
        # "Ready to use" when the build carries the credential, otherwise the
        # "credentials needed" hint (the user must supply one under Advanced).
        self._ss_hint_row.set_visible(uses_screenscraper and not self._ss_embedded)
        self._ss_embedded_hint_row.set_visible(uses_screenscraper and self._ss_embedded)

    # ----- BIOS page ------------------------------------------------------
    def _build_bios_page(self):
        page = Adw.PreferencesPage(
            title=self.t("prefs.page.bios"), icon_name="media-floppy-symbolic"
        )
        self._bios_group = Adw.PreferencesGroup(
            title=self.t("settings.bios.title"),
            description=GLib.markup_escape_text(self.t("bios.instructions")),
        )
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        open_btn = Gtk.Button(label=self.t("bios.open_roms_folder"))
        open_btn.add_css_class("flat")
        open_btn.connect("clicked", lambda _b: self.win._open_roms_folder())
        header_box.append(open_btn)
        reload_btn = Gtk.Button(icon_name="view-refresh-symbolic")
        reload_btn.add_css_class("flat")
        reload_btn.set_tooltip_text(self.t("bios.reload"))
        reload_btn.connect("clicked", lambda _b: self._reload_bios(show_toast=True))
        header_box.append(reload_btn)
        self._bios_group.set_header_suffix(header_box)
        page.add(self._bios_group)
        self._bios_rows = []
        self._reload_bios(show_toast=False)
        return page

    def _reload_bios(self, show_toast=False):
        for row in getattr(self, "_bios_rows", []):
            self._bios_group.remove(row)
        self._bios_rows = []

        status_by_console = scan_all_bios_status(self.config)
        if not status_by_console:
            empty = Adw.ActionRow(title=self.t("bios.no_requirements"))
            self._bios_group.add(empty)
            self._bios_rows.append(empty)
            return

        for console_id in sorted(status_by_console.keys()):
            status = status_by_console[console_id]
            present = sum(
                1 for e in status["required"] + status["optional"] if e["present"]
            )
            total = len(status["required"]) + len(status["optional"])
            expander = Adw.ExpanderRow(
                title=f"{console_id} — {status['display_name']}",
                subtitle=f"{present}/{total}",
            )
            # The row names a console, so show its icon like everywhere else.
            expander.add_prefix(self.win._build_console_icon(console_id))
            open_btn = Gtk.Button(icon_name="folder-open-symbolic")
            open_btn.add_css_class("flat")
            open_btn.set_valign(Gtk.Align.CENTER)
            open_btn.set_tooltip_text(self.t("bios.open_console_folder"))
            open_btn.connect(
                "clicked", lambda _b, cid=console_id: self.win._open_console_bios_folder(cid)
            )
            expander.add_suffix(open_btn)

            for section_key, entries in (
                ("bios.section.required", status["required"]),
                ("bios.section.optional", status["optional"]),
            ):
                for entry in entries:
                    label_text = entry["label"]
                    if entry.get("kind") == "any_of" and label_text:
                        label_text = self.t("bios.one_of", names=label_text)
                    row = Adw.ActionRow(title=label_text, subtitle=self.t(section_key))
                    icon = Gtk.Image.new_from_icon_name(
                        "emblem-ok-symbolic" if entry["present"] else "dialog-warning-symbolic"
                    )
                    icon.add_css_class("success" if entry["present"] else "warning")
                    row.add_prefix(icon)
                    expander.add_row(row)
            self._bios_group.add(expander)
            self._bios_rows.append(expander)

        if show_toast:
            self._toast(self.t("bios.reloaded"))

    def _apply_console_icon_factory(self, combo_row):
        """Render a console ComboRow as "<icon> ID — Name", like the sidebar.

        The pre-libadwaita UI showed console icons in these selectors and the
        refactor dropped them; this restores that without duplicating the icon
        lookup, which stays owned by the window.
        """

        def _setup(_factory, list_item):
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            box.set_margin_top(4)
            box.set_margin_bottom(4)
            list_item.set_child(box)

        def _bind(_factory, list_item):
            box = list_item.get_child()
            while child := box.get_first_child():
                box.remove(child)
            item = list_item.get_item()
            console_id = item.get_string() if item else ""
            box.append(self.win._build_console_icon(console_id))
            label = Gtk.Label(label=f"{console_id} — {get_system_display_name(console_id)}")
            label.set_halign(Gtk.Align.START)
            label.set_xalign(0)
            box.append(label)

        for setter in (combo_row.set_factory, combo_row.set_list_factory):
            factory = Gtk.SignalListItemFactory()
            factory.connect("setup", _setup)
            factory.connect("bind", _bind)
            setter(factory)

    def _apply_device_icon_factory(self, combo_row):
        """Render the device ComboRow as "<icon> Label".

        Icons are themed symbolic names resolved by GTK, so binding stays cheap
        and touches no filesystem -- do not swap this for a file-backed icon.
        """
        # The model holds translated labels; map them back to device ids so the
        # binding never depends on a list position (which is invalid for the
        # ComboRow's closed-state factory).
        device_by_label = {
            self.t(f"input.device.{device_id}"): device_id for device_id in self._device_ids
        }

        def _setup(_factory, list_item):
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            box.set_margin_top(4)
            box.set_margin_bottom(4)
            icon = Gtk.Image()
            label = Gtk.Label()
            label.set_halign(Gtk.Align.START)
            label.set_xalign(0)
            box.append(icon)
            box.append(label)
            list_item.set_child(box)

        def _bind(_factory, list_item):
            box = list_item.get_child()
            icon = box.get_first_child()
            label = icon.get_next_sibling()
            item = list_item.get_item()
            text = item.get_string() if item else ""
            device_id = device_by_label.get(text, "keyboard")
            icon.set_from_icon_name(
                "input-keyboard-symbolic" if device_id == "keyboard" else "input-gaming-symbolic"
            )
            label.set_label(text)

        for setter in (combo_row.set_factory, combo_row.set_list_factory):
            factory = Gtk.SignalListItemFactory()
            factory.connect("setup", _setup)
            factory.connect("bind", _bind)
            setter(factory)

    # ----- Input page -----------------------------------------------------
    def _build_input_page(self):
        page = Adw.PreferencesPage(
            title=self.t("prefs.page.input"), icon_name="input-gaming-symbolic"
        )

        # Bindings reach RetroArch only through the --appendconfig file
        # written at spawn, so a remap only lands in a running game via the
        # state-carrying relaunch (issue #129). Save and Reset trigger it
        # themselves; the banner's button covers the rows that write straight
        # to disk as they change (analog mode, turbo, tuning sliders).
        #
        # Adw.PreferencesPage has no banner slot, so it rides in a group of
        # its own -- which must be the first thing on the page.
        self._relaunch_banner = Adw.Banner(title=self.t("prefs.input.banner.running"))
        self._relaunch_banner.set_button_label(self.t("prefs.input.banner.apply_now"))
        self._relaunch_banner.connect("button-clicked", self._on_relaunch_clicked)
        self._relaunch_banner.set_revealed(False)
        banner_group = Adw.PreferencesGroup()
        banner_group.add(self._relaunch_banner)
        page.add(banner_group)

        controller_group = Adw.PreferencesGroup(title=self.t("prefs.group.controller"))
        self._console_ids = list(SYSTEM_IDS)
        self._console_combo = Adw.ComboRow(title=self.t("input.console"))
        # Model holds bare console ids so the factory can resolve each icon; the
        # factory renders "<icon> ID — Name".
        self._console_combo.set_model(Gtk.StringList.new(self._console_ids))
        self._apply_console_icon_factory(self._console_combo)
        default_console = (
            self.win.current_console
            if self.win.current_console in self._console_ids
            else self._console_ids[0]
        )
        self._console_combo.set_selected(self._console_ids.index(default_console))
        self._console_combo.connect("notify::selected", self._on_console_changed)
        controller_group.add(self._console_combo)

        self._device_ids = list(DEVICE_IDS)
        # Picks which map is being edited, not which one is live: the
        # keyboard and player 1's pad are both always active (issue #150).
        self._device_combo = Adw.ComboRow(
            title=self.t("input.device"),
            subtitle=self.t("input.device.subtitle"),
        )
        self._device_combo.set_model(
            Gtk.StringList.new([self.t(f"input.device.{d}") for d in self._device_ids])
        )
        self._apply_device_icon_factory(self._device_combo)
        self._device_combo.set_selected(0)
        self._device_combo.connect("notify::selected", self._on_device_changed)
        controller_group.add(self._device_combo)

        self._port_enabled_switch = Adw.SwitchRow(
            title=self.t("input.port.enable"),
            subtitle=self.t("input.port.enable.subtitle"),
        )
        self._port_enabled_switch.set_visible(False)
        controller_group.add(self._port_enabled_switch)

        # Which controller the core is told is plugged in (issue #151). Only
        # shown where the console's core publishes more than one -- most
        # publish exactly one, and a combo with a single entry is furniture.
        self._controller_type_row = Adw.ComboRow(
            title=self.t("input.controller_type.title"),
            subtitle=self.t("input.controller_type.subtitle"),
        )
        self._controller_type_guard = False
        self._controller_type_ids = []
        self._sync_controller_type_row()
        self._controller_type_row.connect(
            "notify::selected", self._on_controller_type_changed
        )
        controller_group.add(self._controller_type_row)

        # Analog-as-D-pad (issue #71): per console, RetroArch's own
        # analog_dpad_mode, so the stick and the D-pad steer together.
        self._analog_dpad_ids = list(ANALOG_DPAD_MODES)
        self._analog_dpad_row = Adw.ComboRow(
            title=self.t("input.analog_dpad.title"),
            subtitle=self.t("input.analog_dpad.subtitle"),
        )
        self._analog_dpad_row.set_model(
            Gtk.StringList.new(
                [self.t(f"input.analog_dpad.mode.{mode}") for mode in self._analog_dpad_ids]
            )
        )
        self._analog_dpad_guard = False
        self._sync_analog_dpad_row()
        self._analog_dpad_row.connect("notify::selected", self._on_analog_dpad_changed)
        controller_group.add(self._analog_dpad_row)

        # The other direction (issue #156): the pad's D-pad standing in for
        # the stick, for a game that only reads analog.
        self._dpad_analog_row = Adw.SwitchRow(
            title=self.t("input.dpad_analog.title"),
            subtitle=self.t("input.dpad_analog.subtitle"),
        )
        self._dpad_analog_guard = False
        self._sync_dpad_analog_row()
        self._dpad_analog_row.connect("notify::active", self._on_dpad_analog_changed)
        controller_group.add(self._dpad_analog_row)
        page.add(controller_group)

        # Stick and feedback tuning (issues #154, #155). Global rather than
        # per console: a worn stick drifts the same on every system, and
        # vibration strength belongs to the pad -- making these per console
        # would mean setting the deadzone thirty-one times.
        tuning_group = Adw.PreferencesGroup(
            title=self.t("prefs.group.input_tuning"),
            description=self.t("prefs.group.input_tuning.description"),
        )
        self._tuning_guard = True
        self._tuning_rows = {}
        for name, digits, step in (
            ("analog_deadzone", 2, 0.05),
            ("analog_sensitivity", 2, 0.05),
            ("axis_threshold", 2, 0.05),
        ):
            low, high = INPUT_TUNING[name][3], INPUT_TUNING[name][4]
            row = Adw.SpinRow.new_with_range(low, high, step)
            row.set_digits(digits)
            row.set_title(self.t(f"input.tuning.{name}"))
            row.set_subtitle(self.t(f"input.tuning.{name}.subtitle"))
            row.set_value(self.config.get_input_tuning_value(name))
            row.connect("notify::value", self._on_tuning_changed, name)
            tuning_group.add(row)
            self._tuning_rows[name] = row

        rumble = Adw.SpinRow.new_with_range(0, 100, 5)
        rumble.set_title(self.t("input.tuning.rumble_gain"))
        rumble.set_subtitle(self.t("input.tuning.rumble_gain.subtitle"))
        rumble.set_value(self.config.get_input_tuning_value("rumble_gain"))
        rumble.connect("notify::value", self._on_tuning_changed, "rumble_gain")
        tuning_group.add(rumble)
        self._tuning_rows["rumble_gain"] = rumble

        self._poll_row = Adw.ComboRow(
            title=self.t("input.tuning.poll_type_behavior"),
            subtitle=self.t("input.tuning.poll_type_behavior.subtitle"),
        )
        self._poll_row.set_model(
            Gtk.StringList.new([self.t(f"input.tuning.poll.{i}") for i in range(3)])
        )
        self._poll_row.set_selected(self.config.get_input_tuning_value("poll_type_behavior"))
        self._poll_row.connect("notify::selected", self._on_poll_type_changed)
        tuning_group.add(self._poll_row)

        self._focus_row = Adw.ComboRow(
            title=self.t("input.tuning.auto_game_focus"),
            subtitle=self.t("input.tuning.auto_game_focus.subtitle"),
        )
        self._focus_row.set_model(
            Gtk.StringList.new([self.t(f"input.tuning.focus.{i}") for i in range(3)])
        )
        self._focus_row.set_selected(self.config.get_input_tuning_value("auto_game_focus"))
        self._focus_row.connect("notify::selected", self._on_auto_focus_changed)
        tuning_group.add(self._focus_row)

        self._descriptor_row = Adw.SwitchRow(
            title=self.t("input.tuning.descriptor_label_show"),
            subtitle=self.t("input.tuning.descriptor_label_show.subtitle"),
        )
        self._descriptor_row.set_active(
            self.config.get_input_tuning_value("descriptor_label_show")
        )
        self._descriptor_row.connect("notify::active", self._on_descriptor_changed)
        tuning_group.add(self._descriptor_row)
        self._tuning_guard = False
        page.add(tuning_group)

        # Turbo timing (issue #72): tuning knobs; the modifier button itself is
        # a normal binding row ("Turbo") in the mapping list below.
        turbo_group = Adw.PreferencesGroup(
            title=self.t("prefs.group.turbo"),
            description=self.t("prefs.turbo.description"),
        )
        self._turbo_guard = False
        self._turbo_period_row = Adw.SpinRow.new_with_range(*TURBO_PERIOD_RANGE, 1)
        self._turbo_period_row.set_title(self.t("input.turbo.period"))
        self._turbo_period_row.set_subtitle(self.t("input.turbo.period.subtitle"))
        self._turbo_period_row.connect("notify::value", self._on_turbo_changed)
        turbo_group.add(self._turbo_period_row)

        self._turbo_duty_row = Adw.SpinRow.new_with_range(*TURBO_DUTY_RANGE, 1)
        self._turbo_duty_row.set_title(self.t("input.turbo.duty"))
        self._turbo_duty_row.set_subtitle(self.t("input.turbo.duty.subtitle"))
        self._turbo_duty_row.connect("notify::value", self._on_turbo_changed)
        turbo_group.add(self._turbo_duty_row)

        self._turbo_mode_ids = list(TURBO_MODES)
        self._turbo_mode_row = Adw.ComboRow(title=self.t("input.turbo.mode"))
        self._turbo_mode_row.set_model(
            Gtk.StringList.new(
                [self.t(f"input.turbo.mode.{mode}") for mode in self._turbo_mode_ids]
            )
        )
        self._turbo_mode_row.connect("notify::selected", self._on_turbo_changed)
        turbo_group.add(self._turbo_mode_row)
        self._sync_turbo_rows()
        page.add(turbo_group)

        # Two groups: the controls a game reads (d-pad, face buttons, start…)
        # and the frontend hotkeys (save/load state, volume, fullscreen…).
        # They are bound the same way but answer different questions, and
        # RetroArch itself treats the hotkeys as global rather than per-port.
        self._bindings_group = Adw.PreferencesGroup(title=self.t("prefs.group.bindings.game"))
        self._system_bindings_group = Adw.PreferencesGroup(
            title=self.t("prefs.group.bindings.system"),
            description=self.t("prefs.group.bindings.system.description"),
        )
        actions_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._map_all_btn = Gtk.Button(label=self.t("input.map_all"))
        self._map_all_btn.add_css_class("flat")
        self._map_all_btn.connect("clicked", lambda _b: self._start_map_all())
        actions_box.append(self._map_all_btn)
        reset_btn = Gtk.Button(label=self.t("input.reset"))
        reset_btn.add_css_class("flat")
        reset_btn.connect("clicked", lambda _b: self._reset_defaults())
        actions_box.append(reset_btn)
        save_btn = Gtk.Button(label=self.t("input.save"))
        save_btn.add_css_class("suggested-action")
        save_btn.connect("clicked", lambda _b: self._save_input())
        actions_box.append(save_btn)
        self._bindings_group.set_header_suffix(actions_box)
        page.add(self._bindings_group)
        page.add(self._system_bindings_group)

        self._refresh_bindings()
        self._sync_relaunch_banner()
        return page

    def _sync_relaunch_banner(self):
        """Show the banner only while there is a game to relaunch."""
        banner = getattr(self, "_relaunch_banner", None)
        if banner is None:
            return
        banner.set_revealed(self.win.runtime_manager.is_running())

    def _on_relaunch_clicked(self, _banner):
        # State-preserving apply, same as Save uses -- the button exists for
        # the rows that persist as they change and so never pass through
        # _save_input (issue #129).
        self.win.apply_input_changes_to_running_game()
        # The game is briefly gone and then back, so the banner is left up
        # rather than flickering; this re-checks once the dust settles, which
        # is also what takes it down if the relaunch failed.
        GLib.timeout_add_seconds(5, self._sync_relaunch_banner_once)

    def _sync_relaunch_banner_once(self):
        self._sync_relaunch_banner()
        return False

    def _current_console(self):
        idx = self._console_combo.get_selected()
        if idx < 0 or idx >= len(self._console_ids):
            return self._console_ids[0]
        return self._console_ids[idx]

    def _current_device(self):
        idx = self._device_combo.get_selected()
        if idx < 0 or idx >= len(self._device_ids):
            return "keyboard"
        return self._device_ids[idx]

    def _sync_turbo_rows(self):
        settings = self.config.input_profiles.get_turbo_settings(self._current_console())
        self._turbo_guard = True
        self._turbo_period_row.set_value(settings["period"])
        self._turbo_duty_row.set_value(settings["duty_cycle"])
        self._turbo_mode_row.set_selected(self._turbo_mode_ids.index(settings["mode"]))
        self._turbo_guard = False

    def _on_turbo_changed(self, *_a):
        if self._turbo_guard:
            return
        self.config.input_profiles.set_turbo_settings(
            self._current_console(),
            {
                "period": int(self._turbo_period_row.get_value()),
                "duty_cycle": int(self._turbo_duty_row.get_value()),
                "mode": self._turbo_mode_ids[self._turbo_mode_row.get_selected()],
            },
        )

    def _sync_dpad_analog_row(self):
        console = self._current_console()
        # Only where the core reads a stick at all -- elsewhere there is
        # nothing for the D-pad to stand in for.
        has_stick = "l_up" in get_actions_for_console(console)
        self._dpad_analog_row.set_visible(has_stick)
        if not has_stick:
            return
        self._dpad_analog_guard = True
        self._dpad_analog_row.set_active(
            self.config.input_profiles.get_dpad_drives_analog(console)
        )
        self._dpad_analog_guard = False

    def _on_dpad_analog_changed(self, *_a):
        if self._dpad_analog_guard:
            return
        self.config.input_profiles.set_dpad_drives_analog(
            self._current_console(), self._dpad_analog_row.get_active()
        )

    def _on_tuning_changed(self, row, _param, name):
        if self._tuning_guard:
            return
        self.config.set_input_tuning_value(name, row.get_value())

    def _on_poll_type_changed(self, *_a):
        if self._tuning_guard:
            return
        self.config.set_input_tuning_value(
            "poll_type_behavior", self._poll_row.get_selected()
        )

    def _on_auto_focus_changed(self, *_a):
        if self._tuning_guard:
            return
        self.config.set_input_tuning_value(
            "auto_game_focus", self._focus_row.get_selected()
        )

    def _on_descriptor_changed(self, *_a):
        if self._tuning_guard:
            return
        self.config.set_input_tuning_value(
            "descriptor_label_show", self._descriptor_row.get_active()
        )

    def _sync_controller_type_row(self):
        console = self._current_console()
        types = controller_types_for(console)
        self._controller_type_row.set_visible(bool(types))
        if not types:
            self._controller_type_ids = []
            return
        # None first: "whatever the core boots with", which is the default and
        # the only honest option for a core we have not verified.
        self._controller_type_ids = [None] + [ident for ident, _label in types]
        labels = [self.t("input.controller_type.core_default")] + [
            label for _ident, label in types
        ]
        self._controller_type_guard = True
        self._controller_type_row.set_model(Gtk.StringList.new(labels))
        current = self.config.input_profiles.get_controller_type(console)
        self._controller_type_row.set_selected(
            self._controller_type_ids.index(current)
            if current in self._controller_type_ids
            else 0
        )
        self._controller_type_guard = False

    def _on_controller_type_changed(self, *_a):
        if self._controller_type_guard:
            return
        index = self._controller_type_row.get_selected()
        if index < 0 or index >= len(self._controller_type_ids):
            return
        self.config.input_profiles.set_controller_type(
            self._current_console(), self._controller_type_ids[index]
        )

    def _sync_analog_dpad_row(self):
        mode = self.config.input_profiles.get_analog_dpad_mode(self._current_console())
        self._analog_dpad_guard = True
        self._analog_dpad_row.set_selected(self._analog_dpad_ids.index(mode))
        self._analog_dpad_guard = False

    def _on_analog_dpad_changed(self, *_a):
        if self._analog_dpad_guard:
            return
        mode = self._analog_dpad_ids[self._analog_dpad_row.get_selected()]
        self.config.input_profiles.set_analog_dpad_mode(self._current_console(), mode)

    def _on_console_changed(self, *_a):
        self._cancel_capture()
        self._sync_controller_type_row()
        self._sync_analog_dpad_row()
        self._sync_dpad_analog_row()
        self._sync_turbo_rows()
        self._refresh_bindings()

    def _on_device_changed(self, *_a):
        self._cancel_capture()
        self._refresh_bindings()

    def _input_action_label(self, action):
        return self.t(f"input.action.{action}")

    def _input_action_subtitle(self, action):
        """Extra explanation for rows whose title cannot carry it.

        Only ``enable_hotkey`` needs one today: it reads as one more row among
        the System Hotkeys while actually gating every one of them (#124).
        """
        if action == "enable_hotkey":
            return self.t("input.action.enable_hotkey.subtitle")
        return None

    def _binding_display(self, value):
        if not value:
            return self.t("input.binding.empty")
        if self._current_device() == "keyboard":
            return value
        # Gamepad bindings are stored as RetroArch tokens ("3", "+2", "h0up");
        # show something a human can recognise while keeping the token.
        kind, detail = describe_token(value)
        if kind == "button":
            return self.t("input.binding.button", index=detail)
        if kind == "axis":
            return self.t("input.binding.axis", axis=detail)
        if kind == "hat":
            arrows = {"up": "↑", "down": "↓", "left": "←", "right": "→"}
            return self.t("input.binding.hat", direction=arrows.get(detail, detail))
        return value

    def _group_for_action(self, action):
        """Frontend hotkeys go to the System group, controls to the Game one."""
        if action in GLOBAL_HOTKEY_ACTIONS:
            return self._system_bindings_group
        return self._bindings_group

    def _set_capture_prompt(self, prompt, action=None):
        """Show "press a key…" on the group holding the row being captured.

        ``prompt=None`` restores both groups to their resting descriptions --
        the System group keeps a standing one explaining what it is for.
        """
        system_default = self.t("prefs.group.bindings.system.description")
        if prompt is None or action is None:
            self._bindings_group.set_description(None)
            self._system_bindings_group.set_description(system_default)
            return
        if action in GLOBAL_HOTKEY_ACTIONS:
            self._bindings_group.set_description(None)
            self._system_bindings_group.set_description(prompt)
        else:
            self._bindings_group.set_description(prompt)
            self._system_bindings_group.set_description(system_default)

    def _refresh_bindings(self):
        for action, row in list(self._input_rows.items()):
            self._group_for_action(action).remove(row)
        self._input_rows = {}
        self._input_buttons = {}

        console_id = self._current_console()
        device_id = self._current_device()
        profile = self.config.get_input_profile(console_id)
        if device_id not in profile.get("devices", {}):
            device_id = "keyboard"
            self._device_combo.set_selected(0)
        device = profile.get("devices", {}).get(device_id, {})
        bindings = device.get("bindings", {})
        visible_actions = get_actions_for_console(console_id)
        if device_id in EXTRA_PORT_DEVICE_IDS:
            # RetroArch hotkeys are global, so ports 2-4 only map gameplay.
            visible_actions = [a for a in visible_actions if a not in GLOBAL_HOTKEY_ACTIONS]

        self._loaded_profile = profile
        self._visible_actions = list(visible_actions)
        # Map-all never demands the optional actions (turbo): forcing a user
        # through binding a modifier they may not want defeats the flow.
        self._capture_sequence_actions = [
            action for action in visible_actions if action not in OPTIONAL_ACTIONS
        ]
        self._bindings_buffer = {
            action: str(bindings.get(action, "")).strip().lower() for action in visible_actions
        }
        is_extra_port = device_id in EXTRA_PORT_DEVICE_IDS
        self._port_enabled_switch.set_visible(is_extra_port)
        if is_extra_port:
            self._port_enabled_switch.set_active(bool(device.get("enabled", False)))
        self._map_all_btn.set_sensitive(True)
        self._set_capture_prompt(None)
        # Ports 2-4 map no hotkeys at all (they are global), so the whole
        # System group goes away rather than standing there empty.
        self._system_bindings_group.set_visible(
            any(action in GLOBAL_HOTKEY_ACTIONS for action in visible_actions)
        )

        for action in visible_actions:
            row = Adw.ActionRow(title=self._input_action_label(action))
            subtitle = self._input_action_subtitle(action)
            if subtitle:
                row.set_subtitle(subtitle)
            button = Gtk.Button(label=self._binding_display(self._bindings_buffer.get(action, "")))
            button.set_valign(Gtk.Align.CENTER)
            button.set_size_request(150, -1)
            button.connect("clicked", self._on_binding_clicked, action)
            row.add_suffix(button)
            row.set_activatable_widget(button)
            self._group_for_action(action).add(row)
            self._input_rows[action] = row
            self._input_buttons[action] = button

    def _set_active_row(self, action=None):
        for row_action, row in self._input_rows.items():
            if row_action == action:
                row.add_css_class("input-mapping-current")
            else:
                row.remove_css_class("input-mapping-current")

    def _on_binding_clicked(self, _button, action):
        self._start_capture(action, sequence_mode=False)

    def _start_capture(self, action, sequence_mode):
        if action not in self._input_buttons:
            return
        self._stop_gamepad_reader()
        # Take the controller away from UI navigation for the duration: the
        # very buttons being mapped (B, A, the D-pad) are also the ones that
        # drive the interface, and they would close this dialog mid-capture.
        self._set_exclusive_input(True)
        self._capture_active_action = action
        self._capture_sequence_mode = sequence_mode
        self._set_active_row(action)

        is_gamepad = self._current_device() != "keyboard"
        waiting_key = "input.capture.waiting_gamepad" if is_gamepad else "input.capture.waiting"
        prompt_key = (
            "input.capture.waiting_for_gamepad" if is_gamepad else "input.capture.waiting_for"
        )
        self._input_buttons[action].set_label(self.t(waiting_key))
        prompt = self.t(prompt_key, action=self._input_action_label(action))
        if is_gamepad:
            prompt = f"{prompt} — {self.t('input.capture.cancel_hint')}"
        self._set_capture_prompt(prompt, action)

        if is_gamepad:
            self._start_gamepad_reader()

    # -- gamepad reader plumbing ------------------------------------------
    def _device_for_port(self, port):
        """Pick the physical pad to listen on for RetroArch port ``port``.

        Pads are taken in /dev/input/event* order, which is the same ordering
        RetroArch's udev driver enumerates, so port N listens on the Nth pad.
        Returns ``(device, error_key)``; ``device=None`` with no error means
        "let the reader choose", which only happens for port 1.
        """
        if port <= 1:
            return None, None
        gamepads = list_gamepads()
        if len(gamepads) < port:
            return None, "input.capture.port_unavailable"
        return gamepads[port - 1], None

    def _start_gamepad_reader(self):
        port = player_for_device(self._current_device())
        device, error_key = self._device_for_port(port)
        if error_key:
            self._cancel_capture()
            self._toast(self.t(error_key, port=port), timeout=6)
            return
        self._gamepad_reader = GamepadCaptureReader(
            on_token=lambda token: GLib.idle_add(self._on_gamepad_token, token),
            on_error=lambda reason: GLib.idle_add(self._on_gamepad_error, reason),
            device=device,
        )
        self._gamepad_reader.start()

    def _stop_gamepad_reader(self):
        reader = self._gamepad_reader
        self._gamepad_reader = None
        if reader is not None:
            reader.stop()

    def _on_gamepad_token(self, token):
        # The reader runs on its own thread; capture may have been cancelled
        # between the press and this idle callback.
        if not self._capture_active_action or self._current_device() == "keyboard":
            return False
        self._gamepad_reader = None
        self._commit_capture(token)
        return False

    def _on_gamepad_error(self, reason):
        if not self._capture_active_action:
            return False
        self._gamepad_reader = None
        self._cancel_capture()
        key = (
            "input.capture.permission_denied"
            if reason == "permission_denied"
            else "input.capture.no_gamepad"
        )
        self._toast(self.t(key), timeout=6)
        return False

    def _set_exclusive_input(self, active):
        """Toggle the window's exclusive-capture mode, if there is a window.

        Guarded with getattr so the dialog keeps working against a stub window
        in tests and against any caller that predates the flag.
        """
        setter = getattr(self.win, "set_input_capture_active", None)
        if setter is not None:
            setter(active)

    def _cancel_capture(self, show_toast=False):
        self._stop_gamepad_reader()
        self._set_exclusive_input(False)
        if self._capture_active_action in self._input_buttons:
            action = self._capture_active_action
            self._input_buttons[action].set_label(
                self._binding_display(self._bindings_buffer.get(action, ""))
            )
        self._capture_active_action = None
        was_sequence = self._capture_sequence_mode
        self._capture_sequence_mode = False
        self._capture_sequence_index = -1
        self._set_active_row(None)
        if hasattr(self, "_bindings_group"):
            self._set_capture_prompt(None)
        if show_toast and was_sequence:
            self._toast(self.t("input.capture.cancelled"))

    def _start_map_all(self):
        if not self._capture_sequence_actions:
            return
        self._cancel_capture()
        self._capture_sequence_mode = True
        self._capture_sequence_index = 0
        self._start_capture(self._capture_sequence_actions[0], sequence_mode=True)

    def _actions_holding(self, action, value):
        """What else is on ``value`` and has to let go of it.

        ``enable_hotkey`` is the exception in both directions: it ships on the
        same token as Select on purpose (issue #124), because a hotkey that
        only fires while a modifier is held *is* a shared button. Every other
        collision is real -- the user pointed a button at a new command, and
        the old one cannot keep it (issue #281).
        """
        if not value:
            return []
        return [
            other
            for other, other_value in self._bindings_buffer.items()
            if other != action
            and other_value == value
            and "enable_hotkey" not in (other, action)
        ]

    def _set_binding(self, action, value):
        value = (value or "").strip().lower()
        released = self._actions_holding(action, value)
        for other_action in released:
            self._bindings_buffer[other_action] = ""
            if other_action in self._input_buttons:
                self._input_buttons[other_action].set_label(self._binding_display(""))
        self._bindings_buffer[action] = value
        if action in self._input_buttons:
            self._input_buttons[action].set_label(self._binding_display(value))
        # Say what was taken away. The row going blank on its own read as a
        # glitch, and the value came back on the next visit anyway; now it
        # really is released, so the message is the whole story. Not during
        # map-all: one toast per button is noise, not information.
        if released and not self._capture_sequence_mode:
            self._toast(
                self.t(
                    "toast.input_released",
                    binding=self._binding_display(value),
                    actions=", ".join(
                        self._input_action_label(other) for other in released
                    ),
                )
            )

    @staticmethod
    def _normalize_key(keyval):
        """A captured key, as the token RetroArch will resolve.

        GTK and RetroArch are different vocabularies -- ``=`` is ``equal`` to
        one and ``equals`` to the other -- and a token RetroArch cannot resolve
        produces a binding that reads as bound here and never fires (#144).
        """
        key_name = Gdk.keyval_name(keyval)
        if not key_name:
            return ""
        return retroarch_key_token(key_name.lower())

    def _commit_capture(self, value):
        """Store a captured binding and advance the sequence, if any.

        Shared by keyboard and gamepad capture.
        """
        action = self._capture_active_action
        if not action:
            return
        self._set_binding(action, value)
        if not self._capture_sequence_mode:
            self._cancel_capture()
            return
        self._capture_sequence_index += 1
        if self._capture_sequence_index >= len(self._capture_sequence_actions):
            self._cancel_capture()
            self._toast(self.t("input.capture.completed"))
            return
        next_action = self._capture_sequence_actions[self._capture_sequence_index]
        self._start_capture(next_action, sequence_mode=True)

    def _on_key_pressed(self, _controller, keyval, _keycode, _state):
        if not self._capture_active_action:
            return False
        key_name = self._normalize_key(keyval)
        action = self._capture_active_action

        # Escape always aborts, for both device types.
        if key_name == "escape":
            if self._capture_sequence_mode:
                self._cancel_capture(show_toast=True)
            else:
                self._set_binding(action, "")
                self._cancel_capture()
            return True

        # While capturing a gamepad binding, swallow other keys so a stray
        # keystroke cannot be stored as a controller token.
        if self._current_device() != "keyboard":
            return True

        if not key_name:
            return True
        self._commit_capture(key_name)
        return True

    def _save_input(self):
        console_id = self._current_console()
        device_id = self._current_device()
        # Read the profile back rather than trusting the snapshot taken when
        # the bindings were last refreshed. The analog-stick and turbo rows
        # write straight to disk as they change, so saving a binding from a
        # stale snapshot silently reverted whichever of them was touched
        # first -- change the stick row, press Save, lose the choice (#126).
        profile = self.config.get_input_profile(console_id)
        devices = profile.setdefault("devices", {})
        device = devices.setdefault(
            device_id,
            {"type": device_type_for(device_id), "bindings": {}},
        )
        valid_actions = get_actions_for_console(console_id)
        existing = device.get("bindings") or {}
        device["bindings"] = {
            a: self._bindings_buffer.get(a, existing.get(a, "")) for a in valid_actions
        }
        if device_id in EXTRA_PORT_DEVICE_IDS:
            # Ports 2-4 are opt-in and never take over player 1.
            device["enabled"] = self._port_enabled_switch.get_active()
        else:
            profile["active_device"] = device_id
        self.config.save_input_profile(console_id, profile)
        # Read the rows back from what was actually stored. The buffer is what
        # the user asked for; the profile is what the store kept, and the two
        # used to be allowed to disagree silently until the dialog was
        # reopened (issue #281).
        self._refresh_bindings()
        self._toast(self.t("toast.input_saved", console=console_id))
        # A remap saved mid-game reaches the running game through the
        # state-carrying relaunch (#129) -- but only when the profile being
        # edited is the running console's; saving the SNES bindings must not
        # restart a Game Boy session that never reads them.
        self._apply_to_running_game_if_relevant(console_id)
        # A game may have started (or ended) since the page was built.
        self._sync_relaunch_banner()

    def _reset_defaults(self):
        console_id = self._current_console()
        profile = self.config.reset_input_profile(console_id)
        self._loaded_profile = profile
        self._cancel_capture()
        self._refresh_bindings()
        self._toast(self.t("toast.input_reset", console=console_id))
        # A reset writes the profile just like Save does (#129).
        self._apply_to_running_game_if_relevant(console_id)

    def _apply_to_running_game_if_relevant(self, console_id):
        """Push a just-written profile into the running game, if it uses it."""
        manager = self.win.runtime_manager
        if not manager.is_running():
            return
        active = (manager.active_rom or {}).get("console")
        if active and resolve_system_id(active) == resolve_system_id(console_id):
            self.win.apply_input_changes_to_running_game()

    # ----- Video / Shaders page ------------------------------------------
    def _build_video_page(self):
        page = Adw.PreferencesPage(
            title=self.t("prefs.page.video"), icon_name="applications-graphics-symbolic"
        )

        page.add(self._build_game_window_group())

        appearance = Adw.PreferencesGroup(title=self.t("prefs.group.appearance"))
        # The cartridge frame is one of the view modes now, so this row mirrors
        # the header's switcher rather than owning a switch of its own.
        self._view_modes = list(VIEW_MODES)
        self._view_mode_combo = Adw.ComboRow(
            title=self.t("settings.ui.view_mode.title"),
            subtitle=self.t("settings.ui.view_mode.subtitle"),
        )
        self._view_mode_combo.set_model(
            Gtk.StringList.new([self.t(f"view_mode.{mode}") for mode in self._view_modes])
        )
        current_mode = self.config.get_ui_settings()["view_mode"]
        self._view_mode_combo.set_selected(
            self._view_modes.index(current_mode) if current_mode in self._view_modes else 0
        )
        self._view_mode_combo.connect("notify::selected", self._on_view_mode_changed)
        appearance.add(self._view_mode_combo)

        self._sort_orders = list(SORT_ORDERS)
        self._sort_combo = Adw.ComboRow(
            title=self.t("settings.ui.sort_order.title"),
            subtitle=self.t("settings.ui.sort_order.subtitle"),
        )
        self._sort_combo.set_model(
            Gtk.StringList.new([self.t(f"sort_order.{order}") for order in self._sort_orders])
        )
        current_order = self.config.get_ui_settings()["sort_order"]
        self._sort_combo.set_selected(
            self._sort_orders.index(current_order) if current_order in self._sort_orders else 0
        )
        self._sort_combo.connect("notify::selected", self._on_sort_order_changed)
        appearance.add(self._sort_combo)

        self._show_all_switch = Adw.SwitchRow(title=self.t("settings.shaders.show_all"))
        self._show_all_switch.set_active(
            self.config.get_shader_settings().get("show_all_shaders", False)
        )
        self._show_all_switch.connect("notify::active", self._on_show_all_toggled)
        appearance.add(self._show_all_switch)

        restore_row = Adw.ActionRow(title=self.t("settings.shaders.restore_defaults"))
        restore_row.set_activatable(True)
        restore_row.add_prefix(Gtk.Image.new_from_icon_name("edit-undo-symbolic"))
        restore_row.connect("activated", lambda _r: self._restore_shader_defaults())
        appearance.add(restore_row)
        page.add(appearance)

        self._shaders_group = Adw.PreferencesGroup(title=self.t("prefs.group.shaders"))
        page.add(self._shaders_group)
        self._shader_rows = []
        self._rebuild_shader_rows()
        return page

    def _build_game_window_group(self):
        """Play inside an OpenEmux window, or leave RetroArch its own (#199).

        Sits at the top of the Video page: it decides what the user looks at
        while playing, which outranks the cover-grid appearance below it.
        """
        group = Adw.PreferencesGroup(title=self.t("prefs.group.game_window"))
        self._game_window_row = Adw.SwitchRow(
            title=self.t("prefs.game_window.title"),
            subtitle=self.t("prefs.game_window.subtitle"),
        )
        self._game_window_row.set_active(self.config.get_game_window_enabled())
        if game_window_support.embedding_possible():
            self._game_window_row.connect("notify::active", self._on_game_window_toggled)
        else:
            # Nothing to offer here: no python-xlib, or a session with no X
            # display at all (a Wayland session without XWayland, the Flatpak
            # sandbox on Wayland). The row stays visible and says why, rather
            # than silently disappearing on some machines.
            self._game_window_row.set_sensitive(False)
            self._game_window_row.set_subtitle(self.t("prefs.game_window.unavailable"))
        group.add(self._game_window_row)
        return group

    def _on_game_window_toggled(self, row, _param):
        enabled = row.get_active()
        self.config.set_game_window_enabled(enabled)
        from openemux.ui.game_window import display_supports_embedding

        if enabled and (
            not display_supports_embedding()
            or game_window_support.embed_unavailable_reason()
        ):
            # The X11 backend is chosen before GTK starts, so a session that
            # booted with the setting off is on Wayland for good: the next
            # game would still open in RetroArch's own window. The same is
            # true after an embed has failed once -- the session is latched
            # standalone, and switching this back on silently would promise
            # something this run cannot deliver (issue #267).
            self._toast(self.t("toast.game_window.restart"), timeout=6)

    def _shader_options_for_console(self, console_id):
        show_all = bool(self._show_all_switch.get_active())
        selected = normalize_shader_id(self.config.get_shader_for_console(console_id))
        options = self.win.shader_catalog.get_options(show_all=show_all)
        option_ids = [sid for sid, _label in options]
        if selected not in option_ids:
            options.append((selected, self.win.shader_catalog.label_for_shader(selected)))
        return options, selected

    def _rebuild_shader_rows(self):
        for row in getattr(self, "_shader_rows", []):
            self._shaders_group.remove(row)
        self._shader_rows = []

        for console_id in SYSTEM_IDS:
            options, selected = self._shader_options_for_console(console_id)
            ids = [sid for sid, _label in options]
            labels = [label for _sid, label in options]
            row = Adw.ComboRow(
                title=f"{console_id} — {get_system_display_name(console_id)}"
            )
            # The row names a console, so show its icon here too.
            row.add_prefix(self.win._build_console_icon(console_id))
            row.set_model(Gtk.StringList.new(labels))
            row.set_selected(ids.index(selected) if selected in ids else 0)
            row._shader_ids = ids
            row.connect("notify::selected", self._on_shader_changed, console_id)
            self._shaders_group.add(row)
            self._shader_rows.append(row)

    def _on_shader_changed(self, row, _param, console_id):
        ids = getattr(row, "_shader_ids", [])
        idx = row.get_selected()
        if 0 <= idx < len(ids):
            self.config.set_shader_for_console(console_id, normalize_shader_id(ids[idx]))

    def _on_show_all_toggled(self, switch, _param):
        self.config.set_show_all_shaders(switch.get_active())
        self._rebuild_shader_rows()

    def _restore_shader_defaults(self):
        self.config.reset_shader_defaults()
        self._rebuild_shader_rows()
        self._toast(self.t("toast.shaders.defaults_restored"))

    def _on_view_mode_changed(self, *_a):
        index = self._view_mode_combo.get_selected()
        if 0 <= index < len(self._view_modes):
            self.win._apply_view_mode(self._view_modes[index])

    def _on_sort_order_changed(self, *_a):
        index = self._sort_combo.get_selected()
        if 0 <= index < len(self._sort_orders):
            self.win._apply_sort_order(self._sort_orders[index])

    # ----- Cores page -----------------------------------------------------
    def _build_cores_page(self):
        page = Adw.PreferencesPage(
            title=self.t("prefs.page.cores"), icon_name="application-x-executable-symbolic"
        )
        group = Adw.PreferencesGroup(
            title=self.t("prefs.group.cores"),
            description=self.t("prefs.group.cores.description"),
        )
        page.add(group)

        for console_id in SYSTEM_IDS:
            cores = self.win.core_catalog.cores_for_console(console_id)
            title = f"{console_id} — {get_system_display_name(console_id)}"
            if not cores:
                # Nothing installed: say so rather than offer an empty picker.
                row = Adw.ActionRow(title=title, subtitle=self.t("settings.cores.none"))
                row.add_prefix(self.win._build_console_icon(console_id))
                row.set_sensitive(False)
                group.add(row)
                continue

            auto_label = cores[0].display_name
            filenames = [None] + [core.filename for core in cores]
            labels = [self.t("settings.cores.automatic", core=auto_label)]
            labels += [core.display_name for core in cores]

            row = Adw.ComboRow(
                title=title,
                subtitle=self.t("settings.cores.auto_resolves", core=auto_label),
            )
            row.add_prefix(self.win._build_console_icon(console_id))
            row.set_model(Gtk.StringList.new(labels))
            override = self.config.get_console_core_override(console_id)
            row.set_selected(filenames.index(override) if override in filenames else 0)
            row._core_filenames = filenames
            row.connect("notify::selected", self._on_core_changed, console_id)
            group.add(row)
        return page

    def _on_core_changed(self, row, _param, console_id):
        filenames = getattr(row, "_core_filenames", [])
        idx = row.get_selected()
        if not (0 <= idx < len(filenames)):
            return
        chosen = filenames[idx]
        self.config.set_console_core_override(console_id, chosen)
        if chosen:
            self.win._warn_missing_bios_for_core(console_id, chosen)

    # ----- System page ----------------------------------------------------
    def _build_system_page(self):
        page = Adw.PreferencesPage(
            title=self.t("prefs.page.system"), icon_name="applications-system-symbolic"
        )

        lang_group = Adw.PreferencesGroup(title=self.t("prefs.group.language"))
        self._locale_ids = list(SUPPORTED_LOCALES)
        self._language_combo = Adw.ComboRow(
            title=self.t("settings.system.language.title"),
            subtitle=self.t("settings.system.language.subtitle"),
        )
        self._language_combo.set_model(
            Gtk.StringList.new(
                [
                    f"{LANGUAGE_META.get(l, LANGUAGE_META['en'])['flag']} "
                    f"{LANGUAGE_META.get(l, LANGUAGE_META['en'])['native_name']}"
                    for l in self._locale_ids
                ]
            )
        )
        current = normalize_locale(self.win.locale)
        self._language_combo.set_selected(
            self._locale_ids.index(current) if current in self._locale_ids else 0
        )
        self._language_combo.connect("notify::selected", self._on_language_changed)
        lang_group.add(self._language_combo)
        page.add(lang_group)

        interface_group = Adw.PreferencesGroup(title=self.t("prefs.group.interface"))

        # First row of the group: it is the setting that changes the most on
        # screen. "System" is the default and keeps following the desktop --
        # the header's toggle only ever picks light or dark.
        self._themes = list(THEMES)
        self._theme_combo = Adw.ComboRow(
            title=self.t("settings.system.theme.title"),
            subtitle=self.t("settings.system.theme.subtitle"),
        )
        self._theme_combo.set_model(
            Gtk.StringList.new([self.t(f"theme.{name}") for name in self._themes])
        )
        current_theme = self.config.get_ui_settings()["theme"]
        self._theme_combo.set_selected(self._themes.index(current_theme))
        self._theme_combo.connect("notify::selected", self._on_theme_changed)
        interface_group.add(self._theme_combo)

        self._tips_row = Adw.SwitchRow(
            title=self.t("settings.system.tips.title"),
            subtitle=self.t("settings.system.tips.subtitle"),
        )
        self._tips_row.set_active(self.config.get_ui_settings()["show_tips"])
        self._tips_row.connect("notify::active", self._on_show_tips_changed)
        interface_group.add(self._tips_row)

        self._gamepad_nav_row = Adw.SwitchRow(
            title=self.t("settings.system.gamepad_nav.title"),
            subtitle=self.t("settings.system.gamepad_nav.subtitle"),
        )
        self._gamepad_nav_row.set_active(self.config.get_ui_settings()["gamepad_navigation"])
        self._gamepad_nav_row.connect("notify::active", self._on_gamepad_nav_changed)
        interface_group.add(self._gamepad_nav_row)
        page.add(interface_group)

        welcome_group = Adw.PreferencesGroup(title=self.t("prefs.group.welcome"))
        self._welcome_startup_row = Adw.SwitchRow(
            title=self.t("settings.system.welcome.startup.title"),
            subtitle=self.t("settings.system.welcome.startup.subtitle"),
        )
        self._welcome_startup_row.set_active(self.config.get_show_welcome_on_startup())
        self._welcome_startup_row.connect("notify::active", self._on_welcome_startup_changed)
        welcome_group.add(self._welcome_startup_row)

        open_welcome_row = Adw.ActionRow(
            title=self.t("settings.system.welcome.open.title"),
            subtitle=self.t("settings.system.welcome.open.subtitle"),
        )
        open_welcome_row.set_activatable(True)
        open_welcome_row.add_prefix(Gtk.Image.new_from_icon_name("start-here-symbolic"))
        open_welcome_row.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
        open_welcome_row.connect("activated", self._on_open_welcome)
        welcome_group.add(open_welcome_row)
        page.add(welcome_group)

        saves_group = Adw.PreferencesGroup(title=self.t("prefs.group.saves"))
        export_row = Adw.ActionRow(
            title=self.t("settings.system.saves.export.title"),
            subtitle=self.t("settings.system.saves.export.subtitle"),
        )
        export_row.set_activatable(True)
        export_row.add_prefix(Gtk.Image.new_from_icon_name("media-floppy-symbolic"))
        export_row.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
        export_row.connect("activated", self._on_export_saves)
        saves_group.add(export_row)

        import_row = Adw.ActionRow(
            title=self.t("settings.system.saves.import.title"),
            subtitle=self.t("settings.system.saves.import.subtitle"),
        )
        import_row.set_activatable(True)
        import_row.add_prefix(Gtk.Image.new_from_icon_name("folder-download-symbolic"))
        import_row.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
        import_row.connect("activated", self._on_import_saves)
        saves_group.add(import_row)
        page.add(saves_group)

        setup_group = Adw.PreferencesGroup(title=self.t("prefs.group.setup"))
        state = self.config.get_bootstrap_state()
        status = state.get("status", "pending")
        failed_step = state.get("failed_step")
        if status == "completed":
            subtitle = self.t("settings.system.bootstrap.ok")
        elif status == "failed":
            subtitle = self.t("settings.system.bootstrap.failed", step=failed_step or "-")
        else:
            subtitle = self.t("settings.system.bootstrap.pending")
        status_row = Adw.ActionRow(
            title=self.t("settings.system.bootstrap.title"), subtitle=subtitle
        )
        icon_name = {
            "completed": "emblem-ok-symbolic",
            "failed": "dialog-warning-symbolic",
        }.get(status, "content-loading-symbolic")
        status_row.add_prefix(Gtk.Image.new_from_icon_name(icon_name))
        setup_group.add(status_row)

        retry_row = Adw.ActionRow(
            title=self.t("settings.system.bootstrap.retry.title"),
            subtitle=self.t("settings.system.bootstrap.retry.subtitle"),
        )
        retry_row.set_activatable(True)
        retry_row.add_prefix(Gtk.Image.new_from_icon_name("view-refresh-symbolic"))
        retry_row.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
        retry_row.connect("activated", lambda _r: self.win._trigger_bootstrap_retry())
        setup_group.add(retry_row)
        page.add(setup_group)
        return page

    # ----- saves backup (issue #293) --------------------------------------
    def _saves_filter(self):
        zip_filter = Gtk.FileFilter()
        zip_filter.set_name(self.t("saves.dialog.filter"))
        zip_filter.add_pattern("*.zip")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(zip_filter)
        return filters, zip_filter

    def _on_export_saves(self, _row):
        dialog = Gtk.FileDialog()
        dialog.set_title(self.t("saves.export.dialog.title"))
        dialog.set_modal(True)
        dialog.set_initial_name(save_backup.default_backup_name())
        filters, default = self._saves_filter()
        dialog.set_filters(filters)
        dialog.set_default_filter(default)
        dialog.save(self, None, self._on_export_target_chosen)

    def _on_export_target_chosen(self, dialog, result):
        try:
            target = dialog.save_finish(result)
        except GLib.Error:
            return  # dismissed
        if target is None or not target.get_path():
            return
        save_backup.export_saves_async(
            target.get_path(),
            self.config.get_states_dir(),
            self.config.get_roms_path(),
            on_done=lambda summary: GLib.idle_add(self._on_export_done, summary),
        )

    def _on_export_done(self, summary):
        if summary.get("error"):
            self._toast(self.t("toast.saves.failed", error=summary["error"]))
            return False
        self._toast(
            self.t(
                "toast.saves.exported",
                states=summary.get("states", 0),
                saves=summary.get("saves", 0),
            )
        )
        return False

    def _on_import_saves(self, _row):
        dialog = Gtk.FileDialog()
        dialog.set_title(self.t("saves.import.dialog.title"))
        dialog.set_modal(True)
        filters, default = self._saves_filter()
        dialog.set_filters(filters)
        dialog.set_default_filter(default)
        dialog.open(self, None, self._on_import_source_chosen)

    def _on_import_source_chosen(self, dialog, result):
        try:
            source = dialog.open_finish(result)
        except GLib.Error:
            return  # dismissed
        if source is None or not source.get_path():
            return
        save_backup.import_saves_async(
            source.get_path(),
            self.config.get_states_dir(),
            self.config.get_roms_path(),
            on_done=lambda outcome: GLib.idle_add(self._on_import_done, outcome),
        )

    def _on_import_done(self, outcome):
        errors = outcome.get("errors") or []
        if errors and not outcome.get("restored"):
            self._toast(self.t("toast.saves.failed", error=errors[0]["error"]))
            return False
        self._toast(
            self.t(
                "toast.saves.imported",
                restored=outcome.get("restored", 0),
                skipped=outcome.get("skipped", 0),
            )
        )
        return False

    def _on_theme_changed(self, row, *_a):
        idx = row.get_selected()
        if not (0 <= idx < len(self._themes)):
            return
        theme = self.config.set_theme(self._themes[idx])
        theming.apply_theme(theme)
        # "System" that lands on the same appearance emits no notify::dark,
        # so the header icon is refreshed here rather than left to that.
        self.win._sync_theme_button()

    def _on_show_tips_changed(self, row, *_a):
        enabled = row.get_active()
        self.config.set_show_tips(enabled)
        self.win._apply_tips_visibility(enabled)

    def _on_gamepad_nav_changed(self, row, *_a):
        self.win._apply_gamepad_navigation(row.get_active())

    def _on_welcome_startup_changed(self, row, *_a):
        self.config.set_show_welcome_on_startup(row.get_active())

    def _on_open_welcome(self, _row):
        # Close Preferences first so the assistant is not stacked over it.
        self.close()
        self.win._open_welcome()

    def _on_language_changed(self, *_a):
        idx = self._language_combo.get_selected()
        if idx < 0 or idx >= len(self._locale_ids):
            return
        selected = normalize_locale(self._locale_ids[idx])
        if selected == self.win.locale:
            return
        self.win._apply_language_change(selected)
        # Rebuild the dialog so its own labels follow the new locale.
        GLib.idle_add(self._reopen_after_language)

    def _reopen_after_language(self):
        self.close()
        self.win._open_preferences()
        return False

    def refresh_roms_path(self):
        if hasattr(self, "_roms_path_row"):
            self._roms_path_row.set_subtitle(str(self.config.get_roms_path()))
