"""The look of Big Picture: one scale factor, one stylesheet.

Everything on a TV is read from three metres away, so every size here is a
multiple of one number: the height of the window over 1080 (the design was
drawn at 1080p), times the user's "Text size" preference. GTK's CSS cannot
multiply, so the stylesheet is generated -- ``stylesheet(scale)`` --
and reloaded when the window changes size or the preference moves.

The palette is the Android app's, so a player who uses both sees one
product (issue 957): its dark surfaces whatever the desktop's theme, its
purple accent, its per-console shelf colors, and its controller focus --
the item's background turns a deeper purple, nothing drawn around it
(issue 951).
"""

from openemux.core.big_picture_shelf import ALL_GAMES_COLOR, SHELF_COLORS, css_class
from openemux.core.config import (
    BIG_PICTURE_TEXT_SIZE_STEP,
    DEFAULT_BIG_PICTURE_TEXT_SIZE,
    MAX_BIG_PICTURE_TEXT_SIZE,
    MIN_BIG_PICTURE_TEXT_SIZE,
    normalize_big_picture_text_size,
)

#: The height the design was drawn at. Every size below is for this height.
DESIGN_HEIGHT = 1080

#: Bounds for the scale: below 0.6 nothing is readable from a couch, above
#: 2.2 a single row is taller than a 720p screen.
MIN_SCALE = 0.6
MAX_SCALE = 2.2

#: The "Text size" preference, as a percentage, and its range: the config's.
DEFAULT_TEXT_SIZE = DEFAULT_BIG_PICTURE_TEXT_SIZE
MIN_TEXT_SIZE = MIN_BIG_PICTURE_TEXT_SIZE
MAX_TEXT_SIZE = MAX_BIG_PICTURE_TEXT_SIZE
TEXT_SIZE_STEP = BIG_PICTURE_TEXT_SIZE_STEP

#: Sizes at scale 1.0 (1080p), in px. Names match the CSS classes below.
SIZES = {
    "safe_x": 96,
    "safe_y": 54,
    "title": 40,
    "crumb": 32,
    "eyebrow": 20,
    "row_title": 24,
    "row_subtitle": 18,
    "row_height": 72,
    "row_padding": 24,
    "body": 22,
    "hint": 22,
    "hint_key": 18,
    "hint_bar": 64,
    "key_height": 36,
    "tile_name": 20,
    "tile_count": 18,
    "tile_width": 240,
    # A wide tile (icon + name side by side) is as wide as its name; this is
    # only its floor, so "Search" is not a stub next to "Share nearby".
    "wide_tile_width": 200,
    "tile_height": 160,
    "rail_tile": 96,
    "badge": 72,
    # The icon box of a wide tile (icon + name side by side): smaller, so
    # the six System tiles fit across a screen in the longer locales.
    "wide_badge": 40,
    "dialog_heading": 36,
    "button": 24,
    "button_height": 68,
    "osk_key": 60,
    "osk_font": 26,
    "status": 20,
    "gap": 16,
    "radius": 18,
    "radius_small": 12,
    "card_title": 22,
    # A game's details: the cover column and the save-state tiles under it.
    "details_side": 520,
    "cover_w": 400,
    "cover_h": 500,
    "state_tile": 150,
    # The tasks pages' side panel (the progress mirror, the providers).
    "side": 560,
    # The Android layout (issue 957), at 1080p: the 720p captures times 1.5.
    "rail_width": 232,
    "rail_icon": 34,
    "rail_label": 20,
    "rail_pill": 84,
    "logo": 72,
    "page_title": 58,
    "page_subtitle": 22,
    "section_title": 26,
    "shelf_card_h": 222,
    "shelf_art": 132,
    "shelf_eyebrow": 18,
    "shelf_name": 36,
    "shelf_count": 21,
    "search_h": 70,
    "search_w": 510,
    "chip": 22,
    "chip_h": 56,
    # The console chips' icon (issue 962): the 32-px pixel art at 1x, a glyph.
    "chip_icon": 32,
    "chip_glyph": 24,
    "chip_icon_gap": 10,
    "banner_h": 66,
    "pane_width": 640,
    "pane_art_h": 400,
    "pane_title": 38,
    "play_h": 78,
    "icon_button": 66,
    "list_row": 92,
    "state_thumb": 160,
    "pause_tile_h": 132,
    "pause_tile_w": 216,
    "focus_mat": 9,
    "segment": 66,
}

