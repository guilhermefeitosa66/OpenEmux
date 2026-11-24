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

A custom theme (issue 1012) brings its own palette instead
(:func:`palette_for`), with floors so a couch can still read it, and may add
its font and its library image; the shelf's console colors stay as they are.
"""

from openemux.core.big_picture_shelf import ALL_GAMES_COLOR, SHELF_COLORS, css_class
from openemux.core.cartridge_colors import hex_to_rgb, parse_hex
from openemux.core.contrast import WCAG_AA, contrast_ratio
from openemux.core.custom_themes import FONT_NAME, mix, readable_on
from openemux.core.theme import THEME_DARK
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
    # A game's details page (issue 975): the art column, on the left.
    "details_side": 520,
    "cover_w": 480,
    "cover_h": 600,
    "state_tile": 150,
    # The tasks pages' side panel (the progress mirror, the providers).
    "side": 560,
    # The Android layout (issue 957), at 1080p: the 720p captures times 1.5.
    # The rail is about half its first width (issue 975): it only shows
    # four tabs, and the games need the room more.
    "rail_width": 96,
    "rail_icon": 26,
    "rail_label": 15,
    "rail_pill": 60,
    "logo": 48,
    # The pause menu's tile icons, the rail's old size.
    "pause_icon": 34,
    "page_title": 58,
    "page_subtitle": 22,
    "section_title": 26,
    # The shelf cards, sized so every shipped console name fits on one line
    # at 1920 and 2560 px wide (issue 964). The art box is not the icon's
    # size: the 32 px pixel art is drawn at the largest whole multiple that
    # fits it (2x at 1080p, 3x at 1440p, with a few px to spare for a
    # window a little shorter than the screen), so it stays sharp.
    "shelf_card_h": 150,
    "shelf_art": 76,
    "shelf_gap": 20,
    "shelf_pad_x": 24,
    "shelf_eyebrow": 16,
    "shelf_name": 28,
    "shelf_count": 19,
    "search_h": 70,
    "search_w": 510,
    "chip": 22,
    "chip_h": 56,
    # The console chips' icon (issue 962): the 32-px pixel art at 1x, a glyph.
    "chip_icon": 32,
    "chip_glyph": 24,
    "chip_icon_gap": 10,
    "banner_h": 66,
    "splash_art_h": 400,
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

#: Every color the stylesheet draws with, by name: :data:`PALETTE` plus the
#: accent family, the focus tones and the inks that sit on them. A custom
#: theme replaces it wholesale (:func:`palette_for`, issue 1012); with no
#: theme the sheet is the Android app's, exactly as before.
DEFAULT_PALETTE = {
    **PALETTE,
    "accent": ACCENT,
    "accent_bright": ACCENT_BRIGHT,
    "accent_text": ACCENT_TEXT,
    "accent_soft": ACCENT_SOFT,
    "accent_on_soft": ACCENT_ON_SOFT,
    # Text on the accent (Play, Import ROMs, the A key, a primary row).
    "on_accent": "#ffffff",
    "danger": DANGER,
    "star": STAR,
    "focus_fill": FOCUS_FILL,
    "focus_accent": FOCUS_ACCENT,
    "focus_selected": FOCUS_SELECTED,
    # Text on a focused item, and the washes of it under a focused row's
    # number and switch.
    "on_focus": "#ffffff",
    "focus_wash": "rgba(255, 255, 255, 0.22)",
    "focus_track": "rgba(255, 255, 255, 0.28)",
    # The current console chip: the text color, inverted.
    "chip_current_bg": "#F3F3F6",
    "chip_current_fg": "#17171C",
    # The pause menu's slider knob.
    "slider": "#ffffff",
    # What is read straight on the game's black (the launch splash).
    "game_text": PALETTE["text"],
    "game_muted": PALETTE["muted"],
}

#: Couch readability (issue 1012): whatever a theme says, a focused item
#: stands at least this far (WCAG ratio) from the background and from the
#: plain surface around it...
FOCUS_MIN_CONTRAST = 1.6
#: ...and text, on anything, stays at WCAG AA.
TEXT_MIN_CONTRAST = WCAG_AA
#: Icons (the favourite star) need the WCAG non-text ratio.
ICON_MIN_CONTRAST = 3.0

BLACK = "#000000"
WHITE = "#ffffff"

#: How far a theme's text size may push Big Picture: up only, to 150 %.
MAX_FONT_SCALE_FACTOR = 1.5

#: A theme's background-image fit, as CSS: (background-size, background-repeat).
BACKGROUND_FITS = {
    "cover": ("cover", "no-repeat"),
    "contain": ("contain", "no-repeat"),
    "tile": ("auto", "repeat"),
}
_URI_FORBIDDEN = ('"', "\\", ")", "\n", "\r")


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


def rgba(color_hex, alpha):
    """``#rrggbb`` at ``alpha``, as a CSS ``rgba()``."""
    r, g, b = hex_to_rgb(color_hex)
    return f"rgba({r}, {g}, {b}, {alpha})"


