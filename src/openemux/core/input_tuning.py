"""Global RetroArch input tuning (issues #154, #155).

These belong to the *hardware*, not to a console: a worn stick drifts the same
on every system, and vibration strength is a property of the pad. Keeping them
global is what stops "set the deadzone" from meaning "set it 31 times".

Every setting carries RetroArch's own default, and a value equal to that
default is not written into the runtime override at all -- so an untouched
install produces exactly the file it did before.
"""

#: name -> (retroarch key, default, kind, low, high)
#:
#: Defaults were read out of a real retroarch.cfg rather than assumed, which is
#: also how the turbo key turned out to be input_turbo_button and not
#: input_turbo_default_button.
INPUT_TUNING = {
    # A stick that no longer centres is one of the most common real-world
    # controller faults, and there was no way to compensate without leaving
    # OpenEmux to edit RetroArch's config by hand (issue #154).
    "analog_deadzone": ("input_analog_deadzone", 0.0, float, 0.0, 1.0),
    "analog_sensitivity": ("input_analog_sensitivity", 1.0, float, 0.0, 5.0),
    # How far an axis must tilt to read as a button press -- what the
    # Analog-to-Digital modes act on.
    "axis_threshold": ("input_axis_threshold", 0.5, float, 0.0, 1.0),
    "rumble_gain": ("input_rumble_gain", 100, int, 0, 100),
    # Grab the keyboard while a game runs so hotkeys do not leak to the
    # desktop. 0 off, 1 on menu toggle, 2 on content load.
    "auto_game_focus": ("input_auto_game_focus", 0, int, 0, 2),
    # Input latency: 0 early, 1 normal, 2 late.
    "poll_type_behavior": ("input_poll_type_behavior", 2, int, 0, 2),
    # Use the core's own button names, so a mapping screen can say "B = Jump".
    "descriptor_label_show": ("input_descriptor_label_show", True, bool, None, None),
    # RetroArch supports 16 ports; OpenEmux exposes 4 in the UI, but the
    # ceiling itself is worth being able to raise.
    "max_users": ("input_max_users", 8, int, 1, 16),
}


def default_for(name):
    return INPUT_TUNING[name][1]


def clamp(name, value):
    """Coerce ``value`` into the range RetroArch accepts for ``name``."""
    _key, default, kind, low, high = INPUT_TUNING[name]
    if kind is bool:
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value) if value is not None else default
    try:
        number = kind(value)
    except (TypeError, ValueError):
        return default
    return min(high, max(low, number))


def _format(kind, value):
    if kind is bool:
        return "true" if value else "false"
    if kind is float:
        return f"{value:.6f}"
    return str(int(value))


def to_retroarch_overrides(values):
    """RetroArch keys for every setting that differs from its own default.

    A value equal to RetroArch's default is left out: writing it would be
    noise, and it keeps an untouched install's override byte-identical to
    what it was before these settings existed.
    """
    overrides = {}
    for name, (key, default, kind, _low, _high) in INPUT_TUNING.items():
        value = clamp(name, (values or {}).get(name, default))
        if value == default:
            continue
        overrides[key] = f'"{_format(kind, value)}"'
    return overrides
