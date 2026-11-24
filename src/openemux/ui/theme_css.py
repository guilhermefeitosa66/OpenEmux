"""A custom theme's stylesheet, generated from its validated values (issue 1011).

The app's own ``style.css`` and libadwaita both paint with named colors
(``@window_bg_color``, ``@accent_bg_color``...), so overriding those
cascades into everything. libadwaita 1.6 moved its widgets onto CSS variables
(``--window-bg-color``), which ``@define-color`` no longer reaches; for those
versions the same values are also set as variables. GTK 4.14 / libadwaita
1.5, which CI runs, rejects that syntax, hence the switch.

Only values that went through ``custom_themes.validate_values`` are written:
the text is built here from ``#rrggbb`` strings, whole numbers, a family
name that cannot contain a quote and file URIs the app made itself, never
copied from a file. No GTK import, so the host test run covers it.

Issue 1012 added the shapes and sizes. Some of them are not CSS at all --
the grid gap, the card size and the sidebar width are read by the widgets
(``layout_metrics``) -- and the rest are rules that, like the colors, are
only written for what the theme changed, so an unchanged theme paints
exactly like its base.
"""

from openemux.core.cartridge_colors import hex_to_rgb
from openemux.core.custom_themes import (
    KEYS_BY_NAME,
    THEME_DARK,
    validate_value,
)

#: Theme key -> the libadwaita named colors it overrides.
NAMED_COLORS = {
    "window_bg": ("window_bg_color",),
    "sidebar_bg": ("sidebar_bg_color", "secondary_sidebar_bg_color"),
    "headerbar_bg": ("headerbar_bg_color",),
    "card_bg": ("card_bg_color",),
    "popover_bg": ("popover_bg_color", "dialog_bg_color"),
    "text_primary": (
        "window_fg_color", "view_fg_color", "card_fg_color", "dialog_fg_color",
        "popover_fg_color", "headerbar_fg_color",
    ),
    "sidebar_text_primary": ("sidebar_fg_color", "secondary_sidebar_fg_color"),
    "accent": ("accent_color",),
    "accent_button_bg": ("accent_bg_color",),
    "accent_button_fg": ("accent_fg_color",),
    "border_color": ("borders",),
}

#: libadwaita 1.6 reads borders from ``--border-color``; 1.5 from ``@borders``.
_VARIABLE_NAMES = {"borders": "border-color"}

#: Theme key -> (selector, property) rules for what has no named color.
APP_RULES = {
    "library_bg": ((".library-area", "background-color"),),
    "details_bg": ((".game-details-view", "background-color"),),
    "text_secondary": (
        (".dim-label, .dimmed, row .subtitle", "color"),
    ),
    "sidebar_text_secondary": (
        (".navigation-sidebar .dim-label, .navigation-sidebar .dimmed, "
         ".navigation-sidebar row .subtitle", "color"),
    ),
    "selection_bg": (
        (".navigation-sidebar > row:selected", "background-color"),
    ),
}

#: Secondary text in libadwaita is the text color at reduced opacity; a
#: color the person picked is meant to be seen as picked.
_OPAQUE = {"text_secondary", "sidebar_text_secondary"}


#: Keys turned into rules below rather than through the tables above, and
#: keys that are no CSS at all (read by the widgets: ``layout_metrics``).
SHAPE_KEYS = (
    "border_width", "corner_radius", "shadow_color", "shadow_strength",
    "sidebar_icon_size", "toolbar_icon_size", "icon_color", "font_scale",
    "font_family", "density",
)
LAYOUT_KEYS = ("grid_gap", "card_scale", "sidebar_width")
#: Background image settings: used through ``backgrounds``, which the UI
#: builds from processed files (never from the theme file itself).
IMAGE_KEYS = tuple(
    f"{area}_image{suffix}"
    for area in ("library", "sidebar")
    for suffix in ("", "_fit", "_dim", "_blur")
)

#: Where each background area is painted.
BACKGROUND_SELECTORS = {
    "library": ".library-area",
    "sidebar": ".console-sidebar-pane",
}
_FIT_RULES = {
    "cover": ("cover", "no-repeat"),
    "contain": ("contain", "no-repeat"),
    "tile": ("auto", "repeat"),
}

#: Rounded like a card at the radius picked; buttons, entries and rows at
#: half of it, as libadwaita's own proportions are.
_CARD_SELECTORS = (
    ".card, .boxed-list, list.boxed-list, .rom-card, popover > contents, "
    ".game-details-view .card"
)
_SMALL_RADIUS_SELECTORS = "button, entry, .navigation-sidebar > row, .rom-row"
_COVER_SELECTORS = ".rom-cover, .rom-cover-backdrop"
_BORDER_SELECTORS = ".card, .boxed-list, list.boxed-list, .rom-cover"
_SHADOW_SELECTORS = ".card, .rom-cover"
_SIDEBAR_ICONS = ".navigation-sidebar image"
_TOOLBAR_ICONS = "headerbar image"


def _variable(name):
    return "--" + _VARIABLE_NAMES.get(name, name.replace("_", "-"))


def _rgba(color, alpha):
    r, g, b = hex_to_rgb(color)
    return f"rgba({r}, {g}, {b}, {alpha:.2f})"


def _scaled(length, percent):
    return max(0, int(round(length * percent / 100)))


