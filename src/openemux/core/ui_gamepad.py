"""Continuous gamepad reading for navigating the OpenEmux UI itself.

Pure stdlib, no GTK. Builds on the primitives in ``gamepad_reader``: the same
udev-compatible token numbering (``TokenMapper``), the same device discovery
(``list_gamepads``) and the same threading contract — callbacks fire on the
reader thread and the UI marshals them with ``GLib.idle_add``.

Unlike ``GamepadCaptureReader`` (one press, then stop), the navigator runs for
the life of the window: it tracks presses *and* releases so held directions can
auto-repeat, it reads every connected pad at once (any controller navigates),
and it survives hotplug by rescanning whenever a device goes away.

The button layout is fixed to the RetroArch menu convention rather than the
per-console gameplay profiles: A confirms, B backs out, X opens the context
menu, Y favourites, L1/R1 switch console. Tokens use the udev numbering that
``DEFAULT_GAMEPAD_BINDINGS`` already assumes.
"""

import errno
import os
import select
import struct
import threading
import time

from openemux.core.gamepad_reader import (
    EV_ABS,
    EV_KEY,
    INPUT_EVENT_FORMAT,
    INPUT_EVENT_SIZE,
    TokenMapper,
    _read_axis_ranges,
    list_gamepads,
)

#: Fixed token -> UI action map (RetroArch menu convention, udev numbering).
#: Directions come from the D-pad hat and from the left stick (axes 0/1).
NAV_TOKEN_ACTIONS = {
    "h0up": "up",
    "h0down": "down",
    "h0left": "left",
    "h0right": "right",
    # Left stick (axes 0/1) and right stick (axes 3/4) both steer. Axes 2 and 5
    # are deliberately absent: those are the analog triggers on an Xbox-style
    # pad (DEFAULT_GAMEPAD_BINDINGS ships l2="+2"/r2="+5"), and a resting
    # trigger would otherwise read as a held direction.
    "-1": "up",
    "+1": "down",
    "-0": "left",
    "+0": "right",
    "-4": "up",
    "+4": "down",
    "-3": "left",
    "+3": "right",
    "0": "confirm",   # A (BTN_SOUTH)
    "1": "back",      # B (BTN_EAST)
    "2": "context",   # X (BTN_NORTH/WEST depending on pad; udev index 2)
    "3": "favorite",  # Y
    "4": "prev_console",  # L1
    "5": "next_console",  # R1
    "6": "menu",      # Select/Back/View: the primary menu, so Preferences,
                      # Shortcuts and About are reachable without a mouse
    "7": "confirm",   # Start
}

#: Actions that auto-repeat while their control is held.
REPEATABLE_ACTIONS = {"up", "down", "left", "right"}

#: Auto-repeat timing (seconds): delay before the first repeat, then interval.
REPEAT_DELAY = 0.40
REPEAT_INTERVAL = 0.12

#: How often to rescan for pads when none is connected (seconds).
RESCAN_INTERVAL = 1.0

#: select() timeout when idle; also bounds cancel latency.
IDLE_POLL = 0.2


def action_for_token(token):
    """Return the UI action for a binding token, or ``None``."""
    return NAV_TOKEN_ACTIONS.get((token or "").strip().lower())


class NavTokenTracker:
    """Stateful press/release tracking on top of ``TokenMapper``.

    ``TokenMapper.token_for_event`` only reports presses; navigation needs the
    releases too so held directions can repeat and stop repeating. ``feed``
    returns a list of ``(token, pressed)`` transitions for one evdev event.
    """

    def __init__(self, key_codes, abs_codes, axis_ranges=None):
        self.mapper = TokenMapper(key_codes, abs_codes, axis_ranges=axis_ranges)
        # keycode -> button token currently held
        self._held_buttons = {}
        # hat number -> {axis ("x"/"y") -> direction token currently held}
        self._held_hats = {}
        # ABS code -> axis token currently held ("+2"/"-2")
        self._held_axes = {}

    def feed(self, ev_type, code, value):
        if ev_type == EV_KEY:
            return self._feed_key(code, value)
        if ev_type == EV_ABS:
            if code in self.mapper.hat_map:
                return self._feed_hat(code, value)
            return self._feed_axis(code, value)
        return []

    def _feed_key(self, code, value):
        if value > 1:  # autorepeat from the kernel: we do our own
            return []
        token = self.mapper.token_for_event(EV_KEY, code, 1) if value == 1 else None
        if value == 1:
            if token is None:
                return []
            self._held_buttons[code] = token
            return [(token, True)]
        held = self._held_buttons.pop(code, None)
        return [(held, False)] if held else []

    def _feed_hat(self, code, value):
        hat_number, is_vertical = self.mapper.hat_map[code]
        axis = "y" if is_vertical else "x"
        held = self._held_hats.setdefault(hat_number, {})
        transitions = []
        previous = held.get(axis)
        token = self.mapper.token_for_event(EV_ABS, code, value) if value else None
        if previous and previous != token:
            transitions.append((previous, False))
            held.pop(axis, None)
        if token and token != previous:
            held[axis] = token
            transitions.append((token, True))
        return transitions

    def _feed_axis(self, code, value):
        token = self.mapper.token_for_event(EV_ABS, code, value)
        previous = self._held_axes.get(code)
        transitions = []
        if previous and previous != token:
            transitions.append((previous, False))
            self._held_axes.pop(code, None)
        if token and token != previous:
            self._held_axes[code] = token
            transitions.append((token, True))
        return transitions

    def release_all(self):
        """Forget every held control (used when suspending/losing a device)."""
        self._held_buttons.clear()
        self._held_hats.clear()
        self._held_axes.clear()


