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
import logging
import os
import select
import struct
import threading
import time
from collections import namedtuple

from openemux.core.gamepad_reader import (
    EV_ABS,
    EV_KEY,
    INPUT_EVENT_FORMAT,
    INPUT_EVENT_SIZE,
    TokenMapper,
    _read_axis_ranges,
    list_gamepads,
)

logger = logging.getLogger(__name__)

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
    # The analog triggers, pressed direction only: the pad's Shift for range
    # selection (issue #78). The resting direction ("-2"/"-5") stays unmapped
    # so an idle trigger cannot read as held.
    "+2": "range",
    "+5": "range",
}

#: Actions that auto-repeat while their control is held.
REPEATABLE_ACTIONS = {"up", "down", "left", "right"}

#: Actions whose *held state* matters, emitted as ``<action>_on``/``_off``.
STATEFUL_ACTIONS = {"range"}

#: Actions with tap/long-press semantics: the tap is emitted on release, the
#: hold as ``<action>_hold`` when the delay elapses (issue #78: holding Ⓐ
#: enters selection mode; a tap still confirms).
HOLDABLE_ACTIONS = {"confirm"}

#: Auto-repeat timing (seconds): delay before the first repeat, then interval.
REPEAT_DELAY = 0.40
REPEAT_INTERVAL = 0.12

#: How long a holdable button must stay down to fire its hold action.
LONG_PRESS_DELAY = 0.5

#: How often to rescan for pads (seconds). Applies whether or not one is
#: already open: the scan used to run only while ``pads`` was empty, so a
#: second controller plugged in next to a working one was invisible to UI
#: navigation until the first was unplugged (issue #223).
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


class HoldClock:
    """Tap vs long-press for ``HOLDABLE_ACTIONS``. Injectable clock for tests.

    ``press`` arms the timer; ``due_actions`` reports holds whose delay
    elapsed (each fires once); ``release`` disarms and says whether the tap
    should still be emitted -- it should unless the hold already fired.
    """

    def __init__(self, delay=LONG_PRESS_DELAY, now=time.monotonic):
        self.delay = delay
        self._now = now
        self._deadline = {}
        self._fired = set()

    def press(self, action):
        self._deadline[action] = self._now() + self.delay
        self._fired.discard(action)

    def release(self, action):
        self._deadline.pop(action, None)
        fired = action in self._fired
        self._fired.discard(action)
        return not fired

    def due_actions(self):
        now = self._now()
        due = []
        for action, when in list(self._deadline.items()):
            if now >= when and action not in self._fired:
                self._fired.add(action)
                self._deadline.pop(action, None)
                due.append(action)
        return due

    def next_deadline(self):
        if not self._deadline:
            return None
        return max(0.0, min(self._deadline.values()) - self._now())

    def clear(self):
        self._deadline.clear()
        self._fired.clear()


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


