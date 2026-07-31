"""Which RetroArch audio driver to hand the emulator (issue #176).

OpenEmux ships its own RetroArch build but launches it against the user's
global ``retroarch.cfg``. When that config names a driver the bundled build
was not compiled with, RetroArch cannot honour it::

    [ERROR] Couldn't find any audio driver named "pipewire"
    [WARN]  Going to default to first audio driver...
    [ERROR] failed_to_start_audio_driver

``pipewire`` is the case that bites: it is an ordinary value to find in a
config on a modern desktop, and the vendored RetroArch 1.22 does not have it
(``alsa, alsathread, tinyalsa, oss, jack, sdl2, pulse, null``). The fallback
lands on ``alsa``, which fails on a PipeWire host, and audio never starts.

Silence is not the symptom users report, though -- **speed** is. RetroArch
paces emulation off the audio clock, so with no audio device the pacing falls
through to vsync and the game runs at the monitor's refresh rate. On a 240 Hz
display that is a 60 fps core running four times too fast, with nothing on
screen to suggest audio had anything to do with it.

So the driver is chosen from what the host actually offers instead of from a
config that may have been written for a different RetroArch. ``pulse`` is the
answer whenever a PulseAudio socket exists, which covers native PulseAudio and
PipeWire alike (``pipewire-pulse`` serves the same socket) and exists in every
RetroArch build we launch, vendored or Flatpak. When no socket is found the
key is left unwritten: guessing there could only break a working setup.
"""

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

#: Written when a PulseAudio-compatible server is reachable. Present in both
#: the vendored RetroArch and the RetroArch Flatpak, and speaks to PipeWire
#: through pipewire-pulse just as well as to PulseAudio itself.
PULSE_DRIVER = "pulse"

#: ``audio_driver: auto`` in config.yaml -- detect from the host, the default.
AUTO = "auto"

#: ``audio_driver: inherit`` -- write nothing and let RetroArch use whatever
#: the global config says. The pre-#176 behaviour, kept as an escape hatch.
INHERIT = "inherit"


def _pulse_socket_paths():
    """Where a PulseAudio-compatible server's socket is normally found."""
    candidates = []
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    if runtime_dir:
        candidates.append(Path(runtime_dir) / "pulse" / "native")
    # PULSE_SERVER can point somewhere else entirely; only a unix: path is
    # checkable here, and a remote server is taken at its word.
    server = os.environ.get("PULSE_SERVER", "")
    if server.startswith("unix:"):
        candidates.append(Path(server[len("unix:"):]))
    return candidates


def host_has_pulse():
    """True when a PulseAudio-compatible server looks reachable."""
    server = os.environ.get("PULSE_SERVER", "")
    if server and not server.startswith("unix:"):
        # tcp: or a bare host name -- not checkable from here, but set on
        # purpose, so honour it.
        return True
    return any(path.exists() for path in _pulse_socket_paths())


def detect_audio_driver():
    """The driver to write, or ``None`` to leave the key alone."""
    if host_has_pulse():
        return PULSE_DRIVER
    return None


def resolve_audio_driver(setting):
    """Turn the ``runtime.retroarch.audio_driver`` setting into a driver name.

    ``auto`` (the default) detects from the host, ``inherit`` writes nothing,
    and any other value is passed through verbatim for the JACK/ALSA/sdl2
    setups that want to say so explicitly.
    """
    # Normalised before the emptiness check, so a whitespace-only value falls
    # back to auto rather than becoming an empty driver name in the override.
    value = (setting or "").strip().lower() or AUTO
    if value == INHERIT:
        return None
    if value == AUTO:
        driver = detect_audio_driver()
        if driver is None:
            logger.info(
                "no PulseAudio socket found; leaving audio_driver to RetroArch"
            )
        return driver
    return value
