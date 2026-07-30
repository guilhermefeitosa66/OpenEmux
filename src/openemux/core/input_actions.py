from copy import deepcopy
from openemux.core.systems import resolve_system_id

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
    "turbo",
    "enable_hotkey",
    "menu_toggle",
    "save_state",
    "load_state",
    "state_slot_increase",
    "state_slot_decrease",
    "volume_up",
    "volume_down",
    "audio_mute",
    "fast_forward_toggle",
    "fullscreen_toggle",
    "reset_game",
]

#: Actions that stay unbound unless the user binds them: never auto-filled
#: with a default or a fallback key. Turbo is opt-in by nature -- an
#: accidental turbo modifier would corrupt normal play (issue #72) -- and the
#: newer hotkeys (slot stepping, volume) must not grab a fallback letter on
#: profiles that predate them.
OPTIONAL_ACTIONS = {
    "turbo",
    "state_slot_increase",
    "state_slot_decrease",
    "volume_up",
    "volume_down",
    "audio_mute",
    # Resetting throws away everything since the last save, so it is never
    # handed out by default -- and on a pad every reachable Select combo is
    # already taken, so any default would fire two hotkeys at once (#130).
    "reset_game",
}

FALLBACK_KEYS = ["g", "h", "j", "k", "l", "v", "b", "n", "m", "r", "t", "u", "i", "o", "p"]
GLOBAL_HOTKEY_ACTIONS = [
    "enable_hotkey",
    "menu_toggle",
    "save_state",
    "load_state",
    "state_slot_increase",
    "state_slot_decrease",
    "volume_up",
    "volume_down",
    "audio_mute",
    "fast_forward_toggle",
    "fullscreen_toggle",
    "reset_game",
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
    # No modifier on a keyboard. It exists for pads, where Select has to do
    # double duty because there are only ~10 buttons; a keyboard has plenty of
    # free keys and none of the hotkey defaults below collide with a gameplay
    # key, so a modifier would only add a keypress.
    #
    # This is also what already happened in practice: the previous default,
    # "right shift", is not a name RetroArch resolves, so input_enable_hotkey
    # was effectively unbound and the hotkeys fired directly. Fixing the key
    # translation (issue #144) would otherwise have silently turned that into
    # "hold Right Shift for every hotkey".
    "enable_hotkey": "",
    "menu_toggle": "f1",
    "save_state": "f2",
    "load_state": "f4",
    # RetroArch's own defaults for the volume hotkeys. The save-slot pair uses
    # the page keys rather than RetroArch's F6/F7, which would collide with
    # fast_forward_toggle below (issue #146).
    "volume_up": "kp_plus",
    "volume_down": "kp_minus",
    "state_slot_increase": "pageup",
    "state_slot_decrease": "pagedown",
    "audio_mute": "m",
    "fast_forward_toggle": "f6",
    "fullscreen_toggle": "f",
    "reset_game": "r",
    # Turbo stays unbound on a pad -- an accidental modifier there would
    # corrupt normal play (issue #72) -- but a dedicated key is safe.
    "turbo": "t",
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
    # On an Xbox-style pad button 8 is Guide; the thumbsticks are 9 and 10.
    "l3": "9",
    "r3": "10",
    # Hotkeys follow the Select-as-modifier convention, so every index stays
    # within the 0-10 range a common controller actually exposes (issue #124).
    # Anything above that made enable_hotkey unreachable, and because it gates
    # every other hotkey in RetroArch, all of them died with it.
    "enable_hotkey": "6",  # Select -- the modifier, deliberately also `select`
    "menu_toggle": "7",  # Select + Start
    "save_state": "2",  # Select + X
    "load_state": "3",  # Select + Y
    "fullscreen_toggle": "4",  # Select + L1
    "fast_forward_toggle": "5",  # Select + R1
}

