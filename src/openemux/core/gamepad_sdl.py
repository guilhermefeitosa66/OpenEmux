"""The SDL2 gamepad backend: the same binding tokens, read through SDL.

``gamepad_reader`` reads ``/dev/input/event*`` and numbers controls the way
RetroArch's ``udev`` joypad driver does. Neither of those exists on Windows, so
this module reads the same controls through SDL2 and emits the *same* token
vocabulary -- ``"3"`` for a button, ``"+1"``/``"-1"`` for an axis, ``"h0up"``
for a hat -- so everything above it (``input_actions``, the navigation map, the
profiles on disk) is untouched by which backend produced a token.

**Why the numbering matches.** RetroArch's SDL joypad driver reads the raw
``SDL_Joystick*`` state -- ``SDL_JoystickGetButton``, ``SDL_JoystickGetAxis``,
``SDL_JoystickGetHat`` -- so a token is an index into exactly the arrays this
module reads. It does *not* go through ``SDL_GameController``, whose remapped
numbering would disagree. That correspondence only holds while RetroArch is
actually using that driver, which is why ``retroarch_launcher`` pins
``input_joypad_driver = "sdl2"`` on Windows: RetroArch's default there is
``xinput``, whose button order is its own.

**One pump, many listeners.** SDL has a single per-process event queue, so two
readers polling it would steal each other's events -- and OpenEmux runs two at
once: the navigator that drives the UI, and the capture reader that waits for a
press while remapping. Both subscribe to :class:`SdlJoystickPump` instead, which
polls once and hands every transition to everyone. The navigator drops what it
receives while suspended; the capture reader sees the press either way.

SDL2 is loaded with ``ctypes`` -- no pip dependency, and nothing here is
imported unless the backend is actually selected (see ``gamepad_backend``).
"""

import ctypes
import ctypes.util
import logging
import struct
import threading
import time
from collections import deque

from openemux.core.gamepad_reader import (
    DEFAULT_AXIS_MAX,
    DEFAULT_AXIS_MIN,
    GamepadError,
    axis_threshold,
)
from openemux.core.ui_gamepad import IDLE_POLL, HoldClock, NavigatorCore, RepeatClock

logger = logging.getLogger(__name__)

# ----- SDL2 constants --------------------------------------------------------
SDL_INIT_JOYSTICK = 0x00000200

SDL_JOYAXISMOTION = 0x600
SDL_JOYHATMOTION = 0x602
SDL_JOYBUTTONDOWN = 0x603
SDL_JOYBUTTONUP = 0x604
SDL_JOYDEVICEADDED = 0x605
SDL_JOYDEVICEREMOVED = 0x606

SDL_HAT_CENTERED = 0x00
SDL_HAT_UP = 0x01
SDL_HAT_RIGHT = 0x02
SDL_HAT_DOWN = 0x04
SDL_HAT_LEFT = 0x08

SDL_ENABLE = 1

#: ``SDL_Event`` is a union padded to 56 bytes. We never build one field-wise;
#: the offsets below are read out of the raw buffer instead, which keeps the
#: binding to four small ``struct`` reads rather than a dozen ctypes unions.
SDL_EVENT_SIZE = 56

#: Shared prefix of every SDL_Joy*Event: type, timestamp, which.
_EVENT_HEADER = "=IIi"

#: Names to try, in order, when loading SDL2. The Windows bundle ships
#: ``SDL2.dll`` beside the app's own DLLs; on Linux the distribution package
#: installs the versioned soname.
SDL2_LIBRARY_NAMES = ("SDL2.dll", "libSDL2-2.0.so.0", "libSDL2.so.0", "libSDL2.so")

#: Deflection an axis needs before it reads as pressed. SDL always reports the
#: full signed 16-bit range, so unlike evdev there is nothing to query per axis.
AXIS_THRESHOLD = axis_threshold(DEFAULT_AXIS_MIN, DEFAULT_AXIS_MAX)


class SdlUnavailable(GamepadError):
    """SDL2 could not be loaded or initialised.

    A :class:`~openemux.core.gamepad_reader.GamepadError` so a caller that
    already handles "no usable gamepad" needs no new branch. ``reason`` stays
    ``"no_gamepad"``: from the user's side a controller they cannot use and a
    controller that is not there are the same sentence, and the real cause is
    in the log.
    """

    def __init__(self, message):
        super().__init__("no_gamepad", message)


