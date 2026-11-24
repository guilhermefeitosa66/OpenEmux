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

import colorsys
import copy
import re
import secrets
import time
from pathlib import Path

import yaml

from openemux.core.atomic_write import atomic_write_text
from openemux.core.paths import from_stored_path, store_path, with_stored_keys
from openemux.core.state_recovery import quarantine_state_file
from openemux.core.systems import SYSTEM_IDS, resolve_system_id

DEFAULT_CARTRIDGE_COLORS_FILE = store_path("cartridge_colors")

#: How long a parse is trusted before the file is stat-ed again for a change
#: made behind the app's back. The app's own writes bypass this (``save``
#: drops the parse), so the only thing the delay costs is noticing an edit
#: made with a text editor half a second late -- and what it buys is a page
#: of cards that binds without one syscall per card (issue 907).
STAMP_TTL_S = 0.5

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

#: A color picked freely (issue 983) is stored as its own lowercase hex,
#: ``#rrggbb``, in the same maps as the named ids. No named id starts with
#: ``#``, so the two can never be mistaken for each other.
CUSTOM_COLOR_KEY = "cartridge_color.custom"
_CUSTOM_RE = re.compile(r"^#[0-9a-f]{6}$")
_HEX_INPUT_RE = re.compile(r"^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")

#: The palettes of the Custom Color dialog (issue 983). "shell" is the named
#: shells above; the presets are the Android skin editor's (``SkinPalettes``
#: in ``SkinPaint.kt``), same ids and hex values, so both apps offer the
#: same colors. A preset's name key is ``cartridge_color.palette.<id>`` with
#: ``-`` as ``_``.
SHELL_PALETTE_ID = "shell"
PRESET_PALETTES = [
    ("basic", ("#F472B6", "#EF4444", "#F97316", "#FACC15", "#22C55E", "#3B82F6", "#8B5CF6")),
    ("dracula", ("#282A36", "#44475A", "#BD93F9", "#FF79C6", "#8BE9FD", "#50FA7B", "#FFB86C")),
    ("pastel", ("#FBCFE8", "#FECACA", "#FED7AA", "#FEF08A", "#BBF7D0", "#BFDBFE", "#DDD6FE")),
    ("nord", ("#2E3440", "#4C566A", "#88C0D0", "#81A1C1", "#A3BE8C", "#EBCB8B", "#BF616A")),
    ("gruvbox", ("#282828", "#504945", "#CC241D", "#D79921", "#98971A", "#458588", "#B16286")),
    ("neon", ("#0D0221", "#FF2A6D", "#05D9E8", "#D1F7FF", "#F9C80E", "#7B2FF7", "#01FF89")),
    ("earth", ("#3E2C23", "#6B4F3A", "#A47148", "#D4A373", "#E9EDC9", "#CCD5AE", "#606C38")),
    ("green-screen", ("#0F380F", "#306230", "#8BAC0F", "#9BBC0F")),
]
_PRESETS_BY_ID = dict(PRESET_PALETTES)

#: Saved custom colors kept (the Android editor's ``RECENT_MAX``).
SAVED_COLORS_MAX = 8
#: Limits on the user's own palettes, so a hand-edited file stays sane.
USER_PALETTES_MAX = 50
PALETTE_COLORS_MAX = 32
PALETTE_NAME_MAX = 40
_USER_PALETTE_RE = re.compile(r"^user-[0-9a-f]{8}$")

DEFAULT_CARTRIDGE_COLOR_CONFIG = {
    "version": 1,
    # Per-console default shell, so "all my Mega Drive carts are red" is one
    # action. Absence means the authored (default) shell.
    "console_defaults": {},
    # Per-ROM overrides keyed by absolute ROM path. They win over the console
    # default; "follow the console" is the absence of an entry here.
    "rom_overrides": {},
    # Custom colors applied to a game, most recent first (issue 983).
    "saved_colors": [],
    # The user's own palettes: [{"id", "name", "colors"}], in creation order.
    "palettes": [],
    # The palette the dialog showed last.
    "palette": SHELL_PALETTE_ID,
}


