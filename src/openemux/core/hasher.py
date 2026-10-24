import hashlib
import logging
import zipfile
import zlib
from collections import namedtuple
from functools import lru_cache
from pathlib import Path

from openemux.core import archives

logger = logging.getLogger(__name__)

#: What identifies a ROM by content: its file name (extension included), size,
#: CRC32 and MD5. Any field may be None when it could not be read.
RomIdentity = namedtuple("RomIdentity", "file_name size crc32 md5")

#: Above this uncompressed size an archived ROM is identified by CRC and size
#: only: those come from the zip's directory for free, while the MD5 needs the
#: whole entry decompressed, which for a disc-sized file would stall a worker.
ARCHIVE_MD5_CAP_BYTES = 64 * 1024 * 1024


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


def rom_identity(rom_path, extensions=()):
    """The :data:`RomIdentity` of a ROM, as a content lookup should see it.

    For a ``.zip`` it describes the ROM *inside* -- the entry the scanner
    names the game after -- because the archive's own CRC, MD5 and size match
    no database: a zipped Game Boy library never found a cartridge label on
    ScreenScraper (issue #506). An archive that holds no matching entry, or
    cannot be read, is described as the plain file it is.

    Never raises: what cannot be read comes back as None.
    """
    path = Path(rom_path)
    if archives.is_archive(path):
        identity = _archive_identity(path, extensions)
        if identity is not None:
            return identity
    try:
        crc, md5 = rom_digests(path)
    except OSError as exc:
        logger.debug("hasher digests unavailable: error=%s", exc)
        crc = md5 = None
    try:
        size = path.stat().st_size
    except OSError:
        size = None
    return RomIdentity(path.name, size, crc, md5)


def _archive_identity(path, extensions):
    try:
        stat = path.stat()
    except OSError:
        return None
    return _cached_archive_identity(
        str(path), (stat.st_mtime_ns, stat.st_size), tuple(sorted(extensions))
    )


@lru_cache(maxsize=1024)
def _cached_archive_identity(path, _stamp, extensions):
    info = archives.archive_rom_entry(path, extensions)
    if info is None:
        return None
    md5 = None
    if info.file_size <= ARCHIVE_MD5_CAP_BYTES:
        md5 = _entry_md5(path, info)
    return RomIdentity(
        Path(info.filename).name,
        info.file_size,
        format(info.CRC & 0xFFFFFFFF, "08X"),
        md5,
    )


def _entry_md5(path, info, chunk_size=65536):
    digest = hashlib.md5()  # nosec B324 - content fingerprint, not security
    try:
        with zipfile.ZipFile(path) as archive, archive.open(info) as handle:
            while chunk := handle.read(chunk_size):
                digest.update(chunk)
    except Exception as exc:  # noqa: BLE001 - CRC and size still identify it
        logger.debug("hasher archive md5 unavailable: path=%s error=%s", path, exc)
        return None
    return digest.hexdigest().upper()


def forget_rom_digests():
    """Drop the memo. For tests, and for anything editing ROMs in place."""
    _cached_digests.cache_clear()
    _cached_archive_identity.cache_clear()
