"""The console artwork the sidebar, the dropdowns and the settings all show.

One console id maps to one icon everywhere in the UI: the sidebar row, the
console dropdown in the scan/sync/import prompts, and six rows in the
preferences dialog. That factory lived on `OpenEmuxWindow`, so the
preferences dialog reached back into the window for a picture (issue #237).

The texture cache is module-level on purpose. Dropdown list factories rebuild
their rows on every scroll frame, so the PNG decode has to happen once per
console for the life of the process -- reading and decoding it per bind made
those lists stutter badly.
"""

import logging
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, GLib, Gtk

from openemux.core.systems import get_icon_name
from openemux.ui.scopes import ALL_CONSOLES_ID, FAVORITES_ID, RECENT_ID, is_collection_scope

logger = logging.getLogger(__name__)

CONSOLE_ICON_FILES = {
    "A2600": "atari_2600__atari2600_library@2x.png",
    "A5200": "atari_5200__atari5200_library@2x.png",
    "A7800": "atari_7800__atari7800_library@2x.png",
    "LYNX": "lynx__lynx_library@2x.png",
    "CV": "colecovision__colecovision_library@2x.png",
    "FDS": "nintendo_fds__famicom_library@2x.png",
    "FC": "nintendo_fds__famicom_library@2x.png",
    "GB": "gameboy__gameboy_library@2x.png",
    # OpenEmu has no Game Boy Color icon; this is its Game Boy recoloured to
    # the yellow Pikachu edition, the one the Android app shows (see
    # assets/icons/ATTRIBUTION.md), so the two rows do not look alike.
    "GBC": "gameboy_color__gbc_library@2x.png",
    "GBA": "gameboy_advance__gba_library@2x.png",
    "GG": "gamegear__gamegear_library@2x.png",
    "INTV": "intellivision__intellivision_library@2x.png",
    "NGP": "neogeopocket__neogeopocket_library@2x.png",
    "N64": "n64__n64_library@2x.png",
    "NDS": "nds__nds_library@2x.png",
    "GC": "gamecube__gamecube_library@2x.png",
    "O2": "odyssey2__odyssey2_library@2x.png",
    "SG1000": "sg_1000__sg1000_library@2x.png",
    "S32X": "sega_32x__32x_na_library@2x.png",
    "MCD": "sega_cd__segacd_library@2x.png",
    "MD": "genesis__megadrive_library@2x.png",
    "SMS": "segamastersystem__sms_library@2x.png",
    "SATURN": "saturn__saturn_library@2x.png",
    "PS": "playstation__psx_library@2x.png",
    "PSP": "psp__psp_library@2x.png",
    "SFC": "supernes__snes_usa_library@2x.png",
    "PCE": "pc_engine__pcengine_library@2x.png",
    "PCECD": "pc_engine_cd__pcenginecd_library@2x.png",
    "VECTREX": "vectrex__vectrex_library@2x.png",
    "VB": "virtual_boy__vb_library@2x.png",
    "WS": "wonderswan__wonderswan_library@2x.png",
}


#: console_id -> Gdk.Texture, or None for a console that ships no asset.
#: Misses are cached too, so a console without one does not re-stat per bind.
_TEXTURES = {}


def asset_path(category, filename):
    return Path(__file__).parent / "assets" / "icons" / category / filename


def console_texture(console_id):
    """Load (once) the console's PNG as a texture, or None if it has no asset."""
    if console_id in _TEXTURES:
        return _TEXTURES[console_id]

    candidates = []
    preferred = CONSOLE_ICON_FILES.get(console_id)
    if preferred:
        candidates.append(preferred)
        if preferred.endswith("@2x.png"):
            candidates.append(preferred.replace("@2x.png", ".png"))

    texture = None
    for icon_filename in candidates:
        icon_path = asset_path("systems", icon_filename)
        if not icon_path.exists():
            continue
        try:
            texture = Gdk.Texture.new_from_filename(str(icon_path))
        except GLib.Error as exc:
            logger.info("console icon failed to load: %s (%s)", icon_path, exc)
            continue
        break

    _TEXTURES[console_id] = texture
    return texture


#: console_id -> the 1x (16-px) texture, or None; the chips draw it below 1080p.
_SMALL_TEXTURES = {}


def console_texture_1x(console_id):
    """Load (once) the console's 1x PNG, the art at half the size, or None."""
    if console_id in _SMALL_TEXTURES:
        return _SMALL_TEXTURES[console_id]
    texture = None
    preferred = CONSOLE_ICON_FILES.get(console_id)
    if preferred and preferred.endswith("@2x.png"):
        icon_path = asset_path("systems", preferred.replace("@2x.png", ".png"))
        if icon_path.exists():
            try:
                texture = Gdk.Texture.new_from_filename(str(icon_path))
            except GLib.Error as exc:
                logger.info("console icon failed to load: %s (%s)", icon_path, exc)
    _SMALL_TEXTURES[console_id] = texture
    return texture


def scope_icon_name(scope_id):
    """The symbolic icon of a view that is not a console, or None for a console.

    All, Favorites, Recently played and the playlists: one glyph each, the
    same in the sidebar and Big Picture's chips.
    """
    if scope_id == ALL_CONSOLES_ID:
        return "view-grid-symbolic"
    if scope_id == FAVORITES_ID:
        return "starred-symbolic"
    if scope_id == RECENT_ID:
        return "document-open-recent-symbolic"
    if is_collection_scope(scope_id):
        return "user-bookmarks-symbolic"
    return None


def console_icon(console_id):
    """A fresh ``Gtk.Image`` for ``console_id``, or for one of the virtual views.

    A widget cannot have two parents, so every caller gets its own -- only the
    texture behind it is shared.
    """
    icon_name = scope_icon_name(console_id)
    if icon_name is not None:
        icon = Gtk.Image.new_from_icon_name(icon_name)
        if console_id == FAVORITES_ID:
            icon.add_css_class("favorites-sidebar-icon")
        return icon

    texture = console_texture(console_id)
    if texture is None:
        return Gtk.Image.new_from_icon_name(get_icon_name(console_id))
    img = Gtk.Image.new_from_paintable(texture)
    img.set_size_request(22, 22)
    return img
