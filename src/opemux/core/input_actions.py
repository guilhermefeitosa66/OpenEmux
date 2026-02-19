from copy import deepcopy
from opemux.core.systems import resolve_system_id

ACTION_ORDER = [
    "up",
    "down",
    "left",
    "right",
    "a",
    "b",
    "x",
    "y",
    "start",
    "select",
    "l1",
    "l2",
    "l3",
    "r1",
    "r2",
    "r3",
    "enable_hotkey",
    "menu_toggle",
    "save_state",
    "load_state",
    "fast_forward_toggle",
]

FALLBACK_KEYS = ["g", "h", "j", "k", "l", "v", "b", "n", "m", "r", "t", "u", "i", "o", "p"]
GLOBAL_HOTKEY_ACTIONS = [
    "enable_hotkey",
    "menu_toggle",
    "save_state",
    "load_state",
    "fast_forward_toggle",
]
GAMEPLAY_ACTIONS_2BTN = ["up", "down", "left", "right", "a", "b", "start", "select"]
GAMEPLAY_ACTIONS_2BTN_SHOULDER = ["up", "down", "left", "right", "a", "b", "l1", "r1", "start", "select"]
GAMEPLAY_ACTIONS_4BTN_SHOULDER = ["up", "down", "left", "right", "a", "b", "x", "y", "l1", "r1", "start", "select"]
GAMEPLAY_ACTIONS_FULL = [
    "up",
    "down",
    "left",
    "right",
    "a",
    "b",
    "x",
    "y",
    "l1",
    "l2",
    "l3",
    "r1",
    "r2",
    "r3",
    "start",
    "select",
]

CONSOLE_GAMEPLAY_ACTIONS = {
    "FC": GAMEPLAY_ACTIONS_2BTN,
    "FDS": GAMEPLAY_ACTIONS_2BTN,
    "GB": GAMEPLAY_ACTIONS_2BTN,
    "GBC": GAMEPLAY_ACTIONS_2BTN,
    "GG": GAMEPLAY_ACTIONS_2BTN,
    "SMS": GAMEPLAY_ACTIONS_2BTN,
    "SG1000": GAMEPLAY_ACTIONS_2BTN,
    "WS": GAMEPLAY_ACTIONS_2BTN,
    "NGP": GAMEPLAY_ACTIONS_2BTN,
    "CV": GAMEPLAY_ACTIONS_2BTN,
    "O2": GAMEPLAY_ACTIONS_2BTN,
    "VECTREX": GAMEPLAY_ACTIONS_2BTN,
    "VB": GAMEPLAY_ACTIONS_2BTN,
    "GBA": GAMEPLAY_ACTIONS_2BTN_SHOULDER,
    "LYNX": GAMEPLAY_ACTIONS_2BTN_SHOULDER,
    "MD": GAMEPLAY_ACTIONS_2BTN_SHOULDER,
    "MCD": GAMEPLAY_ACTIONS_2BTN_SHOULDER,
    "S32X": GAMEPLAY_ACTIONS_2BTN_SHOULDER,
    "PCE": GAMEPLAY_ACTIONS_2BTN_SHOULDER,
    "PCECD": GAMEPLAY_ACTIONS_2BTN_SHOULDER,
    "PSP": GAMEPLAY_ACTIONS_2BTN_SHOULDER,
    "SFC": GAMEPLAY_ACTIONS_4BTN_SHOULDER,
    "SATURN": GAMEPLAY_ACTIONS_4BTN_SHOULDER,
    "PS": GAMEPLAY_ACTIONS_4BTN_SHOULDER,
    "GC": GAMEPLAY_ACTIONS_4BTN_SHOULDER,
    "N64": GAMEPLAY_ACTIONS_4BTN_SHOULDER,
    "NDS": GAMEPLAY_ACTIONS_4BTN_SHOULDER,
    "A2600": GAMEPLAY_ACTIONS_2BTN,
    "A5200": GAMEPLAY_ACTIONS_2BTN,
    "A7800": GAMEPLAY_ACTIONS_2BTN,
    "INTV": GAMEPLAY_ACTIONS_2BTN,
}

DEFAULT_KEYBOARD_BINDINGS = {
    "up": "up",
    "down": "down",
    "left": "left",
    "right": "right",
    "a": "z",
    "b": "x",
    "x": "s",
    "y": "c",
    "start": "enter",
    "select": "space",
    "r1": "a",
    "r2": "q",
    "r3": "1",
    "l1": "d",
    "l2": "e",
    "l3": "3",
    # Hotkeys: keep RetroArch defaults while protecting gameplay keys via enable_hotkey.
    "enable_hotkey": "right shift",
    "menu_toggle": "f1",
    "save_state": "f2",
    "load_state": "f4",
    "fast_forward_toggle": "f6",
}

