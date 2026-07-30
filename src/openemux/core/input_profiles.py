import json
from copy import deepcopy
from pathlib import Path

from openemux.core.input_actions import (
    default_gamepad_bindings,
    default_keyboard_bindings,
    get_actions_for_console,
    normalize_bindings,
)
from openemux.core.systems import resolve_system_id

PROFILE_VERSION = 4

#: Lowest pad button index that no common controller exposes. An Xbox-style
#: pad stops at 10, so anything from here up can never be pressed.
FIRST_UNREACHABLE_GAMEPAD_BUTTON = 11

#: Every device slot a profile can hold, in UI order.
DEVICE_IDS = ["keyboard", "gamepad_p1", "gamepad_p2", "gamepad_p3", "gamepad_p4"]

#: Ports 2-4. Port 1 is chosen through ``active_device`` (keyboard or pad),
#: these are opt-in and carry an ``enabled`` flag instead.
EXTRA_PORT_DEVICE_IDS = ["gamepad_p2", "gamepad_p3", "gamepad_p4"]

#: Devices eligible to drive player 1.
PLAYER1_DEVICE_IDS = ["keyboard", "gamepad_p1"]

#: RetroArch's input_playerN_analog_dpad_mode values (issue #71).
ANALOG_DPAD_OFF = 0
ANALOG_DPAD_LEFT_STICK = 1
ANALOG_DPAD_RIGHT_STICK = 2
ANALOG_DPAD_MODES = (ANALOG_DPAD_OFF, ANALOG_DPAD_LEFT_STICK, ANALOG_DPAD_RIGHT_STICK)

#: Consoles whose pads use the analog stick natively: folding it onto the
#: D-pad there would steal the stick from the game, so they default to off.
#: Everything else defaults to the left stick -- a digital-only console has
#: no analog input to lose, and "the stick also moves" is what players expect.
ANALOG_NATIVE_CONSOLES = {"N64", "PS", "PSP", "GC", "SATURN"}


#: RetroArch turbo timing/behavior (issue #72). Period and duty cycle are in
#: frames; mode 0 = classic (hold the turbo modifier + a button), 1 =
#: single-button toggle, 2 = single-button hold.
DEFAULT_TURBO_SETTINGS = {"period": 6, "duty_cycle": 3, "mode": 0}
TURBO_MODES = (0, 1, 2)
TURBO_PERIOD_RANGE = (2, 120)
TURBO_DUTY_RANGE = (1, 119)


def normalize_turbo_settings(value):
    raw = value if isinstance(value, dict) else {}

    def _int(key, default, low, high):
        try:
            number = int(raw.get(key, default))
        except (TypeError, ValueError):
            return default
        return min(high, max(low, number))

    period = _int("period", DEFAULT_TURBO_SETTINGS["period"], *TURBO_PERIOD_RANGE)
    duty = _int("duty_cycle", DEFAULT_TURBO_SETTINGS["duty_cycle"], *TURBO_DUTY_RANGE)
    mode = _int("mode", DEFAULT_TURBO_SETTINGS["mode"], 0, 2)
    # The button must release within the period or it never re-fires.
    duty = min(duty, period - 1)
    return {"period": period, "duty_cycle": duty, "mode": mode}


def clear_unreachable_gamepad_buttons(bindings):
    """Blank pad bindings pointing at a button the hardware does not have.

    Profiles written before version 3 bound the hotkeys to buttons 11-15
    (issue #124). Since ``enable_hotkey`` gates every other hotkey in
    RetroArch, one unreachable modifier silently disabled the whole set.
    Blanking the token is enough: ``normalize_bindings`` refills it from the
    current defaults on the same pass, so the repair needs no manual reset.

    Only bare button indices are considered -- axis (``+2``) and hat
    (``h0up``) tokens are a different namespace and never out of range.
    """
    if not isinstance(bindings, dict):
        return {}
    cleaned = {}
    for action, value in bindings.items():
        token = str(value).strip()
        if token.isdigit() and int(token) >= FIRST_UNREACHABLE_GAMEPAD_BUTTON:
            cleaned[action] = ""
            continue
        cleaned[action] = value
    return cleaned


