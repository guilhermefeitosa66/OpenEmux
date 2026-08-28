"""Startup sweep of the directories the app writes to and never reads back.

Four places grew without bound (issue #221): one set of files per game launch
under ``~/.openemux/runtime``, the buildbot's download cache, the startup log,
and one temp directory per artwork-manager session under
``~/.cache/openemux``. None of them is ever read by the app after the run that
wrote it -- they exist for a human looking at a problem -- so the fix is a
retention policy rather than not writing them.

The startup log is handled where it is opened (``startup_logging``, a rotating
handler); everything else is swept here, once, from ``do_activate``.

Every function is best-effort by design: housekeeping runs before the window
is drawn, and a permission error or a directory that vanished mid-scan must
never be the reason the app fails to start.
"""

import logging
import re
import shutil
import time
from pathlib import Path

from openemux.core.artwork_search import artwork_temp_root as default_artwork_temp_root

logger = logging.getLogger(__name__)

#: How long a per-launch runtime file is worth keeping. Long enough that "it
#: crashed yesterday, can you look?" still has the log; short enough that a
#: daily player does not accumulate a year of verbose RetroArch dumps.
RUNTIME_MAX_AGE_DAYS = 7

#: ...and a floor under that, so the most recent launches survive the age rule
#: even on a machine whose clock is wrong or that is used once a month. Counted
#: in launches, not files: a launch writes up to four files sharing a
#: timestamp, and they are only useful together.
RUNTIME_KEEP_LAUNCHES = 20

#: An artwork-manager temp directory belongs to an open window. Anything this
#: old is from a session that ended -- normally *or* by a crash, which is the
#: case that leaked (the window's close handler is what removes it).
ARTWORK_TEMP_MAX_AGE_HOURS = 24

#: The per-launch files, keyed by the timestamp they share. Written by
#: ``RetroArchLauncher``: ``runtime_<console>_<ts>.cfg``,
#: ``coreopts_<console>_<ts>.cfg``, ``retroarch_<console>_<ts>.log`` and
#: ``retroarch_<console>_<ts>.cmd``. ``input_<console>_<ts>.cfg`` is the same
#: shape from an older launcher: nothing writes those any more, so a library
#: that predates the merge into the runtime override still has a pile of them.
_RUNTIME_FILE_PATTERN = re.compile(
    r"^(?:runtime|coreopts|input)_[a-z0-9_-]+_(\d{14})\.cfg$"
    r"|^retroarch_[a-z0-9_-]+_(\d{14})\.(?:log|cmd)$",
    re.IGNORECASE,
)


def _launch_key(name):
    """The launch timestamp a runtime filename carries, or ``None``."""
    match = _RUNTIME_FILE_PATTERN.match(name)
    if match is None:
        return None
    return match.group(1) or match.group(2)


def _unlink(path):
    try:
        path.unlink()
        return True
    except OSError as exc:
        logger.debug("housekeeping could not remove file: path=%s error=%s", path, exc)
        return False


def prune_runtime_files(
    runtime_dir,
    max_age_days=RUNTIME_MAX_AGE_DAYS,
    keep_launches=RUNTIME_KEEP_LAUNCHES,
    now=None,
):
    """Drop per-launch runtime files, keeping the recent ones.

    A file survives if its launch is one of the newest ``keep_launches`` *or*
    it is younger than ``max_age_days``. Grouping by launch first is what keeps
    a kept ``.log`` from losing the ``.cmd`` that says how it was produced.

    Returns the number of files removed. Only files this app writes are
    considered -- ``openemux_startup.log``, the buildbot cache and the shader
    directories live in the same place and are none of this function's
    business.
    """
    runtime_dir = Path(runtime_dir)
    try:
        entries = list(runtime_dir.iterdir())
    except OSError:
        return 0

    launches = {}
    for entry in entries:
        key = _launch_key(entry.name)
        if key is None:
            continue
        launches.setdefault(key, []).append(entry)

    if not launches:
        return 0

    cutoff = (now if now is not None else time.time()) - max_age_days * 86400
    # Newest first, by the timestamp in the name: zero-padded and fixed width,
    # so lexicographic order is chronological order, and mtime cannot be
    # trusted on files a backup tool may have touched.
    stale = sorted(launches, reverse=True)[keep_launches:]

    removed = 0
    for key in stale:
        for path in launches[key]:
            try:
                if path.stat().st_mtime >= cutoff:
                    continue
            except OSError:
                continue
            if _unlink(path):
                removed += 1

    if removed:
        logger.info(
            "housekeeping pruned runtime files: removed=%d kept_launches=%d dir=%s",
            removed,
            len(launches) - len(stale),
            runtime_dir,
        )
    return removed


def prune_buildbot_cache(cache_dir):
    """Empty the buildbot download cache.

    Nothing reads it: every download writes its archive here, extracts it and
    moves on, and the next run downloads again rather than looking. Hundreds of
    megabytes after a full core download, and the same again after each update.
    Cores are downloaded on a worker thread during bootstrap, so this only ever
    runs at startup, with no download in flight.
    """
    cache_dir = Path(cache_dir)
    try:
        entries = list(cache_dir.iterdir())
    except OSError:
        return 0

    removed = 0
    for entry in entries:
        if entry.is_dir():
            continue
        if _unlink(entry):
            removed += 1

    if removed:
        logger.info(
            "housekeeping emptied buildbot cache: removed=%d dir=%s", removed, cache_dir
        )
    return removed


def sweep_artwork_temp_dirs(
    artwork_temp_root, max_age_hours=ARTWORK_TEMP_MAX_AGE_HOURS, now=None
):
    """Remove artwork-manager session directories left behind by dead sessions.

    ``ArtworkManagerWindow`` creates one per session and removes it on
    ``close-request``, which covers the window being closed and nothing else: a
    crash, a quit with the window open, or a download that finishes after the
    rmtree (``artwork_search`` re-creates the directory it writes into) all
    leave one behind for good.

    The age guard is what makes this safe to run while another OpenEmux
    instance has its own artwork window open.
    """
    root = Path(artwork_temp_root)
    try:
        entries = list(root.iterdir())
    except OSError:
        return 0

    cutoff = (now if now is not None else time.time()) - max_age_hours * 3600
    removed = 0
    for entry in entries:
        if not entry.is_dir():
            continue
        try:
            if entry.stat().st_mtime >= cutoff:
                continue
        except OSError:
            continue
        try:
            shutil.rmtree(entry)
            removed += 1
        except OSError as exc:
            logger.debug(
                "housekeeping could not remove artwork temp dir: path=%s error=%s",
                entry,
                exc,
            )

    if removed:
        logger.info(
            "housekeeping swept artwork temp dirs: removed=%d root=%s", removed, root
        )
    return removed


def run_startup_housekeeping(config_manager, artwork_temp_root=None):
    """Run every sweep, and never let one of them stop the app from starting."""
    summary = {"runtime_files": 0, "buildbot_cache": 0, "artwork_temp_dirs": 0}
    try:
        runtime_dir = Path(config_manager.get_runtime_dir())
        summary["runtime_files"] = prune_runtime_files(runtime_dir)
        summary["buildbot_cache"] = prune_buildbot_cache(runtime_dir / "buildbot_cache")
        summary["artwork_temp_dirs"] = sweep_artwork_temp_dirs(
            artwork_temp_root
            if artwork_temp_root is not None
            else default_artwork_temp_root()
        )
    except Exception:  # noqa: BLE001 - startup must survive anything here
        logger.exception("housekeeping failed")
    return summary
