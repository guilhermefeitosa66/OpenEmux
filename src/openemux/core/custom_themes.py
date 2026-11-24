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
numbers, range-checked. Issue 1012 added the shapes and sizes (numbers, a
few choices, a font family) and the background images: an image key names a
file in the theme's own ``images/`` folder, never a path elsewhere. A file is data, never code: unknown keys are dropped,
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
import tempfile
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from openemux.core.cartridge_colors import hex_to_hsv, hex_to_rgb, parse_hex
from openemux.core.contrast import WCAG_AA, contrast_ratio, relative_luminance
from openemux.core.theme import (
    THEME_DARK,
    THEME_LIGHT,
    READY_MADE,
    THEMES,
    is_custom_theme_id,
    is_ready_made,
)

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
#: A whole number, clamped to the row's range.
KIND_NUMBER = "number"
#: One of the row's ``choices``.
KIND_CHOICE = "choice"
#: A font family name; empty is the desktop's own font.
KIND_FONT = "font"
#: A file name in the theme's ``images/`` folder; empty is no image.
KIND_IMAGE = "image"

#: The editor's sections, in the order its list shows them.
SECTION_COLORS = "colors"
SECTION_TEXT = "text"
SECTION_ACCENT = "accent"
SECTION_BORDERS = "borders"
SECTION_ICONS = "icons"
SECTION_TYPOGRAPHY = "typography"
SECTION_SPACING = "spacing"
SECTION_BACKGROUNDS = "backgrounds"
SECTIONS = (
    SECTION_COLORS, SECTION_TEXT, SECTION_ACCENT, SECTION_BORDERS,
    SECTION_ICONS, SECTION_TYPOGRAPHY, SECTION_SPACING, SECTION_BACKGROUNDS,
)

#: The image folder inside a theme's folder, and what may live in it: a
#: lower-case name and a picture extension. The editor only ever writes
#: ``library.png`` and ``sidebar.png``; an imported file may name others.
IMAGES_DIR = "images"
#: An image key's value, as the shared format writes it (the Android
#: contract, ``docs/THEME_FORMAT.md``): ``images/<name>.<ext>``.
IMAGE_FILE = re.compile(r"[a-z0-9_-]{1,40}\.(png|jpg|jpeg|webp)")
IMAGE_NAME = re.compile(r"images/[a-z0-9_-]{1,40}\.(png|jpg|jpeg|webp)")
#: A font family as stored: letters, digits, spaces and a little punctuation,
#: never a quote, a backslash or a brace, so it cannot leave a CSS string.
FONT_NAME = re.compile(r"[\w .&+()-]{1,64}")

#: The background areas, and the keys each one has.
IMAGE_AREAS = ("library", "sidebar")
FITS = ("cover", "contain", "tile")
#: The density choices and the factor each one scales rows and paddings by
#: (the same as Android's).
DENSITY_FACTORS = {"compact": 0.85, "default": 1.0, "comfortable": 1.15}
DENSITIES = tuple(DENSITY_FACTORS)


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
    choices: tuple = ()
    #: How a number is shown: "px" (stored as px), or "%" (stored as a
    #: fraction, 0.3, and shown as 30%), as the shared format stores them.
    unit: str = ""
    #: The editor's step; a fraction steps by 0.05.
    step: float = 1

    @property
    def fraction(self):
        return self.kind == KIND_NUMBER and self.unit == "%"

    def default(self, base):
        return self.dark if base == THEME_DARK else self.light


def _color(key, section, group, light, dark):
    return ThemeKey(key, section, group, KIND_COLOR, light, dark)


def _number(key, section, group, default, minimum, maximum, unit):
    return ThemeKey(key, section, group, KIND_NUMBER, default, default,
                    minimum=minimum, maximum=maximum, unit=unit,
                    step=0.05 if unit == "%" else 1)


def _choice(key, section, group, default, choices):
    return ThemeKey(key, section, group, KIND_CHOICE, default, default, choices=choices)