# ----- the ctypes binding ----------------------------------------------------
class SdlLibrary:
    """The handful of SDL2 entry points this backend calls.

    A class rather than loose functions so a test can hand the pump a fake with
    the same six methods and drive the whole state machine on a machine with no
    controller -- which is every machine in CI.
    """

    def __init__(self, handle):
        self._sdl = handle
        handle.SDL_Init.argtypes = [ctypes.c_uint32]
        handle.SDL_Init.restype = ctypes.c_int
        handle.SDL_Quit.argtypes = []
        handle.SDL_Quit.restype = None
        handle.SDL_GetError.argtypes = []
        handle.SDL_GetError.restype = ctypes.c_char_p
        handle.SDL_SetHint.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
        handle.SDL_SetHint.restype = ctypes.c_int
        handle.SDL_PollEvent.argtypes = [ctypes.c_void_p]
        handle.SDL_PollEvent.restype = ctypes.c_int
        handle.SDL_JoystickEventState.argtypes = [ctypes.c_int]
        handle.SDL_JoystickEventState.restype = ctypes.c_int
        handle.SDL_NumJoysticks.argtypes = []
        handle.SDL_NumJoysticks.restype = ctypes.c_int
        handle.SDL_JoystickOpen.argtypes = [ctypes.c_int]
        handle.SDL_JoystickOpen.restype = ctypes.c_void_p
        handle.SDL_JoystickClose.argtypes = [ctypes.c_void_p]
        handle.SDL_JoystickClose.restype = None
        handle.SDL_JoystickInstanceID.argtypes = [ctypes.c_void_p]
        handle.SDL_JoystickInstanceID.restype = ctypes.c_int32
        handle.SDL_JoystickName.argtypes = [ctypes.c_void_p]
        handle.SDL_JoystickName.restype = ctypes.c_char_p
        handle.SDL_JoystickNameForIndex.argtypes = [ctypes.c_int]
        handle.SDL_JoystickNameForIndex.restype = ctypes.c_char_p
        handle.SDL_JoystickNumAxes.argtypes = [ctypes.c_void_p]
        handle.SDL_JoystickNumAxes.restype = ctypes.c_int
        handle.SDL_JoystickGetAxis.argtypes = [ctypes.c_void_p, ctypes.c_int]
        handle.SDL_JoystickGetAxis.restype = ctypes.c_int16

    # -- lifecycle
    def init(self):
        # Windows delivers device-arrival notifications to a hidden message
        # window SDL creates, and pumping it is the caller's job. Our poll runs
        # on a worker thread, so SDL gets a thread of its own for that instead
        # -- otherwise hotplug is invisible until something else pumps.
        self._sdl.SDL_SetHint(b"SDL_JOYSTICK_THREAD", b"1")
        # There is no SDL window to focus, but the hint costs nothing and makes
        # the intent explicit: OpenEmux reads the pad while its GTK window has
        # focus, which is not an SDL window at all.
        self._sdl.SDL_SetHint(b"SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS", b"1")
        if self._sdl.SDL_Init(SDL_INIT_JOYSTICK) != 0:
            raise SdlUnavailable(f"SDL_Init failed: {self.error()}")
        self._sdl.SDL_JoystickEventState(SDL_ENABLE)

    def quit(self):
        self._sdl.SDL_Quit()

    def error(self):
        raw = self._sdl.SDL_GetError()
        return (raw or b"").decode("utf-8", "replace")

    # -- events
    def poll_event(self):
        """The next queued event as raw bytes, or ``None`` when the queue is empty."""
        buffer = ctypes.create_string_buffer(SDL_EVENT_SIZE)
        if not self._sdl.SDL_PollEvent(ctypes.cast(buffer, ctypes.c_void_p)):
            return None
        return buffer.raw

    # -- devices
    def num_joysticks(self):
        return int(self._sdl.SDL_NumJoysticks())

    def name_for_index(self, index):
        raw = self._sdl.SDL_JoystickNameForIndex(index)
        return (raw or b"").decode("utf-8", "replace") or "Gamepad"

    def open(self, index):
        handle = self._sdl.SDL_JoystickOpen(index)
        return handle or None

    def close(self, handle):
        self._sdl.SDL_JoystickClose(handle)

    def instance_id(self, handle):
        return int(self._sdl.SDL_JoystickInstanceID(handle))

    def name(self, handle):
        raw = self._sdl.SDL_JoystickName(handle)
        return (raw or b"").decode("utf-8", "replace") or "Gamepad"

    def num_axes(self, handle):
        return int(self._sdl.SDL_JoystickNumAxes(handle))

    def axis(self, handle, index):
        return int(self._sdl.SDL_JoystickGetAxis(handle, index))


