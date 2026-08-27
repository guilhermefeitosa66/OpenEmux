import logging
import re
import time
import threading
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Thread

from openemux.core import embedded_credentials, hasher, screenscraper
from openemux.core.artwork_index import ArtworkNameIndex
from openemux.core.config import (
    ARTWORK_PROVIDER_KINDS_AVAILABLE,
    COVER_ART_TYPE_BOXART,
    COVER_ART_TYPE_CARTRIDGE_LABEL,
)
from openemux.core.atomic_write import atomic_write_bytes
from openemux.core.scraper import (
    COVER_ART,
    LABEL_ART,
    SUPPORTED_COVER_EXTS,
    find_local_art,
    image_format,
    is_image,
    is_image_file,
)
from openemux.core.systems import get_thumbnail_system, resolve_system_id

logger = logging.getLogger(__name__)

# The lookup ladder's stage names (issue #175), as they appear in logs and
# in the summary tally: content hash, the stem as-is, the normalization
# ladder, and the last-resort full-text resolution against the local index.
STAGE_HASH = "hash"
STAGE_EXACT = "exact"
STAGE_NORMALIZED = "normalized"
STAGE_FTS = "fts"

# -- politeness budgets (#186) ---------------------------------------------
#: Worker pool size for the per-ROM fan-out. Parallelism is across ROMs;
#: each ROM still walks its own candidate ladder serially.
SYNC_WORKERS = 6

#: Concurrent in-flight requests allowed per host. Our own mirror is ours
#: to saturate; third-party hosts keep today's one-at-a-time politeness --
#: hammering them risks rate-limiting and is exactly what the mirror was
#: built to avoid.
HOST_BUDGETS = {
    "raw.githubusercontent.com": SYNC_WORKERS,
    "thumbnails.libretro.com": 1,
    "www.screenscraper.fr": 1,
    "api.screenscraper.fr": 1,
}
DEFAULT_HOST_BUDGET = 1

#: Gate name for ScreenScraper's candidate-building API call, which is a
#: network request of its own and must respect the same serial budget.
SCREENSCRAPER_API_GATE = "www.screenscraper.fr"

#: Hosts whose downloads owe ScreenScraper's minimum interval, not just its
#: concurrency budget.
_SCREENSCRAPER_HOSTS = ("www.screenscraper.fr", "api.screenscraper.fr")


def _is_screenscraper_host(url):
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    return host in _SCREENSCRAPER_HOSTS


class _HostGates:
    """Per-host semaphores, created lazily. Thread-safe."""

    def __init__(self, budgets=None, default=DEFAULT_HOST_BUDGET):
        self._budgets = dict(HOST_BUDGETS if budgets is None else budgets)
        self._default = default
        self._gates = {}
        self._lock = threading.Lock()

    def gate(self, host):
        host = (host or "").lower()
        with self._lock:
            gate = self._gates.get(host)
            if gate is None:
                limit = self._budgets.get(host, self._default)
                gate = threading.BoundedSemaphore(limit)
                self._gates[host] = gate
        return gate

    def gate_for_url(self, url):
        return self.gate(urllib.parse.urlparse(url).hostname)

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

# The libretro thumbnail naming convention replaces these characters with
# ``_`` in filenames; a *display* title like "Batman & Robin" must become
# "Batman _ Robin" before the URL is formed, or every candidate 404s (#175,
# diagnosed by mozertdev). Applied at URL build time so every name path --
# exact, normalized and FTS-resolved -- benefits at once, and so
# _normalize_rom_name's earlier "_ -> space" rule cannot undo it.
_THUMBNAIL_SANITIZE = str.maketrans({ch: "_" for ch in '&*/:`<>?\\|"'})


def _sanitize_thumbnail_name(game_name):
    return game_name.translate(_THUMBNAIL_SANITIZE)


