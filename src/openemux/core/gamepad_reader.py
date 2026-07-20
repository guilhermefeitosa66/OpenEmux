"""Gamepad discovery and input capture for the input-mapping UI.

Pure stdlib, no GTK, no third-party dependencies.

The goal is to emit the *same* binding tokens that RetroArch would resolve for
the same physical control, so that a captured value actually works in-game.

RetroArch on Linux defaults to the ``udev`` joypad driver (``retroarch_launcher``
never sets ``input_joypad_driver``, so the RetroArch default applies). The udev
driver numbers controls like this:

* **Buttons** — it walks the device's EV_KEY capability bitmap in ascending
  keycode order starting at ``BTN_MISC`` (0x100) and assigns 0, 1, 2, ... to
  every advertised keycode. Token: a bare index, e.g. ``"3"``.
* **Axes** — it walks the EV_ABS capability bitmap in ascending ABS_* code
  order and assigns 0, 1, 2, ... Token: ``"+2"`` / ``"-2"``.
* **Hats** — ``ABS_HAT0X``..``ABS_HAT3Y`` (0x10..0x17) are *excluded* from the
  axis numbering and exposed as hats instead. Token: ``"h0up"``, ``"h0left"``...

That hat handling is why we emit ``h0up``/``h0down``/``h0left``/``h0right`` for
the D-Pad rather than axis tokens -- and it is consistent with
``DEFAULT_GAMEPAD_BINDINGS`` in ``input_actions.py``, which already ships
``"h0up"`` & friends as the D-Pad defaults.

Capability discovery is done by parsing ``/proc/bus/input/devices`` (no ioctl
needed, works unprivileged). Reading the actual events requires opening the
``/dev/input/event*`` node, which usually needs membership of the ``input``
group; when that fails we fall back to the legacy joydev API (``/dev/input/js*``),
whose numbering is *not* guaranteed to match udev's -- see ``uses_legacy_api``.
"""

import errno
import os
import select
import struct
import threading

# ----- evdev constants -------------------------------------------------------
EV_KEY = 0x01
EV_ABS = 0x03

BTN_MISC = 0x100
BTN_JOYSTICK = 0x120
BTN_GAMEPAD = 0x130  # a.k.a. BTN_SOUTH
KEY_MAX = 0x2FF

ABS_HAT0X = 0x10
ABS_HAT3Y = 0x17
ABS_MAX = 0x3F

PROC_INPUT_DEVICES = "/proc/bus/input/devices"

# struct input_event { struct timeval time; __u16 type; __u16 code; __s32 value; }
INPUT_EVENT_FORMAT = "llHHi"
INPUT_EVENT_SIZE = struct.calcsize(INPUT_EVENT_FORMAT)

# struct js_event { __u32 time; __s16 value; __u8 type; __u8 number; }
JS_EVENT_FORMAT = "IhBB"
JS_EVENT_SIZE = struct.calcsize(JS_EVENT_FORMAT)
JS_EVENT_BUTTON = 0x01
JS_EVENT_AXIS = 0x02
JS_EVENT_INIT = 0x80

# EVIOCGABS(abs) -> struct input_absinfo (6 * __s32)
ABSINFO_FORMAT = "6i"
ABSINFO_SIZE = struct.calcsize(ABSINFO_FORMAT)

DEFAULT_AXIS_MIN = -32768
DEFAULT_AXIS_MAX = 32767

#: Fraction of the half-range an axis must travel before it counts as a press.
AXIS_DEADZONE_RATIO = 0.5


class GamepadError(Exception):
    """Raised when no usable gamepad can be opened.

    ``reason`` is a stable machine-readable code the UI maps to a message:
    ``"no_gamepad"`` or ``"permission_denied"``.
    """

    def __init__(self, reason, message=""):
        super().__init__(message or reason)
        self.reason = reason


# ----- /proc/bus/input/devices parsing ---------------------------------------
def parse_bitmap(text, word_bits=64):
    """Parse a kernel ``B: KEY=...`` bitmap into a set of set bit indices.

    The kernel prints the bitmap as ``%lx`` words separated by spaces, most
    significant word first, with leading all-zero words trimmed. Each word
    therefore covers ``word_bits`` bits, and the *rightmost* word holds bits
    ``0..word_bits-1``.
    """
    bits = set()
    words = (text or "").split()
    if not words:
        return bits
    # Be forgiving: a word wider than 8 hex digits can only come from a 64-bit
    # kernel, regardless of what the caller guessed.
    if any(len(w) > 8 for w in words):
        word_bits = 64
    for offset, word in enumerate(reversed(words)):
        try:
            value = int(word, 16)
        except ValueError:
            continue
        base = offset * word_bits
        index = 0
        while value:
            if value & 1:
                bits.add(base + index)
            value >>= 1
            index += 1
    return bits


