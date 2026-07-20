"""ScreenScraper.fr API v2 client (optional, opt-in cover art source).

Why this exists
---------------
libretro's thumbnail repository only carries No-Intro-named box art. ScreenScraper
additionally carries the *cartridge label* ("support") media, and matches by ROM
hash rather than by filename, so it resolves many ROMs libretro misses.

What the API actually requires (per https://www.screenscraper.fr/webapi2.php)
-----------------------------------------------------------------------------
* Base URL: ``https://api.screenscraper.fr/api2/``.
* Every request requires ``devid`` + ``devpassword`` (a *developer* account,
  granted by ScreenScraper staff on request) plus ``softname`` and ``output``.
  **Anonymous access is not possible** -- the docs are explicit that developer
  credentials are mandatory.
* ``ssid`` + ``sspassword`` are the *end user's* ScreenScraper account. They are
  technically optional, but without them a request runs on the developer's own
  quota, which is tiny. Each user is expected to supply their own account.
* Quotas are per-minute and per-day and scale with the user's contribution level
  (data or financial). HTTP 429 means the concurrent-thread limit was hit; HTTP
  430 means "your scrape quota is exceeded for today".
* The API may only be integrated into freely distributed applications.

Because OpenEmux ships no developer credentials, this source is **opt-in and off
by default**: the user configures their own credentials in Preferences, and when
anything is missing or fails we return no candidates so the caller falls back to
libretro. Nothing in here ever raises into the sync loop.
"""
import hashlib
import json
import logging
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from openemux.core.hasher import compute_crc32
from openemux.core.systems import resolve_system_id

logger = logging.getLogger(__name__)

API_BASE = "https://api.screenscraper.fr/api2/"
JEU_INFOS_ENDPOINT = API_BASE + "jeuInfos.php"

SOFTNAME = "OpenEmux"

# The API punishes bursts (HTTP 429 = thread limit reached), so serialise calls
# and keep a conservative floor between them.
MIN_REQUEST_INTERVAL_SECONDS = 1.0

REQUEST_TIMEOUT_SECONDS = 15

# HTTP status codes the API uses for quota/throttling. 429 = too many
# simultaneous threads for this account, 430 = daily scrape quota exhausted.
QUOTA_STATUS_CODES = (429, 430)

# Parameters that must never reach a log line or an error message.
_SECRET_PARAMS = ("devpassword", "sspassword", "devid", "ssid")

# ScreenScraper `systemeid` values mapped onto OpenEmux canonical system ids
# (src/openemux/core/systems.py). Numbers come from ScreenScraper's
# systemesListe.php platform table.
SYSTEM_ID_MAP = {
    "MD": 1,
    "SMS": 2,
    "FC": 3,
    "SFC": 4,
    "GB": 9,
    "GBC": 10,
    "VB": 11,
    "GBA": 12,
    "GC": 13,
    "N64": 14,
    "NDS": 15,
    "S32X": 19,
    "MCD": 20,
    "GG": 21,
    "SATURN": 22,
    "NGP": 25,
    "A2600": 26,
    "LYNX": 28,
    "PCE": 31,
    "A5200": 40,
    "A7800": 41,
    "WS": 45,
    "CV": 48,
    "PS": 57,
    "PSP": 61,
    "VECTREX": 102,
    "O2": 104,
    "FDS": 106,
    "SG1000": 109,
    "PCECD": 114,
    "INTV": 115,
}

# ScreenScraper media `type` names, in preference order per OpenEmux art kind.
# "box-2D" is the flat 2D box scan; "support-2D" is the cartridge/disc label
# scan (the "support" == physical media), with "support-texture" as fallback.
MEDIA_TYPES_BY_KIND = {
    "boxart": ("box-2D", "box-texture", "box-3D"),
    "cartridge_label": ("support-2D", "support-texture"),
}

DEFAULT_ART_KIND = "boxart"

# ScreenScraper region codes, most-preferred first. "wor" = world, "ss" =
# ScreenScraper's own generic/neutral entry.
DEFAULT_REGION_PRIORITY = ("wor", "us", "eu", "jp", "ss")

# Maps OpenEmux's libretro-style region names onto ScreenScraper region codes so
# the user's existing `region_priority` setting carries over.
_LIBRETRO_REGION_TO_SS = {
    "USA": "us",
    "WORLD": "wor",
    "EUROPE": "eu",
    "JAPAN": "jp",
}

