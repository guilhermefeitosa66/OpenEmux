"""
Local artwork lookup utilities used by the ROM grid.

Two kinds of artwork are supported per ROM:
- COVER_ART: the box art, shown on the card when no cartridge frame is drawn.
- LABEL_ART: the cartridge label sticker, shown inside the cartridge frame.

Remote download is handled by openemux.core.cover_sync.
"""

import os
import threading
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


#: One listing per artwork directory, keyed by ``(roms_dir, console, kind)``
#: and stamped with the directory's mtime: ``{stem: path}`` (issue 907).
_ART_INDEX = {}
_ART_INDEX_LOCK = threading.Lock()
_EXT_RANK = {ext: rank for rank, ext in enumerate(SUPPORTED_COVER_EXTS)}


def local_art_index(roms_dir: Path, console: str, kind: str = COVER_ART) -> dict:
    """Every image in a console's ``kind`` directory, as ``{stem: path}``.

    Built with one ``scandir`` and kept until the directory's mtime moves --
    adding, removing or renaming a file moves it, and the writers in this
    module drop the listing themselves for the case where the change lands
    inside one filesystem clock tick. Before this, every card bind probed up
    to eight candidate names with ``exists()`` on the decode pool: a 3000-game
    library was 24,000 syscalls per page build, each one a round trip on a
    network home (issue 907).

    When several extensions exist for one stem, the first in
    :data:`SUPPORTED_COVER_EXTS` wins, as the candidate order always did.
    """
    directory = Path(roms_dir) / console / kind
    key = (str(roms_dir), console, kind)
    try:
        stamp = directory.stat().st_mtime_ns
    except OSError:
        with _ART_INDEX_LOCK:
            _ART_INDEX.pop(key, None)
        return {}
    with _ART_INDEX_LOCK:
        cached = _ART_INDEX.get(key)
        if cached is not None and cached[0] == stamp:
            return cached[1]
    index = {}
    try:
        with os.scandir(directory) as entries:
            for entry in entries:
                stem, dot, ext = entry.name.rpartition(".")
                rank = _EXT_RANK.get(ext) if dot else None
                if rank is None or not stem:
                    continue
                try:
                    if not entry.is_file():
                        continue
                except OSError:  # pragma: no cover - a vanished entry mid-listing
                    continue
                previous = index.get(stem)
                if previous is None or rank < _EXT_RANK[previous.suffix[1:]]:
                    index[stem] = Path(entry.path)
    except OSError:
        return {}
    with _ART_INDEX_LOCK:
        _ART_INDEX[key] = (stamp, index)
    return index


def forget_art_index(roms_dir: Path = None, console: str = None, kind: str = None):
    """Drop the cached listings, all of them or one directory's.

    For the writers that change a directory and look it up again right away:
    two writes inside one clock tick leave the directory's mtime where it
    was, so the stamp alone would keep serving the old listing.
    """
    with _ART_INDEX_LOCK:
        if roms_dir is None:
            _ART_INDEX.clear()
            return
        _ART_INDEX.pop((str(roms_dir), console, kind), None)


def find_local_art(
    roms_dir: Path, console: str, rom_name: str, kind: str = COVER_ART
) -> Path | None:
    return local_art_index(roms_dir, console, kind).get(rom_name)


def is_label_art(path) -> bool:
    """Whether ``path`` is a cartridge label rather than any other artwork.

    ``fetch_cover`` hands back one path from whichever kind it found first,
    and the cartridge renderer must not take a box cover for a label (issue
    #457). The kind is the directory the art lives in, per
    :func:`get_art_path_candidates`.
    """
    return bool(path) and Path(path).parent.name == LABEL_ART


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
    forget_art_index(roms_dir, console, kind)
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
    forget_art_index(roms_dir, console, kind)
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
        forget_art_index(roms_dir, console, kind)
    return renamed


def get_cover_path_candidates(roms_dir: Path, console: str, rom_name: str) -> list[Path]:
    return get_art_path_candidates(roms_dir, console, rom_name, COVER_ART)


def find_local_cover(roms_dir: Path, console: str, rom_name: str) -> Path | None:
    return find_local_art(roms_dir, console, rom_name, COVER_ART)


def remove_local_covers(roms_dir: Path, console: str, rom_name: str) -> int:
    return remove_local_art(roms_dir, console, rom_name, COVER_ART)


def save_local_cover(roms_dir: Path, console: str, rom_name: str, source_path: str | Path) -> Path:
    return save_local_art(roms_dir, console, rom_name, source_path, COVER_ART)


def resolve_local_art(rom: dict, roms_dir: str | Path, kinds=(COVER_ART,)) -> str | None:
    """The first artwork of ``kinds`` this ROM has on disk, or None.

    ``kinds`` is tried in order, so a card can prefer the cartridge label and
    fall back to the box art when no label was configured.
    """
    for kind in kinds:
        found = find_local_art(Path(roms_dir), rom["console"], rom["name"], kind)
        if found:
            return str(found)
    return None


def fetch_cover(rom: dict, roms_dir: str | Path, on_done_callback=None, kinds=(COVER_ART,)) -> None:
    """
    Resolve local artwork off the main thread to avoid UI blocking.

    Runs on the shared, bounded decode pool rather than a thread of its own:
    a 500-ROM console used to spawn 500 OS threads here (issue #128). The
    ``on_done_callback(rom, path_or_None)`` contract is unchanged, and it is
    still invoked on a worker -- which is now where the decode belongs too.
    """

    def _worker():
        found = resolve_local_art(rom, roms_dir, kinds)
        if on_done_callback:
            on_done_callback(rom, found)

    cover_cache.submit(_worker)
