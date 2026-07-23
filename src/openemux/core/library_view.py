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


#: Sort orders the library offers, in menu order.
SORT_NAME_ASC = "name_asc"
SORT_NAME_DESC = "name_desc"
SORT_RECENTLY_PLAYED = "recently_played"
SORT_RECENTLY_ADDED = "recently_added"
SORT_FILE_SIZE = "file_size"
SORT_PLATFORM = "platform"

SORT_ORDERS = (
    SORT_NAME_ASC,
    SORT_NAME_DESC,
    SORT_RECENTLY_PLAYED,
    SORT_RECENTLY_ADDED,
    SORT_FILE_SIZE,
    SORT_PLATFORM,
)

#: A-Z is what the library has always shown.
DEFAULT_SORT_ORDER = SORT_NAME_ASC

#: Orders that need something the ROM entry does not carry. The UI uses this to
#: know when it has to hand sort_roms() a stat/history lookup.
SORT_ORDERS_NEEDING_FILE_STAT = (SORT_RECENTLY_ADDED, SORT_FILE_SIZE)
SORT_ORDERS_NEEDING_HISTORY = (SORT_RECENTLY_PLAYED,)


def normalize_sort_order(value):
    """Coerce a stored/typed value to one of ``SORT_ORDERS``."""
    candidate = (value or "").strip().lower()
    if candidate in SORT_ORDERS:
        return candidate
    return DEFAULT_SORT_ORDER


def _title(rom):
    return (rom.get("name") or "").casefold()


def sort_roms(roms, order, file_stat=None, last_played=None):
    """Order a page's ROM entries.

    ``file_stat(path)`` returns ``(size_bytes, added_epoch)`` and
    ``last_played(path)`` returns epoch seconds; both are injected so this stays
    pure and testable, and so the caller decides whether hitting the filesystem
    is worth it for the order in use. A missing lookup sorts as 0, which puts
    unknown entries last in the descending orders where they belong.

    Every order falls back to the title, so games that tie (same size, never
    played, same platform) still come out in a stable, readable sequence rather
    than in whatever order the playlist happened to be read in.
    """
    order = normalize_sort_order(order)
    entries = list(roms)

    if order == SORT_NAME_DESC:
        return sorted(entries, key=_title, reverse=True)

    if order == SORT_PLATFORM:
        return sorted(entries, key=lambda rom: ((rom.get("console") or ""), _title(rom)))

    if order == SORT_RECENTLY_PLAYED:
        played = last_played or (lambda _path: 0.0)
        return sorted(
            entries,
            key=lambda rom: (-played(rom.get("path", "")), _title(rom)),
        )

    if order in SORT_ORDERS_NEEDING_FILE_STAT:
        stat = file_stat or (lambda _path: (0, 0.0))
        index = 0 if order == SORT_FILE_SIZE else 1
        return sorted(
            entries,
            key=lambda rom: (-_stat_value(stat, rom.get("path", ""), index), _title(rom)),
        )

    return sorted(entries, key=_title)


def _stat_value(stat, path, index):
    try:
        return stat(path)[index] or 0
    except (OSError, TypeError, IndexError):
        return 0


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


def list_thumb_column_width(zoom=DEFAULT_ZOOM):
    """Width of the thumbnail column in a list.

    Every row reserves the same width, whatever shape its box art is, so the
    titles line up. A Gtk.Picture asked to fit a fixed height reports the width
    that aspect implies, which would otherwise give each console its own indent.
    """
    return scale_length(LIST_ROW_MAX_THUMB_WIDTH, zoom)


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
