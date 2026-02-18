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
            # Try root folder (Autotools) and build folder (previous attempt/CMake)
            paths = [
                self.vendors_path / "nestopia" / "nestopia",
                self.vendors_path / "nestopia" / "build" / "nestopia"
            ]
            for path in paths:
                if path.exists():
                    return str(path)
            return "nestopia" # Fallback to system path

        return None

    def launch(self, rom_path, console):
        emu_binary = self.get_emulator_path(console)
        if not emu_binary:
            print(f"No emulator found for {console}")
            return

        cmd = [emu_binary, rom_path]
        
        try:
            print(f"Launching: {' '.join(cmd)}")
            # We use Popen so we don't block the UI
            subprocess.Popen(cmd)
        except Exception as e:
            print(f"Error launching emulator: {e}")
