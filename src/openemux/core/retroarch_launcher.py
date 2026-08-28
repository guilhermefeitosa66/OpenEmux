import ctypes
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
import logging

from openemux.core import core_options, game_window_support, retroachievements
from openemux.core.appimage_env import host_env
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
from openemux.core.platform import (
    IS_WINDOWS,
    MACHINE,
    VENDORED_RETROARCH,
    bundled_core_dir,
    cfg_path,
    popen_kwargs,
    user_retroarch_dirs,
)
from openemux.core.shaders import ShaderCatalog, normalize_shader_id
from openemux.core.systems import SYSTEM_IDS, get_runtime_core_candidates, resolve_system_id

logger = logging.getLogger(__name__)


#: The AppImage runtime's own "do not mount me" switch.
APPIMAGE_EXTRACT_AND_RUN = "--appimage-extract-and-run"


def is_appimage(binary_path):
    """Is this path a (type-2) AppImage rather than a plain binary?"""
    return str(binary_path).lower().endswith(".appimage")


def appimage_flags(binary_path, libfuse_available=None, force=False):
    """The flags an AppImage needs to run on *this* host, if any.

    OpenEmux no longer ships one -- the vendored RetroArch is a plain binary in
    a portable tree since issue #328 -- but ``runtime.retroarch.binary`` may
    still name an AppImage the user downloaded themselves, and that is the case
    every line below exists for.

    ``--appimage-extract-and-run`` unpacks the image to a temp dir instead of
    mounting it, which is slower but needs no FUSE at all. Only used when
    ``libfuse.so.2`` is genuinely missing: on a host that has it, mounting is
    both faster and what the AppImage is built to do (issue #226).

    ``force`` is the retry after a launch that died mounting anyway. The
    ``libfuse.so.2`` probe answers "can this library be loaded", which is not
    the same question as "can this host mount a FUSE filesystem": a machine
    with the library but no ``/dev/fuse``, no ``fusermount``, or a
    ``fusermount`` that is not setuid passes the probe and still fails at the
    mount. That failure is only visible after the fact, in the launch log,
    so the retry is the only thing that can act on it (issue #248).
    """
    if not is_appimage(binary_path):
        return []
    if force:
        logger.info(
            "retrying the AppImage with --appimage-extract-and-run after a FUSE failure"
        )
        return [APPIMAGE_EXTRACT_AND_RUN]
    if libfuse_available is None:
        libfuse_available = RetroArchLauncher.libfuse2_available()
    if libfuse_available:
        return []
    logger.info(
        "libfuse.so.2 is missing; running the AppImage with --appimage-extract-and-run"
    )
    return [APPIMAGE_EXTRACT_AND_RUN]


# A RetroArch installed as a Flatpak keeps its cores here; still worth searching.
RETROARCH_FLATPAK_ID = "org.libretro.RetroArch"

DEFAULT_CORE_CANDIDATES = {system_id: get_runtime_core_candidates(system_id) for system_id in SYSTEM_IDS}

# Distro-packaged core locations. Empty on Windows, which has no equivalent
# convention -- cores there come from the bundled portable RetroArch.
# The Debian multiarch directory is named after the host triplet, so it is the
# one entry here that changes with the architecture -- and it is the one Ubuntu
# and Debian actually use for the libretro packages (issue #119).
DEFAULT_CORE_DIRS = (
    []
    if IS_WINDOWS
    else [
        "/usr/lib/libretro",
        "/usr/lib64/libretro",
        f"/usr/lib/{MACHINE}-linux-gnu/libretro",
        "/usr/local/lib/libretro",
    ]
)

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


#: Environment variables that point a toolkit at a Wayland compositor. While
#: embedding, RetroArch has to be an X client or the wrapper can never adopt
#: its window, and removing these is what actually pins it -- the config
#: override only stops a saved preference from fighting back (issue #267).
WAYLAND_ENV_VARS = ("WAYLAND_DISPLAY", "SDL_VIDEODRIVER")


def x11_only_env(env):
    """A copy of ``env`` with every Wayland pointer removed.

    ``WAYLAND_DISPLAY`` goes unconditionally -- its mere presence is what
    makes RetroArch's wayland context succeed. ``SDL_VIDEODRIVER`` only goes
    when it names wayland: a user who set it to ``x11`` already agrees with
    us, and unsetting it would just make SDL guess again.
    """
    cleaned = dict(env)
    cleaned.pop("WAYLAND_DISPLAY", None)
    if (cleaned.get("SDL_VIDEODRIVER") or "").strip().lower() == "wayland":
        cleaned.pop("SDL_VIDEODRIVER", None)
    return cleaned


