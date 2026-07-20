"""Short rotating hints shown in the main window's status bar.

The tip texts live in the i18n catalogs; this module owns the canonical list of
keys and the (GTK-free) helpers that render them, so the rotation logic can be
unit tested without a display.

Key names are derived from ``DEFAULT_KEYBOARD_BINDINGS`` instead of being
hardcoded in the translations: if a default binding ever changes, the tip
follows it automatically.
"""

import random

from openemux.core.input_actions import DEFAULT_KEYBOARD_BINDINGS

#: Marker shown before every tip. Adwaita has no lightbulb icon (verified
#: against the live icon theme), so an emoji carries the "hint" meaning.
TIP_ICON = "\U0001F4A1"  # 💡

# Single source of truth: adding a tip is one entry here plus one string per
# locale catalog.
TIP_KEYS = [
    "tips.save_state",
    "tips.load_state",
    "tips.fast_forward",
    "tips.fullscreen",
    "tips.menu_toggle",
    "tips.drag_drop",
    "tips.sync_covers",
    "tips.shaders",
    "tips.search",
]

# Bindings are stored lowercase ("right shift", "f2"); these render them the way
# a user reads them off the keyboard.
_KEY_LABEL_OVERRIDES = {
    "enter": "Enter",
    "space": "Space",
    "right shift": "Right Shift",
    "left shift": "Left Shift",
    "right ctrl": "Right Ctrl",
    "left ctrl": "Left Ctrl",
    "escape": "Esc",
}


def format_key_label(binding):
    """Render a RetroArch binding token as a human-readable key name."""
    value = (binding or "").strip().lower()
    if not value:
        return ""
    if value in _KEY_LABEL_OVERRIDES:
        return _KEY_LABEL_OVERRIDES[value]
    if len(value) > 1 and value[0] == "f" and value[1:].isdigit():
        return value.upper()
    if len(value) == 1:
        return value.upper()
    return " ".join(part.capitalize() for part in value.split())


def tip_key_labels(bindings=None):
    """Placeholder values used to format every tip string."""
    bindings = bindings or DEFAULT_KEYBOARD_BINDINGS
    return {
        "hotkey": format_key_label(bindings.get("enable_hotkey")),
        "save_key": format_key_label(bindings.get("save_state")),
        "load_key": format_key_label(bindings.get("load_state")),
        "fast_forward_key": format_key_label(bindings.get("fast_forward_toggle")),
        "menu_key": format_key_label(bindings.get("menu_toggle")),
        "fullscreen_key": format_key_label(bindings.get("fullscreen_toggle")),
    }


def pick_next_tip(tip_keys, current=None, rng=None):
    """Pick a tip key at random, never returning ``current`` twice in a row.

    Falls back to the only available key when the list has a single entry, and
    returns ``None`` for an empty list.
    """
    keys = list(tip_keys)
    if not keys:
        return None
    candidates = [key for key in keys if key != current]
    if not candidates:
        candidates = keys
    chooser = rng or random
    return chooser.choice(candidates)


def render_tip(translate, tip_key, bindings=None):
    """Render ``tip_key`` using ``translate(key, **kwargs)`` (usually ``tr``)."""
    if not tip_key:
        return ""
    return translate(tip_key, **tip_key_labels(bindings))
