"""Per-ROM artwork search across the configured provider chain (issue #77).

The bulk sync stops at the first URL that downloads; the artwork manager wants
the opposite -- every image the enabled providers actually have for one ROM,
downloaded to a temp folder so the user can pick by eye. The provider chain
and its ordering are exactly the bulk sync's (issue #76), so what the manager
shows is what a sync would have considered, in the same precedence order.

Widget-free on purpose: the window drives this from worker threads.
"""

import hashlib
import logging
import urllib.error
import urllib.request
from pathlib import Path
from threading import Thread

from openemux.core import cover_sync, screenscraper

logger = logging.getLogger(__name__)

#: Stop after this many distinct images per provider: candidate URL lists are
#: name variants of the same file, so distinct hits beyond a few are unlikely
#: and every extra URL is a network round-trip.
MAX_RESULTS_PER_PROVIDER = 4

#: Downloaded candidate: where it landed, which provider offered it.
class ArtworkCandidate:
    def __init__(self, path, provider, url):
        self.path = Path(path)
        self.provider = provider
        self.url = url


def provider_candidates(console, rom_name, sync_settings, art_kind, rom_path=None):
    """``(provider, url)`` pairs for one ROM, chain order preserved.

    ``rom_path=None`` is the name search; passing it lets hash-capable
    providers (ScreenScraper) match by CRC/MD5 instead -- the manager's
    "search by hash" button is exactly that.
    """
    settings = dict(sync_settings or {})
    settings["cover_art_type"] = art_kind
    pairs = []
    for name, provider in cover_sync._ordered_providers(settings):
        try:
            urls = provider(console, rom_name, settings, rom_path=rom_path)
        except Exception as exc:  # noqa: BLE001 - one provider must not kill the search
            logger.warning("artwork search provider failed: provider=%s error=%s",
                           name, screenscraper.redact(exc))
            continue
        for url in urls:
            pairs.append((name, url))
    return pairs


def _download(url, dest_dir, index):
    try:
        with urllib.request.urlopen(url, timeout=12) as resp:  # nosec B310
            data = resp.read()
            ext = cover_sync._source_extension(url, resp)
    except urllib.error.HTTPError:
        return None, None
    except Exception as exc:  # noqa: BLE001
        logger.debug("artwork search download failed: url=%s error=%s",
                     screenscraper.redact(url), screenscraper.redact(exc))
        return None, None
    if not data:
        return None, None
    target = Path(dest_dir) / f"candidate-{index:03d}.{ext}"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return target, hashlib.sha1(data).hexdigest()  # nosec B324 - dedup, not security


def search_artwork(
    console,
    rom_name,
    sync_settings,
    art_kind,
    dest_dir,
    rom_path=None,
    on_result=None,
    should_cancel=None,
):
    """Download every distinct candidate image into ``dest_dir``.

    Returns the list of :class:`ArtworkCandidate`. ``on_result`` fires per
    candidate as it lands (worker thread!), so the UI can fill in as results
    arrive instead of waiting for the tail of 404s.
    """
    pairs = provider_candidates(console, rom_name, sync_settings, art_kind, rom_path=rom_path)
    results = []
    seen_digests = set()
    per_provider = {}
    for index, (provider, url) in enumerate(pairs):
        if should_cancel and should_cancel():
            break
        if per_provider.get(provider, 0) >= MAX_RESULTS_PER_PROVIDER:
            continue
        path, digest = _download(url, dest_dir, index)
        if path is None or digest in seen_digests:
            continue
        seen_digests.add(digest)
        per_provider[provider] = per_provider.get(provider, 0) + 1
        candidate = ArtworkCandidate(path, provider, url)
        results.append(candidate)
        if on_result:
            on_result(candidate)
    logger.info(
        "artwork search done: console=%s rom=%s kind=%s tried=%d found=%d",
        console, rom_name, art_kind, len(pairs), len(results),
    )
    return results


def search_artwork_async(on_done=None, **kwargs):
    """Run :func:`search_artwork` on a background thread."""

    def _worker():
        results = search_artwork(**kwargs)
        if on_done:
            on_done(results)

    Thread(target=_worker, daemon=True).start()
