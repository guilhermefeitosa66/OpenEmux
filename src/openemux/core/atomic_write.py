"""Crash-safe writes for everything the app persists (issue #208).

Every file OpenEmux owns -- ``config.yaml``, the playlists, the collections,
the play history, the input profiles -- used to be written by truncating the
live file and typing into it. A crash, a power loss or a full disk anywhere in
that window left a half-written file behind, and the next start read it as
corrupt and fell back to defaults: the ROM path, the credentials and the
user-curated favorites, gone at once.

The fix is the one ``core/archives.py`` already used for a zip rewrite: build
the new content in a temporary file beside the target, push it all the way to
the disk, and only then rename it into place. ``os.replace`` is atomic on
POSIX, so a reader sees either the whole old file or the whole new one, and an
interrupted write leaves the previous file untouched.
"""

import logging
import os
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

#: What a file gets when it does not exist yet. Matches what ``open(path,
#: "w")`` produced before -- ``tempfile.mkstemp`` opens owner-only, and a
#: config the user's own tooling can no longer read would be a regression.
DEFAULT_FILE_MODE = 0o644


def atomic_write_text(path, text, encoding="utf-8", mode=None, errors=None):
    """Write ``text`` to ``path`` without ever leaving it truncated.

    ``mode`` sets the permissions explicitly (a credential store asks for
    ``0o600``); left out, the file keeps the permissions it already had, and a
    new one gets :data:`DEFAULT_FILE_MODE`. The parent directory is created if
    it is missing, so callers do not each repeat the ``mkdir``.

    Returns the path written. Errors propagate -- the caller decides whether a
    failed save is worth reporting -- and the temporary file is cleaned up on
    the way out, so a failure never litters the directory.
    """
    return _replace_atomically(
        path, lambda handle: handle.write(text), "w", encoding, mode, errors
    )


def _copy_stream(source, handle, chunk_size, on_chunk=None):
    copied = 0
    while True:
        chunk = source.read(chunk_size)
        if not chunk:
            break
        handle.write(chunk)
        copied += len(chunk)
        if on_chunk is not None:
            on_chunk(len(chunk))
    return copied


def _replace_atomically(path, write_body, open_mode, encoding, mode, errors=None):
    """Write through a temporary file and rename it over ``path``."""
    staged = _stage(path, write_body, open_mode, encoding, mode, errors)
    staged.commit(replace=True)
    return staged.path


def _stage(path, write_body, open_mode, encoding, mode, errors=None):
    """Write the content into a temporary file beside ``path``, on the disk."""
    path = Path(path)
    directory = path.parent
    directory.mkdir(parents=True, exist_ok=True)

    if mode is None:
        mode = _existing_mode(path)

    # In the target's own directory, so the rename is a rename and not a
    # cross-filesystem copy -- os.replace is only atomic within one.
    handle_fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(directory)
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(handle_fd, open_mode, encoding=encoding, errors=errors) as handle:
            written = write_body(handle)
            # flush() only reaches the OS; fsync() is what reaches the disk.
            # Without it the rename can land before the content does, and a
            # power loss leaves an intact name over an empty file.
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_path, mode)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
    return StagedFile(path, tmp_path, written if isinstance(written, int) else None)


class StagedFile:
    """A file written in full beside its target, not yet renamed into place.

    The two-phase half of the module, for a caller that must have every file
    of a set on the disk before any of them appears (a game arriving over
    Share nearby, issue #588). ``size`` is the byte count a streamed stage
    copied. Until :meth:`commit`, the content lives under a dotfile name no
    scanner picks up; :meth:`discard` removes it.
    """

    def __init__(self, path, tmp_path, size=None):
        self.path = Path(path)
        self.tmp_path = Path(tmp_path)
        self.size = size
        self.done = False

    def commit(self, replace=True):
        """Rename the content into place.

        ``replace=False`` refuses a target that exists by now, with
        :class:`FileExistsError`: a hard link fails on an existing name, which
        makes the check and the rename one step. A filesystem without hard
        links (FAT, some network mounts) falls back to a check then a rename.
        Either failure removes the temporary file.
        """
        try:
            if replace:
                os.replace(self.tmp_path, self.path)
            else:
                self._commit_new()
        except BaseException:
            self.discard()
            raise
        self.done = True
        _fsync_directory(self.path.parent)
        return self.path

    def _commit_new(self):
        try:
            os.link(self.tmp_path, self.path)
        except FileExistsError:
            raise
        except OSError:
            if os.path.lexists(self.path):
                raise FileExistsError(str(self.path)) from None
            os.replace(self.tmp_path, self.path)
            return
        self.tmp_path.unlink()

    def discard(self):
        """Remove the temporary file; harmless once committed or discarded."""
        if not self.done:
            self.tmp_path.unlink(missing_ok=True)
            self.done = True


def stage_stream(path, source, chunk_size=1024 * 1024, mode=None, on_chunk=None):
    """Copy a binary stream beside ``path`` without renaming it into place.

    ``on_chunk(n)`` is called after each chunk is written, with its size --
    for progress, a running hash or a cancel check. It may raise: the
    temporary file is removed and the exception propagates. Returns a
    :class:`StagedFile` whose ``size`` is the number of bytes copied.
    """
    return _stage(
        path, lambda handle: _copy_stream(source, handle, chunk_size, on_chunk), "wb", None, mode
    )


def atomic_write_bytes(path, data, mode=None):
    """Write ``data`` to ``path`` atomically.

    For content already in memory -- a downloaded cover -- where the final path
    must never hold a partial file (issue #213).
    """
    return _replace_atomically(path, lambda handle: handle.write(data), "wb", None, mode)


def atomic_write_stream(path, source, chunk_size=1024 * 1024, mode=None):
    """Copy a readable binary stream into ``path`` atomically.

    The streaming counterpart of :func:`atomic_write_text`, for content too big
    to hold in memory -- a ROM coming out of an archive. Same guarantee: the
    final path never holds a partial file, so an interrupted extraction cannot
    leave a truncated ROM behind for a later import to mistake for a good one
    (issue #229).
    """
    return _replace_atomically(
        path, lambda handle: _copy_stream(source, handle, chunk_size), "wb", None, mode
    )


def atomic_write_lines(path, lines, encoding="utf-8", errors=None):
    """Write ``lines`` one per line, newline-terminated, atomically.

    The shape every ``.list`` file in the app is written in: favorites,
    console playlists, collections.
    """
    body = "".join(f"{line}\n" for line in lines)
    return atomic_write_text(path, body, encoding=encoding, errors=errors)


def _existing_mode(path):
    try:
        return os.stat(path).st_mode & 0o777
    except OSError:
        return DEFAULT_FILE_MODE


def _fsync_directory(directory):
    """Make the rename itself durable.

    The renamed file's content is on the disk after ``fsync``, but the
    directory entry pointing at it is a separate write. Best-effort: some
    filesystems refuse to open a directory for sync, and a save that worked is
    not worth failing over that.
    """
    try:
        dir_fd = os.open(str(directory), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(dir_fd)
    except OSError as exc:  # pragma: no cover - filesystem dependent
        logger.debug("atomic write: directory not synced: %s (%s)", directory, exc)
    finally:
        os.close(dir_fd)