#: Analog stick axes. Deliberately *not* user-facing actions: they stay out
#: of ACTION_ORDER and get_actions_for_console(), so Preferences rows, input
#: capture and normalize_bindings never see them.
#:
#: RetroArch's input_playerN_analog_dpad_mode cannot fold a stick onto the
#: D-pad without first knowing which axes that stick is, and nothing else in
#: a profile expresses that. Without these keys mode 1 has nothing to read and
#: silently does nothing under any configuration (issue #126).
#:
#: Numbering matches what the codebase already assumes for udev pads in
#: ui_gamepad.py: axes 0/1 are the left stick, 3/4 the right one. Axes 2 and 5
#: are the analog triggers and are bound as l2/r2 instead.
ANALOG_STICK_BINDINGS = {
    "l_x_minus": "-0",
    "l_x_plus": "+0",
    "l_y_minus": "-1",
    "l_y_plus": "+1",
    "r_x_minus": "-3",
    "r_x_plus": "+3",
    "r_y_minus": "-4",
    "r_y_plus": "+4",
}

#: Highest RetroArch port OpenEmux exposes in the UI.
MAX_PLAYERS = 4

#: Gameplay action -> RetroArch key suffix. These keys ARE per-player, so the
#: emitted key is ``input_player<N>_<suffix>``.
PLAYER_ACTION_SUFFIXES = {
    "up": "up",
    "down": "down",
    "left": "left",
    "right": "right",
    "a": "a",
    "b": "b",
    "x": "x",
    "y": "y",
    "start": "start",
    "select": "select",
    "l1": "l",
    "l2": "l2",
    "l3": "l3",
    "r1": "r",
    "r2": "r2",
    "r3": "r3",
    # The turbo modifier: hold it (or use single-button modes) to auto-fire.
    "turbo": "turbo",
}

#: Hotkeys are global in RetroArch: they are NOT numbered per player and must
#: stay exactly as-is regardless of which port is being written.
RETROARCH_GLOBAL_HOTKEY_KEYS = {
    "enable_hotkey": "input_enable_hotkey",
    "menu_toggle": "input_menu_toggle",
    "save_state": "input_save_state",
    "load_state": "input_load_state",
    "state_slot_increase": "input_state_slot_increase",
    "state_slot_decrease": "input_state_slot_decrease",
    "volume_up": "input_volume_up",
    "volume_down": "input_volume_down",
    "audio_mute": "input_audio_mute",
    "fast_forward_toggle": "input_toggle_fast_forward",
    "fullscreen_toggle": "input_toggle_fullscreen",
    # RetroArch's own soft reset. Handled by RetroArch while the game has
    # focus, which is the point: a button in the OpenEmux window needed an
    # alt-tab away from the game to reach it (issue #130).
    "reset_game": "input_reset",
}

#: Kept for backwards compatibility: the player-1 view of the key table.
RETROARCH_BASE_KEYS = {
    **{action: f"input_player1_{suffix}" for action, suffix in PLAYER_ACTION_SUFFIXES.items()},
    **RETROARCH_GLOBAL_HOTKEY_KEYS,
}


def retroarch_key_for(action, player=1):
    """Return the RetroArch config key for ``action`` on port ``player``.

    Global hotkeys ignore ``player`` entirely (RetroArch has a single set).
    """
    if action in RETROARCH_GLOBAL_HOTKEY_KEYS:
        return RETROARCH_GLOBAL_HOTKEY_KEYS[action]
    return f"input_player{int(player)}_{PLAYER_ACTION_SUFFIXES[action]}"


def default_keyboard_bindings():
    return deepcopy(DEFAULT_KEYBOARD_BINDINGS)


def default_gamepad_bindings():
    return deepcopy(DEFAULT_GAMEPAD_BINDINGS)


