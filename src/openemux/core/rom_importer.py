"""Import ROM files into the per-console library layout.

Pure logic (no GTK): the UI layer drives this through :func:`import_roms_async`,
mirroring the threading pattern used by :mod:`openemux.core.cover_sync`.
"""

import hashlib
import logging
import shutil
import zipfile
from pathlib import Path
from threading import Thread

from openemux.core.archives import (
    ARCHIVE_EXTENSIONS,
    extract_archive,
    is_archive,
    loads_archives_natively,
)
from openemux.core.systems import SYSTEM_IDS, get_supported_extensions

logger = logging.getLogger(__name__)

# Several extensions are shared by more than one console (".bin" alone is used by
# a dozen systems). detect_console() returns every candidate, but the head of the
# list is what the UI offers first, so it is worth curating for the common cases.
_PREFERRED_BY_EXTENSION = {
    ".bin": ["MD", "PS", "A2600", "SMS", "PCE"],
    ".rom": ["A2600", "CV", "INTV", "O2"],
    ".iso": ["PS", "PSP", "GC", "SATURN", "MCD", "PCECD"],
    ".chd": ["PS", "SATURN", "MCD", "PCECD"],
    ".cue": ["PS", "SATURN", "MCD", "PCECD"],
    ".pbp": ["PS", "PSP"],
    ".md": ["MD", "S32X"],
}


def _build_extension_map():
    mapping = {}
    for system_id in SYSTEM_IDS:
        for ext in get_supported_extensions(system_id):
            mapping.setdefault(ext, []).append(system_id)

    ordered = {}
    for ext, candidates in mapping.items():
        preferred = [c for c in _PREFERRED_BY_EXTENSION.get(ext, []) if c in candidates]
        rest = [c for c in candidates if c not in preferred]
        ordered[ext] = preferred + rest
    return ordered


EXTENSION_TO_SYSTEMS = _build_extension_map()

# Extensions the file chooser should offer, archives included.
IMPORTABLE_EXTENSIONS = sorted(set(EXTENSION_TO_SYSTEMS) | set(ARCHIVE_EXTENSIONS))


def detect_console(path):
    """Return candidate console ids for ``path``, most likely first.

    Unambiguous extensions yield a single-element list; unrecognized ones yield
    an empty list. ``.zip`` archives are resolved from their inner entries.
    """
    path = Path(path)
    suffix = path.suffix.lower()

    if suffix in ARCHIVE_EXTENSIONS:
        return _detect_console_from_archive(path)

    return list(EXTENSION_TO_SYSTEMS.get(suffix, []))


def _detect_console_from_archive(path):
    """Resolve the console of a zip from the ROM files it contains."""
    try:
        with zipfile.ZipFile(path) as archive:
            names = [info.filename for info in archive.infolist() if not info.is_dir()]
    except (zipfile.BadZipFile, OSError) as exc:
        logger.warning("rom_import: unreadable archive %s: %s", path, exc)
        return []

    candidates = []
    for name in names:
        for system_id in EXTENSION_TO_SYSTEMS.get(Path(name).suffix.lower(), []):
            if system_id not in candidates:
                candidates.append(system_id)
    return candidates


def _is_importable(path):
    suffix = path.suffix.lower()
    return suffix in EXTENSION_TO_SYSTEMS or suffix in ARCHIVE_EXTENSIONS


def _expand_paths(paths):
    """Flatten the requested paths into a list of candidate files."""
    files = []
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            for child in sorted(path.rglob("*")):
                if child.is_file() and _is_importable(child):
                    files.append(child)
        elif path.is_file():
            files.append(path)
    return files


