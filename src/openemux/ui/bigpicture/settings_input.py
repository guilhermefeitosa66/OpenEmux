"""The Input section of Big Picture's Settings: the controller page, for a pad.

The desktop's Input page (``ui/preferences.py``) as rows a D-pad walks: the
console and the device being edited, the stick and turbo tuning, the
console's controller drawn with a focusable target over every button, and
one row per action with its binding at the end. The config calls and the
rules are the desktop's -- the same profile store, the same collision rule,
nothing saved until Save -- so a mapping made on the couch is the one the
desktop shows afterwards.

What differs is the capture. A pad cannot click a "Press button..." label,
so a capture here takes the whole section: a scrim with a card saying what
to press and a countdown, the UI navigator paused for the duration
(``win.set_input_capture_active``) and a key controller on the window, in
the capture phase, so no key reaches the page behind. Escape, the Guide
button and the countdown all cancel *without* clearing the binding --
clearing is an explicit answer on the row's chooser -- because on a pad the
way out of a capture must never double as the way to lose a mapping.
"""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gdk, GLib, Gtk, Pango

from openemux.core.controller_layouts import layout_for
from openemux.core.gamepad_backend import list_gamepads, make_capture_reader, make_held_reader
from openemux.core.gamepad_reader import describe_token
from openemux.core.input_actions import (
    ACTION_ORDER,
    GLOBAL_HOTKEY_ACTIONS,
    OPTIONAL_ACTIONS,
    get_actions_for_console,
    retroarch_key_token,
)
from openemux.core.input_capture import InputCaptureSession
from openemux.core.input_held import HeldKeys, key_token, lit_actions
from openemux.core.input_profiles import (
    ANALOG_DPAD_MODES,
    DEVICE_IDS,
    EXTRA_PORT_DEVICE_IDS,
    TURBO_DUTY_RANGE,
    TURBO_MODES,
    TURBO_PERIOD_RANGE,
    controller_types_for,
    device_type_for,
    player_for_device,
)
from openemux.core.input_tuning import INPUT_TUNING
from openemux.core.systems import SYSTEM_IDS, get_system_display_name, resolve_system_id
from openemux.ui.bigpicture.widgets import (
    ROW_ACTION,
    ROW_CHOICE,
    ROW_INFO,
    ROW_NUMBER,
    ROW_SWITCH,
    Row,
    eyebrow,
    note,
)
from openemux.ui.controller_drawing import ControllerDrawing

#: How long a capture waits for a press before it gives up, in seconds: long
#: enough to find a button on an unfamiliar pad, short enough that a capture
#: started by accident does not hold the interface for long.
CAPTURE_TIMEOUT = 8

#: The Guide/Home/PS button's token (``ui_gamepad.NAV_TOKEN_ACTIONS``). The
#: desktop binds it like any other; here it is the way out of a capture.
GUIDE_TOKEN = "8"

#: The global tuning rows: (setting, decimals shown, step per Left/Right).
TUNING_ROWS = (
    ("analog_deadzone", 2, 0.05),
    ("analog_sensitivity", 2, 0.05),
    ("axis_threshold", 2, 0.05),
    ("rumble_gain", 0, 5),
)

#: The controller-type chooser's "whatever the core boots with" entry, which
#: has no id of its own in the profile (it is stored as None).
CORE_DEFAULT = "default"

#: The answers of the chooser a bound action's row opens.
REMAP, CLEAR, KEEP = "remap", "clear", "keep"


