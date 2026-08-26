"""Read a running RetroArch's log to learn which display server it took.

The game window adopts RetroArch's toplevel with ``XReparentWindow``, which
only works between two X clients. When RetroArch comes up on Wayland instead
there is no X window to find, and the wrapper used to sit on a black screen
for twenty seconds before giving up without a word (issue #267). RetroArch
says which backend it chose as soon as it initializes video, so the answer is
usually there within a second or two of the game starting.

The trap this module exists to avoid: a **successful** X11 run also logs

    [ERROR] [Wayland]: Failed to connect to Wayland server.
    [INFO] [GL] Found GL context: "x".

because RetroArch probes wayland first and falls back on its own. Searching
the log for "wayland" would therefore abandon a perfectly good embed. Only
the quoted names in RetroArch's own "Found ..." lines are trusted, and
anything unrecognized stays :data:`UNKNOWN` rather than guessing.
"""

import logging
import re

logger = logging.getLogger(__name__)

#: Verdicts. ``UNKNOWN`` means "the log has not said yet" -- the caller waits.
X11 = "x11"
NOT_X11 = "not-x11"
UNKNOWN = None

#: How much of the log is read. The lines we want are among RetroArch's first
#: few hundred; the file itself grows without bound while the game runs.
READ_LIMIT_BYTES = 65536

#: ``[INFO] [Video]: Found display server: "x11".``
_DISPLAY_SERVER_RE = re.compile(r'Found display server:\s*"([^"]*)"')
#: ``[INFO] [GL] Found GL context: "x".``
_GL_CONTEXT_RE = re.compile(r'Found GL context:\s*"([^"]*)"')

#: Display-server names that mean "an X client we can reparent". XWayland
#: reports itself as x11 too, which is exactly what we want.
_X11_DISPLAY_SERVERS = {"x11", "x"}
#: ...and the ones that mean we can never adopt this window.
_NON_X11_DISPLAY_SERVERS = {"wayland", "kms", "drm", "null", "gdi", "win32"}

#: Context-driver idents. RetroArch's X11 contexts are "x" (GLX/Vulkan) and
#: "x-egl"; "x11" is *not* a registered ident despite reading like one.
_X11_CONTEXTS = {"x", "x-egl", "x_egl", "xegl"}
_NON_X11_CONTEXTS = {"wayland", "kms", "drm", "khr_display", "vk_display", "gdi", "null"}


def verdict(text):
    """Is the RetroArch that wrote ``text`` an X client? Tri-state.

    Returns :data:`X11`, :data:`NOT_X11`, or :data:`UNKNOWN` when the log has
    not reached the point of saying. The display-server line wins over the GL
    context line when both are present; an unrecognized name is not an
    answer, so a future RetroArch naming something new degrades to waiting
    rather than to a wrong abort.
    """
    if not text:
        return UNKNOWN
    for pattern, x11_names, other_names in (
        (_DISPLAY_SERVER_RE, _X11_DISPLAY_SERVERS, _NON_X11_DISPLAY_SERVERS),
        (_GL_CONTEXT_RE, _X11_CONTEXTS, _NON_X11_CONTEXTS),
    ):
        for match in pattern.finditer(text):
            name = (match.group(1) or "").strip().lower()
            if name in x11_names:
                return X11
            if name in other_names:
                return NOT_X11
    return UNKNOWN


def read_verdict(log_path, limit=READ_LIMIT_BYTES):
    """:func:`verdict` for a log file, read safely while it is being written.

    A bounded binary read decoded with ``errors="replace"``: the file is open
    in another process and the last line is routinely half-written. Never
    raises -- a log we cannot read is simply :data:`UNKNOWN`.
    """
    if not log_path:
        return UNKNOWN
    try:
        with open(log_path, "rb") as handle:
            raw = handle.read(limit)
    except OSError as exc:
        logger.debug("game window: cannot read RetroArch log %s: %s", log_path, exc)
        return UNKNOWN
    return verdict(raw.decode("utf-8", errors="replace"))


def should_abandon(current_verdict, ticks_waited, ceiling_ticks):
    """Whether the wrapper should stop waiting for a window to adopt.

    Two ways to give up: RetroArch has said it is not an X client (act at
    once -- no window will ever appear), or the search budget ran out. Kept
    here beside the parser so the tick policy is assertable without GTK.
    """
    if current_verdict == NOT_X11:
        return True
    return ticks_waited > ceiling_ticks


# -- why a launch died (issue #226) ---------------------------------------
#
# A game that exits within a second or two with a nonzero code never got as
# far as running. The reason is in the log and nowhere else, and the app used
# to answer with "finished (exit code 1)" -- indistinguishable from a clean
# quit -- so the user had no way to find out why.

#: How much of a *finished* log is read from the end. A failed launch says
#: what went wrong in its last handful of lines.
TAIL_LIMIT_BYTES = 8192

#: Lines the AppImage runtime and the dynamic loader emit that a user needs
#: to see verbatim, matched before the generic error scan so they win.
_FATAL_PATTERNS = (
    (re.compile(r"libfuse\.so\.2", re.IGNORECASE),
     "The RetroArch AppImage needs libfuse2, which this system does not have."),
    (re.compile(r"AppImages require FUSE to run", re.IGNORECASE),
     "The RetroArch AppImage needs libfuse2, which this system does not have."),
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
