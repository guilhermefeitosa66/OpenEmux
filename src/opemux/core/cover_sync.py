import logging
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from threading import Thread

from opemux.core.scraper import find_local_cover

logger = logging.getLogger(__name__)

LIBRETRO_SYSTEM_MAP = {
    "nes": "Nintendo - Nintendo Entertainment System",
    "snes": "Nintendo - Super Nintendo Entertainment System",
    "gba": "Nintendo - Game Boy Advance",
}


def _remote_cover_candidates(console, rom_name):
    system = LIBRETRO_SYSTEM_MAP.get(console)
    if not system:
        return []

    names = [
        rom_name,
        rom_name.replace("_", " "),
        rom_name.replace(" ", "_"),
    ]
    # Keep insertion order while removing duplicates.
    deduped = list(dict.fromkeys(names))
    base = (
        "https://raw.githubusercontent.com/libretro-thumbnails/"
        f"{urllib.parse.quote(system, safe='')}/master/Named_Boxarts/"
    )
    return [base + urllib.parse.quote(candidate + ".png", safe="") for candidate in deduped]


def _download_cover(url, dest):
    try:
        with urllib.request.urlopen(url, timeout=12) as resp:
            data = resp.read()
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return True
    except urllib.error.HTTPError:
        return False
    except Exception as exc:
        logger.debug("Cover sync failed for %s: %s", url, exc)
        return False


def sync_covers_async(library_by_console, covers_dir, scope, selected_console, on_done):
    def _worker():
        covers_dir_path = Path(covers_dir)
        consoles = (
            [selected_console]
            if scope == "console" and selected_console in library_by_console
            else list(library_by_console.keys())
        )

        total = 0
        downloaded = 0
        skipped = 0
        errors = 0

        for console in consoles:
            roms = library_by_console.get(console, [])
            for rom in roms:
                total += 1
                name = rom["name"]

                if find_local_cover(covers_dir_path, console, name):
                    skipped += 1
                    continue

                target = covers_dir_path / console / f"{name}.png"
                found = False
                for url in _remote_cover_candidates(console, name):
                    if _download_cover(url, target):
                        downloaded += 1
                        found = True
                        break

                if not found:
                    errors += 1

        if on_done:
            on_done(
                {
                    "scope": scope,
                    "selected_console": selected_console,
                    "total": total,
                    "downloaded": downloaded,
                    "skipped": skipped,
                    "errors": errors,
                }
            )

    Thread(target=_worker, daemon=True).start()
