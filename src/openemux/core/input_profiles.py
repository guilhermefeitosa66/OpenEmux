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

PROFILE_VERSION = 1


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
        return {
            "version": PROFILE_VERSION,
            "console": system_id,
            "active_device": "keyboard",
            "devices": {
                "keyboard": {
                    "type": "keyboard",
                    "bindings": {action: keyboard_defaults.get(action, "") for action in allowed_actions},
                },
                "gamepad_p1": {
                    "type": "gamepad",
                    "bindings": {action: gamepad_defaults.get(action, "") for action in allowed_actions},
                },
            },
        }

    def _normalize_profile(self, console, profile):
        system_id = resolve_system_id(console)
        base = self.default_profile(system_id)
        loaded = profile or {}

        devices = loaded.get("devices", {}) if isinstance(loaded, dict) else {}
        for device_id in ("keyboard", "gamepad_p1"):
            default_device = deepcopy(base["devices"][device_id])
            loaded_device = devices.get(device_id, {}) if isinstance(devices, dict) else {}
            bindings = loaded_device.get("bindings", {}) if isinstance(loaded_device, dict) else {}
            default_device["bindings"] = normalize_bindings(bindings, default_device["type"], console=system_id)
            base["devices"][device_id] = default_device

        active_device = loaded.get("active_device", "keyboard") if isinstance(loaded, dict) else "keyboard"
        if active_device not in base["devices"]:
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