def load_sdl2(loader=None, names=SDL2_LIBRARY_NAMES):
    """Load SDL2 and return an :class:`SdlLibrary`, or raise :class:`SdlUnavailable`.

    Every name in ``names`` is tried before giving up, and only then the
    platform's own search (``ctypes.util.find_library``) -- a Linux developer
    running the backend by hand may have a differently-versioned soname than
    the one the Windows bundle ships.
    """
    loader = loader or ctypes.CDLL
    attempts = []
    for name in names:
        try:
            return SdlLibrary(loader(name))
        except OSError as exc:
            attempts.append(f"{name}: {exc}")
    found = ctypes.util.find_library("SDL2")
    if found:
        try:
            return SdlLibrary(loader(found))
        except OSError as exc:
            attempts.append(f"{found}: {exc}")
    raise SdlUnavailable("SDL2 could not be loaded (" + "; ".join(attempts) + ")")


# ----- event decoding --------------------------------------------------------
def event_type(raw):
    """The ``type`` field of a raw SDL event."""
    return struct.unpack_from("=I", raw, 0)[0]


def event_which(raw):
    """The ``which`` field: an instance id, or a device index for DEVICEADDED."""
    return struct.unpack_from(_EVENT_HEADER, raw, 0)[2]


def hat_direction_tokens(hat_number, value):
    """The set of tokens a hat bitmask stands for, e.g. ``{"h0up", "h0left"}``."""
    tokens = set()
    if value & SDL_HAT_UP:
        tokens.add(f"h{hat_number}up")
    if value & SDL_HAT_DOWN:
        tokens.add(f"h{hat_number}down")
    if value & SDL_HAT_LEFT:
        tokens.add(f"h{hat_number}left")
    if value & SDL_HAT_RIGHT:
        tokens.add(f"h{hat_number}right")
    return tokens


def axis_token(index, value, threshold=AXIS_THRESHOLD):
    """``"+1"``/``"-1"`` once the axis is past the deadzone, else ``None``."""
    if threshold <= 0 or abs(value) < threshold:
        return None
    return f"{'+' if value > 0 else '-'}{index}"


class SdlPadState:
    """Held-control state for one joystick, turned into transitions.

    The same job ``NavTokenTracker`` does for evdev, and for the same reason:
    SDL reports events, the app needs to know what is *held* so a direction can
    auto-repeat and stop repeating. Emits ``(token, pressed)`` pairs, and only
    on an actual change -- an axis nudged twice inside the deadzone produces
    nothing.
    """

    def __init__(self, name, instance_id):
        self.name = name
        self.instance_id = instance_id
        self._axes = {}   # axis index -> token currently held
        self._hats = {}   # hat number -> set of direction tokens held
        self._buttons = set()

    def seed_axis(self, index, value):
        """Record an axis's resting value without emitting a transition.

        A trigger rests at -32768 on SDL, which is well past the deadzone: read
        as an event it would look like a control the user is holding down from
        the moment the pad is opened. Seeding at open is the SDL equivalent of
        the evdev reader draining the queue before it listens.
        """
        token = axis_token(index, value)
        if token:
            self._axes[index] = token
        else:
            self._axes.pop(index, None)

    def feed_axis(self, index, value):
        token = axis_token(index, value)
        previous = self._axes.get(index)
        if token == previous:
            return []
        transitions = []
        if previous:
            transitions.append((previous, False))
            self._axes.pop(index, None)
        if token:
            self._axes[index] = token
            transitions.append((token, True))
        return transitions

    def feed_hat(self, hat_number, value):
        wanted = hat_direction_tokens(hat_number, value)
        held = self._hats.setdefault(hat_number, set())
        transitions = [(token, False) for token in sorted(held - wanted)]
        transitions += [(token, True) for token in sorted(wanted - held)]
        self._hats[hat_number] = wanted
        return transitions

    def feed_button(self, index, pressed):
        token = str(index)
        if pressed:
            if token in self._buttons:
                return []
            self._buttons.add(token)
            return [(token, True)]
        if token not in self._buttons:
            return []
        self._buttons.discard(token)
        return [(token, False)]

    def release_all(self):
        """Every held control, released. Used when the device goes away."""
        transitions = [(token, False) for token in sorted(self._buttons)]
        for tokens in self._hats.values():
            transitions += [(token, False) for token in sorted(tokens)]
        transitions += [(token, False) for token in sorted(self._axes.values())]
        self._buttons.clear()
        self._hats.clear()
        self._axes.clear()
        return transitions


