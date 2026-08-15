import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from openemux.core.input_actions import ANALOG_STICK_BINDINGS
from openemux.core.retroarch_launcher import RetroArchLauncher


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
    def test_resolve_retroarch_binary_from_project_relative_path(self):
        with TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            binary = base / "vendors" / "RetroArch-Linux-x86_64.AppImage"
            binary.parent.mkdir(parents=True, exist_ok=True)
            binary.write_text("", encoding="utf-8")
            core = base / "mgba_libretro.so"
            core.write_text("", encoding="utf-8")
            cfg = _DummyConfig(base, "vendors/RetroArch-Linux-x86_64.AppImage", core)
            launcher = RetroArchLauncher(base, cfg)

            resolved = launcher._resolve_retroarch_binary()

        self.assertEqual(resolved, str(binary))

    def test_per_rom_core_override_wins_and_stale_falls_back(self):
        with TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            cores_dir = base / "cores"
            cores_dir.mkdir()
            (cores_dir / "snes9x_libretro.so").write_text("", encoding="utf-8")
            (cores_dir / "bsnes_libretro.so").write_text("", encoding="utf-8")

            cfg = _DummyConfig(base, base / "retroarch", base / "unused.so", core_hints=[])
            launcher = RetroArchLauncher(base, cfg)
            # Resolve bare filenames against our temp core dir, not the system.
            launcher._core_search_dirs = lambda: [str(cores_dir)]

            # A per-ROM override wins over the automatic candidate list.
            cfg.rom_core = "bsnes_libretro.so"
            resolved = launcher._find_core_path("SFC", rom_path="/g/x.sfc")
            self.assertTrue(resolved.endswith("bsnes_libretro.so"))

            # A stale override (core uninstalled) falls back to the candidate.
            cfg.rom_core = "does_not_exist_libretro.so"
            resolved = launcher._find_core_path("SFC", rom_path="/g/x.sfc")
            self.assertTrue(resolved.endswith("snes9x_libretro.so"))

    def test_launch_blocks_when_required_bios_missing(self):
        with TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            binary = base / "retroarch"
            core = base / "mednafen_psx_libretro.so"
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
            core = base / "mednafen_psx_libretro.so"
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
            core = base / "mgba_libretro.so"
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
            cfg = _DummyConfig(base, base / "retroarch", base / "mgba_libretro.so")
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
            cfg = _DummyConfig(base, base / "retroarch", base / "mgba_libretro.so")
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

    def test_override_leaves_the_window_alone_when_the_setting_is_off(self):
        lines = self._game_window_override_lines(False)
        self.assertNotIn('video_window_show_decorations = "false"', lines)
        self.assertNotIn('input_toggle_fullscreen = "nul"', lines)

    def test_override_leaves_the_window_alone_when_the_session_cannot_embed(self):
        # The setting says yes but nothing can host the embed: writing these
        # anyway would leave RetroArch borderless with no wrapper around it.
        lines = self._game_window_override_lines(True, embeddable=False)
        self.assertNotIn('video_window_show_decorations = "false"', lines)
        self.assertNotIn('input_toggle_fullscreen = "nul"', lines)

    def test_override_seeds_the_state_slot_when_asked(self):
        with TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            cfg = _DummyConfig(base, base / "retroarch", base / "mgba_libretro.so")
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

    def _override_lines_with_audio_driver(self, setting):
        with TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            cfg = _DummyConfig(base, base / "retroarch", base / "mgba_libretro.so")
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


if __name__ == "__main__":
    unittest.main()
