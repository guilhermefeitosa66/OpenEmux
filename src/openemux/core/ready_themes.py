"""The ready-made themes the app ships (issue 1012).

Pastel, Dracula, Kitty, Neon and Tokyo Night: a color scheme and a background
picture each, so a complete look is one click away. They are read-only, like
System, Light and Dark; "Duplicate" makes an editable copy. The Android app
ships the same five with the same ids and the same values (the contract is in
``docs/THEME_FORMAT.md``), each side with its own copy of the pictures.

The pictures are ours, drawn by ``tools/theme_backgrounds.py`` (MIT, like the
app); the Dracula and Tokyo Night palettes are MIT-licensed color schemes,
credited in ``THIRD_PARTY_NOTICES.md``. Every theme passes the editor's
contrast check, its picture included at the default dim (a test holds it).
"""

from pathlib import Path

from openemux.core.custom_themes import Theme, validate_values
from openemux.core.theme import READY_MADE, THEME_DARK, THEME_LIGHT

#: Where the pictures are: ``<id>/library.png`` (and the SVG it was drawn from).
ASSETS_DIR = Path(__file__).resolve().parents[1] / "ui" / "assets" / "themes"

#: Each theme's base and the values it changes. Names are translated
#: (``theme.ready.<id>``); these are only the English fallbacks.
_DEFINITIONS = {
    "pastel": ("Pastel", THEME_LIGHT, {
        "window_bg": "#fff7fb", "sidebar_bg": "#fce7f3", "headerbar_bg": "#fce7f3",
        "library_bg": "#fff7fb", "card_bg": "#ffffff", "popover_bg": "#ffffff",
        "details_bg": "#fff7fb",
        "text_primary": "#3f3350", "text_secondary": "#5f526f",
        "sidebar_text_primary": "#3f3350", "sidebar_text_secondary": "#5f526f",
        "accent": "#7c3aed", "selection_bg": "#ede0ff",
        "accent_button_bg": "#7c3aed", "accent_button_fg": "#ffffff",
        "border_color": "#f5d0e6", "corner_radius": 16,
        "shadow_color": "#c084fc", "shadow_strength": 20, "icon_color": "#6d28d9",
        "library_image": "library.png", "library_image_dim": 55,
    }),
    "dracula": ("Dracula", THEME_DARK, {
        "window_bg": "#282a36", "sidebar_bg": "#21222c", "headerbar_bg": "#21222c",
        "library_bg": "#282a36", "card_bg": "#44475a", "popover_bg": "#343746",
        "details_bg": "#2e303e",
        "text_primary": "#f8f8f2", "text_secondary": "#c6c9de",
        "sidebar_text_primary": "#f8f8f2", "sidebar_text_secondary": "#c6c9de",
        "accent": "#bd93f9", "selection_bg": "#44475a",
        "accent_button_bg": "#bd93f9", "accent_button_fg": "#282a36",
        "border_color": "#44475a", "shadow_strength": 45, "icon_color": "#ff79c6",
        "library_image": "library.png", "library_image_dim": 45,
    }),
    "kitty": ("Kitty", THEME_DARK, {
        "window_bg": "#2a2438", "sidebar_bg": "#241f31", "headerbar_bg": "#241f31",
        "library_bg": "#2a2438", "card_bg": "#3b3250", "popover_bg": "#352c47",
        "details_bg": "#30293f",
        "text_primary": "#f5e0ee", "text_secondary": "#cdbcd9",
        "sidebar_text_primary": "#f5e0ee", "sidebar_text_secondary": "#cdbcd9",
        "accent": "#f5c2e7", "selection_bg": "#4a3b5c",
        "accent_button_bg": "#f5c2e7", "accent_button_fg": "#2a2438",
        "border_color": "#4a3b5c", "corner_radius": 20,
        "shadow_color": "#f5c2e7", "shadow_strength": 20, "icon_color": "#b4befe",
        "library_image": "library.png", "library_image_dim": 30,
    }),
    "neon": ("Neon", THEME_DARK, {
        "window_bg": "#0d0221", "sidebar_bg": "#12062b", "headerbar_bg": "#12062b",
        "library_bg": "#0d0221", "card_bg": "#1b0838", "popover_bg": "#1b0838",
        "details_bg": "#150530",
        "text_primary": "#d1f7ff", "text_secondary": "#a8b8e8",
        "sidebar_text_primary": "#d1f7ff", "sidebar_text_secondary": "#a8b8e8",
        "accent": "#05d9e8", "selection_bg": "#2a0b4a",
        "accent_button_bg": "#ff2a6d", "accent_button_fg": "#0d0221",
        "border_color": "#ff2a6d", "border_width": 1,
        "shadow_color": "#ff2a6d", "shadow_strength": 60, "icon_color": "#05d9e8",
        "library_image": "library.png", "library_image_dim": 35,
    }),
    "tokyo-night": ("Tokyo Night", THEME_DARK, {
        "window_bg": "#1a1b26", "sidebar_bg": "#16161e", "headerbar_bg": "#16161e",
        "library_bg": "#1a1b26", "card_bg": "#24283b", "popover_bg": "#24283b",
        "details_bg": "#1f2335",
        "text_primary": "#c0caf5", "text_secondary": "#a9b1d6",
        "sidebar_text_primary": "#c0caf5", "sidebar_text_secondary": "#a9b1d6",
        "accent": "#7aa2f7", "selection_bg": "#292e42",
        "accent_button_bg": "#7aa2f7", "accent_button_fg": "#1a1b26",
        "border_color": "#3b4261", "icon_color": "#bb9af7",
        "library_image": "library.png", "library_image_dim": 40,
    }),
}

assert tuple(_DEFINITIONS) == READY_MADE  # one table, one order


def get(theme_id):
    """A fresh copy of a ready-made theme, or None for any other id."""
    definition = _DEFINITIONS.get(theme_id)
    if definition is None:
        return None
    name, base, values = definition
    return Theme(theme_id, name, base, validate_values(values), image_dir=ASSETS_DIR / theme_id)


def all_themes():
    """Every ready-made theme, in the picker's order."""
    return [get(theme_id) for theme_id in READY_MADE]
