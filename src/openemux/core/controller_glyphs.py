"""The names a controller's buttons go by, per family (issue 914).

The hint bar used to draw Ⓐ Ⓑ Ⓧ Ⓨ ☰: enclosed letters a font may not have,
and Xbox letters whatever pad is plugged in. The glyphs here are plain text
drawn in the bar's keycaps -- the letters of the family the detected pad
belongs to, the four shapes on a PlayStation pad -- and the family can be
forced from Preferences, as can swapping confirm and cancel.

Buttons are named by their *position* (south, east, west, north: what the
reader's udev indexes 0-3 mean), so a Nintendo pad's south button is "B".
"""

AUTO = "auto"
XBOX = "xbox"
PLAYSTATION = "playstation"
NINTENDO = "nintendo"
GENERIC = "generic"

FAMILIES = (XBOX, PLAYSTATION, NINTENDO, GENERIC)

_KEYWORDS = (
    (XBOX, ("xbox", "x-box", "microsoft", "xinput")),
    (PLAYSTATION, ("playstation", "dualshock", "dualsense", "sony", "ps3", "ps4", "ps5", "wireless controller")),
    (NINTENDO, ("nintendo", "switch", "pro controller", "joy-con", "joycon", "wii")),
)

#: position -> label, per family. "south" confirms, "east" cancels, "west"
#: is the context/details button, "north" the favorite; the shoulders
#: switch consoles; "menu" is Select/View/Options/-; "start" is Start/+.
_LABELS = {
    XBOX: {"south": "A", "east": "B", "west": "X", "north": "Y", "shoulders": "LB/RB", "menu": "View", "start": "Menu", "guide": "Guide"},
    PLAYSTATION: {"south": "✕", "east": "○", "west": "□", "north": "△", "shoulders": "L1/R1", "menu": "Share", "start": "Options", "guide": "PS"},
    NINTENDO: {"south": "B", "east": "A", "west": "Y", "north": "X", "shoulders": "L/R", "menu": "−", "start": "+", "guide": "Home"},
    GENERIC: {"south": "A", "east": "B", "west": "X", "north": "Y", "shoulders": "L1/R1", "menu": "Select", "start": "Start", "guide": "Guide"},
}


def family_for_name(name):
    """The family a pad's reported name points at; ``GENERIC`` when none does."""
    lowered = (name or "").lower()
    for family, words in _KEYWORDS:
        if any(word in lowered for word in words):
            return family
    return GENERIC


def resolve_family(preference, pad_name):
    """The family to draw: the preference unless it is ``AUTO``, else the pad's."""
    if preference in FAMILIES:
        return preference
    return family_for_name(pad_name)


def glyphs(family, swap_confirm_cancel=False):
    """``{action: label}`` for the hint bar's gamepad hints.

    ``swap_confirm_cancel`` mirrors the reader's own swap (issue 914): the
    labels follow the buttons that actually confirm and cancel.
    """
    labels = _LABELS.get(family, _LABELS[GENERIC])
    confirm, back = labels["south"], labels["east"]
    if swap_confirm_cancel:
        confirm, back = back, confirm
    return {
        "confirm": confirm,
        "confirm_hold": f"{confirm}⏳",
        "back": back,
        "context": labels["west"],
        "favorite": labels["north"],
        "consoles": labels["shoulders"],
        "menu": labels["menu"],
        "start": labels["start"],
        # The Guide/Home/PS button: Big Picture on and off.
        "guide": labels["guide"],
        "directions": "✚",
        "range": "L2/R2+✚",
    }
