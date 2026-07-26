"""Per-ROM cartridge shell colors (issue #79).

The palette on disk is the truth: a console's available colors are the
``<CONSOLE>-<color>.svg`` files sitting next to its base frame, so shipping a
new color is a pure art change. The table below only *orders* the known ids,
names them for i18n and gives each a swatch for the menu; an id found on disk
but missing here still works -- it shows up title-cased with a neutral swatch.

Storage mirrors the shader overrides (`ShaderConfigStore`): per-ROM overrides
keyed by absolute path, with an optional per-console default underneath, both
in ``~/.openemux/cartridge_colors.config``. Same shape, same edge cases --
rename follows the ROM, delete forgets it.
"""

import copy
from pathlib import Path

import yaml

from openemux.core.systems import SYSTEM_IDS, resolve_system_id

DEFAULT_CONFIG_DIR = Path.home() / ".openemux"
DEFAULT_CARTRIDGE_COLORS_FILE = DEFAULT_CONFIG_DIR / "cartridge_colors.config"

#: The shell as authored -- the absence of a color, not a color of its own.
DEFAULT_COLOR_ID = "default"

#: Known color ids in menu order: name key for i18n plus the menu swatch.
#: The swatch is the *base* tone from issue #79; the art derives its own
#: shades, so this is only what the little square in the menu shows.
CARTRIDGE_COLOR_TABLE = [
    (DEFAULT_COLOR_ID, "cartridge_color.default", None),
    ("black", "cartridge_color.black", "#26262A"),
    ("white", "cartridge_color.white", "#E8E4DA"),
    ("red", "cartridge_color.red", "#B23A34"),
    ("orange", "cartridge_color.orange", "#CC7A29"),
    ("yellow", "cartridge_color.yellow", "#D9A81F"),
    ("green", "cartridge_color.green", "#3F8C5B"),
    ("teal", "cartridge_color.teal", "#2C8A8A"),
    ("blue", "cartridge_color.blue", "#3167B0"),
    ("purple", "cartridge_color.purple", "#7A4FA3"),
    ("pink", "cartridge_color.pink", "#BE5289"),
    ("gold", "cartridge_color.gold", "#C6A02E"),
    ("clear", "cartridge_color.clear", "#B9C0C7"),
]

_TABLE_INDEX = {entry[0]: position for position, entry in enumerate(CARTRIDGE_COLOR_TABLE)}
_TABLE_BY_ID = {entry[0]: entry for entry in CARTRIDGE_COLOR_TABLE}

#: Swatch for an id the table does not know (a color someone dropped on disk).
UNKNOWN_SWATCH = "#9A9996"

DEFAULT_CARTRIDGE_COLOR_CONFIG = {
    "version": 1,
    # Per-console default shell, so "all my Mega Drive carts are red" is one
    # action. Absence means the authored (default) shell.
    "console_defaults": {},
    # Per-ROM overrides keyed by absolute ROM path. They win over the console
    # default; "follow the console" is the absence of an entry here.
    "rom_overrides": {},
}


def normalize_color_id(color_id):
    value = (color_id or "").strip().lower()
    return value or DEFAULT_COLOR_ID


def color_name_key(color_id):
    """The i18n key for a color id, or ``None`` for an id not in the table."""
    entry = _TABLE_BY_ID.get(normalize_color_id(color_id))
    return entry[1] if entry else None


def color_swatch(color_id):
    """The menu swatch hex for a color id (neutral for unknown ids)."""
    entry = _TABLE_BY_ID.get(normalize_color_id(color_id))
    if entry:
        return entry[2]
    return UNKNOWN_SWATCH


def order_color_ids(color_ids):
    """Sort ids into the table's menu order; unknown ids go last, sorted."""
    ids = {normalize_color_id(value) for value in color_ids or ()}
    known = [value for value in ids if value in _TABLE_INDEX]
    unknown = sorted(value for value in ids if value not in _TABLE_INDEX)
    return sorted(known, key=_TABLE_INDEX.get) + unknown