def parse_proc_input_devices(content):
    """Split ``/proc/bus/input/devices`` content into per-device dicts.

    Each entry has ``name``, ``handlers`` (list), ``key_codes`` (sorted list)
    and ``abs_codes`` (sorted list).
    """
    devices = []
    current = None

    def flush():
        if current is not None and (current["name"] or current["handlers"]):
            devices.append(current)

    for raw_line in (content or "").splitlines():
        line = raw_line.strip()
        if not line:
            flush()
            current = None
            continue
        if current is None:
            current = {"name": "", "handlers": [], "key_codes": [], "abs_codes": []}
        if line.startswith("N: Name="):
            current["name"] = line[len("N: Name="):].strip().strip('"')
        elif line.startswith("H: Handlers="):
            current["handlers"] = line[len("H: Handlers="):].split()
        elif line.startswith("B: KEY="):
            current["key_codes"] = sorted(parse_bitmap(line[len("B: KEY="):]))
        elif line.startswith("B: ABS="):
            current["abs_codes"] = sorted(parse_bitmap(line[len("B: ABS="):]))
    flush()
    return devices


def is_gamepad(entry):
    """A device is a gamepad if it advertises BTN_GAMEPAD or BTN_JOYSTICK."""
    key_codes = set(entry.get("key_codes") or ())
    return BTN_GAMEPAD in key_codes or BTN_JOYSTICK in key_codes


# ----- udev driver index maps ------------------------------------------------
def build_button_index_map(key_codes):
    """keycode -> udev button index, ascending keycode order from BTN_MISC."""
    index_map = {}
    next_index = 0
    for code in sorted(key_codes):
        if code < BTN_MISC or code > KEY_MAX:
            continue
        index_map[code] = next_index
        next_index += 1
    return index_map


def build_axis_index_map(abs_codes):
    """ABS code -> udev axis index, ascending, hats excluded."""
    index_map = {}
    next_index = 0
    for code in sorted(abs_codes):
        if code > ABS_MAX:
            continue
        if ABS_HAT0X <= code <= ABS_HAT3Y:
            continue  # hats are not part of the axis numbering
        index_map[code] = next_index
        next_index += 1
    return index_map