def _image_keys(area):
    group = f"{area}_image"
    return (
        ThemeKey(f"{area}_image", SECTION_BACKGROUNDS, group, KIND_IMAGE, "", ""),
        _choice(f"{area}_image_fit", SECTION_BACKGROUNDS, group, "cover", FITS),
        # Dimmed by default: an image picked as it is would sit under the
        # text at full strength, and readable by default is the rule.
        _number(f"{area}_image_dim", SECTION_BACKGROUNDS, group, 0.4, 0, 0.9, "%"),
        _number(f"{area}_image_blur", SECTION_BACKGROUNDS, group, 0, 0, 24, "px"),
    )


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
    # Big Picture's console list (issue 1012, the maintainer's Android test):
    # left alone, each console card keeps its own color; set, every card
    # takes this one, so a theme never clashes with the per-console colors.
    _color("console_list_bg", SECTION_COLORS, "big_picture", "#ffffff", "#24242c"),
    _color("text_primary", SECTION_TEXT, "content", "#323232", "#ffffff"),
    _color("text_secondary", SECTION_TEXT, "content", "#6e6e6e", "#a8a8a8"),
    _color("sidebar_text_primary", SECTION_TEXT, "sidebar", "#2f2f2f", "#ffffff"),
    _color("sidebar_text_secondary", SECTION_TEXT, "sidebar", "#626262", "#b0b0b0"),
    _color("accent", SECTION_ACCENT, "accent", "#1c71d8", "#78aeed"),
    _color("selection_bg", SECTION_ACCENT, "accent", "#d6d6d6", "#474747"),
    _color("accent_button_bg", SECTION_ACCENT, "accent", "#3584e4", "#3584e4"),
    _color("accent_button_fg", SECTION_ACCENT, "accent", "#ffffff", "#ffffff"),
    # Issue 1012: shapes and sizes. Defaults are what libadwaita 1.5 draws;
    # names and ranges are the shared format's (the Android contract), and
    # the desktop-only ones (font family, sidebar width, the fine density)
    # are named so Android ignores them.
    _color("border_color", SECTION_BORDERS, "borders", "#dcdcdc", "#454545"),
    _number("border_width", SECTION_BORDERS, "borders", 0, 0, 4, "px"),
    _number("corner_radius", SECTION_BORDERS, "borders", 12, 0, 28, "px"),
    _color("shadow_color", SECTION_BORDERS, "shadows", "#000000", "#000000"),
    _number("shadow_strength", SECTION_BORDERS, "shadows", 0.35, 0, 1, "%"),
    _number("icon_scale", SECTION_ICONS, "icons", 1.0, 0.75, 1.5, "%"),
    _color("icon_color", SECTION_ICONS, "icons", "#323232", "#ffffff"),
    _number("font_scale", SECTION_TYPOGRAPHY, "typography", 1.0, 0.85, 1.3, "%"),
    ThemeKey("font_family", SECTION_TYPOGRAPHY, "typography", KIND_FONT, "", ""),
    _choice("density", SECTION_SPACING, "spacing", "default", DENSITIES),
    _number("density_fine", SECTION_SPACING, "spacing", 1.0, 0.8, 1.2, "%"),
    _number("grid_gap", SECTION_SPACING, "spacing", 24, 0, 32, "px"),
    _number("card_scale", SECTION_SPACING, "spacing", 1.0, 0.75, 1.5, "%"),
    _number("sidebar_width", SECTION_SPACING, "spacing", 300, 200, 420, "px"),
    *_image_keys("library"),
    *_image_keys("sidebar"),
)

KEYS_BY_NAME = {spec.key: spec for spec in THEME_KEYS}

#: Text (or foreground) keys and the surfaces they are read on. The editor
#: warns when a pair the theme changed falls below WCAG AA.
CONTRAST_PAIRS = (
    ("text_primary", ("window_bg", "library_bg", "card_bg", "popover_bg",
                      "details_bg", "headerbar_bg", "console_list_bg")),
    ("text_secondary", ("window_bg", "library_bg", "card_bg", "popover_bg",
                        "details_bg", "console_list_bg")),
    # On the selected row the desktop takes this text further until it reads
    # on the selection (``theme_css``), so only the sidebar itself is checked.
    ("sidebar_text_primary", ("sidebar_bg",)),
    ("sidebar_text_secondary", ("sidebar_bg",)),
    ("accent", ("window_bg",)),
    ("accent_button_fg", ("accent_button_bg",)),
    ("icon_color", ("headerbar_bg", "sidebar_bg")),
)

#: Icons are not text: WCAG 2.1 (1.4.11) asks 3:1 of them.
NON_TEXT_CONTRAST = 3.0
_NON_TEXT_KEYS = ("icon_color",)


def needed_contrast(fg):
    """The ratio ``fg`` must reach: 4.5:1 for text, 3:1 for icons."""
    return NON_TEXT_CONTRAST if fg in _NON_TEXT_KEYS else WCAG_AA

