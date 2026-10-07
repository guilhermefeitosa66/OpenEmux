"""Name the game in RetroArch's window title (issue #469).

RetroArch's own window is what the user plays in, and
its title is RetroArch's: ``RetroArch Snes9x 1.63 fae2fea`` -- the core and
its version, the trailing hash being a git commit. There is no setting for
it, so OpenEmux retitles the window over X11 once it appears, and keeps
watching: RetroArch writes its title again when the video driver restarts
(a fullscreen toggle does that).

X11 only, like everything that touches another client's window. On a native
Wayland RetroArch there is no way in, and the title stays RetroArch's.
"""

import logging
import re
import threading
import time
from pathlib import Path

from openemux.core import cores
from openemux.core.x11_windows import XLIB_AVAILABLE, RetroArchWindows

logger = logging.getLogger(__name__)

#: How long the window gets to appear (a slow first core load included), and
#: how often the title is checked while the game runs.
FIND_TIMEOUT_SECONDS = 30.0
FIND_INTERVAL_SECONDS = 0.25
WATCH_INTERVAL_SECONDS = 1.0

_TAGS = re.compile(r"\s*[\(\[][^\)\]]*[\)\]]")


def game_title(rom_path):
    """The ROM's name without its extension or No-Intro style tags."""
    stem = Path(rom_path).stem
    cleaned = _TAGS.sub("", stem).strip()
    return cleaned or stem


def core_name(core_path):
    """The core's display name, from its ``.info`` file when there is one."""
    path = Path(core_path)
    # Through the module, not a from-import: the name is looked up per call.
    info = cores.parse_core_info(path.with_suffix(".info"))
    return info.get("corename") or cores.humanize_core_filename(path.name)


def compose(rom_path, core_path):
    return f"{game_title(rom_path)} — {core_name(core_path)} · RetroArch"


def keep_title(proc, title, embedder_factory=RetroArchWindows, sleep=time.sleep):
    """Retitle the game's window and keep it that way until the game exits.

    Runs on its own daemon thread (see ``start``); returns when the process
    ends or the window never shows up.
    """
    embedder = embedder_factory()
    try:
        # Taken before RetroArch has had time to map a window, so the WM_CLASS
        # fallback can never mistake a RetroArch the user already had open for
        # this launch's.
        embedder.snapshot_existing()
        xid = None
        waited = 0.0
        while xid is None and proc.poll() is None and waited < FIND_TIMEOUT_SECONDS:
            xid = embedder.find_game_window(proc.pid)
            if xid is None:
                sleep(FIND_INTERVAL_SECONDS)
                waited += FIND_INTERVAL_SECONDS
        if xid is None:
            logger.info("window title: no RetroArch window found for pid %s", proc.pid)
            return
        while proc.poll() is None:
            # Looked up again every time: a fullscreen toggle destroys the
            # window and opens a new one, with RetroArch's title on it.
            xid = embedder.find_game_window(proc.pid) or xid
            # Only the EWMH name is watched. RetroArch rewrites its legacy
            # WM_NAME several times a second and leaves _NET_WM_NAME alone;
            # every current window manager shows the latter, and fighting
            # over the former would only make the title flicker.
            if embedder.window_title(xid) != title:
                embedder.set_window_title(xid, title)
            sleep(WATCH_INTERVAL_SECONDS)
    finally:
        embedder.close()


def start(proc, rom_path, core_path):
    """Start keeping the title for this launch, where X11 allows it."""
    if not XLIB_AVAILABLE or not core_path:
        return None
    title = compose(rom_path, core_path)
    thread = threading.Thread(
        target=keep_title, args=(proc, title), name="openemux-window-title", daemon=True
    )
    thread.start()
    return thread
