"""The user's own themes: model, whitelist and storage (issue 1011).

A custom theme is a folder under the themes directory (``~/.openemux/themes``)
holding one ``theme.yaml``::

    version: 1
    name: Midnight
    base: dark
    library_bg: '#24283b'
    card_bg: '#2f3549'

``base`` is one of the built-in looks, light or dark: it gives every setting
its starting value and keeps libadwaita's own widgets coherent. Only the
values the person changed are written; a key that is absent is not
overridden at all, so a theme with nothing changed paints exactly like its
base.

Every key a theme may carry is a row of :data:`THEME_KEYS`, typed and, for
numbers, range-checked. A file is data, never code: unknown keys are dropped,
a value of the wrong type is dropped, a number out of range is clamped, and a
file that cannot be read at all is skipped and logged rather than allowed to
stop the app from starting. Turning the values into CSS is the UI's business
(``openemux.ui.theme_css``); nothing here imports GTK.
"""

import logging
import math
import os
import re
import shutil
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from openemux.core.cartridge_colors import parse_hex
from openemux.core.contrast import WCAG_AA, contrast_ratio
from openemux.core.theme import THEME_DARK, THEME_LIGHT, THEMES, is_custom_theme_id

logger = logging.getLogger(__name__)

THEME_FILE = "theme.yaml"
#: The ``version`` written into every file. A newer number still loads: the
#: keys this build knows are read and the rest ignored.
FORMAT_VERSION = 1
#: The two built-in looks a custom theme starts from.
BASES = (THEME_LIGHT, THEME_DARK)
#: Longest name kept; the picker and the editor's subtitle have to fit it.
MAX_NAME_LENGTH = 64

KIND_COLOR = "color"
KIND_NUMBER = "number"

#: The editor's sections, in the order its list shows them. Later parts of
#: issue 1010 add theirs here and rows to the table below.
SECTION_COLORS = "colors"
SECTION_TEXT = "text"
SECTION_ACCENT = "accent"
SECTIONS = (SECTION_COLORS, SECTION_TEXT, SECTION_ACCENT)


@dataclass(frozen=True)
class ThemeKey:
    """One setting a theme may change.

    ``group`` is the heading the editor puts the row under, within its
    section. ``light``/``dark`` are the starting values on each base: for a
    color, libadwaita's own palette flattened to an opaque hex, so the row
    shows what is on screen before anything is changed.
    """

    key: str
    section: str
    group: str
    kind: str
    light: object
    dark: object
    minimum: float = None
    maximum: float = None

    def default(self, base):
        return self.dark if base == THEME_DARK else self.light


def _color(key, section, group, light, dark):
    return ThemeKey(key, section, group, KIND_COLOR, light, dark)


#: The whitelist. Nothing outside it is ever read from a file or written to
#: the stylesheet.
THEME_KEYS = (
    _color("window_bg", SECTION_COLORS, "surfaces", "#fafafa", "#242424"),
    _color("sidebar_bg", SECTION_COLORS, "surfaces", "#ebebeb", "#303030"),
    _color("headerbar_bg", SECTION_COLORS, "surfaces", "#ebebeb", "#303030"),
    _color("library_bg", SECTION_COLORS, "surfaces", "#ffffff", "#1e1e1e"),
    _color("card_bg", SECTION_COLORS, "surfaces", "#ffffff", "#363636"),
    _color("popover_bg", SECTION_COLORS, "surfaces", "#ffffff", "#383838"),
    _color("details_bg", SECTION_COLORS, "surfaces", "#fafafa", "#383838"),
    _color("text_primary", SECTION_TEXT, "content", "#323232", "#ffffff"),
    _color("text_secondary", SECTION_TEXT, "content", "#6e6e6e", "#a8a8a8"),
    _color("sidebar_text_primary", SECTION_TEXT, "sidebar", "#2f2f2f", "#ffffff"),
    _color("sidebar_text_secondary", SECTION_TEXT, "sidebar", "#626262", "#b0b0b0"),
    _color("accent", SECTION_ACCENT, "accent", "#1c71d8", "#78aeed"),
    _color("selection_bg", SECTION_ACCENT, "accent", "#d6d6d6", "#474747"),
    _color("accent_button_bg", SECTION_ACCENT, "accent", "#3584e4", "#3584e4"),
    _color("accent_button_fg", SECTION_ACCENT, "accent", "#ffffff", "#ffffff"),
)

