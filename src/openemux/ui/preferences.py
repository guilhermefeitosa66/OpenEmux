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
from gi.repository import Adw, Gtk, Gdk, GLib, Pango

from openemux.core.config import (
    COVER_ART_TYPES,
    COVER_SOURCE_LIBRETRO_THEN_SCREENSCRAPER,
    COVER_SOURCE_SCREENSCRAPER,
    COVER_SOURCES,
    normalize_cover_art_type,
    normalize_cover_source,
)
from openemux.core.gamepad_reader import GamepadCaptureReader, describe_token, list_gamepads
from openemux.core.input_actions import (
    ACTION_ORDER,
    GLOBAL_HOTKEY_ACTIONS,
    get_actions_for_console,
)
from openemux.core.input_profiles import (
    DEVICE_IDS,
    EXTRA_PORT_DEVICE_IDS,
    device_type_for,
    player_for_device,
)
from openemux.core.shaders import normalize_shader_id
from openemux.core.systems import SYSTEM_IDS, get_system_display_name
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

        # Never leave a reader thread behind when the dialog goes away.
        self.connect("closed", lambda _d: self._stop_gamepad_reader())

        self.add(self._build_library_page())
        self.add(self._build_bios_page())
        self.add(self._build_input_page())
        self.add(self._build_video_page())
        self.add(self._build_system_page())

    # ----- shared helpers -------------------------------------------------
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
        page.add(self._build_cover_source_group())
        return page

    # ----- Cover sources --------------------------------------------------
    def _build_cover_source_group(self):
        """Cover art source selection (libretro / ScreenScraper).

        ScreenScraper needs the user's own credentials, so its rows only appear
        once a ScreenScraper-backed source is picked.
        """
        settings = self.config.get_cover_sync_settings()

        group = Adw.PreferencesGroup(
            title=self.t("prefs.group.cover_source"),
            description=self.t("prefs.cover_source.description"),
        )

        self._cover_source_ids = list(COVER_SOURCES)
        source_model = Gtk.StringList()
        for source_id in self._cover_source_ids:
            source_model.append(self.t(f"prefs.cover_source.option.{source_id}"))
        self._cover_source_row = Adw.ComboRow(
            title=self.t("prefs.cover_source.title"),
            subtitle=self.t("prefs.cover_source.subtitle"),
            model=source_model,
        )
        self._cover_source_row.set_selected(
            self._cover_source_ids.index(normalize_cover_source(settings.get("cover_source")))
        )
        # Without a wrapping factory the longest option is ellipsized to fit the
        # row width, which hides which sources are actually in play.
        self._apply_wrapping_label_factory(self._cover_source_row)
        self._cover_source_row.connect("notify::selected", self._on_cover_source_changed)
        group.add(self._cover_source_row)

        self._cover_art_type_ids = list(COVER_ART_TYPES)
        art_model = Gtk.StringList()
        for art_id in self._cover_art_type_ids:
            art_model.append(self.t(f"prefs.cover_art_type.option.{art_id}"))
        self._cover_art_type_row = Adw.ComboRow(
            title=self.t("prefs.cover_art_type.title"),
            subtitle=self.t("prefs.cover_art_type.subtitle"),
            model=art_model,
        )
        self._cover_art_type_row.set_selected(
            self._cover_art_type_ids.index(normalize_cover_art_type(settings.get("cover_art_type")))
        )
        self._cover_art_type_row.connect("notify::selected", self._on_cover_art_type_changed)
        group.add(self._cover_art_type_row)

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

        self._ss_devid_row = Adw.EntryRow(title=self.t("prefs.screenscraper.devid"))
        self._ss_devid_row.set_text(settings.get("screenscraper_devid", ""))
        self._ss_devid_row.connect(
            "changed",
            lambda row: self.config.set_cover_sync_setting("screenscraper_devid", row.get_text()),
        )
        group.add(self._ss_devid_row)

        self._ss_devpassword_row = Adw.PasswordEntryRow(
            title=self.t("prefs.screenscraper.devpassword")
        )
        self._ss_devpassword_row.set_text(settings.get("screenscraper_devpassword", ""))
        self._ss_devpassword_row.connect(
            "changed",
            lambda row: self.config.set_cover_sync_setting("screenscraper_devpassword", row.get_text()),
        )
        group.add(self._ss_devpassword_row)

        self._ss_hint_row = Adw.ActionRow(
            title=self.t("prefs.screenscraper.hint.title"),
            subtitle=self.t("prefs.screenscraper.hint.subtitle"),
        )
        self._ss_hint_row.set_subtitle_lines(0)
        group.add(self._ss_hint_row)

        self._update_screenscraper_rows_visibility()
        return group

    def _selected_cover_source(self):
        return self._cover_source_ids[self._cover_source_row.get_selected()]

    def _update_screenscraper_rows_visibility(self):
        uses_screenscraper = self._selected_cover_source() in (
            COVER_SOURCE_LIBRETRO_THEN_SCREENSCRAPER,
            COVER_SOURCE_SCREENSCRAPER,
        )
        for row in (
            self._cover_art_type_row,
            self._ss_user_row,
            self._ss_password_row,
            self._ss_devid_row,
            self._ss_devpassword_row,
            self._ss_hint_row,
        ):
            row.set_visible(uses_screenscraper)

    def _on_cover_source_changed(self, *_args):
        self.config.set_cover_sync_setting("cover_source", self._selected_cover_source())
        self._update_screenscraper_rows_visibility()

    def _on_cover_art_type_changed(self, *_args):
        self.config.set_cover_sync_setting(
            "cover_art_type", self._cover_art_type_ids[self._cover_art_type_row.get_selected()]
        )

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

    def _apply_wrapping_label_factory(self, combo_row):
        """Let a ComboRow's options wrap instead of being cut off.

        Adwaita ellipsizes the selected item to the row width, so a long option
        ("libretro thumbnails, then ScreenScraper") reads as truncated text.
        """

        def _setup(_factory, list_item):
            label = Gtk.Label()
            label.set_wrap(True)
            label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
            label.set_max_width_chars(28)
            label.set_halign(Gtk.Align.START)
            label.set_xalign(0)
            list_item.set_child(label)

        def _bind(_factory, list_item):
            item = list_item.get_item()
            list_item.get_child().set_text(item.get_string() if item else "")

        for setter in (combo_row.set_factory, combo_row.set_list_factory):
            factory = Gtk.SignalListItemFactory()
            factory.connect("setup", _setup)
            factory.connect("bind", _bind)
            setter(factory)

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
        self._device_combo = Adw.ComboRow(title=self.t("input.device"))
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
        page.add(controller_group)

        self._bindings_group = Adw.PreferencesGroup(title=self.t("prefs.group.bindings"))
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

        self._refresh_bindings()
        return page

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

    def _on_console_changed(self, *_a):
        self._cancel_capture()
        self._refresh_bindings()

    def _on_device_changed(self, *_a):
        self._cancel_capture()
        self._refresh_bindings()

    def _input_action_label(self, action):
        return self.t(f"input.action.{action}")

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

    def _refresh_bindings(self):
        for row in list(self._input_rows.values()):
            self._bindings_group.remove(row)
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
        self._capture_sequence_actions = list(visible_actions)
        self._bindings_buffer = {
            action: str(bindings.get(action, "")).strip().lower() for action in visible_actions
        }
        is_extra_port = device_id in EXTRA_PORT_DEVICE_IDS
        self._port_enabled_switch.set_visible(is_extra_port)
        if is_extra_port:
            self._port_enabled_switch.set_active(bool(device.get("enabled", False)))
        self._map_all_btn.set_sensitive(True)
        self._bindings_group.set_description(None)

        for action in visible_actions:
            row = Adw.ActionRow(title=self._input_action_label(action))
            button = Gtk.Button(label=self._binding_display(self._bindings_buffer.get(action, "")))
            button.set_valign(Gtk.Align.CENTER)
            button.set_size_request(150, -1)
            button.connect("clicked", self._on_binding_clicked, action)
            row.add_suffix(button)
            row.set_activatable_widget(button)
            self._bindings_group.add(row)
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
        self._bindings_group.set_description(prompt)

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

    def _cancel_capture(self, show_toast=False):
        self._stop_gamepad_reader()
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
            self._bindings_group.set_description(None)
        if show_toast and was_sequence:
            self._toast(self.t("input.capture.cancelled"))

    def _start_map_all(self):
        if not self._capture_sequence_actions:
            return
        self._cancel_capture()
        self._capture_sequence_mode = True
        self._capture_sequence_index = 0
        self._start_capture(self._capture_sequence_actions[0], sequence_mode=True)

    def _set_binding(self, action, value):
        value = (value or "").strip().lower()
        if value:
            for other_action, other_value in list(self._bindings_buffer.items()):
                if other_action == action:
                    continue
                if other_value == value:
                    self._bindings_buffer[other_action] = ""
                    if other_action in self._input_buttons:
                        self._input_buttons[other_action].set_label(self._binding_display(""))
        self._bindings_buffer[action] = value
        if action in self._input_buttons:
            self._input_buttons[action].set_label(self._binding_display(value))

    @staticmethod
    def _normalize_key(keyval):
        key_name = Gdk.keyval_name(keyval)
        if not key_name:
            return ""
        special = {
            "Return": "enter", "KP_Enter": "enter", "Escape": "escape", "space": "space",
            "Up": "up", "Down": "down", "Left": "left", "Right": "right",
            "Shift_L": "left shift", "Shift_R": "right shift",
            "Control_L": "left ctrl", "Control_R": "right ctrl",
            "Alt_L": "left alt", "Alt_R": "right alt",
            "Super_L": "left super", "Super_R": "right super",
        }
        if key_name in special:
            return special[key_name]
        return key_name.lower()

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
        profile = self._loaded_profile or self.config.get_input_profile(console_id)
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
        self._loaded_profile = profile
        self._toast(self.t("toast.input_saved", console=console_id))

    def _reset_defaults(self):
        console_id = self._current_console()
        profile = self.config.reset_input_profile(console_id)
        self._loaded_profile = profile
        self._cancel_capture()
        self._refresh_bindings()
        self._toast(self.t("toast.input_reset", console=console_id))

    # ----- Video / Shaders page ------------------------------------------
    def _build_video_page(self):
        page = Adw.PreferencesPage(
            title=self.t("prefs.page.video"), icon_name="applications-graphics-symbolic"
        )

        appearance = Adw.PreferencesGroup(title=self.t("prefs.group.appearance"))
        self._cartridge_switch = Adw.SwitchRow(
            title=self.t("settings.ui.render_cartridge.title"),
            subtitle=self.t("settings.ui.render_cartridge.subtitle"),
        )
        self._cartridge_switch.set_active(
            self.config.get_ui_settings().get("render_cartridge_overlay", False)
        )
        self._cartridge_switch.connect("notify::active", self._on_cartridge_toggled)
        appearance.add(self._cartridge_switch)

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

    def _on_cartridge_toggled(self, switch, _param):
        self.win._apply_render_cartridge(switch.get_active())

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

    def _on_show_tips_changed(self, row, *_a):
        enabled = row.get_active()
        self.config.set_show_tips(enabled)
        self.win._apply_tips_visibility(enabled)

    def _on_gamepad_nav_changed(self, row, *_a):
        self.win._apply_gamepad_navigation(row.get_active())

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