def normalize_color_id(color_id):
    value = (color_id or "").strip().lower()
    return value or DEFAULT_COLOR_ID


def is_custom_color(color_id):
    """True for a freely picked color, stored as ``#rrggbb``."""
    return bool(_CUSTOM_RE.match(normalize_color_id(color_id)))


def parse_hex(text):
    """A typed color as a stored custom id (``#rrggbb``), or ``None``.

    Takes what a person types into a hex field: with or without the ``#``,
    either case, and the three-digit shorthand.
    """
    match = _HEX_INPUT_RE.match((text or "").strip())
    if not match:
        return None
    digits = match.group(1).lower()
    if len(digits) == 3:
        digits = "".join(ch * 2 for ch in digits)
    return f"#{digits}"


def hex_to_rgb(color_hex):
    """``#rrggbb`` as three 0-255 ints."""
    value = parse_hex(color_hex)
    if value is None:
        raise ValueError(f"not a hex color: {color_hex!r}")
    return tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))


def hex_to_hsv(color_hex):
    """``#rrggbb`` as (hue in degrees 0-360, saturation 0-1, value 0-1)."""
    r, g, b = (channel / 255 for channel in hex_to_rgb(color_hex))
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    return h * 360.0, s, v


def hsv_to_hex(hue, saturation, value):
    """(hue in degrees, saturation 0-1, value 0-1) as a stored custom id."""
    hue = (float(hue) % 360.0) / 360.0
    saturation = min(1.0, max(0.0, float(saturation)))
    value = min(1.0, max(0.0, float(value)))
    r, g, b = colorsys.hsv_to_rgb(hue, saturation, value)
    return "#" + "".join(f"{round(channel * 255):02x}" for channel in (r, g, b))


def color_name_key(color_id):
    """The i18n key for a color id, or ``None`` for an id not in the table."""
    entry = _TABLE_BY_ID.get(normalize_color_id(color_id))
    if entry:
        return entry[1]
    return CUSTOM_COLOR_KEY if is_custom_color(color_id) else None


def color_swatch(color_id):
    """The menu swatch hex for a color id (neutral for unknown ids)."""
    entry = _TABLE_BY_ID.get(normalize_color_id(color_id))
    if entry:
        return entry[2]
    if is_custom_color(color_id):
        return normalize_color_id(color_id)
    return UNKNOWN_SWATCH


def order_color_ids(color_ids):
    """Sort ids into the table's menu order; unknown ids go last, sorted."""
    ids = {normalize_color_id(value) for value in color_ids or ()}
    known = [value for value in ids if value in _TABLE_INDEX]
    unknown = sorted(value for value in ids if value not in _TABLE_INDEX)
    return sorted(known, key=_TABLE_INDEX.get) + unknown


def custom_color_choices(saved, override):
    """The custom colors a game's color choices list (issue 983).

    The game's own custom color first when it is not among the saved ones
    (it came by Share, or was removed from them), then the saved colors.
    """
    choices = list(saved or ())
    if is_custom_color(override):
        own = normalize_color_id(override)
        if own not in choices:
            choices.insert(0, own)
    return choices


def palette_name_key(palette_id):
    """The i18n key naming a built-in palette ("shell" or a preset)."""
    return "cartridge_color.palette." + palette_id.replace("-", "_")


def builtin_palette_colors(palette_id):
    """The colors of "shell" or a preset as stored ids, or ``None``."""
    if palette_id == SHELL_PALETTE_ID:
        return [
            parse_hex(entry[2]) for entry in CARTRIDGE_COLOR_TABLE if entry[0] != DEFAULT_COLOR_ID
        ]
    colors = _PRESETS_BY_ID.get(palette_id)
    return [parse_hex(color) for color in colors] if colors else None