class RetroArchLauncher:
    def __init__(self, project_root, config_manager):
        self.project_root = Path(project_root).expanduser()
        self.config_manager = config_manager
        self.shader_catalog = ShaderCatalog(
            runtime_dir=self.config_manager.get_runtime_dir(),
            project_root=self.project_root,
        )
        self.core_catalog = CoreCatalog(project_root=self.project_root)

    def _launch_prefix(self, force_extract=False):
        """Return (argv_prefix, error).

        Inside a Flatpak, delegate to the RetroArch Flatpak on the host via
        flatpak-spawn (both apps see the same absolute paths under the real
        home, which RetroArch reads via its own ``--filesystem=host``).
        Otherwise resolve a native/vendored RetroArch binary.
        """
        if is_running_in_flatpak():
            if not shutil.which("flatpak-spawn"):
                return None, "flatpak-spawn is unavailable; cannot reach RetroArch on the host."
            prefix = [
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
            ]
            if game_window_support.game_window_active(self.config_manager):
                # Stripping WAYLAND_DISPLAY from *our* environment does not
                # reach the sandbox -- `flatpak run` builds its own. Denying
                # the socket does, and it is what makes the RetroArch
                # Flatpak's --socket=fallback-x11 actually hand out X11, so
                # the window we are about to adopt is an X window (#267).
                prefix.append("--nosocket=wayland")
            prefix.append(RETROARCH_FLATPAK_ID)
            return prefix, None

        retroarch_path = self._resolve_retroarch_binary()
        if not retroarch_path:
            # Last resort before giving up: a RetroArch Flatpak on this same
            # machine. The message that follows is what the user sees, so it
            # names every way out rather than only the vendored one.
            flatpak_prefix = self._flatpak_fallback_prefix()
            if flatpak_prefix:
                return flatpak_prefix, None
            return None, (
                "RetroArch was not found. Install it from your distribution, "
                "or with `flatpak install flathub org.libretro.RetroArch`, or "
                "set runtime.retroarch.binary to a RetroArch of your own."
            )
        return [retroarch_path, *appimage_flags(retroarch_path, force=force_extract)], None

    def launches_an_appimage(self):
        """Would a launch right now go through an AppImage?

        Asked before retrying a failed launch unpacked: outside an AppImage
        there is nothing to unpack, so a FUSE-looking line in the log (a
        wrapper script echoing one, say) must not buy a second launch
        (issue #248). False for everything OpenEmux ships since issue #328;
        true when the user pointed the setting at an AppImage of their own.
        """
        if is_running_in_flatpak():
            return False
        return is_appimage(self._resolve_retroarch_binary() or "")

    @staticmethod
    def libfuse2_available(loader=None):
        """Whether the AppImage runtime's ``libfuse.so.2`` can be loaded.

        A type-2 AppImage mounts itself with FUSE 2. Several current
        distributions ship only FUSE 3 (or nothing), and there a RetroArch
        AppImage *starts* -- Popen succeeds -- and its runtime exits within a
        second with ``dlopen(): error loading libfuse.so.2`` written only to
        the launch log. Every launch died instantly and the app just said
        "finished (exit code 1)" (issue #226). That was the vendored AppImage
        then; since issue #328 it can only be a user's own.

        Asked the same way the runtime asks: by name, not by guessing from a
        package list. libfuse3 does not answer to this name and must not, or
        we would skip the fallback on a host that needs it.
        """
        loader = loader or ctypes.CDLL
        try:
            loader("libfuse.so.2")
            return True
        except OSError:
            return False

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
            # The vendored build for this platform comes first. Both are
            # portable trees fetched by scripts/vendor_retroarch.py: on Windows
            # retroarch.exe beside its DLLs, on Linux usr/bin/retroarch beside
            # the libraries it finds through RUNPATH (issue #328).
            self.project_root / VENDORED_RETROARCH,
            self.project_root / "vendors" / "retroarch.AppImage",
            self.project_root / "vendors" / "retroarch-assets" / "bin" / "retroarch",
        ]
        for candidate in vendor_candidates:
            if candidate.exists():
                return str(candidate)

        # Nothing vendored. On x86_64 that means `make vendor-retroarch` has
        # not run yet in this checkout; libretro publishes no ARM build at all,
        # so on aarch64 it is the normal case and dead-ending here would mean an
        # install that can never launch a game (issue #119). Both of these are
        # real RetroArch installs a user is likely to already have, and both
        # are how the ARM packages are expected to work until there is a
        # vendored build for them.
        packaged = shutil.which("retroarch")
        if packaged:
            return packaged
        return None

    def _flatpak_fallback_prefix(self):
        """``flatpak run org.libretro.RetroArch``, when that is all there is.

        Distinct from the Flatpak branch in ``_launch_prefix``: that one is
        OpenEmux running *inside* a sandbox and reaching the host through
        flatpak-spawn. This is OpenEmux running natively with no RetroArch of
        its own, on a machine where the only one installed is a Flatpak --
        which on aarch64, where libretro publishes no binary and
        ``org.libretro.RetroArch`` is on Flathub, is a likely shape.
        """
        if not shutil.which("flatpak"):
            return None
        try:
            listed = subprocess.run(
                ["flatpak", "info", RETROARCH_FLATPAK_ID],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if listed.returncode != 0:
            return None
        return ["flatpak", "run", "--die-with-parent", RETROARCH_FLATPAK_ID]

    def _core_search_dirs(self):
        real_home = get_real_home()
        home_dirs = [
            real_home / ".config" / "retroarch" / "cores",
            real_home / ".var" / "app" / RETROARCH_FLATPAK_ID / "config" / "retroarch" / "cores",
            self.project_root / "vendors" / "retroarch-assets" / "cores",
        ]
        # Where the bundled portable RetroArch keeps its cores, and where the
        # updater downloads them, on Windows.
        bundled = bundled_core_dir(self.project_root)
        if bundled:
            home_dirs.append(bundled)
        # A RetroArch the user installed themselves: searched, never written to.
        home_dirs.extend(user_retroarch_dirs())
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

    def _write_runtime_override(self, console, core_filename=None, shader_path=None, shader_enabled=False, state_slot=None, network_cmd_port=None):
        """Assemble this launch's ``--appendconfig`` file and return its path.

        Seven concerns, one file. They used to be one 170-line function whose
        every block carried its own comment explaining which concern it was --
        which is structure standing in for a name (issue #238). Each is a
        helper returning a dict now, and this is the thin writer that merges
        them, in the order a later key should win.
        """
        runtime_dir = self.config_manager.get_runtime_dir()
        runtime_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")

        # Save states live in OpenEmux's own per-console tree (issue #73), so
        # the app can list and manage them.
        states_dir = self.config_manager.get_console_states_dir(console)
        states_dir.mkdir(parents=True, exist_ok=True)

        overrides = {}
        overrides.update(self._input_overrides(console))
        overrides.update(self._joypad_driver_overrides())
        overrides.update(self._desktop_ui_overrides())
        overrides.update(DEFAULT_NOTIFICATION_OVERRIDES)
        overrides.update(self._bios_overrides(console, core_filename))
        overrides.update(self._shader_overrides(shader_path, shader_enabled))
        overrides.update(self._session_overrides(network_cmd_port))
        overrides.update(self._av_overrides())
        overrides.update(self._savestate_overrides(states_dir, state_slot))
        overrides.update(self._embed_overrides())
        # RetroAchievements does its own work inside RetroArch; what it needs
        # from us is the account (issue #300).
        overrides.update(
            retroachievements.runtime_overrides(
                getattr(self.config_manager, "achievements", None)
            )
        )

        # Core options live in their own file, not in the config, so
        # --appendconfig cannot carry them (issue #296). What it can carry is
        # the path RetroArch reads them from.
        options_path = self._write_core_options(
            console, core_filename, runtime_dir, timestamp
        )
        if options_path:
            overrides["core_options_path"] = f'"{cfg_path(options_path)}"'

        override_path = runtime_dir / f"runtime_{resolve_system_id(console).lower()}_{timestamp}.cfg"

        lines = [f"{key} = {value}" for key, value in sorted(overrides.items())]
        override_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return str(override_path)

    # ----- the pieces of the override file --------------------------------

    def _input_overrides(self, console):
        """Bindings, hotkeys, analog modes, controller types, tuning, turbo.

        Everything that comes out of the console's input profile, for every
        port it covers.
        """
        profile = self.config_manager.get_input_profile(console)
        devices = profile.get("devices", {}) or {}
        # A pad's D-pad can stand in for the left stick (issue #156).
        dpad_as_analog = bool(profile.get("dpad_drives_analog"))

        def _bindings_for(device, device_type):
            bindings = device.get("bindings", {})
            # Gamepads only: a keyboard already has the stick on i/j/k/l, and
            # pointing the arrows at it too would just be noise (issue #158).
            if dpad_as_analog and device_type == "gamepad":
                return with_dpad_as_analog(bindings)
            return bindings

        def _enabled_extra_ports():
            for device_id in EXTRA_PORT_DEVICE_IDS:
                extra = devices.get(device_id) or {}
                if extra.get("enabled"):
                    yield device_id, extra

        overrides = {}
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
        for device_id in PLAYER1_DEVICE_IDS:
            device = devices.get(device_id) or {}
            device_type = device_type_for(device_id)
            overrides.update(
                to_retroarch_overrides(
                    _bindings_for(device, device_type),
                    device_type,
                    console=console,
                )
            )
        # Ports 2-4 are opt-in; when none is enabled the output is unchanged.
        for device_id, extra in _enabled_extra_ports():
            extra_type = extra.get("type", "gamepad")
            overrides.update(
                to_retroarch_overrides(
                    _bindings_for(extra, extra_type),
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
        for device_id, _extra in _enabled_extra_ports():
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
            for device_id, _extra in _enabled_extra_ports():
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
        return overrides

    def _bios_overrides(self, console, core_filename):
        """Point the core at this console's BIOS folder, if it needs one."""
        if not core_filename or not get_required_for_core(console, core_filename):
            return {}
        bios_dir = self.config_manager.get_console_bios_dir(console)
        return {"system_directory": f'"{cfg_path(bios_dir)}"'}

    @staticmethod
    def _shader_overrides(shader_path, shader_enabled):
        """Turn the console's shader on, or say plainly that there is none."""
        if shader_enabled and shader_path:
            return {
                "video_shader_enable": '"true"',
                "video_shader": f'"{cfg_path(shader_path)}"',
            }
        return {"video_shader_enable": '"false"'}

    def _session_overrides(self, network_cmd_port):
        """The command channel, the volume, and keeping this launch's own.

        The UDP command channel (issue #69) is loopback-only, and what lets
        the in-app volume control reach the running game. The persisted
        master volume seeds audio_volume so the level survives launches and
        the live stepping starts from a known point.
        """
        # The port is the caller's: it is picked per launch so a standalone
        # RetroArch cannot share it with us (issue #227), and both sides of
        # the channel have to agree on the same number.
        if network_cmd_port is None:
            network_cmd_port = self.config_manager.get_network_cmd_port()
        return {
            "network_cmd_enable": '"true"',
            "network_cmd_port": f'"{int(network_cmd_port)}"',
            "audio_volume": f'"{self.config_manager.get_master_volume_db():.1f}"',
            # Nothing this file injects may outlive the launch that asked for
            # it. RetroArch saves its configuration on exit by default, and by
            # then the --appendconfig values *are* the configuration: every
            # OpenEmux launch was quietly writing its own launch-scoped
            # settings into the user's retroarch.cfg. That is how the game
            # window's borderless override made every later standalone
            # RetroArch window borderless, how the fullscreen hotkey ended up
            # permanently unbound ("nul"), and how OpenEmux's save-state
            # directory became RetroArch's own. Core options, remaps, saves,
            # states and playlists live in their own files and are unaffected
            # -- only the global settings this launch imposes stop being
            # written back.
            "config_save_on_exit": '"false"',
            # ...and what makes the QUIT command on that channel actually
            # quit. RetroArch defaults quit_press_twice to true, and the
            # network QUIT goes through the very same "quit key" path as the
            # hotkey: the first one only arms a two-second "press again to
            # exit" window, so the command the game window sends when it
            # closes was a no-op and the game kept playing. Measured against
            # RetroArch 1.22.2: with the default, a single QUIT datagram
            # leaves the process alive; with this override it exits cleanly
            # (0), flushing battery saves on the way. The stock RetroArch
            # config is untouched -- this is per launch.
            "quit_press_twice": '"false"',
        }

    @staticmethod
    def _joypad_driver_overrides():
        """Pin the joypad driver on Windows so both ends agree on the numbers.

        A binding token is an *index* -- ``"3"`` is "the fourth button as this
        driver counts them" -- so the driver that produced it and the driver
        that reads it have to be the same one. On Linux they already are:
        OpenEmux reads evdev with udev's numbering and RetroArch defaults to
        its ``udev`` joypad driver.

        On Windows RetroArch defaults to ``xinput``, whose button order is its
        own, while OpenEmux reads the pad through SDL2 (``gamepad_sdl``). Left
        alone, a remap captured in OpenEmux would bind a different button in
        the game. Naming the driver here costs nothing when the numbering
        happens to agree and is the difference between working and silently
        wrong when it does not.

        Launch-scoped like every other value in this file: ``--appendconfig``
        with ``config_save_on_exit = false``, so a user's own RetroArch keeps
        whatever driver they chose (issue #118).
        """
        if not IS_WINDOWS:
            return {}
        return {"input_joypad_driver": '"sdl2"'}

    @staticmethod
    def _desktop_ui_overrides():
        """Keep RetroArch's own desktop UI out of a game OpenEmux launched.

        On Windows the win32 UI companion starts with every launch and draws a
        menu bar across the game's window, and the Qt "WIMP" desktop menu is
        initialised behind it. Both are on by default -- the vendored build's
        own retroarch.default.cfg documents `ui_companion_start_on_boot = true`
        and `desktop_menu_enable = true` -- and OpenEmux never said otherwise,
        so a game opened from the library came up wearing the emulator's
        interface (issue #367).

        Windows-only for the same reason the joypad driver above is: the
        vendored Linux build has no WIMP UI to start, so writing it there would
        be a line that reads as if it were load-bearing and is not.

        This is not the game window. That wrapper -- pause, save state, volume
        -- is X11 reparenting and has no Windows equivalent; Preferences says
        so there (issue #118). This only stops RetroArch from putting its own
        menu in front of the game.

        Launch-scoped like everything else in this file: ``--appendconfig``
        with ``config_save_on_exit = false``, so a user's own RetroArch keeps
        whatever they chose.
        """
        if not IS_WINDOWS:
            return {}
        return {
            "ui_companion_start_on_boot": '"false"',
            "desktop_menu_enable": '"false"',
        }

    def _av_overrides(self):
        """Which audio driver RetroArch is told to use (issue #176).

        The global retroarch.cfg may name one the RetroArch we launch was not
        built with -- "pipewire" is the common case, and the vendored build
        has no such driver. RetroArch then falls back to alsa, which fails on
        a PipeWire host, and audio never starts. That reads to the user as
        *speed*, not silence: emulation is paced off the audio clock, so
        without it the game runs at the display's refresh rate.
        """
        audio_driver = resolve_audio_driver(
            self.config_manager.get_retroarch_audio_driver()
        )
        return {"audio_driver": f'"{audio_driver}"'} if audio_driver else {}

    @staticmethod
    def _savestate_overrides(states_dir, state_slot):
        """Park the states in OpenEmux's own tree, on the asked-for slot.

        Thumbnails give the state manager something to show. The slot is the
        one the save/load hotkeys start on: a "load this save" launch names
        it; every other launch starts at 0 and moves from there with the slot
        hotkeys, which is why the setting that used to pin it is gone
        (issue #198).
        """
        return {
            "savestate_directory": f'"{cfg_path(states_dir)}"',
            "savestate_thumbnail_enable": '"true"',
            "state_slot": f'"{int(state_slot or 0)}"',
        }

    def _embed_overrides(self):
        """What the game window needs, or what heals a config it polluted.

        Keyed off the same answer the UI uses (issue #199): written without a
        wrapper to own the window, they would leave the game floating
        borderless.
        """
        if not game_window_support.game_window_active(self.config_manager):
            # Stated rather than left alone, because earlier versions leaked
            # the block below into the user's own retroarch.cfg: a game
            # launched without a wrapper came up borderless and never paused
            # when it lost focus, and turning the setting off did not fix it.
            # Writing RetroArch's defaults back heals a config that was
            # already polluted. (The fullscreen hotkey heals itself: with no
            # wrapper the input profile's own binding is written above.)
            return {
                "video_window_show_decorations": '"true"',
                "pause_nonactive": '"true"',
            }

        # The game window needs RetroArch in a plain windowed window it can
        # re-parent -- no fullscreen, no decorations, and no saving back the
        # position we impose. pause_nonactive off because X keyboard focus
        # moves between our window and the embedded one, and every such hop
        # would otherwise pause the game.
        overrides = {
            "video_fullscreen": '"false"',
            "video_windowed_fullscreen": '"false"',
            "video_window_show_decorations": '"false"',
            "video_window_save_positions": '"false"',
            "pause_nonactive": '"false"',
            # Which backend RetroArch talks to is the whole embed: an X
            # client can only reparent another X client. Dropping the
            # Wayland socket from its environment (see launch_process) is
            # what actually lands it on X11/XWayland, but a retroarch.cfg
            # that *names* the wayland context would override that. Empty is
            # RetroArch's own written default and means "probe" -- so this
            # neutralizes a saved pin without imposing one. Not "x11": that
            # is not a registered ident (the real one is "x"), and naming a
            # context a build lacks would leave the game with no video at all.
            "video_context_driver": '""',
            # Keep RetroArch's output in the log file the launcher opened for
            # it. With log_to_file on, RetroArch writes to its own file
            # instead, our runtime log stays empty, and the game window loses
            # the one early signal that tells it RetroArch is not an X client.
            "log_to_file": '"false"',
        }
        # The wrapper owns the window: RetroArch toggling fullscreen on a
        # reparented child recreates/unparents its window and breaks the
        # embed, so the hotkey is unbound while embedded -- on the pad as
        # well as the keyboard. Only the keyboard one was unbound before, and
        # the gamepad binding written from the input profile
        # (input_toggle_fullscreen_btn) survived: one press of that button
        # destroyed a working embed (issue #267).
        for suffix in ("", "_btn", "_axis"):
            overrides[f"input_toggle_fullscreen{suffix}"] = '"nul"'
        return overrides

    def _write_core_options(self, console, core_filename, runtime_dir, timestamp):
        """This launch's core-options file, or ``None`` when there is nothing to say.

        Written only when the user actually chose something: pointing
        RetroArch at our file replaces the one it would have read, and doing
        that for a console nobody configured would quietly drop whatever they
        set inside RetroArch itself. What they set there is carried over
        anyway -- ours go on top of it, not instead of it.
        """
        store = getattr(self.config_manager, "core_options", None)
        if store is None or not core_filename:
            return None
        chosen = store.get_for_console(resolve_system_id(console), core_filename)
        if not chosen:
            return None
        inherited = self._inherited_core_options(core_filename)
        path = runtime_dir / f"coreopts_{resolve_system_id(console).lower()}_{timestamp}.cfg"
        try:
            path.write_text(
                core_options.render_options_file(chosen, inherited), encoding="utf-8"
            )
        except OSError as exc:
            logger.warning("core options: cannot write %s: %s", path, exc)
            return None
        logger.info(
            "core options written: console=%s core=%s count=%d path=%s",
            console, core_filename, len(chosen), path,
        )
        return str(path)

    def _inherited_core_options(self, core_filename):
        """What the user already configured for this core inside RetroArch.

        RetroArch files those per core under ``config/<Core Name>/<Core
        Name>.opt``, and the display name is its own lookup -- but every
        option a core owns is prefixed with the core's own name, so the file
        can be recognised by its contents instead.
        """
        prefix = core_options.option_prefix(core_filename)
        if not prefix:
            return {}
        config_root = Path.home() / ".config" / "retroarch" / "config"
        if not config_root.is_dir():
            return {}
        try:
            candidates = sorted(config_root.glob("*/*.opt"))
        except OSError:
            return {}
        for candidate in candidates:
            values = core_options.read_options_file(candidate)
            if any(key.startswith(prefix) for key in values):
                return values
        return {}

    def launch_process(self, rom_path, console, state_slot=None, network_cmd_port=None,
                       force_extract=False):
        """Start the game, or say why it could not start.

        Everything before the ``Popen`` writes to disk -- the states dir, the
        runtime dir, the ``--appendconfig`` override, an input profile being
        normalised on load -- and none of it used to be guarded. A full disk or
        a read-only home raised out of here into the GTK click handler, where
        PyGObject prints a traceback and swallows it: the button simply did
        nothing, with no toast (issue #226). Every failure has to come back as
        a message, because a message is the only thing the caller can show.
        """
        try:
            return self._launch_process(
                rom_path, console, state_slot, network_cmd_port, force_extract
            )
        except Exception as exc:
            logger.exception("retroarch launch failed before starting the process")
            return None, f"Could not start the game: {exc}"

    def _launch_process(self, rom_path, console, state_slot=None, network_cmd_port=None,
                        force_extract=False):
        system_id = resolve_system_id(console)
        launch_prefix, prefix_error = self._launch_prefix(force_extract=force_extract)
        if prefix_error:
            return None, prefix_error

        core_path = self._find_core_path(system_id, rom_path=rom_path)
        if not core_path:
            candidates = ", ".join(DEFAULT_CORE_CANDIDATES.get(system_id, []))
            message = (
                f"No RetroArch core found for {system_id}. "
                f"Tried common core dirs and these core names: {candidates}."
            )
            if MACHINE == "x86_64":
                message += " Configure runtime.retroarch.cores in config.yaml."
            else:
                # The buildbot builds 153 cores for aarch64 against 217 for
                # x86_64, so on ARM "not installed" and "does not exist" look
                # identical from here -- and telling somebody to configure a
                # core that was never built for their machine sends them
                # looking for a file they cannot get (issue #119).
                message += (
                    f" The libretro buildbot builds fewer cores for {MACHINE}"
                    " than for x86_64, so this console may have none at all."
                    " Settings \u2192 Cores lists what is installed."
                )
            return None, message
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
            network_cmd_port=network_cmd_port,
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

        log_handle = None
        try:
            runtime_dir = self.config_manager.get_runtime_dir()
            runtime_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
            log_path = runtime_dir / f"retroarch_{resolve_system_id(console).lower()}_{timestamp}.log"
            cmd_path = runtime_dir / f"retroarch_{resolve_system_id(console).lower()}_{timestamp}.cmd"
            cmd_path.write_text(" ".join(cmd), encoding="utf-8")
            log_handle = open(log_path, "w", encoding="utf-8")
            # The session's environment, not this process's. Running from an
            # AppImage, everything started under $APPDIR -- and the vendored
            # RetroArch is -- is handed the bundle's loader path, LD_PRELOAD,
            # PYTHONHOME and GTK/GI/pixbuf caches, so RetroArch resolved its
            # libraries against the stack bundled for a GTK4 app rather than
            # its own (issue #249). Outside an AppImage this is a plain copy.
            # LD_LIBRARY_PATH outranks RUNPATH, and RUNPATH is how the vendored
            # tree finds its own 56 libraries, so dropping it is what keeps the
            # unwrapped RetroArch loading its own (issue #328).
            env = host_env(os.environ)
            # On a Wayland session RetroArch would pick its native wayland
            # driver, whose window no X client can reparent. Stripped of the
            # Wayland pointers it falls back to X11 and lands on XWayland,
            # next to the app that main.py already put on the X11 backend.
            if game_window_support.game_window_active(self.config_manager):
                env = x11_only_env(env)
            proc = subprocess.Popen(
                cmd,
                cwd=os.getcwd(),
                env=env,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                # CREATE_NO_WINDOW on Windows, nothing on Linux: without it a
                # console window flashes up behind the game on every launch.
                **popen_kwargs(),
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
            # Popen raising (the binary vanished, ENOEXEC) left this handle
            # open: one leaked descriptor per failed launch.
            if log_handle is not None:
                try:
                    log_handle.close()
                except Exception:
                    pass
            logger.warning("retroarch launch failed: error=%s", exc)
            return None, f"Failed to launch RetroArch: {exc}"

    # -- stopping a launched game ------------------------------------------
    # Two steps a caller escalates through (see RuntimeManager.stop_active),
    # here rather than there because what a signal actually reaches depends on
    # how the process was launched, which is this module's business.
    def terminate_process(self, proc):
        """SIGTERM the launched process; True when the signal went out.

        On Windows ``terminate()`` is ``TerminateProcess``, which is immediate
        and gives RetroArch no chance to flush a battery save -- there is no
        SIGTERM to deliver. That is survivable because this is not the first
        thing tried: ``RuntimeManager.stop_active`` sends the UDP ``QUIT``
        command first (``network_cmd_enable`` is set in the runtime override),
        which exits RetroArch cleanly with saves written. This stays the
        escalation for a game that ignored it.
        """
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
