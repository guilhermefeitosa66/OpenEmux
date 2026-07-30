import logging
import re
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from threading import Thread

from openemux.core import embedded_credentials, screenscraper
from openemux.core.config import (
    ARTWORK_PROVIDER_KINDS_AVAILABLE,
    COVER_ART_TYPE_BOXART,
    COVER_ART_TYPE_CARTRIDGE_LABEL,
)
from openemux.core.scraper import COVER_ART, LABEL_ART, SUPPORTED_COVER_EXTS, find_local_art
from openemux.core.systems import get_thumbnail_system, resolve_system_id

logger = logging.getLogger(__name__)

# Where each artwork type belongs on disk. Cartridge labels are a different
# asset from box art -- the grid composites labels into a cartridge frame and
# shows box art everywhere else -- so they get their own directory and never
# overwrite one another.
_ART_DIR_BY_KIND = {
    COVER_ART_TYPE_BOXART: COVER_ART,
    COVER_ART_TYPE_CARTRIDGE_LABEL: LABEL_ART,
}

COVER_SOURCE_LIBRETRO = "libretro"
COVER_SOURCE_LIBRETRO_THEN_SCREENSCRAPER = "libretro_then_screenscraper"
COVER_SOURCE_SCREENSCRAPER = "screenscraper"

# Ordered provider names per configured cover source. "libretro" is the default
# and yields exactly the historical single-provider behavior. The project's own
# mirror (issue #74) closes every chain: it only ever fires for a ROM the
# preferred sources missed, so appending it changes no existing match.
_SOURCE_ORDER = {
    COVER_SOURCE_LIBRETRO: ("libretro", "openemux"),
    COVER_SOURCE_LIBRETRO_THEN_SCREENSCRAPER: ("libretro", "screenscraper", "openemux"),
    COVER_SOURCE_SCREENSCRAPER: ("screenscraper", "openemux"),
}

# The OpenEmux artwork mirror: a size-reduced WebP dump of the libretro box
# arts, hosted in its own repository so the project has a fallback source under
# its own control (and so the blobs stay out of the app repository).
OPENEMUX_ARTWORK_BASE = (
    "https://raw.githubusercontent.com/guilhermefeitosa66/openemux-artwork/main"
)

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


# Bracketed groups that carry metadata rather than a title. Anything in
# square brackets is a GoodTools-style marker ([!], [b1], [T+Eng]); the
# parenthesised forms below are No-Intro's. Whatever is left in parentheses
# after these is a genuine alternate title (issue #127).
_REGION_WORDS = {
    "usa", "us", "u", "europe", "eu", "e", "japan", "jp", "j", "world", "asia",
    "australia", "korea", "china", "taiwan", "brazil", "canada", "france",
    "germany", "italy", "spain", "netherlands", "sweden", "russia", "uk",
    "hong kong", "latin america", "scandinavia", "unknown",
}
_METADATA_TAG_RE = re.compile(
    r"^(?:"
    r"rev\s*[\w.]+"          # (Rev A), (Rev 1)
    r"|v?\d+(?:\.\d+)+[a-z]?"  # (v1.1), (1.0)
    r"|beta\s*\d*|proto\s*\d*|demo|sample|kiosk|promo"
    r"|unl|pirate|alt\s*\d*|fix|hack|trainer|aftermarket|homebrew"
    r"|virtual console|vc|gb compatible|sgb enhanced|nes|arcade"
    r"|[a-z]{2}(?:\s*,\s*[a-z]{2})+"  # language lists: En,Fr,De
    r"|[a-z]{2}"                      # a bare language code
    r")$",
    re.IGNORECASE,
)


def _is_metadata_tag(text):
    value = text.strip()
    if not value:
        return True
    parts = [part.strip().lower() for part in value.split(",")]
    if parts and all(part in _REGION_WORDS for part in parts):
        return True
    return bool(_METADATA_TAG_RE.match(value))


def _alternate_titles(rom_name):
    """Titles hiding inside parentheses, e.g. "Aero Fighters (Sonic Wings)".

    Both halves are real names the thumbnail repo might file the game under,
    so both are worth trying in their own right. Region and revision tags
    look identical structurally, so anything that reads as one is skipped.
    """
    titles = []
    for group in re.findall(r"\(([^()]*)\)", rom_name):
        if _is_metadata_tag(group):
            continue
        candidate = group.strip()
        if candidate and candidate not in titles:
            titles.append(candidate)
    return titles


