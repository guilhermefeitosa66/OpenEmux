"""Where each artwork file came from (issue #510).

Synced and hand-picked art share one file per ROM and kind
(``<roms>/<console>/<covers|labels>/<name>.<ext>``), so the file alone cannot
say whether the artwork sync wrote it or the user chose it. This module keeps
that record beside the art, one hidden JSON file per console and kind::

    <roms>/<console>/<kind>/.openemux-sources.json

    {"version": 1, "entries": {"<rom name>": {"source": "synced",
        "file": "<name>.png", "mtime_ns": 123, "updated": "...Z", ...}}}

Living next to the art means it travels with the library folder, and the art
lookup -- which only ever matches ``<name>.<png|jpg|jpeg|webp>`` -- never sees
it. A record is believed only while it still matches the file on disk (name
and ``st_mtime_ns``): art replaced by hand reads as a plain local file again.

Provenance is a nicety. Nothing here may break a save or a sync, so every
read failure reads as "no records" and every write failure is logged and
swallowed.
"""

import json
import logging
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from openemux.core.atomic_write import atomic_write_text
from openemux.core.scraper import COVER_ART, LABEL_ART, find_local_art

logger = logging.getLogger(__name__)

SOURCE_SYNCED = "synced"
SOURCE_MANUAL = "manual"
SOURCE_LOCAL = "local"

SOURCES_FILE = ".openemux-sources.json"
SCHEMA_VERSION = 1

#: Sync workers run in parallel, and every write is a read-modify-write of a
#: shared file: one lock keeps two of them from dropping each other's entry.
_lock = threading.Lock()


@dataclass
class ArtState:
    """What the artwork manager shows about one ROM's art of one kind."""

    path: Path
    source: str
    updated: datetime | None = None
    provider: str | None = None


def sources_path(roms_dir, console, kind):
    return Path(roms_dir) / console / kind / SOURCES_FILE


def _load(path):
    """The entries in ``path``; an absent or damaged file reads as none."""
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError as exc:
        logger.warning("artwork sources unreadable: path=%s error=%s", path, exc)
        return {}
    try:
        data = json.loads(raw)
    except ValueError as exc:
        logger.warning("artwork sources corrupt: path=%s error=%s", path, exc)
        return {}
    entries = data.get("entries") if isinstance(data, dict) else None
    if not isinstance(data, dict) or data.get("version") != SCHEMA_VERSION or not isinstance(
        entries, dict
    ):
        logger.warning("artwork sources has an unknown layout, ignored: path=%s", path)
        return {}
    return {name: entry for name, entry in entries.items() if isinstance(entry, dict)}


def _store(path, entries):
    payload = {"version": SCHEMA_VERSION, "entries": entries}
    try:
        atomic_write_text(path, json.dumps(payload, indent=1, sort_keys=True, ensure_ascii=False))
    except OSError as exc:
        logger.warning("artwork sources not written: path=%s error=%s", path, exc)


def _entry(path, source, meta):
    """The record for ``path``, or None when the file cannot be stat'ed."""
    path = Path(path)
    try:
        mtime_ns = path.stat().st_mtime_ns
    except OSError as exc:
        logger.warning("artwork sources cannot stat art: path=%s error=%s", path, exc)
        return None
    entry = {
        "source": source,
        "file": path.name,
        "mtime_ns": mtime_ns,
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    entry.update({key: value for key, value in meta.items() if value is not None})
    return entry


def _apply(path, change):
    """Read ``path``, let ``change(entries)`` edit it, write it back."""
    with _lock:
        entries = _load(path)
        if change(entries) is not False:
            _store(path, entries)


def record(roms_dir, console, kind, rom_name, path, source, **meta):
    """Note that ``path`` (this ROM's art of ``kind``) came from ``source``."""
    entry = _entry(path, source, meta)
    if entry is None:
        return

    def _set(entries):
        entries[rom_name] = entry

    _apply(sources_path(roms_dir, console, kind), _set)


def forget(roms_dir, console, kind, rom_name):
    """Drop the record of art that was just removed."""
    path = sources_path(roms_dir, console, kind)
    if not path.exists():
        return

    def _drop(entries):
        return entries.pop(rom_name, None) is not None

    _apply(path, _drop)


def rename(roms_dir, console, old_name, new_name):
    """Carry the records over to a renamed ROM, for every kind.

    Mirrors :func:`openemux.core.scraper.rename_local_art`, which moves the
    files themselves; ``file`` follows the new name, ``mtime_ns`` survives
    because a rename does not touch it.
    """
    for kind in (COVER_ART, LABEL_ART):
        path = sources_path(roms_dir, console, kind)
        if not path.exists():
            continue

        def _move(entries):
            entry = entries.pop(old_name, None)
            if entry is None:
                return False
            suffix = Path(str(entry.get("file", ""))).suffix
            entry["file"] = f"{new_name}{suffix}"
            entries[new_name] = entry
            return True

        _apply(path, _move)


def _parse_updated(value):
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def describe(roms_dir, console, rom_name, kind):
    """This ROM's art of ``kind`` and where it came from; None when it has none."""
    found = find_local_art(Path(roms_dir), console, rom_name, kind)
    if found is None:
        return None
    entry = _load(sources_path(roms_dir, console, kind)).get(rom_name)
    try:
        mtime_ns = found.stat().st_mtime_ns
    except OSError:
        mtime_ns = None
    if (
        entry is None
        or entry.get("file") != found.name
        or entry.get("mtime_ns") != mtime_ns
        or entry.get("source") not in (SOURCE_SYNCED, SOURCE_MANUAL)
    ):
        return ArtState(path=found, source=SOURCE_LOCAL)
    provider = entry.get("provider")
    return ArtState(
        path=found,
        source=entry["source"],
        updated=_parse_updated(entry.get("updated")),
        provider=provider if isinstance(provider, str) else None,
    )


class _Batch:
    """Buffers :func:`record` calls for a bulk sync and writes each file once."""

    def __init__(self, roms_dir):
        self.roms_dir = roms_dir
        self._pending = {}

    def record(self, console, kind, rom_name, path, source, **meta):
        entry = _entry(path, source, meta)
        if entry is None:
            return
        self._pending.setdefault((console, kind), {})[rom_name] = entry

    def flush(self):
        pending, self._pending = self._pending, {}
        for (console, kind), new_entries in pending.items():
            _apply(
                sources_path(self.roms_dir, console, kind),
                lambda entries, new=new_entries: entries.update(new),
            )


@contextmanager
def batch(roms_dir):
    """A recorder whose writes land on exit -- also on an exception or cancel.

    A library sync of 2,000 ROMs would otherwise rewrite the same file 2,000
    times.
    """
    recorder = _Batch(roms_dir)
    try:
        yield recorder
    finally:
        recorder.flush()