_rate_limit_lock = threading.Lock()
_last_request_at = [0.0]


def _throttle():
    """Serialise requests and keep MIN_REQUEST_INTERVAL_SECONDS between them."""
    with _rate_limit_lock:
        elapsed = time.monotonic() - _last_request_at[0]
        wait = MIN_REQUEST_INTERVAL_SECONDS - elapsed
        if wait > 0:
            time.sleep(wait)
        _last_request_at[0] = time.monotonic()


def redact(text):
    """Strip credential values out of a URL or message before logging it."""
    if text is None:
        return text
    result = str(text)
    for param in _SECRET_PARAMS:
        result = _redact_param(result, param)
    return result


def _redact_param(text, param):
    out = []
    index = 0
    needle = param + "="
    while True:
        found = text.find(needle, index)
        if found == -1:
            out.append(text[index:])
            return "".join(out)
        out.append(text[index:found])
        out.append(needle + "***")
        end = found + len(needle)
        while end < len(text) and text[end] not in "&#":
            end += 1
        index = end


def get_screenscraper_system_id(console):
    """Return the ScreenScraper `systemeid` for an OpenEmux console, or None."""
    return SYSTEM_ID_MAP.get(resolve_system_id(console))


def normalize_art_kind(value):
    if value in MEDIA_TYPES_BY_KIND:
        return value
    return DEFAULT_ART_KIND


def region_priority_for(region_priority=None):
    """Translate OpenEmux region names to ScreenScraper codes, keeping order."""
    if not region_priority:
        return list(DEFAULT_REGION_PRIORITY)
    codes = []
    for region in region_priority:
        code = _LIBRETRO_REGION_TO_SS.get(str(region).strip().upper())
        if code and code not in codes:
            codes.append(code)
    for code in DEFAULT_REGION_PRIORITY:
        if code not in codes:
            codes.append(code)
    return codes


def compute_md5(rom_path, chunk_size=65536):
    """MD5 of a ROM file as an uppercase hex string, or None if unreadable."""
    try:
        digest = hashlib.md5()  # nosec B324 - content fingerprint, not security
        with open(rom_path, "rb") as handle:
            while chunk := handle.read(chunk_size):
                digest.update(chunk)
        return digest.hexdigest().upper()
    except OSError as exc:
        logger.debug("screenscraper md5 unavailable: error=%s", exc)
        return None


def compute_crc(rom_path):
    """CRC32 of a ROM file as an uppercase hex string, or None if unreadable."""
    try:
        return compute_crc32(rom_path)
    except OSError as exc:
        logger.debug("screenscraper crc unavailable: error=%s", exc)
        return None


class ScreenScraperCredentials:
    """Credentials bundle. Never logged; `__repr__` is deliberately opaque."""

    def __init__(self, devid="", devpassword="", user="", password=""):
        self.devid = (devid or "").strip()
        self.devpassword = (devpassword or "").strip()
        self.user = (user or "").strip()
        self.password = password or ""

    def is_usable(self):
        """The API rejects every request without developer credentials."""
        return bool(self.devid and self.devpassword)

    def __repr__(self):
        return "<ScreenScraperCredentials devid=*** ssid=*** (redacted)>"

    __str__ = __repr__


def build_jeu_infos_url(
    credentials,
    systemeid,
    rom_name,
    crc=None,
    md5=None,
    rom_size=None,
    romtype="rom",
):
    """Build the jeuInfos.php query URL. Returns None without credentials."""
    if credentials is None or not credentials.is_usable():
        return None

    params = [
        ("devid", credentials.devid),
        ("devpassword", credentials.devpassword),
        ("softname", SOFTNAME),
        ("output", "json"),
    ]
    if credentials.user:
        params.append(("ssid", credentials.user))
        params.append(("sspassword", credentials.password))
    if systemeid is not None:
        params.append(("systemeid", str(systemeid)))
    params.append(("romtype", romtype))
    if rom_name:
        params.append(("romnom", rom_name))
    if crc:
        params.append(("crc", crc))
    if md5:
        params.append(("md5", md5))
    if rom_size:
        params.append(("romtaille", str(rom_size)))

    return JEU_INFOS_ENDPOINT + "?" + urllib.parse.urlencode(params)


