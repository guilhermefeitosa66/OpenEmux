"""Keep a corrupt state file instead of destroying it (issue #209).

Every store in the app used to treat an unreadable file as "no file": load
defaults, and then write those defaults straight back over the broken one. The
recovery path destroyed the user's data, not the original problem -- one
truncated write or one hand-edit typo, and the settings, the collection names
or a console's whole binding set were gone with nothing on screen to say so.

So a store that cannot read its file calls :func:`quarantine_state_file`
first. The unreadable file is renamed to ``<name>.broken-<timestamp>`` -- it is
still there, it can still be opened in an editor, and whatever survived in it
can be typed back -- the failure is logged at error level, and the file is
recorded so the window can tell the user on startup rather than leaving them
with an app that quietly forgot everything.
"""

import logging
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)

#: What a quarantined file is called: ``config.yaml.broken-20260825-181230``.
#: The original name stays in front so the file sorts next to the live one and
#: a user scanning the directory can see what it was.
BROKEN_SUFFIX = "broken"

_lock = threading.Lock()
_quarantined = []


def quarantine_state_file(path, error, clock=time.time):
    """Move an unreadable state file aside; returns the new path, or None.

    Returning None means the file could not be moved (already gone, a
    read-only directory). Callers fall back to defaults either way -- the
    point of this function is that they do not do so *over* the user's data.
    """
    path = Path(path)
    if not path.exists():
        return None

    target = _free_name(path, clock)
    try:
        path.rename(target)
    except OSError as exc:  # pragma: no cover - filesystem dependent
        logger.error(
            "unreadable state file could not be set aside: path=%s error=%s (%s)",
            path,
            error,
            exc,
        )
        return None

    logger.error(
        "unreadable state file set aside: path=%s kept_as=%s error=%s",
        path,
        target,
        error,
    )
    with _lock:
        _quarantined.append({"original": path, "kept_as": target, "error": str(error)})
    return target


def quarantined_files():
    """What was set aside since the process started, oldest first."""
    with _lock:
        return list(_quarantined)


def reset_quarantine_log():
    """Forget the session's record. For tests, and for the UI once it has
    reported what happened."""
    with _lock:
        _quarantined.clear()


def _free_name(path, clock):
    """``<name>.broken-<stamp>``, with a counter if that already exists.

    Two failures inside the same second must not have the second one silently
    overwrite the first -- the whole point is that nothing is destroyed.
    """
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(clock()))
    base = path.with_name(f"{path.name}.{BROKEN_SUFFIX}-{stamp}")
    if not base.exists():
        return base
    for index in range(1, 1000):
        candidate = path.with_name(f"{base.name}.{index}")
        if not candidate.exists():
            return candidate
    return path.with_name(f"{base.name}.{int(clock() * 1000)}")