def nudge(color, ok, fallback):
    """``color`` moved the least toward black or white until ``ok`` holds.

    Twenty steps each way, the smaller move first; ``fallback`` when no
    step satisfies ``ok``.
    """
    for step in range(21):
        for end in (BLACK, WHITE):
            candidate = mix(color, end, step / 20)
            if ok(candidate):
                return candidate
    return fallback


def best_end(backgrounds):
    """Black or white, whichever stands farther from every one of ``backgrounds``."""
    return max(
        (BLACK, WHITE),
        key=lambda end: min(contrast_ratio(end, bg) for bg in backgrounds),
    )


def apart_from(color, backgrounds, target):
    return all(contrast_ratio(color, bg) >= target for bg in backgrounds)


def readable_on_all(color, backgrounds, target=TEXT_MIN_CONTRAST):
    """``color``, nudged until it reads at ``target`` on all ``backgrounds``."""
    return nudge(
        color,
        lambda c: apart_from(c, backgrounds, target),
        best_end(backgrounds),
    )


def readable_or(color, background, fallback):
    """``color`` when it reads on ``background`` at AA, else ``fallback``."""
    if contrast_ratio(color, background) >= TEXT_MIN_CONTRAST:
        return color
    return fallback


def focus_tones(accent, bg, surface, text):
    """``(fill, selected, ink)``: the focus tones of an accent, and their text.

    Both tones stand :data:`FOCUS_MIN_CONTRAST` from the background and the
    surface; the ink (the text color pushed until it reads on the fill)
    reads on both at :data:`TEXT_MIN_CONTRAST`. The selected tone falls back
    to the fill when no nudge of it satisfies all three.
    """
    surfaces = (bg, surface)
    fill = nudge(
        mix(accent, surface, 0.55),
        lambda c: apart_from(c, surfaces, FOCUS_MIN_CONTRAST),
        best_end(surfaces),
    )
    ink = readable_on(text, fill, TEXT_MIN_CONTRAST)
    selected = nudge(
        mix(accent, surface, 0.4),
        lambda c: apart_from(c, surfaces, FOCUS_MIN_CONTRAST)
        and contrast_ratio(ink, c) >= TEXT_MIN_CONTRAST,
        fill,
    )
    return fill, selected, ink


def palette_for(values, base):
    """The Big Picture palette of a custom theme (issue 1012).

    ``values`` are the theme's effective values (``Theme.effective_values()``)
    and ``base`` its ``light``/``dark``. The theme's colors map onto Big
    Picture's roles, then the floors are applied so the couch can still read
    it: text and secondary text on the background and surfaces, accent text
    on the background, the focus tones apart from what they sit on.
    """
    dark = base == THEME_DARK
    bg = values["library_bg"]
    surface = values["card_bg"]
    accent = values["accent_button_bg"]
    text = readable_on_all(values["text_primary"], (bg, surface))
    muted = readable_on_all(values["text_secondary"], (bg, surface))
    # The theme's own button ink: the editor already warns about it, and
    # pushing it would turn GNOME's white-on-blue into black-on-blue.
    on_accent = values["accent_button_fg"]
    accent_soft = mix(accent, bg, 0.7)
    fill, selected, on_focus = focus_tones(accent, bg, surface, text)
    focus_accent = nudge(
        mix(accent, BLACK if dark else WHITE, 0.25),
        lambda c: contrast_ratio(on_accent, c) >= TEXT_MIN_CONTRAST,
        accent,
    )
    game_bg = PALETTE["game_bg"]
    return {
        "bg": bg,
        "surface": surface,
        "surface2": values["popover_bg"],
        "sheet": values["sidebar_bg"],
        "raised": mix(surface, values["text_primary"], 0.08),
        "border": values["border_color"],
        "divider": values["border_color"],
        "text": text,
        "muted": muted,
        "faint": mix(muted, bg, 0.25),
        "chevron": mix(muted, bg, 0.4),
        "scrim": rgba(bg, 0.72),
        "game_bg": game_bg,
        "accent": accent,
        "accent_bright": mix(accent, WHITE if dark else BLACK, 0.15),
        "accent_text": readable_on(values["accent"], bg, TEXT_MIN_CONTRAST),
        "accent_soft": accent_soft,
        "accent_on_soft": readable_on(text, accent_soft, TEXT_MIN_CONTRAST),
        "on_accent": on_accent,
        "danger": readable_on_all(DANGER, (bg, surface)),
        "star": readable_on_all(STAR, (surface,), ICON_MIN_CONTRAST),
        "focus_fill": fill,
        "focus_accent": focus_accent,
        "focus_selected": selected,
        "on_focus": on_focus,
        "focus_wash": rgba(on_focus, 0.22),
        "focus_track": rgba(on_focus, 0.28),
        "chip_current_bg": text,
        "chip_current_fg": readable_on(bg, text, TEXT_MIN_CONTRAST),
        "slider": text,
        "game_text": readable_or(text, game_bg, PALETTE["text"]),
        "game_muted": readable_or(muted, game_bg, PALETTE["muted"]),
    }