DEFAULT_GAMEPAD_BINDINGS = {
    "up": "h0up",
    "down": "h0down",
    "left": "h0left",
    "right": "h0right",
    "a": "0",
    "b": "1",
    "x": "2",
    "y": "3",
    "start": "7",
    "select": "6",
    "l1": "4",
    "r1": "5",
    "l2": "+2",
    "r2": "+5",
    "l3": "8",
    "r3": "9",
    "enable_hotkey": "14",
    "menu_toggle": "10",
    "save_state": "11",
    "load_state": "12",
    "fast_forward_toggle": "13",
}

RETROARCH_BASE_KEYS = {
    "up": "input_player1_up",
    "down": "input_player1_down",
    "left": "input_player1_left",
    "right": "input_player1_right",
    "a": "input_player1_a",
    "b": "input_player1_b",
    "x": "input_player1_x",
    "y": "input_player1_y",
    "start": "input_player1_start",
    "select": "input_player1_select",
    "l1": "input_player1_l",
    "l2": "input_player1_l2",
    "l3": "input_player1_l3",
    "r1": "input_player1_r",
    "r2": "input_player1_r2",
    "r3": "input_player1_r3",
    "enable_hotkey": "input_enable_hotkey",
    "menu_toggle": "input_menu_toggle",
    "save_state": "input_save_state",
    "load_state": "input_load_state",
    "fast_forward_toggle": "input_toggle_fast_forward",
}


def default_keyboard_bindings():
    return deepcopy(DEFAULT_KEYBOARD_BINDINGS)


def default_gamepad_bindings():
    return deepcopy(DEFAULT_GAMEPAD_BINDINGS)


def get_actions_for_console(console):
    system_id = resolve_system_id(console)
    gameplay = CONSOLE_GAMEPLAY_ACTIONS.get(system_id, GAMEPLAY_ACTIONS_FULL)
    return list(gameplay) + list(GLOBAL_HOTKEY_ACTIONS)


def default_bindings_for_device(device_type, console=None):
    allowed_actions = set(get_actions_for_console(console))
    if device_type == "gamepad":
        defaults = default_gamepad_bindings()
    else:
        defaults = default_keyboard_bindings()
    return {action: defaults.get(action, "") for action in ACTION_ORDER if action in allowed_actions}


def normalize_bindings(bindings, device_type, console=None):
    normalized = {}
    bindings = bindings or {}
    defaults = default_bindings_for_device(device_type, console=console)
    allowed_actions = get_actions_for_console(console)

    # Preserve user-provided values first.
    for action in allowed_actions:
        value = bindings.get(action, "")
        normalized[action] = str(value).strip().lower() if value is not None else ""

    # Fill missing values from defaults and then fallback letters.
    used_keys = {value for value in normalized.values() if value}
    fallback_index = 0
    for action in allowed_actions:
        if normalized[action]:
            continue
        default_value = defaults.get(action, "")
        if default_value and default_value not in used_keys:
            normalized[action] = default_value
            used_keys.add(default_value)
            continue
        while fallback_index < len(FALLBACK_KEYS) and FALLBACK_KEYS[fallback_index] in used_keys:
            fallback_index += 1
        if fallback_index < len(FALLBACK_KEYS):
            normalized[action] = FALLBACK_KEYS[fallback_index]
            used_keys.add(FALLBACK_KEYS[fallback_index])
            fallback_index += 1
    return {action: normalized.get(action, "") for action in allowed_actions}


def _quote(value):
    escaped = str(value).replace('"', '\\"')
    return f'"{escaped}"'


def _is_axis_binding(value):
    if not value:
        return False
    if value[0] not in ("+", "-"):
        return False
    return value[1:].isdigit()


def to_retroarch_overrides(bindings, device_type, console=None):
    bindings = normalize_bindings(bindings, device_type, console=console)
    allowed_actions = get_actions_for_console(console)
    overrides = {}
    for action in allowed_actions:
        base_key = RETROARCH_BASE_KEYS[action]
        bind_value = bindings.get(action, "")
        if not bind_value:
            continue

        if device_type == "keyboard":
            overrides[base_key] = _quote(bind_value)
            continue

        # Gamepad: infer axis or button token.
        suffix = "_axis" if _is_axis_binding(bind_value) else "_btn"
        overrides[f"{base_key}{suffix}"] = _quote(bind_value)

    return overrides
