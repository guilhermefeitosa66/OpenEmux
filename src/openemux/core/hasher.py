import hashlib
import zlib
from functools import lru_cache
from pathlib import Path


def compute_crc32(rom_path: str, chunk_size: int = 65536) -> str:
    """Compute CRC32 hash of a ROM file, returned as uppercase hex string."""
    return rom_digests(rom_path)[0]


def compute_md5(rom_path: str) -> str:
    """MD5 of a ROM file as an uppercase hex string."""
    return rom_digests(rom_path)[1]


def rom_digests(rom_path, chunk_size: int = 65536):
    """``(crc32, md5)`` for a ROM, read once and remembered.

    A cover-sync pass asked for a ROM's CRC in the name-index stage and then
    for its CRC *and* MD5 in the ScreenScraper stage, and did it again for the
    box-art and label passes -- up to six full reads of the same file, which
    for a PlayStation or PC-Engine CD image is minutes of pure I/O
    (issue #231). Both digests now come from one pass, memoized on the file's
    identity so every later stage is free.

    The key carries mtime and size, so a ROM that changed on disk is re-read
    rather than answered from a stale entry.
    """
    path = Path(rom_path)
    try:
        stat = path.stat()
        stamp = (stat.st_mtime_ns, stat.st_size)
    except OSError:
        # Unreadable: let the read itself raise, as it always did.
        return _digests(str(path), None, chunk_size)
    return _cached_digests(str(path), stamp, chunk_size)


@lru_cache(maxsize=1024)
def _cached_digests(path, _stamp, chunk_size):
    return _digests(path, _stamp, chunk_size)


def _digests(path, _stamp, chunk_size):
    crc = 0
    md5 = hashlib.md5()  # nosec B324 - content fingerprint, not security
    with open(path, "rb") as handle:
        while chunk := handle.read(chunk_size):
            crc = zlib.crc32(chunk, crc)
            md5.update(chunk)
    return format(crc & 0xFFFFFFFF, "08X"), md5.hexdigest().upper()


def forget_rom_digests():
    """Drop the memo. For tests, and for anything editing ROMs in place."""
    _cached_digests.cache_clear()
