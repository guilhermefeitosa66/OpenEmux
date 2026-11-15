"""The Big Picture shelf: each console's card color and short name (issue 957).

The Android app's gamepad layout opens on a shelf of console cards, each in
a color of its own (``data/Console.kt``, ``shelfColor``) with the console's
short code over its name. Big Picture on the desktop is the same shelf, so
both tables are copied here value by value, keyed by the desktop's system
ids (which are the Android ids too). This is not the cartridge plastic
color of ``cartridge_colors``: that one paints a game's shell, this one a
console's card.

Pure and widget-free: the stylesheet and the shelf page read it.
"""

#: The card background per console, from ``Console.kt`` (dark theme: the
#: text on it is white). Big Picture is always dark, so the light variant
#: Android computes for its light theme is not needed.
SHELF_COLORS = {
    "A2600": "#6B4A2E",
    "A5200": "#5A4A3E",
    "A7800": "#4E4A58",
    "LYNX": "#3E4A5E",
    "CV": "#2E3E5A",
    "FDS": "#8A3A3A",
    "FC": "#7A2E2E",
    "GB": "#4F5A3A",
    "GBC": "#5A3A6B",
    "GBA": "#3B3486",
    "GG": "#2E2E36",
    "INTV": "#5E4A2E",
    "NGP": "#3A4E6B",
    "N64": "#2E4A3A",
    "NDS": "#4A4A52",
    "GC": "#4A3A7A",
    "O2": "#3A3A3A",
    "SG1000": "#6B2E2E",
    "S32X": "#5A2E3A",
    "MCD": "#2E3A5A",
    "MD": "#26262E",
    "SMS": "#2E4A6B",
    "SATURN": "#3A3A4A",
    "PS": "#4A4A5A",
    "PSP": "#26262E",
    "SFC": "#4A4757",
    "PCE": "#5A5A62",
    "PCECD": "#4A4A6B",
    "VECTREX": "#2E2E2E",
    "VB": "#6B2626",
    "WS": "#3A4A4A",
}

#: The "All games" card: the Android shelf's library card.
ALL_GAMES_COLOR = "#1F3A5A"

#: A console the table does not know, a favorites or playlist card.
FALLBACK_COLOR = "#24242C"

#: The eyebrow over a console's name, from ``Console.kt`` (``short``).
SHORT_NAMES = {
    "A2600": "2600",
    "A5200": "5200",
    "A7800": "7800",
    "LYNX": "LYNX",
    "CV": "COLECO",
    "FDS": "FDS",
    "FC": "NES",
    "GB": "GB",
    "GBC": "GBC",
    "GBA": "GBA",
    "GG": "GG",
    "INTV": "INTV",
    "NGP": "NGP",
    "N64": "N64",
    "NDS": "NDS",
    "GC": "GC",
    "O2": "O2",
    "SG1000": "SG-1000",
    "S32X": "32X",
    "MCD": "SEGA CD",
    "MD": "MD",
    "SMS": "SMS",
    "SATURN": "SATURN",
    "PS": "PS1",
    "PSP": "PSP",
    "SFC": "SNES",
    "PCE": "PCE",
    "PCECD": "PCE CD",
    "VECTREX": "VECTREX",
    "VB": "VB",
    "WS": "WS",
}


def shelf_color(console_id):
    """The card color for ``console_id``; a neutral surface for an unknown one."""
    return SHELF_COLORS.get(str(console_id or ""), FALLBACK_COLOR)


def short_name(console_id):
    """The short code over the console's name ("NES", "SNES", "PS1")."""
    console_id = str(console_id or "")
    return SHORT_NAMES.get(console_id, console_id.upper())


def css_class(console_id):
    """The stylesheet class that paints a console's card: ``bp-shelf-fc``."""
    safe = "".join(ch for ch in str(console_id or "").lower() if ch.isalnum())
    return f"bp-shelf-{safe or 'none'}"


def full_name(console_id, display_name):
    """``"NES - Nintendo (NES)"``: how Android names a console in a list."""
    return f"{short_name(console_id)} - {display_name}"


__all__ = [
    "ALL_GAMES_COLOR",
    "FALLBACK_COLOR",
    "SHELF_COLORS",
    "SHORT_NAMES",
    "css_class",
    "full_name",
    "shelf_color",
    "short_name",
]