def is_user_palette(palette_id):
    return bool(_USER_PALETTE_RE.match(str(palette_id or "")))


def _hex_list(values, cap):
    """Well-formed custom colors from ``values``, in order, no repeats, capped."""
    if not isinstance(values, list):
        return []
    colors = []
    for value in values:
        color = normalize_color_id(value) if isinstance(value, str) else None
        if color and is_custom_color(color) and color not in colors:
            colors.append(color)
    return colors[:cap]


def _clean_name(name):
    return " ".join(str(name or "").split())[:PALETTE_NAME_MAX]


def _clean_palettes(values):
    """The user palettes worth keeping; anything malformed is left out."""
    if not isinstance(values, list):
        return []
    palettes, seen = [], set()
    for value in values:
        if not isinstance(value, dict):
            continue
        palette_id = value.get("id")
        name = _clean_name(value.get("name"))
        if not is_user_palette(palette_id) or palette_id in seen or not name:
            continue
        seen.add(palette_id)
        palettes.append(
            {"id": palette_id, "name": name,
             "colors": _hex_list(value.get("colors"), PALETTE_COLORS_MAX)}
        )
    return palettes[:USER_PALETTES_MAX]


def _clean_palette_id(value):
    return value if isinstance(value, str) and value else SHELL_PALETTE_ID


def _storable(color_id):
    """A stored value worth keeping: a named id, or a well-formed custom hex.

    A value starting with ``#`` that is not ``#rrggbb`` (a hand edit gone
    wrong) is dropped, so the renderer is never handed a malformed color.
    """
    value = normalize_color_id(color_id)
    if value == DEFAULT_COLOR_ID:
        return None
    if value.startswith("#") and not is_custom_color(value):
        return None
    return value