def build_hat_map(abs_codes):
    """ABS hat code -> (hat_number, is_vertical)."""
    hat_map = {}
    for code in sorted(abs_codes):
        if ABS_HAT0X <= code <= ABS_HAT3Y:
            hat_map[code] = ((code - ABS_HAT0X) // 2, bool((code - ABS_HAT0X) % 2))
    return hat_map


# ----- token helpers ---------------------------------------------------------
def axis_threshold(axis_min, axis_max, ratio=AXIS_DEADZONE_RATIO):
    """Deflection from zero needed for an axis to count as a press.

    RetroArch's udev driver compares the *raw* axis value against zero rather
    than against the midpoint of the reported range, so we do the same. This is
    what makes an analog trigger (range 0..1023, resting at 0) resolve to a
    positive token -- and it is why ``DEFAULT_GAMEPAD_BINDINGS`` ships
    ``l2="+2"`` / ``r2="+5"`` rather than signed half-range values.
    """
    return max(abs(axis_min), abs(axis_max)) * ratio


def describe_token(token):
    """Return ``(kind, detail)`` for a binding token, for human-friendly display.

    ``kind`` is one of ``"button"``, ``"axis"``, ``"hat"`` or ``"raw"``.
    """
    token = (token or "").strip().lower()
    if not token:
        return ("raw", "")
    if token.isdigit():
        return ("button", token)
    if token[0] in "+-" and token[1:].isdigit():
        return ("axis", token)
    if token.startswith("h") and len(token) > 2:
        rest = token[1:]
        digits = ""
        while rest and rest[0].isdigit():
            digits += rest[0]
            rest = rest[1:]
        if digits and rest in ("up", "down", "left", "right"):
            return ("hat", rest)
    return ("raw", token)


class TokenMapper:
    """Converts raw evdev events into RetroArch binding tokens for one device."""

    def __init__(self, key_codes, abs_codes, axis_ranges=None):
        self.button_index = build_button_index_map(key_codes)
        self.axis_index = build_axis_index_map(abs_codes)
        self.hat_map = build_hat_map(abs_codes)
        self.axis_ranges = dict(axis_ranges or {})

    def _range_for(self, code):
        return self.axis_ranges.get(code, (DEFAULT_AXIS_MIN, DEFAULT_AXIS_MAX))

    def token_for_event(self, ev_type, code, value):
        """Return a token for a *press*, or ``None`` for anything else.

        Key releases, axis movement inside the deadzone and hat centring all
        return ``None`` so the caller keeps waiting.
        """
        if ev_type == EV_KEY:
            if value <= 0:  # release (0) or autorepeat sentinel
                return None
            index = self.button_index.get(code)
            if index is None:
                return None
            return str(index)

        if ev_type == EV_ABS:
            if code in self.hat_map:
                hat_number, is_vertical = self.hat_map[code]
                if value == 0:
                    return None
                if is_vertical:
                    direction = "down" if value > 0 else "up"
                else:
                    direction = "right" if value > 0 else "left"
                return f"h{hat_number}{direction}"

            index = self.axis_index.get(code)
            if index is None:
                return None
            axis_min, axis_max = self._range_for(code)
            threshold = axis_threshold(axis_min, axis_max)
            if threshold <= 0 or abs(value) < threshold:
                return None
            return f"{'+' if value > 0 else '-'}{index}"

        return None


# ----- device discovery ------------------------------------------------------
class GamepadDevice:
    def __init__(self, name, event_path, js_path, key_codes, abs_codes):
        self.name = name
        self.event_path = event_path
        self.js_path = js_path
        self.key_codes = list(key_codes)
        self.abs_codes = list(abs_codes)

    def __repr__(self):  # pragma: no cover - debugging aid
        return f"<GamepadDevice {self.name!r} event={self.event_path} js={self.js_path}>"


def _read_proc_devices(path=PROC_INPUT_DEVICES):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError:
        return ""


def list_gamepads(proc_content=None, dev_dir="/dev/input"):
    """Return the connected gamepads, in /dev/input/event* order."""
    content = proc_content if proc_content is not None else _read_proc_devices()
    gamepads = []
    for entry in parse_proc_input_devices(content):
        if not is_gamepad(entry):
            continue
        event_path = None
        js_path = None
        for handler in entry.get("handlers") or ():
            if handler.startswith("event"):
                event_path = os.path.join(dev_dir, handler)
            elif handler.startswith("js"):
                js_path = os.path.join(dev_dir, handler)
        if not event_path and not js_path:
            continue
        gamepads.append(
            GamepadDevice(
                name=entry.get("name") or "Gamepad",
                event_path=event_path,
                js_path=js_path,
                key_codes=entry.get("key_codes") or [],
                abs_codes=entry.get("abs_codes") or [],
            )
        )
    return gamepads


def _read_axis_ranges(fd, abs_codes):
    """Best-effort EVIOCGABS lookup; falls back to the signed 16-bit range."""
    ranges = {}
    try:
        import fcntl
    except ImportError:  # pragma: no cover - non-Linux
        return ranges
    for code in abs_codes:
        if code > ABS_MAX:
            continue
        # EVIOCGABS(abs) = _IOR('E', 0x40 + abs, struct input_absinfo)
        request = (2 << 30) | (ABSINFO_SIZE << 16) | (ord("E") << 8) | (0x40 + code)
        try:
            raw = fcntl.ioctl(fd, request, b"\x00" * ABSINFO_SIZE)
        except OSError:
            continue
        _value, minimum, maximum, _fuzz, _flat, _res = struct.unpack(ABSINFO_FORMAT, raw)
        if maximum != minimum:
            ranges[code] = (minimum, maximum)
    return ranges


# ----- background capture ----------------------------------------------------
class GamepadCaptureReader:
    """Waits for one gamepad press on a background thread.

    ``on_token(token)`` is called at most once, from the reader thread; the UI is
    responsible for marshalling it onto the GTK main loop (``GLib.idle_add``).
    ``on_error(reason)`` is called instead when nothing could be opened.
    """

    POLL_INTERVAL = 0.2

    def __init__(self, on_token, on_error=None, device=None):
        self._on_token = on_token
        self._on_error = on_error
        self._device = device
        self._cancel = threading.Event()
        self._thread = None
        self.uses_legacy_api = False

    # -- lifecycle
    def start(self):
        if self._thread is not None:
            return
        self._cancel.clear()
        self._thread = threading.Thread(target=self._run, name="gamepad-capture", daemon=True)
        self._thread.start()

    def stop(self, join_timeout=1.0):
        self._cancel.set()
        thread = self._thread
        self._thread = None
        if thread is not None and thread.is_alive():
            thread.join(timeout=join_timeout)

    @property
    def cancelled(self):
        return self._cancel.is_set()

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
        device = self._device
        if device is None:
            gamepads = list_gamepads()
            if not gamepads:
                self._emit_error("no_gamepad")
                return
            device = gamepads[0]

        permission_error = False
        if device.event_path:
            try:
                self._read_evdev(device)
                return
            except PermissionError:
                permission_error = True
            except OSError as exc:
                if exc.errno in (errno.EACCES, errno.EPERM):
                    permission_error = True

        if self._cancel.is_set():
            return

        # Legacy joydev fallback. Its indices come from the joydev driver, which
        # does not necessarily agree with udev's numbering, but it is better than
        # refusing to capture at all when /dev/input/event* is unreadable.
        if device.js_path:
            try:
                self.uses_legacy_api = True
                self._read_joydev(device)
                return
            except PermissionError:
                permission_error = True
            except OSError as exc:
                if exc.errno in (errno.EACCES, errno.EPERM):
                    permission_error = True

        self._emit_error("permission_denied" if permission_error else "no_gamepad")

    def _wait_readable(self, fd):
        """Block until ``fd`` has data, honouring the cancel flag."""
        while not self._cancel.is_set():
            try:
                readable, _w, _x = select.select([fd], [], [], self.POLL_INTERVAL)
            except OSError:
                return False
            if readable:
                return True
        return False

    def _read_evdev(self, device):
        fd = os.open(device.event_path, os.O_RDONLY | os.O_NONBLOCK)
        try:
            mapper = TokenMapper(
                device.key_codes,
                device.abs_codes,
                axis_ranges=_read_axis_ranges(fd, device.abs_codes),
            )
            # Drain whatever is already queued so a stale event is not reported
            # as the user's press.
            _drain(fd, INPUT_EVENT_SIZE)
            while self._wait_readable(fd):
                try:
                    data = os.read(fd, INPUT_EVENT_SIZE * 32)
                except BlockingIOError:
                    continue
                except OSError:
                    return
                if not data:
                    return
                for offset in range(0, len(data) - INPUT_EVENT_SIZE + 1, INPUT_EVENT_SIZE):
                    chunk = data[offset:offset + INPUT_EVENT_SIZE]
                    _sec, _usec, ev_type, code, value = struct.unpack(INPUT_EVENT_FORMAT, chunk)
                    token = mapper.token_for_event(ev_type, code, value)
                    if token:
                        self._emit_token(token)
                        return
        finally:
            os.close(fd)

    def _read_joydev(self, device):
        fd = os.open(device.js_path, os.O_RDONLY | os.O_NONBLOCK)
        try:
            _drain(fd, JS_EVENT_SIZE)
            while self._wait_readable(fd):
                try:
                    data = os.read(fd, JS_EVENT_SIZE * 32)
                except BlockingIOError:
                    continue
                except OSError:
                    return
                if not data:
                    return
                for offset in range(0, len(data) - JS_EVENT_SIZE + 1, JS_EVENT_SIZE):
                    chunk = data[offset:offset + JS_EVENT_SIZE]
                    token = joydev_token(*struct.unpack(JS_EVENT_FORMAT, chunk))
                    if token:
                        self._emit_token(token)
                        return
        finally:
            os.close(fd)


def joydev_token(_time, value, ev_type, number):
    """Convert a legacy ``struct js_event`` into a binding token."""
    if ev_type & JS_EVENT_INIT:
        return None  # synthetic initial-state event, not a real press
    kind = ev_type & ~JS_EVENT_INIT
    if kind == JS_EVENT_BUTTON:
        return str(number) if value else None
    if kind == JS_EVENT_AXIS:
        threshold = int(DEFAULT_AXIS_MAX * AXIS_DEADZONE_RATIO)
        if abs(value) < threshold:
            return None
        return f"{'+' if value > 0 else '-'}{number}"
    return None


def _drain(fd, chunk_size):
    while True:
        try:
            if not os.read(fd, chunk_size * 32):
                return
        except (BlockingIOError, OSError):
            return