def _strip_all_tags(name):
    """Drop every bracketed group, not only the trailing ones.

    ``_normalize_rom_name`` only peels tags off the end, so a mid-title
    "(USA)" or "(Rev A)" survived into the lookup name.
    """
    stripped = re.sub(r"\s*[\(\[][^\)\]]*[\)\]]\s*", " ", name)
    return re.sub(r"\s+", " ", stripped).strip()


def _drop_punctuation(name):
    """Collapse punctuation the thumbnail name may not share."""
    cleaned = re.sub(r"[^\w\s]", " ", name, flags=re.UNICODE)
    return re.sub(r"\s+", " ", cleaned).strip()


def fuzzy_candidate_names(rom_name):
    """Last-resort title guesses, tried only after every exact name misses.

    The existing matching is pure exact-URL guessing: normalize, then re-add
    a fixed region set. That covers ~95% of a library and the remaining
    misses are mostly naming shapes it has no rule for -- a mid-title tag, a
    punctuation difference, or a game filed under its other name.
    """
    candidates = []

    def _append(value):
        value = (value or "").strip()
        if value and value not in candidates:
            candidates.append(value)

    untagged = _strip_all_tags(rom_name)
    for seed in (untagged, _strip_accents(untagged)):
        _append(seed)
        _append(_drop_punctuation(seed))
        _append(_lower_connectors(seed))
        _append(_strip_sequence_markers(seed))

    for alternate in _alternate_titles(rom_name):
        for seed in (alternate, _strip_accents(alternate)):
            _append(seed)
            _append(_drop_punctuation(seed))
            _append(_lower_connectors(seed))

    for name in list(candidates):
        variant = _the_variant(name)
        if variant:
            _append(variant)

    return candidates


#: Ceiling on the last-resort pass. Each fuzzy title re-expands across the
#: region list, so an uncapped pass would turn one miss into hundreds of
#: requests. Truncation is logged rather than silent.
MAX_FUZZY_CANDIDATES = 40


def _fuzzy_urls_for(console, rom_name, sync_settings, rom, already_tried):
    """URLs for the fuzzy titles, minus everything already attempted."""
    seen = set(already_tried)
    urls = []
    truncated = False
    for fuzzy_name in fuzzy_candidate_names(rom_name):
        if fuzzy_name == rom_name:
            continue
        for url in _remote_cover_candidates(
            console, fuzzy_name, sync_settings, rom_path=rom.get("path")
        ):
            if url in seen:
                continue
            seen.add(url)
            if len(urls) >= MAX_FUZZY_CANDIDATES:
                truncated = True
                break
            urls.append(url)
        if truncated:
            break
    if truncated:
        logger.info(
            "cover_sync fuzzy pass capped: console=%s rom=%s cap=%d",
            console,
            rom_name,
            MAX_FUZZY_CANDIDATES,
        )
    return urls


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
    """libretro thumbnails provider (the historical, credential-free source).

    Box art only: ``Named_Boxarts`` is all it serves, so a cartridge-label
    pass must not receive box-art URLs that would be saved into ``labels/``.
    """
    if _requested_art_kind(sync_settings) != screenscraper.DEFAULT_ART_KIND:
        return []
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


def _build_openemux_art_url(system, game_name):
    # The mirror keeps libretro's directory names with underscores for spaces,
    # and every file is WebP (see openemux-artwork/README.md).
    directory = system.replace(" ", "_")
    return (
        f"{OPENEMUX_ARTWORK_BASE}/"
        f"{urllib.parse.quote(directory, safe='')}/"
        f"{urllib.parse.quote(game_name + '.webp', safe='')}"
    )


def _openemux_candidates(console, rom_name, sync_settings, rom_path=None):
    """The project's own art mirror (issue #74): libretro naming, WebP files.

    Box art only -- the mirror carries no cartridge labels, so a label pass
    must not receive box-art URLs from it.
    """
    if _requested_art_kind(sync_settings) != screenscraper.DEFAULT_ART_KIND:
        return []
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
    return [_build_openemux_art_url(system, candidate) for candidate in names]


def _screenscraper_credentials(sync_settings):
    devid, devpassword = _resolve_dev_credentials(sync_settings)
    return screenscraper.ScreenScraperCredentials(
        devid=devid,
        devpassword=devpassword,
        user=sync_settings.get("screenscraper_user", ""),
        password=sync_settings.get("screenscraper_password", ""),
    )


