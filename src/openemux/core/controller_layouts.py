"""The drawing of each console's controller, for the input page (issue 760).

The art comes from the Android app's bundled skins: ``tools/export_controller_art.py``
crops each console's ``phone-portrait`` layout below the game screen and writes
``src/openemux/ui/assets/controllers/<CONSOLE>/`` -- ``background.png``, one
image per control and a ``layout.json`` with every control's rect and bind.

This module reads that and says, for each control, which desktop input actions
(``input_actions``) it remaps. The skins name the console's own buttons; the
Android app turns those names into RetroPad buttons (``launch/SkinBinds.kt``),
and the tables below are that file's, so a control on the desktop drawing
remaps what the same control presses on Android. A RetroPad button the desktop
has no action for on that console leaves the control with no action: the
drawing still shows it, as not remappable, rather than leaving a hole.
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from openemux.core.input_actions import PLAYER_ACTION_SUFFIXES, get_actions_for_console
from openemux.core.systems import resolve_system_id

logger = logging.getLogger(__name__)

#: Where the exported controller art lives.
CONTROLLERS_DIR = Path(__file__).resolve().parents[1] / "ui" / "assets" / "controllers"

LAYOUT_FORMAT = 1

ELEMENT_TYPES = {"button", "keypad", "dpad", "stick"}

#: The image roles each element type draws with.
IMAGE_ROLES = {"button": {"button"}, "keypad": {"button"}, "dpad": {"pad"}, "stick": {"base", "knob"}}

# --- SkinBinds.kt -------------------------------------------------------------
# Kept in step with pkg/android/openemux/src/main/java/com/openemux/mobile/
# launch/SkinBinds.kt in openemux-android; tests/test_controller_layouts.py
# spells the table out console by console.

#: Genesis Plus GX and PicoDrive's six-button pad: A on Y, B on B, C on A,
#: X on L, Y on X, Z on R, Mode on Select.
SIX_BUTTON = {"a": "y", "b": "b", "c": "a", "x": "l", "y": "x", "z": "r", "mode": "select"}

#: Where the skins' buttons sit on the RetroPad, for the consoles whose names differ.
CONSOLE_BINDS = {
    "N64": {
        "a": "b", "b": "y", "z": "l2", "cUp": "r_y_minus", "cDown": "r_y_plus",
        "cLeft": "r_x_minus", "cRight": "r_x_plus",
    },
    "MD": SIX_BUTTON,
    # The 32X and the Mega-CD play with the Mega Drive's pad, on the same cores.
    "S32X": SIX_BUTTON,
    "MCD": SIX_BUTTON,
    # Beetle Saturn: A on B, B on A, C on R, X on Y, Y on X, Z on L; its L and R on L2 and R2.
    "SATURN": {"a": "b", "b": "a", "c": "r", "x": "y", "y": "x", "z": "l", "l": "l2", "r": "r2"},
    "GC": {"z": "r", "l": "l2", "r": "r2"},
    # Nestopia turns the disk over on L.
    "FDS": {"disk": "l"},
    # Beetle Lynx has Option 1 on R and Option 2 on L.
    "LYNX": {"option1": "r", "option2": "l"},
    # The Neo Geo Pocket's A is on the left, and Beetle NGP reads it from B; its B from A.
    "NGP": {"a": "b", "b": "a"},
}

#: The generic names, whatever the console, and their RetroPad (overlay) binds.
GENERIC_BINDS = {
    **{name: name for name in (
        "up", "down", "left", "right", "a", "b", "x", "y", "l", "r", "l2", "r2", "l3", "r3", "start", "select",
    )},
    "l1": "l", "r1": "r", "menu": "menu_toggle", "quickSave": "save_state", "quickLoad": "load_state",
    "fastForward": "hold_fast_forward", "toggleFastForward": "toggle_fast_forward",
    "turbo": "turbo_fire_toggle", "screenshot": "screenshot", "restart": "reset", "reset": "reset",
}

#: The second D-pad's up, down, left and right where a console has one: Beetle
#: VB reads the Virtual Boy's right pad from L2, L3, R2 and R3.
SECOND_DPAD = {"VB": ("l2", "l3", "r2", "r3")}

# --- RetroPad -> desktop action ----------------------------------------------

#: A RetroPad button (as a skin bind names it) -> the desktop action that
#: remaps it: the inverse of the action -> RetroArch key suffix table, plus the
#: menu key.
RETROPAD_TO_ACTION = {
    **{suffix: action for action, suffix in PLAYER_ACTION_SUFFIXES.items()},
    "menu_toggle": "menu_toggle",
}

DPAD_RETROPAD = ("up", "down", "left", "right")
LEFT_STICK_RETROPAD = ("l_y_minus", "l_y_plus", "l_x_minus", "l_x_plus")
RIGHT_STICK_RETROPAD = ("r_y_minus", "r_y_plus", "r_x_minus", "r_x_plus")


def bind_to_retropad(console, bind):
    """The RetroPad button a skin's button `bind` presses on `console`, or None."""
    console_binds = CONSOLE_BINDS.get(resolve_system_id(console) or console, {})
    if bind in console_binds:
        return console_binds[bind]
    return GENERIC_BINDS.get(bind)