def _file_digest(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _same_contents(source, dest):
    if source.stat().st_size != dest.stat().st_size:
        return False
    return _file_digest(source) == _file_digest(dest)


def _unique_destination(dest):
    """Return ``dest`` or a ``name (2).ext`` style sibling that does not exist."""
    if not dest.exists():
        return dest
    stem, suffix = dest.stem, dest.suffix
    counter = 2
    while True:
        candidate = dest.with_name(f"{stem} ({counter}){suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


def import_roms(paths, roms_dir, on_progress=None, move=False, console_overrides=None):
    """Copy (or move) ROM files into ``<roms_dir>/<CONSOLE>/``.

    ``console_overrides`` maps a lowercase extension to a console id, letting the
    UI resolve an ambiguous extension once and apply it to the whole batch.

    Returns ``{"imported": [...], "skipped": [...], "unknown": [...], "errors": [...]}``.
    """
    roms_dir = Path(roms_dir)
    overrides = {str(k).lower(): v for k, v in (console_overrides or {}).items()}

    files = _expand_paths(paths)
    total = len(files)

    # "extracted" lists the archives that had to be unpacked because the target
    # console's core cannot read a ROM out of a zip; the UI surfaces this so the
    # behavior difference between consoles is visible rather than surprising.
    result = {"imported": [], "skipped": [], "unknown": [], "errors": [], "extracted": []}

    for index, source in enumerate(files, start=1):
        suffix = source.suffix.lower()
        console = overrides.get(suffix)
        if not console:
            candidates = detect_console(source)
            console = candidates[0] if candidates else None

        if not console:
            logger.info("rom_import: unknown console for %s", source)
            result["unknown"].append(str(source))
            _emit(on_progress, index, total, source, console, "unknown")
            continue

        try:
            target_dir = roms_dir / console
            target_dir.mkdir(parents=True, exist_ok=True)

            # Cores that need a real file on disk cannot read a ROM out of an
            # archive, so unpack rather than copying the container across.
            if is_archive(source) and not loads_archives_natively(console):
                extracted = extract_archive(
                    source, target_dir, extensions=get_supported_extensions(console)
                )
                if not extracted:
                    logger.info("rom_import: nothing extracted from %s", source)
                    result["unknown"].append(str(source))
                    _emit(on_progress, index, total, source, console, "unknown")
                    continue
                if move:
                    source.unlink(missing_ok=True)
                for path in extracted:
                    result["imported"].append(str(path))
                result["extracted"].append(str(source))
                logger.info("rom_import: extracted %s -> %s (%d files)", source, target_dir, len(extracted))
                _emit(on_progress, index, total, source, console, "imported")
                continue

            dest = target_dir / source.name

            if dest.exists() and dest.resolve() == source.resolve():
                result["skipped"].append(str(dest))
                _emit(on_progress, index, total, source, console, "skipped")
                continue

            if dest.exists() and _same_contents(source, dest):
                logger.info("rom_import: already imported %s", dest)
                result["skipped"].append(str(dest))
                _emit(on_progress, index, total, source, console, "skipped")
                continue

            dest = _unique_destination(dest)
            if move:
                shutil.move(str(source), str(dest))
            else:
                shutil.copy2(str(source), str(dest))
            logger.info("rom_import: imported %s -> %s", source, dest)
            result["imported"].append(str(dest))
            _emit(on_progress, index, total, source, console, "imported")
        except OSError as exc:
            logger.warning("rom_import: failed to import %s: %s", source, exc)
            result["errors"].append({"path": str(source), "error": str(exc)})
            _emit(on_progress, index, total, source, console, "error")

    logger.info(
        "rom_import finished: imported=%d extracted=%d skipped=%d unknown=%d errors=%d",
        len(result["imported"]),
        len(result["extracted"]),
        len(result["skipped"]),
        len(result["unknown"]),
        len(result["errors"]),
    )
    return result


def _emit(on_progress, current, total, source, console, status):
    if not on_progress:
        return
    on_progress(
        {
            "current": current,
            "total": total,
            "path": str(source),
            "name": Path(source).name,
            "console": console,
            "status": status,
        }
    )


def collect_ambiguous_extensions(paths):
    """Return ``{extension: [candidate ids]}`` for files needing disambiguation."""
    ambiguous = {}
    for source in _expand_paths(paths):
        suffix = source.suffix.lower()
        if suffix in ambiguous:
            continue
        candidates = detect_console(source)
        if len(candidates) > 1:
            ambiguous[suffix] = candidates
    return ambiguous


def import_roms_async(paths, roms_dir, on_done, on_progress=None, move=False, console_overrides=None):
    """Run :func:`import_roms` on a background thread (see ``sync_covers_async``)."""

    def _worker():
        summary = import_roms(
            paths=paths,
            roms_dir=roms_dir,
            on_progress=on_progress,
            move=move,
            console_overrides=console_overrides,
        )
        if on_done:
            on_done(summary)

    Thread(target=_worker, daemon=True).start()