def _media_entries(payload):
    """Pull response.jeu.medias out of a decoded payload, defensively."""
    if not isinstance(payload, dict):
        return []
    response = payload.get("response")
    if not isinstance(response, dict):
        return []
    jeu = response.get("jeu")
    if not isinstance(jeu, dict):
        return []
    medias = jeu.get("medias")
    if not isinstance(medias, list):
        return []
    return [entry for entry in medias if isinstance(entry, dict)]


def parse_media_urls(payload, art_kind=DEFAULT_ART_KIND, region_priority=None):
    """Select media URLs for `art_kind`, ordered by region preference.

    Returns an empty list for any malformed / empty / error payload.
    """
    entries = _media_entries(payload)
    if not entries:
        return []

    wanted_types = MEDIA_TYPES_BY_KIND[normalize_art_kind(art_kind)]
    regions = region_priority_for(region_priority)

    def region_rank(entry):
        region = str(entry.get("region") or "").strip().lower()
        if region in regions:
            return regions.index(region)
        # Region-less entries sort just after the known regions, unknown last.
        return len(regions) if not region else len(regions) + 1

    urls = []
    for media_type in wanted_types:
        matching = [
            entry
            for entry in entries
            if str(entry.get("type") or "").strip().lower() == media_type.lower()
        ]
        matching.sort(key=region_rank)
        for entry in matching:
            url = str(entry.get("url") or "").strip()
            if url and url not in urls:
                urls.append(url)
    return urls


def _fetch_json(url, opener=None):
    """GET `url` and decode JSON. Returns None on any failure."""
    _throttle()
    try:
        open_url = opener or urllib.request.urlopen
        # url is always built by build_jeu_infos_url against a fixed https host.
        with open_url(url, timeout=REQUEST_TIMEOUT_SECONDS) as resp:  # nosec B310
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        if exc.code in QUOTA_STATUS_CODES:
            logger.warning(
                "screenscraper quota/throttle: status=%s (see webapi2.php: 429 thread limit, 430 daily quota)",
                exc.code,
            )
        else:
            logger.info("screenscraper http_error: status=%s", exc.code)
        return None
    except Exception as exc:  # noqa: BLE001 - never escape into the sync loop
        logger.warning("screenscraper request_error: error=%s", redact(exc))
        return None

    if isinstance(raw, bytes):
        text = raw.decode("utf-8", errors="replace")
    else:
        text = str(raw)

    try:
        return json.loads(text)
    except (ValueError, TypeError) as exc:
        # The API returns plain-text error bodies (e.g. quota messages) with a
        # 200 status in some cases; treat those as "no result".
        logger.info("screenscraper malformed_json: error=%s", redact(exc))
        return None


def lookup_media_urls(
    credentials,
    console,
    rom_name,
    rom_path=None,
    art_kind=DEFAULT_ART_KIND,
    region_priority=None,
    opener=None,
):
    """Look a ROM up and return candidate media URLs. Never raises.

    Returns [] whenever the source is unusable: no credentials, unmapped
    console, HTTP/quota error, malformed JSON, or no matching media.
    """
    if credentials is None or not credentials.is_usable():
        logger.debug("screenscraper skipped: credentials not configured")
        return []

    systemeid = get_screenscraper_system_id(console)
    if systemeid is None:
        logger.info("screenscraper unmapped_console: console=%s", console)
        return []

    crc = None
    md5 = None
    rom_size = None
    if rom_path:
        crc = compute_crc(rom_path)
        md5 = compute_md5(rom_path)
        try:
            import os

            rom_size = os.path.getsize(rom_path)
        except OSError:
            rom_size = None

    url = build_jeu_infos_url(
        credentials=credentials,
        systemeid=systemeid,
        rom_name=rom_name,
        crc=crc,
        md5=md5,
        rom_size=rom_size,
    )
    if not url:
        return []

    logger.info(
        "screenscraper lookup: console=%s systemeid=%s rom=%s url=%s",
        console,
        systemeid,
        rom_name,
        redact(url),
    )
    payload = _fetch_json(url, opener=opener)
    if payload is None:
        return []

    urls = parse_media_urls(payload, art_kind=art_kind, region_priority=region_priority)
    logger.info(
        "screenscraper result: console=%s rom=%s art_kind=%s candidates=%d",
        console,
        rom_name,
        normalize_art_kind(art_kind),
        len(urls),
    )
    return urls