def font_scale_factor(theme_font_scale):
    """How much a theme's text size (a factor, 1.1) grows Big Picture: 1.0 to 1.5.

    Big Picture only scales up: a theme that shrinks the desktop's text
    leaves the couch sizes alone.
    """
    try:
        factor = float(theme_font_scale)
    except (TypeError, ValueError):
        return 1.0
    return clamp(factor, 1.0, MAX_FONT_SCALE_FACTOR)


def themed_rules(p):
    """What only a theme's palette needs: the pause sheet's own ink.

    The pause window's text is the game's (light, on black); its sheet is
    the theme's, which may be light.
    """
    return f"""
/* A custom theme (issue 1012). */
.bp-pause-window .bp-pause-sheet {{
    color: {p['text']};
}}
"""


def font_rule(font_family):
    """The theme's font family, or nothing for a name that is not safe."""
    if not isinstance(font_family, str) or not FONT_NAME.fullmatch(font_family):
        return ""
    return f"""
.big-picture,
.bp-pause-window {{
    font-family: "{font_family}";
}}
"""


def background_rules(background):
    """The theme's library image behind the content, or nothing.

    ``background`` is ``{"uri": "file:///….png", "fit": "cover"}``; only a
    ``file://`` URI that cannot close the ``url("…")`` is accepted.
    """
    if not isinstance(background, dict):
        return ""
    uri = background.get("uri")
    if not isinstance(uri, str) or not uri.startswith("file://"):
        return ""
    if any(ch in uri for ch in _URI_FORBIDDEN):
        return ""
    size, repeat = BACKGROUND_FITS.get(background.get("fit"), BACKGROUND_FITS["cover"])
    return f"""
.big-picture .bp-content {{
    background-image: url("{uri}");
    background-position: center;
    background-size: {size};
    background-repeat: {repeat};
}}
.big-picture .bp-content navigation-view,
.big-picture .bp-content navigation-view-page {{
    background: none;
}}
"""


def console_list_rules(color, p):
    """Every console card in one theme color, with the theme's ink on it.

    After ``shelf_rules`` and one class more specific than them, so it wins
    over each console's own color. ``color`` must be a ``#rrggbb``.
    """
    color = parse_hex(color) if isinstance(color, str) else None
    if color is None:
        return ""
    return f"""
/* The console list in a theme's color (issue 1012). */
.big-picture .bp-content .bp-shelf-card,
.big-picture .bp-content .bp-shelf-card.bp-shelf-all {{
    background-color: {color};
    color: {p['text']};
}}
.big-picture .bp-content .bp-shelf-card .bp-shelf-name {{
    color: {p['text']};
}}
.big-picture .bp-content .bp-shelf-card .bp-shelf-eyebrow,
.big-picture .bp-content .bp-shelf-card .bp-shelf-count {{
    color: {p['muted']};
}}
"""


