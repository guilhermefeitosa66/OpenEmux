import logging
import re
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from threading import Thread

from openemux.core import screenscraper
from openemux.core.scraper import find_local_cover
from openemux.core.systems import get_thumbnail_system, resolve_system_id

logger = logging.getLogger(__name__)

COVER_SOURCE_LIBRETRO = "libretro"
COVER_SOURCE_LIBRETRO_THEN_SCREENSCRAPER = "libretro_then_screenscraper"
COVER_SOURCE_SCREENSCRAPER = "screenscraper"

# Ordered provider names per configured cover source. "libretro" is the default
# and yields exactly the historical single-provider behavior.
_SOURCE_ORDER = {
    COVER_SOURCE_LIBRETRO: ("libretro",),
    COVER_SOURCE_LIBRETRO_THEN_SCREENSCRAPER: ("libretro", "screenscraper"),
    COVER_SOURCE_SCREENSCRAPER: ("screenscraper",),
}

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


# Small connecting words that libretro's No-Intro thumbnail names keep lowercase
# (e.g. "Castlevania - Harmony of Dissonance"), while handheld ROM sets often
# title-case them ("Harmony Of Dissonance").
_CONNECTOR_WORDS = {
    "of", "the", "and", "in", "no", "de", "a", "to", "for", "vs", "or", "on", "at",
}

# libretro No-Intro thumbnails frequently use combined region tags rather than a
# single region, e.g. "Sonic The Hedgehog (USA, Europe)". Try the most common
# combos in addition to the configured single-region priority list.
_COMMON_REGION_COMBOS = ("USA, Europe", "Japan, USA", "USA, Australia", "World")


def _strip_accents(value):
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _lower_connectors(name):
    words = name.split(" ")
    result = []
    for index, word in enumerate(words):
        if index > 0 and word.lower() in _CONNECTOR_WORDS:
            result.append(word.lower())
        else:
            result.append(word)
    return " ".join(result)


def _strip_sequence_markers(name):
    # Drop anbernic-style ordering markers embedded in the title, e.g.
    # "Pokemon 2.1 - Gold Version" -> "Pokemon Gold Version".
    stripped = re.sub(r"\s*\b\d+(?:\.\d+)?\s*[-–]\s*", " ", name)
    return re.sub(r"\s+", " ", stripped).strip()


def _strip_trailing_number(name):
    # Drop a trailing bare sequence number appended by some ROM sets, e.g.
    # "Donkey Kong 1" -> "Donkey Kong", "Sonic The Hedgehog 1" -> "...Hedgehog".
    return re.sub(r"\s+\d{1,2}$", "", name).strip()


def _candidate_names(rom_name, matching_mode, region_priority, name_cleanup):
    base_names = []

    def _append(value):
        if not value:
            return
        value = value.strip()
        if value and value not in base_names:
            base_names.append(value)

    seeds = [rom_name, rom_name.replace("_", " ")]
    if name_cleanup:
        seeds.append(_normalize_rom_name(rom_name))

    for seed in seeds:
        _append(seed)
        if not name_cleanup:
            continue
        # Additional normalizations to bridge common ROM-set naming quirks toward
        # libretro's No-Intro thumbnail names. Each is added as an extra candidate
        # (tried until one URL resolves), so correct names still match first.
        for variant in (
            _lower_connectors(seed),
            _strip_sequence_markers(seed),
            _strip_trailing_number(seed),
        ):
            _append(variant)
        # De-accented forms (e.g. "Pokémon" -> "Pokemon").
        _append(_strip_accents(seed))
        _append(_strip_accents(_lower_connectors(seed)))
        _append(_strip_accents(_strip_sequence_markers(seed)))
        _append(_strip_accents(_strip_trailing_number(seed)))

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
        for region in list(region_priority) + list(_COMMON_REGION_COMBOS):
            candidate = f"{name} ({region})"
            if candidate not in candidates:
                candidates.append(candidate)
        multi_lang = f"{name} (En,Fr,De,Es,It)"
        if multi_lang not in candidates:
            candidates.append(multi_lang)

    return candidates


def _libretro_candidates(console, rom_name, sync_settings, rom_path=None):
    """libretro thumbnails provider (the historical, credential-free source)."""
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


def _screenscraper_credentials(sync_settings):
    return screenscraper.ScreenScraperCredentials(
        devid=sync_settings.get("screenscraper_devid", ""),
        devpassword=sync_settings.get("screenscraper_devpassword", ""),
        user=sync_settings.get("screenscraper_user", ""),
        password=sync_settings.get("screenscraper_password", ""),
    )


