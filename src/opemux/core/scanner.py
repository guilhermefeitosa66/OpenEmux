from pathlib import Path

SUPPORTED_EXTENSIONS = {
    "nes": [".nes"],
    "snes": [".sfc", ".smc"],
    "gba": [".gba"]
}

class RomScanner:
    def __init__(self, base_path):
        self.base_path = Path(base_path)

    def scan_all(self):
        library = {}
        for console, extensions in SUPPORTED_EXTENSIONS.items():
            library[console] = self.scan_console(console)
        return library

    def scan_console(self, console):
        console_path = self.base_path / console
        if not console_path.exists():
            return []

        roms = []
        extensions = SUPPORTED_EXTENSIONS.get(console, [])
        
        for file in console_path.iterdir():
            if file.suffix.lower() in extensions:
                roms.append({
                    "name": file.stem,
                    "path": str(file),
                    "console": console
                })
        
        return sorted(roms, key=lambda x: x["name"])
