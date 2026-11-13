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
import stat as stat_module
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


def walk_entries(root, follow_symlinks=True):
    """Yield ``(path, stat)`` for every file under ``root``, one stat each.

    The same walk as :func:`walk_files`, with the one ``stat`` a scan needs
    anyway -- the file's size and times go into the playlist index (issue
    901) -- taken here from the directory entry, so the scanner never asks
    ``is_file()`` and then stats again. A link pointing nowhere yields
    ``None`` for its stat, which is how the caller knows it is not a game.
    """
    for dirpath, dirnames, filenames, entries in _walk_with_entries(root, follow_symlinks):
        base = Path(dirpath)
        for name in filenames:
            entry = entries.get(name)
            info = None
            try:
                info = entry.stat(follow_symlinks=follow_symlinks) if entry is not None else None
            except OSError:
                info = None
            if info is not None and not stat_module.S_ISREG(info.st_mode):
                info = None
            yield base / name, info


def _walk_with_entries(root, follow_symlinks):
    """``os.walk`` with the directory entries of each level kept at hand.

    ``os.walk`` throws its ``DirEntry`` objects away after splitting them
    into names, and the stat each of them can answer with it. This walks the
    tree the same way (same visited-inode guard, same unreadable-directory
    skip) and keeps them, so the caller stats each file once.
    """
    root = Path(root)
    visited = set()
    stack = [os.fspath(root)]
    while stack:
        dirpath = stack.pop()
        try:
            with os.scandir(dirpath) as scan:
                listed = list(scan)
        except OSError as exc:
            logger.debug("walk: skipping unreadable directory: %s", exc)
            continue
        if follow_symlinks:
            key = _identity(dirpath)
            if key is not None:
                if key in visited:
                    continue
                visited.add(key)
        dirnames, filenames, entries = [], [], {}
        for entry in listed:
            try:
                is_dir = entry.is_dir(follow_symlinks=follow_symlinks)
            except OSError:
                is_dir = False
            if is_dir:
                if follow_symlinks:
                    child = _identity(entry.path)
                    if child is not None and child in visited:
                        continue
                dirnames.append(entry.name)
            else:
                filenames.append(entry.name)
                entries[entry.name] = entry
        dirnames.sort()
        filenames.sort()
        yield dirpath, dirnames, filenames, entries
        # Depth first, in name order: pushed reversed so the stack pops a-z.
        for name in reversed(dirnames):
            stack.append(os.path.join(dirpath, name))


def directory_stamps(root, follow_symlinks=True):
    """``{relative dir: mtime_ns}`` for ``root`` and every directory under it.

    A directory's mtime moves when a file is added to it, removed from it or
    renamed in it, so this is the fingerprint the start-up scan compares to
    decide whether a console's tree changed since the playlist was built
    (issue 901): a listing of the directories, no stat of the files.
    """
    root = Path(root)
    stamps = {}
    for dirpath, _dirnames, _filenames, _entries in _walk_with_entries(root, follow_symlinks):
        try:
            mtime = os.stat(dirpath).st_mtime_ns
        except OSError:
            continue
        relative = os.path.relpath(dirpath, root)
        stamps["." if relative == os.curdir else relative] = mtime
    return stamps


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