#: The background each image sits on, for the contrast check: text read on
#: the library is also read on its image, dimmed into that color.
IMAGE_SURFACES = {"library": "library_bg", "sidebar": "sidebar_bg"}

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
    if spec.kind == KIND_CHOICE:
        # A bool is an int to Python (True == 1), and never a choice.
        if isinstance(value, bool):
            return None
        # The choice's own value, never an equal one of another type
        # (16.0 for 16), so it is written back exactly as the table has it.
        for choice in spec.choices:
            if type(choice) is type(value) and choice == value:
                return choice
        return None
    if spec.kind == KIND_FONT:
        if not isinstance(value, str) or value != value.strip():
            return None
        return value if FONT_NAME.fullmatch(value) else None
    if spec.kind == KIND_IMAGE:
        return value if isinstance(value, str) and IMAGE_NAME.fullmatch(value) else None
    # A bool is an int to Python, and never what a number setting means.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value):
        return None
    if spec.minimum is not None:
        value = max(spec.minimum, value)
    if spec.maximum is not None:
        value = min(spec.maximum, value)
    # Pixels are whole; a fraction keeps two decimals (0.35).
    if spec.unit == "%":
        return round(float(value), 2)
    return int(round(value))


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
    #: The folder its image values are relative to (they read
    #: ``images/<name>``): the theme's own folder, a ready-made theme's assets,
    #: or the editor's staging copy while it is edited. Never written.
    folder: Path = field(default=None, compare=False)

    def effective(self, key):
        """What the key paints with: the theme's value, else the base's."""
        if key in self.values:
            return self.values[key]
        return KEYS_BY_NAME[key].default(self.base)

    def effective_values(self):
        return {spec.key: self.effective(spec.key) for spec in THEME_KEYS}

    def is_changed(self, key):
        return key in self.values

    def image_path(self, area):
        """The file of ``area``'s background (``library``/``sidebar``), or None."""
        name = self.values.get(f"{area}_image")
        if not name or self.folder is None:
            return None
        path = Path(self.folder) / name
        return path if path.is_file() else None

    def copy(self, **changes):
        fields = {"id": self.id, "name": self.name, "base": self.base,
                  "values": dict(self.values), "folder": self.folder}
        fields.update(changes)
        return Theme(**fields)


def contrast_problems(theme, image_colors=None):
    """Every pair below AA that the theme itself changed, worst first.

    Pairs the theme left alone are libadwaita's own and are not the person's
    to fix (its accent button, for one, sits under 4.5:1), so they never warn.
    ``image_colors`` maps an area (``library``/``sidebar``) to the average
    color of its dimmed background image: text read on that area's surface is
    read on the image too, reported against ``<area>_image``.
    """
    problems = []
    surfaces = {}
    for area, color in (image_colors or {}).items():
        if area in IMAGE_SURFACES and theme.values.get(f"{area}_image") and parse_hex(color):
            surfaces[IMAGE_SURFACES[area]] = (f"{area}_image", parse_hex(color))
    for fg, backgrounds in CONTRAST_PAIRS:
        for bg in backgrounds:
            if theme.is_changed(fg) or theme.is_changed(bg):
                ratio = contrast_ratio(theme.effective(fg), theme.effective(bg))
                if ratio < needed_contrast(fg):
                    problems.append((fg, bg, ratio))
            if bg in surfaces:
                image_key, color = surfaces[bg]
                ratio = contrast_ratio(theme.effective(fg), color)
                if ratio < needed_contrast(fg):
                    problems.append((fg, image_key, ratio))
    problems.sort(key=lambda problem: problem[2])
    return problems


def mix(first, second, amount):
    """``first`` moved ``amount`` (0..1) of the way to ``second``."""
    a, b = hex_to_rgb(first), hex_to_rgb(second)
    return "#" + "".join(
        f"{int(round(x + (y - x) * amount)):02x}" for x, y in zip(a, b)
    )


def readable_on(color, background, target=WCAG_AA):
    """``color``, pushed toward black or white until it reads on ``background``.

    The direction is whichever end is farther from the background; the
    smallest step that reaches ``target`` wins, so the color keeps as much of
    its own hue as it can. Unreachable targets end at black or white.
    """
    end = "#000000" if relative_luminance(background) > 0.18 else "#ffffff"
    for step in range(21):
        candidate = mix(color, end, step / 20)
        if contrast_ratio(candidate, background) >= target:
            return candidate
    return end


def _toward_base(color, base, limit):
    """``color`` darkened (dark base) or lightened (light base) to ``limit``.

    ``limit`` is a relative luminance: at most it for a dark base, at least
    it for a light one.
    """
    end = "#000000" if base == THEME_DARK else "#ffffff"
    # The end itself (black or white) always meets the limit.
    for step in range(20):
        candidate = mix(color, end, step / 20)
        luminance = relative_luminance(candidate)
        if (luminance <= limit) if base == THEME_DARK else (luminance >= limit):
            return candidate
    return end


