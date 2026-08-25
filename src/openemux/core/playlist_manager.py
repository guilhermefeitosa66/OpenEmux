from pathlib import Path
import logging

from openemux.core.archives import archive_rom_name, is_archive, loads_archives_natively
from openemux.core.systems import SYSTEM_IDS, get_supported_extensions, resolve_system_id

logger = logging.getLogger(__name__)


class PlaylistManager:
    def __init__(self, config_manager, scanner):
        self.config_manager = config_manager
        self.scanner = scanner
        # The parsed favorites file, keyed on its (mtime_ns, size) -- the key
        # shape the cover cache already uses. is_favorite() is asked once per
        # card rendered, so the parse has to happen once per page, not once
        # per card (issue #217).
        self._favorites_cache = (None, frozenset())

    def get_playlist_path(self, console):
        system_id = resolve_system_id(console)
        return self.config_manager.get_playlists_dir() / f"{system_id}.list"

    def get_favorites_playlist_path(self):
        return self.config_manager.get_playlists_dir() / "FAVORITES.list"

    def playlist_exists(self, console):
        return self.get_playlist_path(console).exists()

    def ensure_playlist(self, console):
        if self.playlist_exists(console):
            return False
        self.scan_and_rebuild_playlist(console)
        return True

    def load_playlist(self, console):
        system_id = resolve_system_id(console)
        playlist_path = self.get_playlist_path(console)
        if not playlist_path.exists():
            logger.info("playlist load skipped: console=%s path=%s reason=missing_file", system_id, playlist_path)
            return []

        entries = []
        logger.info("playlist load started: console=%s path=%s", system_id, playlist_path)
        extensions = get_supported_extensions(system_id)
        with open(playlist_path, "r", encoding="utf-8") as f:
            for line in f:
                path_str = line.strip()
                if not path_str:
                    continue
                path = Path(path_str)
                if not path.exists():
                    continue
                display_name = self._playlist_entry_name(path, system_id, extensions)
                if display_name is None:
                    continue
                entries.append(self._rom_entry(path, system_id, name=display_name))

        sorted_entries = sorted(entries, key=lambda x: x["name"])
        logger.info("playlist load finished: console=%s total=%d", system_id, len(sorted_entries))
        return sorted_entries

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
            display_name = self._playlist_entry_name(
                path, console, get_supported_extensions(console)
            )
            if display_name is None:
                continue
            entries.append(self._rom_entry(path, console, name=display_name))
        return sorted(entries, key=lambda x: x["name"].lower())

    def load_favorites_playlist(self):
        playlist_path = self.get_favorites_playlist_path()
        if not playlist_path.exists():
            return []
        with open(playlist_path, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f]
        return self.entries_for_paths(lines)

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
        playlist_path = self.get_favorites_playlist_path()
        try:
            stat = playlist_path.stat()
        except OSError:
            self._favorites_cache = (None, frozenset())
            return self._favorites_cache[1]
        stamp = (stat.st_mtime_ns, stat.st_size)
        cached_stamp, cached = self._favorites_cache
        if cached_stamp == stamp:
            return cached
        with open(playlist_path, "r", encoding="utf-8") as f:
            paths = frozenset(
                str(Path(line.strip())) for line in f if line.strip()
            )
        self._favorites_cache = (stamp, paths)
        return paths

    def _drop_favorites_cache(self):
        """Forget the parse after writing the file.

        The (mtime, size) key would catch it on its own, but a coarse-grained
        filesystem clock and a rewrite of the same length could land inside
        one tick, and our own writes are the one case we can be exact about.
        """
        self._favorites_cache = (None, frozenset())

    def list_favorite_paths(self):
        """A mutable copy of the favorite paths."""
        return set(self._favorite_paths())

    def is_favorite(self, rom_path):
        # No copy: this is the per-card call.
        return str(Path(rom_path)) in self._favorite_paths()

    def toggle_favorite(self, rom):
        rom_path = str(Path(rom["path"]))
        playlist_path = self.get_favorites_playlist_path()
        playlist_path.parent.mkdir(parents=True, exist_ok=True)
        current = self.list_favorite_paths()
        is_now_favorite = rom_path not in current
        if is_now_favorite:
            current.add(rom_path)
        else:
            current.discard(rom_path)

        with open(playlist_path, "w", encoding="utf-8") as f:
            for path in sorted(current):
                f.write(f"{path}\n")
        self._drop_favorites_cache()
        return is_now_favorite

    def remove_missing_favorites(self):
        playlist_path = self.get_favorites_playlist_path()
        if not playlist_path.exists():
            return 0
        with open(playlist_path, "r", encoding="utf-8") as f:
            original = [line.strip() for line in f if line.strip()]
        valid = [path for path in original if Path(path).exists()]
        removed = len(original) - len(valid)
        if removed > 0:
            with open(playlist_path, "w", encoding="utf-8") as f:
                for path in sorted(set(valid)):
                    f.write(f"{path}\n")
            self._drop_favorites_cache()
        return removed

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
        for playlist_path in (
            self.get_playlist_path(console),
            self.get_favorites_playlist_path(),
        ):
            if not playlist_path.exists():
                continue
            with open(playlist_path, "r", encoding="utf-8") as f:
                lines = [line.strip() for line in f if line.strip()]
            if old_line not in lines:
                continue
            updated = []
            for line in lines:
                if line != old_line:
                    updated.append(line)
                elif new_line:
                    updated.append(new_line)
            with open(playlist_path, "w", encoding="utf-8") as f:
                for line in updated:
                    f.write(f"{line}\n")
            self._drop_favorites_cache()
            changed += 1
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
        roms = self.scanner.scan_console(system_id)
        playlist_path = self.get_playlist_path(system_id)
        playlist_path.parent.mkdir(parents=True, exist_ok=True)

        with open(playlist_path, "w", encoding="utf-8") as f:
            for rom in roms:
                logger.info(
                    "playlist add rom: console=%s rom=%s path=%s playlist=%s",
                    system_id,
                    rom["name"],
                    rom["path"],
                    playlist_path,
                )
                f.write(f"{rom['path']}\n")

        logger.info("playlist rebuild finished: console=%s total=%d path=%s", system_id, len(roms), playlist_path)
        return roms

    def scan_and_rebuild_all_playlists(self, consoles=None, on_progress=None):
        selected_consoles = list(consoles or SYSTEM_IDS)
        summary = {
            "consoles": {},
            "total_consoles": len(selected_consoles),
            "total_roms": 0,
        }
        for index, console in enumerate(selected_consoles, start=1):
            roms = self.scan_and_rebuild_playlist(console)
            system_id = resolve_system_id(console)
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
        return summary

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
        roms_base = self.config_manager.get_roms_path()
        try:
            relative = path.resolve().relative_to(roms_base.resolve())
        except Exception:
            return None
        if len(relative.parts) < 2:
            return None
        console = resolve_system_id(relative.parts[0])
        return console if console in SYSTEM_IDS else None
