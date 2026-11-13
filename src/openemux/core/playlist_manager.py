from pathlib import Path
import json
import logging
import threading
import time

from openemux.core.archives import archive_rom_name, is_archive, loads_archives_natively
from openemux.core.atomic_write import atomic_write_text
from openemux.core.dir_walk import relative_to_base
from openemux.core.paths import read_path_lines, write_path_lines
from openemux.core.state_recovery import quarantine_state_file
from openemux.core.systems import SYSTEM_IDS, get_supported_extensions, resolve_system_id

logger = logging.getLogger(__name__)

#: The index beside each console's ``.list`` (issue 901): what the scan
#: derived from the disk -- the display name (an archive's inner title, read
#: by opening the zip), the size and the time the file appeared -- plus the
#: directory fingerprint the scan saw, so a load is a parse and a start-up
#: rescan can tell an unchanged console from a changed one without walking it.
META_VERSION = 1

#: How long the favorites parse is trusted before the file is stat-ed again
#: for a change made outside the app. The manager's own writes drop the
#: parse at once; this only spaces out the stat that catches everything
#: else, so a page of cards binds without one syscall per star (issue 907).
FAVORITES_STAMP_TTL_S = 0.5


class PlaylistManager:
    def __init__(self, config_manager, scanner):
        self.config_manager = config_manager
        self.scanner = scanner
        # The parsed favorites file, keyed on its (mtime_ns, size) -- the key
        # shape the cover cache already uses. is_favorite() is asked once per
        # card rendered, so the parse has to happen once per page, not once
        # per card (issue #217).
        self._favorites_cache = (None, frozenset())
        # When the favorites stamp was last compared; see FAVORITES_STAMP_TTL_S.
        self._favorites_checked_at = None
        # toggle_favorite is a read-modify-write of one file; two of them at
        # once (a click while a rescan repaths) would lose one edit (#208).
        self._write_lock = threading.RLock()

    def get_playlist_path(self, console):
        system_id = resolve_system_id(console)
        return self.config_manager.get_playlists_dir() / f"{system_id}.list"

    def get_favorites_playlist_path(self):
        return self.config_manager.get_playlists_dir() / "FAVORITES.list"

    def get_meta_path(self, console):
        system_id = resolve_system_id(console)
        return self.config_manager.get_playlists_dir() / f"{system_id}.meta.json"

    def playlist_exists(self, console):
        return self.get_playlist_path(console).exists()

    def ensure_playlist(self, console):
        if self.playlist_exists(console):
            return False
        self.scan_and_rebuild_playlist(console)
        return True

    def load_playlist(self, console):
        """The console's games, from the index alone.

        A parse and nothing else (issue 901): no ``exists()`` per ROM and no
        archive opened for its inner name. The scan is what decides what is
        on the disk -- a game deleted outside the app is dropped by the next
        start's rescan, which sees the folder's mtime move -- and the names,
        sizes and dates come from the meta index written beside the list. A
        line the index does not know (a list written by an older version, a
        portable install moved to another machine) is derived from the file
        as before, once, until the next scan writes it down.
        """
        system_id = resolve_system_id(console)
        playlist_path = self.get_playlist_path(console)
        try:
            lines = read_path_lines(playlist_path)
        except OSError:
            logger.info("playlist load skipped: console=%s path=%s reason=missing_file", system_id, playlist_path)
            return []

        entries = []
        logger.info("playlist load started: console=%s path=%s", system_id, playlist_path)
        extensions = get_supported_extensions(system_id)
        known = self._read_meta(system_id).get("roms", {})
        for path_str in lines:
            meta = known.get(path_str)
            if meta is None:
                path = Path(path_str)
                display_name = self._playlist_entry_name(path, system_id, extensions)
                if display_name is None:
                    continue
                entries.append(self._rom_entry(path, system_id, name=display_name))
                continue
            entries.append(
                {
                    "name": meta.get("name") or Path(path_str).stem,
                    "path": path_str,
                    "console": system_id,
                    "size": meta.get("size", 0),
                    "added": meta.get("added", 0.0),
                }
            )

        sorted_entries = sorted(entries, key=lambda x: x["name"])
        logger.info("playlist load finished: console=%s total=%d", system_id, len(sorted_entries))
        return sorted_entries

    # -- the meta index ----------------------------------------------------
    def _read_meta(self, console):
        meta_path = self.get_meta_path(console)
        try:
            raw = json.loads(meta_path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict) or not isinstance(raw.get("roms"), dict):
                raise ValueError("not a meta index")
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as exc:
            quarantine_state_file(meta_path, exc)
            return {}
        return raw

    def _write_meta(self, console, roms, fingerprint):
        payload = {
            "version": META_VERSION,
            "dirs": fingerprint,
            "roms": {
                rom["path"]: {
                    "name": rom["name"],
                    "size": rom.get("size", 0),
                    "added": rom.get("added", 0.0),
                }
                for rom in roms
            },
        }
        atomic_write_text(
            self.get_meta_path(console), json.dumps(payload, sort_keys=True), durable=False
        )

    def name_for_path(self, console, path):
        """The index's display name for a ROM, or None when it has none."""
        return self._read_meta(console).get("roms", {}).get(str(path), {}).get("name")

    def playlist_is_current(self, console):
        """Whether the console's folders are as the last scan left them.

        The fingerprint is the directory mtimes under the console (a file
        added, removed or renamed moves the one holding it); it is compared
        with the one the scan wrote beside the list. A console with no index
        yet, or whose folder is gone, is not current.
        """
        meta = self._read_meta(console)
        if not meta or "dirs" not in meta:
            return False
        return meta["dirs"] == self.scanner.fingerprint(console)

    def entries_for_paths(self, paths):
        """Resolve a flat list of ROM paths into mixed-console rom entries.

        Shared by the favorites list and by collections: each is a bag of paths
        spanning consoles, so the console is derived from the path and missing
        or non-ROM files are skipped, exactly as the favorites list has always
        done.
        """
        entries = []
        seen = set()
        for path_str in paths:
            path_str = str(path_str).strip()
            if not path_str or path_str in seen:
                continue
            seen.add(path_str)
            path = Path(path_str)
            if not path.exists() or not path.is_file():
                continue
            console = self._console_from_rom_path(path)
            if not console:
                continue
            # From the index when it knows the game, so a favorite in an
            # archive is not re-opened on every visit (issue 901).
            display_name = self._known_names(console).get(path_str)
            if display_name is None:
                display_name = self._playlist_entry_name(
                    path, console, get_supported_extensions(console)
                )
            if display_name is None:
                continue
            entries.append(self._rom_entry(path, console, name=display_name))
        return sorted(entries, key=lambda x: x["name"].lower())

    def _known_names(self, console):
        """``{path: name}`` from the console's index, read once per call chain."""
        cache = getattr(self, "_names_cache", None)
        if cache is None or cache[0] != console:
            names = {
                path: meta.get("name")
                for path, meta in self._read_meta(console).get("roms", {}).items()
            }
            self._names_cache = cache = (console, names)
        return cache[1]

    def load_favorites_playlist(self):
        playlist_path = self.get_favorites_playlist_path()
        if not playlist_path.exists():
            return []
        return self.entries_for_paths(read_path_lines(playlist_path))

    def _favorite_paths(self):
        """The favorite paths as written, parsed at most once per file write.

        Deliberately *not* entries_for_paths: resolving a favorite stats the
        file and opens archives to read the inner name, and this is asked once
        per card rendered. A 200-card page with 20 favorites re-read the file
        200 times and re-resolved those 20 ROMs 200 times (issue #217).

        Reading the raw lines also means a favorite whose drive is not mounted
        is still a favorite: it is only missing, and only remove_missing_
        favorites is allowed to decide it is gone.
        """
        now = time.monotonic()
        cached_stamp, cached = self._favorites_cache
        if (
            self._favorites_checked_at is not None
            and now - self._favorites_checked_at < FAVORITES_STAMP_TTL_S
        ):
            return cached
        playlist_path = self.get_favorites_playlist_path()
        try:
            stat = playlist_path.stat()
        except OSError:
            self._favorites_cache = (None, frozenset())
            self._favorites_checked_at = now
            return self._favorites_cache[1]
        stamp = (stat.st_mtime_ns, stat.st_size)
        self._favorites_checked_at = now
        if cached_stamp == stamp:
            return cached
        paths = frozenset(str(Path(line)) for line in read_path_lines(playlist_path))
        self._favorites_cache = (stamp, paths)
        return paths

    def _drop_favorites_cache(self):
        """Forget the parse after writing the file.

        The (mtime, size) key would catch it on its own, but a coarse-grained
        filesystem clock and a rewrite of the same length could land inside
        one tick, and our own writes are the one case we can be exact about.
        """
        self._favorites_cache = (None, frozenset())
        self._favorites_checked_at = None

    def list_favorite_paths(self):
        """A mutable copy of the favorite paths."""
        return set(self._favorite_paths())

    def is_favorite(self, rom_path):
        # No copy: this is the per-card call.
        return str(Path(rom_path)) in self._favorite_paths()

    def has_favorites(self):
        """Whether anything is favorited at all.

        The sidebar asks this on every toggle to decide whether the
        "Favorites" row belongs in the list (issue #382), so it goes through
        the same parsed-once cache the per-card ``is_favorite`` uses -- never
        a fresh read of the file per keystroke.
        """
        return bool(self._favorite_paths())

    def toggle_favorite(self, rom):
        rom_path = str(Path(rom["path"]))
        playlist_path = self.get_favorites_playlist_path()
        with self._write_lock:
            current = self.list_favorite_paths()
            is_now_favorite = rom_path not in current
            if is_now_favorite:
                current.add(rom_path)
            else:
                current.discard(rom_path)

            write_path_lines(playlist_path, sorted(current))
            self._drop_favorites_cache()
        return is_now_favorite

    def remove_missing_favorites(self):
        """Drop the favorites whose ROM is really gone -- not merely unreachable.

        A favorite is an absolute path, and a library kept on an external or
        network drive has unreachable paths every single time the app opens
        without that drive. Deleting them then is not a cleanup, it is data
        loss the user cannot undo: the files were fine, the drive was not, and
        this runs on every visit to the Favorites page (issue #210).

        So a path only goes when the directory that would hold it is there and
        the file is not -- the drive is mounted, the console folder is present,
        and the ROM has genuinely been deleted from it. An unmounted tree is
        left exactly as it is, and the favorites come back with the drive.
        """
        playlist_path = self.get_favorites_playlist_path()
        with self._write_lock:
            if not playlist_path.exists():
                return 0
            original = read_path_lines(playlist_path)
            kept = [path for path in original if not self._rom_is_deleted(path)]
            removed = len(original) - len(kept)
            unreachable = sum(
                1 for path in kept if not Path(path).exists()
            )
            if removed > 0:
                write_path_lines(playlist_path, sorted(set(kept)))
                self._drop_favorites_cache()
        if removed or unreachable:
            logger.info(
                "favorites pruned: deleted=%d unreachable_kept=%d",
                removed,
                unreachable,
            )
        return removed

    def _rom_is_deleted(self, rom_path):
        """True only when the ROM's own directory is there and the file is not.

        The directory is the proof the storage is actually mounted. Without
        it, "the file is not there" says nothing about whether the file still
        exists -- only that we cannot see it right now.
        """
        path = Path(rom_path)
        try:
            if path.exists():
                return False
            return path.parent.is_dir()
        except OSError:
            # A drive that errors instead of answering is unreachable, not
            # empty. Never prune on an I/O error.
            return False

    def forget_rom(self, console, rom_path):
        """Drop a ROM from the console playlist and from the favorites.

        Called after the file itself is gone: a rescan would do the same, but
        it walks the whole tree, and the grid has to refresh right away.
        """
        return self._rewrite_indexes(console, rom_path, None)

    def repath_rom(self, console, old_path, new_path):
        """Point the indexes at a ROM's new path after a rename."""
        return self._rewrite_indexes(console, old_path, new_path)

    def _rewrite_indexes(self, console, old_path, new_path):
        old_line = str(Path(old_path))
        new_line = str(Path(new_path)) if new_path else None
        changed = 0
        # Same read-modify-write on the favorites file that toggle_favorite
        # does, so it takes the same lock (issue #208).
        with self._write_lock:
            for playlist_path in (
                self.get_playlist_path(console),
                self.get_favorites_playlist_path(),
            ):
                if not playlist_path.exists():
                    continue
                lines = read_path_lines(playlist_path)
                if old_line not in lines:
                    continue
                updated = []
                for line in lines:
                    if line != old_line:
                        updated.append(line)
                    elif new_line:
                        updated.append(new_line)
                write_path_lines(playlist_path, updated)
                self._drop_favorites_cache()
                changed += 1
            self._repath_meta(console, old_line, new_line)
        logger.info(
            "playlist reindex: console=%s old=%s new=%s files=%d",
            console,
            old_line,
            new_line,
            changed,
        )
        return changed

    def scan_and_rebuild_playlist(self, console):
        system_id = resolve_system_id(console)
        logger.info("playlist rebuild started: console=%s", system_id)
        # The fingerprint before the walk: a file landing during the scan
        # moves a directory the fingerprint already recorded as older, so
        # the next start rescans rather than trusting a list that missed it.
        fingerprint = self.scanner.fingerprint(system_id)
        roms = self.scanner.scan_console(system_id)
        playlist_path = self.get_playlist_path(system_id)

        for rom in roms:
            # One line per ROM, on a rescan that runs at every launch: the
            # single largest contributor to a startup log that reached 260,000
            # lines (issue #221). The count is in the "finished" line below.
            logger.debug(
                "playlist add rom: console=%s rom=%s path=%s playlist=%s",
                system_id,
                rom["name"],
                rom["path"],
                playlist_path,
            )
        lines = [rom["path"] for rom in roms]
        # Written whole, so the main thread reading this playlist while the
        # rescan worker rebuilds it sees the old list or the new one -- never
        # the half a truncate-and-append left exposed (issue #208). And only
        # when it changed (issue 901): the start-up scan of an unchanged
        # library used to rewrite 31 lists with 62 fsyncs for nothing.
        if self._playlist_lines(playlist_path) != lines:
            write_path_lines(playlist_path, lines)
        self._write_meta(system_id, roms, fingerprint)
        self._names_cache = None

        logger.info("playlist rebuild finished: console=%s total=%d path=%s", system_id, len(roms), playlist_path)
        return roms

    @staticmethod
    def _playlist_lines(playlist_path):
        try:
            return read_path_lines(playlist_path)
        except OSError:
            return None

    def scan_and_rebuild_all_playlists(self, consoles=None, on_progress=None, only_changed=False):
        """Rebuild every console's playlist, one bad console at a time.

        A console that cannot be scanned is recorded and skipped rather than
        ending the run: a single unreadable directory -- or, before the
        surrogate-safe encoding above, a single ROM with a non-UTF-8 name --
        used to abort the whole rescan and leave the rest of the library
        un-scanned (issue #214).

        ``only_changed`` is the start-up scan (issue 901): a console whose
        folders carry the fingerprint the last scan wrote is reported from
        its index and not walked. Refresh asks for everything.
        """
        selected_consoles = list(consoles or SYSTEM_IDS)
        summary = {
            "consoles": {},
            "total_consoles": len(selected_consoles),
            "total_roms": 0,
            "failed": {},
            "skipped": [],
        }
        for index, console in enumerate(selected_consoles, start=1):
            system_id = resolve_system_id(console)
            try:
                if only_changed and self.playlist_is_current(system_id):
                    roms = self.load_playlist(system_id)
                    summary["skipped"].append(system_id)
                else:
                    roms = self.scan_and_rebuild_playlist(console)
            except Exception as exc:
                logger.exception("playlist rebuild failed: console=%s", system_id)
                summary["failed"][system_id] = str(exc)
                roms = []
            count = len(roms)
            summary["consoles"][system_id] = count
            summary["total_roms"] += count
            if on_progress:
                on_progress(
                    {
                        "console": system_id,
                        "current": index,
                        "total": len(selected_consoles),
                        "console_roms": count,
                        "total_roms": summary["total_roms"],
                    }
                )
        if summary["skipped"]:
            logger.info(
                "playlist rebuild skipped unchanged consoles: %d of %d",
                len(summary["skipped"]),
                len(selected_consoles),
            )
        return summary

    def _repath_meta(self, console, old_line, new_line):
        """Follow a rename, or a removal, in the console's index."""
        meta = self._read_meta(console)
        roms = meta.get("roms", {})
        entry = roms.pop(old_line, None)
        if entry is None:
            return
        if new_line:
            entry["name"] = Path(new_line).stem if not is_archive(new_line) else entry.get("name")
            roms[new_line] = entry
        self._names_cache = None
        atomic_write_text(
            self.get_meta_path(console), json.dumps(meta, sort_keys=True), durable=False
        )

    def _playlist_entry_name(self, path, console, extensions):
        """Display name for a playlist line, or None when it is not a ROM.

        Archives are resolved through their inner entry so a zipped ROM shows
        the real game title -- which is also what cover lookups match on.
        """
        if is_archive(path):
            if not loads_archives_natively(console):
                # The core needs a real file; the importer extracts these, so a
                # leftover archive here is not playable.
                return None
            return archive_rom_name(path, extensions)
        if path.suffix.lower() not in extensions:
            return None
        return path.stem

    def _rom_entry(self, path, console, name=None):
        return {
            "name": name or path.stem,
            "path": str(path),
            "console": console,
        }

    def _console_from_rom_path(self, path):
        """Which console a ROM path belongs to, or ``None``.

        The literal path is tried before the resolved one. Resolving first
        rewrote a path going through a symlinked console directory to its
        physical location, which is outside the library root: relative_to
        raised, this returned None, and entries_for_paths skipped the ROM. The
        file still existed, so remove_missing_favorites kept the line -- the
        favourite was stored and never displayed (issue #228).
        """
        roms_base = self.config_manager.get_roms_path()
        relative = relative_to_base(path, roms_base)
        if relative is None or len(relative.parts) < 2:
            return None
        console = resolve_system_id(relative.parts[0])
        return console if console in SYSTEM_IDS else None
