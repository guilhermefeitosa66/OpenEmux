import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from openemux.core import game_window_support
from openemux.core.input_actions import ANALOG_STICK_BINDINGS
from openemux.core.core_options import CoreOptionsStore
from openemux.core.platform import CORE_SUFFIX, VENDORED_RETROARCH
from openemux.core.retroarch_launcher import (
    APPIMAGE_EXTRACT_AND_RUN,
    RetroArchLauncher,
    appimage_flags,
    x11_only_env,
)


def _close_log(proc):
    """Close the launch log the mocked process is holding open.

    In the app ``RuntimeManager._clear_active`` does this when the game ends;
    a Mock never ends, so the tests have to.
    """
    handle = getattr(proc, "_openemux_log_handle", None)
    if handle is not None and not isinstance(handle, Mock):
        handle.close()


class _DummyConfig:
    def __init__(self, base_dir, binary_path, core_path, shader_by_console=None, core_hints=None):
        self.base_dir = Path(base_dir)
        self.binary_path = str(binary_path)
        self.core_path = str(core_path)
        self.input_dir = self.base_dir / "input"
        self.runtime_dir = self.base_dir / "runtime"
        self.shader_by_console = shader_by_console or {}
        self.input_profile = None
        # When set, overrides the default hint of [core_path]; [] falls through
        # to the automatic candidate list.
        self.core_hints = core_hints
        self.rom_core = None
        self.input_tuning = {}
        # "inherit" keeps the override free of audio_driver, so the existing
        # assertions stay about what they were written for; the #176 tests set
        # it explicitly.
        self.audio_driver = "inherit"
        self.game_window = False
        # Per-console core options (issue #296); None means "no store", which
        # is what every test that predates them expects.
        self.core_options = None

    def get_retroarch_binary(self):
        return self.binary_path

    def get_retroarch_core_hints(self, _console):
        return self.core_hints if self.core_hints is not None else [self.core_path]

    def get_rom_core_override(self, _rom_path):
        return self.rom_core

    def get_retroarch_extra_flags(self):
        return []

    def get_retroarch_audio_driver(self):
        return self.audio_driver

    def get_input_profile(self, _console):
        if self.input_profile is not None:
            return self.input_profile
        return {
            "active_device": "keyboard",
            "devices": {
                "keyboard": {
                    "type": "keyboard",
                    "bindings": {"a": "z", "b": "x"},
                }
            },
        }

    def get_runtime_dir(self):
        return self.runtime_dir

    def get_console_bios_dir(self, console):
        return self.base_dir / "roms" / console / "bios"

    def get_shader_for_console(self, console):
        return self.shader_by_console.get(console, "disabled")

    def get_network_cmd_port(self):
        return 55355

    def get_input_tuning(self):
        # Whatever the test does not care about stays at RetroArch's own
        # defaults, which write nothing (issues #154, #155).
        return dict(self.input_tuning)

    def get_master_volume_db(self):
        return -6.0

    def get_console_states_dir(self, console):
        return self.base_dir / "states" / console

    def get_game_window_enabled(self):
        # Off unless a test says otherwise: the embed overrides rewrite how
        # RetroArch's own window behaves, and every other assertion here is
        # about the standalone launch.
        return self.game_window


