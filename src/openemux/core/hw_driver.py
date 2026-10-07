"""Which video driver RetroArch will end up on for a core (issue #471).

A core that renders on the GPU asks RetroArch for a context of its own --
OpenGL, OpenGL core profile, Vulkan -- and RetroArch *switches* its video
driver to match, mid-launch: the log says ``Using HW render, glcore driver
forced``. The two N64 cores do it from ``gl`` to ``glcore``. That used to cost
nothing visible, and now it does: the in-game bar's margin is a shader pass,
every launch carries a preset, and a preset only loads on the driver whose
format it is written in (``.glslp`` on ``gl``, ``.slangp`` on ``glcore`` and
``vulkan``). A ``.glslp`` handed to a ``glcore`` RetroArch is a black screen.
Turning the switch off is no way out: those cores then fail to load, or
crash.

So the launch starts RetroArch on the driver the core is going to ask for,
and nothing switches. Which one that is comes from, in order:

1. What this core asked for last time, read back from its launch log when the
   game ended (``remember_from_log``) -- exact from the second launch on.
2. A core known to ask for something its ``.info`` does not say
   (``KNOWN_DRIVERS``).
3. The ``.info``'s ``required_hw_api``, when it leaves no choice: a core that
   lists only core-profile OpenGL and/or Vulkan never asks for the legacy
   ``gl`` context.
4. Otherwise nothing: the configured driver stands. Software cores, which are
   most of them, never switch.
"""

import json
import logging
import re
from pathlib import Path

from openemux.core.platform import core_stem

logger = logging.getLogger(__name__)

#: RetroArch's log line for a switch, and the names it uses for each driver.
_FORCED_RE = re.compile(r"Using HW render, (\w+) driver forced")
_LOGGED_NAMES = {"opengl": "gl", "gl": "gl", "glcore": "glcore", "vulkan": "vulkan"}

#: How much of a launch log is read: the switch is logged while the video
#: driver starts, in the first few dozen lines.
HEAD_LIMIT_BYTES = 64 * 1024

#: Cores whose .info does not tell. parallel_n64 lists "OpenGL >= 3.0" first
#: and still asks for a 4.3 core-profile context (measured, RetroArch 1.22.2).
KNOWN_DRIVERS = {
    "parallel_n64": "glcore",
}

MEMORY_FILE = "hw_drivers.json"


def forced_driver(text):
    """The driver a launch log says RetroArch was switched to, or ``None``."""
    match = _FORCED_RE.search(text or "")
    if not match:
        return None
    return _LOGGED_NAMES.get(match.group(1).lower())


def _stem(core_path):
    name = Path(core_path).name
    stem = core_stem(name)
    return stem[: -len("_libretro")] if stem.endswith("_libretro") else stem


def driver_from_info(core_path):
    """What the ``.info`` leaves no choice about, or ``None``."""
    info_path = Path(core_path).with_suffix(".info")
    try:
        text = info_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    match = re.search(r'^\s*required_hw_api\s*=\s*"([^"]*)"', text, re.M)
    if not match:
        return None
    apis = [api.strip().lower() for api in match.group(1).split("|") if api.strip()]
    if any(api.startswith("opengl") and not api.startswith(("opengl core", "opengl es"))
           for api in apis):
        # The legacy context is on the list: which one it asks for depends on
        # the core's options and on what RetroArch prefers. Not ours to guess.
        return None
    if any(api.startswith("opengl core") for api in apis):
        return "glcore"
    if apis and all(api.startswith("vulkan") for api in apis):
        return "vulkan"
    return None


class HwDriverMemory:
    """What each core asked for the last time it ran, kept in the runtime dir."""

    def __init__(self, runtime_dir):
        self.path = Path(runtime_dir) / MEMORY_FILE

    def _load(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def get(self, core_path):
        value = self._load().get(_stem(core_path))
        return value if value in _LOGGED_NAMES.values() else None

    def remember(self, core_path, driver):
        data = self._load()
        stem = _stem(core_path)
        if data.get(stem) == driver:
            return
        data[stem] = driver
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        except OSError as exc:
            logger.warning("hw driver: cannot record %s for %s: %s", driver, stem, exc)

    def remember_from_log(self, core_path, log_path):
        """Record the switch a finished launch's log shows, if it shows one."""
        if not core_path or not log_path:
            return None
        try:
            with open(log_path, "r", encoding="utf-8", errors="replace") as handle:
                driver = forced_driver(handle.read(HEAD_LIMIT_BYTES))
        except OSError:
            return None
        if driver:
            self.remember(core_path, driver)
        return driver


def predicted_driver(core_path, memory):
    """The driver a core will make RetroArch switch to, or ``None`` for none."""
    if not core_path:
        return None
    return (
        memory.get(core_path)
        or KNOWN_DRIVERS.get(_stem(core_path))
        or driver_from_info(core_path)
    )
