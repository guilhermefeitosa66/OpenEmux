"""
Destructive, file-level operations on a ROM: send to trash, rename.

Neither is just a file operation. A ROM's *display name* is the key for its
cover art, its cartridge composite and the playlists that index it, so renaming
or removing the file has to carry those along or the library ends up pointing
at names that no longer exist. That bookkeeping lives here, widget-free, so it
can be tested without a display.

Playlists are not touched from here: they belong to PlaylistManager, which the
UI already owns, and it is called right after these.
"""

import logging
from pathlib import Path

import gi

from gi.repository import Gio, GLib

from openemux.core import cartridge_render
from openemux.core.archives import (
    archive_entries,
    is_archive,
    rename_archive_rom_entry,
)
from openemux.core.scraper import rename_local_art
from openemux.core.systems import get_supported_extensions

logger = logging.getLogger(__name__)

# Characters that cannot appear in a file name, plus the two names that would
# escape the ROM's own folder.
_FORBIDDEN = ("/", "\\", "\0")
_RESERVED = (".", "..")


class RomActionError(RuntimeError):
    """A rename or delete could not be carried out."""


def sanitize_rom_name(name):
    """Validate a user-typed ROM name, or raise RomActionError."""
    cleaned = (name or "").strip()
    if not cleaned:
        raise RomActionError("empty name")
    if cleaned in _RESERVED or any(char in cleaned for char in _FORBIDDEN):
        raise RomActionError(f"invalid name: {name!r}")
    return cleaned


def _gio_trash(path):
    """Move a path to the desktop trash. False when the volume has none."""
    try:
        return bool(Gio.File.new_for_path(str(path)).trash(None))
    except GLib.Error as exc:
        logger.warning("rom_actions trash failed: path=%s error=%s", path, exc)
        return False


def delete_rom(roms_dir, rom, trash=_gio_trash, cache_dir=None):
    """Send a ROM to the trash and drop what was rendered from it.

    The cover art is deliberately left alone: it is the user's own file when it
    was picked by hand, and it costs nothing to keep. The cartridge composite
    *is* dropped, since it is a derived file that would otherwise linger for a
    ROM that no longer exists.
    """
    path = Path(rom["path"])
    if not path.exists():
        raise RomActionError(f"{path} is no longer on disk")
    if not trash(path):
        raise RomActionError(f"{path} could not be moved to the trash")

    cartridge_render.drop_cached(rom["console"], rom["name"], cache_dir)
    logger.info("rom_actions trashed: console=%s rom=%s path=%s", rom["console"], rom["name"], path)
    return True


def rename_rom(roms_dir, rom, new_name, cache_dir=None):
    """Rename a ROM and everything keyed on its name.

    The file keeps its extension; artwork and the cartridge composite follow
    the new name. Returns the updated rom dict (a copy) so the caller can
    re-index it.
    """
    new_name = sanitize_rom_name(new_name)
    console = rom["console"]
    old_name = rom["name"]
    old_path = Path(rom["path"])
    if not old_path.exists():
        raise RomActionError(f"{old_path} is no longer on disk")

    new_path = old_path.with_name(f"{new_name}{old_path.suffix}")
    if new_path != old_path and new_path.exists():
        raise RomActionError(f"{new_path.name} already exists")

    # An archive shows the name of the ROM *inside* it, not its own, so
    # renaming only the container would leave the card unchanged.
    if is_archive(old_path):
        extensions = get_supported_extensions(console)
        if len(archive_entries(old_path, extensions)) == 1:
            rename_archive_rom_entry(old_path, new_name, extensions)

    if new_path != old_path:
        old_path.rename(new_path)

    if new_name != old_name:
        rename_local_art(roms_dir, console, old_name, new_name)
        cartridge_render.drop_cached(console, old_name, cache_dir)

    logger.info(
        "rom_actions renamed: console=%s old=%s new=%s path=%s",
        console,
        old_name,
        new_name,
        new_path,
    )
    renamed = dict(rom)
    renamed["name"] = new_name
    renamed["path"] = str(new_path)
    return renamed
