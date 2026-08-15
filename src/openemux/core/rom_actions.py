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

from openemux.core import cartridge_render, save_states
from openemux.core.archives import (
    archive_entries,
    is_archive,
    rename_archive_rom_entry,
)
from openemux.core.scraper import SUPPORTED_COVER_EXTS, rename_local_art
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


def _rename_sibling_saves(old_path, new_path, console):
    """Carry the battery saves and other core companions along (#134).

    RetroArch's default ``savefile_directory`` puts the in-game save --
    ``.srm``, ``.rtc`` and whatever else the core invents, including
    multi-dotted shapes like ``.data.szsnes`` -- next to the content file
    under the same stem. Matching on "same stem, not a ROM, not artwork" is
    safer than a fixed extension list. Another ROM sharing the stem
    (``Game.sfc`` next to ``Game.smc``) is its own game and stays put, and
    an existing target is never overwritten.
    """
    rom_extensions = {ext.lower() for ext in get_supported_extensions(console)}
    art_extensions = {f".{ext.lower().lstrip('.')}" for ext in SUPPORTED_COVER_EXTS}
    prefix = f"{old_path.stem}."
    moved = 0
    for sibling in sorted(old_path.parent.iterdir()):
        if not sibling.is_file() or sibling == old_path or sibling == new_path:
            continue
        if not sibling.name.startswith(prefix):
            continue
        suffix = sibling.suffix.lower()
        if suffix in rom_extensions or suffix in art_extensions:
            continue
        remainder = sibling.name[len(old_path.stem):]
        target = new_path.with_name(f"{new_path.stem}{remainder}")
        if target.exists():
            logger.warning(
                "rom_actions sibling save skipped, target exists: %s -> %s",
                sibling, target,
            )
            continue
        try:
            sibling.rename(target)
            moved += 1
        except OSError as exc:
            logger.warning(
                "rom_actions sibling save rename failed: path=%s error=%s", sibling, exc
            )
    if moved:
        logger.info(
            "rom_actions sibling saves renamed: old=%s new=%s files=%d",
            old_path.stem, new_path.stem, moved,
        )
    return moved


def rename_rom(roms_dir, rom, new_name, cache_dir=None, states_dir=None):
    """Rename a ROM and everything keyed on its name.

    The file keeps its extension; artwork, the cartridge composite, the
    save states under ``states_dir`` and the battery saves next to the file
    follow the new name (#134). Returns the updated rom dict (a copy) so
    the caller can re-index it.

    For an archive holding several ROMs the *display name* cannot change --
    the card is named after the entry inside, which stays as it is -- so
    everything keyed on the display name deliberately stays put; only the
    container file and its stem-keyed companions move.
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
    # renaming only the container would leave the card unchanged. With
    # several entries there is no single card to follow: the display name
    # keeps the inner entry's name (#134).
    display_name = new_name
    if is_archive(old_path):
        extensions = get_supported_extensions(console)
        if len(archive_entries(old_path, extensions)) == 1:
            rename_archive_rom_entry(old_path, new_name, extensions)
        else:
            display_name = old_name

    if new_path != old_path:
        old_path.rename(new_path)
        _rename_sibling_saves(old_path, new_path, console)
        if states_dir is not None:
            # States are keyed on the content file stem (#73), so they move
            # with the file, not with the display name.
            save_states.rename_states(states_dir, old_path.stem, new_path.stem)

    if display_name != old_name:
        rename_local_art(roms_dir, console, old_name, display_name)
        cartridge_render.drop_cached(console, old_name, cache_dir)

    logger.info(
        "rom_actions renamed: console=%s old=%s new=%s display=%s path=%s",
        console,
        old_name,
        new_name,
        display_name,
        new_path,
    )
    renamed = dict(rom)
    renamed["name"] = display_name
    renamed["path"] = str(new_path)
    return renamed
