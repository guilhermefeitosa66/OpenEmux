import logging
import os
import re
from pathlib import Path

from openemux.core.dir_walk import directory_stamps, walk_entries
from openemux.core.archives import (
    ARCHIVE_EXTENSIONS,
    archive_rom_name,
    loads_archives_natively,
)
from openemux.core.systems import get_supported_extensions, resolve_system_id

logger = logging.getLogger(__name__)


_CUE_FILE_RE = re.compile(r'^\s*FILE\s+(?:"([^"]+)"|([^\s]+))', re.IGNORECASE)

#: Folders under a console that hold the app's own files, never games.
_SKIPPED_FOLDERS = ("covers", "bios")


class RomScanner:
    def __init__(self, base_path):
        self.base_path = Path(base_path)

    def console_path(self, console):
        return self.base_path / resolve_system_id(console)

    def fingerprint(self, console):
        """The console tree's directory mtimes: what a rescan would re-read.

        Compared with the one stored at the last scan to skip consoles whose
        folders have not changed since (issue 901); an empty dict for a
        console folder that does not exist.
        """
        console_path = self.console_path(console)
        if not console_path.is_dir():
            return {}
        return directory_stamps(console_path)

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
        extensions = get_supported_extensions(system_id)
        allow_archives = loads_archives_natively(system_id)

        # One walk, one stat per file (issue 901): the tree used to be walked
        # twice -- once for the cue sheets, once for the ROMs -- with an
        # is_file() per entry on top of what os.walk already knew. The cue
        # sheets are collected on the way and read afterwards, so the .bin
        # tracks they reference can be dropped from what was found.
        found = []
        cue_files = []
        for file, info in walk_entries(console_path):
            if any(part.lower() in _SKIPPED_FOLDERS for part in file.parts):
                continue
            if info is None:
                # A link pointing nowhere, or a file that vanished mid-scan.
                continue
            suffix = file.suffix.lower()
            if suffix == ".cue":
                cue_files.append(file)

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
                found.append(self._rom(rom_name, file, system_id, info))
                continue

            if suffix in extensions:
                logger.debug("scan_roms found rom: console=%s rom=%s path=%s", system_id, file.stem, file)
                found.append(self._rom(file.stem, file, system_id, info))

        referenced = self._cue_referenced_bins(cue_files)
        roms = []
        for rom in found:
            path = Path(rom["path"])
            if path.suffix.lower() == ".bin" and referenced and _same_file_key(path) in referenced:
                logger.debug("scan_roms hidden helper track: console=%s path=%s", system_id, path)
                continue
            roms.append(rom)

        sorted_roms = sorted(roms, key=lambda x: x["name"])
        logger.info("scan_roms finished: console=%s total=%d", system_id, len(sorted_roms))
        return sorted_roms

    @staticmethod
    def _rom(name, path, system_id, info):
        """A playlist entry, with what the index keeps about the file.

        ``added`` is the inode change time, not the modification time:
        copying a ROM in preserves the original file's mtime, and "recently
        added" has to mean when *this* copy appeared.
        """
        return {
            "name": name,
            "path": str(path),
            "console": system_id,
            "size": int(info.st_size),
            "added": float(info.st_ctime),
        }

    @staticmethod
    def _cue_referenced_bins(cue_files):
        referenced = set()
        for cue_file in cue_files:
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
                referenced_file = cue_file.parent / name
                if referenced_file.suffix.lower() == ".bin":
                    # Normalised, not resolved: resolve() stats every segment,
                    # and a cue and its tracks sit in the same folder, reached
                    # by the same walk (issue 901).
                    referenced.add(_same_file_key(referenced_file))
        return referenced


def _same_file_key(path):
    """One spelling for a path, so a cue's ``FILE`` line matches the walked track."""
    return os.path.normcase(os.path.normpath(os.fspath(path)))
