"""The whole input configuration, owned by OpenEmux for its launches (issue #759).

The runtime override is *appended* to the user's own ``retroarch.cfg``, so any
input key OpenEmux did not write came from there: a hotkey rebound in
RetroArch, keyboard binds for a port OpenEmux does not enable, a menu combo, a
turbo setting. The game then ran on a mix of the two configurations and nobody
could tell which one won.

So every launch starts from RetroArch's own default for every input key
(``retroarch_input_defaults``, read out of the vendored binary) and lays
OpenEmux's values on top. Hotkeys OpenEmux does not expose keep RetroArch's
stock keys -- ``escape`` still quits, ``f1`` still opens the menu. The user's
file is never written; it simply stops contributing to input, and the launch
log names the keys it would have changed so a "my pad stopped being player 1"
report can be read off the log.
"""

import logging
from functools import lru_cache

from openemux.core import core_options
from openemux.core.retroarch_input_defaults import (
    GLOBAL_DEFAULTS,
    INDEX_SUFFIXES,
    PLAYER1_DEFAULTS,
    PLAYER_DEFAULTS,
    PLAYERS,
)

logger = logging.getLogger(__name__)

#: RetroArch's automatic core/game remap files re-map libretro buttons on top
#: of every bind -- the other way RetroArch's side still mixed into OpenEmux's
#: mapping. Off for OpenEmux launches only; the files are untouched and a
#: standalone RetroArch still loads them.
REMAP_OVERRIDES = {"auto_remaps_enable": '"false"'}

#: A hotkey whose stock value is this has no key at all.
UNBOUND = "nul"


def _player_values(player):
    values = dict(PLAYER_DEFAULTS)
    if player == 1:
        values.update(PLAYER1_DEFAULTS)
    for suffix in INDEX_SUFFIXES:
        values[suffix] = str(player - 1)
    return values


@lru_cache(maxsize=1)
def _baseline():
    values = dict(GLOBAL_DEFAULTS)
    for player in range(1, PLAYERS + 1):
        for suffix, value in _player_values(player).items():
            values[f"input_player{player}_{suffix}"] = value
    return values


def baseline_overrides():
    """``{key: '"value"'}`` for every input key RetroArch has, players 1-16.

    A fresh dict per call: the caller layers the launch's own values onto it.
    """
    overrides = {key: f'"{value}"' for key, value in _baseline().items()}
    overrides.update(REMAP_OVERRIDES)
    return overrides


def stock_keyboard_hotkeys():
    """RetroArch's stock keyboard hotkeys and the key each one takes.

    Every global bind with a key: no ``_btn``/``_axis``/``_mbtn`` suffix (those
    are pad and mouse binds) and not ``nul``. Settings that are not binds are
    told apart by being unbound-capable -- a hotkey has a ``_btn`` sibling.
    """
    hotkeys = {}
    for key, value in GLOBAL_DEFAULTS.items():
        if f"{key}_btn" not in GLOBAL_DEFAULTS or value == UNBOUND:
            continue
        hotkeys[key] = value
    return hotkeys


def read_cfg_values(path):
    """The user's ``retroarch.cfg`` as ``{key: value}``; ``{}`` when unreadable."""
    try:
        return core_options.read_options_file(path)
    except ValueError as exc:  # a file that is not UTF-8
        logger.debug("input baseline: cannot read %s: %s", path, exc)
        return {}


def _owned(key):
    return key.startswith("input_") or key in REMAP_OVERRIDES


def overridden_user_keys(user_values, written):
    """Names of the user's input keys this launch writes with another value.

    ``written`` is the launch's whole override, values quoted as in the file.
    Only keys the launch actually writes count -- a plumbing key the baseline
    leaves alone (the input driver, the overlay) still comes from the user.
    """
    names = []
    for key, value in (user_values or {}).items():
        if not _owned(key) or key not in written:
            continue
        if str(written[key]).strip('"') != str(value):
            names.append(key)
    return sorted(names)
