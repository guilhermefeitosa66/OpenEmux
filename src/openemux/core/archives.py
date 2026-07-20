"""Shared handling for ROM archives (.zip).

Both the scanner and the playlist loader need to answer the same two questions
about an archive -- "is there a ROM for this console inside?" and "what should
it be called?" -- so the logic lives here rather than in either of them.

Two classes of console matter:

* Cores that load ROM data from memory (snes9x, nestopia, mgba,
  genesis_plus_gx, ...) open a ``.zip`` natively, so the archive itself is the
  launch target and nothing needs unpacking.
* Cores flagged ``needs_fullpath`` -- the disc-based systems -- are handed a
  path and open it themselves, so RetroArch's internal archive support does not
  apply. For those, the importer extracts the archive instead (see
  :func:`extract_archive`).
"""

import logging
import zipfile
from pathlib import Path

logger = logging.getLogger(__name__)

# Archive containers we can inspect with the standard library. ".7z" is
# deliberately absent: reading it would require a third-party dependency
# (py7zr), which the project does not vendor.
ARCHIVE_EXTENSIONS = (".zip",)

# Systems whose cores need a real file on disk (needs_fullpath) and therefore
# cannot load a ROM straight out of an archive. Importing a zip for one of
# these extracts it instead of copying it as-is.
EXTRACT_ON_IMPORT_SYSTEMS = frozenset({"MCD", "SATURN", "PS", "PSP", "PCECD", "GC"})

# Entries inside an archive that are never the actual ROM.
_IGNORED_PREFIXES = ("__MACOSX/", ".")


def is_archive(path):
    return Path(path).suffix.lower() in ARCHIVE_EXTENSIONS


def loads_archives_natively(system_id):
    """True when this system's core can be handed a ``.zip`` directly."""
    return system_id not in EXTRACT_ON_IMPORT_SYSTEMS


def _is_junk(name):
    entry_name = Path(name).name
    return name.startswith(_IGNORED_PREFIXES) or entry_name.startswith(_IGNORED_PREFIXES)


def archive_entries(archive_path, extensions):
    """Return the archive's entries matching ``extensions``, as Paths.

    An unreadable or corrupt archive yields an empty list; scanning must never
    fail because of one bad file.
    """
    try:
        with zipfile.ZipFile(archive_path) as archive:
            names = [info.filename for info in archive.infolist() if not info.is_dir()]
    except Exception as exc:
        logger.warning("archives unreadable: path=%s error=%s", archive_path, exc)
        return []

    matches = []
    for name in names:
        if _is_junk(name):
            continue
        entry = Path(name)
        if entry.suffix.lower() in extensions:
            matches.append(entry)
    return matches


def archive_rom_name(archive_path, extensions):
    """Display name for an archive holding a ROM, or None when it holds none.

    With exactly one matching entry we use that entry's stem, so cover art and
    playlist lookups keep matching the real game title instead of whatever the
    archive happens to be called. Multi-ROM archives fall back to the archive's
    own stem.
    """
    matches = archive_entries(archive_path, extensions)
    if not matches:
        return None
    if len(matches) == 1:
        return matches[0].stem
    return Path(archive_path).stem


def _safe_target(dest_dir, member_name):
    """Resolve an archive member under ``dest_dir``, or None if it escapes.

    Guards against zip-slip: a crafted archive can carry ``../`` components or
    an absolute path and would otherwise write outside the ROM folder.
    """
    dest_dir = Path(dest_dir).resolve()
    target = (dest_dir / member_name).resolve()
    try:
        target.relative_to(dest_dir)
    except ValueError:
        logger.warning("archives rejected traversing entry: name=%s", member_name)
        return None
    return target


def extract_archive(archive_path, dest_dir, extensions=None):
    """Extract an archive into ``dest_dir``, flattening any inner folders.

    Returns the list of extracted file paths. ``extensions`` limits extraction
    to matching entries plus their sidecars (a ``.cue`` needs its ``.bin``), so
    passing None extracts everything that is not junk.
    """
    dest_dir = Path(dest_dir)
    extracted = []
    try:
        with zipfile.ZipFile(archive_path) as archive:
            members = [info for info in archive.infolist() if not info.is_dir()]
            for info in members:
                if _is_junk(info.filename):
                    continue
                # Flatten: disc sets reference sibling tracks by bare filename,
                # so a nested folder layout would break the .cue references.
                flat_name = Path(info.filename).name
                target = _safe_target(dest_dir, flat_name)
                if target is None:
                    continue
                if target.exists():
                    logger.info("archives extract skip existing: path=%s", target)
                    extracted.append(target)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as src, open(target, "wb") as dst:
                    while True:
                        chunk = src.read(1024 * 1024)
                        if not chunk:
                            break
                        dst.write(chunk)
                extracted.append(target)
                logger.info("archives extracted: archive=%s entry=%s -> %s", archive_path, info.filename, target)
    except Exception as exc:
        logger.warning("archives extract failed: path=%s error=%s", archive_path, exc)
        return extracted
    return extracted
