"""The theme editor's live preview: a small drawing of the app (issues 1011, 1012).

Header bar, the console sidebar with one console selected, three cards with
one selected, and the game details pane with its Play button, painted from a
theme's effective values. Drawn rather than built from real widgets:
libadwaita 1.5's named colors are global (``@define-color`` cannot be scoped
to one subtree), so real widgets could only show a theme by repainting the
whole app, which is what the editor's "apply to the whole app" switch is for.

Issue 1012: the drawing also follows the shapes and sizes (corner radius,
border, shadow, text size and font, icon size and color, density, grid gap,
card size, sidebar width) and the background images, scaled down to the
miniature.
"""

import math

import cairo
from gi.repository import Gdk, Gtk, Pango, PangoCairo

from openemux.core.cartridge_colors import hex_to_rgb
from openemux.core.custom_themes import DENSITY_FACTORS

PREVIEW_HEIGHT = 300
NARROW_PREVIEW_HEIGHT = 170
#: The miniature is about a third of the real window: sizes scale by this.
MINIATURE = 0.4
#: The real window width the sidebar width is a share of.
REFERENCE_WIDTH = 1100

#: Starting values for a drawing given only colors (part 1's callers).
_SHAPE_DEFAULTS = {
    "border_width": 0, "corner_radius": 12, "shadow_strength": 0.35,
    "shadow_color": "#000000", "border_color": "#454545", "icon_color": "#ffffff",
    "icon_scale": 1.0, "font_scale": 1.0, "font_family": "", "density": "default",
    "density_fine": 1.0, "grid_gap": 24, "card_scale": 1.0, "sidebar_width": None,
}


def _rgb(color):
    return tuple(channel / 255 for channel in hex_to_rgb(color))


def _path(cr, x, y, w, h, radius):
    radius = max(0, min(radius, w / 2, h / 2))
    if radius:
        cr.new_sub_path()
        cr.arc(x + w - radius, y + radius, radius, -math.pi / 2, 0)
        cr.arc(x + w - radius, y + h - radius, radius, 0, math.pi / 2)
        cr.arc(x + radius, y + h - radius, radius, math.pi / 2, math.pi)
        cr.arc(x + radius, y + radius, radius, math.pi, 3 * math.pi / 2)
        cr.close_path()
    else:
        cr.rectangle(x, y, w, h)


def _rect(cr, x, y, w, h, color, radius=0):
    cr.set_source_rgb(*_rgb(color))
    _path(cr, x, y, w, h, radius)
    cr.fill()


def _text(cr, x, y, text, color, size, bold=False, max_width=None, family=None):
    layout = PangoCairo.create_layout(cr)
    font = Pango.FontDescription.from_string(f"Sans {'Bold ' if bold else ''}{size:.1f}")
    if family:
        font.set_family(family)
    layout.set_font_description(font)
    layout.set_text(text, -1)
    if max_width is not None:
        layout.set_width(int(max(1, max_width) * Pango.SCALE))
        layout.set_ellipsize(Pango.EllipsizeMode.END)
    cr.set_source_rgb(*_rgb(color))
    cr.move_to(x, y)
    PangoCairo.show_layout(cr, layout)


def _image(cr, x, y, w, h, image):
    """Paint ``(pixbuf, fit)`` into the box, clipped to it."""
    pixbuf, fit = image
    iw, ih = pixbuf.get_width(), pixbuf.get_height()
    cr.save()
    cr.rectangle(x, y, w, h)
    cr.clip()
    if fit == "tile":
        cr.translate(x, y)
        cr.scale(MINIATURE, MINIATURE)
        Gdk.cairo_set_source_pixbuf(cr, pixbuf, 0, 0)
        cr.get_source().set_extend(cairo.EXTEND_REPEAT)
    else:
        pick = max if fit == "cover" else min
        scale = pick(w / iw, h / ih)
        cr.translate(x + (w - iw * scale) / 2, y + (h - ih * scale) / 2)
        cr.scale(scale, scale)
        Gdk.cairo_set_source_pixbuf(cr, pixbuf, 0, 0)
    cr.paint()
    cr.restore()


def _icon(cr, x, y, size, color):
    """A plain ring standing for a symbolic icon."""
    cr.set_source_rgb(*_rgb(color))
    cr.set_line_width(max(1, size / 7))
    cr.new_sub_path()
    cr.arc(x + size / 2, y + size / 2, max(1, size / 2 - 1), 0, 2 * math.pi)
    cr.stroke()


