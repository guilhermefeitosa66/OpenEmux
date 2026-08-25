"""Export and import everything a player would hate to lose (issue #293).

Two kinds of file, in two different places, because RetroArch puts them there:

* **save states** live under OpenEmux's own tree, ``~/.openemux/states/<CONSOLE>/``
  (the launcher points ``savestate_directory`` at it -- issue #73);
* **battery saves** -- ``.srm``, ``.rtc``, and whatever else a core invents --
  live *next to the ROM*, because ``savefile_directory`` is deliberately left
  at RetroArch's default.

Finding the second kind is the same question the rename path already answers:
a file in a console's ROM folder that is neither a ROM nor artwork belongs to
a core. Matching on that rather than on a fixed extension list is what makes
multi-dotted shapes like ``Game.data.szsnes`` come along.

Pure and widget-free, one test file: the repo's core-module convention.
"""

import json
import logging
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from threading import Thread

from openemux.core.scraper import SUPPORTED_COVER_EXTS
from openemux.core.systems import SYSTEM_IDS, get_supported_extensions, resolve_system_id

logger = logging.getLogger(__name__)

#: Bumped when the archive layout changes in a way an older app cannot read.
BACKUP_VERSION = 1

MANIFEST_NAME = "openemux-saves.json"
STATES_PREFIX = "states"
SAVES_PREFIX = "saves"

#: What to do when a file being imported already exists.
ON_COLLISION_SKIP = "skip"
ON_COLLISION_NEWEST = "newest"
ON_COLLISION_OVERWRITE = "overwrite"
COLLISION_POLICIES = (ON_COLLISION_SKIP, ON_COLLISION_NEWEST, ON_COLLISION_OVERWRITE)

_ART_SUFFIXES = {f".{ext.lower().lstrip('.')}" for ext in SUPPORTED_COVER_EXTS}


def is_battery_save(path, console):
    """Is this file in a console's ROM folder a core's save rather than content?

    Neither a ROM (any extension the console's cores load) nor artwork. A
    directory is never one; neither is a dotfile, which is somebody else's
    bookkeeping.
    """
    path = Path(path)
    if not path.is_file() or path.name.startswith("."):
        return False
    suffix = path.suffix.lower()
    if not suffix:
        return False
    if suffix in _ART_SUFFIXES:
        return False
    rom_suffixes = {ext.lower() for ext in get_supported_extensions(console)}
    return suffix not in rom_suffixes


def collect_battery_saves(roms_dir, consoles=None):
    """``{console: [paths]}`` for the battery saves sitting beside the ROMs."""
    roms_dir = Path(roms_dir)
    found = {}
    for console in _consoles_to_scan(consoles):
        console_dir = roms_dir / console
        if not console_dir.is_dir():
            continue
        saves = sorted(
            path
            for path in console_dir.iterdir()
            if is_battery_save(path, console)
        )
        if saves:
            found[console] = saves
    return found


def collect_save_states(states_dir, consoles=None):
    """``{console: [paths]}`` for the save states, screenshots included.

    RetroArch with ``sort_savestates_enable`` files states into a per-core
    subdirectory, so those are walked too and their relative shape is kept.
    """
    states_dir = Path(states_dir)
    found = {}
    for console in _consoles_to_scan(consoles):
        console_dir = states_dir / console
        if not console_dir.is_dir():
            continue
        states = sorted(
            path for path in console_dir.rglob("*") if path.is_file()
        )
        if states:
            found[console] = states
    return found


def _consoles_to_scan(consoles):
    if consoles is None:
        return list(SYSTEM_IDS)
    wanted = []
    for console in consoles:
        canonical = resolve_system_id(console)
        if canonical in SYSTEM_IDS and canonical not in wanted:
            wanted.append(canonical)
    return wanted


def export_saves(dest_zip, states_dir, roms_dir, consoles=None, on_progress=None):
    """Write every save state and battery save into one zip.

    Returns ``{"states": n, "saves": n, "consoles": [...], "path": str}``.
    """
    dest_zip = Path(dest_zip)
    states = collect_save_states(states_dir, consoles)
    saves = collect_battery_saves(roms_dir, consoles)

    total = sum(len(paths) for paths in states.values()) + sum(
        len(paths) for paths in saves.values()
    )
    written = 0
    dest_zip.parent.mkdir(parents=True, exist_ok=True)
    # Written beside the target and renamed into place: a half-written backup
    # that looks like a whole one is worse than no backup.
    staging = dest_zip.with_name(f".{dest_zip.name}.part")
    try:
        with zipfile.ZipFile(staging, "w", zipfile.ZIP_DEFLATED) as archive:
            for console, paths in sorted(states.items()):
                base = Path(states_dir) / console
                for path in paths:
                    archive.write(path, f"{STATES_PREFIX}/{console}/{path.relative_to(base)}")
                    written += 1
                    _emit(on_progress, written, total, path)
            for console, paths in sorted(saves.items()):
                for path in paths:
                    archive.write(path, f"{SAVES_PREFIX}/{console}/{path.name}")
                    written += 1
                    _emit(on_progress, written, total, path)
            archive.writestr(
                MANIFEST_NAME,
                json.dumps(
                    {
                        "version": BACKUP_VERSION,
                        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        "states": sum(len(p) for p in states.values()),
                        "saves": sum(len(p) for p in saves.values()),
                        "consoles": sorted(set(states) | set(saves)),
                    },
                    indent=2,
                    sort_keys=True,
                ),
            )
        staging.replace(dest_zip)
    finally:
        if staging.exists():
            staging.unlink(missing_ok=True)

    summary = {
        "path": str(dest_zip),
        "states": sum(len(p) for p in states.values()),
        "saves": sum(len(p) for p in saves.values()),
        "consoles": sorted(set(states) | set(saves)),
    }
    logger.info(
        "save_backup exported: path=%s states=%d saves=%d consoles=%d",
        dest_zip, summary["states"], summary["saves"], len(summary["consoles"]),
    )
    return summary