#: The Android app's palette (``ui/Theme.kt``, ``Oe.*``), dark: Big Picture
#: is always dark, whatever the desktop's theme (issue 957).
ACCENT = "#7C3AED"
ACCENT_BRIGHT = "#8B5CF6"
ACCENT_TEXT = "#B79CFF"
ACCENT_SOFT = "#3B2A6B"
ACCENT_ON_SOFT = "#D4C4FF"
DANGER = "#FF8A80"
STAR = "#F5C543"

#: The controller focus of issue 951 (``Theme.kt``, ``FocusTones``): the
#: item's background takes one of these, nothing is drawn around it.
FOCUS_FILL = "#3B2A6B"       # a plain item
FOCUS_ACCENT = "#5B21B6"     # an accent button (Play, Import ROMs)
FOCUS_SELECTED = "#4E3A8C"   # an item already selected (the current chip, tab)

#: The surfaces and inks.
PALETTE = {
    "bg": "#121216",
    "surface": "#1C1C23",
    "surface2": "#24242C",
    "sheet": "#1A1A20",
    "raised": "#2A2A33",
    "border": "#2B2B35",
    "divider": "#2A2A33",
    "text": "#F3F3F6",
    "muted": "#A3A3B2",
    "faint": "#8C8C9A",
    "chevron": "#6E6E7C",
    "scrim": "rgba(11, 11, 14, 0.72)",
    "game_bg": "#0B0B0E",
}


def clamp(value, low, high):
    return max(low, min(high, value))


def normalize_text_size(value):
    """A stored "Text size" back into its range, in whole steps."""
    return normalize_big_picture_text_size(value)


def scale_for(height, text_size=DEFAULT_TEXT_SIZE):
    """The scale factor for a window ``height`` px tall and a text size."""
    try:
        height = float(height)
    except (TypeError, ValueError):
        height = DESIGN_HEIGHT
    if height <= 0:
        height = DESIGN_HEIGHT
    factor = (height / DESIGN_HEIGHT) * (normalize_text_size(text_size) / 100.0)
    return round(clamp(factor, MIN_SCALE, MAX_SCALE), 3)


def px(name, scale):
    """``SIZES[name]`` at ``scale``, as a whole number of px."""
    return max(1, int(round(SIZES[name] * scale)))


def shelf_rules():
    """One rule per console card color: ``.bp-shelf-fc { background: … }``."""
    rules = [
        f".big-picture .bp-shelf-card.{css_class(console)} {{ background-color: {color}; }}"
        for console, color in sorted(SHELF_COLORS.items())
    ]
    rules.append(f".big-picture .bp-shelf-card.bp-shelf-all {{ background-color: {ALL_GAMES_COLOR}; }}")
    return "\n".join(rules)