# ----- the shared pump -------------------------------------------------------
class SdlJoystickPump:
    """Polls the SDL event queue on one thread and fans transitions out.

    Listeners are plain objects with three optional callbacks --
    ``on_transition(pad, token, pressed)``, ``on_connected(name)``,
    ``on_disconnected()`` -- called on the pump thread, which is the same
    contract the evdev readers have: the UI marshals with ``GLib.idle_add``.

    SDL is started when the first listener subscribes and shut down when the
    last one leaves, so nothing initialises it until a reader actually starts
    -- and a headless run of the suite never touches the library.
    """

    #: How long to sleep when the queue came up empty. 8 ms is half a frame at
    #: 60 Hz: fast enough that a press never feels late, idle enough that the
    #: thread is invisible in a profile.
    IDLE_SLEEP = 0.008

    #: How long ``subscribe`` waits for SDL to come up before returning anyway.
    START_TIMEOUT = 5.0

    def __init__(self, load=load_sdl2):
        self._load = load
        self._lock = threading.RLock()
        self._listeners = []
        self._thread = None
        self._cancel = threading.Event()
        self._pads = {}          # instance id -> SdlPadState
        self._handles = {}       # instance id -> SDL_Joystick*
        self._announced = False
        self._start_error = None

    # -- subscription
    def subscribe(self, listener):
        """Add a listener, starting SDL if this is the first one.

        Raises :class:`SdlUnavailable` when SDL cannot be brought up, so the
        caller can report it the way it reports "no gamepad".
        """
        ready = None
        announce = None
        with self._lock:
            self._listeners.append(listener)
            if self._thread is None:
                ready = self._spawn_locked()
            elif self._announced:
                # Joining a pump that already found a pad: say so straight
                # away, or the UI would wait for a hotplug that will not come.
                announce = next(iter(self._pads.values())).name if self._pads else "Gamepad"
        if ready is not None:
            # Waited for *outside* the lock. The reader thread takes the same
            # lock to record a start-up failure, so holding it here would keep
            # it from ever setting the flag we are waiting on: SDL2 missing
            # would surface as a five-second stall and then no error at all.
            ready.wait(timeout=self.START_TIMEOUT)
        elif announce is not None:
            _call(listener, "on_connected", announce)
        error = self._start_error
        if error is not None:
            self.unsubscribe(listener)
            raise error
        return listener

    def unsubscribe(self, listener):
        with self._lock:
            try:
                self._listeners.remove(listener)
            except ValueError:
                return
            if self._listeners:
                return
            thread = self._thread
            self._thread = None
            self._cancel.set()
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=2.0)

    def _spawn_locked(self):
        """Start the reader thread; the caller waits on the event returned.

        Waiting at all is what lets ``subscribe`` report a missing SDL2
        synchronously, instead of the caller waiting forever for a press that
        can never arrive.
        """
        self._cancel.clear()
        self._start_error = None
        ready = threading.Event()
        self._thread = threading.Thread(
            target=self._run, args=(ready,), name="gamepad-sdl", daemon=True
        )
        self._thread.start()
        return ready

    # -- the loop
    def _run(self, ready):
        try:
            sdl = self._load()
            sdl.init()
        except GamepadError as exc:
            with self._lock:
                self._start_error = exc
            logger.warning("gamepad (sdl2): %s", exc)
            ready.set()
            return
        ready.set()
        try:
            while not self._cancel.is_set():
                if not self._drain(sdl):
                    self._cancel.wait(self.IDLE_SLEEP)
        except Exception:  # noqa: BLE001 - a bare thread: log, do not vanish
            logger.warning("gamepad (sdl2): the reader stopped", exc_info=True)
        finally:
            self._close_all(sdl)
            try:
                sdl.quit()
            except Exception:  # noqa: BLE001 - teardown must not raise
                logger.debug("gamepad (sdl2): SDL_Quit failed", exc_info=True)

    def _drain(self, sdl):
        """Handle every queued event. False when there was nothing to do."""
        handled = False
        while not self._cancel.is_set():
            raw = sdl.poll_event()
            if raw is None:
                return handled
            handled = True
            self._handle(sdl, raw)
        return handled

    def _handle(self, sdl, raw):
        kind = event_type(raw)
        if kind == SDL_JOYDEVICEADDED:
            self._open(sdl, event_which(raw))
            return
        if kind == SDL_JOYDEVICEREMOVED:
            self._close(sdl, event_which(raw))
            return
        pad = self._pads.get(event_which(raw))
        if pad is None:
            return
        if kind == SDL_JOYAXISMOTION:
            index = struct.unpack_from("=B", raw, 12)[0]
            value = struct.unpack_from("=h", raw, 16)[0]
            self._emit(pad, pad.feed_axis(index, value))
        elif kind == SDL_JOYHATMOTION:
            number, value = struct.unpack_from("=BB", raw, 12)
            self._emit(pad, pad.feed_hat(number, value))
        elif kind in (SDL_JOYBUTTONDOWN, SDL_JOYBUTTONUP):
            index = struct.unpack_from("=B", raw, 12)[0]
            self._emit(pad, pad.feed_button(index, kind == SDL_JOYBUTTONDOWN))

    def _open(self, sdl, device_index):
        handle = sdl.open(device_index)
        if handle is None:
            logger.warning("gamepad (sdl2): could not open joystick %s: %s",
                           device_index, sdl.error())
            return
        instance = sdl.instance_id(handle)
        if instance in self._pads:  # already open; SDL re-announced it
            sdl.close(handle)
            return
        pad = SdlPadState(sdl.name(handle), instance)
        for axis in range(sdl.num_axes(handle)):
            pad.seed_axis(axis, sdl.axis(handle, axis))
        with self._lock:
            self._pads[instance] = pad
            self._handles[instance] = handle
            announce = not self._announced
            self._announced = True
        if announce:
            self._broadcast("on_connected", pad.name)

    def _close(self, sdl, instance):
        with self._lock:
            pad = self._pads.pop(instance, None)
            handle = self._handles.pop(instance, None)
        if pad is not None:
            # Release what was held, or a direction the user was pushing when
            # they unplugged the pad repeats forever.
            self._emit(pad, pad.release_all())
        if handle is not None:
            sdl.close(handle)
        with self._lock:
            gone = not self._pads and self._announced
            if gone:
                self._announced = False
        if gone:
            self._broadcast("on_disconnected")

    def _close_all(self, sdl):
        with self._lock:
            instances = list(self._handles)
        for instance in instances:
            self._close(sdl, instance)

    # -- fan-out
    def _emit(self, pad, transitions):
        for token, pressed in transitions:
            self._broadcast("on_transition", pad, token, pressed)

    def _broadcast(self, name, *args):
        with self._lock:
            listeners = list(self._listeners)
        for listener in listeners:
            _call(listener, name, *args)

    # -- introspection, for the readers
    def connected_pads(self):
        """The open pads, in the order SDL announced them."""
        with self._lock:
            return list(self._pads.values())


