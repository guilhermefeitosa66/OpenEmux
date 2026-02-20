import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from threading import Thread

from opemux.core.scraper import find_local_cover
from opemux.core.systems import get_thumbnail_system, resolve_system_id

logger = logging.getLogger(__name__)

def _build_cover_url(system, game_name):
    return (
        "https://thumbnails.libretro.com/"
        f"{urllib.parse.quote(system, safe='')}/Named_Boxarts/"
        f"{urllib.parse.quote(game_name + '.png', safe='')}"
    )


def _normalize_rom_name(rom_name):
    normalized = rom_name.strip()
    normalized = re.sub(r"\.(nes|sfc|smc|gba)$", "", normalized, flags=re.IGNORECASE)
    # Remove trailing tags repeatedly, e.g. "(Rev 1) [!]"
    while True:
        cleaned = re.sub(r"\s*[\(\[][^\)\]]*[\)\]]\s*$", "", normalized)
        if cleaned == normalized:
            break
        normalized = cleaned.strip()
    normalized = normalized.replace("_", " ").replace(".", " ")
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if normalized.endswith(", The"):
        normalized = f"The {normalized[:-5].strip()}"
    return normalized


def _the_variant(name):
    if name.startswith("The "):
        return f"{name[4:]}, The"
    if name.endswith(", The"):
        return f"The {name[:-5].strip()}"
    return None


def _candidate_names(rom_name, matching_mode, region_priority, name_cleanup):
    base_names = []

    def _append(value):
        value = value.strip()
        if value and value not in base_names:
            base_names.append(value)

    _append(rom_name)
    _append(rom_name.replace("_", " "))
    if name_cleanup:
        _append(_normalize_rom_name(rom_name))

    expanded = []
    for name in base_names:
        if name not in expanded:
            expanded.append(name)
        alt = _the_variant(name)
        if alt and alt not in expanded:
            expanded.append(alt)

    if matching_mode != "normalized_region_priority":
        return expanded

    candidates = []
    for name in expanded:
        if name not in candidates:
            candidates.append(name)
        for region in region_priority:
            candidate = f"{name} ({region})"
            if candidate not in candidates:
                candidates.append(candidate)
        multi_lang = f"{name} (En,Fr,De,Es,It)"
        if multi_lang not in candidates:
            candidates.append(multi_lang)

    return candidates


def _remote_cover_candidates(console, rom_name, sync_settings):
    system_id = resolve_system_id(console)
    system = get_thumbnail_system(system_id)
    if not system:
        return []

    names = _candidate_names(
        rom_name=rom_name,
        matching_mode=sync_settings.get("matching_mode", "normalized_region_priority"),
        region_priority=sync_settings.get("region_priority", ["USA", "World", "Europe", "Japan"]),
        name_cleanup=bool(sync_settings.get("name_cleanup", True)),
    )
    return [_build_cover_url(system, candidate) for candidate in names]


def _download_cover(url, dest):
    try:
        logger.debug("cover_sync trying candidate: url=%s target=%s", url, dest)
        with urllib.request.urlopen(url, timeout=12) as resp:
            data = resp.read()
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        logger.info("cover_sync downloaded: url=%s target=%s bytes=%d", url, dest, len(data))
        return True
    except urllib.error.HTTPError:
        logger.info("cover_sync not_found: url=%s", url)
        return False
    except Exception as exc:
        logger.warning("cover_sync error: url=%s error=%s", url, exc)
        return False


def _sync_covers(library_by_console, covers_dir, scope, selected_console, sync_settings=None, on_progress=None):
    sync_settings = sync_settings or {}
    roms_dir_path = Path(covers_dir)
    consoles = (
        [selected_console]
        if scope == "console" and selected_console in library_by_console
        else list(library_by_console.keys())
    )
    logger.info("cover_sync started: scope=%s selected_console=%s consoles=%s", scope, selected_console, consoles)

    total = 0
    downloaded = 0
    skipped = 0
    errors = 0
    total_targets = sum(len(library_by_console.get(console, [])) for console in consoles)

    for console in consoles:
        roms = library_by_console.get(console, [])
        for rom in roms:
            total += 1
            name = rom["name"]

            if find_local_cover(roms_dir_path, console, name):
                logger.info("cover_sync skip existing: console=%s rom=%s", console, name)
                skipped += 1
                if on_progress:
                    on_progress(
                        {
                            "console": console,
                            "rom_name": name,
                            "processed": total,
                            "total": total_targets,
                            "downloaded": downloaded,
                            "skipped": skipped,
                            "errors": errors,
                        }
                    )
                continue

            target = roms_dir_path / console / "covers" / f"{name}.png"
            urls = _remote_cover_candidates(console, name, sync_settings)
            logger.info("cover_sync candidate_set: console=%s rom=%s candidates=%d", console, name, len(urls))
            found = False
            for url in urls:
                if _download_cover(url, target):
                    downloaded += 1
                    found = True
                    logger.info("cover_sync selected candidate: console=%s rom=%s url=%s", console, name, url)
                    break

            if not found:
                logger.info("cover_sync missed: console=%s rom=%s tried=%d", console, name, len(urls))
                errors += 1
            if on_progress:
                on_progress(
                    {
                        "console": console,
                        "rom_name": name,
                        "processed": total,
                        "total": total_targets,
                        "downloaded": downloaded,
                        "skipped": skipped,
                        "errors": errors,
                    }
                )

    summary = {
        "scope": scope,
        "selected_console": selected_console,
        "total": total,
        "downloaded": downloaded,
        "skipped": skipped,
        "errors": errors,
    }
    logger.info(
        "cover_sync finished: scope=%s selected_console=%s total=%d downloaded=%d skipped=%d errors=%d",
        scope,
        selected_console,
        total,
        downloaded,
        skipped,
        errors,
    )
    return summary


def sync_covers_async(
    library_by_console,
    covers_dir,
    scope,
    selected_console,
    on_done,
    sync_settings=None,
    on_progress=None,
):
    def _worker():
        summary = _sync_covers(
            library_by_console=library_by_console,
            covers_dir=covers_dir,
            scope=scope,
            selected_console=selected_console,
            sync_settings=sync_settings,
            on_progress=on_progress,
        )
        if on_done:
            on_done(summary)

    Thread(target=_worker, daemon=True).start()