def _shape_rules(clean, effective):
    """Rules for the Borders, Icons, Typography and Spacing sections."""
    rules = []
    if "corner_radius" in clean:
        radius = clean["corner_radius"]
        rules.append(f"{_CARD_SELECTORS} {{ border-radius: {radius}px; }}")
        rules.append(f"{_SMALL_RADIUS_SELECTORS} {{ border-radius: {radius // 2}px; }}")
        rules.append(f"{_COVER_SELECTORS} {{ border-radius: {max(0, radius - 4)}px; }}")
    if "border_width" in clean:
        width = clean["border_width"]
        if width:
            rules.append(
                f"{_BORDER_SELECTORS} {{ border: {width}px solid {effective('border_color')}; }}"
            )
        else:
            rules.append(f"{_BORDER_SELECTORS} {{ border: none; }}")
    if "shadow_color" in clean or "shadow_strength" in clean:
        strength = effective("shadow_strength")
        if strength:
            color = _rgba(effective("shadow_color"), strength / 100)
            blur = 4 + strength // 8
            rules.append(
                f"{_SHADOW_SELECTORS} {{ box-shadow: 0 {2 + strength // 25}px {blur}px {color}; }}"
            )
        else:
            rules.append(f"{_SHADOW_SELECTORS} {{ box-shadow: none; }}")
    if "sidebar_icon_size" in clean:
        rules.append(f"{_SIDEBAR_ICONS} {{ -gtk-icon-size: {clean['sidebar_icon_size']}px; }}")
    if "toolbar_icon_size" in clean:
        rules.append(f"{_TOOLBAR_ICONS} {{ -gtk-icon-size: {clean['toolbar_icon_size']}px; }}")
    if "icon_color" in clean:
        rules.append(f"{_TOOLBAR_ICONS}, {_SIDEBAR_ICONS} {{ color: {clean['icon_color']}; }}")
    window = []
    if "font_family" in clean and clean["font_family"]:
        window.append(f'font-family: "{clean["font_family"]}";')
    if "font_scale" in clean:
        window.append(f"font-size: {clean['font_scale']}%;")
    if window:
        rules.append("window { " + " ".join(window) + " }")
    if "density" in clean:
        density = clean["density"]
        rules.append(f".boxed-list > row, list.boxed-list > row {{ min-height: {_scaled(50, density)}px; }}")
        rules.append(
            f".navigation-sidebar > row {{ min-height: {_scaled(36, density)}px; "
            f"padding-top: {_scaled(6, density)}px; padding-bottom: {_scaled(6, density)}px; }}"
        )
        rules.append(f".rom-card {{ padding: {_scaled(8, density)}px; }}")
        rules.append(f"headerbar {{ min-height: {_scaled(47, density)}px; }}")
    return rules


def _background_rules(backgrounds):
    rules = []
    for area, selector in BACKGROUND_SELECTORS.items():
        background = (backgrounds or {}).get(area)
        if not background:
            continue
        uri = background.get("uri", "")
        # Made by the app from a cache path; still checked, since it lands
        # inside a CSS string.
        if not uri.startswith("file://") or any(c in uri for c in '"\\)\n\r'):
            continue
        size, repeat = _FIT_RULES.get(background.get("fit"), _FIT_RULES["cover"])
        rules.append(
            f'{selector} {{ background-image: url("{uri}"); background-size: {size}; '
            f"background-repeat: {repeat}; background-position: center; }}"
        )
    return rules


def stylesheet(values, css_variables=False, base=THEME_DARK, backgrounds=None):
    """The CSS for ``values`` (theme key -> value); empty for no values.

    ``base`` gives the starting value of a setting a rule needs but the
    theme left alone (a shadow's color when only its strength changed).
    ``backgrounds`` maps an area (``library``, ``sidebar``) to
    ``{"uri": "file://...", "fit": "cover"|"contain"|"tile"}``.
    """
    clean = {}
    for key, value in values.items():
        spec = KEYS_BY_NAME.get(key)
        if spec is not None:
            checked = validate_value(spec, value)
            if checked is not None:
                clean[key] = checked

    def effective(key):
        return clean[key] if key in clean else KEYS_BY_NAME[key].default(base)

    lines = []
    variables = []
    for key, names in NAMED_COLORS.items():
        if key in clean:
            for name in names:
                lines.append(f"@define-color {name} {clean[key]};")
                variables.append(f"  {_variable(name)}: {clean[key]};")
    if css_variables and variables:
        lines.append(":root {")
        lines.extend(variables)
        lines.append("}")
    for key, rules in APP_RULES.items():
        if key in clean:
            for selector, prop in rules:
                extra = " opacity: 1;" if key in _OPAQUE else ""
                lines.append(f"{selector} {{ {prop}: {clean[key]};{extra} }}")
    lines.extend(_shape_rules(clean, effective))
    lines.extend(_background_rules(backgrounds))
    return "\n".join(lines) + ("\n" if lines else "")


def layout_metrics(values):
    """The sizes the widgets read: ``{key: value}`` for what the theme changed."""
    metrics = {}
    for key in LAYOUT_KEYS:
        if key in values:
            checked = validate_value(KEYS_BY_NAME[key], values[key])
            if checked is not None:
                metrics[key] = checked
    return metrics