def _resolve_dev_credentials(sync_settings):
    """Pick the developer credential: user-configured wins, else the build's
    embedded one, else nothing.

    A user who supplies their own complete developer account overrides the
    credential baked into official builds; otherwise the embedded credential
    (empty in dev/local builds) is used so ScreenScraper works out of the box.
    """
    devid = (sync_settings.get("screenscraper_devid", "") or "").strip()
    devpassword = (sync_settings.get("screenscraper_devpassword", "") or "").strip()
    if devid and devpassword:
        return devid, devpassword
    return embedded_credentials.get_embedded_dev_credentials()


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
    "openemux": "_openemux_candidates",
}


def _requested_art_kind(sync_settings):
    return screenscraper.normalize_art_kind(
        (sync_settings or {}).get("cover_art_type", screenscraper.DEFAULT_ART_KIND)
    )


def _ordered_providers(sync_settings):
    """The provider chain for this run's artwork kind, in precedence order.

    Driven by the configured provider list (issue #76) when present: enabled
    providers only, and only those both *capable* of the kind being synced and
    *asked* to serve it. Configs that predate the list fall back to the old
    ``cover_source`` enum, which never gated on kind.
    """
    kind = _requested_art_kind(sync_settings)
    providers = (sync_settings or {}).get("providers")
    if providers:
        names = [
            entry.get("id")
            for entry in providers
            if entry.get("enabled", True)
            and entry.get("id") in _PROVIDER_FUNCTIONS
            and kind in ARTWORK_PROVIDER_KINDS_AVAILABLE.get(entry.get("id"), ())
            and kind in (entry.get("kinds") or ())
        ]
    else:
        source = sync_settings.get("cover_source", COVER_SOURCE_LIBRETRO)
        names = _SOURCE_ORDER.get(source, _SOURCE_ORDER[COVER_SOURCE_LIBRETRO])
    return [(name, globals()[_PROVIDER_FUNCTIONS[name]]) for name in names]


def has_provider_for_kind(sync_settings, art_kind):
    """Whether any enabled provider serves ``art_kind`` -- a pass with none
    would only burn requests and report every ROM as an error."""
    probe = dict(sync_settings or {})
    probe["cover_art_type"] = art_kind
    return bool(_ordered_providers(probe))


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


# Content-Type -> file extension, for providers whose URLs do not carry one.
_EXT_BY_CONTENT_TYPE = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
}


def _source_extension(url, response):
    """The downloaded image's own format: URL extension, then Content-Type.

    Saving a JPEG under ``.png`` loads fine (GdkPixbuf sniffs content) but lies
    on disk; every extension in ``SUPPORTED_COVER_EXTS`` is found by the local
    lookups, so the honest one costs nothing. Defaults to png when neither
    signal is usable.
    """
    ext = Path(urllib.parse.urlparse(url).path).suffix.lstrip(".").lower()
    if ext in SUPPORTED_COVER_EXTS:
        return "jpg" if ext == "jpeg" else ext
    content_type = (response.headers.get_content_type() or "").lower()
    return _EXT_BY_CONTENT_TYPE.get(content_type, "png")


