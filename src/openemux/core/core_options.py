"""Per-console core options for the cores that can look better (issue #296).

Core options are *not* config keys: RetroArch keeps them in their own file and
``--appendconfig`` cannot carry them. What it can carry is
``core_options_path``, which points RetroArch at one options file for the
launch -- so a launch writes its own file and names it.

The catalog below is deliberately small and deliberately verified. Every key,
every value and every default was read back from the cores themselves: each
core was run once so RetroArch wrote its ``.opt`` file, and the value lists
were confirmed against the strings the core ships. An option written with a
vocabulary the core does not know is silently ignored, which is the one
failure mode this feature must not have -- so an unknown value is refused
here rather than written.

Widget-free, one test file: the repo's core-module convention.
"""

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


class CoreOption:
    """An option the user can pick, with the values its core actually accepts."""

    def __init__(self, key, label_key, values, default):
        self.key = key
        self.label_key = label_key
        self.values = list(values)
        self.default = default

    def is_valid(self, value):
        return value in self.values


#: Keyed on the core's filename stem, the way ``cores.config`` keys its
#: per-console choices. Only cores whose options were verified are here: a
#: core absent from this table simply has no Advanced group.
CORE_OPTIONS = {
    "mednafen_psx_hw": [
        CoreOption(
            "beetle_psx_hw_internal_resolution",
            "core_options.internal_resolution",
            ["1x(native)", "2x", "4x", "8x", "16x"],
            "1x(native)",
        ),
        CoreOption(
            "beetle_psx_hw_renderer",
            "core_options.renderer",
            ["hardware", "hardware_gl", "hardware_vk"],
            "hardware",
        ),
        CoreOption(
            "beetle_psx_hw_filter",
            "core_options.texture_filter",
            ["nearest", "bilinear", "3-point", "SABR", "xBR", "JINC2"],
            "nearest",
        ),
    ],
    "ppsspp": [
        CoreOption(
            "ppsspp_internal_resolution",
            "core_options.internal_resolution",
            [
                "480x272",
                "960x544",
                "1440x816",
                "1920x1088",
                "2400x1360",
                "2880x1632",
                "3360x1904",
                "3840x2176",
                "4320x2448",
                "4800x2720",
            ],
            "480x272",
        ),
        CoreOption(
            "ppsspp_texture_filtering",
            "core_options.texture_filter",
            ["Auto", "Auto max quality"],
            "Auto",
        ),
    ],
}


#: Values whose stored spelling is not what a person should be shown. Only
#: where the two genuinely differ: a resolution reads fine as "960x544" and a
#: filter as "bilinear", but "hardware_vk" names an API, not a setting.
VALUE_LABELS = {
    "hardware": "Hardware",
    "hardware_gl": "OpenGL",
    "hardware_vk": "Vulkan",
}


def value_label(value):
    """What the picker shows for a stored value."""
    return VALUE_LABELS.get(value, value)


def core_stem(core_filename):
    """``mednafen_psx_hw_libretro.so`` -> ``mednafen_psx_hw``."""
    if not core_filename:
        return ""
    name = Path(str(core_filename)).name
    for suffix in ("_libretro.so", "_libretro.dll", ".so"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def options_for_core(core_filename):
    """The options this core exposes, or ``[]`` when it has none here."""
    return list(CORE_OPTIONS.get(core_stem(core_filename), []))


def option_prefix(core_filename):
    """The prefix a core's own option keys share, or ``""``.

    Not the same thing as the file name: Beetle PSX HW ships as
    ``mednafen_psx_hw_libretro.so`` and names its options ``beetle_psx_hw_*``.
    The launcher recognises the core's existing options file by this prefix,
    so it has to come from the options themselves.
    """
    options = options_for_core(core_filename)
    if not options:
        return ""
    return os.path.commonprefix([option.key for option in options])


def option_for_key(core_filename, key):
    for option in options_for_core(core_filename):
        if option.key == key:
            return option
    return None


def sanitize(core_filename, chosen):
    """Drop anything this core would not understand.

    A value the core does not know is silently ignored by RetroArch, which
    looks exactly like the setting doing nothing -- so it never gets written.
    The default is dropped too: it is what the core does anyway, and leaving
    it out keeps the file to what the user actually changed.
    """
    clean = {}
    for key, value in (chosen or {}).items():
        option = option_for_key(core_filename, key)
        if option is None:
            logger.info("core_options: %s has no option %s", core_filename, key)
            continue
        if not option.is_valid(value):
            logger.warning("core_options: %r is not a value %s accepts", value, key)
            continue
        if value == option.default:
            continue
        clean[key] = value
    return clean


def render_options_file(chosen, inherited=None):
    """The text RetroArch reads: ``key = "value"``, one per line.

    ``inherited`` is whatever the user already configured for this core inside
    RetroArch itself; ours are applied on top rather than replacing it, so
    pointing RetroArch at our file for one launch does not quietly discard
    everything else they set.
    """
    merged = dict(inherited or {})
    merged.update(chosen or {})
    lines = [f'{key} = "{value}"' for key, value in sorted(merged.items())]
    return "\n".join(lines) + ("\n" if lines else "")


def read_options_file(path):
    """Parse a RetroArch options file into a dict. Missing file -> ``{}``."""
    path = Path(path)
    if not path.is_file():
        return {}
    values = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.partition("=")
            if not sep:
                continue
            values[key.strip()] = value.strip().strip('"')
    except OSError as exc:
        logger.warning("core_options: cannot read %s: %s", path, exc)
        return {}
    return values


class CoreOptionsStore:
    """Per-console core-option choices, in ``~/.openemux/core_options.config``.

    Keyed by console and then by option key, so the same core serving two
    consoles keeps a setting per console -- the way the shader and core
    stores already work.
    """

    def __init__(self, config_file):
        self.config_file = Path(config_file).expanduser()

    def load(self):
        if not self.config_file.exists():
            return {}
        try:
            data = json.loads(self.config_file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning("core_options: unreadable store: %s", exc)
            return {}
        return data if isinstance(data, dict) else {}

    def save(self, data):
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        self.config_file.write_text(
            json.dumps(data, indent=2, sort_keys=True), encoding="utf-8"
        )
        return data

    def get_for_console(self, console, core_filename):
        chosen = self.load().get(str(console), {})
        return sanitize(core_filename, chosen)

    def set_for_console(self, console, core_filename, key, value):
        """Set (or with ``value=None`` clear) one option for a console."""
        option = option_for_key(core_filename, key)
        if option is None:
            return self.get_for_console(console, core_filename)
        data = self.load()
        console_options = dict(data.get(str(console), {}))
        if value is None or value == option.default or not option.is_valid(value):
            console_options.pop(key, None)
        else:
            console_options[key] = value
        if console_options:
            data[str(console)] = console_options
        else:
            data.pop(str(console), None)
        self.save(data)
        return self.get_for_console(console, core_filename)
