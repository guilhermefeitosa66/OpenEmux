"""Read a finished RetroArch log to say why a launch died (issue #226).

A game that exits within a second or two never got as far as running, and
the reason is in RetroArch's log and nowhere else. This reads it back for the
toast -- and recognizes the one failure the launcher can do something about,
an AppImage that cannot mount itself (issue #248).

(It also used to tell the game window which display server RetroArch had
taken; that window is gone, issue #469.)
"""

import logging
import re

logger = logging.getLogger(__name__)

# -- why a launch died (issue #226) ---------------------------------------
#
# A game that exits within a second or two with a nonzero code never got as
# far as running. The reason is in the log and nowhere else, and the app used
# to answer with "finished (exit code 1)" -- indistinguishable from a clean
# quit -- so the user had no way to find out why.

#: How much of a *finished* log is read from the end. A failed launch says
#: what went wrong in its last handful of lines.
TAIL_LIMIT_BYTES = 8192

#: The AppImage runtime failing to mount itself, in every wording it uses:
#: the loader cannot find libfuse2, fusermount is missing or not setuid, or
#: the kernel has no /dev/fuse. All the same class of failure, and all fixed
#: by unpacking the image instead of mounting it (issue #248).
FUSE_FAILURE_RE = re.compile(
    r"libfuse\.so\.2"
    r"|AppImages require FUSE to run"
    r"|Cannot mount AppImage"
    r"|fuse: device not found"
    r"|fusermount[3]?: (?:command )?not found",
    re.IGNORECASE,
)

#: Lines the AppImage runtime and the dynamic loader emit that a user needs
#: to see verbatim, matched before the generic error scan so they win.
_FATAL_PATTERNS = (
    (FUSE_FAILURE_RE,
     "The RetroArch AppImage needs FUSE (libfuse2), which this system does not have."),
)

#: Noise that is present in a *healthy* run too, so it can never be the
#: reason a launch failed (see the module docstring for the same trap).
_BENIGN_RE = re.compile(
    r"Failed to connect to Wayland server|udev|Could not open joystick",
    re.IGNORECASE,
)


def failure_reason(text):
    """One line explaining why a launch died, or None if the log does not say.

    A known-fatal signature wins; otherwise the last error-looking line that
    is not part of every healthy run. None means "nothing here worth showing"
    -- better silence than a scary line that is present on a good launch too.
    """
    if not text:
        return None
    for pattern, explanation in _FATAL_PATTERNS:
        if pattern.search(text):
            return explanation

    for line in reversed([line.strip() for line in text.splitlines()]):
        if not line or _BENIGN_RE.search(line):
            continue
        if "[ERROR]" in line or "error" in line.lower() or "not found" in line.lower():
            return line[:200]
    return None


def read_failure_reason(log_path, limit=TAIL_LIMIT_BYTES):
    """:func:`failure_reason` for the tail of a finished launch log.

    Never raises: a log we cannot read simply has no reason to give.
    """
    if not log_path:
        return None
    try:
        with open(log_path, "rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - limit))
            raw = handle.read()
    except OSError as exc:
        logger.debug("launch failure: cannot read RetroArch log %s: %s", log_path, exc)
        return None
    return failure_reason(raw.decode("utf-8", errors="replace"))


def is_fuse_failure(text):
    """Did this launch die because the AppImage runtime could not mount?

    Kept apart from :func:`failure_reason` because the two answer different
    questions: that one produces a sentence for the user, this one decides
    whether the launch is worth retrying unpacked (issue #248).
    """
    return bool(text) and bool(FUSE_FAILURE_RE.search(text))


def read_is_fuse_failure(log_path, limit=TAIL_LIMIT_BYTES):
    """:func:`is_fuse_failure` for the tail of a finished launch log.

    Never raises: a log we cannot read is not a reason to retry.
    """
    if not log_path:
        return False
    try:
        with open(log_path, "rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - limit))
            raw = handle.read()
    except OSError as exc:
        logger.debug("launch failure: cannot read RetroArch log %s: %s", log_path, exc)
        return False
    return is_fuse_failure(raw.decode("utf-8", errors="replace"))