KEYS_BY_NAME = {spec.key: spec for spec in THEME_KEYS}

#: Text (or foreground) keys and the surfaces they are read on. The editor
#: warns when a pair the theme changed falls below WCAG AA.
CONTRAST_PAIRS = (
    ("text_primary", ("window_bg", "library_bg", "card_bg", "popover_bg",
                      "details_bg", "headerbar_bg")),
    ("text_secondary", ("window_bg", "library_bg", "card_bg", "popover_bg",
                        "details_bg")),
    ("sidebar_text_primary", ("sidebar_bg", "selection_bg")),
    ("sidebar_text_secondary", ("sidebar_bg",)),
    ("accent", ("window_bg",)),
    ("accent_button_fg", ("accent_button_bg",)),
)

#: The keys of the file that are not settings.
_RESERVED = ("version", "name", "base")

_SLUG_RUN = re.compile(r"[^a-z0-9]+")
#: Room left for a "-NN" suffix inside the 48 characters an id may have.
_SLUG_LENGTH = 40


class ThemeError(ValueError):
    """A theme file that cannot become a theme at all."""


def keys_in_section(section):
    return [spec for spec in THEME_KEYS if spec.section == section]


def validate_value(spec, value):
    """``value`` as ``spec`` stores it, or ``None`` when it is unusable."""
    if spec.kind == KIND_COLOR:
        return parse_hex(value) if isinstance(value, str) else None
    # A bool is an int to Python, and never what a number setting means.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value):
        return None
    if spec.minimum is not None:
        value = max(spec.minimum, value)
    if spec.maximum is not None:
        value = min(spec.maximum, value)
    return value


def validate_values(raw, source="theme"):
    """Only the whitelisted keys of ``raw``, each validated or dropped."""
    if not isinstance(raw, dict):
        return {}
    values = {}
    for key, value in raw.items():
        if key in _RESERVED:
            continue
        spec = KEYS_BY_NAME.get(key)
        if spec is None:
            logger.info("%s: ignoring unknown key %r", source, key)
            continue
        cleaned = validate_value(spec, value)
        if cleaned is None:
            logger.info("%s: ignoring %s=%r", source, key, value)
            continue
        values[key] = cleaned
    return values


def clean_name(name):
    """A name as it is stored: one line, trimmed, not too long."""
    if not isinstance(name, str):
        return ""
    return " ".join(name.split())[:MAX_NAME_LENGTH].strip()


def slugify(name):
    """A folder-safe id from a name; ``theme`` when nothing Latin is left."""
    ascii_name = (
        unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode("ascii")
    )
    slug = _SLUG_RUN.sub("-", ascii_name.lower()).strip("-")
    return slug[:_SLUG_LENGTH].strip("-") or "theme"


@dataclass
class Theme:
    id: str
    name: str
    base: str
    values: dict = field(default_factory=dict)

    def effective(self, key):
        """What the key paints with: the theme's value, else the base's."""
        if key in self.values:
            return self.values[key]
        return KEYS_BY_NAME[key].default(self.base)

    def effective_values(self):
        return {spec.key: self.effective(spec.key) for spec in THEME_KEYS}

    def is_changed(self, key):
        return key in self.values

    def copy(self, **changes):
        fields = {"id": self.id, "name": self.name, "base": self.base,
                  "values": dict(self.values)}
        fields.update(changes)
        return Theme(**fields)


def contrast_problems(theme):
    """Every pair below AA that the theme itself changed, worst first.

    Pairs the theme left alone are libadwaita's own and are not the person's
    to fix (its accent button, for one, sits under 4.5:1), so they never warn.
    """
    problems = []
    for fg, backgrounds in CONTRAST_PAIRS:
        for bg in backgrounds:
            if not (theme.is_changed(fg) or theme.is_changed(bg)):
                continue
            ratio = contrast_ratio(theme.effective(fg), theme.effective(bg))
            if ratio < WCAG_AA:
                problems.append((fg, bg, ratio))
    problems.sort(key=lambda problem: problem[2])
    return problems


