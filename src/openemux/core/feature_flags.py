"""Environment-driven feature flags (POC switches).

Flags live in the developer's ``.env`` (exported by ``make run``), so an
experiment can ship in the tree without touching config.yaml or the UI.
Everything here must stay importable before GTK.

An experiment that graduates leaves: the game window itself is a setting now
(``runtime.game_window``, issue #199), so only the CRT frame around it is
still flagged here.
"""

import os

_TRUE_VALUES = {"1", "true", "yes", "on"}


def env_bool(name, default=False):
    """Read a boolean env var; unset or blank falls back to ``default``."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if not value:
        return default
    return value in _TRUE_VALUES


def retroarch_embed_frame_enabled():
    """POC: draw the CRT TV frame artwork around the embedded game screen."""
    return env_bool("OPENEMUX_RETROARCH_EMBED_FRAME")