def _call(listener, name, *args):
    callback = getattr(listener, name, None)
    if callback is None:
        return
    try:
        callback(*args)
    except Exception:  # noqa: BLE001 - one listener's bug is not the pump's
        logger.warning("gamepad (sdl2): listener %s failed", name, exc_info=True)


_PUMP = None
_PUMP_LOCK = threading.Lock()


def shared_pump():
    """The process-wide pump. One SDL event queue means one poller."""
    global _PUMP
    with _PUMP_LOCK:
        if _PUMP is None:
            _PUMP = SdlJoystickPump()
        return _PUMP


def reset_shared_pump():
    """Drop the shared pump. Tests only -- nothing in the app replaces it."""
    global _PUMP
    with _PUMP_LOCK:
        _PUMP = None


# ----- device listing --------------------------------------------------------
class SdlGamepadDevice:
    """One connected pad, in the shape the UI's port picker expects.

    ``event_path``/``js_path`` are the evdev reader's fields and stay ``None``
    here; nothing outside that reader looks at them, and keeping the attributes
    means the port picker does not need to know which backend it is holding.
    """

    def __init__(self, name, index, instance_id=None):
        self.name = name
        self.index = index
        self.instance_id = instance_id
        self.event_path = None
        self.js_path = None
        self.key_codes = []
        self.abs_codes = []

    def __repr__(self):  # pragma: no cover - debugging aid
        return f"<SdlGamepadDevice {self.name!r} index={self.index}>"


