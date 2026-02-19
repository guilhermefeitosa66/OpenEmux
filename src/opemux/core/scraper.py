"""
Local cover lookup utilities used by the ROM grid.

Remote download is handled by opemux.core.cover_sync.
"""

from pathlib import Path
from threading import Thread

SUPPORTED_COVER_EXTS = ("png", "jpg", "webp")


def get_cover_path_candidates(covers_dir: Path, console: str, rom_name: str) -> list[Path]:
    return [covers_dir / console / f"{rom_name}.{ext}" for ext in SUPPORTED_COVER_EXTS]


def find_local_cover(covers_dir: Path, console: str, rom_name: str) -> Path | None:
    for candidate in get_cover_path_candidates(covers_dir, console, rom_name):
        if candidate.exists():
            return candidate
    return None


def fetch_cover(rom: dict, covers_dir: str | Path, on_done_callback=None) -> None:
    """
    Resolve local cover art in a background thread to avoid UI blocking.
    """

    def _worker():
        local_cover = find_local_cover(Path(covers_dir), rom["console"], rom["name"])
        if on_done_callback:
            on_done_callback(rom, str(local_cover) if local_cover else None)

    Thread(target=_worker, daemon=True).start()
