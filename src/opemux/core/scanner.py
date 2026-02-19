from pathlib import Path
import logging
from opemux.core.hasher import compute_rom_id

logger = logging.getLogger(__name__)

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
        logger.info("scan_roms started: console=%s path=%s", console, console_path)
        if not console_path.exists():
            logger.info("scan_roms skipped: console path does not exist console=%s path=%s", console, console_path)
            return []

        roms = []
        extensions = SUPPORTED_EXTENSIONS.get(console, [])

        for file in console_path.rglob("*"):
            if file.is_file() and file.suffix.lower() in extensions:
                rom_id = None
                try:
                    rom_id = compute_rom_id(str(file))
                except Exception:
                    # Keep scanning even if hashing fails for one file.
                    rom_id = None
                logger.info("scan_roms found rom: console=%s rom=%s path=%s", console, file.stem, file)
                roms.append({
                    "name": file.stem,
                    "path": str(file),
                    "console": console,
                    "rom_id": rom_id,
                })

        sorted_roms = sorted(roms, key=lambda x: x["name"])
        logger.info("scan_roms finished: console=%s total=%d", console, len(sorted_roms))
        return sorted_roms
