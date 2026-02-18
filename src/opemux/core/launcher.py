import subprocess
import shutil
import os
import os.path
from pathlib import Path

class Launcher:
    def __init__(self, project_root):
        self.project_root = Path(project_root)
        self.vendors_path = self.project_root / "vendors"

    def get_emulator_path(self, console):
        """Returns (binary_path, is_vendored) tuple."""
        if console == "nes":
            paths = [
                self.vendors_path / "nestopia" / "nestopia",
                self.vendors_path / "nestopia" / "build" / "nestopia",
            ]
            for path in paths:
                if path.exists():
                    return str(path), True
            # Fallback to system binary
            system_bin = shutil.which("nestopia")
            if system_bin:
                return system_bin, False
            return None, False

        if console == "snes":
            paths = [
                self.vendors_path / "snes9x" / "gtk" / "build" / "snes9x-gtk",
            ]
            for path in paths:
                if path.exists():
                    return str(path), True
            system_bin = shutil.which("snes9x-gtk")
            if system_bin:
                return system_bin, False
            return None, False

        if console == "gba":
            paths = [
                self.vendors_path / "mgba" / "build" / "sdl" / "mgba",
                self.vendors_path / "mgba" / "build" / "sdl" / "mgba-sdl",
            ]
            for path in paths:
                if path.exists():
                    return str(path), True
            system_bin = shutil.which("mgba-sdl") or shutil.which("mgba")
            if system_bin:
                return system_bin, False
            return None, False

        return None, False

    def _build_command(self, emu_binary, rom_path, console):
        """Build the command list with any emulator-specific flags."""
        return [emu_binary, rom_path]

    def launch(self, rom_path, console):
        emu_binary, is_vendored = self.get_emulator_path(console)

        if not emu_binary:
            error_msg = (
                f"No emulator found for {console.upper()}. "
                f"Either build the vendored emulator with 'make build-emulators' "
                f"or install the system package."
            )
            print(f"Error: {error_msg}")
            return False, error_msg

        cmd = self._build_command(emu_binary, rom_path, console)

        try:
            print(f"Launching: {' '.join(cmd)}")
            # Only set cwd for vendored binaries so they can find their data files.
            # We also explicitly set PWD in the environment — some emulators (e.g. Nestopia)
            # read std::getenv("PWD") instead of getcwd(), so cwd= alone is not enough.
            emu_dir = os.path.dirname(emu_binary) if is_vendored else None
            env = None
            if emu_dir:
                env = os.environ.copy()
                env["PWD"] = emu_dir
            subprocess.Popen(cmd, cwd=emu_dir or None, env=env)
            return True, None
        except FileNotFoundError:
            error_msg = f"Emulator binary not found: {emu_binary}"
            print(f"Error: {error_msg}")
            return False, error_msg
        except Exception as e:
            error_msg = f"Error launching emulator: {e}"
            print(error_msg)
            return False, error_msg
