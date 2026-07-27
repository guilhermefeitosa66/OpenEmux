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

logger = logging.getLogger(__name__)

DEFAULT_NETWORK_CMD_PORT = 55355

#: RetroArch's own volume step per VOLUME_UP/VOLUME_DOWN command.
VOLUME_STEP_DB = 0.5

#: The slider's floor; RetroArch itself goes to -80 but everything below
#: -40 dB is inaudible in practice. 0 dB is unity gain.
MIN_VOLUME_DB = -40.0
MAX_VOLUME_DB = 0.0


def clamp_volume_db(value):
    try:
        level = float(value)
    except (TypeError, ValueError):
        return MAX_VOLUME_DB
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

    def send(self, command):
        """Send one command; True when the packet left, False otherwise."""
        payload = (command or "").strip()
        if not payload:
            return False
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.sendto(payload.encode("utf-8"), (self.host, self.port))
            return True
        except OSError as exc:
            logger.warning("retroarch command failed: cmd=%s error=%s", payload, exc)
            return False

    def send_repeated(self, command, count):
        """Send the same command ``count`` times (volume stepping)."""
        sent = 0
        for _ in range(max(0, int(count))):
            if self.send(command):
                sent += 1
        return sent