class RepeatClock:
    """Decides when a held direction fires again. Injectable clock for tests."""

    def __init__(self, delay=REPEAT_DELAY, interval=REPEAT_INTERVAL, now=time.monotonic):
        self.delay = delay
        self.interval = interval
        self._now = now
        # action -> next fire timestamp; only one direction repeats at a time
        # per action name, which is all UI navigation needs.
        self._next_fire = {}

    def press(self, action):
        self._next_fire[action] = self._now() + self.delay

    def release(self, action):
        self._next_fire.pop(action, None)

    def clear(self):
        self._next_fire.clear()

    def due_actions(self):
        """Actions whose repeat is due now; reschedules each one returned."""
        now = self._now()
        due = []
        for action, when in self._next_fire.items():
            if now >= when:
                due.append(action)
                self._next_fire[action] = now + self.interval
        return due

    def next_deadline(self):
        """Seconds until the earliest pending repeat, or ``None`` when idle."""
        if not self._next_fire:
            return None
        return max(0.0, min(self._next_fire.values()) - self._now())


class GamepadNavigator:
    """Reads every connected gamepad and emits UI navigation actions.

    ``on_action(action)`` fires for each press (and for repeats of held
    directions). ``on_connected(name)`` / ``on_disconnected()`` report hotplug.
    All callbacks run on the reader thread; marshal with ``GLib.idle_add``.

    ``should_suspend()`` is polled continuously; while it returns True events
    are drained and dropped (a running game owns the pad, and the preferences
    switch can turn UI navigation off without tearing the thread down).
    """

    def __init__(self, on_action, on_connected=None, on_disconnected=None, should_suspend=None):
        self._on_action = on_action
        self._on_connected = on_connected
        self._on_disconnected = on_disconnected
        self._should_suspend = should_suspend or (lambda: False)
        self._cancel = threading.Event()
        self._thread = None

    # -- lifecycle
    def start(self):
        if self._thread is not None:
            return
        self._cancel.clear()
        self._thread = threading.Thread(target=self._run, name="gamepad-nav", daemon=True)
        self._thread.start()

    def stop(self, join_timeout=1.0):
        self._cancel.set()
        thread = self._thread
        self._thread = None
        if thread is not None and thread.is_alive():
            thread.join(timeout=join_timeout)

    # -- internals
    def _emit(self, callback, *args):
        if callback and not self._cancel.is_set():
            callback(*args)

    def _open_pads(self):
        """Open every readable pad; returns {fd: (tracker, name)}."""
        opened = {}
        for device in list_gamepads():
            if not device.event_path:
                continue
            try:
                fd = os.open(device.event_path, os.O_RDONLY | os.O_NONBLOCK)
            except OSError:
                continue
            tracker = NavTokenTracker(
                device.key_codes,
                device.abs_codes,
                axis_ranges=_read_axis_ranges(fd, device.abs_codes),
            )
            opened[fd] = (tracker, device.name)
        return opened

    def _close_all(self, pads):
        for fd in pads:
            try:
                os.close(fd)
            except OSError:
                pass
        pads.clear()

    def _run(self):
        pads = {}
        repeat = RepeatClock()
        connected_announced = False
        was_suspended = False
        try:
            while not self._cancel.is_set():
                if not pads:
                    if connected_announced:
                        connected_announced = False
                        repeat.clear()
                        self._emit(self._on_disconnected)
                    pads = self._open_pads()
                    if not pads:
                        self._cancel.wait(RESCAN_INTERVAL)
                        continue
                    connected_announced = True
                    self._emit(self._on_connected, next(iter(pads.values()))[1])

                suspended = self._should_suspend()
                if suspended and not was_suspended:
                    # Drop held state so nothing "sticks" across a game session.
                    for tracker, _name in pads.values():
                        tracker.release_all()
                    repeat.clear()
                was_suspended = suspended

                timeout = IDLE_POLL
                deadline = repeat.next_deadline()
                if deadline is not None:
                    timeout = min(timeout, deadline)
                try:
                    readable, _w, _x = select.select(list(pads), [], [], timeout)
                except OSError:
                    self._close_all(pads)
                    continue

                for fd in readable:
                    if not self._read_fd(fd, pads, repeat, suspended):
                        # Device gone: close it and drop its repeats.
                        tracker, _name = pads.pop(fd)
                        tracker.release_all()
                        try:
                            os.close(fd)
                        except OSError:
                            pass
                if not pads:
                    continue

                if not suspended:
                    for action in repeat.due_actions():
                        self._emit(self._on_action, action)
        finally:
            self._close_all(pads)

    def _read_fd(self, fd, pads, repeat, suspended):
        """Read pending events from one pad. False when the device is gone."""
        tracker, _name = pads[fd]
        try:
            data = os.read(fd, INPUT_EVENT_SIZE * 64)
        except BlockingIOError:
            return True
        except OSError as exc:
            return exc.errno not in (errno.ENODEV, errno.EIO, errno.EBADF)
        if not data:
            return False

        for offset in range(0, len(data) - INPUT_EVENT_SIZE + 1, INPUT_EVENT_SIZE):
            chunk = data[offset:offset + INPUT_EVENT_SIZE]
            _sec, _usec, ev_type, code, value = struct.unpack(INPUT_EVENT_FORMAT, chunk)
            for token, pressed in tracker.feed(ev_type, code, value):
                action = action_for_token(token)
                if action is None:
                    continue
                if not pressed:
                    repeat.release(action)
                    continue
                if suspended:
                    continue
                if action in REPEATABLE_ACTIONS:
                    repeat.press(action)
                self._emit(self._on_action, action)
        return True
