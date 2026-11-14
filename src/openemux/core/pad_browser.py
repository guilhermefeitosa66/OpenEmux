"""The folder listing behind Big Picture's pad file browser (issue 957).

GTK's file chooser cannot be driven with a pad, so Big Picture's Import has
a browser of its own, in the Android list style: folders first, then the
files OpenEmux can import, A to enter a folder, B to go up. This module is
the listing; the page draws it.

Pure and widget-free: one test file, the repo's core-module convention.
"""

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


class Entry:
    """One line of the listing: a folder or an importable file."""

    __slots__ = ("path", "name", "is_dir")

    def __init__(self, path, is_dir):
        self.path = Path(path)
        self.name = self.path.name
        self.is_dir = bool(is_dir)

    def __repr__(self):  # pragma: no cover - debugging aid only
        return f"Entry({self.path!s}, is_dir={self.is_dir})"


def _wanted(name, extensions):
    suffix = os.path.splitext(name)[1].lower().lstrip(".")
    return suffix in extensions


def list_dir(path, extensions, show_hidden=False):
    """The folders and the importable files in ``path``, folders first.

    ``extensions`` are the importable suffixes without the dot, any case.
    Hidden entries (a leading dot) are left out unless ``show_hidden``.
    A folder that cannot be read lists as empty; a broken link is skipped.
    """
    extensions = {str(ext).lower().lstrip(".") for ext in extensions or ()}
    folders = []
    files = []
    try:
        scanner = os.scandir(path)
    except OSError as exc:
        logger.debug("pad browser: cannot list %s: %s", path, exc)
        return []
    with scanner:
        for item in scanner:
            if not show_hidden and item.name.startswith("."):
                continue
            try:
                is_dir = item.is_dir()
                is_file = not is_dir and item.is_file()
            except OSError:
                continue
            if is_dir:
                folders.append(Entry(item.path, True))
            elif is_file and _wanted(item.name, extensions):
                files.append(Entry(item.path, False))
    key = lambda entry: entry.name.casefold()  # noqa: E731 - a local shorthand
    return sorted(folders, key=key) + sorted(files, key=key)


def parent(path):
    """The folder above ``path``; ``None`` at the root."""
    path = Path(path)
    above = path.parent
    return None if above == path else above


def start_folder(preferred=None):
    """Where the browser opens: ``preferred`` when it exists, else home."""
    if preferred:
        candidate = Path(preferred).expanduser()
        if candidate.is_dir():
            return candidate
    return Path.home()


__all__ = ["Entry", "list_dir", "parent", "start_folder"]
