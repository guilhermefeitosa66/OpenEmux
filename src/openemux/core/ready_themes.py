"""The ready-made themes the app ships (issue 1012).

Pastel, Dracula, Kitty, Neon and Tokyo Night: a color scheme and a background
picture each, so a complete look is one click away. They are read-only, like
System, Light and Dark; "Duplicate" makes an editable copy.

Both apps ship the same five with the same ids and the same values. Android's
``theme.yaml`` files (``openemux-android``,
``pkg/android/openemux/src/main/assets/themes/``) are the reference; each one
is copied here as ``ui/assets/themes/<id>/theme.yaml``, the picture's name
being the one thing that differs (each app ships its own copy: a PNG here).
The pictures are ours, drawn by ``tools/theme_backgrounds.py`` (MIT); the
Dracula and Tokyo Night palettes are MIT-licensed, credited in
``THIRD_PARTY_NOTICES.md``. Every theme passes the editor's contrast check,
its picture included at its own dim (a test holds it).
"""

import logging
from pathlib import Path

import yaml

from openemux.core.custom_themes import THEME_FILE, ThemeError, parse_theme
from openemux.core.theme import READY_MADE

logger = logging.getLogger(__name__)

#: ``<id>/theme.yaml``, ``<id>/images/library.png`` and the SVG it came from.
ASSETS_DIR = Path(__file__).resolve().parents[1] / "ui" / "assets" / "themes"


def get(theme_id):
    """A fresh copy of a ready-made theme, or None for any other id."""
    if theme_id not in READY_MADE:
        return None
    folder = ASSETS_DIR / theme_id
    try:
        data = yaml.safe_load((folder / THEME_FILE).read_text(encoding="utf-8"))
        theme = parse_theme(data, theme_id)
    except (OSError, yaml.YAMLError, ThemeError) as exc:  # pragma: no cover - a shipped asset
        logger.warning("Ready-made theme %s is unreadable: %s", theme_id, exc)
        return None
    theme.folder = folder
    return theme


def all_themes():
    """Every ready-made theme, in the picker's order."""
    return [theme for theme in map(get, READY_MADE) if theme is not None]
