"""RetroAchievements for the running game (issue #300).

RetroArch does the achievement work itself; what it needs is an account. It
takes a username and a **token** -- not a password -- so the password is
exchanged for one once, here, and never stored, never written into a launch
override and never logged.

The exchange is RetroAchievements' own ``login2`` request, the same one
RetroArch performs. Everything else -- unlocking, the overlay, hardcore mode
-- belongs to RetroArch and reaches it through the launch config.

Widget-free, one test file: the repo's core-module convention.
"""

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from openemux.core.atomic_write import atomic_write_text

logger = logging.getLogger(__name__)

LOGIN_URL = "https://retroachievements.org/dorequest.php"
REQUEST_TIMEOUT_SECONDS = 15

#: The RetroArch keys an account reaches the emulator through.
CHEEVOS_ENABLE_KEY = "cheevos_enable"
CHEEVOS_USERNAME_KEY = "cheevos_username"
CHEEVOS_TOKEN_KEY = "cheevos_token"
CHEEVOS_PASSWORD_KEY = "cheevos_password"
CHEEVOS_HARDCORE_KEY = "cheevos_hardcore_mode_enable"


class LoginError(Exception):
    """The account could not be signed in. Never carries the password."""


def _payload_from_error(error):
    """The JSON body of a failed response, or ``None`` if there is not one."""
    try:
        return json.loads(error.read().decode("utf-8"))
    except (OSError, ValueError, AttributeError):
        return None


def login(username, password, opener=None):
    """Exchange a password for a RetroAchievements token.

    Returns the token. Raises :class:`LoginError` with something a person can
    act on -- the service's own message where there is one.

    The password is used for this one request and then dropped: it is not
    returned, not stored and not logged, and the caller is expected to keep
    only the token.
    """
    username = (username or "").strip()
    if not username or not password:
        raise LoginError("A username and a password are needed")

    query = urllib.parse.urlencode({"r": "login2", "u": username, "p": password})
    request = urllib.request.Request(
        LOGIN_URL,
        data=query.encode("utf-8"),
        headers={"User-Agent": "OpenEmux"},
        method="POST",
    )
    open_url = opener or urllib.request.urlopen
    try:
        with open_url(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:  # nosec B310
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # Wrong details come back as 401 with the reason in the body, and an
        # HTTPError is also a response -- so read it rather than telling
        # someone who mistyped their password that the service is down.
        payload = _payload_from_error(exc)
        if payload is None:
            logger.warning(
                "retroachievements: login for %s failed with HTTP %s", username, exc.code
            )
            raise LoginError("RetroAchievements could not be reached") from exc
    except (OSError, ValueError) as exc:
        # Deliberately not the request: it carries the password.
        logger.warning("retroachievements: login failed for %s: %s", username, type(exc).__name__)
        raise LoginError("RetroAchievements could not be reached") from exc

    if not isinstance(payload, dict) or not payload.get("Success"):
        message = ""
        if isinstance(payload, dict):
            message = str(payload.get("Error") or "")
        logger.info("retroachievements: login refused for %s", username)
        raise LoginError(message or "RetroAchievements refused those details")

    token = str(payload.get("Token") or "")
    if not token:
        raise LoginError("RetroAchievements returned no token")
    logger.info("retroachievements: signed in as %s", username)
    return token


class AchievementsStore:
    """The account, in ``~/.openemux/cheevos.config``.

    Holds a username and a token. The password is never here: it is exchanged
    for the token once and dropped. The file is written owner-only, the way a
    credential file should be.
    """

    def __init__(self, config_file):
        self.config_file = Path(config_file).expanduser()

    def load(self):
        if not self.config_file.exists():
            return {}
        try:
            data = json.loads(self.config_file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning("retroachievements: unreadable store: %s", exc)
            return {}
        return data if isinstance(data, dict) else {}

    def save(self, data):
        # Owner-only from the moment it exists: the temporary file the atomic
        # write renames into place is created 0600 and never widened, so the
        # token is never briefly world-readable.
        atomic_write_text(
            self.config_file,
            json.dumps(data, indent=2, sort_keys=True),
            mode=0o600,
        )
        return data

    # -- account -----------------------------------------------------------
    def get_username(self):
        return str(self.load().get("username") or "")

    def get_token(self):
        return str(self.load().get("token") or "")

    def is_signed_in(self):
        return bool(self.get_username() and self.get_token())

    def set_account(self, username, token):
        data = self.load()
        data["username"] = (username or "").strip()
        data["token"] = token or ""
        return self.save(data)

    def sign_out(self):
        data = self.load()
        data.pop("username", None)
        data.pop("token", None)
        return self.save(data)

    # -- settings ----------------------------------------------------------
    def get_enabled(self):
        return bool(self.load().get("enabled", False))

    def set_enabled(self, enabled):
        data = self.load()
        data["enabled"] = bool(enabled)
        return self.save(data)

    def get_hardcore(self):
        """Hardcore mode: no save states, no rewind, no fast-forward.

        Off by default. It is what RetroAchievements calls the real thing, but
        turning it on silently would take save states away from someone who
        only wanted to see achievements.
        """
        return bool(self.load().get("hardcore", False))

    def set_hardcore(self, hardcore):
        data = self.load()
        data["hardcore"] = bool(hardcore)
        return self.save(data)


def runtime_overrides(store):
    """The RetroArch keys for this account, ready for the launch override.

    Achievements are off unless the user asked *and* an account is signed in.
    ``cheevos_password`` is written empty on purpose: a password must never
    reach a config file, and stating it keeps an older one from lingering.
    """
    if store is None or not store.get_enabled() or not store.is_signed_in():
        return {}
    return {
        CHEEVOS_ENABLE_KEY: '"true"',
        CHEEVOS_USERNAME_KEY: f'"{store.get_username()}"',
        CHEEVOS_TOKEN_KEY: f'"{store.get_token()}"',
        CHEEVOS_PASSWORD_KEY: '""',
        CHEEVOS_HARDCORE_KEY: '"true"' if store.get_hardcore() else '"false"',
    }
