import logging
from pathlib import Path

from openemux.core.bios_catalog import (
    get_console_bios_union,
    get_required_for_core,
    has_any_bios_requirement,
)
from openemux.core.systems import SYSTEM_IDS, get_system_display_name, resolve_system_id

logger = logging.getLogger(__name__)


def _entry_label(entry):
    if "file" in entry:
        return entry["file"]
    names = entry.get("any_of", [])
    if not names:
        return ""
    return " | ".join(names)


def _evaluate_entry(entry, bios_dir):
    bios_dir = Path(bios_dir)
    if "file" in entry:
        filename = entry["file"]
        exists = (bios_dir / filename).exists()
        return {
            "label": filename,
            "present": exists,
            "present_files": [filename] if exists else [],
            "missing_files": [] if exists else [filename],
            "kind": "file",
        }

    names = list(entry.get("any_of", []))
    present_files = [name for name in names if (bios_dir / name).exists()]
    return {
        "label": _entry_label(entry),
        "present": bool(present_files),
        "present_files": present_files,
        "missing_files": [name for name in names if name not in present_files],
        "kind": "any_of",
    }


def get_console_bios_dir(config_manager, console):
    system_id = resolve_system_id(console)
    return config_manager.get_console_bios_dir(system_id)


def _ensure_readable_dir(directory):
    """Create ``directory`` if we can, and carry on if we cannot.

    Both callers below only ever *read* this directory. Creating it is a
    convenience -- it is where the user drops their BIOS files -- so a
    read-only mount or a permission problem must answer "nothing here",
    not raise out of the preferences page and the pre-launch check
    (issue #234).
    """
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.warning("bios dir not created: path=%s error=%s", directory, exc)


def scan_console_bios_status(config_manager, console):
    system_id = resolve_system_id(console)
    bios_dir = get_console_bios_dir(config_manager, system_id)
    _ensure_readable_dir(bios_dir)

    union = get_console_bios_union(system_id)
    required = [_evaluate_entry(entry, bios_dir) for entry in union.get("required", [])]
    optional = [_evaluate_entry(entry, bios_dir) for entry in union.get("optional", [])]
    return {
        "console": system_id,
        "display_name": get_system_display_name(system_id),
        "bios_dir": bios_dir,
        "required": required,
        "optional": optional,
        "has_entries": bool(required or optional),
    }


def scan_all_bios_status(config_manager):
    result = {}
    for console in SYSTEM_IDS:
        if not has_any_bios_requirement(console):
            continue
        status = scan_console_bios_status(config_manager, console)
        if status["has_entries"]:
            result[status["console"]] = status
    return result


def find_missing_required_for_core(config_manager, console, core_filename):
    system_id = resolve_system_id(console)
    bios_dir = get_console_bios_dir(config_manager, system_id)
    _ensure_readable_dir(bios_dir)
    missing = []
    for entry in get_required_for_core(system_id, core_filename):
        evaluated = _evaluate_entry(entry, bios_dir)
        if evaluated["present"]:
            continue
        missing.append(evaluated["label"])
    return missing