#: Keyboard bindings introduced in profile version 4 (issue #146), and the
#: value each one replaces when it is still whatever the app put there.
#:
#: These actions are all in OPTIONAL_ACTIONS, which normalize_bindings skips by
#: design so a profile that predates an action never has one auto-filled. That
#: protection also means a new default reaches nobody who has already run the
#: app -- first_boot writes a .config for every console on first launch -- so
#: they are filled once, here.
V4_KEYBOARD_DEFAULTS = {
    "reset_game": ("",),
    "turbo": ("",),
    "state_slot_increase": ("",),
    "state_slot_decrease": ("",),
    # f9 was the old shipped default rather than a choice anyone made.
    "audio_mute": ("", "f9"),
}

#: Bindings version 4 *blanks* when they still hold a superseded default.
#:
#: ``enable_hotkey`` shipped as "right shift", which is not a name RetroArch
#: resolves -- so input_enable_hotkey was effectively unbound and keyboard
#: hotkeys have always fired directly. Once issue #144 translates it to
#: `rshift` it starts working, silently demanding a modifier for every hotkey
#: on profiles that already exist. Clearing the value nobody chose keeps the
#: behaviour people actually have.
V4_KEYBOARD_CLEARED = {"enable_hotkey": ("right shift", "rshift")}


def apply_v4_keyboard_defaults(bindings, defaults):
    """Bring a keyboard profile up to version 4 (issue #146).

    Only touches a value that is empty or still a superseded default, so a
    deliberate binding is always left alone.
    """
    if not isinstance(bindings, dict):
        bindings = {}
    updated = dict(bindings)
    for action, replaceable in V4_KEYBOARD_DEFAULTS.items():
        new_value = defaults.get(action, "")
        if not new_value:
            continue
        current = str(updated.get(action, "")).strip().lower()
        if current in replaceable:
            updated[action] = new_value
    for action, superseded in V4_KEYBOARD_CLEARED.items():
        current = str(updated.get(action, "")).strip().lower()
        if current in superseded:
            updated[action] = ""
    return updated


def default_analog_dpad_mode(console):
    canonical = resolve_system_id(console)
    if canonical in ANALOG_NATIVE_CONSOLES:
        return ANALOG_DPAD_OFF
    return ANALOG_DPAD_LEFT_STICK


def normalize_analog_dpad_mode(value, console):
    try:
        mode = int(value)
    except (TypeError, ValueError):
        return default_analog_dpad_mode(console)
    return mode if mode in ANALOG_DPAD_MODES else default_analog_dpad_mode(console)


def player_for_device(device_id):
    """Return the RetroArch port a device slot maps to (1-based)."""
    if device_id in ("keyboard", "gamepad_p1"):
        return 1
    if isinstance(device_id, str) and device_id.startswith("gamepad_p"):
        suffix = device_id[len("gamepad_p"):]
        if suffix.isdigit():
            return int(suffix)
    return 1


def device_type_for(device_id):
    return "keyboard" if device_id == "keyboard" else "gamepad"