class RetroArchLauncherTests(unittest.TestCase):
    def setUp(self):
        # The embed verdict and the failure latch are module-global; a test
        # elsewhere that latched them would silently push every override
        # here into the "no wrapper" branch.
        game_window_support.reset_embed_state()
        self.addCleanup(game_window_support.reset_embed_state)

    def test_resolve_retroarch_binary_from_project_relative_path(self):
        with TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            binary = base / VENDORED_RETROARCH
            binary.parent.mkdir(parents=True, exist_ok=True)
            binary.write_text("", encoding="utf-8")
            core = base / f"mgba_libretro{CORE_SUFFIX}"
            core.write_text("", encoding="utf-8")
            cfg = _DummyConfig(base, VENDORED_RETROARCH, core)
            launcher = RetroArchLauncher(base, cfg)

            resolved = launcher._resolve_retroarch_binary()

        self.assertEqual(resolved, str(binary))

    def test_the_vendored_retroarch_is_launched_as_a_plain_binary(self):
        # No --appimage-extract-and-run, no libfuse probe, nothing to unpack:
        # what OpenEmux vendors is the portable tree upstream's AppImage wraps,
        # so a host with no FUSE at all launches it the same way (issue #328).
        with TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            binary = base / VENDORED_RETROARCH
            binary.parent.mkdir(parents=True, exist_ok=True)
            binary.write_text("", encoding="utf-8")
            core = base / f"mgba_libretro{CORE_SUFFIX}"
            core.write_text("", encoding="utf-8")
            launcher = RetroArchLauncher(base, _DummyConfig(base, VENDORED_RETROARCH, core))
            with patch.object(
                RetroArchLauncher, "libfuse2_available", staticmethod(lambda: False)
            ):
                prefix, error = launcher._launch_prefix()
            self.assertFalse(launcher.launches_an_appimage())

        self.assertIsNone(error)
        self.assertEqual(prefix, [str(binary)])

    def test_per_rom_core_override_wins_and_stale_falls_back(self):
        with TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            cores_dir = base / "cores"
            cores_dir.mkdir()
            (cores_dir / f"snes9x_libretro{CORE_SUFFIX}").write_text("", encoding="utf-8")
            (cores_dir / f"bsnes_libretro{CORE_SUFFIX}").write_text("", encoding="utf-8")

            cfg = _DummyConfig(base, base / "retroarch", base / "unused.so", core_hints=[])
            launcher = RetroArchLauncher(base, cfg)
            # Resolve bare filenames against our temp core dir, not the system.
            launcher._core_search_dirs = lambda: [str(cores_dir)]

            # A per-ROM override wins over the automatic candidate list.
            cfg.rom_core = f"bsnes_libretro{CORE_SUFFIX}"
            resolved = launcher._find_core_path("SFC", rom_path="/g/x.sfc")
            self.assertTrue(resolved.endswith(f"bsnes_libretro{CORE_SUFFIX}"))

            # A stale override (core uninstalled) falls back to the candidate.
            cfg.rom_core = f"does_not_exist_libretro{CORE_SUFFIX}"
            resolved = launcher._find_core_path("SFC", rom_path="/g/x.sfc")
            self.assertTrue(resolved.endswith(f"snes9x_libretro{CORE_SUFFIX}"))

    def test_launch_blocks_when_required_bios_missing(self):
        with TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            binary = base / "retroarch"
            core = base / f"mednafen_psx_libretro{CORE_SUFFIX}"
            binary.write_text("", encoding="utf-8")
            core.write_text("", encoding="utf-8")
            cfg = _DummyConfig(base, binary, core)
            launcher = RetroArchLauncher(base, cfg)

            with patch("openemux.core.retroarch_launcher.subprocess.Popen") as popen_mock:
                proc, error = launcher.launch_process("/tmp/game.cue", "PS")

        self.assertIsNone(proc)
        self.assertIsNotNone(error)
        self.assertIn("Missing required BIOS", error)
        popen_mock.assert_not_called()

    def test_launch_writes_system_directory_and_runs_when_bios_present(self):
        with TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            binary = base / "retroarch"
            core = base / f"mednafen_psx_libretro{CORE_SUFFIX}"
            binary.write_text("", encoding="utf-8")
            core.write_text("", encoding="utf-8")
            cfg = _DummyConfig(base, binary, core)
            bios_dir = cfg.get_console_bios_dir("PS")
            bios_dir.mkdir(parents=True, exist_ok=True)
            (bios_dir / "scph5501.bin").write_bytes(b"bios")
            launcher = RetroArchLauncher(base, cfg)

            with patch("openemux.core.retroarch_launcher.subprocess.Popen") as popen_mock:
                popen_mock.return_value = Mock()
                proc, error = launcher.launch_process("/tmp/game.cue", "PS")
                _close_log(proc)

            runtime_cfgs = list((base / "runtime").glob("runtime_ps_*.cfg"))
            self.assertTrue(runtime_cfgs)
            content = runtime_cfgs[0].read_text(encoding="utf-8")

        self.assertIsNotNone(proc)
        self.assertIsNone(error)
        self.assertIn("system_directory", content)

    def test_launch_applies_shader_when_available(self):
        with TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            binary = base / "retroarch"
            core = base / f"mgba_libretro{CORE_SUFFIX}"
            binary.write_text("", encoding="utf-8")
            core.write_text("", encoding="utf-8")
            shader = base / "runtime" / "shaders_glsl" / "handheld" / "dot.glslp"
            shader.parent.mkdir(parents=True, exist_ok=True)
            shader.write_text("shader preset", encoding="utf-8")
            cfg = _DummyConfig(base, binary, core, shader_by_console={"GBA": "dot"})
            launcher = RetroArchLauncher(base, cfg)

            with patch("openemux.core.retroarch_launcher.subprocess.Popen") as popen_mock:
                popen_mock.return_value = Mock()
                proc, error = launcher.launch_process("/tmp/game.gba", "GBA")
                _close_log(proc)
                args, kwargs = popen_mock.call_args
                cmd = args[0]
            runtime_cfgs = list((base / "runtime").glob("runtime_gba_*.cfg"))
            self.assertTrue(runtime_cfgs)
            runtime_content = runtime_cfgs[0].read_text(encoding="utf-8")

        self.assertIsNotNone(proc)
        self.assertIsNone(error)
        self.assertIn("--set-shader", cmd)
        self.assertIn(str(shader), cmd)
        self.assertIn('video_shader_enable = "true"', runtime_content)
        self.assertIn(f'video_shader = "{shader}"', runtime_content)

    # ----- multi-port -----------------------------------------------------
    def _override_lines(self, profile):
        with TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            cfg = _DummyConfig(base, base / "retroarch", base / f"mgba_libretro{CORE_SUFFIX}")
            cfg.input_profile = profile
            launcher = RetroArchLauncher(base, cfg)
            path = launcher._write_runtime_override("GBA")
            return Path(path).read_text(encoding="utf-8").splitlines()

    def test_override_emits_the_analog_dpad_mode_per_port(self):
        # Issue #71: the per-console profile decides whether the stick also
        # drives the D-pad; every enabled port gets the same mode.
        profile = {
            "active_device": "gamepad_p1",
            "analog_dpad_mode": 1,
            "devices": {
                "gamepad_p1": {"type": "gamepad", "bindings": {"a": "0"}},
                "gamepad_p2": {"type": "gamepad", "bindings": {"a": "0"}, "enabled": True},
            },
        }
        lines = self._override_lines(profile)
        self.assertIn('input_player1_analog_dpad_mode = "1"', lines)
        self.assertIn('input_player2_analog_dpad_mode = "1"', lines)

    def test_override_declares_the_analog_stick_axes(self):
        # Issue #126: analog_dpad_mode = "1" folds the left stick onto the
        # D-pad only if RetroArch knows which axes the stick is. Nothing else
        # in a profile says so, and without these keys mode 1 silently does
        # nothing -- the stick simply never steered.
        profile = {
            "active_device": "gamepad_p1",
            "devices": {"gamepad_p1": {"type": "gamepad", "bindings": {"a": "0"}}},
        }
        lines = self._override_lines(profile)
        self.assertIn('input_player1_analog_dpad_mode = "1"', lines)
        for suffix, token in ANALOG_STICK_BINDINGS.items():
            self.assertIn(f'input_player1_{suffix}_axis = "{token}"', lines)

    def test_analog_native_consoles_still_declare_the_axes(self):
        # N64/PS keep analog_dpad_mode off (folding would steal the stick from
        # the game) but the stick has to work natively there, which it cannot
        # do unless the axes are declared.
        with TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            cfg = _DummyConfig(base, base / "retroarch", base / "core.so")
            cfg.input_profile = {
                "active_device": "gamepad_p1",
                "devices": {"gamepad_p1": {"type": "gamepad", "bindings": {"a": "0"}}},
            }
            launcher = RetroArchLauncher(base, cfg)
            lines = Path(launcher._write_runtime_override("N64")).read_text(
                encoding="utf-8"
            ).splitlines()
        self.assertIn('input_player1_analog_dpad_mode = "0"', lines)
        self.assertIn('input_player1_l_x_plus_axis = "+0"', lines)

    def test_port_one_carries_both_the_keyboard_and_the_pad(self):
        # Issue #150: RetroArch keeps keyboard and joypad binds under separate
        # keys, so both can be live at once. Emitting only the "active" device
        # meant a plugged-in pad got none of OpenEmux's configuration -- no
        # hotkeys, no analog axes -- while still appearing to work through
        # RetroArch's own autoconfig.
        profile = {
            "active_device": "keyboard",
            "devices": {
                "keyboard": {"type": "keyboard", "bindings": {"a": "z"}},
                "gamepad_p1": {"type": "gamepad", "bindings": {"a": "0"}},
            },
        }
        lines = self._override_lines(profile)
        self.assertIn('input_player1_a = "z"', lines)
        self.assertIn('input_player1_a_btn = "0"', lines)
        self.assertIn('input_player1_l_x_plus_axis = "+0"', lines)

    def test_the_pad_is_configured_even_when_the_profile_says_keyboard(self):
        profile = {
            "active_device": "keyboard",
            "devices": {
                "keyboard": {"type": "keyboard", "bindings": {"a": "z"}},
                "gamepad_p1": {"type": "gamepad", "bindings": {}},
            },
        }
        lines = self._override_lines(profile)
        # The pad hotkeys from issue #124 reach RetroArch too.
        self.assertIn('input_enable_hotkey_btn = "6"', lines)
        self.assertIn('input_save_state_btn = "2"', lines)

    def test_extra_ports_declare_their_own_axes(self):
        profile = {
            "active_device": "gamepad_p1",
            "devices": {
                "gamepad_p1": {"type": "gamepad", "bindings": {"a": "0"}},
                "gamepad_p2": {"type": "gamepad", "bindings": {"a": "0"}, "enabled": True},
            },
        }
        lines = self._override_lines(profile)
        self.assertIn('input_player2_l_y_minus_axis = "-1"', lines)

    def test_override_gives_the_hotkey_modifier_a_block_delay(self):
        # Issue #124: Select is both a gameplay button and the hotkey
        # modifier, so RetroArch has to wait a few frames before deciding
        # which one a press was -- otherwise a tap never reaches the game.
        lines = self._override_lines(None)
        self.assertIn('input_hotkey_block_delay = "5"', lines)

    def test_override_analog_dpad_mode_defaults_by_console(self):
        # No mode in the profile: GBA (digital-only) folds the left stick in.
        lines = self._override_lines(None)
        self.assertIn('input_player1_analog_dpad_mode = "1"', lines)

    def test_override_owns_the_savestate_directory(self):
        # Issue #73: states land in OpenEmux's per-console tree. A plain
        # launch starts on slot 0 -- the setting that used to pin a slot is
        # gone (issue #198), so the hotkeys move it from there.
        lines = self._override_lines(None)
        self.assertTrue(any(line.startswith('savestate_directory = "') for line in lines))
        self.assertTrue(any("/states/GBA" in line for line in lines))
        self.assertIn('savestate_thumbnail_enable = "true"', lines)
        self.assertIn('state_slot = "0"', lines)

    def _game_window_override_lines(self, enabled, embeddable=True):
        with TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            cfg = _DummyConfig(base, base / "retroarch", base / f"mgba_libretro{CORE_SUFFIX}")
            cfg.game_window = enabled
            launcher = RetroArchLauncher(base, cfg)
            with patch(
                "openemux.core.game_window_support.embedding_possible",
                return_value=embeddable,
            ):
                path = launcher._write_runtime_override("GBA")
            return Path(path).read_text(encoding="utf-8").splitlines()

    def test_override_hands_retroarch_a_window_the_game_window_can_adopt(self):
        # Issue #199: re-parenting needs a plain windowed window, and the
        # fullscreen hotkey has to go -- toggling it recreates the window and
        # breaks the embed.
        lines = self._game_window_override_lines(True)
        self.assertIn('video_fullscreen = "false"', lines)
        self.assertIn('video_window_show_decorations = "false"', lines)
        self.assertIn('video_window_save_positions = "false"', lines)
        self.assertIn('pause_nonactive = "false"', lines)
        self.assertIn('input_toggle_fullscreen = "nul"', lines)

    def test_override_unbinds_the_pads_fullscreen_button_too(self):
        # Only the keyboard binding used to go. The gamepad one was still
        # written from the input profile, so one press of that button made
        # RetroArch recreate its window and the embed died with it (#267).
        lines = self._game_window_override_lines(True)
        self.assertIn('input_toggle_fullscreen_btn = "nul"', lines)
        self.assertIn('input_toggle_fullscreen_axis = "nul"', lines)

    def test_override_stops_a_saved_config_from_forcing_a_wayland_context(self):
        # An X client can only reparent another X client. Dropping the
        # Wayland socket from RetroArch's environment is what lands it on
        # X11, but a retroarch.cfg naming the wayland context would override
        # that -- empty is RetroArch's own "probe" value (#267).
        lines = self._game_window_override_lines(True)
        self.assertIn('video_context_driver = ""', lines)

    def test_override_keeps_retroarchs_output_in_our_log(self):
        # The game window reads that log to find out whether RetroArch is an
        # X client at all; log_to_file sends it somewhere else and leaves
        # ours empty (#267).
        lines = self._game_window_override_lines(True)
        self.assertIn('log_to_file = "false"', lines)

    def test_the_embed_only_overrides_stay_out_of_a_standalone_launch(self):
        lines = self._game_window_override_lines(False)
        self.assertNotIn('video_context_driver = ""', lines)
        self.assertNotIn('input_toggle_fullscreen_btn = "nul"', lines)

    def test_a_latched_embed_failure_heals_the_window_for_later_launches(self):
        # After one failure the session runs standalone, and the very next
        # launch has to give RetroArch its decorations back -- otherwise the
        # user is handed a second borderless window (#267).
        game_window_support.mark_embed_unavailable("RetroArch is not an X11 client")
        lines = self._game_window_override_lines(True)
        self.assertIn('video_window_show_decorations = "true"', lines)
        self.assertIn('pause_nonactive = "true"', lines)
        self.assertNotIn('input_toggle_fullscreen = "nul"', lines)

    def test_override_gives_the_window_its_decorations_when_the_setting_is_off(self):
        # Stated, not merely omitted: earlier versions leaked the embed
        # overrides into the user's own retroarch.cfg, so a game launched
        # without a wrapper still came up borderless and never paused. The
        # defaults are written back so a polluted config heals itself.
        lines = self._game_window_override_lines(False)
        self.assertNotIn('video_window_show_decorations = "false"', lines)
        self.assertNotIn('input_toggle_fullscreen = "nul"', lines)
        self.assertIn('video_window_show_decorations = "true"', lines)
        self.assertIn('pause_nonactive = "true"', lines)

    def test_override_leaves_the_window_alone_when_the_session_cannot_embed(self):
        # The setting says yes but nothing can host the embed: writing these
        # anyway would leave RetroArch borderless with no wrapper around it.
        lines = self._game_window_override_lines(True, embeddable=False)
        self.assertNotIn('video_window_show_decorations = "false"', lines)
        self.assertNotIn('input_toggle_fullscreen = "nul"', lines)
        self.assertIn('video_window_show_decorations = "true"', lines)

    def test_override_seeds_the_state_slot_when_asked(self):
        with TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            cfg = _DummyConfig(base, base / "retroarch", base / f"mgba_libretro{CORE_SUFFIX}")
            launcher = RetroArchLauncher(base, cfg)
            path = launcher._write_runtime_override("GBA", state_slot=3)
            lines = Path(path).read_text(encoding="utf-8").splitlines()
        self.assertIn('state_slot = "3"', lines)

    def test_override_emits_turbo_timing_and_the_bound_modifier(self):
        # Issue #72: timing knobs always ride along (defaults are RetroArch's
        # own), and a bound turbo modifier lands as the port's turbo button.
        profile = {
            "active_device": "gamepad_p1",
            "turbo": {"period": 10, "duty_cycle": 5, "mode": 1},
            "devices": {
                "gamepad_p1": {"type": "gamepad", "bindings": {"a": "0", "turbo": "9"}},
            },
        }
        lines = self._override_lines(profile)
        self.assertIn('input_turbo_period = "10"', lines)
        self.assertIn('input_turbo_duty_cycle = "5"', lines)
        self.assertIn('input_turbo_mode = "1"', lines)
        self.assertIn('input_player1_turbo_btn = "9"', lines)

    def test_override_has_no_turbo_binding_when_none_is_bound(self):
        lines = self._override_lines(None)
        self.assertFalse(any("input_player1_turbo" in line for line in lines))
        # ...but the timing keys still restate the defaults.
        self.assertIn('input_turbo_period = "6"', lines)

    def test_override_enables_the_command_channel_and_seeds_the_volume(self):
        # Issue #69: every launch opens the loopback UDP channel and starts
        # the game at the persisted master volume, so live stepping has a
        # known starting point.
        lines = self._override_lines(None)
        self.assertIn('network_cmd_enable = "true"', lines)
        self.assertIn('network_cmd_port = "55355"', lines)
        self.assertIn('audio_volume = "-6.0"', lines)

    def test_the_launch_decides_the_command_port(self):
        # The port is picked per launch (issue #227) and RetroArch has to be
        # told the same number the client will send to.
        with TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            cfg = _DummyConfig(base, base / "retroarch", base / f"mgba_libretro{CORE_SUFFIX}")
            launcher = RetroArchLauncher(base, cfg)
            override = launcher._write_runtime_override("GBA", network_cmd_port=54321)
            lines = Path(override).read_text(encoding="utf-8").splitlines()
        self.assertIn('network_cmd_port = "54321"', lines)

    def test_override_never_lets_itself_be_saved_into_the_users_config(self):
        # RetroArch saves its configuration on exit, and by then the
        # --appendconfig values are part of it: without this every launch
        # wrote OpenEmux's launch-scoped settings into the user's
        # retroarch.cfg for good -- borderless windows, an unbound fullscreen
        # hotkey and OpenEmux's save-state directory, all outliving the game.
        lines = self._override_lines(None)
        self.assertIn('config_save_on_exit = "false"', lines)

    def test_override_makes_a_single_quit_command_quit(self):
        # RetroArch's own default (quit_press_twice) answers the first quit
        # with "press again to exit", and the network QUIT goes through that
        # very same path -- so the command the game window sends on close did
        # nothing and the game played on behind a closed window.
        lines = self._override_lines(None)
        self.assertIn('quit_press_twice = "false"', lines)

    def _override_lines_with_audio_driver(self, setting):
        with TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            cfg = _DummyConfig(base, base / "retroarch", base / f"mgba_libretro{CORE_SUFFIX}")
            cfg.audio_driver = setting
            launcher = RetroArchLauncher(base, cfg)
            path = launcher._write_runtime_override("GBA")
            return Path(path).read_text(encoding="utf-8").splitlines()

    def test_override_pins_the_audio_driver(self):
        # Issue #176: the global retroarch.cfg may name a driver the RetroArch
        # we launch was not built with ("pipewire" against the vendored
        # build). RetroArch then falls back to alsa, audio never starts, and
        # the emulation -- paced off the audio clock -- runs at the display's
        # refresh rate instead of the core's.
        lines = self._override_lines_with_audio_driver("jack")
        self.assertIn('audio_driver = "jack"', lines)

    def test_override_leaves_the_audio_driver_alone_when_inheriting(self):
        lines = self._override_lines_with_audio_driver("inherit")
        self.assertEqual([l for l in lines if l.startswith("audio_driver")], [])

    def test_override_pins_the_joypad_driver_on_windows(self):
        # Issue #118: a binding token is an index into whatever the joypad
        # driver counts. OpenEmux reads the pad through SDL2 on Windows, and
        # RetroArch's default there is xinput, whose button order is its own --
        # so a button remapped in OpenEmux would bind a different one in the
        # game. Naming the driver is what makes the two ends agree.
        with patch("openemux.core.retroarch_launcher.IS_WINDOWS", True):
            lines = self._override_lines(None)
        self.assertIn('input_joypad_driver = "sdl2"', lines)

    def test_override_leaves_the_joypad_driver_alone_on_linux(self):
        # On Linux both ends already agree: OpenEmux reads evdev with udev's
        # numbering and RetroArch defaults to its udev joypad driver. Naming a
        # driver here would be imposing a choice the user did not make.
        with patch("openemux.core.retroarch_launcher.IS_WINDOWS", False):
            lines = self._override_lines(None)
        self.assertEqual([l for l in lines if l.startswith("input_joypad_driver")], [])

    def test_override_is_unchanged_when_no_extra_port_is_enabled(self):
        legacy_only = {
            "active_device": "keyboard",
            "devices": {"keyboard": {"type": "keyboard", "bindings": {"a": "z", "b": "x"}}},
        }
        with_disabled_ports = {
            "active_device": "keyboard",
            "devices": {
                "keyboard": {"type": "keyboard", "bindings": {"a": "z", "b": "x"}},
                "gamepad_p2": {"type": "gamepad", "bindings": {"a": "0"}, "enabled": False},
                "gamepad_p3": {"type": "gamepad", "bindings": {"a": "0"}, "enabled": False},
                "gamepad_p4": {"type": "gamepad", "bindings": {"a": "0"}, "enabled": False},
            },
        }
        def _stable(lines):
            # savestate_directory embeds each run's temp dir; not what this
            # test compares.
            return [l for l in lines if not l.startswith("savestate_directory")]

        self.assertEqual(
            _stable(self._override_lines(legacy_only)),
            _stable(self._override_lines(with_disabled_ports)),
        )
        self.assertIn('input_player1_a = "z"', self._override_lines(legacy_only))

    def test_enabled_extra_ports_emit_their_own_player_keys(self):
        profile = {
            "active_device": "gamepad_p1",
            "devices": {
                "gamepad_p1": {"type": "gamepad", "bindings": {"a": "0"}},
                "gamepad_p2": {"type": "gamepad", "bindings": {"a": "1"}, "enabled": True},
                "gamepad_p3": {"type": "gamepad", "bindings": {"a": "2"}, "enabled": False},
                "gamepad_p4": {"type": "gamepad", "bindings": {"a": "3"}, "enabled": True},
            },
        }
        lines = self._override_lines(profile)
        self.assertIn('input_player1_a_btn = "0"', lines)
        self.assertIn('input_player2_a_btn = "1"', lines)
        self.assertIn('input_player4_a_btn = "3"', lines)
        # Port 3 stayed off.
        self.assertFalse([line for line in lines if line.startswith("input_player3_")])
        # Hotkeys are global: exactly one set, written by port 1.
        self.assertEqual(len([l for l in lines if l.startswith("input_enable_hotkey")]), 1)
        self.assertFalse([l for l in lines if "player2_enable_hotkey" in l])