def get_actions_for_console(console):
    system_id = resolve_system_id(console)
    gameplay = CONSOLE_GAMEPLAY_ACTIONS.get(system_id, GAMEPLAY_ACTIONS_FULL)
    # Turbo rides along for every console: RetroArch implements it at the
    # frontend level, so it is not a per-console capability.
    return list(gameplay) + ["turbo"] + list(GLOBAL_HOTKEY_ACTIONS)


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
        if action in OPTIONAL_ACTIONS:
            continue
        default_value = defaults.get(action, "")
        # Hotkeys are exempt from the dedup on purpose: they only fire while
        # enable_hotkey is held, so sharing a token with a gameplay button is
        # what a modifier *is* (Select + X), not a conflict. Without this the
        # enable_hotkey default is rejected for colliding with `select` and
        # the whole hotkey set stays dead (issue #124).
        is_hotkey = action in GLOBAL_HOTKEY_ACTIONS
        if default_value and (is_hotkey or default_value not in used_keys):
            normalized[action] = default_value
            used_keys.add(default_value)
            continue
        # A gamepad has no letters. Handing a pad profile a keyboard fallback
        # key produces a binding that can never fire, which reads in the UI as
        # "bound" while doing nothing at all.
        #
        # A hotkey never takes a fallback either: it has a considered default
        # or it stays unbound. Handing enable_hotkey an arbitrary letter would
        # gate every other hotkey behind a key nobody chose.
        if device_type == "gamepad" or is_hotkey:
            continue
        while fallback_index < len(FALLBACK_KEYS) and FALLBACK_KEYS[fallback_index] in used_keys:
            fallback_index += 1
        if fallback_index < len(FALLBACK_KEYS):
            normalized[action] = FALLBACK_KEYS[fallback_index]
            used_keys.add(FALLBACK_KEYS[fallback_index])
            fallback_index += 1
    return {action: normalized.get(action, "") for action in allowed_actions}


#: GTK key name -> RetroArch key name, for the keys where the two vocabularies
#: disagree (issue #144). ``Gdk.keyval_name()`` is what input capture reads, and
#: RetroArch resolves config tokens through its own table; a name that is not in
#: that table resolves to nothing, so the binding reads as bound in Preferences
#: and can never fire.
#:
#: Names on the right were taken from RetroArch's own key table and from the
#: tokens RetroArch writes into retroarch.cfg (``num1``, ``rshift``, ``pageup``,
#: ``kp_equals``, ``backquote``, ``leftbracket``…). Anything not listed here is
#: already identical in both vocabularies -- letters, ``f1``-``f12``, ``minus``,
#: ``comma``, the arrow keys -- and passes through untouched.
#:
#: Legacy spellings this app itself produced are included so a profile saved
#: before the fix is healed on the next launch rather than needing a reset.
RETROARCH_KEY_NAMES = {
    # Top-row digits. RetroArch reserves the bare digits for nothing and files
    # these under num*, while the keypad ones are keypad*.
    **{str(digit): f"num{digit}" for digit in range(10)},
    **{f"kp_{digit}": f"keypad{digit}" for digit in range(10)},
    "equal": "equals",
    "kp_equal": "kp_equals",
    "kp_add": "kp_plus",
    "kp_subtract": "kp_minus",
    "kp_decimal": "kp_period",
    "page_up": "pageup",
    "page_down": "pagedown",
    "prior": "pageup",
    "next": "pagedown",
    "delete": "del",
    "return": "enter",
    "grave": "backquote",
    "bracketleft": "leftbracket",
    "bracketright": "rightbracket",
    "apostrophe": "quote",
    "caps_lock": "capslock",
    "num_lock": "numlock",
    "print": "print_screen",
    # Modifiers. RetroArch names the left-hand one bare and prefixes the right.
    "shift_l": "shift",
    "shift_r": "rshift",
    "control_l": "ctrl",
    "control_r": "rctrl",
    "alt_l": "alt",
    "alt_r": "ralt",
    "super_l": "lsuper",
    "super_r": "rsuper",
    "meta_l": "lmeta",
    "meta_r": "rmeta",
    # Spellings written by earlier versions of this app's own capture table.
    "left shift": "shift",
    "right shift": "rshift",
    "left ctrl": "ctrl",
    "right ctrl": "rctrl",
    "left alt": "alt",
    "right alt": "ralt",
    "left super": "lsuper",
    "right super": "rsuper",
}


