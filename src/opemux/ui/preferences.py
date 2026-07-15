"""GNOME HIG-compliant preferences dialog for Opemux.

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
from gi.repository import Adw, Gtk, Gdk, GLib

from opemux.core.input_actions import ACTION_ORDER, get_actions_for_console
from opemux.core.shaders import normalize_shader_id
from opemux.core.systems import SYSTEM_IDS, get_system_display_name
from opemux.core.bios_manager import scan_all_bios_status
from opemux.i18n import LANGUAGE_META, SUPPORTED_LOCALES, normalize_locale


class OpemuxPreferences(Adw.PreferencesDialog):
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

        self._key_controller = Gtk.EventControllerKey()
        self._key_controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        self._key_controller.connect("key-pressed", self._on_key_pressed)
        self.add_controller(self._key_controller)

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
        return page

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

    # ----- Input page -----------------------------------------------------
    def _build_input_page(self):
        page = Adw.PreferencesPage(
            title=self.t("prefs.page.input"), icon_name="input-gaming-symbolic"
        )

        controller_group = Adw.PreferencesGroup(title=self.t("prefs.group.controller"))
        self._console_ids = list(SYSTEM_IDS)
        self._console_combo = Adw.ComboRow(title=self.t("input.console"))
        self._console_combo.set_model(
            Gtk.StringList.new(
                [f"{cid} — {get_system_display_name(cid)}" for cid in self._console_ids]
            )
        )
        default_console = (
            self.win.current_console
            if self.win.current_console in self._console_ids
            else self._console_ids[0]
        )
        self._console_combo.set_selected(self._console_ids.index(default_console))
        self._console_combo.connect("notify::selected", self._on_console_changed)
        controller_group.add(self._console_combo)

        self._device_ids = ["keyboard", "gamepad_p1"]
        self._device_combo = Adw.ComboRow(title=self.t("input.device"))
        self._device_combo.set_model(
            Gtk.StringList.new(
                [self.t("input.device.keyboard"), self.t("input.device.gamepad_p1")]
            )
        )
        self._device_combo.set_selected(0)
        self._device_combo.connect("notify::selected", self._on_device_changed)
        controller_group.add(self._device_combo)
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
        return value if value else self.t("input.binding.empty")

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

        self._loaded_profile = profile
        self._visible_actions = list(visible_actions)
        self._capture_sequence_actions = list(visible_actions)
        self._bindings_buffer = {
            action: str(bindings.get(action, "")).strip().lower() for action in visible_actions
        }
        self._map_all_btn.set_sensitive(device_id == "keyboard")
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
        if self._current_device() != "keyboard":
            self._toast(self.t("input.capture.keyboard_only"))
            return
        self._start_capture(action, sequence_mode=False)

    def _start_capture(self, action, sequence_mode):
        if action not in self._input_buttons:
            return
        self._capture_active_action = action
        self._capture_sequence_mode = sequence_mode
        self._input_buttons[action].set_label(self.t("input.capture.waiting"))
        self._set_active_row(action)
        self._bindings_group.set_description(
            self.t("input.capture.waiting_for", action=self._input_action_label(action))
        )

    def _cancel_capture(self, show_toast=False):
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
        if self._current_device() != "keyboard":
            self._toast(self.t("input.capture.keyboard_only"))
            return
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

    def _on_key_pressed(self, _controller, keyval, _keycode, _state):
        if not self._capture_active_action:
            return False
        if self._current_device() != "keyboard":
            return False
        key_name = self._normalize_key(keyval)
        action = self._capture_active_action
        if key_name == "escape":
            if self._capture_sequence_mode:
                self._cancel_capture(show_toast=True)
            else:
                self._set_binding(action, "")
                self._cancel_capture()
            return True
        if not key_name:
            return True
        self._set_binding(action, key_name)
        if not self._capture_sequence_mode:
            self._cancel_capture()
            return True
        self._capture_sequence_index += 1
        if self._capture_sequence_index >= len(self._capture_sequence_actions):
            self._cancel_capture()
            self._toast(self.t("input.capture.completed"))
            return True
        next_action = self._capture_sequence_actions[self._capture_sequence_index]
        self._start_capture(next_action, sequence_mode=True)
        return True

    def _save_input(self):
        console_id = self._current_console()
        device_id = self._current_device()
        profile = self._loaded_profile or self.config.get_input_profile(console_id)
        devices = profile.setdefault("devices", {})
        device = devices.setdefault(
            device_id,
            {"type": "keyboard" if device_id == "keyboard" else "gamepad", "bindings": {}},
        )
        valid_actions = get_actions_for_console(console_id)
        device["bindings"] = {a: self._bindings_buffer.get(a, "") for a in valid_actions}
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
