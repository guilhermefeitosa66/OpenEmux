import subprocess
import os
from pathlib import Path

class Launcher:
    def __init__(self, project_root):
        self.project_root = Path(project_root)
        self.vendors_path = self.project_root / "vendors"

    def get_emulator_path(self, console):
        if console == "nes":
            # Check for vendorized nestopia binary
            paths = [
                self.vendors_path / "nestopia" / "nestopia",
                self.vendors_path / "nestopia" / "build" / "nestopia"
            ]
            for path in paths:
                if path.exists():
                    return str(path)
            return "nestopia" # Fallback to system path

        if console == "snes":
            # Check for vendorized snes9x binary
            paths = [
                self.vendors_path / "snes9x" / "gtk" / "build" / "snes9x-gtk",
            ]
            for path in paths:
                if path.exists():
                    return str(path)
            return "snes9x-gtk" # Fallback to system path

        if console == "gba":
            # Check for vendorized mgba binary
            paths = [
                self.vendors_path / "mgba" / "build" / "sdl" / "mgba-sdl",
            ]
            for path in paths:
                if path.exists():
                    return str(path)
            return "mgba-sdl" # Fallback to system path

        return None


    def launch(self, rom_path, console):
        emu_binary = self.get_emulator_path(console)
        if not emu_binary:
            print(f"No emulator found for {console}")
            return

        cmd = [emu_binary, rom_path]
        
        try:
            print(f"Launching: {' '.join(cmd)}")
            # Set working directory to the emulator's folder so it finds its database
            emu_dir = os.path.dirname(emu_binary)
            subprocess.Popen(cmd, cwd=emu_dir)
        except Exception as e:
            print(f"Error launching emulator: {e}")