def element_retropad(console, element_type, bind):
    """The RetroPad buttons an element presses, in up/down/left/right order for a pad or stick."""
    system_id = resolve_system_id(console) or console
    if element_type == "dpad":
        if bind == "dpad2":
            return tuple(SECOND_DPAD.get(system_id, ()))
        return DPAD_RETROPAD
    if element_type == "stick":
        if bind == "analogStick":
            return LEFT_STICK_RETROPAD
        if bind == "rightAnalogStick":
            return RIGHT_STICK_RETROPAD
        return ()
    target = bind_to_retropad(system_id, bind)
    return (target,) if target else ()


def actions_for_element(console, element_type, bind, has_dpad=True):
    """The desktop actions an element remaps on `console` (possibly none).

    Only the console's own actions (``get_actions_for_console``) count. A left
    stick on a console the desktop gives no stick actions, whose drawing has no
    D-pad either (the Atari 5200), remaps the directions instead: otherwise
    its movement could not be remapped from the drawing at all.
    """
    allowed = set(get_actions_for_console(console))
    targets = element_retropad(console, element_type, bind)
    actions = tuple(
        action for action in (RETROPAD_TO_ACTION.get(t) for t in targets) if action and action in allowed
    )
    if not actions and element_type == "stick" and bind == "analogStick" and not has_dpad:
        actions = tuple(a for a in DPAD_RETROPAD if a in allowed)
    return actions


@dataclass(frozen=True)
class ControllerElement:
    id: str
    type: str
    bind: str
    x: int
    y: int
    width: int
    height: int
    #: Role ("button", "pad", "base", "knob") -> absolute image path.
    images: dict
    #: The desktop actions it remaps; empty when it is not remappable.
    actions: tuple


@dataclass(frozen=True)
class ControllerLayout:
    console: str
    width: int
    height: int
    background: Path
    elements: tuple


class _BadLayout(ValueError):
    pass


def _require(condition, message):
    if not condition:
        raise _BadLayout(message)


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _parse(console, folder, data):
    _require(isinstance(data, dict), "not an object")
    _require(data.get("format") == LAYOUT_FORMAT, "unsupported format")
    size = data.get("size")
    _require(isinstance(size, dict), "no size")
    width, height = size.get("width"), size.get("height")
    _require(_is_int(width) and _is_int(height) and width > 0 and height > 0, "bad size")
    background_name = data.get("background")
    _require(isinstance(background_name, str) and background_name, "no background")
    background = folder / background_name
    _require(background.is_file(), f"missing {background_name}")
    raw_elements = data.get("elements")
    _require(isinstance(raw_elements, list), "no elements")

    _require(all(isinstance(raw, dict) for raw in raw_elements), "an element is not an object")
    has_dpad = any(raw.get("type") == "dpad" and raw.get("bind", "dpad") == "dpad" for raw in raw_elements)
    elements = []
    for index, raw in enumerate(raw_elements):
        where = f"elements[{index}]"
        element_id, element_type, bind = raw.get("id"), raw.get("type"), raw.get("bind")
        _require(isinstance(element_id, str) and element_id, f"{where}: no id")
        _require(isinstance(element_type, str) and element_type in ELEMENT_TYPES, f"{where}: unknown type")
        _require(isinstance(bind, str), f"{where}: no bind")
        rect = [raw.get(key) for key in ("x", "y", "width", "height")]
        _require(all(_is_int(v) for v in rect) and rect[2] > 0 and rect[3] > 0, f"{where}: bad rect")
        images = raw.get("images")
        _require(isinstance(images, dict) and set(images) == IMAGE_ROLES[element_type], f"{where}: bad images")
        paths = {}
        for role, name in images.items():
            _require(isinstance(name, str) and name, f"{where}: bad image name")
            path = folder / name
            _require(path.is_file(), f"{where}: missing {name}")
            paths[role] = path
        elements.append(ControllerElement(
            id=element_id, type=element_type, bind=bind,
            x=rect[0], y=rect[1], width=rect[2], height=rect[3],
            images=paths, actions=actions_for_element(console, element_type, bind, has_dpad),
        ))
    return ControllerLayout(console=console, width=width, height=height, background=background, elements=tuple(elements))


def layout_for(console, root=None):
    """The controller drawing of `console`, or None when there is none.

    None also for a ``layout.json`` that cannot be read or does not hold what
    it should: the input page then falls back to its list, and the reason is
    logged rather than raised into the UI.
    """
    system_id = resolve_system_id(console)
    if not system_id:
        return None
    folder = Path(root or CONTROLLERS_DIR) / system_id
    layout_file = folder / "layout.json"
    if not layout_file.is_file():
        return None
    try:
        data = json.loads(layout_file.read_text(encoding="utf-8"))
        return _parse(system_id, folder, data)
    except (OSError, ValueError) as error:
        logger.warning("Controller layout for %s is unusable (%s): %s", system_id, layout_file, error)
        return None
