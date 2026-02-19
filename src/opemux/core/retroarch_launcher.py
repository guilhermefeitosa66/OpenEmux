import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from opemux.core.input_actions import to_retroarch_overrides
from opemux.core.systems import SYSTEM_IDS, get_runtime_core_candidates, resolve_system_id

DEFAULT_CORE_CANDIDATES = {system_id: get_runtime_core_candidates(system_id) for system_id in SYSTEM_IDS}

DEFAULT_CORE_DIRS = [
    "/usr/lib/libretro",
    "/usr/lib64/libretro",
    "/usr/lib/x86_64-linux-gnu/libretro",
    "/usr/local/lib/libretro",
]

# Runtime OSD policy:
# - Hide startup/runtime noise (content/core/autoconfig/override/remap/etc).
# - Keep only save/load state and fast-forward notifications enabled.
DEFAULT_NOTIFICATION_OVERRIDES = {
    "menu_show_load_content_animation": '"false"',
    "notification_show_autoconfig": '"false"',
    "notification_show_autoconfig_fails": '"false"',
    "notification_show_remap_load": '"false"',
    "notification_show_cheats_applied": '"false"',
    "notification_show_patch_applied": '"false"',
    "notification_show_config_override_load": '"false"',
    "notification_show_set_initial_disk": '"false"',
    "notification_show_disk_control": '"false"',
    "notification_show_refresh_rate": '"false"',
    "notification_show_netplay_extra": '"false"',
    "notification_show_when_menu_is_alive": '"false"',
    "notification_show_save_state": '"true"',
    "notification_show_fast_forward": '"true"',
}


class RetroArchLauncher:
    def __init__(self, project_root, config_manager):
        self.project_root = Path(project_root)
        self.config_manager = config_manager

    def _resolve_retroarch_binary(self):
        configured = self.config_manager.get_retroarch_binary()
        configured_path = Path(configured).expanduser()

        if configured_path.exists():
            return str(configured_path)

        resolved = shutil.which(configured)
        if resolved:
            return resolved

        vendor_candidates = [
            self.project_root / "vendors" / "RetroArch-Linux-x86_64.AppImage",
            self.project_root / "vendors" / "retroarch.AppImage",
        ]
        for candidate in vendor_candidates:
            if candidate.exists():
                return str(candidate)

        return None

    def _find_core_path(self, console):
        system_id = resolve_system_id(console)
        for hint in self.config_manager.get_retroarch_core_hints(system_id):
            hint_path = Path(hint).expanduser()
            if hint_path.exists():
                return str(hint_path)

        candidates = DEFAULT_CORE_CANDIDATES.get(system_id, [])
        home_dirs = [
            Path.home() / ".config" / "retroarch" / "cores",
            Path.home() / ".var" / "app" / "org.libretro.RetroArch" / "config" / "retroarch" / "cores",
        ]
        search_dirs = [str(p) for p in home_dirs] + DEFAULT_CORE_DIRS

        for core_dir in search_dirs:
            base = Path(core_dir)
            if not base.exists():
                continue
            for name in candidates:
                candidate = base / name
                if candidate.exists():
                    return str(candidate)
        return None

    def _write_runtime_override(self, console):
        profile = self.config_manager.get_input_profile(console)
        active_device = profile.get("active_device", "keyboard")
        device = profile.get("devices", {}).get(active_device, {})
        device_type = device.get("type", "keyboard")
        bindings = device.get("bindings", {})
        overrides = to_retroarch_overrides(bindings, device_type, console=console)
        overrides.update(DEFAULT_NOTIFICATION_OVERRIDES)

        runtime_dir = self.config_manager.get_runtime_dir()
        runtime_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        override_path = runtime_dir / f"runtime_{resolve_system_id(console).lower()}_{timestamp}.cfg"

        lines = [f"{key} = {value}" for key, value in sorted(overrides.items())]
        override_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return str(override_path)

    def launch_process(self, rom_path, console):
        system_id = resolve_system_id(console)
        retroarch_path = self._resolve_retroarch_binary()
        if not retroarch_path:
            return None, (
                "RetroArch binary not found. Set runtime.retroarch.binary "
                "or add RetroArch AppImage under vendors/."
            )

        core_path = self._find_core_path(system_id)
        if not core_path:
            candidates = ", ".join(DEFAULT_CORE_CANDIDATES.get(system_id, []))
            return None, (
                f"No RetroArch core found for {system_id}. "
                f"Tried common core dirs and these core names: {candidates}. "
                "Configure runtime.retroarch.cores in config.yaml."
            )

        cmd = [retroarch_path, "-L", core_path]
        runtime_override = self._write_runtime_override(system_id)
        cmd.extend(["--appendconfig", runtime_override])
        cmd.extend(self.config_manager.get_retroarch_extra_flags())
        cmd.append(rom_path)

        try:
            proc = subprocess.Popen(cmd, cwd=os.getcwd(), env=os.environ.copy())
            return proc, None
        except Exception as exc:
            return None, f"Failed to launch RetroArch: {exc}"
