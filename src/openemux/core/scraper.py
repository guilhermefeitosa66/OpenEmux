"""
Local artwork lookup utilities used by the ROM grid.

Two kinds of artwork are supported per ROM:
- COVER_ART: the box art, shown on the card when no cartridge frame is drawn.
- LABEL_ART: the cartridge label sticker, shown inside the cartridge frame.

Remote download is handled by openemux.core.cover_sync.
"""

from pathlib import Path
import shutil
from threading import Thread

SUPPORTED_COVER_EXTS = ("png", "jpg", "jpeg", "webp")

COVER_ART = "covers"
LABEL_ART = "labels"


def get_art_path_candidates(
    roms_dir: Path, console: str, rom_name: str, kind: str = COVER_ART
) -> list[Path]:
    return [Path(roms_dir) / console / kind / f"{rom_name}.{ext}" for ext in SUPPORTED_COVER_EXTS]


def find_local_art(
    roms_dir: Path, console: str, rom_name: str, kind: str = COVER_ART
) -> Path | None:
    for candidate in get_art_path_candidates(roms_dir, console, rom_name, kind):
        if candidate.exists():
            return candidate
    return None


def remove_local_art(roms_dir: Path, console: str, rom_name: str, kind: str = COVER_ART) -> int:
    removed = 0
    for candidate in get_art_path_candidates(roms_dir, console, rom_name, kind):
        if not candidate.exists():
            continue
        try:
            candidate.unlink()
            removed += 1
        except Exception:
            continue
    return removed


def save_local_art(
    roms_dir: Path, console: str, rom_name: str, source_path: str | Path, kind: str = COVER_ART
) -> Path:
    source = Path(source_path)
    ext = source.suffix.lower().lstrip(".")
    if ext not in SUPPORTED_COVER_EXTS:
        raise ValueError(f"Unsupported cover extension: {source.suffix}")

    remove_local_art(roms_dir, console, rom_name, kind)
    target = Path(roms_dir) / console / kind / f"{rom_name}.{ext}"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return target


def get_cover_path_candidates(roms_dir: Path, console: str, rom_name: str) -> list[Path]:
    return get_art_path_candidates(roms_dir, console, rom_name, COVER_ART)


def find_local_cover(roms_dir: Path, console: str, rom_name: str) -> Path | None:
    return find_local_art(roms_dir, console, rom_name, COVER_ART)


def remove_local_covers(roms_dir: Path, console: str, rom_name: str) -> int:
    return remove_local_art(roms_dir, console, rom_name, COVER_ART)


def save_local_cover(roms_dir: Path, console: str, rom_name: str, source_path: str | Path) -> Path:
    return save_local_art(roms_dir, console, rom_name, source_path, COVER_ART)


def fetch_cover(rom: dict, roms_dir: str | Path, on_done_callback=None, kinds=(COVER_ART,)) -> None:
    """
    Resolve local artwork in a background thread to avoid UI blocking.

    `kinds` is tried in order, so a card can prefer the cartridge label and fall
    back to the box art when no label was configured.
    """

    def _worker():
        found = None
        for kind in kinds:
            found = find_local_art(Path(roms_dir), rom["console"], rom["name"], kind)
            if found:
                break
        if on_done_callback:
            on_done_callback(rom, str(found) if found else None)

    Thread(target=_worker, daemon=True).start()
