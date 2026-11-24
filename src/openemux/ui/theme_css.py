"""A custom theme's stylesheet, generated from its validated values (issue 1011).

The app's own ``style.css`` and libadwaita both paint with named colors
(``@window_bg_color``, ``@accent_bg_color``...), so overriding those
cascades into everything. libadwaita 1.6 moved its widgets onto CSS variables
(``--window-bg-color``), which ``@define-color`` no longer reaches; for those
versions the same values are also set as variables. GTK 4.14 / libadwaita
1.5, which CI runs, rejects that syntax, hence the switch.

Only values that went through ``custom_themes.validate_values`` are written:
the text is built here from ``#rrggbb`` strings, never copied from a file.
No GTK import, so the host test run covers it.
"""

from openemux.core.custom_themes import KEYS_BY_NAME, validate_value

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
}

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


def _variable(name):
    return "--" + name.replace("_", "-")


def stylesheet(values, css_variables=False):
    """The CSS for ``values`` (theme key -> value); empty for no values."""
    clean = {}
    for key, value in values.items():
        spec = KEYS_BY_NAME.get(key)
        if spec is not None:
            checked = validate_value(spec, value)
            if checked is not None:
                clean[key] = checked
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
    return "\n".join(lines) + ("\n" if lines else "")