class LaunchFailuresAreVisibleTests(unittest.TestCase):
    """Every launch failure has to come back as a message (issue #226)."""

    def _launcher(self, base):
        binary = base / "retroarch"
        core = base / "mgba_libretro.so"
        binary.write_text("", encoding="utf-8")
        core.write_text("", encoding="utf-8")
        return RetroArchLauncher(base, _DummyConfig(base, binary, core))

    def test_an_io_error_before_the_launch_becomes_an_error_message(self):
        # _write_runtime_override creates directories and writes a file, all
        # of it outside the old try: a read-only home raised straight into the
        # GTK click handler, which prints the traceback and swallows it.
        with TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            launcher = self._launcher(base)
            with patch.object(
                RetroArchLauncher,
                "_write_runtime_override",
                side_effect=OSError("Read-only file system"),
            ):
                proc, error = launcher.launch_process("/tmp/game.gba", "GBA")

        self.assertIsNone(proc)
        self.assertIn("Read-only file system", error)

    def test_a_failed_popen_closes_the_log_it_opened(self):
        with TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            launcher = self._launcher(base)
            opened = []
            real_open = open

            def _tracking_open(*args, **kwargs):
                handle = real_open(*args, **kwargs)
                opened.append(handle)
                return handle

            with patch("openemux.core.retroarch_launcher.open", _tracking_open, create=True):
                with patch(
                    "openemux.core.retroarch_launcher.subprocess.Popen",
                    side_effect=OSError("Exec format error"),
                ):
                    proc, error = launcher.launch_process("/tmp/game.gba", "GBA")

        self.assertIsNone(proc)
        self.assertIn("Exec format error", error)
        self.assertTrue(opened, "the launcher never opened its log")
        self.assertTrue(
            all(handle.closed for handle in opened),
            "a failed launch leaked its log file descriptor",
        )