class _ProbeListener:
    """A listener that wants nothing, used to hold the pump open while listing."""


def list_gamepads(pump=None, settle=0.25):
    """The connected pads in the order SDL announced them.

    That order is the one RetroArch's SDL driver assigns ports in, which is
    what makes "port 2 listens on the second pad" true in the remapping screen.

    Asked through the shared pump rather than with an SDL_Init/SDL_Quit pair of
    its own: ``SDL_Quit`` is process-wide, so listing while the navigator runs
    would shut the navigator's SDL down underneath it. Subscribing instead
    keeps one owner of the library. ``settle`` bounds how long a cold pump is
    given to report the pads already plugged in -- SDL queues one
    ``JOYDEVICEADDED`` per pad at init, so this is a poll cycle, not a wait.

    Returns ``[]`` rather than raising when SDL is missing: a caller asking
    what is connected wants an answer, and the reader that follows reports the
    failure properly.
    """
    pump = pump or shared_pump()
    probe = _ProbeListener()
    try:
        pump.subscribe(probe)
    except GamepadError as exc:
        logger.warning("gamepad (sdl2): %s", exc)
        return []
    try:
        deadline = time.monotonic() + settle
        while not pump.connected_pads() and time.monotonic() < deadline:
            time.sleep(0.01)
        return [
            SdlGamepadDevice(pad.name, index, pad.instance_id)
            for index, pad in enumerate(pump.connected_pads())
        ]
    finally:
        pump.unsubscribe(probe)


# ----- the two readers -------------------------------------------------------
class SdlCaptureReader:
    """Waits for one gamepad press, the SDL equivalent of ``GamepadCaptureReader``.

    Same contract, so the remapping screen does not know which backend it is
    holding: ``on_token(token)`` fires at most once from the reader thread,
    ``on_error(reason)`` fires instead when nothing usable is connected, and
    the UI marshals either onto the GTK loop.
    """

    #: How long a cold pump is given to report the pads that are already
    #: plugged in before this reader calls it "no gamepad".
    SETTLE = 0.5

    def __init__(self, on_token, on_error=None, device=None, pump=None):
        self._on_token = on_token
        self._on_error = on_error
        self._device = device
        self._pump = pump or shared_pump()
        self._cancel = threading.Event()
        self._thread = None
        #: Always False: SDL has no equivalent of the joydev fallback, whose
        #: numbering the evdev reader has to warn about. The attribute stays so
        #: the UI can ask either backend the same question.
        self.uses_legacy_api = False

    # -- lifecycle
    def start(self):
        if self._thread is not None:
            return
        self._cancel.clear()
        self._thread = threading.Thread(
            target=self._run, name="gamepad-capture-sdl", daemon=True
        )
        self._thread.start()

    def stop(self, join_timeout=1.0):
        self._cancel.set()
        thread = self._thread
        self._thread = None
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=join_timeout)

    @property
    def cancelled(self):
        return self._cancel.is_set()

    # -- pump listener
    def on_transition(self, pad, token, pressed):
        if not pressed or not self._matches(pad):
            return
        self._emit_token(token)

    def _matches(self, pad):
        """Is this the pad the caller asked to listen on?

        ``None`` means "whichever is there", which is what port 1 asks for.
        Otherwise the device came from :func:`list_gamepads`: prefer its SDL
        instance id, and fall back to its position when that instance is no
        longer connected -- the pad was replugged between listing and
        capturing, and the user still means "the second controller".
        """
        device = self._device
        if device is None:
            return True
        pads = self._pump.connected_pads()
        instance = getattr(device, "instance_id", None)
        if instance is not None and any(p.instance_id == instance for p in pads):
            return pad.instance_id == instance
        index = getattr(device, "index", None)
        if index is not None and 0 <= index < len(pads):
            return pad.instance_id == pads[index].instance_id
        return True

    # -- internals
    def _emit_token(self, token):
        if self._cancel.is_set():
            return
        self._cancel.set()
        if self._on_token:
            self._on_token(token)

    def _emit_error(self, reason):
        if self._cancel.is_set():
            return
        self._cancel.set()
        if self._on_error:
            self._on_error(reason)

    def _run(self):
        try:
            self._pump.subscribe(self)
        except GamepadError as exc:
            logger.warning("gamepad capture (sdl2): %s", exc)
            self._emit_error(exc.reason)
            return
        try:
            deadline = time.monotonic() + self.SETTLE
            while (not self._cancel.is_set()
                   and not self._pump.connected_pads()
                   and time.monotonic() < deadline):
                self._cancel.wait(0.02)
            if not self._pump.connected_pads():
                self._emit_error("no_gamepad")
                return
            # Then simply wait: the press arrives on the pump thread and sets
            # the flag, and so does stop().
            self._cancel.wait()
        finally:
            self._pump.unsubscribe(self)