def _download_cover(url, dest):
    """Download ``url`` and return the file written, or ``False`` on failure.

    The path is returned rather than a plain ``True`` because the extension is
    decided here, from the source: a caller replacing existing art has to know
    which file is the new one before it deletes the others.
    """
    # Media URLs can come from ScreenScraper, so redact before every log line in
    # case credentials were ever carried in the query string.
    safe_url = screenscraper.redact(url)
    try:
        logger.debug("cover_sync trying candidate: url=%s target=%s", safe_url, dest)
        # url is an https cover endpoint built by one of the source providers.
        with urllib.request.urlopen(url, timeout=12) as resp:  # nosec B310
            data = resp.read()
            # The caller's target carries the default .png; keep the source's
            # real format instead when the URL or the response names one.
            dest = dest.with_suffix(f".{_source_extension(url, resp)}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        logger.info("cover_sync downloaded: url=%s target=%s bytes=%d", safe_url, dest, len(data))
        return dest
    except urllib.error.HTTPError:
        logger.info("cover_sync not_found: url=%s", safe_url)
        return False
    except Exception as exc:
        logger.warning("cover_sync error: url=%s error=%s", safe_url, screenscraper.redact(exc))
        return False


def _drop_stale_art(roms_dir, console, rom_name, art_dir, keep):
    """Remove ``rom_name``'s art files in ``art_dir`` other than ``keep``."""
    if not isinstance(keep, (str, Path)):
        # Nothing to compare against: deleting here would risk taking the file
        # that was just downloaded with it.
        return
    for ext in SUPPORTED_COVER_EXTS:
        candidate = Path(roms_dir) / console / art_dir / f"{rom_name}.{ext}"
        if candidate == Path(keep) or not candidate.exists():
            continue
        try:
            candidate.unlink()
            logger.info("cover_sync replaced art: console=%s rom=%s old=%s", console, rom_name, candidate)
        except OSError as exc:
            logger.warning("cover_sync could not remove old art: path=%s error=%s", candidate, exc)


def _sync_covers(
    library_by_console,
    covers_dir,
    scope,
    selected_console,
    sync_settings=None,
    on_progress=None,
    should_cancel=None,
    replace_existing=False,
):
    """Sync covers, optionally stopping early.

    ``replace_existing`` turns off the skip-what-is-already-there rule. A
    library-wide sync leaves existing art alone -- it is a fill-in-the-blanks
    pass -- but syncing one ROM the user just asked for would otherwise do
    nothing at all on the very games whose art is wrong.

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
    # The configured artwork type decides which directory this run fills, so a
    # label sync never clobbers box art already scraped for the same ROM.
    art_kind = screenscraper.normalize_art_kind(
        sync_settings.get("cover_art_type", screenscraper.DEFAULT_ART_KIND)
    )
    art_dir = _ART_DIR_BY_KIND.get(art_kind, COVER_ART)
    logger.info(
        "cover_sync started: scope=%s selected_console=%s consoles=%s art_kind=%s dir=%s",
        scope,
        selected_console,
        consoles,
        art_kind,
        art_dir,
    )

    total = 0
    downloaded = 0
    skipped = 0
    errors = 0
    missed = []
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

            if not replace_existing and find_local_art(roms_dir_path, console, name, art_dir):
                logger.info("cover_sync skip existing: console=%s rom=%s kind=%s", console, name, art_kind)
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

            target = roms_dir_path / console / art_dir / f"{name}.png"
            urls = _remote_cover_candidates(console, name, sync_settings, rom_path=rom.get("path"))
            logger.info("cover_sync candidate_set: console=%s rom=%s candidates=%d", console, name, len(urls))

            def _try_urls(candidate_urls):
                """Download the first candidate that resolves.

                Returns (found, cancelled) so the caller keeps owning both
                counters and the outer loop's control flow.
                """
                for url in candidate_urls:
                    if should_cancel and should_cancel():
                        logger.info(
                            "cover_sync cancelled mid-candidate: console=%s rom=%s",
                            console,
                            name,
                        )
                        return False, True
                    written = _download_cover(url, target)
                    if not written:
                        continue
                    if replace_existing:
                        # Art saved earlier under another extension would still
                        # win the local lookup, so the replaced file has to go.
                        _drop_stale_art(roms_dir_path, console, name, art_dir, keep=written)
                    logger.info(
                        "cover_sync selected candidate: console=%s rom=%s url=%s",
                        console,
                        name,
                        screenscraper.redact(url),
                    )
                    return True, False
                return False, False

            found, cancelled_here = _try_urls(urls)
            if cancelled_here:
                cancelled = True
            tried_count = len(urls)

            if not found and not cancelled:
                # Every exact name missed. Fall back to the fuzzy titles --
                # mid-title tags stripped, punctuation dropped, and the
                # parenthesised alternate title tried in its own right
                # (issue #127). Deduplicated against what was already
                # attempted, since most fuzzy names regenerate the same URLs.
                extra = _fuzzy_urls_for(console, name, sync_settings, rom, urls)
                if extra:
                    logger.info(
                        "cover_sync fuzzy pass: console=%s rom=%s candidates=%d",
                        console,
                        name,
                        len(extra),
                    )
                    found, cancelled_here = _try_urls(extra)
                    if cancelled_here:
                        cancelled = True
                    tried_count += len(extra)

            if found:
                downloaded += 1

            if cancelled:
                total -= 1  # this ROM was not actually processed
                break
            if not found:
                logger.info(
                    "cover_sync missed: console=%s rom=%s tried=%d", console, name, tried_count
                )
                errors += 1
                # Carried through to the summary so the UI can say *which*
                # ROMs to look at, not just how many failed.
                missed.append({"console": console, "rom_name": name})
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
        # The identities behind `errors`, so the UI can name the ROMs that
        # still need artwork instead of only counting them (issue #127).
        "missed": missed,
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


def build_artwork_passes(library_by_console, label_consoles):
    """Plan the artwork passes for a set of ROMs: box art, then labels.

    Box art applies to every console. Cartridge labels only apply to the
    consoles in ``label_consoles`` -- the ones with a cartridge frame to paste
    a label into. Scraping a label for any other console is pointless work that
    also ends up displayed as if it were box art, so those are dropped here
    rather than filtered downstream.

    ``label_consoles`` is passed in rather than looked up so this stays free of
    the rendering stack; callers hand in
    ``cartridge_render.consoles_with_frames()``.
    """
    eligible = set(label_consoles or ())
    boxart = {console: roms for console, roms in library_by_console.items() if roms}
    labels = {console: roms for console, roms in boxart.items() if console in eligible}

    passes = []
    if boxart:
        passes.append((COVER_ART_TYPE_BOXART, boxart))
    if labels:
        passes.append((COVER_ART_TYPE_CARTRIDGE_LABEL, labels))
    logger.info(
        "artwork passes planned: boxart=%s labels=%s",
        sorted(boxart),
        sorted(labels),
    )
    return passes


def _sync_artwork(
    passes,
    covers_dir,
    sync_settings=None,
    on_progress=None,
    should_cancel=None,
    replace_existing=False,
):
    """Run several single-kind sync passes and aggregate them into one summary.

    ``passes`` is a sequence of ``(art_kind, library_by_console)`` pairs, run in
    order. Each pass overrides ``cover_art_type`` for itself, which is how one
    run can fetch box art for the whole import and cartridge labels for only the
    consoles that have a frame.

    Progress is reported against the combined total of every pass and carries
    the ``art_kind`` in flight, so a caller can show one task for the lot rather
    than one per kind. Passes with an empty library are dropped, so an import
    that touched no frame-capable console does not open an empty second pass.
    """
    settings = dict(sync_settings or {})
    planned = []
    for art_kind, library in passes:
        if not (library and any(library.get(console) for console in library)):
            continue
        # A kind no enabled provider serves would report every ROM as an
        # error; dropping the pass is the configuration speaking, not a bug.
        if not has_provider_for_kind(settings, art_kind):
            logger.info("artwork pass dropped, no provider serves it: kind=%s", art_kind)
            continue
        planned.append((art_kind, library))
    grand_total = sum(
        len(roms) for _kind, library in planned for roms in library.values()
    )

    aggregate = {
        "cancelled": False,
        "total": 0,
        "downloaded": 0,
        "skipped": 0,
        "errors": 0,
        "passes": [],
    }
    processed_before = 0

    for art_kind, library in planned:
        if should_cancel and should_cancel():
            aggregate["cancelled"] = True
            break

        def _pass_progress(evt, art_kind=art_kind, offset=processed_before):
            if not on_progress:
                return
            # Re-base this pass's counter onto the combined run so the banner
            # advances monotonically across kinds instead of restarting.
            forwarded = dict(evt)
            forwarded["processed"] = offset + evt.get("processed", 0)
            forwarded["total"] = grand_total
            forwarded["art_kind"] = art_kind
            on_progress(forwarded)

        summary = _sync_covers(
            library_by_console=library,
            covers_dir=covers_dir,
            scope="all",
            selected_console=None,
            sync_settings={**settings, "cover_art_type": art_kind},
            on_progress=_pass_progress,
            should_cancel=should_cancel,
            replace_existing=replace_existing,
        )
        summary["art_kind"] = art_kind
        aggregate["passes"].append(summary)
        for key in ("total", "downloaded", "skipped", "errors"):
            aggregate[key] += summary[key]
        processed_before += summary["total"]
        if summary["cancelled"]:
            aggregate["cancelled"] = True
            break

    logger.info(
        "sync_artwork %s: passes=%s total=%d downloaded=%d skipped=%d errors=%d",
        "cancelled" if aggregate["cancelled"] else "finished",
        [p["art_kind"] for p in aggregate["passes"]],
        aggregate["total"],
        aggregate["downloaded"],
        aggregate["skipped"],
        aggregate["errors"],
    )
    return aggregate


def sync_artwork_async(
    passes,
    covers_dir,
    on_done,
    sync_settings=None,
    on_progress=None,
    should_cancel=None,
    replace_existing=False,
):
    """Run :func:`_sync_artwork` on a background thread (see ``sync_covers_async``)."""

    def _worker():
        summary = _sync_artwork(
            passes=passes,
            covers_dir=covers_dir,
            sync_settings=sync_settings,
            on_progress=on_progress,
            should_cancel=should_cancel,
            replace_existing=replace_existing,
        )
        if on_done:
            on_done(summary)

    Thread(target=_worker, daemon=True).start()
