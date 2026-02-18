"""
Cover art scraper using the ScreenScraper API.

Scraping runs asynchronously so the UI never blocks.
Images are stored in <roms>/covers/<console>/<rom_name>.<ext>
"""

import logging
import urllib.request
import urllib.parse
import json
from pathlib import Path
from threading import Thread

logger = logging.getLogger(__name__)
SUPPORTED_COVER_EXTS = ("png", "jpg", "webp")

# ScreenScraper anonymous endpoint (no API key needed, rate-limited)
SS_BASE = "https://www.screenscraper.fr/api2/jeuInfos.php"
SS_DEV_ID = "opemux"
SS_DEV_PASSWORD = "opemux"

# Map our console names to ScreenScraper system IDs
CONSOLE_SYSTEM_IDS = {
    "nes": 3,
    "snes": 4,
    "gba": 12,
}


def get_cover_path_candidates(covers_dir: Path, console: str, rom_name: str) -> list[Path]:
    return [covers_dir / console / f"{rom_name}.{ext}" for ext in SUPPORTED_COVER_EXTS]


def find_local_cover(covers_dir: Path, console: str, rom_name: str) -> Path | None:
    for candidate in get_cover_path_candidates(covers_dir, console, rom_name):
        if candidate.exists():
            return candidate
    return None


def _fetch_cover_url(rom_name: str, crc32: str, console: str) -> str | None:
    """
    Query ScreenScraper for cover art URL.
    Returns the image URL string, or None if not found.
    """
    system_id = CONSOLE_SYSTEM_IDS.get(console)
    if not system_id:
        return None

    params = urllib.parse.urlencode({
        "devid": SS_DEV_ID,
        "devpassword": SS_DEV_PASSWORD,
        "softname": "opemux",
        "output": "json",
        "systemeid": system_id,
        "romnom": urllib.parse.quote(rom_name),
        "crc": crc32,
    })
    url = f"{SS_BASE}?{params}"

    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        logger.debug(f"ScreenScraper request failed for {rom_name}: {e}")
        return None

    try:
        medias = data["response"]["jeu"]["medias"]
        # Prefer box-2D (front cover), fall back to screenshot
        for media_type in ("box-2D", "box-2D-side", "ss"):
            for media in medias:
                if media.get("type") == media_type:
                    return media.get("url")
    except (KeyError, TypeError):
        pass

    return None


def _pick_extension_from_url(url: str) -> str:
    suffix = Path(urllib.parse.urlparse(url).path).suffix.lower().lstrip(".")
    if suffix == "jpeg":
        return "jpg"
    if suffix in SUPPORTED_COVER_EXTS:
        return suffix
    return "jpg"


def _download_image(url: str, covers_dir: Path, console: str, rom_name: str) -> Path | None:
    """Download an image and return its destination path on success."""
    try:
        ext = _pick_extension_from_url(url)
        dest = covers_dir / console / f"{rom_name}.{ext}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(url, timeout=15) as resp:
            dest.write_bytes(resp.read())
        return dest
    except Exception as e:
        logger.debug(f"Failed to download {url}: {e}")
        return None


def fetch_cover(rom: dict, covers_dir: str | Path, on_done_callback=None) -> None:
    """
    Fetch cover art for a ROM in a background thread.
    
    rom: dict with keys 'name', 'path', 'console'
    on_done_callback: called with (rom, cover_path) when done (may be None if failed)
    """
    def _worker():
        from opemux.core.hasher import compute_crc32

        name = rom["name"]
        console = rom["console"]
        target_dir = Path(covers_dir)
        local_cover = find_local_cover(target_dir, console, name)

        # Already available in local covers folder.
        if local_cover and local_cover.exists():
            if on_done_callback:
                on_done_callback(rom, str(local_cover))
            return

        # Compute hash
        try:
            crc32 = compute_crc32(rom["path"])
        except Exception as e:
            logger.debug(f"Failed to hash {name}: {e}")
            if on_done_callback:
                on_done_callback(rom, None)
            return

        # Fetch URL from ScreenScraper
        cover_url = _fetch_cover_url(name, crc32, console)
        if not cover_url:
            logger.debug(f"No cover found for {name}")
            if on_done_callback:
                on_done_callback(rom, None)
            return

        # Download
        saved_path = _download_image(cover_url, target_dir, console, name)
        if on_done_callback:
            on_done_callback(rom, str(saved_path) if saved_path else None)

    thread = Thread(target=_worker, daemon=True)
    thread.start()
