"""Walking a library tree that has symlinked directories in it.

``Path.rglob("*")`` does not descend into a symlinked directory: the link
itself is yielded, ``is_file()`` is false for it, and everything underneath is
skipped in silence. That makes the standard "big files live on another disk,
symlink them in" layout invisible -- ``~/games/roms/PS/discs ->
/mnt/storage/ps1`` scanned as empty, with no error and nothing in the log
(issue #228).

``walk_files`` follows them, and guards the loops that following implies with
a visited-inode set: a link pointing at one of its own ancestors is otherwise
an infinite descent.
"""

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def walk_files(root, follow_symlinks=True):
    """Yield every file under ``root`` as a :class:`~pathlib.Path`.

    Descends into symlinked directories, which is the whole point, and visits
    each real directory at most once so a link back up the tree cannot loop.
    Unreadable directories are skipped rather than raised: a library is a
    user's directory tree, and one folder with the wrong permissions must not
    take a whole scan down.
    """
    root = Path(root)
    visited = set()

    def _on_error(exc):
        logger.debug("walk: skipping unreadable directory: %s", exc)

    for dirpath, dirnames, filenames in os.walk(
        root, followlinks=follow_symlinks, onerror=_on_error
    ):
        if follow_symlinks:
            # Identity is (device, inode), not the path: two paths reaching the
            # same directory through different links are the same directory,
            # and a link pointing at an ancestor would otherwise descend
            # forever. Pruning dirnames in place is what os.walk() honours.
            key = _identity(dirpath)
            if key is not None:
                if key in visited:
                    dirnames[:] = []
                    continue
                visited.add(key)
            kept = []
            for name in dirnames:
                child = _identity(os.path.join(dirpath, name))
                if child is not None and child in visited:
                    continue
                kept.append(name)
            dirnames[:] = kept

        base = Path(dirpath)
        for name in filenames:
            yield base / name


def _identity(path):
    """``(device, inode)`` for a directory, or ``None`` if it cannot be read."""
    try:
        info = os.stat(path)
    except OSError:
        return None
    return (info.st_dev, info.st_ino)


def relative_to_base(path, base):
    """``path`` relative to ``base``, seeing through symlinks only if it must.

    The literal comparison comes first. Resolving both sides rewrites a path
    that goes *through* a symlinked directory to its physical location, and a
    console directory that is itself a link then lands outside the library
    root -- so ``~/games/roms/SFC -> /mnt/storage/snes`` made every ROM under
    it unattributable to a console (issue #228). Favourites stored fine and
    never appeared.

    Returns ``None`` when ``path`` is genuinely not under ``base``.
    """
    path = Path(path)
    base = Path(base)
    try:
        return path.relative_to(base)
    except ValueError:
        pass
    try:
        return path.resolve().relative_to(base.resolve())
    except (ValueError, OSError):
        return None
