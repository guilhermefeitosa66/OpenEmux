"""Where the library was left, so the next launch opens there (issue #383).

A file of its own, deliberately not ``config.yaml``. This is written every
time the user changes view -- a gamepad sweeping the sidebar is a write a
row -- and the ROM path, the ScreenScraper credentials, the per-console cores
and the input profiles have no business being rewritten that often. A few
dozen bytes, written atomically, is the whole of it.

It follows the pattern of the other stores (``ShaderConfigStore``,
``CartridgeColorStore``): resolved against the manager's config dir, so a
throwaway config directory keeps its own session file and the devbox and the
tests never touch the user's (issue #239). Unreadable is set aside rather than
overwritten (issue #209) -- the file is small and rebuilt by using the app,
but destroying something readable is never the recovery.
"""

import json
import logging
from pathlib import Path

from openemux.core.atomic_write import atomic_write_text
from openemux.core.paths import store_path
from openemux.core.state_recovery import quarantine_state_file

logger = logging.getLogger(__name__)

#: Beside config.yaml. The default is only for a caller with no ConfigManager
#: to ask; the app uses ``config_manager.session``.
DEFAULT_SESSION_FILE = store_path("session")

DEFAULT_SESSION = {"version": 1, "last_view": None}


class SessionStore:
    """The one thing worth remembering between launches: the view.

    Kept in memory after the first read and written on change, so the close
    handler and the per-navigation write cost one ``os.replace`` each and no
    re-parse.
    """

    def __init__(self, session_file=DEFAULT_SESSION_FILE):
        self.session_file = Path(session_file)
        self._data = None

    # -- persistence -------------------------------------------------------
    def load(self):
        if self._data is None:
            self._data = self._read()
        return dict(self._data)

    def _read(self):
        try:
            with open(self.session_file, "r", encoding="utf-8") as handle:
                raw = json.load(handle)
            if not isinstance(raw, dict):
                raise ValueError(f"not an object: {type(raw).__name__}")
        except FileNotFoundError:
            return dict(DEFAULT_SESSION)
        except (OSError, ValueError) as exc:
            quarantine_state_file(self.session_file, exc)
            return dict(DEFAULT_SESSION)
        data = dict(DEFAULT_SESSION)
        data["version"] = _as_int(raw.get("version"), DEFAULT_SESSION["version"])
        data["last_view"] = _as_view(raw.get("last_view"))
        return data

    def save(self):
        data = self.load()
        try:
            atomic_write_text(
                self.session_file, json.dumps(data, indent=2, sort_keys=True)
            )
        except OSError as exc:
            # Not worth a dialog: the app opens on the default next time.
            logger.info("session not saved: %s", exc)
            return False
        return True

    # -- the view ----------------------------------------------------------
    def get_last_view(self):
        """The scope id the app was last on, or ``None`` if it has none."""
        return self.load()["last_view"]

    def set_last_view(self, view):
        """Remember ``view``; returns whether anything was written.

        A no-op when the view has not actually moved, so the close handler
        after a navigation writes nothing.
        """
        value = _as_view(view)
        current = self.load()
        if current["last_view"] == value:
            return False
        current["last_view"] = value
        self._data = current
        return self.save()


def _as_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_view(value):
    """A scope id is a non-empty string; anything else is "nothing stored"."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None