class AppImageFuseFallbackTests(unittest.TestCase):
    """An AppImage on a host with no libfuse2 (issue #226)."""

    def test_a_host_without_libfuse2_runs_the_appimage_extracted(self):
        self.assertEqual(
            appimage_flags("/opt/RetroArch-Linux-x86_64.AppImage", libfuse_available=False),
            [APPIMAGE_EXTRACT_AND_RUN],
        )

    def test_a_host_with_libfuse2_mounts_it_as_usual(self):
        # Extract-and-run unpacks the whole image on every launch; only worth
        # paying for when mounting genuinely cannot work.
        self.assertEqual(
            appimage_flags("/opt/RetroArch-Linux-x86_64.AppImage", libfuse_available=True),
            [],
        )

    def test_a_plain_binary_is_never_given_appimage_flags(self):
        self.assertEqual(appimage_flags("/usr/bin/retroarch", libfuse_available=False), [])

    def test_the_extension_check_is_case_insensitive(self):
        self.assertEqual(
            appimage_flags("/opt/RetroArch.APPIMAGE", libfuse_available=False),
            [APPIMAGE_EXTRACT_AND_RUN],
        )

    def test_libfuse3_does_not_count_as_libfuse2(self):
        # The AppImage runtime dlopens "libfuse.so.2" by that exact name, so
        # that is what gets asked for. A host with only FUSE 3 must still get
        # the fallback.
        def _loader(name):
            if name == "libfuse.so.2":
                raise OSError("cannot open shared object file")
            return object()

        self.assertFalse(RetroArchLauncher.libfuse2_available(loader=_loader))

    def test_a_loadable_libfuse2_is_reported_as_present(self):
        self.assertTrue(RetroArchLauncher.libfuse2_available(loader=lambda name: object()))

    def test_the_flag_goes_in_front_of_the_core_argument(self):
        # It is the AppImage runtime's own switch, so it has to sit right
        # after the binary -- RetroArch never sees it.
        with TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            binary = base / "RetroArch.AppImage"
            core = base / "mgba_libretro.so"
            binary.write_text("", encoding="utf-8")
            core.write_text("", encoding="utf-8")
            launcher = RetroArchLauncher(base, _DummyConfig(base, binary, core))
            with patch.object(RetroArchLauncher, "libfuse2_available", staticmethod(lambda: False)):
                prefix, error = launcher._launch_prefix()

        self.assertIsNone(error)
        self.assertEqual(prefix, [str(binary), APPIMAGE_EXTRACT_AND_RUN])