class OpenPad(namedtuple("OpenPad", "tracker name path")):
    """One pad this reader holds open: its decoder, its name and its node."""

    __slots__ = ()


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

    def _open_pads(self, already_open=()):
        """Open every readable pad not already open; returns {fd: OpenPad}.

        ``already_open`` is the set of device paths this reader is holding, so
        a rescan next to a live pad adds the new one instead of opening a
        second descriptor onto the same device.
        """
        opened = {}
        for device in list_gamepads():
            if not device.event_path or device.event_path in already_open:
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
            opened[fd] = OpenPad(tracker, device.name, device.event_path)
        return opened

    def _close_all(self, pads):
        for fd in pads:
            try:
                os.close(fd)
            except OSError:
                pass
        pads.clear()

    def _suspended(self):
        """The suspend flag, with a failure counted as "suspended".

        The callback reaches into the window and the runtime manager, and this
        is a bare thread: an exception here is not caught by anything above and
        simply ends the reader, taking gamepad navigation down for the rest of
        the session (issue #223). Suspended is the safe answer -- navigation
        pauses for one loop rather than stopping forever, and the next call
        gets another chance.
        """
        try:
            return bool(self._should_suspend())
        except Exception:  # noqa: BLE001 - a caller's bug must not end the thread
            logger.warning("gamepad navigation: suspend check failed", exc_info=True)
            return True

    def _run(self):
        pads = {}
        repeat = RepeatClock()
        hold = HoldClock()
        connected_announced = False
        was_suspended = False
        next_rescan = 0.0
        try:
            while not self._cancel.is_set():
                # Rescan on a cadence rather than only when nothing is open, so
                # a pad plugged in next to a working one is picked up (#223).
                if time.monotonic() >= next_rescan:
                    next_rescan = time.monotonic() + RESCAN_INTERVAL
                    found = self._open_pads({pad.path for pad in pads.values()})
                    if found:
                        pads.update(found)
                if not pads:
                    if connected_announced:
                        connected_announced = False
                        repeat.clear()
                        self._emit(self._on_disconnected)
                    self._cancel.wait(RESCAN_INTERVAL)
                    continue
                if not connected_announced:
                    connected_announced = True
                    self._emit(self._on_connected, next(iter(pads.values())).name)

                suspended = self._suspended()
                if suspended and not was_suspended:
                    # Drop held state so nothing "sticks" across a game session.
                    for pad in pads.values():
                        pad.tracker.release_all()
                    repeat.clear()
                    hold.clear()
                was_suspended = suspended

                timeout = IDLE_POLL
                for deadline in (repeat.next_deadline(), hold.next_deadline()):
                    if deadline is not None:
                        timeout = min(timeout, deadline)
                try:
                    readable, _w, _x = select.select(list(pads), [], [], timeout)
                except OSError:
                    self._close_all(pads)
                    continue

                # Re-read after the block, not before it. select() waits up to
                # 200 ms, and the events it just reported arrived *during* that
                # wait: a button pressed within that window of an input capture
                # starting was both bound and acted on -- the double-handling
                # exclusive capture exists to prevent (issue #223).
                if readable:
                    suspended = self._suspended()
                    if suspended and not was_suspended:
                        for pad in pads.values():
                            pad.tracker.release_all()
                        repeat.clear()
                        hold.clear()
                    was_suspended = suspended

                for fd in readable:
                    if not self._read_fd(fd, pads, repeat, hold, suspended):
                        # Device gone: close it and drop its repeats.
                        pads.pop(fd).tracker.release_all()
                        try:
                            os.close(fd)
                        except OSError:
                            pass
                if not pads:
                    continue

                if not suspended:
                    for action in repeat.due_actions():
                        self._emit(self._on_action, action)
                    for action in hold.due_actions():
                        self._emit(self._on_action, f"{action}_hold")
        finally:
            self._close_all(pads)

    def _read_fd(self, fd, pads, repeat, hold, suspended):
        """Read pending events from one pad. False when the device is gone."""
        tracker = pads[fd].tracker
        try:
            data = os.read(fd, INPUT_EVENT_SIZE * 64)
        except BlockingIOError:
            return True
        except OSError as exc:
            # Anything other than "try again" drops the descriptor. Keeping it
            # in the select set on an unrecognised errno was a spin: select
            # reports it readable, the read raises, and around again at full
            # speed on one core (issue #223). The rescan re-opens the device if
            # it is still there, so a transient error costs a second at worst.
            if exc.errno not in (errno.ENODEV, errno.EIO, errno.EBADF):
                logger.warning(
                    "gamepad navigation: dropping %s after an unexpected read error: %s",
                    pads[fd].name,
                    exc,
                )
            return False
        if not data:
            return False

        for offset in range(0, len(data) - INPUT_EVENT_SIZE + 1, INPUT_EVENT_SIZE):
            chunk = data[offset:offset + INPUT_EVENT_SIZE]
            _sec, _usec, ev_type, code, value = struct.unpack(INPUT_EVENT_FORMAT, chunk)
            for token, pressed in tracker.feed(ev_type, code, value):
                action = action_for_token(token)
                if action is None:
                    continue
                if action in STATEFUL_ACTIONS:
                    # Held state matters (the triggers): report both edges.
                    if not suspended:
                        self._emit(self._on_action, f"{action}_{'on' if pressed else 'off'}")
                    continue
                if not pressed:
                    repeat.release(action)
                    if action in HOLDABLE_ACTIONS:
                        # The tap fires on release -- unless the long press
                        # already fired its hold action instead.
                        if hold.release(action) and not suspended:
                            self._emit(self._on_action, action)
                    continue
                if suspended:
                    continue
                if action in HOLDABLE_ACTIONS:
                    hold.press(action)
                    continue
                if action in REPEATABLE_ACTIONS:
                    repeat.press(action)
                self._emit(self._on_action, action)
        return True
