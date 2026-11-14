"""The Big Picture pause menu's state and the commands it sends (issue 957).

The menu is drawn by OpenEmux over a paused RetroArch, so every action is a
command on the channel the launcher opens for each game (stdin on Linux,
UDP on Windows; ``RuntimeManager.send_command``). The channel is
fire-and-forget -- RetroArch answers nothing -- so the toggles the menu
shows (fast forward, slow motion, mute) are OpenEmux's own record of what
it asked for during this session, and the save slot is OpenEmux's too:
saves and loads name the slot explicitly (``SAVE_STATE_SLOT n``), which
never depends on RetroArch's current slot.

Pure: ``send`` is any callable taking the command line and returning
whether it went out; ``clock`` gives the time.
"""

import time

PAUSE = "PAUSE_TOGGLE"
RESET = "RESET"
FAST_FORWARD = "FAST_FORWARD"
SLOW_MOTION = "SLOWMOTION"
SCREENSHOT = "SCREENSHOT"
MUTE = "MUTE"
MENU = "MENU_TOGGLE"
QUIT = "QUIT"

#: The slots the slider walks, the desktop's range (``slot_entries``).
MIN_SLOT = 0
MAX_SLOT = 9


def clamp_slot(slot):
    try:
        slot = int(slot)
    except (TypeError, ValueError):
        return MIN_SLOT
    return max(MIN_SLOT, min(MAX_SLOT, slot))


class PauseSession:
    """One game's pause-menu state, from launch to quit."""

    def __init__(self, send, clock=time.monotonic, slot=MIN_SLOT, hardcore=False):
        self._send = send
        self._clock = clock
        self.started_at = clock()
        self.slot = clamp_slot(slot)
        self.hardcore = bool(hardcore)
        self.fast_forward = False
        self.slow_motion = False
        self.muted = False
        self.paused = False

    # -- the clock -----------------------------------------------------------
    def played_minutes(self):
        """Whole minutes since the game started."""
        return max(0, int((self._clock() - self.started_at) // 60))

    # -- pausing ---------------------------------------------------------------
    def pause(self):
        """The menu opened: pause the game (once)."""
        if self.paused:
            return True
        if self._send(PAUSE):
            self.paused = True
            return True
        return False

    def resume(self):
        """Continue: unpause the game (once)."""
        if not self.paused:
            return True
        if self._send(PAUSE):
            self.paused = False
            return True
        return False

    # -- the slot ---------------------------------------------------------------
    def set_slot(self, slot):
        self.slot = clamp_slot(slot)
        return self.slot

    def step_slot(self, delta):
        return self.set_slot(self.slot + int(delta))

    # -- actions ------------------------------------------------------------------
    def save(self):
        return self._send(f"SAVE_STATE_SLOT {self.slot}")

    def load(self):
        return self._send(f"LOAD_STATE_SLOT {self.slot}")

    def load_slot(self, slot):
        self.set_slot(slot)
        return self.load()

    def restart(self):
        return self._send(RESET)

    def screenshot(self):
        return self._send(SCREENSHOT)

    def retroarch_menu(self):
        """RetroArch's own menu: the game is unpaused first, the menu pauses it."""
        self.resume()
        return self._send(MENU)

    def quit(self):
        return self._send(QUIT)

    @property
    def speed_allowed(self):
        """Fast forward and slow motion: off under RetroAchievements hardcore."""
        return not self.hardcore

    def toggle_fast_forward(self):
        if not self.speed_allowed:
            return False
        if self._send(FAST_FORWARD):
            self.fast_forward = not self.fast_forward
            return True
        return False

    def toggle_slow_motion(self):
        if not self.speed_allowed:
            return False
        if self._send(SLOW_MOTION):
            self.slow_motion = not self.slow_motion
            return True
        return False

    def toggle_mute(self):
        if self._send(MUTE):
            self.muted = not self.muted
            return True
        return False


__all__ = [
    "FAST_FORWARD",
    "MAX_SLOT",
    "MENU",
    "MIN_SLOT",
    "MUTE",
    "PAUSE",
    "PauseSession",
    "QUIT",
    "RESET",
    "SCREENSHOT",
    "SLOW_MOTION",
    "clamp_slot",
]