class LaunchEnvironmentTests(unittest.TestCase):
    """What RetroArch's environment says when we run from an AppImage (#249).

    The vendored RetroArch lives inside our AppDir, and appimage-builder's
    AppRun hooks hand anything under ``$APPDIR`` this bundle's loader path,
    ``LD_PRELOAD`` and toolkit caches. The launcher is the only place that can
    hand it the session's environment instead.
    """

    def _launch_env(self, environ):
        with TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            binary = base / "RetroArch.AppImage"
            core = base / f"mgba_libretro{CORE_SUFFIX}"
            binary.write_text("", encoding="utf-8")
            core.write_text("", encoding="utf-8")
            launcher = RetroArchLauncher(base, _DummyConfig(base, binary, core))
            with patch.dict(
                "openemux.core.retroarch_launcher.os.environ", environ, clear=True
            ):
                with patch(
                    "openemux.core.retroarch_launcher.subprocess.Popen"
                ) as popen_mock:
                    popen_mock.return_value = Mock()
                    proc, error = launcher.launch_process("/tmp/game.gba", "GBA")
                    _close_log(proc)
            self.assertIsNone(error)
            return popen_mock.call_args.kwargs["env"]

    def test_the_bundles_loader_never_reaches_retroarch(self):
        env = self._launch_env(
            {
                "HOME": "/home/u",
                "APPDIR": "/tmp/.mount_OpenEmXYZ",
                "LD_LIBRARY_PATH": "/tmp/.mount_OpenEmXYZ/usr/lib",
                "LD_PRELOAD": "libapprun_hooks.so",
                "PYTHONHOME": "/tmp/.mount_OpenEmXYZ/usr",
                "GI_TYPELIB_PATH": "/tmp/.mount_OpenEmXYZ/usr/lib/girepository-1.0",
                "PATH": "/tmp/.mount_OpenEmXYZ/usr/bin:/usr/bin",
                "APPRUN_ORIGINAL_PATH": "/home/u/bin:/usr/bin",
            }
        )
        self.assertNotIn("APPDIR", env)
        self.assertNotIn("LD_LIBRARY_PATH", env)
        self.assertNotIn("LD_PRELOAD", env)
        self.assertNotIn("PYTHONHOME", env)
        self.assertNotIn("GI_TYPELIB_PATH", env)
        self.assertEqual(env["PATH"], "/home/u/bin:/usr/bin")
        self.assertEqual(env["HOME"], "/home/u")

    def test_a_native_run_hands_the_session_through_untouched(self):
        env = self._launch_env(
            {"HOME": "/home/u", "PATH": "/usr/bin", "LD_PRELOAD": "/usr/lib/mangohud.so"}
        )
        self.assertEqual(env["LD_PRELOAD"], "/usr/lib/mangohud.so")
        self.assertEqual(env["PATH"], "/usr/bin")


