"""How the library is presented: the view modes and their layout rules.

Pure logic, no GTK, so the rules the toolbar and the grid both depend on can
be unit tested. The UI layer owns the widgets and the icons; what lives here
is the vocabulary (which modes exist, which one a config means) and the sizing
each mode implies.
"""

#: Full box art on a card, laid out on a grid.
VIEW_MODE_COVER = "cover"
#: The same grid, with each game drawn inside its console's cartridge.
VIEW_MODE_CARTRIDGE = "cartridge"
#: One game per row: a small thumbnail, the title and the console.
VIEW_MODE_LIST = "list"

#: Presentation order, which is also the order the toolbar lists them in.
VIEW_MODES = (VIEW_MODE_COVER, VIEW_MODE_CARTRIDGE, VIEW_MODE_LIST)

#: The cartridge shelf is the look OpenEmux ships with.
DEFAULT_VIEW_MODE = VIEW_MODE_CARTRIDGE

#: Modes that lay cards out on a grid rather than in rows.
GRID_VIEW_MODES = (VIEW_MODE_COVER, VIEW_MODE_CARTRIDGE)

#: Thumbnail height of a list row, and the widest one may get: N64 and SFC
#: boxes are much wider than they are tall, and an uncapped thumbnail would
#: push every title on the page over to a different indent.
LIST_ROW_THUMB_HEIGHT = 64
LIST_ROW_MAX_THUMB_WIDTH = 96

#: A list row still needs a minimum width for the flow box to lay it out; the
#: row expands past this to fill the viewport.
LIST_ROW_MIN_WIDTH = 320

#: Thumbnail scales the zoom control steps through, smallest first. Discrete
#: rather than continuous: every step has to land on a size the covers still
#: read at, and stepping is what a keyboard shortcut can do.
ZOOM_LEVELS = (0.5, 0.75, 1.0, 1.25, 1.5, 2.0)

#: 100%: the size the library has always been drawn at.
DEFAULT_ZOOM = 1.0

#: Gaps shrink with the artwork, but never below this -- cards still need to
#: read as separate cards at 50%.
MIN_SCALED_SPACING = 8


def normalize_zoom(value):
    """Snap a stored/typed zoom to the nearest level we actually render."""
    try:
        candidate = float(value)
    except (TypeError, ValueError):
        return DEFAULT_ZOOM
    if candidate <= 0:
        return DEFAULT_ZOOM
    return min(ZOOM_LEVELS, key=lambda level: (abs(level - candidate), level))


def zoom_step(value, delta):
    """The zoom ``delta`` steps away from ``value``, clamped to the ends."""
    current = normalize_zoom(value)
    index = ZOOM_LEVELS.index(current) + int(delta)
    index = max(0, min(index, len(ZOOM_LEVELS) - 1))
    return ZOOM_LEVELS[index]


def can_zoom(value, delta):
    """False when a step would fall off the end (used to dim the buttons)."""
    return zoom_step(value, delta) != normalize_zoom(value)


def zoom_percent(value):
    """The zoom as a whole percentage, for the label between the buttons."""
    return int(round(normalize_zoom(value) * 100))


def scale_length(length, zoom):
    """Scale one pixel length, never down to nothing."""
    return max(1, int(round(length * normalize_zoom(zoom))))


def scale_spacing(spacing, zoom):
    """Scale a gap between items, keeping them visibly apart."""
    return max(MIN_SCALED_SPACING, int(round(spacing * normalize_zoom(zoom))))


def normalize_view_mode(value):
    """Coerce a stored/typed value to one of ``VIEW_MODES``."""
    candidate = (value or "").strip().lower()
    if candidate in VIEW_MODES:
        return candidate
    return DEFAULT_VIEW_MODE


def view_mode_from_legacy(render_cartridge_overlay):
    """The mode a pre-view-mode config was expressing with its one switch."""
    return VIEW_MODE_CARTRIDGE if render_cartridge_overlay else VIEW_MODE_COVER


def renders_cartridge(view_mode):
    """True when cards are drawn inside a cartridge frame."""
    return normalize_view_mode(view_mode) == VIEW_MODE_CARTRIDGE


def is_grid_view(view_mode):
    """True when the mode lays cards out on a grid (as opposed to rows)."""
    return normalize_view_mode(view_mode) in GRID_VIEW_MODES


def list_thumb_size(cover_size, zoom=DEFAULT_ZOOM):
    """Thumbnail size for a list row, keeping the cover's proportions.

    ``cover_size`` is the card-sized artwork the grid modes would use. The row
    height is fixed (scaled by the zoom), so the width follows from the aspect
    -- capped, so a very wide box (SFC, N64) cannot push its title far right of
    everyone else's.
    """
    row_height = scale_length(LIST_ROW_THUMB_HEIGHT, zoom)
    max_width = scale_length(LIST_ROW_MAX_THUMB_WIDTH, zoom)
    width, height = cover_size
    if width <= 0 or height <= 0:
        return max_width, row_height
    scaled_width = int(round(row_height * (width / height)))
    return max(1, min(scaled_width, max_width)), row_height
