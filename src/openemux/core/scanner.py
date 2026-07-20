import logging
import re
import zipfile
from pathlib import Path

from openemux.core.hasher import compute_rom_id
from openemux.core.systems import SYSTEM_IDS, get_supported_extensions, resolve_system_id

logger = logging.getLogger(__name__)


_CUE_FILE_RE = re.compile(r'^\s*FILE\s+(?:"([^"]+)"|([^\s]+))', re.IGNORECASE)

# Archive containers we can inspect with the standard library. ".7z" is
# deliberately absent: reading it would require a third-party dependency
# (py7zr), which the project does not vendor.
ARCHIVE_EXTENSIONS = (".zip",)

# Disc-based systems are excluded from archive scanning. A zip holding a
# .cue + .bin set (or a raw .iso/.chd) is not directly loadable by the cores
# we ship for these systems, so surfacing the archive as a ROM would only
# produce launch failures.
ARCHIVE_UNSUPPORTED_SYSTEMS = frozenset({"MCD", "SATURN", "PS", "PSP", "PCECD", "GC"})

# Entries inside an archive that are never the actual ROM.
_ARCHIVE_IGNORED_PREFIXES = ("__MACOSX/", ".")


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
        cue_referenced_bins = self._cue_referenced_bins(console_path)

        allow_archives = system_id not in ARCHIVE_UNSUPPORTED_SYSTEMS

        for file in console_path.rglob("*"):
            if not file.is_file():
                continue
            if any(part.lower() in ("covers", "bios") for part in file.parts):
                continue
            suffix = file.suffix.lower()

            if suffix in ARCHIVE_EXTENSIONS and suffix not in extensions:
                if not allow_archives:
                    logger.info(
                        "scan_roms archive skipped (disc-based system): console=%s path=%s",
                        system_id,
                        file,
                    )
                    continue
                rom_name = self._archive_rom_name(file, extensions)
                if rom_name is None:
                    continue
                rom_id = None
                try:
                    rom_id = compute_rom_id(str(file))
                except Exception:
                    rom_id = None
                logger.info("scan_roms found archived rom: console=%s rom=%s path=%s", system_id, rom_name, file)
                roms.append({
                    "name": rom_name,
                    "path": str(file),
                    "console": system_id,
                    "rom_id": rom_id,
                })
                continue

            if suffix in extensions:
                if file.suffix.lower() == ".bin" and file.resolve() in cue_referenced_bins:
                    logger.info("scan_roms hidden helper track: console=%s path=%s", system_id, file)
                    continue
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

    def _archive_rom_name(self, archive_path, extensions):
        """Return the display name for an archive holding a ROM, or None.

        The archive itself stays the launch target (RetroArch loads zipped
        content natively for most cores). When the archive holds exactly one
        matching entry we use that entry's stem so cover art and playlist
        lookups keep matching the real game title; otherwise we fall back to
        the archive's own stem.
        """
        try:
            with zipfile.ZipFile(archive_path) as archive:
                names = archive.namelist()
        except Exception as exc:
            logger.warning("scan_roms unreadable archive: path=%s error=%s", archive_path, exc)
            return None

        matches = []
        for name in names:
            if name.endswith("/"):
                continue
            entry = Path(name)
            if entry.name.startswith(_ARCHIVE_IGNORED_PREFIXES) or name.startswith(_ARCHIVE_IGNORED_PREFIXES):
                continue
            if entry.suffix.lower() in extensions:
                matches.append(entry)

        if not matches:
            logger.info("scan_roms archive has no matching rom: path=%s", archive_path)
            return None
        if len(matches) == 1:
            return matches[0].stem

        logger.info(
            "scan_roms archive holds %d roms, using archive name: path=%s",
            len(matches),
            archive_path,
        )
        return archive_path.stem

    def _cue_referenced_bins(self, console_path):
        referenced = set()
        for cue_file in console_path.rglob("*.cue"):
            if not cue_file.is_file():
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
