"""The look of Big Picture: one scale factor, one stylesheet.

Everything on a TV is read from three metres away, so every size here is a
multiple of one number: the height of the window over 1080 (the design was
drawn at 1080p), times the user's "Text size" preference. GTK's CSS cannot
multiply, so the stylesheet is generated -- ``stylesheet(scale, dark)`` --
and reloaded when the window changes size or the preference moves.

The palette is the Android app's, so a player who uses both sees one
product: the same purple accent, the same focus ring (a 4 px ring with a
soft halo and a slight lift), the same hint keycaps. Surfaces come from
libadwaita's named colours, which already follow the light and dark themes.
"""

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
    "tile_name": 22,
    "tile_count": 18,
    "tile_width": 232,
    "tile_height": 160,
    "rail_tile": 96,
    "badge": 72,
    "dialog_heading": 36,
    "button": 24,
    "button_height": 68,
    "osk_key": 60,
    "osk_font": 26,
    "status": 20,
    "gap": 16,
    "radius": 18,
    "radius_small": 12,
    "ring": 4,
    "halo": 14,
    "card_title": 22,
    # A game's details: the cover column and the save-state tiles under it.
    "details_side": 520,
    "cover_w": 400,
    "cover_h": 500,
    "state_tile": 150,
    # The tasks pages' side panel (the progress mirror, the providers).
    "side": 560,
}

#: The Android app's accent family. Fixed, so the two apps match.
ACCENT = "#7C3AED"
ACCENT_BRIGHT = "#8B5CF6"
ACCENT_TEXT_DARK = "#B79CFF"
ACCENT_TEXT_LIGHT = "#6D28D9"
ACCENT_SOFT_DARK = "#3B2A6B"
ACCENT_SOFT_LIGHT = "#E4D9FD"
DANGER_DARK = "#FF8A80"
DANGER_LIGHT = "#C0302A"


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


def palette(dark):
    """The theme-dependent half of the palette."""
    if dark:
        return {
            "accent_text": ACCENT_TEXT_DARK,
            "accent_soft": ACCENT_SOFT_DARK,
            "danger": DANGER_DARK,
            "halo": "rgba(139, 92, 246, 0.28)",
            "scrim": "rgba(11, 11, 14, 0.6)",
            "surface": "#1C1C23",
            "surface2": "#24242C",
            "raised": "#2A2A33",
            "border": "#2B2B35",
            "muted": "#A3A3B2",
            "faint": "#6E6E7C",
            "text": "#F3F3F6",
            "bg": "#121216",
        }
    return {
        "accent_text": ACCENT_TEXT_LIGHT,
        "accent_soft": ACCENT_SOFT_LIGHT,
        "danger": DANGER_LIGHT,
        "halo": "rgba(124, 58, 237, 0.22)",
        "scrim": "rgba(23, 23, 28, 0.45)",
        "surface": "#FFFFFF",
        "surface2": "#EFEEF4",
        "raised": "#E9E7EF",
        "border": "#E2E0EA",
        "muted": "#5C5C6B",
        "faint": "#8A8A9A",
        "text": "#17171C",
        "bg": "#F6F5F9",
    }