def stylesheet(scale=1.0, palette=None, font_family=None, background=None, console_list=None):
    """The whole Big Picture stylesheet at ``scale``.

    Every rule is scoped under ``.big-picture``, the class the window carries
    while the mode is on, so the desktop layout never sees any of it.

    ``palette`` (from :func:`palette_for`), ``font_family`` and
    ``background`` (see :func:`background_rules`) come from a custom theme
    (issue 1012); without them the sheet is the default one.
    """
    p = DEFAULT_PALETTE if palette is None else {**DEFAULT_PALETTE, **palette}
    s = lambda name: px(name, scale)  # noqa: E731 - a local shorthand
    extra = "" if palette is None else themed_rules(p)
    extra += font_rule(font_family) + background_rules(background)
    extra += console_list_rules(console_list, p)
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
    padding: {s('safe_y')}px {s('gap') // 2}px;
}}
.big-picture .bp-rail-logo {{
    min-width: {s('logo')}px;
    min-height: {s('logo')}px;
    -gtk-icon-size: {s('logo')}px;
    margin-bottom: {s('gap') * 2}px;
}}
.big-picture .bp-tab {{
    background: none;
    border: none;
    box-shadow: none;
    color: {p['muted']};
    padding: {s('gap') // 4}px {s('gap') // 4}px;
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
    background-color: {p['accent_soft']};
    color: {p['accent_on_soft']};
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
    color: {p['accent_on_soft']};
    background-color: {p['accent_soft']};
}}
.big-picture .bp-row.bp-primary {{
    background-color: {p['accent']};
    border-color: {p['accent']};
}}
.big-picture .bp-row.bp-primary .bp-row-title {{
    color: {p['on_accent']};
}}
.big-picture .bp-row.bp-danger .bp-row-title {{
    color: {p['danger']};
}}
.big-picture .bp-row.bp-current {{
    background-color: {p['accent_soft']};
    border-color: {p['accent_soft']};
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
    color: {p['danger']};
}}
.big-picture .bp-tile.bp-on {{
    background-color: {p['accent_soft']};
    border-color: {p['accent_soft']};
}}
.big-picture .bp-tile.bp-on .bp-tile-name,
.big-picture .bp-tile.bp-on image {{
    color: {p['accent_on_soft']};
}}

/* The shelf: one card per console, in the console's color. */
.big-picture .bp-shelf-card {{
    min-height: {s('shelf_card_h')}px;
    border-radius: {s('radius') + 6}px;
    background-color: {p['surface2']};
    color: #ffffff;
    padding: {s('gap')}px {s('shelf_pad_x')}px;
    border: none;
    box-shadow: none;
}}
.big-picture .bp-shelf-card > box {{
    border-spacing: {s('shelf_gap')}px;
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
    background-color: {p['accent']};
    color: {p['on_accent']};
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
    color: {p['star']};
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
    background-color: {p['accent_bright']};
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
    min-height: {s('chip_icon')}px;
}}
.big-picture .bp-chip.bp-current {{
    background-color: {p['chip_current_bg']};
    color: {p['chip_current_fg']};
}}
.big-picture .bp-chip.bp-on {{
    background-color: {p['accent_soft']};
    color: {p['accent_on_soft']};
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

/* A game's details: the title, the meta line, Play. */
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
    background-color: {p['accent']};
    color: {p['on_accent']};
    font-size: {s('button') + 2}px;
    font-weight: 600;
    border: none;
    box-shadow: none;
}}
.big-picture .bp-pill-button {{
    min-height: {s('chip_h')}px;
    border-radius: 999px;
    background-color: transparent;
    border: 1px solid {p['accent_soft']};
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
/* The time at the right end of the hint bar (issue 977). */
.big-picture .bp-hints .bp-clock {{
    font-weight: 600;
    font-feature-settings: "tnum";
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
    background-color: {p['accent_bright']};
    color: {p['on_accent']};
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
    background-color: {p['accent']};
    border-color: {p['accent']};
    color: {p['on_accent']};
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
    background-color: {p['accent']};
    border-color: {p['accent']};
    color: {p['on_accent']};
}}
.big-picture .bp-osk-field {{
    min-height: {s('button_height') + 16}px;
    border-radius: {s('radius_small') + 4}px;
    background-color: {p['bg']};
    border: 2px solid {p['accent_bright']};
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

/* Scrollers (issue 999). The pad drives the mode on a TV: no scrollbar is
   ever drawn, and none takes room or catches the pointer, while the content
   still scrolls (focus, wheel, touch). Scoped to the mode's classes, so the
   desktop keeps its scrollbars. */
.big-picture scrollbar,
.big-picture scrollbar trough,
.big-picture scrollbar slider {{
    opacity: 0;
    min-width: 0;
    min-height: 0;
    margin: 0;
    padding: 0;
    border: none;
    background: none;
    box-shadow: none;
}}
/* The focus mat lies outside its item, and a scroller clips at its edge: the
   content gets a gutter of the mat inside the clip, and the scroller reaches
   out by as much, so the items stay on the page margins. In the middle of
   the content the shell scrolls the mat into view as the focus moves
   (``widgets.reveal_whole``). */
.big-picture .bp-scroller {{
    margin-left: -{s('focus_mat')}px;
    margin-right: -{s('focus_mat')}px;
    min-width: {2 * s('focus_mat')}px; /* never narrower than its margins: GTK refuses a negative size */
}}
.big-picture .bp-scroller > viewport > * {{
    margin-left: {s('focus_mat')}px;
    margin-right: {s('focus_mat')}px;
}}
.big-picture .bp-scroller-vertical > viewport > * {{
    margin-bottom: {s('focus_mat')}px;
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

/* A game's details page: the art column on the left. */
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
    color: {p['game_text']};
}}
.big-picture .bp-splash-art {{
    min-height: {s('splash_art_h')}px;
}}
.big-picture .bp-splash-caption {{
    font-size: {s('row_title')}px;
    color: {p['game_muted']};
}}
.big-picture .bp-splash-error {{
    font-size: {s('row_title')}px;
    color: {p['danger']};
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
    -gtk-icon-size: {s('pause_icon')}px;
}}
.bp-pause-window .bp-tile.bp-primary {{
    background-color: {p['accent']};
    border-color: {p['accent']};
    color: {p['on_accent']};
}}
.bp-pause-window scale trough {{
    min-height: {max(6, s('gap') // 2)}px;
    background-color: {p['raised']};
}}
.bp-pause-window scale highlight {{
    background-color: {p['accent']};
}}
.bp-pause-window scale slider {{
    min-width: {s('key_height')}px;
    min-height: {s('key_height')}px;
    background-color: {p['slider']};
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
    background-color: {p['focus_fill']};
    border-color: {p['focus_fill']};
    color: {p['on_focus']};
    outline: none;
    box-shadow: none;
}}
.big-picture .bp-chip.bp-current:focus,
.big-picture .bp-chip.bp-on:focus,
.big-picture .bp-segment.bp-current:focus,
.big-picture .bp-row.bp-current:focus,
.big-picture .bp-tab.bp-current:focus .bp-tab-pill,
.bp-pause-window .bp-tile.bp-on:focus {{
    background-color: {p['focus_selected']};
    color: {p['on_focus']};
}}
.big-picture .bp-tab:focus {{
    background: none;
}}
.big-picture .bp-tab:focus .bp-tab-pill {{
    background-color: {p['focus_fill']};
}}
.big-picture .bp-accent-button:focus,
.big-picture .bp-play:focus,
.big-picture .bp-row.bp-primary:focus,
.big-picture .bp-button.suggested-action:focus,
.big-picture .bp-osk-key.suggested-action:focus,
.bp-pause-window .bp-tile.bp-primary:focus {{
    background-color: {p['focus_accent']};
    border-color: {p['focus_accent']};
    outline: none;
    box-shadow: none;
}}
.big-picture .bp-shelf-card:focus {{
    outline: none;
    box-shadow: 0 0 0 {s('focus_mat')}px {p['focus_fill']};
}}
.big-picture gridview > child:focus-within .rom-card {{
    background-color: {p['focus_fill']};
    border-radius: {s('radius_small')}px;
    box-shadow: 0 0 0 {s('focus_mat')}px {p['focus_fill']};
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
    color: {p['on_focus']};
}}
.big-picture .bp-row:focus .bp-number {{
    background-color: {p['focus_wash']};
}}
/* Switches in the accent too, not the desktop's accent colour. */
.big-picture switch:checked {{
    background-color: {p['accent']};
}}
.big-picture .bp-row:focus switch {{
    background-color: {p['focus_track']};
}}
.big-picture .bp-row:focus switch:checked {{
    background-color: {p['on_focus']};
}}
.big-picture .bp-row:focus switch:checked slider {{
    background-color: {p['accent']};
}}
""" + extra
