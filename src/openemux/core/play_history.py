"""When each game was last played, so the library can sort by it.

A ROM entry is derived from the filesystem on every scan, so it has nowhere to
carry this: it lives in its own JSON file keyed by ROM path.

Deliberately tolerant. A history that cannot be read or written is not worth an
error in front of the user -- the library just falls back to sorting the games
it can, so every failure path here degrades to "no history" instead of raising.
"""

import json
import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)

#: Written next to config.yaml, like the playlists and input profiles.
DEFAULT_HISTORY_FILE = Path.home() / ".openemux" / "play_history.json"


class PlayHistory:
    """Last-played timestamps and play counts, persisted as JSON."""

    def __init__(self, history_file=DEFAULT_HISTORY_FILE, clock=time.time):
        self.history_file = Path(history_file)
        self._clock = clock
        self._entries = self._load()

    # -- persistence -------------------------------------------------------
    def _load(self):
        try:
            with open(self.history_file, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as exc:
            logger.info("play history unreadable, starting empty: %s", exc)
            return {}
        if not isinstance(data, dict):
            return {}
        entries = {}
        for path, entry in data.items():
            if isinstance(entry, dict):
                entries[str(path)] = {
                    "last_played": _as_float(entry.get("last_played")),
                    "play_count": _as_int(entry.get("play_count")),
                }
        return entries

    def save(self):
        try:
            self.history_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.history_file, "w", encoding="utf-8") as handle:
                json.dump(self._entries, handle, indent=2, sort_keys=True)
        except OSError as exc:
            logger.info("play history not saved: %s", exc)

    # -- queries -----------------------------------------------------------
    def last_played(self, rom_path):
        """Epoch seconds of the last launch; 0.0 for a game never played."""
        entry = self._entries.get(str(rom_path))
        return entry["last_played"] if entry else 0.0

    def play_count(self, rom_path):
        entry = self._entries.get(str(rom_path))
        return entry["play_count"] if entry else 0

    def has_history(self):
        return bool(self._entries)

    # -- updates -----------------------------------------------------------
    def record_launch(self, rom_path):
        """Stamp a launch and persist it. Returns the timestamp written."""
        key = str(rom_path)
        now = float(self._clock())
        entry = self._entries.setdefault(key, {"last_played": 0.0, "play_count": 0})
        entry["last_played"] = now
        entry["play_count"] += 1
        self.save()
        return now

    def forget(self, rom_path):
        """Drop a ROM's history (the file was deleted)."""
        if self._entries.pop(str(rom_path), None) is not None:
            self.save()

    def repath(self, old_path, new_path):
        """Follow a renamed ROM, so its history is not orphaned by the rename."""
        entry = self._entries.pop(str(old_path), None)
        if entry is None:
            return
        self._entries[str(new_path)] = entry
        self.save()


def _as_float(value):
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return 0.0


def _as_int(value):
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0