class InputSection:
    """The Input section: ``widget`` is the whole view, ready to be appended.

    Built once by the Settings page and kept; ``refresh()`` rebuilds it from
    the store whenever the page comes back. Everything the desktop page does
    on a row is here under the same name, so a change to one can be checked
    against the other.
    """

    def __init__(self, shell, page):
        self.shell = shell
        self.page = page
        self.win = shell.win
        self.t = shell.t
        self.config = shell.win.config_manager
        self._console_ids = list(SYSTEM_IDS)
        self._device_ids = list(DEVICE_IDS)
        current = self.win.current_console
        self._console = current if current in self._console_ids else self._console_ids[0]
        self._device = "keyboard"
        self._controller_type_options = []
        # The bindings being edited and which action is listening: the same
        # widget-free machine the desktop drives (issue #238).
        self._capture = InputCaptureSession()
        self._capture.load({}, ACTION_ORDER)
        # What the store held when the rows were last built, for ``has_unsaved``.
        self._loaded_bindings = {}
        self._loaded_port_enabled = None
        self._binding_rows = {}
        self._gamepad_reader = None
        # What is held down right now, to light it on the drawing (issue 816).
        self._held_keys = HeldKeys()
        self._held_pad = frozenset()
        self._held_reader = None
        self._held_reader_port = None
        self._drawing = None
        self._drawing_console = None
        self._drawing_highlight = None
        self._controller_layouts = {}
        self._countdown_source = 0
        self._countdown_left = 0
        self._key_controller = None
        # Where the focus goes back to when the capture ends: the row or the
        # drawn button that started it, or the Map all row for a sequence.
        self._return_to = None
        self._build()
        self.refresh()

    # -- building ------------------------------------------------------------------
    def _build(self):
        t = self.t
        self.list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=28)

        # Bindings reach RetroArch only through the --appendconfig file written
        # at spawn, so a remap lands in a running game via the state-carrying
        # relaunch that Save triggers (issue #129). Shown only while there is
        # a game to relaunch.
        self.relaunch_row = Row(t("prefs.input.banner.running"), kind=ROW_INFO)
        self.list.append(self.relaunch_row)

        rows = self._group(t("prefs.group.controller"))
        self.console_row = Row(t("input.console"), kind=ROW_CHOICE, on_activate=self._pick_console)
        rows.append(self.console_row)
        # Picks which map is being edited, not which one is live: the
        # keyboard and player 1's pad are both always active (issue #150).
        self.device_row = Row(
            t("input.device"), t("input.device.subtitle"), kind=ROW_CHOICE,
            on_activate=self._pick_device,
        )
        rows.append(self.device_row)
        self.port_row = Row(
            t("input.port.enable"), t("input.port.enable.subtitle"), kind=ROW_SWITCH,
            on_activate=lambda _active: self._sync_save_row(),
        )
        rows.append(self.port_row)
        # Only where the console's core publishes more than one type (issue
        # #151); a chooser with a single entry is furniture.
        self.controller_type_row = Row(
            t("input.controller_type.title"), t("input.controller_type.subtitle"),
            kind=ROW_CHOICE, on_activate=self._pick_controller_type,
        )
        rows.append(self.controller_type_row)
        self.analog_dpad_row = Row(
            t("input.analog_dpad.title"), t("input.analog_dpad.subtitle"), kind=ROW_CHOICE,
            on_activate=self._pick_analog_dpad,
        )
        rows.append(self.analog_dpad_row)
        self.dpad_analog_row = Row(
            t("input.dpad_analog.title"), t("input.dpad_analog.subtitle"), kind=ROW_SWITCH,
            on_activate=self._on_dpad_analog_toggled,
        )
        rows.append(self.dpad_analog_row)

        # Global rather than per console (issues #154, #155): a worn stick
        # drifts the same on every system. These save as they change.
        rows = self._group(
            t("prefs.group.input_tuning"), t("prefs.group.input_tuning.description")
        )
        self.tuning_rows = {}
        for name, digits, step in TUNING_ROWS:
            row = Row(
                t(f"input.tuning.{name}"), t(f"input.tuning.{name}.subtitle"),
                kind=ROW_NUMBER, value="",
                on_step=lambda delta, name=name, digits=digits, step=step: self._step_tuning(
                    name, digits, step, delta
                ),
            )
            rows.append(row)
            self.tuning_rows[name] = row
        self.poll_row = Row(
            t("input.tuning.poll_type_behavior"), t("input.tuning.poll_type_behavior.subtitle"),
            kind=ROW_CHOICE, on_activate=self._pick_poll,
        )
        rows.append(self.poll_row)
        self.focus_row = Row(
            t("input.tuning.auto_game_focus"), t("input.tuning.auto_game_focus.subtitle"),
            kind=ROW_CHOICE, on_activate=self._pick_focus,
        )
        rows.append(self.focus_row)
        self.descriptor_row = Row(
            t("input.tuning.descriptor_label_show"),
            t("input.tuning.descriptor_label_show.subtitle"),
            kind=ROW_SWITCH,
            on_activate=lambda active: self.config.set_input_tuning_value(
                "descriptor_label_show", active
            ),
        )
        rows.append(self.descriptor_row)

        # Turbo timing (issue #72); the modifier itself is a binding row below.
        rows = self._group(t("prefs.group.turbo"), t("prefs.turbo.description"))
        self.turbo_period_row = Row(
            t("input.turbo.period"), t("input.turbo.period.subtitle"), kind=ROW_NUMBER, value="",
            on_step=lambda delta: self._step_turbo("period", TURBO_PERIOD_RANGE, delta),
        )
        rows.append(self.turbo_period_row)
        self.turbo_duty_row = Row(
            t("input.turbo.duty"), t("input.turbo.duty.subtitle"), kind=ROW_NUMBER, value="",
            on_step=lambda delta: self._step_turbo("duty_cycle", TURBO_DUTY_RANGE, delta),
        )
        rows.append(self.turbo_duty_row)
        self.turbo_mode_row = Row(
            t("input.turbo.mode"), kind=ROW_CHOICE, on_activate=self._pick_turbo_mode
        )
        rows.append(self.turbo_mode_row)

        # The console's controller, drawn (issue 815): a target over every
        # button, each a real button the pad can land on and press.
        self.drawing_group = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.drawing_group.append(eyebrow(t("prefs.group.controller_drawing")))
        self.drawing_group.append(note(t("big_picture.input.drawing.description")))
        self.drawing_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.drawing_card.add_css_class("card")
        self.drawing_card.add_css_class("controller-drawing-card")
        self.drawing_card.set_overflow(Gtk.Overflow.HIDDEN)
        self.drawing_group.append(self.drawing_card)
        self.drawing_caption = Gtk.Label()
        self.drawing_caption.add_css_class("bp-body")
        self.drawing_caption.set_wrap(True)
        self.drawing_caption.set_justify(Gtk.Justification.CENTER)
        self.drawing_group.append(self.drawing_caption)
        self.list.append(self.drawing_group)

        # The controls a game reads, then the frontend hotkeys: bound the same
        # way, but RetroArch treats the hotkeys as global, so ports 2-4 have
        # no System group at all.
        self.game_rows = self._group(t("prefs.group.bindings.game"))
        self.game_group = self.game_rows.get_parent()
        self.system_rows = self._group(
            t("prefs.group.bindings.system"), t("prefs.group.bindings.system.description")
        )
        self.system_group = self.system_rows.get_parent()

        rows = self._group(t("big_picture.input.tools"))
        self.map_all_row = Row(
            t("input.map_all"), t("big_picture.input.map_all.subtitle"), kind=ROW_ACTION,
            on_activate=self.start_map_all,
        )
        rows.append(self.map_all_row)
        self.reset_row = Row(
            t("input.reset"), t("big_picture.input.reset.subtitle"), kind=ROW_ACTION,
            destructive=True, on_activate=self.reset_defaults,
        )
        rows.append(self.reset_row)
        self.save_row = Row(
            t("input.save"), t("big_picture.input.save.subtitle"), kind=ROW_ACTION,
            primary=True, on_activate=self.save,
        )
        rows.append(self.save_row)

        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_vexpand(True)
        scroller.set_child(self.list)
        self.widget = Gtk.Overlay()
        self.widget.set_vexpand(True)
        self.widget.set_child(scroller)
        self._build_capture_card()
        self.widget.add_overlay(self.capture_card)

        # Keys over the section light the drawn button they are bound to
        # (issue 816); a key let go of elsewhere never reports its release.
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_key_pressed)
        keys.connect("key-released", self._on_key_released)
        self.widget.add_controller(keys)
        focus = Gtk.EventControllerFocus()
        focus.connect("leave", lambda _c: self._forget_held_keys())
        self.widget.add_controller(focus)
        # The pad is read for the drawing only while the section is on screen
        # in the window the user is in: every way in or out passes here.
        self.widget.connect("map", lambda _w: self._sync_held_reader())
        self.widget.connect("unmap", lambda _w: self._on_unmapped())
        self.win.connect("notify::is-active", lambda *_a: self._sync_held_reader())

    def _group(self, title, description=None):
        """A heading, an optional note and the box the rows go in (returned)."""
        group = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        group.append(eyebrow(title))
        if description:
            group.append(note(description))
        rows = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        group.append(rows)
        self.list.append(group)
        return rows

    def _build_capture_card(self):
        """The card over the section while a binding is being captured."""
        self.capture_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.capture_card.add_css_class("bp-scrim")
        self.capture_card.set_halign(Gtk.Align.FILL)
        self.capture_card.set_valign(Gtk.Align.FILL)
        self.capture_card.set_visible(False)
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        card.add_css_class("card")
        card.add_css_class("bp-dialog")
        card.set_halign(Gtk.Align.CENTER)
        card.set_valign(Gtk.Align.CENTER)
        card.set_vexpand(True)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        for side in ("top", "bottom", "start", "end"):
            getattr(content, f"set_margin_{side}")(40)
        self.capture_eyebrow = eyebrow("")
        content.append(self.capture_eyebrow)
        self.capture_heading = Gtk.Label(xalign=0.0)
        self.capture_heading.add_css_class("bp-dialog-heading")
        self.capture_heading.set_wrap(True)
        self.capture_heading.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self.capture_heading.set_max_width_chars(36)
        content.append(self.capture_heading)
        self.capture_countdown = Gtk.Label(xalign=0.0)
        self.capture_countdown.add_css_class("bp-title")
        content.append(self.capture_countdown)
        self.capture_note = note("")
        self.capture_note.set_max_width_chars(56)
        content.append(self.capture_note)
        card.append(content)
        self.capture_card.append(card)

    # -- the section's API ------------------------------------------------------------
    def refresh(self):
        """Rebuild every row from the store (the page is being shown again)."""
        self._cancel_capture()
        self._sync_console_rows()
        self._sync_tuning_rows()
        self._refresh_bindings()
        self._sync_relaunch_row()

    def focus_default(self):
        return self.console_row.grab_focus()

    def select_console(self, console_id):
        """Point the section at a console (a context menu's, the chooser's)."""
        if console_id not in self._console_ids or console_id == self._console:
            return
        self._console = console_id
        self._cancel_capture()
        self._sync_console_rows()
        self._refresh_bindings()

    def has_unsaved(self):
        """Bindings changed, or a port switched, and not saved yet."""
        if self._capture.bindings != self._loaded_bindings:
            return True
        return bool(
            self.port_row.get_visible() and self.port_row.get_active() != self._loaded_port_enabled
        )

    def confirm_leave(self, on_leave):
        """Run ``on_leave`` now, or after the user agrees to drop unsaved changes."""
        self._cancel_capture()
        if not self.has_unsaved():
            on_leave()
            return
        t = self.t
        self.shell.confirm(
            t("big_picture.input.leave.heading"),
            t("big_picture.input.leave.body"),
            t("big_picture.input.leave.discard"),
            on_leave,
        )

    @property
    def capturing(self):
        return self._capture.capturing

    def on_pad_action(self, action):
        """X maps every control in turn, Y resets the console; True when taken."""
        if action == "context":
            self.start_map_all()
            return True
        if action == "favorite":
            self.reset_defaults()
            return True
        return False

    def hints(self, glyphs, t):
        """The hint pairs while the focus is in this section."""
        return [
            (glyphs["confirm"], t("big_picture.hints.change")),
            (glyphs["context"], t("input.map_all")),
            (glyphs["favorite"], t("input.reset")),
            (glyphs["back"], t("hints.back")),
        ]

    # -- the console and device rows ---------------------------------------------
    def _toast(self, text, timeout=3):
        self.win._toast(text, timeout)

    def _open_chooser(self, title, options, current, on_pick, lead=None):
        """A full-page pick among ``(id, label)`` pairs, under the Settings crumbs."""
        t = self.t
        self.shell.open_chooser(
            title,
            [{"id": option_id, "label": label} for option_id, label in options],
            current,
            on_pick,
            crumbs=[t("menu.preferences"), t("prefs.page.input"), title],
            lead=lead,
        )

    def _console_label(self, console_id):
        return f"{console_id} — {get_system_display_name(console_id)}"

    def _pick_console(self):
        options = [(console, self._console_label(console)) for console in self._console_ids]
        self._open_chooser(self.t("input.console"), options, self._console, self.select_console)

    def _pick_device(self):
        options = [(device, self.t(f"input.device.{device}")) for device in self._device_ids]
        self._open_chooser(self.t("input.device"), options, self._device, self._on_device_picked)

    def _on_device_picked(self, device_id):
        if device_id not in self._device_ids or device_id == self._device:
            return
        self._device = device_id
        self._cancel_capture()
        self.device_row.set_value(self.t(f"input.device.{device_id}"))
        self._refresh_bindings()

    def _sync_console_rows(self):
        """The rows that describe the console being edited, from the store."""
        console = self._console
        self.console_row.set_value(self._console_label(console))
        self.device_row.set_value(self.t(f"input.device.{self._device}"))
        self._sync_controller_type_row()
        mode = self.config.input_profiles.get_analog_dpad_mode(console)
        self.analog_dpad_row.set_value(self.t(f"input.analog_dpad.mode.{mode}"))
        # Only where the core reads a stick at all -- elsewhere there is
        # nothing for the D-pad to stand in for (issue #156).
        has_stick = "l_up" in get_actions_for_console(console)
        self.dpad_analog_row.set_visible(has_stick)
        if has_stick:
            self.dpad_analog_row.set_active(
                self.config.input_profiles.get_dpad_drives_analog(console)
            )
        self._sync_turbo_rows()

    def _sync_controller_type_row(self):
        console = self._console
        types = controller_types_for(console)
        self.controller_type_row.set_visible(bool(types))
        if not types:
            self._controller_type_options = []
            return
        # None first: "whatever the core boots with", the default and the only
        # honest option for a core nobody has verified.
        self._controller_type_options = [
            (CORE_DEFAULT, self.t("input.controller_type.core_default"))
        ] + [(str(ident), label) for ident, label in types]
        self.controller_type_row.set_value(
            dict(self._controller_type_options)[self._controller_type_current()]
        )

    def _controller_type_current(self):
        current = self.config.input_profiles.get_controller_type(self._console)
        return CORE_DEFAULT if current is None else str(current)

    def _pick_controller_type(self):
        self._open_chooser(
            self.t("input.controller_type.title"),
            self._controller_type_options,
            self._controller_type_current(),
            self._on_controller_type_picked,
        )

    def _on_controller_type_picked(self, choice):
        ident = None if choice == CORE_DEFAULT else int(choice)
        self.config.input_profiles.set_controller_type(self._console, ident)
        self._sync_controller_type_row()

    def _pick_analog_dpad(self):
        options = [
            (str(mode), self.t(f"input.analog_dpad.mode.{mode}")) for mode in ANALOG_DPAD_MODES
        ]
        current = str(self.config.input_profiles.get_analog_dpad_mode(self._console))
        self._open_chooser(
            self.t("input.analog_dpad.title"), options, current, self._on_analog_dpad_picked
        )

    def _on_analog_dpad_picked(self, choice):
        self.config.input_profiles.set_analog_dpad_mode(self._console, int(choice))
        self._sync_console_rows()

    def _on_dpad_analog_toggled(self, active):
        self.config.input_profiles.set_dpad_drives_analog(self._console, active)

    # -- stick, feedback and turbo -------------------------------------------------
    @staticmethod
    def _number(value, digits):
        return f"{value:.{digits}f}" if digits else str(int(value))

    def _sync_tuning_rows(self):
        config = self.config
        for name, digits, _step in TUNING_ROWS:
            self.tuning_rows[name].set_value(
                self._number(config.get_input_tuning_value(name), digits)
            )
        poll = config.get_input_tuning_value("poll_type_behavior")
        self.poll_row.set_value(self.t(f"input.tuning.poll.{poll}"))
        focus = config.get_input_tuning_value("auto_game_focus")
        self.focus_row.set_value(self.t(f"input.tuning.focus.{focus}"))
        self.descriptor_row.set_active(config.get_input_tuning_value("descriptor_label_show"))

    def _step_tuning(self, name, digits, step, delta):
        low, high = INPUT_TUNING[name][3], INPUT_TUNING[name][4]
        value = self.config.get_input_tuning_value(name) + delta * step
        self.config.set_input_tuning_value(name, round(min(high, max(low, value)), digits))
        self.tuning_rows[name].set_value(
            self._number(self.config.get_input_tuning_value(name), digits)
        )

    def _pick_poll(self):
        options = [(str(index), self.t(f"input.tuning.poll.{index}")) for index in range(3)]
        current = str(self.config.get_input_tuning_value("poll_type_behavior"))
        self._open_chooser(
            self.t("input.tuning.poll_type_behavior"), options, current,
            lambda choice: self._set_tuning_choice("poll_type_behavior", choice),
        )

    def _pick_focus(self):
        options = [(str(index), self.t(f"input.tuning.focus.{index}")) for index in range(3)]
        current = str(self.config.get_input_tuning_value("auto_game_focus"))
        self._open_chooser(
            self.t("input.tuning.auto_game_focus"), options, current,
            lambda choice: self._set_tuning_choice("auto_game_focus", choice),
        )

    def _set_tuning_choice(self, name, choice):
        self.config.set_input_tuning_value(name, int(choice))
        self._sync_tuning_rows()

    def _sync_turbo_rows(self):
        settings = self.config.input_profiles.get_turbo_settings(self._console)
        self.turbo_period_row.set_value(settings["period"])
        self.turbo_duty_row.set_value(settings["duty_cycle"])
        self.turbo_mode_row.set_value(self.t(f"input.turbo.mode.{settings['mode']}"))

    def _step_turbo(self, key, bounds, delta):
        settings = self.config.input_profiles.get_turbo_settings(self._console)
        low, high = bounds
        settings[key] = min(high, max(low, settings[key] + delta))
        self.config.input_profiles.set_turbo_settings(self._console, settings)
        # Read back: the store keeps the duty cycle under the period.
        self._sync_turbo_rows()

    def _pick_turbo_mode(self):
        options = [(str(mode), self.t(f"input.turbo.mode.{mode}")) for mode in TURBO_MODES]
        current = str(self.config.input_profiles.get_turbo_settings(self._console)["mode"])
        self._open_chooser(self.t("input.turbo.mode"), options, current, self._on_turbo_mode_picked)

    def _on_turbo_mode_picked(self, choice):
        settings = self.config.input_profiles.get_turbo_settings(self._console)
        settings["mode"] = int(choice)
        self.config.input_profiles.set_turbo_settings(self._console, settings)
        self._sync_turbo_rows()

    def _sync_relaunch_row(self):
        """The relaunch note shows only while there is a game to relaunch."""
        self.relaunch_row.set_visible(self.win.runtime_manager.is_running())

    # -- the binding rows -----------------------------------------------------------
    def _input_action_label(self, action):
        return self.t(f"input.action.{action}")

    def _input_action_subtitle(self, action):
        # Only ``enable_hotkey`` needs one: it reads as one more hotkey while
        # actually gating every one of them (issue #124).
        if action == "enable_hotkey":
            return self.t("input.action.enable_hotkey.subtitle")
        return None

    def _binding_display(self, value):
        if not value:
            return self.t("input.binding.empty")
        if self._device == "keyboard":
            return value
        # Gamepad bindings are RetroArch tokens ("3", "+2", "h0up"): show
        # something a person can recognise while keeping the token.
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
        for row in self._binding_rows.values():
            row.get_parent().remove(row)
        self._binding_rows = {}

        console_id, device_id = self._console, self._device
        profile = self.config.get_input_profile(console_id)
        device = profile.get("devices", {}).get(device_id, {})
        bindings = device.get("bindings", {})
        visible_actions = get_actions_for_console(console_id)
        is_extra_port = device_id in EXTRA_PORT_DEVICE_IDS
        if is_extra_port:
            # RetroArch hotkeys are global, so ports 2-4 only map gameplay.
            visible_actions = [a for a in visible_actions if a not in GLOBAL_HOTKEY_ACTIONS]
        # Map-all never demands the optional actions (turbo, the right stick):
        # forcing a user through a modifier they may not want defeats the flow.
        self._capture.load(
            {action: str(bindings.get(action, "")).strip().lower() for action in visible_actions},
            [action for action in visible_actions if action not in OPTIONAL_ACTIONS],
        )
        self._loaded_bindings = dict(self._capture.bindings)
        self.port_row.set_visible(is_extra_port)
        self._loaded_port_enabled = bool(device.get("enabled", False)) if is_extra_port else None
        if is_extra_port:
            self.port_row.set_active(self._loaded_port_enabled)
        self.system_group.set_visible(
            any(action in GLOBAL_HOTKEY_ACTIONS for action in visible_actions)
        )
        for action in visible_actions:
            row = Row(
                self._input_action_label(action), self._input_action_subtitle(action),
                kind=ROW_ACTION, value=self._binding_display(self._capture.binding_for(action)),
                on_activate=lambda action=action: self._on_binding_row(action),
            )
            (self.system_rows if action in GLOBAL_HOTKEY_ACTIONS else self.game_rows).append(row)
            self._binding_rows[action] = row

        # Another console or device: the keys seen so far belonged to the rows
        # left behind, and the pad reader moves only if the port did.
        self._held_keys.clear()
        self._rebuild_drawing(console_id)
        self._sync_held_reader()
        self._sync_save_row()

    def _sync_save_row(self):
        key = "big_picture.input.save.unsaved" if self.has_unsaved() else "big_picture.input.save.subtitle"
        self.save_row.set_subtitle(self.t(key))

    def _on_binding_row(self, action):
        """A on a row: capture at once when it is empty, else ask what to do."""
        row = self._binding_rows[action]
        binding = self._capture.binding_for(action)
        if not binding:
            self._start_capture(action, sequence_mode=False, return_to=row)
            return
        t = self.t
        options = [
            (REMAP, t("big_picture.input.binding.remap")),
            (CLEAR, t("big_picture.input.binding.clear")),
            (KEEP, t("big_picture.input.binding.keep")),
        ]
        self._open_chooser(
            self._input_action_label(action), options, KEEP,
            lambda choice: self._on_binding_choice(action, choice),
            lead=t("big_picture.input.binding.lead", binding=self._binding_display(binding)),
        )

    def _on_binding_choice(self, action, choice):
        if choice == REMAP:
            self._start_capture(action, sequence_mode=False, return_to=self._binding_rows[action])
        elif choice == CLEAR:
            self._set_binding(action, "")

    # -- the controller drawing (issue 815) ------------------------------------------
    def _controller_layout(self, console_id):
        """The console's drawing, read once per section (None: it has none)."""
        if console_id not in self._controller_layouts:
            self._controller_layouts[console_id] = layout_for(console_id)
        return self._controller_layouts[console_id]

    def _rebuild_drawing(self, console_id):
        """Put the console's drawing in its card, or hide the group.

        Only a console change builds a new drawing; a device change keeps it
        and refreshes what each target says and whether it can be used.
        """
        if self._drawing is None or self._drawing_console != console_id:
            if self._drawing is not None:
                self.drawing_card.remove(self._drawing)
                # Unparent its targets now: by the time it is finalized its
                # Python side, which does that in do_dispose, is gone.
                self._drawing.run_dispose()
                self._drawing = None
            self._drawing_highlight = None
            self._drawing_console = console_id
            layout = self._controller_layout(console_id)
            self.drawing_group.set_visible(layout is not None)
            if layout is None:
                self._sync_drawing_caption()
                return
            self._drawing = ControllerDrawing(
                layout,
                on_activate=self._on_drawing_activated,
                on_highlight=self._on_drawing_highlight,
                not_remappable_text=self.t("input.drawing.not_remappable"),
            )
            self._drawing.update_property(
                [Gtk.AccessibleProperty.LABEL],
                [self.t("input.drawing.accessible_name", console=get_system_display_name(console_id))],
            )
            self.drawing_card.append(self._drawing)
        self._sync_drawing()

    def _drawing_target_text(self, action, binding_text=None):
        if binding_text is None:
            binding_text = self._binding_display(self._capture.binding_for(action))
        return self.t(
            "input.drawing.target", action=self._input_action_label(action), binding=binding_text
        )

    def _sync_drawing(self):
        """Bring every target in line with the bindings and the capture."""
        drawing = self._drawing
        if drawing is None:
            return
        for action in drawing.buttons:
            # An action the device does not map (the hotkeys on ports 2-4)
            # is drawn but, like a control with no action, not remappable.
            if action in self._binding_rows:
                drawing.set_action_state(action, self._drawing_target_text(action), True)
            else:
                drawing.set_action_state(action, self.t("input.drawing.not_remappable"), False)
        drawing.set_current(self._capture.active_action if self._capture.capturing else None)
        self._sync_lit()
        self._sync_drawing_caption()

    def _sync_drawing_caption(self):
        """The line under the drawing: the capture, else the focused target."""
        caption = self.drawing_caption
        drawing = self._drawing
        action = self._capture.active_action if self._capture.capturing else None
        if drawing is not None and action in drawing.buttons:
            waiting_key = (
                "input.capture.waiting" if self._device == "keyboard"
                else "input.capture.waiting_gamepad"
            )
            caption.set_text(self._drawing_target_text(action, self.t(waiting_key)))
            caption.add_css_class("accent")
            return
        caption.remove_css_class("accent")
        highlight = self._drawing_highlight
        if drawing is not None and highlight in self._binding_rows:
            caption.set_text(self._drawing_target_text(highlight))
        else:
            caption.set_text("")

    def _on_drawing_highlight(self, action):
        self._drawing_highlight = action
        self._sync_drawing_caption()

    def _on_drawing_activated(self, action):
        # The row's own path, with the focus coming back to the drawn button.
        self._start_capture(
            action, sequence_mode=False, return_to=self._drawing.buttons[action][0]
        )

    # -- lighting what is pressed (issue 816) ------------------------------------------
    def _lit_bindings(self):
        """The bindings on screen, action -> token, as the held tokens are spelled."""
        keyboard = self._device == "keyboard"
        bindings = {}
        for action in self._binding_rows:
            value = self._capture.binding_for(action)
            bindings[action] = key_token(value) if keyboard else value
        return bindings

    def _sync_lit(self):
        """Light the button being captured, or else the ones whose input is held."""
        drawing = self._drawing
        if drawing is None:
            return
        if self._capture.capturing:
            drawing.set_lit({self._capture.active_action})
            return
        held = self._held_keys.tokens if self._device == "keyboard" else self._held_pad
        drawing.set_lit(lit_actions(self._lit_bindings(), held))

    def _on_key_pressed(self, _controller, keyval, keycode, _state):
        """A key went down over the section: light the drawn button it is bound to.

        Never taken from the page: an arrow still moves the focus and Enter
        still activates, lit or not. A capture owns the keys instead.
        """
        if self._capture.capturing or self._device != "keyboard" or self._drawing is None:
            return False
        if self._held_keys.press(keycode, Gdk.keyval_name(keyval)):
            self._sync_lit()
        return False

    def _on_key_released(self, _controller, _keyval, keycode, _state):
        if self._held_keys.release(keycode):
            self._sync_lit()

    def _forget_held_keys(self):
        if self._held_keys.clear():
            self._sync_lit()

    def _section_is_live(self):
        """On screen, in a window that has the focus: a pad pressed while
        another application is in front is none of this section's business."""
        if not self.widget.get_mapped():
            return False
        root = self.widget.get_root()
        return root is None or root.is_active()

    def _sync_held_reader(self):
        """Read the pad for the drawing exactly while that is called for.

        Wanted while the section is live, a pad is the device being edited and
        no capture owns it; stopped the moment any of that ends. It only reads:
        UI navigation keeps the pad.
        """
        wanted = (
            self._drawing is not None
            and self._device != "keyboard"
            and not self._capture.capturing
            and self._section_is_live()
        )
        port = player_for_device(self._device) if wanted else None
        if self._held_reader is not None and port != self._held_reader_port:
            self._stop_held_reader()
        if not wanted or self._held_reader is not None:
            return
        device, error_key = self._device_for_port(port)
        if error_key:
            return  # no pad on that port: nothing to light, and nothing to say
        self._held_reader_port = port
        reader = make_held_reader(
            on_change=lambda tokens: GLib.idle_add(self._on_pad_held, reader, tokens),
            device=device,
        )
        self._held_reader = reader
        reader.start()

    def _stop_held_reader(self):
        reader = self._held_reader
        self._held_reader = None
        self._held_reader_port = None
        if reader is not None:
            # Not waited for: its thread ends on its own within a poll, and a
            # join here would stall the press that starts a capture.
            reader.stop(join_timeout=0)
        if self._held_pad:
            self._held_pad = frozenset()
            self._sync_lit()

    def _on_pad_held(self, reader, tokens):
        # From the reader's thread through the main loop: by now that reader
        # may have been stopped, and what it saw is stale.
        if reader is self._held_reader:
            self._held_pad = frozenset(tokens)
            self._sync_lit()
        return False

    def _on_unmapped(self):
        self._forget_held_keys()
        self._stop_held_reader()

    # -- the capture -------------------------------------------------------------------
    def _set_exclusive_input(self, active):
        """Pause the pad navigator: the buttons being mapped are the ones that drive the UI."""
        self.win.set_input_capture_active(active)

    def _start_capture(self, action, sequence_mode, return_to=None):
        if action not in self._binding_rows:
            return
        self._stop_gamepad_reader()
        self._set_exclusive_input(True)
        self._capture.start(action, sequence_mode)
        # The capture owns the input from here: nothing held is lit, and the
        # pad is the capture reader's alone.
        self._held_keys.clear()
        self._stop_held_reader()
        if return_to is not None:
            self._return_to = return_to

        is_gamepad = self._device != "keyboard"
        waiting_key = "input.capture.waiting_gamepad" if is_gamepad else "input.capture.waiting"
        self._binding_rows[action].set_value(self.t(waiting_key))
        self._show_capture_card(action, is_gamepad)
        self._start_countdown()
        self._install_key_controller()
        self._sync_drawing()
        if is_gamepad:
            self._start_gamepad_reader()

    def _show_capture_card(self, action, is_gamepad):
        t = self.t
        console = self._console_label(self._console)
        device = t(f"input.device.{self._device}")
        if self._capture.sequence_mode:
            sequence = self._capture.sequence_actions
            self.capture_eyebrow.set_label(t(
                "big_picture.input.capture.sequence",
                index=sequence.index(action) + 1, count=len(sequence),
                console=console, device=device,
            ))
        else:
            self.capture_eyebrow.set_label(
                t("big_picture.input.capture.single", console=console, device=device)
            )
        prompt_key = "input.capture.waiting_for_gamepad" if is_gamepad else "input.capture.waiting_for"
        self.capture_heading.set_label(t(prompt_key, action=self._input_action_label(action)))
        note_key = (
            "big_picture.input.capture.note_gamepad" if is_gamepad
            else "big_picture.input.capture.note_keyboard"
        )
        self.capture_note.set_label(t(note_key))
        self.capture_card.set_visible(True)

    # The countdown: a capture nobody answers ends on its own, the way Escape
    # ends it, so a pad put down mid-capture never leaves the UI frozen.
    def _start_countdown(self):
        self._stop_countdown()
        self._countdown_left = CAPTURE_TIMEOUT
        self._show_countdown()
        self._countdown_source = GLib.timeout_add_seconds(1, self._on_countdown_tick)

    def _show_countdown(self):
        self.capture_countdown.set_label(
            self.t("big_picture.input.capture.seconds", count=self._countdown_left)
        )

    def _stop_countdown(self):
        if self._countdown_source:
            GLib.source_remove(self._countdown_source)
            self._countdown_source = 0

    def _on_countdown_tick(self):
        self._countdown_left -= 1
        if self._countdown_left > 0:
            self._show_countdown()
            return GLib.SOURCE_CONTINUE
        self._stop_countdown()
        self._cancel_capture(show_toast=True)
        return GLib.SOURCE_REMOVE

    # The keys, while capturing: on the window, in the capture phase, so they
    # are taken before the window's own Escape (B) or any focused row sees them.
    def _install_key_controller(self):
        if self._key_controller is not None:
            return
        controller = Gtk.EventControllerKey()
        controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        controller.connect("key-pressed", self._on_capture_key)
        self.win.add_controller(controller)
        self._key_controller = controller

    def _remove_key_controller(self):
        controller = self._key_controller
        self._key_controller = None
        if controller is not None:
            self.win.remove_controller(controller)

    @staticmethod
    def _normalize_key(keyval):
        """A captured key, as the token RetroArch will resolve (issue #144)."""
        key_name = Gdk.keyval_name(keyval)
        if not key_name:
            return ""
        return retroarch_key_token(key_name.lower())

    def _on_capture_key(self, _controller, keyval, _keycode, _state):
        if not self._capture.capturing:
            return False
        key_name = self._normalize_key(keyval)
        # Escape cancels, for both device types -- and keeps the binding: on
        # a pad the way out must not double as the way to lose a mapping.
        if key_name == "escape":
            self._cancel_capture(show_toast=True)
            return True
        # While capturing a gamepad binding, swallow other keys so a stray
        # keystroke cannot be stored as a controller token.
        if self._device != "keyboard":
            return True
        if not key_name:
            return True
        self._commit_capture(key_name)
        return True

    # -- the gamepad reader ------------------------------------------------------------
    def _device_for_port(self, port):
        """The physical pad for RetroArch port ``port``: the Nth pad in the backend's order.

        ``(device, error_key)``; ``device=None`` with no error means "let the
        reader choose", which only happens for port 1.
        """
        if port <= 1:
            return None, None
        gamepads = list_gamepads()
        if len(gamepads) < port:
            return None, "input.capture.port_unavailable"
        return gamepads[port - 1], None

    def _start_gamepad_reader(self):
        port = player_for_device(self._device)
        device, error_key = self._device_for_port(port)
        if error_key:
            self._cancel_capture()
            self._toast(self.t(error_key, port=port), timeout=6)
            return
        self._gamepad_reader = make_capture_reader(
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
        # The reader runs on its own thread; the capture may have been
        # cancelled between the press and this idle callback.
        if not self._capture.capturing or self._device == "keyboard":
            return False
        self._gamepad_reader = None
        if token == GUIDE_TOKEN:
            self._cancel_capture(show_toast=True)
            return False
        self._commit_capture(token)
        return False

    def _on_gamepad_error(self, reason):
        if not self._capture.capturing:
            return False
        self._gamepad_reader = None
        self._cancel_capture()
        key = (
            "input.capture.permission_denied" if reason == "permission_denied"
            else "input.capture.no_gamepad"
        )
        self._toast(self.t(key), timeout=6)
        return False

    # -- ending a capture ----------------------------------------------------------------
    def _cancel_capture(self, show_toast=False):
        self._stop_gamepad_reader()
        self._stop_countdown()
        self._remove_key_controller()
        self._set_exclusive_input(False)
        cancelled = self._capture.cancel()
        if cancelled.action in self._binding_rows:
            self._binding_rows[cancelled.action].set_value(
                self._binding_display(self._capture.binding_for(cancelled.action))
            )
        self.capture_card.set_visible(False)
        self._sync_drawing()
        self._sync_held_reader()
        if show_toast and cancelled.was_sequence:
            self._toast(self.t("input.capture.cancelled"))
        self._focus_return()

    def _focus_return(self):
        target, self._return_to = self._return_to, None
        if target is not None:
            target.grab_focus()

    def start_map_all(self):
        self._cancel_capture()
        first = self._capture.begin_sequence()
        if first is None:
            return
        self._start_capture(first, sequence_mode=True, return_to=self.map_all_row)

    def _set_binding(self, action, value):
        """Store a binding through the session, then render what it did."""
        released = self._capture.set_binding(action, value)
        self._render_binding(action, released)
        return released

    def _render_binding(self, action, released):
        """Repaint the rows a stored binding touched, and say what it took."""
        for other_action in released:
            self._binding_rows[other_action].set_value(self._binding_display(""))
        value = self._capture.binding_for(action)
        self._binding_rows[action].set_value(self._binding_display(value))
        self._sync_drawing()
        self._sync_save_row()
        # Say what was taken away (issue #281) -- but not during map-all, where
        # one toast per button is noise, not information.
        if released and not self._capture.sequence_mode:
            self._toast(self.t(
                "toast.input_released",
                binding=self._binding_display(value),
                actions=", ".join(self._input_action_label(other) for other in released),
            ))

    def _commit_capture(self, value):
        """Store a captured binding and advance the sequence, if any."""
        outcome = self._capture.commit(value)
        if outcome is None:
            return
        self._render_binding(outcome.action, outcome.released)
        if outcome.next_action is not None:
            self._start_capture(outcome.next_action, sequence_mode=True)
            return
        self._cancel_capture()
        if outcome.finished:
            self._toast(self.t("input.capture.completed"))

    # -- save and reset ---------------------------------------------------------------------
    def save(self):
        """Write the edited bindings to the console's profile (the desktop's Save)."""
        self._cancel_capture()
        console_id, device_id = self._console, self._device
        # Read the profile back rather than trusting the snapshot taken when
        # the rows were built: the stick and turbo rows write straight to
        # disk, and a save from a stale snapshot reverted them (issue #126).
        profile = self.config.get_input_profile(console_id)
        devices = profile.setdefault("devices", {})
        device = devices.setdefault(
            device_id, {"type": device_type_for(device_id), "bindings": {}}
        )
        valid_actions = get_actions_for_console(console_id)
        existing = device.get("bindings") or {}
        device["bindings"] = {
            a: self._capture.bindings.get(a, existing.get(a, "")) for a in valid_actions
        }
        if device_id in EXTRA_PORT_DEVICE_IDS:
            # Ports 2-4 are opt-in and never take over player 1.
            device["enabled"] = self.port_row.get_active()
        else:
            profile["active_device"] = device_id
        self.config.save_input_profile(console_id, profile)
        # Read the rows back from what was actually stored (issue #281).
        self._refresh_bindings()
        self._toast(self.t("toast.input_saved", console=console_id))
        # A remap saved mid-game reaches the running game through the
        # state-carrying relaunch (issue #129), when it is this console's.
        self._apply_to_running_game_if_relevant(console_id)
        self._sync_relaunch_row()

    def reset_defaults(self):
        """Ask first: on a pad, Y is one press away from every row."""
        t = self.t
        self.shell.confirm(
            t("big_picture.input.reset.heading", console=self._console),
            t("big_picture.input.reset.body"),
            t("input.reset"),
            self._do_reset,
        )

    def _do_reset(self):
        console_id = self._console
        self.config.reset_input_profile(console_id)
        self._cancel_capture()
        # The reset also takes the stick, turbo and controller-type rows back.
        self._sync_console_rows()
        self._refresh_bindings()
        self._toast(self.t("toast.input_reset", console=console_id))
        # A reset writes the profile just like Save does (issue #129).
        self._apply_to_running_game_if_relevant(console_id)

    def _apply_to_running_game_if_relevant(self, console_id):
        """Push a just-written profile into the running game, if it uses it."""
        manager = self.win.runtime_manager
        if not manager.is_running():
            return
        active = (manager.active_rom or {}).get("console")
        if active and resolve_system_id(active) == resolve_system_id(console_id):
            self.win.apply_input_changes_to_running_game()


__all__ = ["InputSection", "CAPTURE_TIMEOUT", "GUIDE_TOKEN"]
