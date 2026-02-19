from pathlib import Path
import logging
from opemux.core.hasher import compute_rom_id
from opemux.core.systems import SYSTEM_IDS, get_supported_extensions, resolve_system_id

logger = logging.getLogger(__name__)

class RomScanner:
    def __init__(self, base_path):
        self.base_path = Path(base_path)

    def scan_all(self):
        library = {}
        for console in SYSTEM_IDS:
            library[console] = self.scan_console(console)
        return library

    def scan_console(self, console):
        system_id = resolve_system_id(console)
        console_path = self.base_path / system_id
        logger.info("scan_roms started: console=%s path=%s", system_id, console_path)
        if not console_path.exists():
            logger.info("scan_roms skipped: console path does not exist console=%s path=%s", system_id, console_path)
            return []

        roms = []
        extensions = get_supported_extensions(system_id)

        for file in console_path.rglob("*"):
            if not file.is_file():
                continue
            if any(part.lower() in ("covers", "bios") for part in file.parts):
                continue
            if file.suffix.lower() in extensions:
                rom_id = None
                try:
                    rom_id = compute_rom_id(str(file))
                except Exception:
                    # Keep scanning even if hashing fails for one file.
                    rom_id = None
                logger.info("scan_roms found rom: console=%s rom=%s path=%s", system_id, file.stem, file)
                roms.append({
                    "name": file.stem,
                    "path": str(file),
                    "console": system_id,
                    "rom_id": rom_id,
                })

        sorted_roms = sorted(roms, key=lambda x: x["name"])
        logger.info("scan_roms finished: console=%s total=%d", system_id, len(sorted_roms))
        return sorted_roms