def stylesheet(scale=1.0):
    """The whole Big Picture stylesheet at ``scale``.

    Every rule is scoped under ``.big-picture``, the class the window carries
    while the mode is on, so the desktop layout never sees any of it.
    """
    p = PALETTE
    s = lambda name: px(name, scale)  # noqa: E731 - a local shorthand
    return f"""
/* Big Picture, generated at scale {scale}. */
.big-picture .bp-shell,
.big-picture .bp-content {{
    background-color: {p['bg']};
    color: {p['text']};
}}
.big-picture .bp-safe {{
    padding: {s('safe_y')}px {s('safe_x') // 2}px 0 {s('safe_x') // 2}px;
}}
.big-picture .bp-title {{
    font-size: {s('title')}px;
    font-weight: 700;
}}
.big-picture .bp-page-title {{
    font-size: {s('page_title')}px;
    font-weight: 700;
}}
.big-picture .bp-page-subtitle {{
    font-size: {s('page_subtitle')}px;
    color: {p['muted']};
}}
.big-picture .bp-section-title {{
    font-size: {s('section_title')}px;
    font-weight: 600;
}}
.big-picture .bp-caps {{
    font-size: {s('eyebrow')}px;
    font-weight: 600;
    letter-spacing: 1px;
    color: {p['muted']};
}}
.big-picture .bp-crumb {{
    font-size: {s('crumb')}px;
    font-weight: 700;
}}
.big-picture .bp-crumb-dim {{
    font-size: {s('crumb')}px;
    font-weight: 500;
    color: {p['faint']};
}}
.big-picture .bp-eyebrow {{
    font-size: {s('eyebrow')}px;
    font-weight: 600;
    letter-spacing: 1px;
    color: {ACCENT_TEXT};
}}
.big-picture .bp-body {{
    font-size: {s('body')}px;
    color: {p['muted']};
}}
.big-picture .bp-status {{
    font-size: {s('status')}px;
    color: {p['muted']};
}}
.big-picture .bp-clock {{
    font-size: {s('row_title')}px;
    font-weight: 600;
    color: {p['muted']};
}}
.big-picture .bp-back-link {{
    font-size: {s('row_subtitle')}px;
    color: {p['muted']};
    padding: {s('gap') // 4}px {s('gap') // 2}px;
    border-radius: {s('radius_small')}px;
    background: none;
    border: none;
}}

/* The navigation rail on the left (Android's). */
.big-picture .bp-rail {{
    min-width: {s('rail_width')}px;
    background-color: {p['bg']};
    border-right: 1px solid {p['divider']};
    padding: {s('safe_y')}px 0;
}}
.big-picture .bp-rail-logo {{
    min-width: {s('logo')}px;
    min-height: {s('logo')}px;
    margin-bottom: {s('gap') * 3}px;
}}
.big-picture .bp-tab {{
    background: none;
    border: none;
    box-shadow: none;
    color: {p['muted']};
    padding: {s('gap') // 2}px {s('gap')}px;
    border-radius: {s('radius')}px;
}}
.big-picture .bp-tab .bp-tab-pill {{
    min-width: {s('rail_pill')}px;
    min-height: {s('rail_icon') + s('gap')}px;
    border-radius: 999px;
}}
.big-picture .bp-tab image {{
    -gtk-icon-size: {s('rail_icon')}px;
}}
.big-picture .bp-tab .bp-tab-label {{
    font-size: {s('rail_label')}px;
    font-weight: 500;
}}
.big-picture .bp-tab.bp-current {{
    color: {p['text']};
}}
.big-picture .bp-tab.bp-current .bp-tab-pill {{
    background-color: {ACCENT_SOFT};
    color: {ACCENT_ON_SOFT};
}}
.big-picture .bp-tab.bp-current .bp-tab-label {{
    font-weight: 700;
}}

/* Rows: a settings row, a list row, a chooser option. */
.big-picture .bp-row {{
    min-height: {s('row_height')}px;
    padding: 0 {s('row_padding')}px;
    border-radius: {s('radius_small')}px;
    background-color: {p['surface']};
    border: 1px solid {p['border']};
    color: {p['text']};
}}
.big-picture .bp-row-title {{
    font-size: {s('row_title')}px;
    font-weight: 500;
}}
.big-picture .bp-row-subtitle {{
    font-size: {s('row_subtitle')}px;
    color: {p['muted']};
}}
.big-picture .bp-row-value {{
    font-size: {s('row_title') - 3}px;
    color: {p['muted']};
}}
.big-picture .bp-row-chevron {{
    font-size: {s('row_title')}px;
    color: {p['chevron']};
}}
.big-picture .bp-tag {{
    font-size: {s('row_subtitle') - 4}px;
    font-weight: 700;
    letter-spacing: 1px;
    color: {p['muted']};
    background-color: {p['raised']};
    border-radius: {s('radius_small') // 2}px;
    padding: {s('gap') // 6}px {s('gap') // 2}px;
}}
.big-picture .bp-tag.bp-tag-accent {{
    color: {ACCENT_ON_SOFT};
    background-color: {ACCENT_SOFT};
}}
.big-picture .bp-row.bp-primary {{
    background-color: {ACCENT};
    border-color: {ACCENT};
}}
.big-picture .bp-row.bp-primary .bp-row-title {{
    color: #ffffff;
}}
.big-picture .bp-row.bp-danger .bp-row-title {{
    color: {DANGER};
}}
.big-picture .bp-row.bp-current {{
    background-color: {ACCENT_SOFT};
    border-color: {ACCENT_SOFT};
}}
.big-picture .bp-row:disabled,
.big-picture .bp-row.bp-disabled {{
    opacity: 0.5;
}}
.big-picture .bp-row switch {{
    min-width: {s('key_height') * 5 // 3}px;
    min-height: {s('key_height') - 4}px;
}}
.big-picture .bp-row switch slider {{
    min-width: {s('key_height') - 8}px;
    min-height: {s('key_height') - 8}px;
}}
.big-picture .bp-step {{
    min-width: {s('key_height') + 4}px;
    min-height: {s('key_height') + 4}px;
    border-radius: {s('radius_small') - 2}px;
    background-color: {p['raised']};
    color: {p['text']};
    font-size: {s('row_title')}px;
    font-weight: 700;
    padding: 0;
}}
.big-picture .bp-number {{
    font-size: {s('row_title')}px;
    font-weight: 600;
    min-width: {s('row_title') * 3}px;
}}
.big-picture .bp-list-row {{
    min-height: {s('list_row')}px;
}}

/* Tiles: the pause menu's, the BIOS card. */
.big-picture .bp-tile {{
    min-width: {s('tile_width')}px;
    min-height: {s('tile_height')}px;
    border-radius: {s('radius')}px;
    background-color: {p['surface']};
    border: 1px solid {p['border']};
    color: {p['text']};
    padding: {s('gap')}px;
}}
.big-picture .bp-tile-name {{
    font-size: {s('tile_name')}px;
    font-weight: 600;
}}
.big-picture .bp-tile-count {{
    font-size: {s('tile_count')}px;
    color: {p['muted']};
}}
.big-picture .bp-badge {{
    min-width: {s('badge')}px;
    min-height: {s('badge')}px;
    border-radius: {s('radius_small') + 4}px;
    background-color: transparent;
    color: {p['text']};
    font-size: {s('row_title') + 2}px;
    font-weight: 700;
}}
.big-picture .bp-tile.bp-wide {{
    min-width: {s('wide_tile_width')}px;
    min-height: {s('rail_tile')}px;
}}
.big-picture .bp-tile.bp-wide .bp-badge {{
    min-width: {s('wide_badge')}px;
    min-height: {s('wide_badge')}px;
}}
.big-picture .bp-tile.bp-danger,
.big-picture .bp-tile.bp-danger .bp-tile-name {{
    color: {DANGER};
}}
.big-picture .bp-tile.bp-on {{
    background-color: {ACCENT_SOFT};
    border-color: {ACCENT_SOFT};
}}
.big-picture .bp-tile.bp-on .bp-tile-name,
.big-picture .bp-tile.bp-on image {{
    color: {ACCENT_ON_SOFT};
}}

/* The shelf: one card per console, in the console's color. */
.big-picture .bp-shelf-card {{
    min-height: {s('shelf_card_h')}px;
    border-radius: {s('radius') + 6}px;
    background-color: {p['surface2']};
    color: #ffffff;
    padding: {s('gap')}px {s('gap') * 2}px;
    border: none;
    box-shadow: none;
}}
.big-picture .bp-shelf-art {{
    min-width: {s('shelf_art')}px;
    min-height: {s('shelf_art')}px;
}}
.big-picture .bp-shelf-art image {{
    -gtk-icon-size: {s('shelf_art') // 2}px;
}}
.big-picture .bp-shelf-eyebrow {{
    font-size: {s('shelf_eyebrow')}px;
    font-weight: 700;
    letter-spacing: 1px;
    color: rgba(255, 255, 255, 0.72);
}}
.big-picture .bp-shelf-name {{
    font-size: {s('shelf_name')}px;
    font-weight: 700;
    color: #ffffff;
}}
.big-picture .bp-shelf-count {{
    font-size: {s('shelf_count')}px;
    color: rgba(255, 255, 255, 0.78);
}}
{shelf_rules()}

/* The search field and the accent buttons. */
.big-picture .bp-search {{
    min-height: {s('search_h')}px;
    min-width: {s('search_w')}px;
    border-radius: 999px;
    background-color: {p['surface']};
    border: none;
    color: {p['muted']};
    font-size: {s('page_subtitle')}px;
    padding: 0 {s('gap') * 2}px;
}}
.big-picture .bp-search-field {{
    min-height: {s('search_h')}px;
    border-radius: 999px;
    background-color: {p['surface']};
    color: {p['text']};
    font-size: {s('page_subtitle')}px;
    padding: 0 {s('gap') * 2}px;
}}
.big-picture .bp-accent-button {{
    min-height: {s('search_h')}px;
    border-radius: {s('radius_small') + 6}px;
    background-color: {ACCENT};
    color: #ffffff;
    font-size: {s('button')}px;
    font-weight: 600;
    padding: 0 {s('gap') * 2}px;
    border: none;
    box-shadow: none;
}}
.big-picture .bp-plain-button {{
    min-height: {s('search_h')}px;
    border-radius: {s('radius_small') + 6}px;
    background-color: {p['surface2']};
    color: {p['text']};
    font-size: {s('button')}px;
    font-weight: 600;
    padding: 0 {s('gap') * 2}px;
    border: none;
    box-shadow: none;
}}
.big-picture .bp-icon-button {{
    min-width: {s('icon_button')}px;
    min-height: {s('icon_button')}px;
    border-radius: 999px;
    background-color: {p['surface']};
    color: {p['text']};
    padding: 0;
    border: none;
    box-shadow: none;
}}
.big-picture .bp-icon-button.bp-on {{
    color: {STAR};
}}

/* The task banners. */
.big-picture .bp-banner {{
    min-height: {s('banner_h')}px;
    border-radius: {s('radius_small') + 4}px;
    background-color: {p['surface']};
    border: 1px solid {p['border']};
    color: {p['text']};
    padding: 0 {s('gap') + 4}px;
}}
.big-picture .bp-banner-title {{
    font-size: {s('row_subtitle') + 2}px;
    font-weight: 600;
}}
.big-picture .bp-banner-detail {{
    font-size: {s('row_subtitle') + 2}px;
    color: {p['muted']};
}}
.big-picture .bp-banner progressbar trough {{
    background-color: transparent;
}}
.big-picture .bp-banner progressbar progress {{
    background-color: {ACCENT_BRIGHT};
}}

/* Chips: the consoles, the filters, the view switch. */
.big-picture .bp-chip {{
    min-height: {s('chip_h')}px;
    border-radius: 999px;
    background-color: {p['surface2']};
    color: {p['text']};
    font-size: {s('chip')}px;
    font-weight: 500;
    padding: 0 {s('gap') + 6}px;
    border: none;
    box-shadow: none;
}}
.big-picture .bp-chip.bp-chip-icon {{
    padding: 0 {s('gap') + 6}px 0 {s('gap')}px;
}}
.big-picture .bp-chip-content {{
    border-spacing: {s('chip_icon_gap')}px;
}}
.big-picture .bp-chip-art {{
    min-width: {s('chip_icon')}px;
    min-height: {s('chip_icon')}px;
}}
.big-picture .bp-chip-glyph {{
    -gtk-icon-size: {s('chip_glyph')}px;
    min-width: {s('chip_icon')}px;
}}
.big-picture .bp-chip.bp-current {{
    background-color: #F3F3F6;
    color: #17171C;
}}
.big-picture .bp-chip.bp-on {{
    background-color: {ACCENT_SOFT};
    color: {ACCENT_ON_SOFT};
}}
.big-picture .bp-segments {{
    background-color: {p['surface2']};
    border-radius: {s('radius_small') + 4}px;
    padding: {s('gap') // 3}px;
}}
.big-picture .bp-segment {{
    min-width: {s('segment')}px;
    min-height: {s('segment') - 8}px;
    border-radius: {s('radius_small')}px;
    background: none;
    border: none;
    box-shadow: none;
    color: {p['muted']};
}}
.big-picture .bp-segment.bp-current {{
    background-color: {p['raised']};
    color: {p['text']};
}}
.big-picture .bp-group-header {{
    font-size: {s('section_title')}px;
    font-weight: 600;
}}

/* The detail pane. */
.big-picture .bp-pane {{
    min-width: {s('pane_width')}px;
    background-color: {p['bg']};
    border-left: 1px solid {p['divider']};
    background-image: radial-gradient(circle at 60% 0%, rgba(124, 58, 237, 0.28), transparent 55%);
}}
.big-picture .bp-pane .bp-details-cover {{
    min-width: {s('pane_art_h') * 3 // 4}px;
    min-height: {s('pane_art_h') * 3 // 4}px;
}}
.big-picture .bp-pane-art {{
    min-height: {s('pane_art_h')}px;
}}
.big-picture .bp-pane-title {{
    font-size: {s('pane_title')}px;
    font-weight: 700;
}}
.big-picture .bp-pane-meta {{
    font-size: {s('row_subtitle') + 2}px;
    color: {p['muted']};
}}
.big-picture .bp-play {{
    min-height: {s('play_h')}px;
    border-radius: {s('radius') + 6}px;
    background-color: {ACCENT};
    color: #ffffff;
    font-size: {s('button') + 2}px;
    font-weight: 600;
    border: none;
    box-shadow: none;
}}
.big-picture .bp-pill-button {{
    min-height: {s('chip_h')}px;
    border-radius: 999px;
    background-color: transparent;
    border: 1px solid {ACCENT_SOFT};
    color: {p['text']};
    font-size: {s('row_subtitle') + 2}px;
    padding: 0 {s('gap') + 6}px;
    box-shadow: none;
}}
.big-picture .bp-empty {{
    font-size: {s('row_subtitle') + 2}px;
    color: {p['muted']};
}}
.big-picture .bp-empty image {{
    -gtk-icon-size: {s('badge') // 2}px;
}}
.big-picture .bp-empty-icon {{
    min-width: {s('badge') + 16}px;
    min-height: {s('badge') + 16}px;
    border-radius: {s('radius')}px;
    background-color: {p['surface2']};
    color: {p['text']};
}}
.big-picture .bp-state {{
    min-width: {s('state_thumb')}px;
    border-radius: {s('radius_small')}px;
    background-color: {p['surface']};
    border: 1px solid {p['border']};
    padding: {s('gap') // 3}px;
    color: {p['text']};
}}
.big-picture .bp-state picture {{
    min-height: {s('state_thumb') * 3 // 4}px;
    border-radius: {s('radius_small') - 4}px;
}}

/* The hint bar: centered, as on Android. */
.big-picture .bp-hints {{
    min-height: {s('hint_bar')}px;
    padding: 0 {s('safe_x') // 2}px;
    border-top: 1px solid {p['divider']};
    background-color: {p['bg']};
}}
.big-picture .bp-hint {{
    font-size: {s('hint')}px;
    color: {p['muted']};
}}
.big-picture .bp-key {{
    min-width: {s('key_height')}px;
    min-height: {s('key_height')}px;
    padding: 0 {s('gap') // 2}px;
    border-radius: {s('key_height') // 2}px;
    background-color: {p['raised']};
    color: {p['text']};
    font-size: {s('hint_key')}px;
    font-weight: 700;
}}
.big-picture .bp-key.bp-confirm {{
    background-color: {ACCENT_BRIGHT};
    color: #ffffff;
}}

/* Buttons and dialogs. */
.big-picture .bp-button {{
    min-height: {s('button_height')}px;
    padding: 0 {s('row_padding')}px;
    border-radius: {s('radius_small') + 4}px;
    background-color: {p['surface2']};
    border: 1px solid {p['border']};
    color: {p['text']};
    font-size: {s('button')}px;
    font-weight: 600;
}}
.big-picture .bp-button.suggested-action {{
    background-color: {ACCENT};
    border-color: {ACCENT};
    color: #ffffff;
}}
.big-picture .bp-button.destructive-action {{
    color: {DANGER};
}}
.big-picture dialog .alert-dialog,
.big-picture .bp-dialog {{
    font-size: {s('body')}px;
}}
.big-picture .bp-dialog-heading {{
    font-size: {s('dialog_heading')}px;
    font-weight: 700;
}}
.big-picture .bp-dialog-body {{
    font-size: {s('body')}px;
    color: {p['muted']};
}}
.big-picture .bp-note {{
    font-size: {s('row_subtitle')}px;
    color: {p['faint']};
}}
.big-picture .bp-sheet {{
    background-color: {p['sheet']};
    border-top: 1px solid {p['border']};
    border-radius: {s('radius') + 6}px {s('radius') + 6}px 0 0;
    padding: {s('gap') * 2}px {s('safe_x') // 2}px;
}}
.big-picture .bp-scrim {{
    background-color: {p['scrim']};
}}

/* The on-screen keyboard. */
.big-picture .bp-osk-key {{
    min-width: {s('osk_key')}px;
    min-height: {s('osk_key')}px;
    border-radius: {s('radius_small')}px;
    background-color: {p['surface2']};
    border: 1px solid {p['border']};
    color: {p['text']};
    font-size: {s('osk_font')}px;
    font-weight: 600;
    padding: 0 {s('gap') // 2}px;
}}
.big-picture .bp-osk-key.suggested-action {{
    background-color: {ACCENT};
    border-color: {ACCENT};
    color: #ffffff;
}}
.big-picture .bp-osk-field {{
    min-height: {s('button_height') + 16}px;
    border-radius: {s('radius_small') + 4}px;
    background-color: {p['bg']};
    border: 2px solid {ACCENT_BRIGHT};
    font-size: {s('title') - 6}px;
    font-weight: 600;
    padding: 0 {s('row_padding')}px;
}}

/* The toast, bigger than the desktop's, and above the hint bar. */
.big-picture toast {{
    font-size: {s('hint')}px;
    margin-bottom: {s('hint_bar') + s('gap')}px;
}}

.big-picture .rom-title {{
    font-size: {s('card_title')}px;
}}
.big-picture .rom-console {{
    font-size: {s('row_subtitle')}px;
}}
.big-picture gridview {{
    padding: {s('gap')}px 0;
    background: none;
}}
.big-picture .console-group-header label.heading {{
    font-size: {s('section_title')}px;
}}
.big-picture .console-group-header label {{
    font-size: {s('row_subtitle')}px;
    color: {p['muted']};
}}
.big-picture .bp-section {{
    min-height: {s('row_height') + 4}px;
    padding: 0 {s('gap') + 4}px;
    border-radius: {s('radius_small') + 2}px;
    color: {p['muted']};
    font-size: {s('row_title')}px;
    font-weight: 600;
    background-color: transparent;
    border: 1px solid transparent;
}}
.big-picture .bp-section.bp-current {{
    background-color: {p['surface']};
    border-color: {p['border']};
    color: {p['text']};
}}

/* A game's details, expanded: the cover column on the left. */
.big-picture .bp-details-side {{
    min-width: {s('details_side')}px;
}}
.big-picture .bp-details-cover {{
    min-width: {s('cover_w')}px;
    min-height: {s('cover_h')}px;
    border-radius: {s('radius')}px;
    background-color: {p['surface2']};
}}
.big-picture .bp-side {{
    min-width: {s('side')}px;
}}
.big-picture .bp-panel {{
    border-radius: {s('radius')}px;
    background-color: {p['surface']};
    border: 1px solid {p['border']};
    padding: {s('row_padding')}px;
}}
.big-picture progressbar trough,
.big-picture progressbar progress {{
    min-height: {max(4, s('gap') // 3)}px;
    border-radius: {max(2, s('gap') // 6)}px;
}}
.big-picture progressbar text {{
    font-size: {s('row_subtitle')}px;
}}

/* The launch splash and the pause menu: over the game's black. */
.big-picture .bp-splash,
.bp-pause-window {{
    background-color: {p['game_bg']};
    color: {p['text']};
}}
.big-picture .bp-splash-art {{
    min-height: {s('pane_art_h')}px;
}}
.big-picture .bp-splash-caption {{
    font-size: {s('row_title')}px;
    color: {p['muted']};
}}
.big-picture .bp-splash-error {{
    font-size: {s('row_title')}px;
    color: {DANGER};
}}
.bp-pause-window .bp-pause-sheet {{
    background-color: {p['sheet']};
    border-radius: {s('radius') + 10}px;
    border: 1px solid {p['border']};
    padding: {s('gap') * 2}px;
}}
.bp-pause-window .bp-tile {{
    min-width: {s('pause_tile_w')}px;
    min-height: {s('pause_tile_h')}px;
}}
.bp-pause-window .bp-tile image {{
    -gtk-icon-size: {s('rail_icon')}px;
}}
.bp-pause-window .bp-tile.bp-primary {{
    background-color: {ACCENT};
    border-color: {ACCENT};
    color: #ffffff;
}}
.bp-pause-window scale trough {{
    min-height: {max(6, s('gap') // 2)}px;
    background-color: {p['raised']};
}}
.bp-pause-window scale highlight {{
    background-color: {ACCENT};
}}
.bp-pause-window scale slider {{
    min-width: {s('key_height')}px;
    min-height: {s('key_height')}px;
    background-color: #ffffff;
}}

/* The desktop's dialogs that stay dialogs in the mode -- the confirmations,
   the import "which console?" question, Share nearby, the welcome tour --
   and the first-boot screen when the app opens straight into it: drawn
   bigger, nothing else changed. */
.big-picture dialog.alert .message-area .title-2,
.big-picture dialog.alert .message-area .title-4 {{
    font-size: {s('dialog_heading')}px;
    font-weight: 700;
}}
.big-picture dialog .body,
.big-picture dialog.alert .message-area .body {{
    font-size: {s('body')}px;
}}
.big-picture dialog .title-1 {{
    font-size: {s('title')}px;
}}
.big-picture dialog .caption {{
    font-size: {s('row_subtitle')}px;
}}
.big-picture dialog row {{
    min-height: {s('row_height')}px;
}}
.big-picture dialog row .title {{
    font-size: {s('row_title')}px;
}}
.big-picture dialog row .subtitle {{
    font-size: {s('row_subtitle')}px;
}}
.big-picture dialog button {{
    min-height: {s('button_height') - 12}px;
    font-size: {s('button')}px;
}}
.big-picture dialog.alert .response-area > button {{
    min-height: {s('button_height')}px;
    font-size: {s('button')}px;
}}
.big-picture dialog carouselindicatordots {{
    min-height: {s('key_height')}px;
}}
.big-picture statuspage .title {{
    font-size: {s('title') - 4}px;
}}
.big-picture statuspage .icon {{
    -gtk-icon-size: {s('badge')}px;
}}
.big-picture .bp-first-boot {{
    min-width: {s('side') + s('safe_x')}px;
}}

/* Focus (issue 951): the item's background takes the focus tone, nothing is
   drawn around it. Art items (a cover, a cartridge, a console card) sit on a
   plate of the tone and grow a little. Last in the sheet, so it wins over
   the per-kind colours above at equal specificity. */
.big-picture .bp-row:focus,
.big-picture .bp-tile:focus,
.big-picture .bp-tab:focus,
.big-picture .bp-button:focus,
.big-picture .bp-osk-key:focus,
.big-picture .bp-step:focus,
.big-picture .bp-section:focus,
.big-picture .bp-chip:focus,
.big-picture .bp-segment:focus,
.big-picture .bp-search:focus,
.big-picture .bp-plain-button:focus,
.big-picture .bp-pill-button:focus,
.big-picture .bp-icon-button:focus,
.big-picture .bp-banner:focus,
.big-picture .bp-state:focus,
.big-picture .bp-back-link:focus,
.bp-pause-window .bp-tile:focus,
.bp-pause-window .bp-row:focus {{
    background-color: {FOCUS_FILL};
    border-color: {FOCUS_FILL};
    color: #ffffff;
    outline: none;
    box-shadow: none;
}}
.big-picture .bp-chip.bp-current:focus,
.big-picture .bp-chip.bp-on:focus,
.big-picture .bp-segment.bp-current:focus,
.big-picture .bp-row.bp-current:focus,
.big-picture .bp-tab.bp-current:focus .bp-tab-pill,
.bp-pause-window .bp-tile.bp-on:focus {{
    background-color: {FOCUS_SELECTED};
    color: #ffffff;
}}
.big-picture .bp-tab:focus {{
    background: none;
}}
.big-picture .bp-tab:focus .bp-tab-pill {{
    background-color: {FOCUS_FILL};
}}
.big-picture .bp-accent-button:focus,
.big-picture .bp-play:focus,
.big-picture .bp-row.bp-primary:focus,
.big-picture .bp-button.suggested-action:focus,
.big-picture .bp-osk-key.suggested-action:focus,
.bp-pause-window .bp-tile.bp-primary:focus {{
    background-color: {FOCUS_ACCENT};
    border-color: {FOCUS_ACCENT};
    outline: none;
    box-shadow: none;
}}
.big-picture .bp-shelf-card:focus {{
    outline: none;
    box-shadow: 0 0 0 {s('focus_mat')}px {FOCUS_FILL};
}}
.big-picture gridview > child:focus-within .rom-card {{
    background-color: {FOCUS_FILL};
    border-radius: {s('radius_small')}px;
    box-shadow: 0 0 0 {s('focus_mat')}px {FOCUS_FILL};
    outline: none;
}}
.big-picture .bp-row:focus label,
.big-picture .bp-row:focus .bp-row-title,
.big-picture .bp-row:focus .bp-row-subtitle,
.big-picture .bp-row:focus .bp-row-value,
.big-picture .bp-row:focus .bp-row-chevron,
.big-picture .bp-tile:focus label,
.big-picture .bp-tile:focus .bp-badge,
.big-picture .bp-button:focus label,
.big-picture .bp-osk-key:focus label,
.big-picture .bp-section:focus label,
.big-picture .bp-banner:focus label,
.big-picture gridview > child:focus-within .rom-card label {{
    color: #ffffff;
}}
.big-picture .bp-row:focus .bp-number {{
    background-color: rgba(255, 255, 255, 0.22);
}}
/* Switches in the accent too, not the desktop's accent colour. */
.big-picture switch:checked {{
    background-color: {ACCENT};
}}
.big-picture .bp-row:focus switch {{
    background-color: rgba(255, 255, 255, 0.28);
}}
.big-picture .bp-row:focus switch:checked {{
    background-color: #ffffff;
}}
.big-picture .bp-row:focus switch:checked slider {{
    background-color: {ACCENT};
}}
"""