def _saturation(color):
    return hex_to_hsv(color)[1]


def seed_from_palette(base, colors):
    """Surface, text and accent values for ``base`` taken from ``colors``.

    The darkest colors become the surfaces of a dark base and the lightest
    those of a light one; text comes from the other end, nudged until it
    reads; the most saturated color is the accent. Returns ``{}`` for fewer
    than two usable colors.
    """
    cleaned = []
    for color in colors or ():
        parsed = parse_hex(color) if isinstance(color, str) else None
        if parsed and parsed not in cleaned:
            cleaned.append(parsed)
    if len(cleaned) < 2:
        return {}
    by_light = sorted(cleaned, key=relative_luminance)
    if base == THEME_DARK:
        surfaces, inks = by_light, list(reversed(by_light))
        lift = "#ffffff"
    else:
        surfaces, inks = list(reversed(by_light)), by_light
        lift = "#000000"
    # A palette with no dark (or no light) color still has to make a dark
    # (or light) theme: its end color is taken further until it is one.
    window = _toward_base(surfaces[0], base, 0.03 if base == THEME_DARK else 0.8)
    raised = surfaces[1] if len(surfaces) > 2 else mix(window, lift, 0.08)
    raised = _toward_base(raised, base, 0.06 if base == THEME_DARK else 0.7)
    accent = max(cleaned, key=lambda color: (_saturation(color), cleaned.index(color) * -1))
    text = readable_on(inks[0], raised)
    text = readable_on(text, window)
    secondary = readable_on(mix(text, window, 0.35), raised)
    secondary = readable_on(secondary, window)
    button_fg = max(("#ffffff", "#000000"), key=lambda ink: contrast_ratio(ink, accent))
    # The button keeps the accent's hue, moved away from its text until the
    # label reads on it.
    button_bg = readable_on(accent, button_fg)
    selection = mix(raised, accent, 0.25)
    sidebar_text = readable_on(readable_on(text, selection), raised)
    values = {
        "window_bg": window,
        "library_bg": window,
        "headerbar_bg": raised,
        "sidebar_bg": raised,
        "card_bg": raised,
        "popover_bg": raised,
        "details_bg": raised,
        "text_primary": text,
        "text_secondary": secondary,
        "sidebar_text_primary": sidebar_text,
        "sidebar_text_secondary": readable_on(secondary, raised),
        "accent": readable_on(accent, window),
        "selection_bg": selection,
        "accent_button_bg": button_bg,
        "accent_button_fg": button_fg,
        "icon_color": text,
    }
    return values


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
    """The themes folder: one subfolder per theme, named by its id.

    A theme's images live in its folder's ``images/``. While the editor has a
    theme open it works on a *staging* copy of that folder (a hidden folder
    beside the themes), so Cancel throws the copy away and Save swaps it in.
    """

    STAGING_PREFIX = ".staging-"
    IMPORT_PREFIX = ".import-"

    def __init__(self, root):
        self.root = Path(root)

    def _folder(self, theme_id):
        # Ids are checked before any path is built from one, so nothing a
        # caller (or a file) says can point outside the themes folder.
        if not is_custom_theme_id(theme_id):
            raise ValueError(f"not a theme id: {theme_id!r}")
        return self.root / theme_id

    def images_dir(self, theme_id):
        return self._folder(theme_id) / IMAGES_DIR

    def _load(self, theme_id):
        path = self._folder(theme_id) / THEME_FILE
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            theme = parse_theme(data, theme_id)
        except (OSError, UnicodeDecodeError, yaml.YAMLError, ThemeError) as exc:
            logger.warning("Skipping theme %s: %s", theme_id, exc)
            return None
        theme.folder = self._folder(theme_id)
        return theme

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
        """A user theme by id; a ready-made id gives that theme (issue 1012)."""
        if is_ready_made(theme_id):
            # Imported here: ready_themes builds on this module.
            from openemux.core import ready_themes
            return ready_themes.get(theme_id)
        if not is_custom_theme_id(theme_id):
            return None
        return self._load(theme_id)

    def new_id(self, name):
        slug = slugify(name)
        candidate, number = slug, 2
        while candidate in THEMES or is_ready_made(candidate) or (self.root / candidate).exists():
            candidate = f"{slug}-{number}"
            number += 1
        return candidate

    def unique_name(self, name):
        """``name``, or "name (2)", "(3)"... when a theme already has it."""
        name = clean_name(name)
        taken = {theme.name.casefold() for theme in self.list()}
        if name.casefold() not in taken:
            return name
        number = 2
        while True:
            suffix = f" ({number})"
            candidate = name[:MAX_NAME_LENGTH - len(suffix)].rstrip() + suffix
            if candidate.casefold() not in taken:
                return candidate
            number += 1

    def _write_images(self, folder, theme, images_from):
        """Make ``folder/images`` hold exactly the images ``theme`` names.

        The files come from ``images_from``, the folder their ``images/...``
        values are relative to (or the theme's own folder);
        the new set is built beside the old one and swapped in, so a failure
        halfway leaves the old images as they were.
        """
        source = Path(images_from) if images_from is not None else folder
        wanted = [
            theme.values[spec.key] for spec in THEME_KEYS
            if spec.kind == KIND_IMAGE and theme.values.get(spec.key)
        ]
        target = folder / IMAGES_DIR
        if not wanted:
            if target.is_dir():
                shutil.rmtree(target)
            return
        fresh = folder / f".{IMAGES_DIR}.tmp"
        if fresh.exists():
            shutil.rmtree(fresh)
        fresh.mkdir()
        try:
            for name in wanted:
                if (source / name).is_file():
                    shutil.copyfile(source / name, fresh / Path(name).name)
                else:
                    logger.warning("Theme %s: image %s is missing", theme.id, name)
            if target.is_dir():
                shutil.rmtree(target)
            os.replace(fresh, target)
        except OSError:
            shutil.rmtree(fresh, ignore_errors=True)
            raise

    def save(self, theme, images_from=None):
        """Write ``theme`` whole; the file is replaced, never half-written.

        ``images_from`` is where its images are now (the editor's staging
        folder); without it, the images already in the folder are kept, less
        the ones the theme no longer names.
        """
        folder = self._folder(theme.id)
        folder.mkdir(parents=True, exist_ok=True)
        self._write_images(folder, theme, images_from)
        temp = folder / f".{THEME_FILE}.tmp"
        try:
            temp.write_text(
                yaml.safe_dump(serialize(theme), sort_keys=False, allow_unicode=True),
                encoding="utf-8",
            )
            os.replace(temp, folder / THEME_FILE)
        except OSError:
            temp.unlink(missing_ok=True)
            raise
        theme.folder = folder
        return theme

    def create(self, name, base, values=None, images_from=None):
        name = clean_name(name)
        if not name:
            raise ValueError("a theme needs a name")
        if base not in BASES:
            raise ValueError(f"not a base: {base!r}")
        theme = Theme(self.new_id(name), name, base, validate_values(values or {}))
        return self.save(theme, images_from=images_from)

    def duplicate(self, theme_id, name):
        source = self.get(theme_id)
        if source is None:
            raise KeyError(theme_id)
        return self.create(name, source.base, source.values, images_from=source.folder)

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

    # -- the editor's working copy of a theme's images --------------------

    def stage(self, theme):
        """A private copy of ``theme``'s images for the editor to change."""
        self.root.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=self.STAGING_PREFIX, dir=self.root))
        (staging / IMAGES_DIR).mkdir()
        source = Path(theme.folder) / IMAGES_DIR if theme.folder is not None else None
        if source is not None and source.is_dir():
            for entry in source.iterdir():
                if entry.is_file() and IMAGE_FILE.fullmatch(entry.name):
                    shutil.copyfile(entry, staging / IMAGES_DIR / entry.name)
        return staging

    def discard(self, staging):
        """Remove a staging folder; anything else is left alone."""
        staging = Path(staging)
        if staging.parent == self.root and staging.name.startswith(self.STAGING_PREFIX):
            shutil.rmtree(staging, ignore_errors=True)

    def move_reserved_ids(self):
        """Give a new id to a user theme whose folder a ready-made theme now owns.

        Before issue 1012 shipped the ready-made themes, a theme named "Neon"
        was stored as ``neon``; that id is reserved now and the folder would
        be hidden. Returns ``{old id: new id}`` for whoever stored the old one.
        """
        moved = {}
        for theme_id in READY_MADE:
            folder = self.root / theme_id
            if not folder.is_dir():
                continue
            new_id = self.new_id(theme_id)
            try:
                folder.rename(self.root / new_id)
            except OSError as exc:
                logger.warning("Could not move theme %s aside: %s", theme_id, exc)
                continue
            moved[theme_id] = new_id
        return moved

    def purge_leftovers(self):
        """Staging and import folders a crash left behind."""
        try:
            entries = list(self.root.iterdir())
        except OSError:
            return
        for entry in entries:
            if entry.is_dir() and entry.name.startswith(
                (self.STAGING_PREFIX, self.IMPORT_PREFIX)
            ):
                shutil.rmtree(entry, ignore_errors=True)
