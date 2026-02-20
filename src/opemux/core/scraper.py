"""
Local cover lookup utilities used by the ROM grid.

Remote download is handled by opemux.core.cover_sync.
"""

from pathlib import Path
import shutil
from threading import Thread

SUPPORTED_COVER_EXTS = ("png", "jpg", "jpeg", "webp")


def get_cover_path_candidates(roms_dir: Path, console: str, rom_name: str) -> list[Path]:
    return [roms_dir / console / "covers" / f"{rom_name}.{ext}" for ext in SUPPORTED_COVER_EXTS]


def find_local_cover(roms_dir: Path, console: str, rom_name: str) -> Path | None:
    for candidate in get_cover_path_candidates(roms_dir, console, rom_name):
        if candidate.exists():
            return candidate
    return None


def remove_local_covers(roms_dir: Path, console: str, rom_name: str) -> int:
    removed = 0
    for candidate in get_cover_path_candidates(roms_dir, console, rom_name):
        if not candidate.exists():
            continue
        try:
            candidate.unlink()
            removed += 1
        except Exception:
            continue
    return removed


def save_local_cover(roms_dir: Path, console: str, rom_name: str, source_path: str | Path) -> Path:
    source = Path(source_path)
    ext = source.suffix.lower().lstrip(".")
    if ext not in SUPPORTED_COVER_EXTS:
        raise ValueError(f"Unsupported cover extension: {source.suffix}")

    remove_local_covers(roms_dir, console, rom_name)
    target = Path(roms_dir) / console / "covers" / f"{rom_name}.{ext}"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return target


def fetch_cover(rom: dict, roms_dir: str | Path, on_done_callback=None) -> None:
    """
    Resolve local cover art in a background thread to avoid UI blocking.
    """

    def _worker():
        local_cover = find_local_cover(Path(roms_dir), rom["console"], rom["name"])
        if on_done_callback:
            on_done_callback(rom, str(local_cover) if local_cover else None)

    Thread(target=_worker, daemon=True).start()
