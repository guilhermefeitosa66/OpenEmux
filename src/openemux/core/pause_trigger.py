"""Which pad buttons open the Big Picture pause menu during a game (issue 957).

While a game runs, RetroArch owns the pad and OpenEmux's navigator ignores
it. The navigator still reads the pad (evdev is not exclusive), so it can
watch for one gesture and open the pause menu over the paused game, as the
Android app's pause combo does. The gesture is a setting:

* ``guide``        -- a press of Guide (Xbox / PS / Home). The default:
  no game reads it, and OpenEmux's RetroArch override binds RetroArch's
  own menu to Select + Start, never to Guide.
* ``hold_start``   -- Start held for ``HOLD_SECONDS`` (Android's default).
  A short press of Start still reaches the game.
* ``start_select`` -- Start and Select down together.
* ``l3_r3``        -- both sticks pressed in together.
* ``off``          -- nothing opens it.

Tokens use the udev numbering the navigator reads with
(``ui_gamepad.NAV_TOKEN_ACTIONS``): 6 Select, 7 Start, 8 Guide, 9 L3,
10 R3. Pure: ``feed`` and ``poll`` take the time, the tests give it.
"""

GUIDE = "guide"
HOLD_START = "hold_start"
START_SELECT = "start_select"
L3_R3 = "l3_r3"
OFF = "off"

#: The choices, in the order Settings lists them.
MODES = (GUIDE, HOLD_START, START_SELECT, L3_R3, OFF)
DEFAULT_MODE = GUIDE

SELECT = "6"
START = "7"
GUIDE_TOKEN = "8"
L3 = "9"
R3 = "10"

#: How long Start must stay down for ``hold_start`` (Android's pause combo).
HOLD_SECONDS = 0.8

#: The buttons each chord mode needs down at once.
CHORDS = {
    START_SELECT: frozenset({START, SELECT}),
    L3_R3: frozenset({L3, R3}),
}


def normalize_mode(mode):
    """A stored mode back to a known one; anything else is the default."""
    return mode if mode in MODES else DEFAULT_MODE


class PauseTrigger:
    """Fed the pad's button edges, says when the pause gesture happened.

    ``feed(token, pressed, now)`` and ``poll(now)`` return True exactly once
    per gesture: a chord fires when its last button goes down and fires
    again only after one of them was released; a hold fires once per press.
    """

    def __init__(self, mode=DEFAULT_MODE):
        self.mode = normalize_mode(mode)
        self._held = set()
        self._start_down_at = None
        self._fired = False

    def set_mode(self, mode):
        self.mode = normalize_mode(mode)
        self.reset()

    def reset(self):
        """Forget every held button (a game started or ended)."""
        self._held.clear()
        self._start_down_at = None
        self._fired = False

    def feed(self, token, pressed, now):
        token = str(token or "").strip()
        if pressed:
            self._held.add(token)
        else:
            self._held.discard(token)
        mode = self.mode
        if mode == GUIDE:
            return bool(pressed and token == GUIDE_TOKEN)
        if mode == HOLD_START:
            if token == START:
                self._start_down_at = now if pressed else None
                if not pressed:
                    self._fired = False
            return self.poll(now)
        chord = CHORDS.get(mode)
        if chord is None:
            return False
        if not chord <= self._held:
            self._fired = False
            return False
        if self._fired:
            return False
        self._fired = True
        return True

    def poll(self, now):
        """The hold gesture's clock: True once Start was held long enough."""
        if self.mode != HOLD_START or self._start_down_at is None or self._fired:
            return False
        if now - self._start_down_at >= HOLD_SECONDS:
            self._fired = True
            return True
        return False

    def next_deadline(self, now):
        """Seconds until ``poll`` could fire, or None when nothing is pending."""
        if self.mode != HOLD_START or self._start_down_at is None or self._fired:
            return None
        return max(0.0, self._start_down_at + HOLD_SECONDS - now)


__all__ = [
    "DEFAULT_MODE",
    "GUIDE",
    "HOLD_SECONDS",
    "HOLD_START",
    "L3_R3",
    "MODES",
    "OFF",
    "PauseTrigger",
    "START_SELECT",
    "normalize_mode",
]