class ForcedExtractRetryTests(unittest.TestCase):
    """The second attempt after an AppImage failed to mount itself (#248).

    The ``libfuse.so.2`` probe answers "can this library be loaded", which is
    not "can this host mount a FUSE filesystem". A machine with the library
    but no ``/dev/fuse``, or a ``fusermount`` that is not setuid, passes the
    probe and still dies at the mount -- only visible afterwards, in the log.
    """

    def test_forcing_overrides_a_libfuse2_that_loads_fine(self):
        self.assertEqual(
            appimage_flags(
                "/opt/RetroArch-Linux-x86_64.AppImage",
                libfuse_available=True,
                force=True,
            ),
            [APPIMAGE_EXTRACT_AND_RUN],
        )

    def test_forcing_never_invents_a_flag_for_a_plain_binary(self):
        self.assertEqual(appimage_flags("/usr/bin/retroarch", force=True), [])

    def test_the_forced_flag_reaches_the_launch_prefix(self):
        with TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            binary = base / "RetroArch.AppImage"
            core = base / "mgba_libretro.so"
            binary.write_text("", encoding="utf-8")
            core.write_text("", encoding="utf-8")
            launcher = RetroArchLauncher(base, _DummyConfig(base, binary, core))
            with patch.object(RetroArchLauncher, "libfuse2_available", staticmethod(lambda: True)):
                mounted, _ = launcher._launch_prefix()
                unpacked, _ = launcher._launch_prefix(force_extract=True)

        self.assertEqual(mounted, [str(binary)])
        self.assertEqual(unpacked, [str(binary), APPIMAGE_EXTRACT_AND_RUN])

    def test_an_appimage_retroarch_is_recognized_as_retryable(self):
        with TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            binary = base / "RetroArch.AppImage"
            core = base / "mgba_libretro.so"
            binary.write_text("", encoding="utf-8")
            core.write_text("", encoding="utf-8")
            launcher = RetroArchLauncher(base, _DummyConfig(base, binary, core))
            self.assertTrue(launcher.launches_an_appimage())

    def test_a_native_retroarch_has_nothing_to_unpack(self):
        # Nothing to retry: a wrapper script that merely echoes a FUSE line
        # must not buy a second launch.
        with TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            binary = base / "retroarch"
            core = base / "mgba_libretro.so"
            binary.write_text("", encoding="utf-8")
            core.write_text("", encoding="utf-8")
            launcher = RetroArchLauncher(base, _DummyConfig(base, binary, core))
            self.assertFalse(launcher.launches_an_appimage())