def stylesheet(scale=1.0, dark=True):
    """The whole Big Picture stylesheet at ``scale``.

    Every rule is scoped under ``.big-picture``, the class the window carries
    while the mode is on, so the desktop layout never sees any of it.
    """
    p = palette(dark)
    s = lambda name: px(name, scale)  # noqa: E731 - a local shorthand
    ring = s("ring")
    halo = s("halo")
    return f"""
/* Big Picture, generated at scale {scale} ({'dark' if dark else 'light'}). */
.big-picture .bp-shell {{
    background-color: {p['bg']};
    color: {p['text']};
}}
.big-picture .bp-safe {{
    padding: {s('safe_y')}px {s('safe_x')}px 0 {s('safe_x')}px;
}}
.big-picture .bp-title {{
    font-size: {s('title')}px;
    font-weight: 700;
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
    color: {p['accent_text']};
}}
.big-picture .bp-body {{
    font-size: {s('body')}px;
    color: {p['muted']};
}}
.big-picture .bp-status {{
    font-size: {s('status')}px;
    color: {p['muted']};
}}
.big-picture .bp-chip {{
    font-size: {s('status')}px;
    color: {p['text']};
    background-color: {p['surface']};
    border: 1px solid {p['border']};
    border-radius: 999px;
    padding: {max(4, s('gap') // 2)}px {s('gap')}px;
}}
.big-picture .bp-clock {{
    font-size: {s('row_title')}px;
    font-weight: 600;
}}

/* Rows: a settings row, a details row, a chooser option. */
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
    font-weight: 600;
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
    color: {p['faint']};
}}
.big-picture .bp-row.bp-primary {{
    background-color: {ACCENT};
    border-color: {ACCENT};
    color: #ffffff;
}}
.big-picture .bp-row.bp-primary .bp-row-title,
.big-picture .bp-row.bp-primary .bp-row-value {{
    color: #ffffff;
}}
.big-picture .bp-row.bp-primary .bp-row-subtitle,
.big-picture .bp-row.bp-primary .bp-row-chevron {{
    color: rgba(255, 255, 255, 0.82);
}}
.big-picture .bp-row.bp-danger .bp-row-title {{
    color: {p['danger']};
}}
.big-picture .bp-row.bp-current {{
    background-color: {p['accent_soft']};
    border-color: {ACCENT_BRIGHT};
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

/* Tiles: the home rows, the quick menu, the system row. */
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
    background-color: {p['surface2']};
    color: {p['text']};
    font-size: {s('row_title') + 2}px;
    font-weight: 700;
}}
.big-picture .bp-tile.bp-all {{
    background-color: #2F5D8A;
    border-color: #2F5D8A;
    color: #ffffff;
}}
.big-picture .bp-tile.bp-favorites {{
    background-color: #5B3FA8;
    border-color: #5B3FA8;
    color: #ffffff;
}}
.big-picture .bp-tile.bp-all .bp-tile-count,
.big-picture .bp-tile.bp-favorites .bp-tile-count,
.big-picture .bp-tile.bp-all .bp-tile-name,
.big-picture .bp-tile.bp-favorites .bp-tile-name {{
    color: #ffffff;
}}
.big-picture .bp-tile.bp-wide {{
    min-height: {s('rail_tile')}px;
}}
.big-picture .bp-tile.bp-danger .bp-tile-name {{
    color: {p['danger']};
}}

/* The console rail over the games. */
.big-picture .bp-rail-tile {{
    min-height: {s('rail_tile')}px;
    padding: 0 {s('gap') + 6}px 0 {s('gap') - 2}px;
    border-radius: {s('radius_small') + 4}px;
    background-color: {p['surface']};
    border: 1px solid {p['border']};
    color: {p['muted']};
    font-size: {s('tile_name')}px;
    font-weight: 600;
}}
.big-picture .bp-rail-tile.bp-current {{
    background-color: {p['accent_soft']};
    border-color: {ACCENT_BRIGHT};
    color: {p['text']};
}}
.big-picture .bp-rail-tile .bp-badge {{
    min-width: {s('badge') - 8}px;
    min-height: {s('badge') - 8}px;
}}
.big-picture .bp-rail-tile.bp-current .bp-badge {{
    background-color: {ACCENT};
    color: #ffffff;
}}
.big-picture .bp-shoulder {{
    min-width: {s('key_height') + 16}px;
    min-height: {s('key_height') + 4}px;
    border-radius: {s('radius_small')}px;
    background-color: {p['raised']};
    color: {p['text']};
    font-size: {s('hint_key')}px;
    font-weight: 700;
}}

/* The hint bar. */
.big-picture .bp-hints {{
    min-height: {s('hint_bar')}px;
    padding: 0 {s('safe_x')}px;
    border-top: 1px solid {p['surface2']};
    background-color: {p['bg']};
}}
.big-picture .bp-hint {{
    font-size: {s('hint')}px;
    color: {p['muted']};
}}
.big-picture .bp-key {{
    min-width: {s('key_height')}px;
    min-height: {s('key_height')}px;
    padding: 0 {s('gap') - 4}px;
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
    color: {p['danger']};
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
    background-color: {p['surface']};
    border-top: 1px solid {p['border']};
    padding: {s('gap') * 2}px {s('safe_x')}px;
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

/* The focus ring: a ring, a halo and a lift, on whatever the pad lands on. */
.big-picture .bp-row:focus,
.big-picture .bp-tile:focus,
.big-picture .bp-rail-tile:focus,
.big-picture .bp-button:focus,
.big-picture .bp-osk-key:focus,
.big-picture .bp-step:focus,
.big-picture .bp-section:focus {{
    outline: {ring}px solid {p['accent_text']};
    outline-offset: {ring}px;
    box-shadow: 0 0 0 {halo}px {p['halo']};
}}
.big-picture .bp-tile:focus,
.big-picture .bp-rail-tile:focus {{
    transform: scale(1.04);
}}
.big-picture.keynav-active gridview > child:focus-within .rom-card {{
    outline-width: {ring}px;
    outline-offset: -{ring}px;
    outline-color: {p['accent_text']};
    box-shadow: 0 0 0 {halo}px {p['halo']};
    transform: scale(1.04);
}}
.big-picture .rom-title {{
    font-size: {s('card_title')}px;
}}
.big-picture .rom-console {{
    font-size: {s('row_subtitle')}px;
}}
.big-picture gridview {{
    padding: {s('gap')}px {s('safe_x')}px;
}}
.big-picture .console-group-header label.heading {{
    font-size: {s('crumb') - 4}px;
}}
.big-picture .console-group-header label {{
    font-size: {s('row_subtitle')}px;
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

/* A game's details: the cover column on the left, its save states under it. */
.big-picture .bp-details-side {{
    min-width: {s('details_side')}px;
}}
.big-picture .bp-details-cover {{
    min-width: {s('cover_w')}px;
    min-height: {s('cover_h')}px;
    border-radius: {s('radius')}px;
    background-color: {p['surface2']};
}}
.big-picture .bp-tile.bp-state {{
    min-width: {s('state_tile')}px;
    min-height: {s('state_tile') - 30}px;
    padding: {s('gap') // 2}px;
}}

/* The tasks pages: the options on the left, the progress panel on the right. */
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
    min-height: {max(6, s('gap') // 2)}px;
    border-radius: {max(3, s('gap') // 4)}px;
}}
.big-picture progressbar text {{
    font-size: {s('row_subtitle')}px;
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
"""