def draw_preview(cr, width, height, colors, labels, images=None):
    """Paint the app with ``colors`` (theme key -> effective value) on ``cr``.

    ``labels`` gives the words drawn: ``title``, ``consoles`` (three names),
    ``favorites``, ``games`` (three titles), ``console`` (the console's short
    name), ``played`` and ``play``. ``images`` maps ``library``/``sidebar`` to
    ``(pixbuf, fit)``. The layout drops the details pane, then shrinks the
    sidebar, as the width runs out, as the app does.
    """
    c = dict(_SHAPE_DEFAULTS)
    c.update(colors)
    images = images or {}
    text_scale = c["font_scale"]
    family = c["font_family"] or None
    density = DENSITY_FACTORS.get(c["density"], 1.0) * c["density_fine"]
    radius = c["corner_radius"] * MINIATURE * 1.5

    def text(x, y, words, color, size, **kw):
        _text(cr, x, y, words, color, size * text_scale, family=family, **kw)

    _rect(cr, 0, 0, width, height, c["window_bg"])
    header = round(30 * max(0.8, density))
    _rect(cr, 0, 0, width, header, c["headerbar_bg"])
    icon = 16 * c["icon_scale"] * MINIATURE * 1.4
    toolbar_icon = icon
    _icon(cr, width - toolbar_icon - 10, (header - toolbar_icon) / 2, toolbar_icon, c["icon_color"])
    text(10, 8, labels["title"], c["text_primary"], 8, bold=True, max_width=width - 40)

    if c["sidebar_width"]:
        sidebar = round(width * c["sidebar_width"] / REFERENCE_WIDTH * 1.4)
    else:
        sidebar = 120 if width >= 420 else 90
    sidebar = max(70, min(sidebar, width // 3))
    details = 130 if width >= 520 else 0
    body_y, body_h = header, height - header
    _rect(cr, 0, body_y, sidebar, body_h, c["sidebar_bg"])
    if "sidebar" in images:
        _image(cr, 0, body_y, sidebar, body_h, images["sidebar"])
    row_h = 22 * density
    sidebar_icon = icon
    y = body_y + 8
    for index, name in enumerate(labels["consoles"]):
        if index == 0:
            _rect(cr, 6, y - 2, sidebar - 12, row_h, c["selection_bg"], radius=radius / 2)
        _icon(cr, 12, y + (row_h - 4 - sidebar_icon) / 2, sidebar_icon, c["icon_color"])
        text(16 + sidebar_icon, y + 2, name, c["sidebar_text_primary"], 7,
             max_width=sidebar - 28 - sidebar_icon)
        y += row_h + 2
    text(14, y + 2, labels["favorites"], c["sidebar_text_secondary"], 7, max_width=sidebar - 24)

    library_x = sidebar
    library_w = width - sidebar - details
    _rect(cr, library_x, body_y, library_w, body_h, c["library_bg"])
    if "library" in images:
        _image(cr, library_x, body_y, library_w, body_h, images["library"])
    gap = max(2, c["grid_gap"] * MINIATURE)
    card_scale = c["card_scale"]
    want = 72 * card_scale
    columns = max(1, min(3, int((library_w - gap) // (want + gap))))
    card_w = max(20, min(want * 1.25, (library_w - gap * (columns + 1)) / columns))
    cover_h = min(70 * card_scale, card_w * 1.1)
    pad = 5 * density
    shadow = c["shadow_strength"]
    for index, title in enumerate(labels["games"][:columns]):
        x = library_x + gap + index * (card_w + gap)
        y = body_y + gap
        card_h = cover_h + 38
        if shadow:
            r, g, b = _rgb(c["shadow_color"])
            cr.set_source_rgba(r, g, b, shadow * 0.6)
            _path(cr, x + 1, y + 3, card_w, card_h, radius)
            cr.fill()
        if index == 0:
            _rect(cr, x - 2, y - 2, card_w + 4, card_h + 4, c["accent"], radius=radius + 1)
        _rect(cr, x, y, card_w, card_h, c["card_bg"], radius=radius)
        if c["border_width"]:
            cr.set_source_rgb(*_rgb(c["border_color"]))
            cr.set_line_width(c["border_width"])
            _path(cr, x, y, card_w, card_h, radius)
            cr.stroke()
        _rect(cr, x + pad, y + pad, card_w - 2 * pad, cover_h - pad, c["selection_bg"],
              radius=max(0, radius - 3))
        text(x + 6, y + cover_h + 4, title, c["text_primary"], 7, max_width=card_w - 12)
        text(x + 6, y + cover_h + 19, labels["console"], c["text_secondary"], 6,
             max_width=card_w - 12)

    if details:
        x = width - details
        _rect(cr, x, body_y, details, body_h, c["details_bg"])
        _rect(cr, x + 10, body_y + 10, details - 20, 70, c["card_bg"], radius=radius)
        text(x + 10, body_y + 88, labels["games"][0], c["text_primary"], 8, bold=True,
             max_width=details - 20)
        text(x + 10, body_y + 106, labels["played"], c["text_secondary"], 6,
             max_width=details - 20)
        _rect(cr, x + 10, body_y + 126, details - 20, 22, c["accent_button_bg"], radius=11)
        layout_w = details - 20
        text(x + 10 + layout_w / 2 - 10, body_y + 130, labels["play"],
             c["accent_button_fg"], 7, bold=True)

    # The popover color has nowhere to show in the window itself: a small
    # menu opened from the header, as the app's own menus are.
    menu_w = 74
    _rect(cr, width - menu_w - 8, header - 4, menu_w, 26, c["popover_bg"], radius=radius / 2)
    text(width - menu_w, header + 2, "• • •", c["text_primary"], 7)


class ThemePreview(Gtk.DrawingArea):
    """The drawing, as a widget; ``set_theme`` repaints it."""

    def __init__(self, labels, colors):
        super().__init__()
        self.labels = labels
        self.colors = colors
        self.images = {}
        self.set_content_height(PREVIEW_HEIGHT)
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.add_css_class("theme-preview")
        self.set_draw_func(self._draw)

    def set_theme(self, colors, images=None):
        self.colors = colors
        self.images = images or {}
        self.queue_draw()

    def set_colors(self, colors):
        self.set_theme(colors, self.images)

    def _draw(self, _area, cr, width, height):
        # The rounded window the drawing sits in.
        cr.save()
        _path(cr, 0, 0, width, height, 12)
        cr.clip()
        draw_preview(cr, width, height, self.colors, self.labels, self.images)
        cr.restore()


def draw_card(cr, width, height, colors, image=None):
    """A ready-made theme's card (issue 1012): its picture, framed by its colors.

    Smaller than the editor's preview and without words: a header strip, the
    sidebar with a selected row, and three cards over the library's picture,
    the first outlined in the accent.
    """
    c = dict(_SHAPE_DEFAULTS)
    c.update(colors)
    _rect(cr, 0, 0, width, height, c["library_bg"])
    if image is not None:
        _image(cr, 0, 0, width, height, image)
    header = max(8, round(height * 0.14))
    _rect(cr, 0, 0, width, header, c["headerbar_bg"])
    sidebar = round(width * 0.26)
    r, g, b = _rgb(c["sidebar_bg"])
    cr.set_source_rgba(r, g, b, 0.92)
    cr.rectangle(0, header, sidebar, height - header)
    cr.fill()
    row = max(6, round(height * 0.11))
    _rect(cr, 4, header + 5, sidebar - 8, row, c["selection_bg"], radius=3)
    for index in range(1, 3):
        _rect(cr, 8, header + 5 + index * (row + 4) + row / 3, sidebar * 0.55, row / 3,
              c["sidebar_text_secondary"], radius=1)
    gap = 6
    card_w = (width - sidebar - gap * 4) / 3
    card_h = min(height - header - gap * 2, card_w * 1.2)
    radius = min(card_w / 4, c["corner_radius"] * 0.35)
    for index in range(3):
        x = sidebar + gap + index * (card_w + gap)
        y = header + gap
        if index == 0:
            _rect(cr, x - 1.5, y - 1.5, card_w + 3, card_h + 3, c["accent"], radius=radius + 1)
        _rect(cr, x, y, card_w, card_h, c["card_bg"], radius=radius)
        _rect(cr, x + 3, y + card_h - 7, card_w * 0.6, 3, c["text_primary"], radius=1)


class ThemeCard(Gtk.DrawingArea):
    """``draw_card`` as a widget, clipped to a rounded frame."""

    def __init__(self, colors, image=None, width=140, height=88):
        super().__init__()
        self.colors = colors
        self.image = image
        self.set_content_width(width)
        self.set_content_height(height)
        self.add_css_class("ready-theme-art")
        self.set_draw_func(self._draw)

    def _draw(self, _area, cr, width, height):
        cr.save()
        _path(cr, 0, 0, width, height, 8)
        cr.clip()
        draw_card(cr, width, height, self.colors, self.image)
        cr.restore()
