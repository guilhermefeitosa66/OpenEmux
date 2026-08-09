"""Environment-driven feature flags (POC switches).

Flags live in the developer's ``.env`` (exported by ``make run``), so an
experiment can ship in the tree without touching config.yaml or the UI.
Everything here must stay importable before GTK: ``main.py`` consults the
embed flag to pick the GDK backend ahead of the first ``gi`` import.
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


def retroarch_embed_enabled():
    """POC: reparent the running RetroArch X11 window into an OpenEmux window."""
    return env_bool("OPENEMUX_RETROARCH_EMBED")


def retroarch_embed_frame_enabled():
    """POC: draw the CRT TV frame artwork around the embedded game screen."""
    return env_bool("OPENEMUX_RETROARCH_EMBED_FRAME")
