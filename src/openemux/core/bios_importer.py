"""Import BIOS files the user picked into one console's BIOS folder (issue 667).

The cores look a BIOS up by its exact file name, so the name is the whole
check: a file is accepted only when it is one of the names the catalog lists
for *that* console (each name of an ``any_of`` entry included). The match is
case-insensitive and the copy is saved under the catalog's spelling, because a
core opens ``scph5501.bin`` on a case-sensitive filesystem whatever the user's
download called it.

One bad file never stops the batch: every file gets its own outcome, and the
caller shows them all in one summary.
"""

import errno
import logging
import os
from pathlib import Path
from threading import Thread

from openemux.core.atomic_write import atomic_write_stream
from openemux.core.bios_catalog import CONSOLE_BIOS_REQUIREMENTS, get_console_bios_union
from openemux.core.bios_manager import get_console_bios_dir
from openemux.core.rom_importer import _same_contents
from openemux.core.systems import resolve_system_id

logger = logging.getLogger(__name__)

# Why a file was not imported.
REASON_UNKNOWN = "unknown"              # no console expects this name
REASON_OTHER_CONSOLE = "other_console"  # the name belongs to another console
REASON_ERROR = "error"                  # the file could not be read or written


def _entry_names(entry):
    if "file" in entry:
        return [entry["file"]]
    return list(entry.get("any_of", []))


def console_bios_names(console):
    """Every BIOS name ``console`` expects, in catalog order, without repeats."""
    union = get_console_bios_union(resolve_system_id(console))
    names = []
    for entry in union["required"] + union["optional"]:
        for name in _entry_names(entry):
            if name not in names:
                names.append(name)
    return names


def _owners_by_name():
    """``{lowercase name: [consoles]}`` over the whole catalog, built once per import."""
    owners = {}
    for console in CONSOLE_BIOS_REQUIREMENTS:
        for name in console_bios_names(console):
            consoles = owners.setdefault(name.lower(), [])
            if console not in consoles:
                consoles.append(console)
    return owners


def consoles_expecting(filename):
    """The consoles whose catalog lists ``filename`` (case-insensitive)."""
    return list(_owners_by_name().get(filename.lower(), []))


def _copy_into(source, dest):
    """Copy ``source`` to ``dest`` atomically; True when a different file was there."""
    if source.is_dir():
        raise IsADirectoryError(errno.EISDIR, os.strerror(errno.EISDIR), str(source))
    existed = dest.exists()
    if existed and _same_contents(source, dest):
        return False
    with open(source, "rb") as handle:
        atomic_write_stream(dest, handle)
    return existed


def import_bios_files(paths, config_manager, console):
    """Copy each of ``paths`` whose name ``console`` expects into its BIOS folder.

    Returns ``{"console", "imported": [{source, name, replaced}],
    "rejected": [{source, name, reason, consoles, error}]}``. The sources are
    copied, never moved.
    """
    system_id = resolve_system_id(console)
    expected = {name.lower(): name for name in console_bios_names(system_id)}
    bios_dir = Path(get_console_bios_dir(config_manager, system_id))
    summary = {"console": system_id, "imported": [], "rejected": []}
    owners_by_name = None  # the whole catalog, read only when a name is rejected

    for raw in paths:
        source = Path(raw)
        canonical = expected.get(source.name.lower())
        if canonical is None:
            if owners_by_name is None:
                owners_by_name = _owners_by_name()
            owners = [c for c in owners_by_name.get(source.name.lower(), []) if c != system_id]
            reason = REASON_OTHER_CONSOLE if owners else REASON_UNKNOWN
            logger.info("bios import: name=%s console=%s status=%s", source.name, system_id, reason)
            summary["rejected"].append({
                "source": str(source), "name": source.name, "reason": reason,
                "consoles": owners, "error": None,
            })
            continue
        try:
            bios_dir.mkdir(parents=True, exist_ok=True)
            replaced = _copy_into(source, bios_dir / canonical)
        except OSError as exc:
            logger.warning(
                "bios import: name=%s console=%s status=error error=%s", source.name, system_id, exc
            )
            summary["rejected"].append({
                "source": str(source), "name": source.name, "reason": REASON_ERROR,
                "consoles": [], "error": exc.strerror or str(exc),
            })
            continue
        logger.info(
            "bios import: name=%s console=%s status=%s",
            canonical, system_id, "replaced" if replaced else "imported",
        )
        summary["imported"].append({"source": str(source), "name": canonical, "replaced": replaced})
    return summary


def _failed_summary(paths, console, exc):
    """Every path rejected with ``exc``: what the caller gets when the import itself broke."""
    error = str(exc) or type(exc).__name__
    return {
        "console": resolve_system_id(console),
        "imported": [],
        "rejected": [
            {"source": str(raw), "name": Path(raw).name, "reason": REASON_ERROR,
             "consoles": [], "error": error}
            for raw in paths
        ],
    }


def import_bios_files_async(paths, config_manager, console, on_done):
    """Run :func:`import_bios_files` on a background thread; ``on_done(summary)`` there.

    ``on_done`` is always called, even when the import raises something
    unexpected: the caller holds its Import buttons until it hears back.
    """

    def _worker():
        try:
            summary = import_bios_files(paths, config_manager, console)
        except Exception as exc:  # the UI must never wait forever
            logger.exception("bios import: console=%s failed", console)
            summary = _failed_summary(paths, console, exc)
        on_done(summary)

    Thread(target=_worker, daemon=True).start()
