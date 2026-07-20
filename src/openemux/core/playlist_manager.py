from pathlib import Path
import logging

from openemux.core.archives import archive_rom_name, is_archive, loads_archives_natively
from openemux.core.hasher import compute_rom_id
from openemux.core.systems import SYSTEM_IDS, get_supported_extensions, resolve_system_id

logger = logging.getLogger(__name__)


class PlaylistManager:
    def __init__(self, config_manager, scanner):
        self.config_manager = config_manager
        self.scanner = scanner

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

    def load_favorites_playlist(self):
        playlist_path = self.get_favorites_playlist_path()
        if not playlist_path.exists():
            return []

        entries = []
        seen = set()
        with open(playlist_path, "r", encoding="utf-8") as f:
            for line in f:
                path_str = line.strip()
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

    def list_favorite_paths(self):
        return {entry["path"] for entry in self.load_favorites_playlist()}

    def is_favorite(self, rom_path):
        rom_path = str(Path(rom_path))
        return rom_path in self.list_favorite_paths()

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
        return removed

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
        rom_id = None
        try:
            rom_id = compute_rom_id(str(path))
        except Exception:
            rom_id = None

        return {
            "name": name or path.stem,
            "path": str(path),
            "console": console,
            "rom_id": rom_id,
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