class InputProfileManager:
    def __init__(self, input_dir):
        self.input_dir = Path(input_dir).expanduser()

    def ensure_dir(self):
        self.input_dir.mkdir(parents=True, exist_ok=True)

    def profile_path(self, console):
        system_id = resolve_system_id(console)
        return self.input_dir / f"{system_id}.config"

    def default_profile(self, console):
        system_id = resolve_system_id(console)
        allowed_actions = set(get_actions_for_console(system_id))
        keyboard_defaults = default_keyboard_bindings()
        gamepad_defaults = default_gamepad_bindings()
        devices = {}
        for device_id in DEVICE_IDS:
            device_type = device_type_for(device_id)
            defaults = keyboard_defaults if device_type == "keyboard" else gamepad_defaults
            entry = {
                "type": device_type,
                "bindings": {action: defaults.get(action, "") for action in allowed_actions},
            }
            # Ports 2-4 are opt-in; port 1 is selected through active_device.
            entry["enabled"] = device_id not in EXTRA_PORT_DEVICE_IDS
            devices[device_id] = entry
        return {
            "version": PROFILE_VERSION,
            "console": system_id,
            "active_device": "keyboard",
            # The stick folded onto the D-pad (issue #71) is a per-console
            # choice, not per-device: RetroArch applies it per port and every
            # pad on the console should behave the same way.
            "analog_dpad_mode": default_analog_dpad_mode(system_id),
            # Turbo timing (issue #72). Turbo itself is on iff a turbo
            # modifier is bound on a device; these only tune how it fires.
            "turbo": dict(DEFAULT_TURBO_SETTINGS),
            "devices": devices,
        }

    def _normalize_profile(self, console, profile):
        system_id = resolve_system_id(console)
        base = self.default_profile(system_id)
        loaded = profile or {}

        try:
            loaded_version = int(loaded.get("version", 0)) if isinstance(loaded, dict) else 0
        except (TypeError, ValueError):
            loaded_version = 0
        keyboard_defaults = default_keyboard_bindings()

        devices = loaded.get("devices", {}) if isinstance(loaded, dict) else {}
        # Devices absent from the file (e.g. a 1.2.x profile that only knew
        # keyboard + gamepad_p1) fall back to defaults, with ports 2-4 disabled.
        for device_id in DEVICE_IDS:
            default_device = deepcopy(base["devices"][device_id])
            loaded_device = devices.get(device_id, {}) if isinstance(devices, dict) else {}
            if not isinstance(loaded_device, dict):
                loaded_device = {}
            bindings = loaded_device.get("bindings", {})
            if loaded_version < 3 and default_device["type"] == "gamepad":
                bindings = clear_unreachable_gamepad_buttons(bindings)
            if loaded_version < 4 and default_device["type"] == "keyboard":
                bindings = apply_v4_keyboard_defaults(bindings, keyboard_defaults)
            default_device["bindings"] = normalize_bindings(bindings, default_device["type"], console=system_id)
            if device_id in EXTRA_PORT_DEVICE_IDS:
                default_device["enabled"] = bool(loaded_device.get("enabled", False))
            else:
                default_device["enabled"] = True
            base["devices"][device_id] = default_device

        active_device = loaded.get("active_device", "keyboard") if isinstance(loaded, dict) else "keyboard"
        # Only keyboard / gamepad_p1 can drive player 1.
        if active_device not in PLAYER1_DEVICE_IDS:
            active_device = "keyboard"

        base["version"] = PROFILE_VERSION
        base["console"] = system_id
        base["active_device"] = active_device
        base["analog_dpad_mode"] = normalize_analog_dpad_mode(
            loaded.get("analog_dpad_mode") if isinstance(loaded, dict) else None,
            system_id,
        )
        base["turbo"] = normalize_turbo_settings(
            loaded.get("turbo") if isinstance(loaded, dict) else None
        )
        return base

    def load_profile(self, console):
        self.ensure_dir()
        system_id = resolve_system_id(console)
        path = self.profile_path(system_id)
        if not path.exists():
            profile = self.default_profile(system_id)
            self.save_profile(system_id, profile)
            return profile

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            data = {}

        profile = self._normalize_profile(system_id, data)
        if profile != data:
            self.save_profile(system_id, profile)
        return profile

    def save_profile(self, console, profile):
        self.ensure_dir()
        system_id = resolve_system_id(console)
        normalized = self._normalize_profile(system_id, profile)
        path = self.profile_path(system_id)
        path.write_text(json.dumps(normalized, indent=2, sort_keys=True), encoding="utf-8")
        return normalized

    def reset_console(self, console):
        profile = self.default_profile(console)
        return self.save_profile(console, profile)

    def ensure_default_profiles(self, consoles):
        self.ensure_dir()
        for console in consoles:
            self.load_profile(console)

    def get_analog_dpad_mode(self, console):
        return self.load_profile(console).get(
            "analog_dpad_mode", default_analog_dpad_mode(console)
        )

    def set_analog_dpad_mode(self, console, mode):
        profile = self.load_profile(console)
        profile["analog_dpad_mode"] = normalize_analog_dpad_mode(mode, console)
        return self.save_profile(console, profile)

    def get_turbo_settings(self, console):
        return normalize_turbo_settings(self.load_profile(console).get("turbo"))

    def set_turbo_settings(self, console, settings):
        profile = self.load_profile(console)
        profile["turbo"] = normalize_turbo_settings(settings)
        return self.save_profile(console, profile)

    def get_device_profile(self, console, device_id=None):
        profile = self.load_profile(console)
        selected = device_id or profile.get("active_device", "keyboard")
        if selected not in profile["devices"]:
            selected = "keyboard"
        return profile, selected, profile["devices"][selected]
