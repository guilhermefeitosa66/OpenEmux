import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
import logging

from openemux.core import game_window_support
from openemux.core.audio_driver import resolve_audio_driver
from openemux.core.bios_catalog import get_required_for_core
from openemux.core.bios_manager import find_missing_required_for_core
from openemux.core.cores import CoreCatalog
from openemux.core import input_tuning
from openemux.core.input_actions import (
    conflicting_stock_hotkeys,
    to_retroarch_overrides,
    with_dpad_as_analog,
)
from openemux.core.input_profiles import (
    EXTRA_PORT_DEVICE_IDS,
    PLAYER1_DEVICE_IDS,
    device_type_for,
    normalize_analog_dpad_mode,
    normalize_controller_type,
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
            return [
                "flatpak-spawn",
                "--host",
                "flatpak",
                "run",
                # Without --die-with-parent the process handle we keep is
                # useless as a stop button: flatpak-spawn does forward our
                # SIGTERM to the host, but it stops at `flatpak run` -- bwrap
                # lives in its own systemd scope and RetroArch plays on inside
                # a sandbox nothing can reach. That is how closing the game
                # window left a game running with no window, audible and only
                # killable from a process manager. With the flag the sandbox
                # dies with the process we signalled.
                "--die-with-parent",
                RETROARCH_FLATPAK_ID,
            ], None

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
        # Port 1 gets *both* device maps, not just the "active" one.
        #
        # RetroArch keeps keyboard and joypad binds under separate keys --
        # input_player1_a vs input_player1_a_btn, input_enable_hotkey vs
        # input_enable_hotkey_btn -- so they never collide and both can be
        # live at once. Emitting only the active device meant a plugged-in
        # pad got none of OpenEmux's configuration: not the hotkeys, not the
        # analog stick axes. It still appeared to work because RetroArch's
        # own autoconfig maps the buttons, which is what made it so hard to
        # notice (issue #150).
        # A pad's D-pad can stand in for the left stick (issue #156).
        dpad_as_analog = bool(profile.get("dpad_drives_analog"))

        def _bindings_for(device_id, device, device_type):
            bindings = device.get("bindings", {})
            # Gamepads only: a keyboard already has the stick on i/j/k/l, and
            # pointing the arrows at it too would just be noise (issue #158).
            if dpad_as_analog and device_type == "gamepad":
                return with_dpad_as_analog(bindings)
            return bindings

        overrides = {}
        for device_id in PLAYER1_DEVICE_IDS:
            device = devices.get(device_id) or {}
            device_type = device_type_for(device_id)
            overrides.update(
                to_retroarch_overrides(
                    _bindings_for(device_id, device, device_type),
                    device_type,
                    console=console,
                )
            )
        # Ports 2-4 are opt-in; when none is enabled the output is unchanged.
        for device_id in EXTRA_PORT_DEVICE_IDS:
            extra = devices.get(device_id) or {}
            if not extra.get("enabled"):
                continue
            extra_type = extra.get("type", "gamepad")
            overrides.update(
                to_retroarch_overrides(
                    _bindings_for(device_id, extra, extra_type),
                    extra_type,
                    console=console,
                    player=player_for_device(device_id),
                )
            )
        # This file is appended to RetroArch's own config, so a stock hotkey
        # sitting on a key we just bound would still fire alongside ours --
        # `m` would mute and cycle the shader at the same time (issue #146).
        overrides.update(conflicting_stock_hotkeys(overrides))
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
        # Which controller the core is told is in each port (issue #151).
        # Left out entirely when unset, so the core keeps its own default --
        # PlayStation boots as a digital pad, and an analog game needs
        # DualShock chosen here just as it does in RetroArch.
        controller_type = normalize_controller_type(
            profile.get("controller_type"), console
        )
        if controller_type is not None:
            overrides["input_libretro_device_p1"] = f'"{controller_type}"'
            for device_id in EXTRA_PORT_DEVICE_IDS:
                extra = devices.get(device_id) or {}
                if extra.get("enabled"):
                    player = player_for_device(device_id)
                    overrides[f"input_libretro_device_p{player}"] = f'"{controller_type}"'
        # Deadzone, sensitivity, rumble, latency (issues #154, #155). Global
        # rather than per console: a worn stick drifts the same everywhere.
        # Only values that differ from RetroArch's own defaults are written.
        overrides.update(
            input_tuning.to_retroarch_overrides(self.config_manager.get_input_tuning())
        )
        # Turbo timing (issue #72): global RetroArch knobs; the turbo modifier
        # itself is a normal binding ("turbo" action) emitted per port above,
        # so without one bound these just restate the defaults.
        turbo = normalize_turbo_settings(profile.get("turbo"))
        overrides["input_turbo_period"] = f'"{turbo["period"]}"'
        overrides["input_turbo_duty_cycle"] = f'"{turbo["duty_cycle"]}"'
        overrides["input_turbo_mode"] = f'"{turbo["mode"]}"'
        # Select doubles as the gamepad hotkey modifier (issue #124), so a
        # *tap* has to still reach the game as Select while a *hold* opens a
        # hotkey. This is how many frames RetroArch waits before deciding;
        # without it Select feels unresponsive in games that use it.
        overrides["input_hotkey_block_delay"] = '"5"'
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

        # Nothing this file injects may outlive the launch that asked for it.
        # RetroArch saves its configuration on exit by default, and by then
        # the --appendconfig values *are* the configuration: every OpenEmux
        # launch was quietly writing its own launch-scoped settings into the
        # user's retroarch.cfg. That is how the game window's borderless
        # override made every later standalone RetroArch window borderless,
        # how the fullscreen hotkey ended up permanently unbound ("nul"), and
        # how OpenEmux's save-state directory became RetroArch's own. Core
        # options, remaps, saves, states and playlists live in their own
        # files and are unaffected -- only the global settings this launch
        # imposes stop being written back.
        overrides["config_save_on_exit"] = '"false"'

        # ...and what makes the QUIT command on that channel actually quit.
        # RetroArch defaults quit_press_twice to true, and the network QUIT
        # goes through the very same "quit key" path as the hotkey: the first
        # one only arms a two-second "press again to exit" window, so the
        # command the game window sends when it closes was a no-op and the
        # game kept playing. Measured against RetroArch 1.22.2: with the
        # default, a single QUIT datagram leaves the process alive; with this
        # override it exits cleanly (0), flushing battery saves on the way.
        # The stock RetroArch config is untouched -- this is per launch.
        overrides["quit_press_twice"] = '"false"'

        # Which audio driver RetroArch is told to use (issue #176). The global
        # retroarch.cfg may name one the RetroArch we launch was not built
        # with -- "pipewire" is the common case, and the vendored build has no
        # such driver. RetroArch then falls back to alsa, which fails on a
        # PipeWire host, and audio never starts. That reads to the user as
        # *speed*, not silence: emulation is paced off the audio clock, so
        # without it the game runs at the display's refresh rate.
        audio_driver = resolve_audio_driver(
            self.config_manager.get_retroarch_audio_driver()
        )
        if audio_driver:
            overrides["audio_driver"] = f'"{audio_driver}"'

        # Save states live in OpenEmux's own per-console tree (issue #73), so
        # the app can list and manage them; thumbnails give the manager
        # something to show. state_slot seeds "play from this state" launches.
        states_dir = self.config_manager.get_console_states_dir(console)
        states_dir.mkdir(parents=True, exist_ok=True)
        overrides["savestate_directory"] = f'"{states_dir}"'
        overrides["savestate_thumbnail_enable"] = '"true"'
        # The slot the save/load hotkeys start on. A "load this save" launch
        # names it; every other launch starts at 0 and moves from there with
        # the slot hotkeys, which is why the setting that used to pin it is
        # gone (issue #198).
        overrides["state_slot"] = f'"{int(state_slot or 0)}"'

        # The game window needs RetroArch in a plain windowed window it can
        # re-parent -- no fullscreen, no decorations, and no saving back the
        # position we impose. pause_nonactive off because X keyboard focus
        # moves between our window and the embedded one, and every such hop
        # would otherwise pause the game. Keyed off the same answer the UI
        # uses (issue #199): written without a wrapper to own the window, they
        # would leave the game floating borderless.
        if game_window_support.game_window_active(self.config_manager):
            overrides["video_fullscreen"] = '"false"'
            overrides["video_windowed_fullscreen"] = '"false"'
            overrides["video_window_show_decorations"] = '"false"'
            overrides["video_window_save_positions"] = '"false"'
            overrides["pause_nonactive"] = '"false"'
            # The wrapper owns the window: RetroArch toggling fullscreen on
            # a reparented child recreates/unparents its window and breaks
            # the embed, so the hotkey is unbound while embedded.
            overrides["input_toggle_fullscreen"] = '"nul"'
        else:
            # Stated rather than left alone, because earlier versions leaked
            # the block above into the user's own retroarch.cfg: a game
            # launched without a wrapper came up borderless and never paused
            # when it lost focus, and turning the setting off did not fix it.
            # Writing RetroArch's defaults back heals a config that was
            # already polluted. (The fullscreen hotkey heals itself: with no
            # wrapper the input profile's own binding is written above.)
            overrides["video_window_show_decorations"] = '"true"'
            overrides["pause_nonactive"] = '"true"'

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
            env = os.environ.copy()
            # On a Wayland session RetroArch would pick its native wayland
            # driver, whose window no X client can reparent. Without
            # WAYLAND_DISPLAY it falls back to X11 and lands on XWayland,
            # next to the app that main.py already put on the X11 backend.
            if game_window_support.game_window_active(self.config_manager):
                env.pop("WAYLAND_DISPLAY", None)
            proc = subprocess.Popen(
                cmd,
                cwd=os.getcwd(),
                env=env,
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

    # -- stopping a launched game ------------------------------------------
    # Two steps a caller escalates through (see RuntimeManager.stop_active),
    # here rather than there because what a signal actually reaches depends on
    # how the process was launched, which is this module's business.
    def terminate_process(self, proc):
        """SIGTERM the launched process; True when the signal went out."""
        try:
            proc.terminate()
            return True
        except Exception as exc:  # noqa: BLE001 - a dead process must not raise
            logger.warning("failed to terminate RetroArch: %s", exc)
            return False

    def kill_process(self, proc):
        """Last resort, for a game that ignored both QUIT and SIGTERM.

        Inside a Flatpak the handle we hold is the ``flatpak-spawn`` relay,
        and SIGKILL is the one signal it cannot forward -- killing the relay
        there would only orphan RetroArch for good. The sandbox is stopped on
        the host instead, and the relay is killed afterwards so nothing is
        left waiting on it.
        """
        killed = False
        if is_running_in_flatpak():
            killed = self._host_kill_retroarch()
        try:
            proc.kill()
            return True
        except Exception as exc:  # noqa: BLE001 - a dead process must not raise
            logger.warning("failed to kill RetroArch: %s", exc)
            return killed

    @staticmethod
    def _host_kill_retroarch():
        """Stop the RetroArch Flatpak instance from inside our own sandbox."""
        if not shutil.which("flatpak-spawn"):
            return False
        try:
            subprocess.run(
                ["flatpak-spawn", "--host", "flatpak", "kill", RETROARCH_FLATPAK_ID],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
            )
            logger.info("stopped the RetroArch Flatpak instance on the host")
            return True
        except Exception as exc:  # noqa: BLE001 - best effort, never raises
            logger.warning("failed to stop the RetroArch Flatpak instance: %s", exc)
            return False
