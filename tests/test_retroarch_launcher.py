import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from opemux.core.retroarch_launcher import RetroArchLauncher


class _DummyConfig:
    def __init__(self, base_dir, binary_path, core_path):
        self.base_dir = Path(base_dir)
        self.binary_path = str(binary_path)
        self.core_path = str(core_path)
        self.input_dir = self.base_dir / "input"
        self.runtime_dir = self.base_dir / "runtime"

    def get_retroarch_binary(self):
        return self.binary_path

    def get_retroarch_core_hints(self, _console):
        return [self.core_path]

    def get_retroarch_extra_flags(self):
        return []

    def get_input_profile(self, _console):
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


class RetroArchLauncherTests(unittest.TestCase):
    def test_launch_blocks_when_required_bios_missing(self):
        with TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            binary = base / "retroarch"
            core = base / "mednafen_psx_libretro.so"
            binary.write_text("", encoding="utf-8")
            core.write_text("", encoding="utf-8")
            cfg = _DummyConfig(base, binary, core)
            launcher = RetroArchLauncher(base, cfg)

            with patch("opemux.core.retroarch_launcher.subprocess.Popen") as popen_mock:
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

            with patch("opemux.core.retroarch_launcher.subprocess.Popen") as popen_mock:
                popen_mock.return_value = Mock()
                proc, error = launcher.launch_process("/tmp/game.cue", "PS")

            runtime_cfgs = list((base / "runtime").glob("runtime_ps_*.cfg"))
            self.assertTrue(runtime_cfgs)
            content = runtime_cfgs[0].read_text(encoding="utf-8")

        self.assertIsNotNone(proc)
        self.assertIsNone(error)
        self.assertIn("system_directory", content)


if __name__ == "__main__":
    unittest.main()