#: RetroArch's own stock keyboard hotkeys and the key each one takes.
#:
#: The runtime override is *appended* to RetroArch's config, so a stock hotkey
#: sitting on a key we also bind still fires alongside ours: pressing `m` would
#: mute *and* cycle the shader (issue #146). Anything here that collides with an
#: OpenEmux binding is explicitly unbound.
RETROARCH_STOCK_KEYBOARD_HOTKEYS = {
    "input_rewind": "r",
    "input_shader_next": "m",
    "input_shader_prev": "n",
    "input_shader_toggle": "comma",
    "input_cheat_index_minus": "t",
    "input_cheat_index_plus": "y",
    "input_cheat_toggle": "u",
    "input_hold_slowmotion": "e",
    "input_hold_fast_forward": "l",
    "input_frame_advance": "k",
    "input_pause_toggle": "p",
    "input_screenshot": "f8",
    "input_fps_toggle": "f3",
    "input_desktop_menu_toggle": "f5",
    "input_grab_mouse_toggle": "f11",
    "input_game_focus_toggle": "scroll_lock",
    "input_netplay_game_watch": "i",
    "input_netplay_player_chat": "tilde",
    "input_exit_emulator": "escape",
    "input_volume_up": "add",
    "input_volume_down": "subtract",
    "input_state_slot_increase": "f7",
    "input_state_slot_decrease": "f6",
    "input_reset": "h",
    "input_audio_mute": "f9",
    "input_menu_toggle": "f1",
    "input_save_state": "f2",
    "input_load_state": "f4",
    "input_toggle_fast_forward": "f6",
    "input_toggle_fullscreen": "f",
}


def conflicting_stock_hotkeys(overrides):
    """RetroArch hotkeys to unbind because an OpenEmux binding took their key.

    ``overrides`` is the dict from :func:`to_retroarch_overrides`, which only
    ever holds binding keys. Gamepad entries carry a ``_btn``/``_axis`` suffix
    and are skipped: a pad token like ``"6"`` is a button, not a key.

    A hotkey we write ourselves is never cleared -- our value already wins.
    """
    claimed = set()
    for key, value in overrides.items():
        if key.endswith(("_btn", "_axis", "_mbtn")):
            continue
        claimed.add(str(value).strip('"').strip().lower())
    claimed.discard("")

    cleared = {}
    for key, stock_value in RETROARCH_STOCK_KEYBOARD_HOTKEYS.items():
        if key in overrides:
            continue
        if stock_value in claimed:
            cleared[key] = '"nul"'
    return cleared


def retroarch_key_token(value):
    """Translate one keyboard binding into the token RetroArch understands.

    Idempotent: a value already in RetroArch's vocabulary passes through, so
    this is safe to apply both at capture time and again when the runtime
    override is written.
    """
    if not value:
        return value
    return RETROARCH_KEY_NAMES.get(str(value).strip().lower(), value)


def _quote(value):
    escaped = str(value).replace('"', '\\"')
    return f'"{escaped}"'


def _is_axis_binding(value):
    if not value:
        return False
    if value[0] not in ("+", "-"):
        return False
    return value[1:].isdigit()


def to_retroarch_overrides(bindings, device_type, console=None, player=1):
    """Translate a binding map into RetroArch config keys for one port.

    ``player`` defaults to 1 so existing callers keep their behaviour. Ports
    other than 1 emit only the gameplay keys: the hotkeys are global, so
    writing them again from port 2+ would just clobber port 1's hotkeys.
    """
    player = int(player)
    bindings = normalize_bindings(bindings, device_type, console=console)
    allowed_actions = get_actions_for_console(console)
    overrides = {}
    for action in allowed_actions:
        if player != 1 and action in RETROARCH_GLOBAL_HOTKEY_KEYS:
            continue
        base_key = retroarch_key_for(action, player)
        bind_value = bindings.get(action, "")
        if not bind_value:
            continue

        if device_type == "keyboard":
            # Translated here as well as at capture time, so a profile saved
            # with a GTK spelling is healed without a reset (issue #144).
            overrides[base_key] = _quote(retroarch_key_token(bind_value))
            continue

        # Gamepad: infer axis or button token.
        suffix = "_axis" if _is_axis_binding(bind_value) else "_btn"
        overrides[f"{base_key}{suffix}"] = _quote(bind_value)

    if device_type == "gamepad":
        # The sticks are not bindable actions, but analog_dpad_mode is dead
        # without them and an analog-native console needs them to read the
        # stick at all (issue #126).
        for suffix, token in ANALOG_STICK_BINDINGS.items():
            overrides[f"input_player{player}_{suffix}_axis"] = _quote(token)

    return overrides
