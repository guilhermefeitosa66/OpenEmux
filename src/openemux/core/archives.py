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
import zlib
from collections import Counter
from pathlib import Path, PurePosixPath

from openemux.core.atomic_write import atomic_write_stream

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


def rename_archive_rom_entry(archive_path, new_stem, extensions):
    """Rename the single ROM entry inside an archive, keeping its extension.

    An archive's display name comes from the entry it holds (see
    :func:`archive_rom_name`), so renaming the container alone would leave the
    library showing the old title. Zip entries cannot be renamed in place, so
    the archive is rewritten next to itself and swapped in only once it is
    complete -- an interrupted rename leaves the original untouched.
    """
    archive_path = Path(archive_path)
    matches = archive_entries(archive_path, extensions)
    if len(matches) != 1:
        return False

    target_name = matches[0].name
    renamed = f"{new_stem}{matches[0].suffix}"
    if renamed == target_name:
        return False

    tmp_path = archive_path.with_name(f"{archive_path.name}.renaming")
    try:
        with zipfile.ZipFile(archive_path) as source:
            with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as dest:
                for info in source.infolist():
                    if info.is_dir():
                        continue
                    data = source.read(info)
                    name = renamed if info.filename == str(matches[0]) else info.filename
                    entry = zipfile.ZipInfo(name, date_time=info.date_time)
                    entry.compress_type = info.compress_type
                    entry.external_attr = info.external_attr
                    dest.writestr(entry, data)
        tmp_path.replace(archive_path)
    except Exception as exc:
        logger.warning("archives rename failed: path=%s error=%s", archive_path, exc)
        tmp_path.unlink(missing_ok=True)
        raise
    logger.info("archives renamed entry: archive=%s %s -> %s", archive_path, target_name, renamed)
    return True


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


def plan_extraction(members):
    """Where each member goes, relative to the destination, in member order.

    Flat by default: disc sets reference sibling tracks by bare filename, so a
    nested layout would break the ``.cue`` references. But a multi-disc
    archive has ``Disc 1/track01.bin`` *and* ``Disc 2/track01.bin``, and
    flattening those onto one name used to write the first and silently report
    the second as extracted too -- the import then offered a disc 2 holding
    disc 1's data (issue #229).

    So the colliding entries keep the folder they came from instead. Each
    ``.cue`` still sits beside its own tracks, one directory down, which is
    the layout that makes the references resolve. Anything left ambiguous
    after that (a zip really can carry the same path twice) gets a
    ``name (2).ext`` sibling rather than being dropped.
    """
    names = [PurePosixPath(info.filename).name for info in members]
    collisions = {name for name, count in Counter(names).items() if count > 1}

    planned = []
    used = set()
    for info, name in zip(members, names):
        if name in collisions:
            folder = PurePosixPath(info.filename).parent.name
            relative = f"{folder}/{name}" if folder else name
        else:
            relative = name
        relative = _unique_relative(relative, used)
        used.add(relative.casefold())
        planned.append(relative)
    return planned


def _unique_relative(relative, used):
    if relative.casefold() not in used:
        return relative
    path = PurePosixPath(relative)
    counter = 2
    while True:
        candidate = str(path.with_name(f"{path.stem} ({counter}){path.suffix}"))
        if candidate.casefold() not in used:
            return candidate
        counter += 1


def _unique_target(target):
    """``target`` or a ``name (2).ext`` sibling that is not taken."""
    counter = 2
    while True:
        candidate = target.with_name(f"{target.stem} ({counter}){target.suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


def _crc32_of(path, chunk_size=1024 * 1024):
    checksum = 0
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            checksum = zlib.crc32(chunk, checksum)
    return checksum & 0xFFFFFFFF


def _starts_the_same(path, archive, info, length, chunk_size=1024 * 1024):
    """True when the first ``length`` bytes of ``path`` are the entry's."""
    with open(path, "rb") as existing, archive.open(info) as src:
        remaining = length
        while remaining > 0:
            want = min(chunk_size, remaining)
            here = existing.read(want)
            there = src.read(want)
            if not here or here != there:
                return False
            remaining -= len(here)
    return True


def _existing_verdict(target, archive, info):
    """What the file already sitting at ``target`` is: the entry, half of it,
    or something else entirely."""
    try:
        size = target.stat().st_size
    except OSError:
        return "different"
    if size == info.file_size:
        return "same" if _crc32_of(target) == info.CRC else "different"
    if size < info.file_size and _starts_the_same(target, archive, info, size):
        # An extraction of this very entry that was cut short. Before the
        # write became atomic this was how a truncated ROM got left at its
        # final name -- and "skip existing" then blessed it forever.
        return "partial"
    return "different"


def extract_archive(archive_path, dest_dir, extensions=None):
    """Extract an archive into ``dest_dir``, flattening any inner folders.

    Returns the list of extracted file paths. ``extensions`` limits extraction
    to matching entries plus their sidecars (a ``.cue`` needs its ``.bin``), so
    passing None extracts everything that is not junk.

    Each entry is written through a temporary file and renamed into place, so
    an interrupted extraction leaves nothing at the final path rather than a
    truncated ROM that every later import would skip as already there.
    """
    dest_dir = Path(dest_dir)
    extracted = []
    try:
        with zipfile.ZipFile(archive_path) as archive:
            members = [
                info
                for info in archive.infolist()
                if not info.is_dir() and not _is_junk(info.filename)
            ]
            for info, relative in zip(members, plan_extraction(members)):
                target = _safe_target(dest_dir, relative)
                if target is None:
                    continue
                if target.exists():
                    verdict = _existing_verdict(target, archive, info)
                    if verdict == "same":
                        logger.info("archives extract skip existing: path=%s", target)
                        extracted.append(target)
                        continue
                    if verdict == "different":
                        # Somebody else's file under the same name. Never
                        # overwrite it, and never report it as this entry.
                        target = _unique_target(target)
                    else:
                        logger.info("archives extract repairs partial: path=%s", target)
                with archive.open(info) as src:
                    atomic_write_stream(target, src)
                extracted.append(target)
                logger.info("archives extracted: archive=%s entry=%s -> %s", archive_path, info.filename, target)
    except Exception as exc:
        logger.warning("archives extract failed: path=%s error=%s", archive_path, exc)
        return extracted
    return extracted