class CartridgeColorStore:
    def __init__(self, config_file=DEFAULT_CARTRIDGE_COLORS_FILE):
        self.config_file = Path(config_file).expanduser()
        # The parsed file, keyed on its (mtime_ns, size). get_effective_color
        # calls load() twice per card -- once for the ROM override, once for
        # the console default -- so a 500-ROM page was 1000 file reads and
        # YAML parses on the GTK main thread, repeated on every zoom, sort and
        # view-mode change (issue #231). Same key shape as the cover cache.
        self._cache = (None, None)
        # When the stamp was last compared; see STAMP_TTL_S.
        self._checked_at = None

    def _stamp(self):
        try:
            stat = self.config_file.stat()
        except OSError:
            return None
        return (stat.st_mtime_ns, stat.st_size)

    def _current(self):
        """The parsed file, for readers: shared, never copied, never edited.

        ``get_effective_color`` is asked on every card bind, on the main
        thread. It used to go through :meth:`load` twice -- two stats and two
        deep copies of the whole mapping per card, 22,000 copies over one
        zoom round-trip on a 3000-game library (issue 907). Readers get the
        cached mapping itself; writers still take :meth:`load`, which copies.
        """
        cached_stamp, cached = self._cache
        now = time.monotonic()
        if (
            cached is not None
            and self._checked_at is not None
            and now - self._checked_at < STAMP_TTL_S
        ):
            return cached
        stamp = self._stamp()
        self._checked_at = now
        if stamp is not None and cached_stamp == stamp and cached is not None:
            return cached
        data = self._load_uncached()
        self._cache = (stamp, data)
        return data

    def load(self):
        # A deep copy on the way out: a caller that mutates the result must
        # not edit the cache.
        return copy.deepcopy(self._current())

    def _load_uncached(self):
        # Deep copies for the same reason the shader store takes them: the
        # nested dicts must never alias the module-level default.
        if not self.config_file.exists():
            return copy.deepcopy(DEFAULT_CARTRIDGE_COLOR_CONFIG)

        try:
            raw = yaml.safe_load(self.config_file.read_text(encoding="utf-8")) or {}
            if not isinstance(raw, dict):
                raise ValueError(f"not a mapping: {type(raw).__name__}")

            data = copy.deepcopy(DEFAULT_CARTRIDGE_COLOR_CONFIG)
            data["version"] = int(raw.get("version", 1))

            defaults = {}
            for key, value in (raw.get("console_defaults") or {}).items():
                canonical = resolve_system_id(key)
                if canonical not in SYSTEM_IDS:
                    continue
                color = _storable(value)
                if color is not None:
                    defaults[canonical] = color
            data["console_defaults"] = defaults

            overrides = {}
            for key, value in (raw.get("rom_overrides") or {}).items():
                if not key:
                    continue
                color = _storable(value)
                if color is not None:
                    overrides[from_stored_path(str(key))] = color
            data["rom_overrides"] = overrides
            data["saved_colors"] = _hex_list(raw.get("saved_colors"), SAVED_COLORS_MAX)
            data["palettes"] = _clean_palettes(raw.get("palettes"))
            data["palette"] = _clean_palette_id(raw.get("palette"))
            return data
        except Exception as exc:
            quarantine_state_file(self.config_file, exc)
            return copy.deepcopy(DEFAULT_CARTRIDGE_COLOR_CONFIG)

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
        payload["saved_colors"] = _hex_list(
            (settings or {}).get("saved_colors"), SAVED_COLORS_MAX
        )
        payload["palettes"] = _clean_palettes((settings or {}).get("palettes"))
        payload["palette"] = _clean_palette_id((settings or {}).get("palette"))
        stored = dict(payload, rom_overrides=with_stored_keys(payload["rom_overrides"]))
        atomic_write_text(self.config_file, yaml.safe_dump(stored, sort_keys=True))
        # Our own writes are the one case the stamp cannot be trusted for: a
        # rewrite of the same length inside one filesystem clock tick.
        self._cache = (None, None)
        self._checked_at = None
        return payload

    # -- per-console defaults ---------------------------------------------
    def get_console_color(self, console_id):
        canonical = resolve_system_id(console_id)
        return self._current().get("console_defaults", {}).get(canonical, DEFAULT_COLOR_ID)

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
        return self._current().get("rom_overrides", {}).get(str(rom_path))

    def get_effective_color(self, rom_path, console_id):
        """The shell that will actually draw: per-ROM first, then per-console.

        One read of the parsed mapping for both lookups: this is the per-card
        call, and it costs two dictionary lookups and no copy.
        """
        data = self._current()
        override = data.get("rom_overrides", {}).get(str(rom_path))
        if override:
            return override
        canonical = resolve_system_id(console_id)
        return data.get("console_defaults", {}).get(canonical, DEFAULT_COLOR_ID)

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

    # -- saved custom colors (issue 983) -----------------------------------
    def saved_colors(self):
        """Custom colors applied to a game, most recent first."""
        return list(self._current().get("saved_colors", []))

    def remember_color(self, color_id):
        """Put a custom color first in the saved ones (no repeats, capped)."""
        if not is_custom_color(color_id):
            return
        color = normalize_color_id(color_id)
        data = self.load()
        saved = data.get("saved_colors", [])
        if saved[:1] == [color]:
            return
        data["saved_colors"] = [color] + [value for value in saved if value != color]
        self.save(data)

    def forget_saved_color(self, color_id):
        """Drop a saved color; games painted with it keep it."""
        color = normalize_color_id(color_id)
        data = self.load()
        saved = data.get("saved_colors", [])
        if color in saved:
            data["saved_colors"] = [value for value in saved if value != color]
            self.save(data)

    # -- palettes (issue 983) ----------------------------------------------
    def user_palettes(self):
        """The user's palettes, copies: ``[{"id", "name", "colors"}]``."""
        return copy.deepcopy(self._current().get("palettes", []))

    def user_palette(self, palette_id):
        for palette in self._current().get("palettes", []):
            if palette["id"] == palette_id:
                return copy.deepcopy(palette)
        return None

    def palette_colors(self, palette_id):
        """The colors of any palette, built-in or the user's, or ``None``."""
        builtin = builtin_palette_colors(palette_id)
        if builtin is not None:
            return builtin
        palette = self.user_palette(palette_id)
        return palette["colors"] if palette else None

    def selected_palette(self):
        """The palette the dialog shows: the last one chosen, if it still exists."""
        palette_id = self._current().get("palette", SHELL_PALETTE_ID)
        return palette_id if self.palette_colors(palette_id) is not None else SHELL_PALETTE_ID

    def select_palette(self, palette_id):
        if self.palette_colors(palette_id) is None:
            return
        data = self.load()
        if data.get("palette") != palette_id:
            data["palette"] = palette_id
            self.save(data)

    def _edit_palette(self, palette_id, change):
        """Apply ``change(palette)`` to a user palette and save; its result says if it changed."""
        data = self.load()
        for palette in data.get("palettes", []):
            if palette["id"] == palette_id:
                if change(palette):
                    self.save(data)
                    return True
                return False
        return False

    def create_palette(self, name, colors=()):
        """A new user palette, selected; returns its id, or ``None``."""
        name = _clean_name(name)
        data = self.load()
        palettes = data.get("palettes", [])
        if not name or len(palettes) >= USER_PALETTES_MAX:
            return None
        taken = {palette["id"] for palette in palettes}
        palette_id = "user-" + secrets.token_hex(4)
        while palette_id in taken:  # pragma: no cover -- a 1 in 4 billion clash
            palette_id = "user-" + secrets.token_hex(4)
        palettes.append(
            {"id": palette_id, "name": name,
             "colors": _hex_list(list(colors or ()), PALETTE_COLORS_MAX)}
        )
        data["palettes"] = palettes
        data["palette"] = palette_id
        self.save(data)
        return palette_id

    def duplicate_palette(self, palette_id, name):
        """A user palette with ``palette_id``'s colors (built-in or not)."""
        colors = self.palette_colors(palette_id)
        if colors is None:
            return None
        return self.create_palette(name, colors)

    def rename_palette(self, palette_id, name):
        name = _clean_name(name)
        if not name:
            return False

        def change(palette):
            if palette["name"] == name:
                return False
            palette["name"] = name
            return True

        return self._edit_palette(palette_id, change)

    def delete_palette(self, palette_id):
        data = self.load()
        palettes = data.get("palettes", [])
        kept = [palette for palette in palettes if palette["id"] != palette_id]
        if len(kept) == len(palettes):
            return False
        data["palettes"] = kept
        if data.get("palette") == palette_id:
            data["palette"] = SHELL_PALETTE_ID
        self.save(data)
        return True

    def add_palette_color(self, palette_id, color_id):
        if not is_custom_color(color_id):
            return False
        color = normalize_color_id(color_id)

        def change(palette):
            colors = palette["colors"]
            if color in colors or len(colors) >= PALETTE_COLORS_MAX:
                return False
            colors.append(color)
            return True

        return self._edit_palette(palette_id, change)

    def remove_palette_color(self, palette_id, color_id):
        color = normalize_color_id(color_id)

        def change(palette):
            if color not in palette["colors"]:
                return False
            palette["colors"].remove(color)
            return True

        return self._edit_palette(palette_id, change)

    def move_palette_color(self, palette_id, color_id, step):
        """Move a color ``step`` places (-1 left, +1 right) inside its palette."""
        color = normalize_color_id(color_id)

        def change(palette):
            colors = palette["colors"]
            if color not in colors:
                return False
            index = colors.index(color)
            target = index + step
            if target < 0 or target >= len(colors):
                return False
            colors.insert(target, colors.pop(index))
            return True

        return self._edit_palette(palette_id, change)
