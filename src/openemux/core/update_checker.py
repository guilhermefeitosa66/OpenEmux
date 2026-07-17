"""
Checks GitHub for a newer OpenEmux release.

Pure core logic: the check runs on a worker thread and reports back through a
callback, which fires on that worker thread. Marshalling to the GTK main loop is
the UI layer's job, same as openemux.core.cover_sync.
"""

import json
import logging
import re
import urllib.error
import urllib.request
from threading import Thread

logger = logging.getLogger(__name__)

DEFAULT_API_URL = "https://api.github.com/repos/guilhermefeitosa66/OpenEmux/releases/latest"
DEFAULT_DOWNLOAD_URL = "https://github.com/guilhermefeitosa66/OpenEmux/releases/latest"
DEFAULT_TIMEOUT = 10

_VERSION_RE = re.compile(r"(\d+(?:\.\d+)*)")


def parse_version(value):
    """Turn "v1.2.3" / "1.2.3" / "OpenEmux 1.2" into a comparable tuple."""
    match = _VERSION_RE.search(str(value or ""))
    if not match:
        return None
    return tuple(int(part) for part in match.group(1).split("."))


def is_newer(candidate, current):
    """True when `candidate` is a strictly newer version than `current`."""
    new = parse_version(candidate)
    old = parse_version(current)
    if new is None or old is None:
        return False
    # Pad so 1.2 and 1.2.0 compare equal instead of by length.
    size = max(len(new), len(old))
    new += (0,) * (size - len(new))
    old += (0,) * (size - len(old))
    return new > old


def fetch_latest_release(api_url=DEFAULT_API_URL, timeout=DEFAULT_TIMEOUT):
    """
    Read the latest release from the GitHub API.

    Returns {"version": str, "url": str} or None when the check cannot be made.
    GitHub excludes drafts and pre-releases from this endpoint, so whatever it
    returns is a real release.
    """
    request = urllib.request.Request(
        api_url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "OpenEmux",
        },
    )
    try:
        # Fixed https endpoint from config, not user input.
        with urllib.request.urlopen(request, timeout=timeout) as resp:  # nosec B310
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        logger.info("update check failed: %s", exc)
        return None

    version = payload.get("tag_name") or payload.get("name")
    if not version:
        return None
    return {"version": str(version), "url": payload.get("html_url") or DEFAULT_DOWNLOAD_URL}


def check_for_update(current_version, api_url=DEFAULT_API_URL, timeout=DEFAULT_TIMEOUT):
    """
    Returns {"version", "url"} when a newer release exists, otherwise None.

    Never raises: a failed check (offline, rate limited, API change) is simply
    "no update to report", since this runs unattended on every startup.
    """
    release = fetch_latest_release(api_url=api_url, timeout=timeout)
    if not release:
        return None
    if not is_newer(release["version"], current_version):
        logger.info(
            "update check: up to date (current=%s latest=%s)", current_version, release["version"]
        )
        return None
    logger.info(
        "update check: newer release available (current=%s latest=%s)",
        current_version,
        release["version"],
    )
    return release


def check_for_update_async(
    current_version, on_done, api_url=DEFAULT_API_URL, timeout=DEFAULT_TIMEOUT
):
    """Run check_for_update on a daemon thread; on_done fires on that thread."""

    def _worker():
        result = None
        try:
            result = check_for_update(current_version, api_url=api_url, timeout=timeout)
        except Exception as exc:  # never let a startup check break the app
            logger.info("update check crashed: %s", exc)
        if on_done:
            on_done(result)

    Thread(target=_worker, daemon=True).start()