def _screenscraper_candidates(console, rom_name, sync_settings, rom_path=None):
    """ScreenScraper provider. Opt-in; returns [] whenever it is unusable."""
    try:
        return screenscraper.lookup_media_urls(
            credentials=_screenscraper_credentials(sync_settings),
            console=console,
            rom_name=rom_name,
            rom_path=rom_path,
            art_kind=sync_settings.get("cover_art_type", screenscraper.DEFAULT_ART_KIND),
            region_priority=sync_settings.get("region_priority"),
        )
    except Exception as exc:  # noqa: BLE001 - a source must never break the sync
        logger.warning("cover_sync screenscraper_failed: error=%s", screenscraper.redact(exc))
        return []


# Provider name -> module-level function name. Resolved lazily through globals()
# so the functions stay individually patchable in tests.
_PROVIDER_FUNCTIONS = {
    "libretro": "_libretro_candidates",
    "screenscraper": "_screenscraper_candidates",
}


def _ordered_providers(sync_settings):
    source = sync_settings.get("cover_source", COVER_SOURCE_LIBRETRO)
    names = _SOURCE_ORDER.get(source, _SOURCE_ORDER[COVER_SOURCE_LIBRETRO])
    return [(name, globals()[_PROVIDER_FUNCTIONS[name]]) for name in names]


def _remote_cover_candidates(console, rom_name, sync_settings, rom_path=None):
    """Concatenate candidate URLs from each configured source, in order."""
    urls = []
    for name, provider in _ordered_providers(sync_settings):
        for url in provider(console, rom_name, sync_settings, rom_path=rom_path):
            if url not in urls:
                urls.append(url)
        logger.debug(
            "cover_sync provider_candidates: provider=%s console=%s rom=%s total=%d",
            name,
            console,
            rom_name,
            len(urls),
        )
    return urls


def _download_cover(url, dest):
    # Media URLs can come from ScreenScraper, so redact before every log line in
    # case credentials were ever carried in the query string.
    safe_url = screenscraper.redact(url)
    try:
        logger.debug("cover_sync trying candidate: url=%s target=%s", safe_url, dest)
        # url is an https cover endpoint built by one of the source providers.
        with urllib.request.urlopen(url, timeout=12) as resp:  # nosec B310
            data = resp.read()
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        logger.info("cover_sync downloaded: url=%s target=%s bytes=%d", safe_url, dest, len(data))
        return True
    except urllib.error.HTTPError:
        logger.info("cover_sync not_found: url=%s", safe_url)
        return False
    except Exception as exc:
        logger.warning("cover_sync error: url=%s error=%s", safe_url, screenscraper.redact(exc))
        return False


def _sync_covers(
    library_by_console,
    covers_dir,
    scope,
    selected_console,
    sync_settings=None,
    on_progress=None,
    should_cancel=None,
):
    """Sync covers, optionally stopping early.

    ``should_cancel`` is polled between ROMs and between candidate URLs, so a
    cancel takes effect within one HTTP request rather than at the end of the
    run. Whatever was already downloaded stays on disk -- covers are
    independent files, so a partial run is useful rather than corrupt.
    """
    sync_settings = sync_settings or {}
    cancelled = False
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
        if cancelled:
            break
        for rom in roms:
            if should_cancel and should_cancel():
                logger.info("cover_sync cancelled: console=%s processed=%d", console, total)
                cancelled = True
                break
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
            urls = _remote_cover_candidates(console, name, sync_settings, rom_path=rom.get("path"))
            logger.info("cover_sync candidate_set: console=%s rom=%s candidates=%d", console, name, len(urls))
            found = False
            for url in urls:
                if should_cancel and should_cancel():
                    logger.info("cover_sync cancelled mid-candidate: console=%s rom=%s", console, name)
                    cancelled = True
                    break
                if _download_cover(url, target):
                    downloaded += 1
                    found = True
                    logger.info(
                        "cover_sync selected candidate: console=%s rom=%s url=%s",
                        console,
                        name,
                        screenscraper.redact(url),
                    )
                    break

            if cancelled:
                total -= 1  # this ROM was not actually processed
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
        "cancelled": cancelled,
        "total": total,
        "downloaded": downloaded,
        "skipped": skipped,
        "errors": errors,
    }
    logger.info(
        "cover_sync %s: scope=%s selected_console=%s total=%d downloaded=%d skipped=%d errors=%d",
        "cancelled" if cancelled else "finished",
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
    should_cancel=None,
):
    def _worker():
        summary = _sync_covers(
            library_by_console=library_by_console,
            covers_dir=covers_dir,
            scope=scope,
            selected_console=selected_console,
            sync_settings=sync_settings,
            on_progress=on_progress,
            should_cancel=should_cancel,
        )
        if on_done:
            on_done(summary)

    Thread(target=_worker, daemon=True).start()
