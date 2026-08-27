"""
Local artwork lookup utilities used by the ROM grid.

Two kinds of artwork are supported per ROM:
- COVER_ART: the box art, shown on the card when no cartridge frame is drawn.
- LABEL_ART: the cartridge label sticker, shown inside the cartridge frame.

Remote download is handled by openemux.core.cover_sync.
"""

from pathlib import Path
import shutil

from openemux.core import cover_cache

SUPPORTED_COVER_EXTS = ("png", "jpg", "jpeg", "webp")

#: What an image of each supported format starts with. Sniffed rather than
#: trusted from the Content-Type or the URL, because the bodies that caused
#: issue #213 arrive with a 200 and a plausible header and are not images at
#: all: ScreenScraper answers some quota failures with a plain-text message,
#: and a captive portal answers everything with HTML.
_IMAGE_SIGNATURES = (
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"\xff\xd8\xff", "jpg"),
    (b"GIF87a", "gif"),
    (b"GIF89a", "gif"),
)

#: The smallest thing that could plausibly be a cover. Below this it is a
#: truncated download or an error page, whatever the bytes say.
MIN_IMAGE_BYTES = 64


def image_format(data):
    """The format ``data`` really is, or None when it is not an image.

    Returns one of the names in :data:`SUPPORTED_COVER_EXTS` (plus ``gif``,
    which GdkPixbuf renders); an image we recognise but do not want to store
    is still better identified than mislabelled.
    """
    if not data or len(data) < MIN_IMAGE_BYTES:
        return None
    for signature, name in _IMAGE_SIGNATURES:
        if data.startswith(signature):
            return name
    # RIFF....WEBP -- the size field sits between the two markers.
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def is_image(data):
    """Whether these bytes are an image we can actually render."""
    return image_format(data) is not None


def is_image_file(path):
    """Whether the file at ``path`` is an image, from its first bytes.

    Reads a header, not the file: this is asked once per ROM on a fill-in
    sync, and the answer only needs the magic number. A file we cannot read
    is not called junk -- an unreadable file may just be on a drive that is
    not mounted, and deleting art on that basis would be its own bug.
    """
    try:
        with open(path, "rb") as handle:
            header = handle.read(_HEADER_READ_BYTES)
    except OSError:
        return True
    return is_image(header)


#: Enough for every signature plus the size check.
_HEADER_READ_BYTES = 512

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


def remove_local_art(
    roms_dir: Path, console: str, rom_name: str, kind: str = COVER_ART, keep=None
) -> int:
    """Delete this ROM's art in ``kind``, optionally sparing one file.

    ``keep`` is how ``save_local_art`` clears the other extensions *after*
    writing the new file rather than before (issue #234).
    """
    keep = Path(keep) if keep is not None else None
    removed = 0
    for candidate in get_art_path_candidates(roms_dir, console, rom_name, kind):
        if candidate == keep or not candidate.exists():
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

    target = Path(roms_dir) / console / kind / f"{rom_name}.{ext}"
    target.parent.mkdir(parents=True, exist_ok=True)
    # Copy first, clean up after -- the order cover_sync already uses. Removing
    # the old art up front meant a copy that failed (full disk, source gone,
    # permissions) left the ROM with no art at all, having had a perfectly
    # good cover a moment earlier (issue #234).
    shutil.copy2(source, target)
    remove_local_art(roms_dir, console, rom_name, kind, keep=target)
    return target


def rename_local_art(roms_dir: Path, console: str, old_name: str, new_name: str) -> int:
    """Carry a ROM's artwork over to its new name, for every art kind.

    Artwork is keyed on the display name, so a renamed ROM would otherwise
    stop finding its own cover.
    """
    renamed = 0
    for kind in (COVER_ART, LABEL_ART):
        for candidate in get_art_path_candidates(roms_dir, console, old_name, kind):
            if not candidate.exists():
                continue
            target = candidate.with_name(f"{new_name}{candidate.suffix}")
            try:
                candidate.replace(target)
                renamed += 1
            except OSError:
                continue
    return renamed


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
    Resolve local artwork off the main thread to avoid UI blocking.

    `kinds` is tried in order, so a card can prefer the cartridge label and fall
    back to the box art when no label was configured.

    Runs on the shared, bounded decode pool rather than a thread of its own:
    a 500-ROM console used to spawn 500 OS threads here (issue #128). The
    ``on_done_callback(rom, path_or_None)`` contract is unchanged, and it is
    still invoked on a worker -- which is now where the decode belongs too.
    """

    def _worker():
        found = None
        for kind in kinds:
            found = find_local_art(Path(roms_dir), rom["console"], rom["name"], kind)
            if found:
                break
        if on_done_callback:
            on_done_callback(rom, str(found) if found else None)

    cover_cache.submit(_worker)
