from pathlib import Path
import logging

from opemux.core.hasher import compute_rom_id
from opemux.core.scanner import SUPPORTED_EXTENSIONS

logger = logging.getLogger(__name__)


class PlaylistManager:
    def __init__(self, config_manager, scanner):
        self.config_manager = config_manager
        self.scanner = scanner

    def get_playlist_path(self, console):
        return self.config_manager.get_playlists_dir() / f"{console}.list"

    def playlist_exists(self, console):
        return self.get_playlist_path(console).exists()

    def ensure_playlist(self, console):
        if self.playlist_exists(console):
            return False
        self.scan_and_rebuild_playlist(console)
        return True

    def load_playlist(self, console):
        playlist_path = self.get_playlist_path(console)
        if not playlist_path.exists():
            logger.info("playlist load skipped: console=%s path=%s reason=missing_file", console, playlist_path)
            return []

        entries = []
        logger.info("playlist load started: console=%s path=%s", console, playlist_path)
        with open(playlist_path, "r", encoding="utf-8") as f:
            for line in f:
                path_str = line.strip()
                if not path_str:
                    continue
                path = Path(path_str)
                if not path.exists():
                    continue
                if path.suffix.lower() not in SUPPORTED_EXTENSIONS.get(console, []):
                    continue
                entries.append(self._rom_entry(path, console))

        sorted_entries = sorted(entries, key=lambda x: x["name"])
        logger.info("playlist load finished: console=%s total=%d", console, len(sorted_entries))
        return sorted_entries

    def scan_and_rebuild_playlist(self, console):
        logger.info("playlist rebuild started: console=%s", console)
        roms = self.scanner.scan_console(console)
        playlist_path = self.get_playlist_path(console)
        playlist_path.parent.mkdir(parents=True, exist_ok=True)

        with open(playlist_path, "w", encoding="utf-8") as f:
            for rom in roms:
                logger.info(
                    "playlist add rom: console=%s rom=%s path=%s playlist=%s",
                    console,
                    rom["name"],
                    rom["path"],
                    playlist_path,
                )
                f.write(f"{rom['path']}\n")

        logger.info("playlist rebuild finished: console=%s total=%d path=%s", console, len(roms), playlist_path)
        return roms

    def _rom_entry(self, path, console):
        rom_id = None
        try:
            rom_id = compute_rom_id(str(path))
        except Exception:
            rom_id = None

        return {
            "name": path.stem,
            "path": str(path),
            "console": console,
            "rom_id": rom_id,
        }
