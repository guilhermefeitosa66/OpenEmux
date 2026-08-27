"""Browsing and deleting RetroArch save states (issue #73).

The launcher points ``savestate_directory`` at OpenEmux's own per-console
tree (``~/.openemux/states/<CONSOLE>/``), so managing states is plain
filesystem work over files RetroArch names after the content file:

    <rom-stem>.state      slot 0
    <rom-stem>.state<N>   slot N (1..)
    <rom-stem>.state.auto the automatic state -- not a user slot, ignored
    <...>.png             companion screenshot, when thumbnails are enabled

Pure and widget-free, one test file: the repo's core-module convention.
"""

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

_STATE_SUFFIX_RE = re.compile(r"^\.state(\d*)$")


class SaveState:
    """One state file on disk: slot, timestamps, optional screenshot."""

    def __init__(self, path, slot, mtime, thumbnail=None):
        self.path = Path(path)
        self.slot = int(slot)
        self.mtime = mtime
        self.thumbnail = Path(thumbnail) if thumbnail else None


def rom_state_stem(rom_path):
    """The basename RetroArch keys a ROM's states on: the content file stem."""
    return Path(rom_path).stem


def _slot_for(path):
    match = _STATE_SUFFIX_RE.match(path.suffix)
    if match is None:
        return None
    return int(match.group(1)) if match.group(1) else 0


def _entries(directory):
    """List a directory, or nothing when it cannot be listed.

    A subdirectory the user cannot read, or one removed between the is_dir()
    check and the listing, used to raise straight out of the states context
    menu and the hot-apply poll (issue #234).
    """
    try:
        return list(directory.iterdir())
    except OSError as exc:
        logger.debug("save states: cannot list %s: %s", directory, exc)
        return []


def _scan_dirs(directory):
    """The console directory and each per-core subdirectory under it."""
    return [directory] + [entry for entry in _entries(directory) if entry.is_dir()]


def list_states(states_dir, rom_path):
    """Every user slot saved for ``rom_path``, sorted by slot number.

    RetroArch with ``sort_savestates_enable`` on files each state into a
    per-core subdirectory (``SFC/Snes9x/…``) rather than the console dir
    itself, so the immediate subdirectories are scanned too. When the same
    slot exists in more than one place (two cores saved it), the newest file
    wins -- it is the one the user just made.
    """
    directory = Path(states_dir)
    if not directory.is_dir():
        return []
    stem = rom_state_stem(rom_path)
    by_slot = {}
    for scan_dir in _scan_dirs(directory):
        for path in _entries(scan_dir):
            if not path.is_file() or path.stem != stem:
                continue
            slot = _slot_for(path)
            if slot is None:  # .state.auto, .png companions, unrelated files
                continue
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            current = by_slot.get(slot)
            if current is not None and current.mtime >= mtime:
                continue
            thumbnail = path.with_name(path.name + ".png")
            by_slot[slot] = SaveState(
                path,
                slot,
                mtime,
                thumbnail=thumbnail if thumbnail.is_file() else None,
            )
    return sorted(by_slot.values(), key=lambda state: state.slot)


def slot_entries(states_dir, rom_path, max_slot=9):
    """``(slot, mtime-or-None)`` for every slot up to ``max_slot``.

    The context menu's "load state" list wants the full slot range with the
    empty ones visible (shown as "empty"), so absence is data here, not an
    omission.
    """
    by_slot = {state.slot: state.mtime for state in list_states(states_dir, rom_path)}
    return [(slot, by_slot.get(slot)) for slot in range(max_slot + 1)]


#: What may follow the stem in a state-family filename: ``.state``,
#: ``.state<N>``, ``.state.auto``, each optionally with a ``.png`` thumbnail.
_STATE_FAMILY_RE = re.compile(r"^\.state(?:\d*|\.auto)(?:\.png)?$")


def rename_states(states_dir, old_stem, new_stem):
    """Move every state file keyed on ``old_stem`` to ``new_stem`` (#134).

    Covers slot files, the automatic state and their thumbnails, in the
    console dir and each immediate per-core subdirectory (the
    ``sort_savestates_enable`` layout). A move that would overwrite an
    existing target is skipped and logged -- same refuse-don't-overwrite
    rule as the ROM rename itself. Returns how many files moved.
    """
    directory = Path(states_dir)
    if old_stem == new_stem or not directory.is_dir():
        return 0
    moved = 0
    for scan_dir in _scan_dirs(directory):
        for path in sorted(_entries(scan_dir)):
            if not path.is_file() or not path.name.startswith(old_stem):
                continue
            remainder = path.name[len(old_stem):]
            # The remainder check is what keeps "Mega Man X2.state" safe
            # while "Mega Man X" is being renamed.
            if not _STATE_FAMILY_RE.match(remainder):
                continue
            target = path.with_name(f"{new_stem}{remainder}")
            if target.exists():
                logger.warning(
                    "save state rename skipped, target exists: %s -> %s", path, target
                )
                continue
            try:
                path.rename(target)
                moved += 1
            except OSError as exc:
                logger.warning("save state rename failed: path=%s error=%s", path, exc)
    if moved:
        logger.info(
            "save states renamed: dir=%s old=%s new=%s files=%d",
            directory, old_stem, new_stem, moved,
        )
    return moved


def delete_state(state):
    """Remove one state and its screenshot; True when the state file went."""
    removed = False
    try:
        state.path.unlink()
        removed = True
    except OSError as exc:
        logger.warning("save state delete failed: path=%s error=%s", state.path, exc)
    if state.thumbnail is not None:
        try:
            state.thumbnail.unlink()
        except OSError:
            pass
    return removed