class SdlNavigator(NavigatorCore):
    """Continuous UI navigation, the SDL equivalent of ``GamepadNavigator``.

    Transitions arrive on the pump thread and are queued; this reader's own
    thread drains the queue, so the auto-repeat and long-press clocks are
    touched by one thread only and need no lock. Draining also means the
    suspend flag is read *after* the wait that delivered the events, which is
    what stops a press made just as an input capture starts from being both
    bound and acted on (the same care ``GamepadNavigator`` takes, issue #223).
    """

    THREAD_NAME = "gamepad-nav-sdl"

    def __init__(self, *args, pump=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._pump = pump or shared_pump()
        self._queue = deque()
        self._reset_clocks = False

    # -- pump listener
    def on_transition(self, pad, token, pressed):
        self._queue.append((token, pressed))

    def on_connected(self, name):
        self._emit(self._on_connected, name)

    def on_disconnected(self):
        # The queue is deliberately *not* cleared: the pump released every held
        # control before announcing this, and those releases are what stop a
        # direction repeating. Dropping them would leave the grid scrolling
        # after the pad was unplugged mid-push. The clocks are cleared anyway,
        # once the queue has drained, in case the releases never arrived.
        self._reset_clocks = True
        self._emit(self._on_disconnected)

    # -- the loop
    def _run(self):
        try:
            self._pump.subscribe(self)
        except GamepadError as exc:
            logger.warning("gamepad navigation (sdl2): %s", exc)
            return
        repeat = RepeatClock()
        hold = HoldClock()
        was_suspended = False
        try:
            while not self._cancel.is_set():
                if not self._queue:
                    timeout = IDLE_POLL
                    for pending in (repeat.next_deadline(), hold.next_deadline()):
                        if pending is not None:
                            timeout = min(timeout, pending)
                    self._cancel.wait(timeout)
                    if self._cancel.is_set():
                        break

                suspended = self._suspended()
                if suspended and not was_suspended:
                    # Drop held state so nothing "sticks" across a game session.
                    self._queue.clear()
                    repeat.clear()
                    hold.clear()
                was_suspended = suspended

                while self._queue:
                    token, pressed = self._queue.popleft()
                    self._dispatch(token, pressed, repeat, hold, suspended)

                if self._reset_clocks:
                    self._reset_clocks = False
                    repeat.clear()
                    hold.clear()

                if not suspended:
                    for action in repeat.due_actions():
                        self._emit(self._on_action, action)
                    for action in hold.due_actions():
                        self._emit(self._on_action, f"{action}_hold")
        finally:
            self._pump.unsubscribe(self)