def warnings_for(theme, key, problems=None):
    """The pairs ``key`` takes part in that fail, as (other key, ratio)."""
    if problems is None:
        problems = contrast_problems(theme)
    found = []
    for fg, bg, ratio in problems:
        if key == fg:
            found.append((bg, ratio))
        elif key == bg:
            found.append((fg, ratio))
    return found


def parse_theme(data, theme_id):
    """A theme from a loaded ``theme.yaml``; :class:`ThemeError` if it is none."""
    if not isinstance(data, dict):
        raise ThemeError("not a mapping")
    version = data.get("version", FORMAT_VERSION)
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise ThemeError(f"bad version {version!r}")
    base = data.get("base")
    if base not in BASES:
        raise ThemeError(f"bad base {base!r}")
    name = clean_name(data.get("name")) or theme_id
    values = validate_values(data, source=f"theme {theme_id}")
    return Theme(theme_id, name, base, values)


def serialize(theme):
    data = {"version": FORMAT_VERSION, "name": theme.name, "base": theme.base}
    for spec in THEME_KEYS:
        if spec.key in theme.values:
            data[spec.key] = theme.values[spec.key]
    return data


class ThemeStore:
    """The themes folder: one subfolder per theme, named by its id."""

    def __init__(self, root):
        self.root = Path(root)

    def _folder(self, theme_id):
        # Ids are checked before any path is built from one, so nothing a
        # caller (or a file) says can point outside the themes folder.
        if not is_custom_theme_id(theme_id):
            raise ValueError(f"not a theme id: {theme_id!r}")
        return self.root / theme_id

    def _load(self, theme_id):
        path = self._folder(theme_id) / THEME_FILE
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            return parse_theme(data, theme_id)
        except (OSError, UnicodeDecodeError, yaml.YAMLError, ThemeError) as exc:
            logger.warning("Skipping theme %s: %s", theme_id, exc)
            return None

    def list(self):
        """Every readable theme, by name."""
        try:
            entries = sorted(self.root.iterdir())
        except OSError:
            return []
        themes = []
        for entry in entries:
            if not entry.is_dir() or not is_custom_theme_id(entry.name):
                continue
            theme = self._load(entry.name)
            if theme is not None:
                themes.append(theme)
        themes.sort(key=lambda theme: (theme.name.casefold(), theme.id))
        return themes

    def get(self, theme_id):
        if not is_custom_theme_id(theme_id):
            return None
        return self._load(theme_id)

    def new_id(self, name):
        slug = slugify(name)
        candidate, number = slug, 2
        while candidate in THEMES or (self.root / candidate).exists():
            candidate = f"{slug}-{number}"
            number += 1
        return candidate

    def save(self, theme):
        """Write ``theme`` whole; the file is replaced, never half-written."""
        folder = self._folder(theme.id)
        folder.mkdir(parents=True, exist_ok=True)
        temp = folder / f".{THEME_FILE}.tmp"
        temp.write_text(
            yaml.safe_dump(serialize(theme), sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        os.replace(temp, folder / THEME_FILE)
        return theme

    def create(self, name, base, values=None):
        name = clean_name(name)
        if not name:
            raise ValueError("a theme needs a name")
        if base not in BASES:
            raise ValueError(f"not a base: {base!r}")
        theme = Theme(self.new_id(name), name, base, validate_values(values or {}))
        return self.save(theme)

    def duplicate(self, theme_id, name):
        source = self.get(theme_id)
        if source is None:
            raise KeyError(theme_id)
        return self.create(name, source.base, source.values)

    def rename(self, theme_id, name):
        theme = self.get(theme_id)
        if theme is None:
            raise KeyError(theme_id)
        name = clean_name(name)
        if not name:
            raise ValueError("a theme needs a name")
        theme.name = name
        return self.save(theme)

    def delete(self, theme_id):
        folder = self._folder(theme_id)
        if folder.is_dir():
            shutil.rmtree(folder)