def read_manifest(src_zip):
    """The archive's manifest, or ``None`` if this is not one of ours."""
    try:
        with zipfile.ZipFile(src_zip) as archive:
            with archive.open(MANIFEST_NAME) as handle:
                return json.loads(handle.read().decode("utf-8"))
    except (KeyError, OSError, ValueError, zipfile.BadZipFile) as exc:
        logger.warning("save_backup unreadable archive: path=%s error=%s", src_zip, exc)
        return None


def import_saves(src_zip, states_dir, roms_dir, on_collision=ON_COLLISION_NEWEST,
                 on_progress=None):
    """Restore an archive written by :func:`export_saves`.

    Returns ``{"restored": n, "skipped": n, "errors": [...], "manifest": {...}}``.
    Never overwrites a newer file unless asked to: the default keeps whichever
    side was saved last, which is what someone restoring onto a machine they
    have already played on wants.
    """
    if on_collision not in COLLISION_POLICIES:
        on_collision = ON_COLLISION_NEWEST
    manifest = read_manifest(src_zip)
    result = {"restored": 0, "skipped": 0, "errors": [], "manifest": manifest}
    if manifest is None:
        result["errors"].append({"path": str(src_zip), "error": "not an OpenEmux save backup"})
        return result

    states_dir = Path(states_dir)
    roms_dir = Path(roms_dir)
    with zipfile.ZipFile(src_zip) as archive:
        members = [info for info in archive.infolist() if not info.is_dir()]
        total = len(members)
        for index, info in enumerate(members, start=1):
            if info.filename == MANIFEST_NAME:
                continue
            target = _target_for(info.filename, states_dir, roms_dir)
            if target is None:
                result["skipped"] += 1
                continue
            try:
                if target.exists() and not _should_replace(target, info, on_collision):
                    result["skipped"] += 1
                    _emit(on_progress, index, total, target)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, open(target, "wb") as handle:
                    shutil.copyfileobj(source, handle)
                result["restored"] += 1
                _emit(on_progress, index, total, target)
            except OSError as exc:
                logger.warning("save_backup restore failed: path=%s error=%s", target, exc)
                result["errors"].append({"path": str(target), "error": str(exc)})

    logger.info(
        "save_backup imported: path=%s restored=%d skipped=%d errors=%d",
        src_zip, result["restored"], result["skipped"], len(result["errors"]),
    )
    return result


def _target_for(member_name, states_dir, roms_dir):
    """Where an archive member lands, or ``None`` if it may not land at all.

    A member naming a console we do not know, or trying to climb out of its
    directory, is refused rather than written -- an archive is untrusted
    input, whoever it came from.
    """
    parts = Path(member_name).parts
    if len(parts) < 3:
        return None
    prefix, console, rest = parts[0], parts[1], parts[2:]
    if any(part in ("..", "") or part.startswith("/") for part in rest):
        return None
    canonical = resolve_system_id(console)
    if canonical not in SYSTEM_IDS:
        return None
    if prefix == STATES_PREFIX:
        base = states_dir / canonical
    elif prefix == SAVES_PREFIX:
        base = roms_dir / canonical
    else:
        return None
    target = (base / Path(*rest)).resolve()
    try:
        target.relative_to(base.resolve())
    except ValueError:
        return None
    return target


def _should_replace(target, info, on_collision):
    if on_collision == ON_COLLISION_OVERWRITE:
        return True
    if on_collision == ON_COLLISION_SKIP:
        return False
    # "newest": the archive wins only when it holds the later file.
    archived = datetime(*info.date_time).timestamp()
    try:
        return archived > target.stat().st_mtime
    except OSError:
        return True


def _emit(on_progress, current, total, path):
    if not on_progress:
        return
    on_progress({"current": current, "total": total, "path": str(path), "name": Path(path).name})


def export_saves_async(dest_zip, states_dir, roms_dir, on_done, consoles=None,
                       on_progress=None):
    """Run :func:`export_saves` on a background thread (see ``import_roms_async``)."""

    def _worker():
        try:
            summary = export_saves(
                dest_zip, states_dir, roms_dir, consoles=consoles, on_progress=on_progress
            )
        except OSError as exc:
            logger.warning("save_backup export failed: path=%s error=%s", dest_zip, exc)
            summary = {"path": str(dest_zip), "error": str(exc)}
        if on_done:
            on_done(summary)

    Thread(target=_worker, daemon=True).start()


def import_saves_async(src_zip, states_dir, roms_dir, on_done,
                       on_collision=ON_COLLISION_NEWEST, on_progress=None):
    """Run :func:`import_saves` on a background thread."""

    def _worker():
        try:
            result = import_saves(
                src_zip, states_dir, roms_dir,
                on_collision=on_collision, on_progress=on_progress,
            )
        except (OSError, zipfile.BadZipFile) as exc:
            logger.warning("save_backup import failed: path=%s error=%s", src_zip, exc)
            result = {"restored": 0, "skipped": 0, "errors": [{"path": str(src_zip), "error": str(exc)}]}
        if on_done:
            on_done(result)

    Thread(target=_worker, daemon=True).start()


def default_backup_name(now=None):
    """``openemux-saves-YYYY-MM-DD.zip`` -- the name the file chooser offers."""
    stamp = (now or datetime.now()).strftime("%Y-%m-%d")
    return f"openemux-saves-{stamp}.zip"