class CartridgeColorStore:
    def __init__(self, config_file=DEFAULT_CARTRIDGE_COLORS_FILE):
        self.config_file = Path(config_file).expanduser()

    def load(self):
        # Deep copies for the same reason the shader store takes them: the
        # nested dicts must never alias the module-level default.
        if not self.config_file.exists():
            return copy.deepcopy(DEFAULT_CARTRIDGE_COLOR_CONFIG)

        try:
            raw = yaml.safe_load(self.config_file.read_text(encoding="utf-8")) or {}
        except Exception:
            return copy.deepcopy(DEFAULT_CARTRIDGE_COLOR_CONFIG)

        data = copy.deepcopy(DEFAULT_CARTRIDGE_COLOR_CONFIG)
        data["version"] = int(raw.get("version", 1))

        defaults = {}
        for key, value in (raw.get("console_defaults") or {}).items():
            canonical = resolve_system_id(key)
            if canonical not in SYSTEM_IDS:
                continue
            color = normalize_color_id(value)
            if color != DEFAULT_COLOR_ID:
                defaults[canonical] = color
        data["console_defaults"] = defaults

        overrides = {}
        for key, value in (raw.get("rom_overrides") or {}).items():
            if not key:
                continue
            color = normalize_color_id(value)
            if color != DEFAULT_COLOR_ID:
                overrides[str(key)] = color
        data["rom_overrides"] = overrides
        return data

    def save(self, settings):
        payload = copy.deepcopy(DEFAULT_CARTRIDGE_COLOR_CONFIG)
        payload["version"] = int((settings or {}).get("version", 1))
        payload["console_defaults"] = {
            console: color
            for console, color in ((settings or {}).get("console_defaults") or {}).items()
            if console in SYSTEM_IDS and normalize_color_id(color) != DEFAULT_COLOR_ID
        }
        payload["rom_overrides"] = {
            str(key): normalize_color_id(color)
            for key, color in ((settings or {}).get("rom_overrides") or {}).items()
            if key and normalize_color_id(color) != DEFAULT_COLOR_ID
        }
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        self.config_file.write_text(yaml.safe_dump(payload, sort_keys=True), encoding="utf-8")
        return payload

    # -- per-console defaults ---------------------------------------------
    def get_console_color(self, console_id):
        canonical = resolve_system_id(console_id)
        return self.load().get("console_defaults", {}).get(canonical, DEFAULT_COLOR_ID)

    def set_console_color(self, console_id, color_id):
        canonical = resolve_system_id(console_id)
        if canonical not in SYSTEM_IDS:
            return self.load()
        data = self.load()
        defaults = data.setdefault("console_defaults", {})
        value = normalize_color_id(color_id)
        if value == DEFAULT_COLOR_ID:
            defaults.pop(canonical, None)
        else:
            defaults[canonical] = value
        return self.save(data)

    # -- per-ROM overrides -------------------------------------------------
    def get_rom_color(self, rom_path):
        """The ROM's own color override, or ``None`` to follow the console."""
        return self.load().get("rom_overrides", {}).get(str(rom_path))

    def get_effective_color(self, rom_path, console_id):
        """The shell that will actually draw: per-ROM first, then per-console."""
        override = self.get_rom_color(rom_path)
        if override:
            return override
        return self.get_console_color(console_id)

    def set_rom_color(self, rom_path, console_id, color_id):
        """Set (or with ``color_id=None`` clear) a ROM's shell color.

        Picking the console's own default clears the override too, so the file
        does not carry an entry that merely repeats the console setting.
        """
        data = self.load()
        overrides = data.setdefault("rom_overrides", {})
        key = str(rom_path)
        if color_id is None:
            overrides.pop(key, None)
            return self.save(data)
        value = normalize_color_id(color_id)
        if value == self.get_console_color(console_id):
            overrides.pop(key, None)
        else:
            overrides[key] = value
        return self.save(data)

    def repath_rom(self, old_path, new_path):
        """Follow a renamed ROM so its color is not orphaned."""
        data = self.load()
        overrides = data.get("rom_overrides", {})
        entry = overrides.pop(str(old_path), None)
        if entry is None:
            return
        overrides[str(new_path)] = entry
        self.save(data)

    def forget_rom(self, rom_path):
        """Drop a deleted ROM's color so the file does not accumulate dead entries."""
        data = self.load()
        overrides = data.get("rom_overrides", {})
        if overrides.pop(str(rom_path), None) is not None:
            self.save(data)
