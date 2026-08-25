"""RetroArch's UDP network command interface (issue #69).

RetroArch listens on localhost UDP when ``network_cmd_enable`` is on (the
launcher writes it into every runtime override) and accepts plain-text
commands: ``VOLUME_UP`` / ``VOLUME_DOWN`` move the master volume in fixed
0.5 dB steps, ``MUTE`` toggles. There is no absolute set-volume command, so
an absolute slider is driven by stepping from a locally tracked level -- the
initial level is written as ``audio_volume`` at launch, which keeps the local
tracker honest.

Fire-and-forget on purpose: a lost UDP packet costs half a decibel, and the
UI must never block on the emulator.
"""

import logging
import socket
import threading
import time

logger = logging.getLogger(__name__)

DEFAULT_NETWORK_CMD_PORT = 55355

#: ``network_cmd_port`` set to this means "pick a free one per launch".
AUTO_NETWORK_CMD_PORT = 0


def pick_free_udp_port(host="127.0.0.1"):
    """A UDP port nothing is listening on, for one launch's command channel.

    RetroArch's own default is 55355, and it binds the socket with the reuse
    flags set: a standalone RetroArch the user started themselves binds the
    same port happily, and the kernel then hands each datagram to one of the
    two by a hash of the sending socket. A whole session's volume, save-state
    and QUIT commands can land in the wrong emulator, which looks exactly like
    the controls drifting out of sync (issue #227).

    Falls back to the default port if the probe fails -- a broken channel is
    still better than refusing to launch.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.bind((host, 0))
            return int(probe.getsockname()[1])
    except OSError as exc:
        logger.warning("could not pick a free command port: %s", exc)
        return DEFAULT_NETWORK_CMD_PORT

#: RetroArch's own volume step per VOLUME_UP/VOLUME_DOWN command.
VOLUME_STEP_DB = 0.5

#: One packet per RetroArch command-poll. Measured against the vendored
#: RetroArch 1.22 (issue #125 follow-up): it drains roughly one command
#: every 3-4 frames, NOT one per frame -- paced at 70 ms every packet
#: landed, at 40 ms ~10% were lost and at the old 16 ms cadence ~75% were,
#: which is exactly how "slider to max" stopped far below the top.
VOLUME_PACING_INTERVAL = 0.075

#: The slider's floor; RetroArch itself goes to -80 but everything below
#: -40 dB is inaudible in practice.
MIN_VOLUME_DB = -40.0
#: RetroArch's own top clamp (+12 dB, its OSD shows 398%); verified by
#: stepping past it on the vendored build. 0 dB is unity gain.
MAX_VOLUME_DB = 12.0
#: What garbage input falls back to: unity gain, never the +12 dB ceiling.
DEFAULT_VOLUME_DB = 0.0

#: How close (in dB) a slider drag must get to unity gain to snap onto it.
#: The sliders mark 0 dB with a tick, desktop-volume style, now that the
#: range continues past 100%; the snap makes landing exactly there easy.
VOLUME_SNAP_WINDOW_DB = 1.0

#: Extra distance walked when the target sits on RetroArch's top clamp.
#: RetroArch pins at +12 dB, so overshooting is free -- and because the
#: pin is exact, it re-synchronizes the tracker with the real level after
#: hotkey volume changes that happen behind the tracker's back. The
#: slider floor gets no such treatment: -40 dB is not a RetroArch bound
#: (it clamps at -80), but the floor engages mute in the UI instead.
SATURATION_MARGIN_DB = 15.0


def clamp_volume_db(value):
    try:
        level = float(value)
    except (TypeError, ValueError):
        return DEFAULT_VOLUME_DB
    return min(MAX_VOLUME_DB, max(MIN_VOLUME_DB, level))


def volume_steps(current_db, target_db):
    """The (command, count) to walk from one level to another in 0.5 dB steps.

    Returns ``(None, 0)`` when the levels already round to the same step.
    """
    delta = clamp_volume_db(target_db) - clamp_volume_db(current_db)
    count = int(round(abs(delta) / VOLUME_STEP_DB))
    if count == 0:
        return None, 0
    return ("VOLUME_UP" if delta > 0 else "VOLUME_DOWN"), count


class RetroArchCommandClient:
    """Sends network commands to a running RetroArch. Never raises."""

    def __init__(self, port=DEFAULT_NETWORK_CMD_PORT, host="127.0.0.1"):
        self.port = int(port)
        self.host = host
        # One reusable socket rather than one per packet: a volume walk is
        # dozens of datagrams and each fresh socket is a syscall pair for no
        # gain. Guarded because the pacer sends from its own thread.
        self._sock = None
        self._sock_lock = threading.Lock()

    def _ensure_socket(self):
        if self._sock is None:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        return self._sock

    def _drop_socket(self):
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    def close(self):
        with self._sock_lock:
            self._drop_socket()

    def send(self, command):
        """Send one command; True when the packet left, False otherwise."""
        payload = (command or "").strip()
        if not payload:
            return False
        try:
            with self._sock_lock:
                self._ensure_socket().sendto(
                    payload.encode("utf-8"), (self.host, self.port)
                )
            return True
        except OSError as exc:
            # A broken socket must not stay cached, or every later command
            # fails against the same dead handle.
            with self._sock_lock:
                self._drop_socket()
            logger.warning("retroarch command failed: cmd=%s error=%s", payload, exc)
            return False

    def send_repeated(self, command, count, delay=0.0):
        """Send the same command ``count`` times.

        ``delay`` seconds between packets. It defaults to 0 so this stays the
        honest primitive, but any caller stepping the volume wants
        ``VOLUME_PACING_INTERVAL`` -- see ``VolumePacer``.
        """
        sent = 0
        total = max(0, int(count))
        for index in range(total):
            if self.send(command):
                sent += 1
            if delay and index < total - 1:
                time.sleep(delay)
        return sent


class VolumePacer:
    """Walks a running game's volume toward a target, one packet per frame.

    RetroArch drains its command socket once per frame, so turning a slider
    drag into N back-to-back datagrams overruns the receive buffer and nearly
    all of them are dropped. That is the whole of issue #125, and it explains
    the reported asymmetry: MUTE is one packet in one frame and always lands.

    ``set_target`` only moves the goal, so a fast drag coalesces into a single
    walk instead of N overlapping bursts. The tracked level advances **only**
    for packets that actually left the socket -- assuming otherwise is how the
    tracker drifted permanently out of sync with RetroArch's real level.

    ``sleep`` is injectable so the pacing is assertable without real time.
    """

    def __init__(self, client, level=MAX_VOLUME_DB, sleep=time.sleep,
                 interval=VOLUME_PACING_INTERVAL):
        self._client = client
        self._sleep = sleep
        self._interval = interval
        self._lock = threading.Lock()
        self._level = clamp_volume_db(level)
        self._target = self._level
        self._worker = None

    @property
    def level(self):
        """The level RetroArch is at, as far as delivered packets can say."""
        with self._lock:
            return self._level

    @property
    def target(self):
        with self._lock:
            return self._target

    def reset(self, level):
        """Re-seed the tracker -- at launch RetroArch is told audio_volume."""
        with self._lock:
            self._level = clamp_volume_db(level)
            self._target = self._level

    def set_target(self, target_db):
        """Move the goal. Starts a worker only if one is not already walking."""
        target = clamp_volume_db(target_db)
        start = None
        with self._lock:
            if target >= MAX_VOLUME_DB:
                # Aiming at RetroArch's own clamp: walk extra steps so the
                # real level is pinned there even if the tracker had
                # drifted low, and the tracker ends exactly at the truth.
                self._level = min(
                    self._level, MAX_VOLUME_DB - SATURATION_MARGIN_DB
                )
            self._target = target
            if self._worker is None:
                # Assigned under the lock so a second caller cannot start a
                # second worker between the check and the assignment.
                self._worker = threading.Thread(
                    target=self._run, name="openemux-volume-pacer", daemon=True
                )
                start = self._worker
        if start is not None:
            start.start()
        return target

    def join(self, timeout=None):
        """Wait for the current walk to finish. Test/shutdown helper."""
        worker = self._worker
        if worker is not None:
            worker.join(timeout)

    def _run(self):
        while True:
            with self._lock:
                command, _count = volume_steps(self._level, self._target)
                if command is None:
                    self._worker = None
                    return
                step = VOLUME_STEP_DB if command == "VOLUME_UP" else -VOLUME_STEP_DB

            if not self._client.send(command):
                # The datagram never left. Stop rather than spin: the tracker
                # stays at what actually landed, so the next drag walks from
                # the truth instead of compounding the error.
                with self._lock:
                    self._worker = None
                return

            with self._lock:
                self._level = clamp_volume_db(self._level + step)
            self._sleep(self._interval)
