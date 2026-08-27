import logging
import re
from pathlib import Path

from openemux.core.dir_walk import walk_files
from openemux.core.archives import (
    ARCHIVE_EXTENSIONS,
    archive_rom_name,
    loads_archives_natively,
)
from openemux.core.systems import SYSTEM_IDS, get_supported_extensions, resolve_system_id

logger = logging.getLogger(__name__)


_CUE_FILE_RE = re.compile(r'^\s*FILE\s+(?:"([^"]+)"|([^\s]+))', re.IGNORECASE)


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

        # Everything per file below logs at DEBUG. A scan runs for all 31
        # consoles at every launch, so one INFO line per ROM meant the launch
        # log was mostly a list of the library (issue #221); the count is in
        # the "finished" line at the bottom.
        roms = []
        extensions = get_supported_extensions(system_id)
        cue_referenced_bins = self._cue_referenced_bins(console_path)

        allow_archives = loads_archives_natively(system_id)

        # walk_files, not rglob: rglob does not descend into a symlinked
        # directory, so "PS/discs -> /mnt/storage/ps1" scanned as empty with
        # no error and nothing in the log (issue #228).
        for file in walk_files(console_path):
            if not file.is_file():
                continue
            if any(part.lower() in ("covers", "bios") for part in file.parts):
                continue
            suffix = file.suffix.lower()

            if suffix in ARCHIVE_EXTENSIONS and suffix not in extensions:
                if not allow_archives:
                    logger.debug(
                        "scan_roms archive skipped (core needs a real file): console=%s path=%s",
                        system_id,
                        file,
                    )
                    continue
                rom_name = archive_rom_name(file, extensions)
                if rom_name is None:
                    continue
                logger.debug("scan_roms found archived rom: console=%s rom=%s path=%s", system_id, rom_name, file)
                roms.append({
                    "name": rom_name,
                    "path": str(file),
                    "console": system_id,
                })
                continue

            if suffix in extensions:
                if file.suffix.lower() == ".bin" and file.resolve() in cue_referenced_bins:
                    logger.debug("scan_roms hidden helper track: console=%s path=%s", system_id, file)
                    continue
                logger.debug("scan_roms found rom: console=%s rom=%s path=%s", system_id, file.stem, file)
                roms.append({
                    "name": file.stem,
                    "path": str(file),
                    "console": system_id,
                })

        sorted_roms = sorted(roms, key=lambda x: x["name"])
        logger.info("scan_roms finished: console=%s total=%d", system_id, len(sorted_roms))
        return sorted_roms


    def _cue_referenced_bins(self, console_path):
        referenced = set()
        for cue_file in walk_files(console_path):
            if cue_file.suffix.lower() != ".cue" or not cue_file.is_file():
                continue
            if any(part.lower() in ("covers", "bios") for part in cue_file.parts):
                continue

            try:
                lines = cue_file.read_text(encoding="utf-8", errors="ignore").splitlines()
            except Exception:
                continue

            for line in lines:
                match = _CUE_FILE_RE.match(line)
                if not match:
                    continue
                name = (match.group(1) or match.group(2) or "").strip()
                if not name:
                    continue
                referenced_file = (cue_file.parent / name).resolve()
                if referenced_file.suffix.lower() == ".bin":
                    referenced.add(referenced_file)
        return referenced
