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


def list_states(states_dir, rom_path):
    """Every user slot saved for ``rom_path``, sorted by slot number."""
    directory = Path(states_dir)
    if not directory.is_dir():
        return []
    stem = rom_state_stem(rom_path)
    states = []
    for path in directory.iterdir():
        if not path.is_file() or path.stem != stem:
            continue
        slot = _slot_for(path)
        if slot is None:  # .state.auto, .png companions, unrelated files
            continue
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        thumbnail = path.with_name(path.name + ".png")
        states.append(
            SaveState(
                path,
                slot,
                mtime,
                thumbnail=thumbnail if thumbnail.is_file() else None,
            )
        )
    return sorted(states, key=lambda state: state.slot)


def slot_entries(states_dir, rom_path, max_slot=9):
    """``(slot, mtime-or-None)`` for every slot up to ``max_slot``.

    The context menu's "load state" list wants the full slot range with the
    empty ones visible (shown as "empty"), so absence is data here, not an
    omission.
    """
    by_slot = {state.slot: state.mtime for state in list_states(states_dir, rom_path)}
    return [(slot, by_slot.get(slot)) for slot in range(max_slot + 1)]


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
