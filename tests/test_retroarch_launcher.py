import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from openemux.core.retroarch_launcher import RetroArchLauncher


class _DummyConfig:
    def __init__(self, base_dir, binary_path, core_path, shader_by_console=None):
        self.base_dir = Path(base_dir)
        self.binary_path = str(binary_path)
        self.core_path = str(core_path)
        self.input_dir = self.base_dir / "input"
        self.runtime_dir = self.base_dir / "runtime"
        self.shader_by_console = shader_by_console or {}
        self.input_profile = None

    def get_retroarch_binary(self):
        return self.binary_path

    def get_retroarch_core_hints(self, _console):
        return [self.core_path]

    def get_retroarch_extra_flags(self):
        return []

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
        self.assertEqual(
            self._override_lines(legacy_only), self._override_lines(with_disabled_ports)
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
