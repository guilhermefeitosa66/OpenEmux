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

PROFILE_VERSION = 2

#: Every device slot a profile can hold, in UI order.
DEVICE_IDS = ["keyboard", "gamepad_p1", "gamepad_p2", "gamepad_p3", "gamepad_p4"]

#: Ports 2-4. Port 1 is chosen through ``active_device`` (keyboard or pad),
#: these are opt-in and carry an ``enabled`` flag instead.
EXTRA_PORT_DEVICE_IDS = ["gamepad_p2", "gamepad_p3", "gamepad_p4"]

#: Devices eligible to drive player 1.
PLAYER1_DEVICE_IDS = ["keyboard", "gamepad_p1"]


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
            "devices": devices,
        }

    def _normalize_profile(self, console, profile):
        system_id = resolve_system_id(console)
        base = self.default_profile(system_id)
        loaded = profile or {}

        devices = loaded.get("devices", {}) if isinstance(loaded, dict) else {}
        # Devices absent from the file (e.g. a 1.2.x profile that only knew
        # keyboard + gamepad_p1) fall back to defaults, with ports 2-4 disabled.
        for device_id in DEVICE_IDS:
            default_device = deepcopy(base["devices"][device_id])
            loaded_device = devices.get(device_id, {}) if isinstance(devices, dict) else {}
            if not isinstance(loaded_device, dict):
                loaded_device = {}
            bindings = loaded_device.get("bindings", {})
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

    def get_device_profile(self, console, device_id=None):
        profile = self.load_profile(console)
        selected = device_id or profile.get("active_device", "keyboard")
        if selected not in profile["devices"]:
            selected = "keyboard"
        return profile, selected, profile["devices"][selected]