def _build_cover_url(system, game_name):
    return (
        "https://thumbnails.libretro.com/"
        f"{urllib.parse.quote(system, safe='')}/Named_Boxarts/"
        f"{urllib.parse.quote(_sanitize_thumbnail_name(game_name) + '.png', safe='')}"
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


def _libretro_candidates(console, rom_name, sync_settings, rom_path=None, names=None):
    """libretro thumbnails provider (the historical, credential-free source).

    Box art only: ``Named_Boxarts`` is all it serves, so a cartridge-label
    pass must not receive box-art URLs that would be saved into ``labels/``.

    ``names`` overrides the generated candidate list -- the staged ladder
    (#175) uses it to ask for exactly one stage's names at a time.
    """
    if _requested_art_kind(sync_settings) != screenscraper.DEFAULT_ART_KIND:
        return []
    system_id = resolve_system_id(console)
    system = get_thumbnail_system(system_id)
    if not system:
        return []

    if names is None:
        names = _candidate_names(
            rom_name=rom_name,
            matching_mode=sync_settings.get("matching_mode", "normalized_region_priority"),
            region_priority=sync_settings.get("region_priority", ["USA", "World", "Europe", "Japan"]),
            name_cleanup=bool(sync_settings.get("name_cleanup", True)),
        )
    return [_build_cover_url(system, candidate) for candidate in names]


def _build_openemux_art_url(system, game_name):
    # The mirror keeps libretro's directory names with underscores for spaces,
    # and every file is WebP (see openemux-artwork/README.md). Filenames carry
    # the same character substitutions as upstream (#175).
    directory = system.replace(" ", "_")
    return (
        f"{OPENEMUX_ARTWORK_BASE}/"
        f"{urllib.parse.quote(directory, safe='')}/"
        f"{urllib.parse.quote(_sanitize_thumbnail_name(game_name) + '.webp', safe='')}"
    )


def _openemux_candidates(console, rom_name, sync_settings, rom_path=None, names=None):
    """The project's own art mirror (issue #74): libretro naming, WebP files.

    Box art only -- the mirror carries no cartridge labels, so a label pass
    must not receive box-art URLs from it. ``names`` as in
    :func:`_libretro_candidates`.
    """
    if _requested_art_kind(sync_settings) != screenscraper.DEFAULT_ART_KIND:
        return []
    system_id = resolve_system_id(console)
    system = get_thumbnail_system(system_id)
    if not system:
        return []

    if names is None:
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


def _screenscraper_candidates(console, rom_name, sync_settings, rom_path=None, quota=None):
    """ScreenScraper provider. Opt-in; returns [] whenever it is unusable."""
    try:
        return screenscraper.lookup_media_urls(
            credentials=_screenscraper_credentials(sync_settings),
            console=console,
            rom_name=rom_name,
            rom_path=rom_path,
            art_kind=sync_settings.get("cover_art_type", screenscraper.DEFAULT_ART_KIND),
            region_priority=sync_settings.get("region_priority"),
            quota=quota,
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


#: The process-wide name index, created lazily; tests patch the factory.
_NAME_INDEX = None


def _get_name_index():
    global _NAME_INDEX
    if _NAME_INDEX is None:
        _NAME_INDEX = ArtworkNameIndex()
    return _NAME_INDEX


def _resolve_hash_stem(console, rom_path, sync_settings):
    """Stage 1 for the file-based providers: the canonical stem by CRC32.

    Gated on the index actually carrying a ``crc_index`` table, so hashing
    the ROM file -- the only costly step -- never runs for nothing. One
    resolution serves every file-based provider (#175: "one index hit fixes
    both").
    """
    if not rom_path:
        return None
    try:
        index = _get_name_index()
        if not index.has_crc_index():
            return None
        thumb_system = get_thumbnail_system(resolve_system_id(console))
        if not thumb_system:
            return None
        return index.resolve_by_crc(thumb_system, hasher.compute_crc32(rom_path))
    except Exception as exc:  # noqa: BLE001
        logger.warning("cover_sync hash stage failed: rom=%s error=%s", rom_path, exc)
        return None


#: The two file-based providers serve the same files under the same stems
#: (the mirror reproduces upstream filenames), which is what makes them
#: interchangeable for load balancing (#186, mozertdev's suggestion).
_EQUIVALENT_PROVIDERS = ("libretro", "openemux")


def _staged_cover_candidates(console, rom_name, sync_settings, rom_path=None,
                             provider_rotation=0, gates=None, quota=None):
    """``(provider, stage, url)`` triples: each provider's ladder in order.

    **A generator, and that is the point.** Provider *n* runs hash -> exact ->
    normalized before provider *n+1* starts (#175), and building all of it up
    front made the ladder's order a lie: the ScreenScraper block does a
    ``jeuInfos`` round trip while it is being *assembled*, so every ROM paid
    for that call -- one request off the daily quota, and at least a second in
    the throttle -- even when the very first libretro candidate was about to
    work. A first sync of a 1000-ROM library spent at least 1000 seconds
    waiting to be told things it never needed to ask (issue #220).

    Consumed lazily, a provider's block is only built when the ladder actually
    reaches it, so ScreenScraper is asked about the ROMs libretro missed and no
    others. The CRC32 of the ROM file, which the file-based hash stage needs,
    is resolved the same way: once, on first use, and not at all when an
    earlier provider answers.

    ``provider_rotation`` load-balances across the two equivalent file
    hosts (#186): on odd rotations the libretro and openemux blocks trade
    places, so a parallel sync drains both hosts at once instead of
    serializing every ROM on the first one. Each ROM still exhausts every
    provider before being reported as missed. ``gates`` throttles the
    ScreenScraper candidate lookup, which is a network call of its own, and
    ``quota`` is the run's latch: once the API has said the daily quota is
    gone, the lookup returns without asking again.
    """
    providers = _ordered_providers(sync_settings)
    if provider_rotation % 2 == 1:
        names = [name for name, _provider in providers]
        if all(name in names for name in _EQUIVALENT_PROVIDERS):
            first, second = (names.index(n) for n in _EQUIVALENT_PROVIDERS)
            providers[first], providers[second] = providers[second], providers[first]

    hash_stem = _LazyOnce(lambda: _resolve_hash_stem(console, rom_path, sync_settings))
    seen = set()
    for name, provider in providers:
        if name == "screenscraper":
            block = _screenscraper_block(
                name, provider, console, rom_name, sync_settings, rom_path, gates, quota
            )
        else:
            block = _file_provider_block(
                name, provider, console, rom_name, sync_settings, rom_path, hash_stem
            )
        for triple in block:
            if triple[2] in seen:
                continue
            seen.add(triple[2])
            yield triple


class _LazyOnce:
    """Call ``produce`` at most once, on first use, and keep the answer."""

    _MISSING = object()

    def __init__(self, produce):
        self._produce = produce
        self._value = self._MISSING

    def get(self):
        if self._value is self._MISSING:
            self._value = self._produce()
        return self._value


def _screenscraper_block(name, provider, console, rom_name, sync_settings,
                         rom_path, gates, quota):
    """ScreenScraper's whole ladder: the API answers by content hash."""
    stage = STAGE_HASH if rom_path else STAGE_NORMALIZED
    if gates is not None:
        with gates.gate(SCREENSCRAPER_API_GATE):
            urls = provider(console, rom_name, sync_settings, rom_path=rom_path, quota=quota)
    else:
        urls = provider(console, rom_name, sync_settings, rom_path=rom_path, quota=quota)
    return [(name, stage, url) for url in urls]


def _file_provider_block(name, provider, console, rom_name, sync_settings,
                         rom_path, hash_stem):
    """A file host's ladder: the canonical stem, the name, then the variants."""
    block = []
    stem = hash_stem.get()
    if stem:
        block.extend((name, STAGE_HASH, url) for url in provider(
            console, rom_name, sync_settings, rom_path=rom_path, names=[stem]
        ))
    block.extend((name, STAGE_EXACT, url) for url in provider(
        console, rom_name, sync_settings, rom_path=rom_path, names=[rom_name]
    ))
    block.extend((name, STAGE_NORMALIZED, url) for url in provider(
        console, rom_name, sync_settings, rom_path=rom_path
    ))
    return block


def _fts_stage_candidates(console, rom_name, sync_settings, already_tried):
    """Stage 4 (#175): resolve the name against the local FTS index, once,
    after every provider exhausted its ladder -- and only then, because this
    is the single stage able to match the wrong game.

    Only URLs built from stems known to exist in the mirror are returned;
    no index, no FTS5 or no acceptable match simply yields nothing.
    """
    try:
        index = _get_name_index()
        thumb_system = get_thumbnail_system(resolve_system_id(console))
        if not thumb_system:
            return []
        resolved = index.resolve_name(
            thumb_system,
            rom_name,
            region_priority=sync_settings.get("region_priority"),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("cover_sync fts stage failed: rom=%s error=%s", rom_name, exc)
        return []
    if not resolved:
        return []
    stem, round_label = resolved
    logger.debug(
        "cover_sync fts resolved: console=%s rom=%s stem=%s round=%s",
        console,
        rom_name,
        stem,
        round_label,
    )
    triples = []
    for name, provider in _ordered_providers(sync_settings):
        if name == "screenscraper":
            continue  # an API provider gains nothing from a filename stem
        for url in provider(console, rom_name, sync_settings, names=[stem]):
            if url not in already_tried:
                triples.append((name, STAGE_FTS, url))
    return triples


def _remote_cover_candidates(console, rom_name, sync_settings, rom_path=None):
    """Candidate URLs from each configured source, ladder order preserved."""
    return [
        url
        for _provider, _stage, url in _staged_cover_candidates(
            console, rom_name, sync_settings, rom_path=rom_path
        )
    ]


# Content-Type -> file extension, for providers whose URLs do not carry one.
_EXT_BY_CONTENT_TYPE = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
}


def _source_extension(url, response, data=None):
    """The downloaded image's own format: the bytes, the URL, then Content-Type.

    Saving a JPEG under ``.png`` loads fine (GdkPixbuf sniffs content) but lies
    on disk; every extension in ``SUPPORTED_COVER_EXTS`` is found by the local
    lookups, so the honest one costs nothing. The bytes come first when they
    are available: a server is free to be wrong about its own Content-Type,
    and the file cannot be.
    """
    sniffed = image_format(data) if data is not None else None
    if sniffed:
        return sniffed
    ext = Path(urllib.parse.urlparse(url).path).suffix.lstrip(".").lower()
    if ext in SUPPORTED_COVER_EXTS:
        return "jpg" if ext == "jpeg" else ext
    content_type = (response.headers.get_content_type() or "").lower()
    return _EXT_BY_CONTENT_TYPE.get(content_type, "png")


#: Statuses worth one more try: the host is rate-limiting us or having a bad
#: minute, neither of which means the cover is absent.
_RETRYABLE_STATUSES = (408, 425, 429, 500, 502, 503, 504)

#: How long to wait before that retry, and the ceiling on a Retry-After the
#: host asks for. A sync holds this host's gate while it waits, which is the
#: point -- but a worker must not park on it.
_RETRY_DELAY_SECONDS = 1.5
_MAX_RETRY_DELAY_SECONDS = 5.0


def _retry_delay(response):
    """The pause before a retry, honouring a sane ``Retry-After``."""
    header = getattr(response, "headers", None)
    raw = header.get("Retry-After") if header is not None else None
    try:
        asked = float(raw)
    except (TypeError, ValueError):
        return _RETRY_DELAY_SECONDS
    return max(0.0, min(asked, _MAX_RETRY_DELAY_SECONDS))


def _download_cover(url, dest, attempts=2):
    """Download ``url`` and return the file written, or ``False`` on failure.

    The path is returned rather than a plain ``True`` because the extension is
    decided here, from the source: a caller replacing existing art has to know
    which file is the new one before it deletes the others.

    Every HTTP error used to be logged as ``not_found`` and dropped, so a 429
    from ``thumbnails.libretro.com`` -- or a transient 500 -- was recorded as a
    ROM with no artwork, and the next sync skipped it (issue #220). A 404 is
    the only status that really means "not there"; the rest get one retry.

    Nothing is written unless the bytes are actually an image. A 200 response
    is not proof of one -- ScreenScraper answers some quota failures with a
    plain-text body and a 200, and a captive portal answers everything with
    HTML -- and whatever landed at that path became the ROM's "art" forever
    after: every later sync skipped the ROM because a file was there, and the
    only symptom was a blank card and a decode warning (issue #213).
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
            # real format instead -- read from the bytes themselves.
            extension = _source_extension(url, resp, data=data)
        if not is_image(data):
            logger.warning(
                "cover_sync rejected non-image body: url=%s bytes=%d starts=%r",
                safe_url,
                len(data or b""),
                (data or b"")[:32],
            )
            return False
        dest = dest.with_suffix(f".{extension}")
        # Written whole or not at all: a partial file at the final name is
        # indistinguishable from art, and blocks the ROM just the same.
        atomic_write_bytes(dest, data)
        logger.debug("cover_sync downloaded: url=%s target=%s bytes=%d", safe_url, dest, len(data))
        return dest
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            logger.debug("cover_sync not_found: url=%s", safe_url)
            return False
        if exc.code in _RETRYABLE_STATUSES and attempts > 1:
            delay = _retry_delay(exc)
            logger.info(
                "cover_sync retrying: url=%s status=%s in=%.1fs", safe_url, exc.code, delay
            )
            time.sleep(delay)
            return _download_cover(url, dest, attempts=attempts - 1)
        logger.warning("cover_sync http_error: url=%s status=%s", safe_url, exc.code)
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
            logger.debug("cover_sync replaced art: console=%s rom=%s old=%s", console, rom_name, candidate)
        except OSError as exc:
            logger.warning("cover_sync could not remove old art: path=%s error=%s", candidate, exc)


def _process_rom(console, rom, roms_dir_path, art_dir, art_kind, sync_settings,
                 should_cancel, replace_existing, rotation, gates, quota=None):
    """One ROM's whole lookup, run on a pool worker (#186).

    Returns a result dict; the completion loop owns every shared counter,
    so nothing here mutates state outside this ROM's own files.
    """
    name = rom["name"]
    rom_path = rom.get("path")
    if should_cancel and should_cancel():
        return {"status": "cancelled", "console": console, "rom_name": name,
                "rom_path": rom_path}

    existing = None if replace_existing else find_local_art(roms_dir_path, console, name, art_dir)
    if existing and not is_image_file(existing):
        # An error page saved as a cover by an older version. It is what made
        # this sticky: any file at that path counted as art, so the ROM was
        # skipped on every later sync and the user had to find and delete it
        # by hand (issue #213). Clear it and fetch properly.
        logger.warning(
            "cover_sync discarding art that is not an image: console=%s rom=%s path=%s",
            console,
            name,
            existing,
        )
        try:
            Path(existing).unlink()
            existing = None
        except OSError as exc:
            logger.warning("cover_sync could not remove junk art: path=%s error=%s", existing, exc)

    if existing:
        logger.debug(
            "cover_sync skip existing: console=%s rom=%s kind=%s", console, name, art_kind
        )
        return {"status": "skipped", "console": console, "rom_name": name,
                "rom_path": rom_path}

    target = roms_dir_path / console / art_dir / f"{name}.png"
    candidates = _staged_cover_candidates(
        console, name, sync_settings, rom_path=rom.get("path"),
        provider_rotation=rotation, gates=gates, quota=quota,
    )
    # Recorded as they are consumed rather than counted up front: the ladder
    # is a generator now, so the candidates past the one that won were never
    # built (issue #220). This is also what the FTS stage has to exclude.
    tried = []

    def _try_candidates(triples):
        """First candidate that resolves: (stage or None, cancelled)."""
        for provider, stage, url in triples:
            if should_cancel and should_cancel():
                logger.info(
                    "cover_sync cancelled mid-candidate: console=%s rom=%s", console, name
                )
                return None, True
            tried.append(url)
            with gates.gate_for_url(url):
                if _is_screenscraper_host(url):
                    # Media lives on a ScreenScraper host too, and the host
                    # gate only bounds concurrency. Without this the image
                    # fetch skipped the interval the API call just waited out.
                    screenscraper.throttle()
                written = _download_cover(url, target)
            if not written:
                continue
            if replace_existing:
                # Art saved earlier under another extension would still
                # win the local lookup, so the replaced file has to go.
                _drop_stale_art(roms_dir_path, console, name, art_dir, keep=written)
            logger.debug(
                "cover_sync selected candidate: console=%s rom=%s provider=%s stage=%s url=%s",
                console,
                name,
                provider,
                stage,
                screenscraper.redact(url),
            )
            return stage, False
        return None, False

    stage, cancelled = _try_candidates(candidates)

    if stage is None and not cancelled:
        # Stage 4 (#175): every provider exhausted its ladder, so resolve
        # the name once against the local FTS index and try only URLs whose
        # stems are known to exist in the mirror. Runs last and globally on
        # purpose -- it is the only stage that can match the wrong game.
        extra = _fts_stage_candidates(
            console, name, sync_settings, already_tried=set(tried),
        )
        if extra:
            stage, cancelled = _try_candidates(extra)

    if stage is not None:
        return {"status": "downloaded", "console": console, "rom_name": name,
                "rom_path": rom_path, "stage": stage}
    if cancelled:
        return {"status": "cancelled", "console": console, "rom_name": name,
                "rom_path": rom_path}
    logger.debug(
        "cover_sync missed: console=%s rom=%s tried=%d", console, name, len(tried)
    )
    return {"status": "missed", "console": console, "rom_name": name,
            "rom_path": rom_path}


def _sync_covers(
    library_by_console,
    covers_dir,
    scope,
    selected_console,
    sync_settings=None,
    on_progress=None,
    should_cancel=None,
    replace_existing=False,
    max_workers=None,
):
    """Sync covers on a bounded worker pool, optionally stopping early.

    ``replace_existing`` turns off the skip-what-is-already-there rule. A
    library-wide sync leaves existing art alone -- it is a fill-in-the-blanks
    pass -- but syncing one ROM the user just asked for would otherwise do
    nothing at all on the very games whose art is wrong.

    ``should_cancel`` is polled per worker between candidate URLs, so a
    cancel takes effect within roughly one in-flight request per worker.
    Whatever was already downloaded stays on disk -- covers are independent
    files, so a partial run is useful rather than corrupt.

    Parallelism (#186) is across ROMs -- each ROM's provider ladder stays
    serial -- with per-host politeness budgets: the project's own mirror
    takes real concurrency, third-party hosts keep one request at a time.
    Progress events fire from the completion loop in submission-independent
    arrival order, with a ``processed`` counter that only ever grows.
    """
    sync_settings = sync_settings or {}
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

    work = [
        (console, rom)
        for console in consoles
        for rom in library_by_console.get(console, [])
    ]
    total_targets = len(work)
    workers = max(1, int(max_workers or SYNC_WORKERS))
    gates = _HostGates()
    # One per run: the first ROM told the daily quota is gone spares every ROM
    # after it a request and a second of throttle (issue #220).
    quota = screenscraper.QuotaLatch()

    cancelled = False
    total = 0
    downloaded = 0
    skipped = 0
    errors = 0
    missed = []
    # Which ladder stage found each downloaded cover (#175): the sync's own
    # observability, so reports like mozertdev's are answerable from a log.
    stage_tally = {STAGE_HASH: 0, STAGE_EXACT: 0, STAGE_NORMALIZED: 0, STAGE_FTS: 0}

    with ThreadPoolExecutor(
        max_workers=workers, thread_name_prefix="openemux-cover-sync"
    ) as pool:
        futures = [
            pool.submit(
                _process_rom, console, rom, roms_dir_path, art_dir, art_kind,
                sync_settings, should_cancel, replace_existing, index, gates, quota,
            )
            for index, (console, rom) in enumerate(work)
        ]
        for future in as_completed(futures):
            if future.cancelled():
                continue
            try:
                result = future.result()
            except Exception as exc:  # noqa: BLE001 - one ROM must not kill the run
                logger.warning("cover_sync worker failed: error=%s",
                               screenscraper.redact(exc))
                result = {"status": "missed", "console": "?", "rom_name": "?"}
            status = result["status"]
            if status == "cancelled":
                if not cancelled:
                    cancelled = True
                    logger.info("cover_sync cancelled: processed=%d", total)
                    # Nothing queued should start; in-flight workers notice
                    # should_cancel within about one request each.
                    for pending in futures:
                        pending.cancel()
                continue
            total += 1
            if status == "downloaded":
                downloaded += 1
                stage_tally[result["stage"]] = stage_tally.get(result["stage"], 0) + 1
            elif status == "skipped":
                skipped += 1
            else:
                errors += 1
                # Carried through to the summary so the UI can say *which*
                # ROMs to look at, not just how many failed (issue #127).
                missed.append(
                    {"console": result["console"], "rom_name": result["rom_name"]}
                )
            if on_progress:
                on_progress(
                    {
                        "console": result["console"],
                        "rom_name": result["rom_name"],
                        "rom_path": result.get("rom_path"),
                        "result": status,
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
        # Which ladder stage each downloaded cover came from (#175).
        "stages": stage_tally,
    }
    logger.info(
        "cover_sync %s: scope=%s selected_console=%s total=%d downloaded=%d skipped=%d errors=%d stages=%s",
        "cancelled" if cancelled else "finished",
        scope,
        selected_console,
        total,
        downloaded,
        skipped,
        errors,
        stage_tally,
    )
    return summary


def _crashed_summary(scope, selected_console, error):
    """A sync summary for a run that died, so the caller can still finish.

    Zeroes everywhere and the error in ``crashed``: the UI clears its running
    flag, closes the task and can say what happened, instead of being left
    with a banner it can never dismiss.
    """
    return {
        "scope": scope,
        "selected_console": selected_console,
        "cancelled": False,
        "total": 0,
        "downloaded": 0,
        "skipped": 0,
        "errors": 0,
        "error_roms": [],
        "stages": {},
        "crashed": str(error),
    }


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
        summary = None
        try:
            summary = _sync_covers(
                library_by_console=library_by_console,
                covers_dir=covers_dir,
                scope=scope,
                selected_console=selected_console,
                sync_settings=sync_settings,
                on_progress=on_progress,
                should_cancel=should_cancel,
            )
        except Exception as exc:
            # on_done is what clears the caller's "a sync is running" flag.
            # A worker that dies without firing it wedges the app for the
            # rest of the session (issue #214), so it always fires -- with a
            # summary shaped like a real one, carrying the error.
            logger.exception("cover sync crashed")
            summary = _crashed_summary(scope, selected_console, exc)
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
        "stages": {STAGE_HASH: 0, STAGE_EXACT: 0, STAGE_NORMALIZED: 0, STAGE_FTS: 0},
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
        for stage, count in summary.get("stages", {}).items():
            aggregate["stages"][stage] = aggregate["stages"].get(stage, 0) + count
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
        summary = None
        try:
            summary = _sync_artwork(
                passes=passes,
                covers_dir=covers_dir,
                sync_settings=sync_settings,
                on_progress=on_progress,
                should_cancel=should_cancel,
                replace_existing=replace_existing,
            )
        except Exception as exc:
            logger.exception("artwork sync crashed")
            summary = _crashed_summary("all", None, exc)
            summary["passes"] = []
        if on_done:
            on_done(summary)

    Thread(target=_worker, daemon=True).start()
