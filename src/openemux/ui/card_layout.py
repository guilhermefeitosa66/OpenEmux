"""How big a ROM card is, and the shell it is drawn in.

Pure geometry plus one widget: the aspect ratio of every console's box art,
the card size those imply, how many of them fit a viewport, and the cartridge
SVG a card is framed with. `ui/grid.py` was 2,200 lines with all of this at
the top of it (issue #238); it is what both the card and the grid measure
themselves against, and what the artwork manager sizes its preview with.
"""

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

from openemux.core import cartridge_render
from openemux.core.library_view import (
    DEFAULT_ZOOM,
    LIST_ROW_MIN_WIDTH,
    renders_cartridge,
    scale_length,
)

# The composite is rendered above the logical card size so it stays sharp on
# HiDPI displays; GTK scales the texture down when it is not needed.
CARTRIDGE_RENDER_SCALE = 2

DEFAULT_ITEM_SIZE = (200, 200)
FIXED_ITEM_WIDTH = 200

#: Gap between cards, and the grid's padding inside the viewport.
#: How long after a launch the same card's activation is treated as the
#: second half of a double-click rather than a new launch (issue #236).
ACTIVATION_DEBOUNCE_US = 500_000

GRID_SPACING = 24
GRID_MARGIN = 28

#: The same, for the compact list: rows sit close together and closer to the
#: edges, like a file manager's list view.
LIST_ROW_SPACING = 4
LIST_MARGIN = 12

# Box art proportions (width / height) per console, so a card matches the shape
# of the artwork it holds instead of forcing every console into a square.
# Measured as the median of libretro Named_Boxarts samples per system (~30
# scans each), which is where synced covers come from.
DEFAULT_COVER_ASPECT = 1.0
CONSOLE_COVER_ASPECTS = {
    "A2600": 0.73,
    "A5200": 0.73,
    "A7800": 0.73,
    "CV": 0.73,
    "FC": 0.73,
    "FDS": 0.98,
    "GB": 1.00,
    "GBA": 1.00,
    "GBC": 1.00,
    "GC": 0.71,
    "GG": 0.71,
    "INTV": 0.72,
    "LYNX": 1.12,
    "MCD": 0.71,
    "MD": 0.70,
    "N64": 1.37,
    "NDS": 1.11,
    "NGP": 0.88,
    "O2": 0.74,
    "PCE": 1.03,
    "PCECD": 1.00,
    "PS": 1.00,
    "PSP": 0.58,
    "S32X": 0.73,
    "SATURN": 1.00,
    "SFC": 1.41,
    "SG1000": 0.73,
    "SMS": 0.71,
    "VB": 1.00,
    "VECTREX": 0.74,
    "WS": 0.81,
}


def cover_size_for_console(console, zoom=DEFAULT_ZOOM):
    """Card size for a console when no cartridge frame is drawn."""
    width = scale_length(FIXED_ITEM_WIDTH, zoom)
    aspect = CONSOLE_COVER_ASPECTS.get(console, DEFAULT_COVER_ASPECT)
    height = int(round(width / aspect)) if aspect > 0 else width
    return width, max(1, height)


def default_item_size(zoom=DEFAULT_ZOOM):
    """The uniform square box pages that mix consoles lay their covers in."""
    return scale_length(DEFAULT_ITEM_SIZE[0], zoom), scale_length(DEFAULT_ITEM_SIZE[1], zoom)


def card_size_for(cover_size, mixed_consoles=False, compact=False):
    """Full card size for a cover: the artwork plus the caption below it.

    The grid needs this to lay out its columns and the card needs it to pin its
    own size, so it is computed in one place. Pages that mix consoles carry a
    second caption line for the console name.

    A compact row puts the caption *beside* the thumbnail instead, so its
    height is the thumbnail's and its width is only a minimum -- the row
    stretches to the viewport.
    """
    if compact:
        return LIST_ROW_MIN_WIDTH, cover_size[1]
    caption_height = 44 + (18 if mixed_consoles else 0)
    return cover_size[0], cover_size[1] + caption_height


def columns_and_slack(available, card_width, item_count, spacing=GRID_SPACING):
    """How many cards fit on a line, and the width left over after them.

    ``available`` is the viewport width minus the grid's margins. GtkGridView
    splits its own width evenly between its columns, so the way to get an even
    lattice is to hand it a width that divides evenly: one **cell** is a card
    plus one gap, and a card centred in a cell sits exactly ``spacing`` from
    its neighbour. The leftover is what the caller gives to the end margin --
    see RomGrid._retune_columns.

    A page with fewer cards than fit on a line is sized for the cards it
    actually has, otherwise those few get spread across the full width.
    """
    cell = card_width + spacing
    columns = max(1, available // cell)
    filled = max(1, min(columns, item_count))
    return columns, max(0, available - filled * cell)


def cartridge_frame_svg(console, color=None):
    """The pre-render frame for a console, when one was authored as SVG.

    ``color`` picks a shell variant when one exists on disk; the default (and
    any color with no file) is the authored ``<CONSOLE>.svg``.
    """
    return cartridge_render.cartridge_frame(console, color=color)


def cartridge_frame_for(console, view_mode, mixed_consoles=False, compact=False):
    """The shell a grid of ``console`` draws in, or ``None`` for plain covers.

    The rule the card shape comes from, in one place so it can be stated
    without a display:

    * only in a cartridge view mode -- a cover grid draws box art;
    * never in list view: a frame at thumbnail size is an unreadable smudge;
    * never on a grid that mixes consoles, because the card shape comes from
      the frame art and a ``GtkGridView`` lays out on a single lattice. Since
      issue #384 the mixed pages are one grid *per console*, which is what
      makes the shelf reachable there at all (issue #385);
    * and only for a console someone actually drew a cartridge for. The rest
      fall back to covers, on a mixed page exactly as on their own.
    """
    if mixed_consoles or compact or not renders_cartridge(view_mode):
        return None
    return cartridge_frame_svg(console)


class FixedSizePicture(Gtk.Picture):
    """A Picture that measures as the slot it sits in, not as its image.

    Gtk.Picture reports its paintable's pixel size as the natural size, and
    set_size_request only raises the minimum. Two places need the slot to win
    instead:

    * the cartridge composite is rendered at CARTRIDGE_RENDER_SCALE for HiDPI,
      and would blow the card up by that factor;
    * a list thumbnail asked to fit a fixed height reports the width its aspect
      implies, so each console would indent its titles differently.

    Reporting the slot directly fixes both, and GTK still draws from the
    full-resolution image.
    """

    __gtype_name__ = "OpenEmuxFixedSizePicture"

    def __init__(self, width, height):
        super().__init__()
        self._slot_size = (width, height)

    def do_measure(self, orientation, for_size):
        size = (
            self._slot_size[0]
            if orientation == Gtk.Orientation.HORIZONTAL
            else self._slot_size[1]
        )
        return size, size, -1, -1