class X11OnlyEnvTests(unittest.TestCase):
    """What RetroArch's environment must not say while the wrapper embeds."""

    def test_the_wayland_socket_pointer_always_goes(self):
        # Its mere presence is what makes RetroArch's wayland context
        # succeed, and a wayland window can never be reparented into ours.
        cleaned = x11_only_env({"DISPLAY": ":0", "WAYLAND_DISPLAY": "wayland-0"})
        self.assertNotIn("WAYLAND_DISPLAY", cleaned)
        self.assertEqual(cleaned["DISPLAY"], ":0")

    def test_an_sdl_driver_pinned_to_wayland_goes(self):
        cleaned = x11_only_env({"DISPLAY": ":0", "SDL_VIDEODRIVER": "wayland"})
        self.assertNotIn("SDL_VIDEODRIVER", cleaned)

    def test_an_sdl_driver_already_on_x11_is_left_alone(self):
        # The user already agrees with us; unsetting it would only make SDL
        # guess again.
        cleaned = x11_only_env({"DISPLAY": ":0", "SDL_VIDEODRIVER": "x11"})
        self.assertEqual(cleaned["SDL_VIDEODRIVER"], "x11")

    def test_the_callers_environment_is_not_mutated(self):
        original = {"DISPLAY": ":0", "WAYLAND_DISPLAY": "wayland-0"}
        x11_only_env(original)
        self.assertIn("WAYLAND_DISPLAY", original)


