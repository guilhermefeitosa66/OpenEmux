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
from gi.repository import Gdk, GLib, Graphene, Gsk, Gtk

from openemux.core.systems import get_icon_name
from openemux.ui.scopes import ALL_CONSOLES_ID, FAVORITES_ID, RECENT_ID, is_collection_scope

logger = logging.getLogger(__name__)

#: The slot of a console icon in a row (sidebar, preferences, dropdowns): the
#: art was authored for 16 points, the same as the symbolic icons beside it,
#: so the 16-px PNG lands 1:1 at scale 1 and the 32-px one at scale 2 (issue 966).
CONSOLE_ICON_SIZE = 16

#: From this many physical pixels per art pixel up, the art gets the soft grid.
SOFT_GRID_FROM = 4
#: A seam's colour: its pixel's, this much as bright (same alpha).
SOFT_GRID_SHADE = 0.8

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


def console_art_textures(console_id):
    """The console's art at every size it ships (32 px first), or ``[]``."""
    return [t for t in (console_texture(console_id), console_texture_1x(console_id)) if t is not None]


def pixel_icon_geometry(width, height, native, scale=1):
    """Where a ``native``-px pixel-art icon goes in a ``width`` x ``height`` slot.

    ``(x, y, size, nearest)`` in logical pixels: the largest whole multiple of
    ``native`` that fits the slot *in physical pixels* (``scale`` is the
    widget's scale factor), nearest-neighbour, so every source pixel stays a
    sharp square (issues 962, 966). A slot smaller than the art draws it at
    the slot's size with the smooth filter instead: nearest-neighbour
    shrinking drops pixel rows unevenly. Centred on whole physical pixels.
    """
    scale = max(1, int(scale))
    side = max(0, min(width, height)) * scale
    multiple = side // max(1, native)
    nearest = multiple >= 1
    size = multiple * native if nearest else side
    x, y = (width * scale - size) // 2, (height * scale - size) // 2
    if scale == 1:
        return x, y, size, nearest
    return x / scale, y / scale, size / scale, nearest


def pick_pixel_art(width, height, natives, scale=1):
    """Which of the art's sizes fills the slot crisply: ``(index, x, y, size, nearest)``.

    The one drawn biggest at a whole multiple wins, the more detailed one on a
    tie: at 1080p the 32-px art at 1x, at 720p the 16-px art at 1x (the 32-px
    one would have to shrink, and blur), at a 48-px slot the 16-px art at 3x.
    Only a slot smaller than every size falls back to the smooth filter, with
    the biggest art.
    """
    best = None
    for index, native in enumerate(natives):
        x, y, size, nearest = pixel_icon_geometry(width, height, native, scale)
        if not nearest:
            continue
        if best is None or (size, native) > (best[3], natives[best[0]]):
            best = (index, x, y, size, nearest)
    if best is None:
        index = max(range(len(natives)), key=natives.__getitem__)
        best = (index,) + pixel_icon_geometry(width, height, natives[index], scale)
    return best


def soft_grid_seam(cell):
    """The seam of a ``cell``-px art pixel: an eighth of it, at least one pixel."""
    return max(1, (cell + 4) // 8)


#: (texture, cell) -> the art blown up with its soft grid; built once each.
_GRIDDED = {}


def soft_grid_texture(texture, cell):
    """``texture`` at ``cell`` physical pixels per art pixel, with the soft grid.

    Every opaque pixel gets a seam on its right and bottom edges
    (``soft_grid_seam``), in its own colour at ``SOFT_GRID_SHADE``, alpha kept;
    a transparent one gets nothing, so no grid shows on the background
    (issue 966, the POC's variant D). Drawn 1:1, nearest-neighbour.
    """
    key = (texture, cell)
    gridded = _GRIDDED.get(key)
    if gridded is not None:
        return gridded
    width, height = texture.get_width(), texture.get_height()
    downloader = Gdk.TextureDownloader.new(texture)
    downloader.set_format(Gdk.MemoryFormat.R8G8B8A8)
    data, stride = downloader.download_bytes()
    pixels = data.get_data()
    seam = soft_grid_seam(cell)
    clear = bytes(4) * cell
    out = bytearray()
    for row in range(height):
        start = row * stride
        cell_row, seam_row = bytearray(), bytearray()
        for col in range(width):
            r, g, b, a = pixels[start + col * 4:start + col * 4 + 4]
            if a == 0:
                cell_row += clear
                seam_row += clear
                continue
            shade = bytes((round(r * SOFT_GRID_SHADE), round(g * SOFT_GRID_SHADE),
                           round(b * SOFT_GRID_SHADE), a))
            cell_row += bytes((r, g, b, a)) * (cell - seam) + shade * seam
            seam_row += shade * cell
        out += cell_row * (cell - seam) + seam_row * seam
    side = width * cell
    gridded = Gdk.MemoryTexture.new(side, height * cell, Gdk.MemoryFormat.R8G8B8A8,
                                    GLib.Bytes.new(bytes(out)), side * 4)
    _GRIDDED[key] = gridded
    return gridded


class ConsolePixelArt(Gtk.Widget):
    """A console's pixel art, crisp at any size: every console icon's renderer.

    ``Gtk.Image`` and ``Gtk.Picture`` scale with a linear filter, which blurs
    the art big and smears it small. This draws it itself, picking among
    ``textures`` (the same art at several sizes) with ``pick_pixel_art`` in
    physical pixels, nearest-neighbour, and from ``SOFT_GRID_FROM`` pixels per
    art pixel up with the soft grid (issue 966). The slot's size is the
    caller's (``set_size_request`` or the stylesheet).
    """

    def __init__(self, textures):
        super().__init__()
        # A size the console does not ship (``None``) is left out.
        self.textures = [texture for texture in textures if texture is not None]
        self.set_valign(Gtk.Align.CENTER)

    def do_snapshot(self, snapshot):
        scale = max(1, self.get_scale_factor())
        natives = [max(texture.get_width(), texture.get_height()) for texture in self.textures]
        index, x, y, size, nearest = pick_pixel_art(self.get_width(), self.get_height(), natives, scale)
        if size <= 0:
            return
        texture = self.textures[index]
        rect = Graphene.Rect().init(x, y, size, size)
        if not nearest:
            snapshot.append_scaled_texture(texture, Gsk.ScalingFilter.TRILINEAR, rect)
            return
        cell = round(size * scale / natives[index])
        if cell >= SOFT_GRID_FROM:
            texture = soft_grid_texture(texture, cell)
        snapshot.append_scaled_texture(texture, Gsk.ScalingFilter.NEAREST, rect)


def console_icon(console_id):
    """A fresh icon for ``console_id``, or for one of the virtual views.

    A console with art gets a ``ConsolePixelArt`` at ``CONSOLE_ICON_SIZE``;
    the virtual views and a console with no art, a symbolic ``Gtk.Image``.

    A widget cannot have two parents, so every caller gets its own -- only the
    texture behind it is shared.
    """
    icon_name = scope_icon_name(console_id)
    if icon_name is not None:
        icon = Gtk.Image.new_from_icon_name(icon_name)
        if console_id == FAVORITES_ID:
            icon.add_css_class("favorites-sidebar-icon")
        return icon

    textures = console_art_textures(console_id)
    if not textures:
        return Gtk.Image.new_from_icon_name(get_icon_name(console_id))
    art = ConsolePixelArt(textures)
    art.set_size_request(CONSOLE_ICON_SIZE, CONSOLE_ICON_SIZE)
    return art
