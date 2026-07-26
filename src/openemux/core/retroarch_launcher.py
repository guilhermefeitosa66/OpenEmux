import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
import logging

from openemux.core.bios_catalog import get_required_for_core
from openemux.core.bios_manager import find_missing_required_for_core
from openemux.core.cores import CoreCatalog
from openemux.core.input_actions import to_retroarch_overrides
from openemux.core.input_profiles import (
    EXTRA_PORT_DEVICE_IDS,
    normalize_analog_dpad_mode,
    normalize_turbo_settings,
    player_for_device,
)
from openemux.core.paths import get_real_home, is_running_in_flatpak
from openemux.core.shaders import ShaderCatalog, normalize_shader_id
from openemux.core.systems import SYSTEM_IDS, get_runtime_core_candidates, resolve_system_id

logger = logging.getLogger(__name__)

# A RetroArch installed as a Flatpak keeps its cores here; still worth searching.
RETROARCH_FLATPAK_ID = "org.libretro.RetroArch"

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
        self.project_root = Path(project_root).expanduser()
        self.config_manager = config_manager
        self.shader_catalog = ShaderCatalog(
            runtime_dir=self.config_manager.get_runtime_dir(),
            project_root=self.project_root,
        )
        self.core_catalog = CoreCatalog(project_root=self.project_root)

    def _launch_prefix(self):
        """Return (argv_prefix, error).

        Inside a Flatpak, delegate to the RetroArch Flatpak on the host via
        flatpak-spawn (both apps see the same absolute paths under the real
        home, which RetroArch reads via its own ``--filesystem=host``).
        Otherwise resolve a native/vendored RetroArch binary.
        """
        if is_running_in_flatpak():
            if not shutil.which("flatpak-spawn"):
                return None, "flatpak-spawn is unavailable; cannot reach RetroArch on the host."
            return ["flatpak-spawn", "--host", "flatpak", "run", RETROARCH_FLATPAK_ID], None

        retroarch_path = self._resolve_retroarch_binary()
        if not retroarch_path:
            return None, (
                "RetroArch binary not found. Set runtime.retroarch.binary "
                "or add RetroArch AppImage under vendors/."
            )
        return [retroarch_path], None

    def _resolve_retroarch_binary(self):
        configured = self.config_manager.get_retroarch_binary()
        configured_path = Path(configured).expanduser()

        if configured_path.is_absolute():
            if configured_path.exists():
                return str(configured_path)
        else:
            project_relative = self.project_root / configured_path
            if project_relative.exists():
                return str(project_relative)
            if configured_path.exists():
                return str(configured_path)

        resolved = shutil.which(configured)
        if resolved:
            return resolved

        vendor_candidates = [
            self.project_root / "vendors" / "RetroArch-Linux-x86_64.AppImage",
            self.project_root / "vendors" / "retroarch.AppImage",
            self.project_root / "vendors" / "retroarch-assets" / "bin" / "retroarch",
        ]
        for candidate in vendor_candidates:
            if candidate.exists():
                return str(candidate)

        return None

    def _core_search_dirs(self):
        real_home = get_real_home()
        home_dirs = [
            real_home / ".config" / "retroarch" / "cores",
            real_home / ".var" / "app" / RETROARCH_FLATPAK_ID / "config" / "retroarch" / "cores",
            self.project_root / "vendors" / "retroarch-assets" / "cores",
        ]
        return [str(p) for p in home_dirs] + DEFAULT_CORE_DIRS

    def _resolve_core_name(self, core_filename):
        """Find an installed core by its bare filename, or ``None``."""
        if not core_filename:
            return None
        for core_dir in self._core_search_dirs():
            candidate = Path(core_dir) / core_filename
            if candidate.exists():
                return str(candidate)
        return None

    def _resolve_core_hint(self, hint):
        """A config hint is either a path (historical) or a bare core filename."""
        if not hint:
            return None
        hint_path = Path(hint).expanduser()
        if hint_path.is_absolute() or len(hint_path.parts) > 1:
            resolved = hint_path if hint_path.is_absolute() else self.project_root / hint_path
            if resolved.exists():
                return str(resolved)
            if hint_path.exists():
                return str(hint_path)
            return None
        return self._resolve_core_name(hint)

    def _find_core_path(self, console, rom_path=None):
        system_id = resolve_system_id(console)

        # 1. Per-ROM override. A stale override (its core uninstalled) must not
        #    fail the launch: fall through to the console/automatic choice.
        if rom_path and hasattr(self.config_manager, "get_rom_core_override"):
            rom_core = self.config_manager.get_rom_core_override(rom_path)
            resolved = self._resolve_core_name(rom_core)
            if resolved:
                return resolved

        # 2. Per-console override (config hint: a path, or a bare filename).
        for hint in self.config_manager.get_retroarch_core_hints(system_id):
            resolved = self._resolve_core_hint(hint)
            if resolved:
                return resolved

        # 3. Automatic: the curated candidate list, first installed wins.
        for name in DEFAULT_CORE_CANDIDATES.get(system_id, []):
            resolved = self._resolve_core_name(name)
            if resolved:
                return resolved
        return None

    def _write_runtime_override(self, console, core_filename=None, shader_path=None, shader_enabled=False, state_slot=None):
        profile = self.config_manager.get_input_profile(console)
        devices = profile.get("devices", {}) or {}
        active_device = profile.get("active_device", "keyboard")
        device = devices.get(active_device, {})
        device_type = device.get("type", "keyboard")
        bindings = device.get("bindings", {})
        # Port 1 comes from the active device, exactly as before.
        overrides = to_retroarch_overrides(bindings, device_type, console=console)
        # Ports 2-4 are opt-in; when none is enabled the output is unchanged.
        for device_id in EXTRA_PORT_DEVICE_IDS:
            extra = devices.get(device_id) or {}
            if not extra.get("enabled"):
                continue
            overrides.update(
                to_retroarch_overrides(
                    extra.get("bindings", {}),
                    extra.get("type", "gamepad"),
                    console=console,
                    player=player_for_device(device_id),
                )
            )
        # Fold the analog stick onto the D-pad where the console wants it
        # (issue #71): RetroArch's native analog_dpad_mode, per port, so both
        # the stick and the D-pad steer without re-remapping.
        analog_mode = normalize_analog_dpad_mode(
            profile.get("analog_dpad_mode"), console
        )
        overrides["input_player1_analog_dpad_mode"] = f'"{analog_mode}"'
        for device_id in EXTRA_PORT_DEVICE_IDS:
            extra = devices.get(device_id) or {}
            if extra.get("enabled"):
                player = player_for_device(device_id)
                overrides[f"input_player{player}_analog_dpad_mode"] = f'"{analog_mode}"'
        # Turbo timing (issue #72): global RetroArch knobs; the turbo modifier
        # itself is a normal binding ("turbo" action) emitted per port above,
        # so without one bound these just restate the defaults.
        turbo = normalize_turbo_settings(profile.get("turbo"))
        overrides["input_turbo_period"] = f'"{turbo["period"]}"'
        overrides["input_turbo_duty_cycle"] = f'"{turbo["duty_cycle"]}"'
        overrides["input_turbo_mode"] = f'"{turbo["mode"]}"'
        overrides.update(DEFAULT_NOTIFICATION_OVERRIDES)
        required_for_core = get_required_for_core(console, core_filename) if core_filename else []
        if required_for_core:
            bios_dir = self.config_manager.get_console_bios_dir(console)
            overrides["system_directory"] = f'"{bios_dir}"'
        if shader_enabled and shader_path:
            overrides["video_shader_enable"] = '"true"'
            overrides["video_shader"] = f'"{shader_path}"'
        else:
            overrides["video_shader_enable"] = '"false"'

        # The UDP command channel (issue #69): loopback-only, and what lets
        # the in-app volume control reach the running game. The persisted
        # master volume seeds audio_volume so the level survives launches and
        # the live stepping starts from a known point.
        overrides["network_cmd_enable"] = '"true"'
        overrides["network_cmd_port"] = f'"{self.config_manager.get_network_cmd_port()}"'
        overrides["audio_volume"] = f'"{self.config_manager.get_master_volume_db():.1f}"'

        # Save states live in OpenEmux's own per-console tree (issue #73), so
        # the app can list and manage them; thumbnails give the manager
        # something to show. state_slot seeds "play from this state" launches.
        states_dir = self.config_manager.get_console_states_dir(console)
        states_dir.mkdir(parents=True, exist_ok=True)
        overrides["savestate_directory"] = f'"{states_dir}"'
        overrides["savestate_thumbnail_enable"] = '"true"'
        if state_slot is not None:
            overrides["state_slot"] = f'"{int(state_slot)}"'

        runtime_dir = self.config_manager.get_runtime_dir()
        runtime_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        override_path = runtime_dir / f"runtime_{resolve_system_id(console).lower()}_{timestamp}.cfg"

        lines = [f"{key} = {value}" for key, value in sorted(overrides.items())]
        override_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return str(override_path)

    def launch_process(self, rom_path, console, state_slot=None):
        system_id = resolve_system_id(console)
        launch_prefix, prefix_error = self._launch_prefix()
        if prefix_error:
            return None, prefix_error

        core_path = self._find_core_path(system_id, rom_path=rom_path)
        if not core_path:
            candidates = ", ".join(DEFAULT_CORE_CANDIDATES.get(system_id, []))
            return None, (
                f"No RetroArch core found for {system_id}. "
                f"Tried common core dirs and these core names: {candidates}. "
                "Configure runtime.retroarch.cores in config.yaml."
            )
        core_filename = Path(core_path).name
        missing_bios = find_missing_required_for_core(self.config_manager, system_id, core_filename)
        if missing_bios:
            bios_dir = self.config_manager.get_console_bios_dir(system_id)
            missing_str = ", ".join(missing_bios)
            return None, (
                f"Missing required BIOS for {system_id} ({core_filename}): {missing_str}. "
                f"Place BIOS files in: {bios_dir}"
            )

        shader_id = "disabled"
        if hasattr(self.config_manager, "get_shader_for_rom"):
            # Per-ROM override wins, falling back to the console setting.
            shader_id = normalize_shader_id(self.config_manager.get_shader_for_rom(rom_path, system_id))
        elif hasattr(self.config_manager, "get_shader_for_console"):
            shader_id = normalize_shader_id(self.config_manager.get_shader_for_console(system_id))
        shader_path = self.shader_catalog.resolve_shader_path(shader_id)

        cmd = [*launch_prefix, "-L", core_path]
        runtime_override = self._write_runtime_override(
            system_id,
            core_filename=core_filename,
            shader_path=shader_path,
            shader_enabled=bool(shader_path),
            state_slot=state_slot,
        )
        cmd.extend(["--appendconfig", runtime_override])
        if shader_path:
            cmd.extend(["--set-shader", shader_path])
        elif shader_id != "disabled":
            logger.info("shader preset not found, running without shader: console=%s shader=%s", system_id, shader_id)
        extra_flags = list(self.config_manager.get_retroarch_extra_flags())
        if "--verbose" not in extra_flags and "-v" not in extra_flags:
            extra_flags.append("--verbose")
        cmd.extend(extra_flags)
        cmd.append(rom_path)

        try:
            runtime_dir = self.config_manager.get_runtime_dir()
            runtime_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
            log_path = runtime_dir / f"retroarch_{resolve_system_id(console).lower()}_{timestamp}.log"
            cmd_path = runtime_dir / f"retroarch_{resolve_system_id(console).lower()}_{timestamp}.cmd"
            cmd_path.write_text(" ".join(cmd), encoding="utf-8")
            log_handle = open(log_path, "w", encoding="utf-8")
            proc = subprocess.Popen(
                cmd,
                cwd=os.getcwd(),
                env=os.environ.copy(),
                stdout=log_handle,
                stderr=subprocess.STDOUT,
            )
            # Keep a reference attached to process object to avoid GC closing the file descriptor too early.
            proc._openemux_log_handle = log_handle
            proc._openemux_log_path = str(log_path)
            logger.info(
                "retroarch launch started: console=%s core=%s rom=%s log=%s cmd_file=%s",
                system_id,
                core_filename,
                rom_path,
                log_path,
                cmd_path,
            )
            return proc, None
        except Exception as exc:
            return None, f"Failed to launch RetroArch: {exc}"