class StoppingAGameTests(unittest.TestCase):
    """What a stop signal actually reaches, per launch shape."""

    def _launcher(self, tmp_dir):
        base = Path(tmp_dir)
        return RetroArchLauncher(
            base, _DummyConfig(base, base / "retroarch", base / f"mgba_libretro{CORE_SUFFIX}")
        )

    def test_the_flatpak_prefix_ties_the_sandbox_to_the_process_we_hold(self):
        # Without --die-with-parent our SIGTERM stops at the host's
        # `flatpak run`: bwrap lives on in its own systemd scope and the game
        # keeps playing inside a sandbox nothing can signal.
        with TemporaryDirectory() as tmp_dir:
            launcher = self._launcher(tmp_dir)
            with patch(
                "openemux.core.retroarch_launcher.is_running_in_flatpak",
                return_value=True,
            ), patch(
                "openemux.core.retroarch_launcher.shutil.which",
                return_value="/usr/bin/flatpak-spawn",
            ):
                prefix, error = launcher._launch_prefix()
        self.assertIsNone(error)
        self.assertEqual(
            prefix,
            [
                "flatpak-spawn",
                "--host",
                "flatpak",
                "run",
                "--die-with-parent",
                "org.libretro.RetroArch",
            ],
        )

    def test_the_flatpak_prefix_denies_the_wayland_socket_while_embedding(self):
        # Popping WAYLAND_DISPLAY from *our* environment never reaches the
        # sandbox -- `flatpak run` builds its own. Denying the socket does,
        # and it is what makes --socket=fallback-x11 hand out X11, so the
        # window the wrapper is about to adopt is an X window (issue #267).
        with TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            cfg = _DummyConfig(base, base / "retroarch", base / f"mgba_libretro{CORE_SUFFIX}")
            cfg.game_window = True
            launcher = RetroArchLauncher(base, cfg)
            with patch(
                "openemux.core.retroarch_launcher.is_running_in_flatpak",
                return_value=True,
            ), patch(
                "openemux.core.retroarch_launcher.shutil.which",
                return_value="/usr/bin/flatpak-spawn",
            ), patch(
                "openemux.core.game_window_support.embedding_possible",
                return_value=True,
            ):
                prefix, error = launcher._launch_prefix()
        self.assertIsNone(error)
        self.assertIn("--nosocket=wayland", prefix)
        # Never after the app id, or flatpak hands it to RetroArch as an
        # argument instead of reading it as a sandbox option.
        self.assertLess(
            prefix.index("--nosocket=wayland"), prefix.index("org.libretro.RetroArch")
        )

    def test_terminate_signals_the_process(self):
        with TemporaryDirectory() as tmp_dir:
            launcher = self._launcher(tmp_dir)
            proc = Mock()
            self.assertTrue(launcher.terminate_process(proc))
            proc.terminate.assert_called_once_with()

    def test_terminate_survives_a_process_that_is_already_gone(self):
        with TemporaryDirectory() as tmp_dir:
            launcher = self._launcher(tmp_dir)
            proc = Mock()
            proc.terminate.side_effect = OSError("no such process")
            self.assertFalse(launcher.terminate_process(proc))

    def test_kill_outside_a_flatpak_is_just_the_signal(self):
        with TemporaryDirectory() as tmp_dir:
            launcher = self._launcher(tmp_dir)
            proc = Mock()
            with patch(
                "openemux.core.retroarch_launcher.is_running_in_flatpak",
                return_value=False,
            ), patch("openemux.core.retroarch_launcher.subprocess.run") as run_mock:
                self.assertTrue(launcher.kill_process(proc))
            proc.kill.assert_called_once_with()
            run_mock.assert_not_called()

    def test_kill_inside_a_flatpak_stops_the_instance_on_the_host(self):
        # SIGKILL is the one signal flatpak-spawn cannot forward, so killing
        # the relay alone would orphan RetroArch for good.
        with TemporaryDirectory() as tmp_dir:
            launcher = self._launcher(tmp_dir)
            proc = Mock()
            with patch(
                "openemux.core.retroarch_launcher.is_running_in_flatpak",
                return_value=True,
            ), patch(
                "openemux.core.retroarch_launcher.shutil.which",
                return_value="/usr/bin/flatpak-spawn",
            ), patch(
                "openemux.core.retroarch_launcher.subprocess.run"
            ) as run_mock:
                self.assertTrue(launcher.kill_process(proc))
            self.assertEqual(
                run_mock.call_args[0][0],
                [
                    "flatpak-spawn",
                    "--host",
                    "flatpak",
                    "kill",
                    "org.libretro.RetroArch",
                ],
            )
            proc.kill.assert_called_once_with()


class CoreOptionsOverrideTests(unittest.TestCase):
    """Core options travel in their own file, named by the override (#296)."""

    def _launcher(self, base, chosen=None):
        cfg = _DummyConfig(base, base / "retroarch", base / f"mednafen_psx_hw_libretro{CORE_SUFFIX}")
        if chosen is not None:
            cfg.core_options = CoreOptionsStore(base / "core_options.config")
            for key, value in chosen.items():
                cfg.core_options.set_for_console("PS", f"mednafen_psx_hw_libretro{CORE_SUFFIX}", key, value)
        return RetroArchLauncher(base, cfg)

    def test_nothing_chosen_writes_no_options_path(self):
        # Naming our file replaces the one RetroArch would have read, so a
        # console nobody configured must not get one.
        with TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            launcher = self._launcher(base)
            override = launcher._write_runtime_override(
                "PS", core_filename=f"mednafen_psx_hw_libretro{CORE_SUFFIX}"
            )
            lines = Path(override).read_text(encoding="utf-8").splitlines()
        self.assertFalse(any(line.startswith("core_options_path") for line in lines))

    def test_a_choice_is_written_to_a_file_the_override_names(self):
        with TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            launcher = self._launcher(base, {"beetle_psx_hw_internal_resolution": "4x"})
            override = launcher._write_runtime_override(
                "PS", core_filename=f"mednafen_psx_hw_libretro{CORE_SUFFIX}"
            )
            lines = Path(override).read_text(encoding="utf-8").splitlines()
            named = [l for l in lines if l.startswith("core_options_path")]
            self.assertEqual(len(named), 1, lines)
            options_path = named[0].split("=", 1)[1].strip().strip('"')
            written = Path(options_path).read_text(encoding="utf-8")
        self.assertIn('beetle_psx_hw_internal_resolution = "4x"', written)

    def test_a_console_with_a_different_core_gets_nothing(self):
        with TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            launcher = self._launcher(base, {"beetle_psx_hw_filter": "xBR"})
            override = launcher._write_runtime_override(
                "SFC", core_filename=f"snes9x_libretro{CORE_SUFFIX}"
            )
            lines = Path(override).read_text(encoding="utf-8").splitlines()
        self.assertFalse(any(line.startswith("core_options_path") for line in lines))


if __name__ == "__main__":
    unittest.main()
