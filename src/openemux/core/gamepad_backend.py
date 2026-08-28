"""Which gamepad backend this machine uses, and the three things it provides.

Two readers exist -- evdev (``gamepad_reader``, ``ui_gamepad``) and SDL2
(``gamepad_sdl``) -- and the UI must not care which one it holds. Everything
above this module asks here instead of importing a backend directly, so neither
platform carries the other's code path and a third one would be a branch in one
file (issue #118).

The pick follows the platform, and ``OPENEMUX_GAMEPAD_BACKEND`` overrides it.
That override is not a user setting: it is how the SDL path gets exercised on a
Linux desktop, which is where this project is developed and where the numbering
in ``gamepad_sdl`` can be checked against a real controller. An unknown value is
ignored with a warning rather than leaving the app with no gamepad at all.
"""

import logging
import os

from openemux.core.platform import IS_WINDOWS

logger = logging.getLogger(__name__)

EVDEV = "evdev"
SDL2 = "sdl2"

BACKEND_ENV = "OPENEMUX_GAMEPAD_BACKEND"


def backend_name(environ=None):
    """``"evdev"`` or ``"sdl2"``: which backend the readers below will build."""
    environ = os.environ if environ is None else environ
    override = (environ.get(BACKEND_ENV) or "").strip().lower()
    if override:
        if override in (EVDEV, SDL2):
            return override
        logger.warning(
            "%s=%r is not a known backend; using the platform default",
            BACKEND_ENV, override,
        )
    return SDL2 if IS_WINDOWS else EVDEV


def _sdl():
    # Imported here, not at module scope: on Linux the SDL module is never
    # loaded at all, so a fault in the ctypes binding cannot reach a platform
    # that does not use it.
    from openemux.core import gamepad_sdl

    return gamepad_sdl


def list_gamepads():
    """The connected pads, in the order RetroArch numbers its ports.

    Both backends return objects with a ``.name``; that and the ordering are
    all the port picker in the preferences dialog uses.
    """
    if backend_name() == SDL2:
        return _sdl().list_gamepads()
    from openemux.core.gamepad_reader import list_gamepads as evdev_list

    return evdev_list()


def make_capture_reader(on_token, on_error=None, device=None):
    """A one-press reader for the remapping screen.

    ``on_token(token)`` fires at most once, ``on_error(reason)`` instead when
    no pad can be read. Both run on the reader's thread.
    """
    if backend_name() == SDL2:
        return _sdl().SdlCaptureReader(on_token, on_error=on_error, device=device)
    from openemux.core.gamepad_reader import GamepadCaptureReader

    return GamepadCaptureReader(on_token, on_error=on_error, device=device)


def make_navigator(on_action, on_connected=None, on_disconnected=None, should_suspend=None):
    """The continuous reader that drives UI navigation."""
    if backend_name() == SDL2:
        return _sdl().SdlNavigator(
            on_action,
            on_connected=on_connected,
            on_disconnected=on_disconnected,
            should_suspend=should_suspend,
        )
    from openemux.core.ui_gamepad import GamepadNavigator

    return GamepadNavigator(
        on_action,
        on_connected=on_connected,
        on_disconnected=on_disconnected,
        should_suspend=should_suspend,
    )
