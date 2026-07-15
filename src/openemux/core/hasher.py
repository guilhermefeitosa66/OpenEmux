import zlib
from pathlib import Path


def compute_crc32(rom_path: str, chunk_size: int = 65536) -> str:
    """Compute CRC32 hash of a ROM file, returned as uppercase hex string."""
    crc = 0
    with open(rom_path, "rb") as f:
        while chunk := f.read(chunk_size):
            crc = zlib.crc32(chunk, crc)
    return format(crc & 0xFFFFFFFF, "08X")


def compute_rom_id(rom_path: str) -> str:
    """
    Build a stable ROM identifier combining CRC32 and file size.
    Format: <CRC32>-<size_bytes>
    """
    path = Path(rom_path)
    crc32 = compute_crc32(rom_path)
    size = path.stat().st_size
    return f"{crc32}-{size}"
