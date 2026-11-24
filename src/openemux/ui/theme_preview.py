"""The theme editor's live preview: a small drawing of the app (issue 1011).

Header bar, the console sidebar with one console selected, three cards with
one selected, and the game details pane with its Play button, painted from a
theme's effective colors. Drawn rather than built from real widgets:
libadwaita 1.5's named colors are global (``@define-color`` cannot be scoped
to one subtree), so real widgets could only show a theme by repainting the
whole app, which is what the editor's "apply to the whole app" switch is for.
"""

import math

from gi.repository import Gtk, Pango, PangoCairo

from openemux.core.cartridge_colors import hex_to_rgb

PREVIEW_HEIGHT = 300
NARROW_PREVIEW_HEIGHT = 170


def _rgb(color):
    return tuple(channel / 255 for channel in hex_to_rgb(color))


def _rect(cr, x, y, w, h, color, radius=0):
    cr.set_source_rgb(*_rgb(color))
    if radius:
        cr.new_sub_path()
        cr.arc(x + w - radius, y + radius, radius, -math.pi / 2, 0)
        cr.arc(x + w - radius, y + h - radius, radius, 0, math.pi / 2)
        cr.arc(x + radius, y + h - radius, radius, math.pi / 2, math.pi)
        cr.arc(x + radius, y + radius, radius, math.pi, 3 * math.pi / 2)
        cr.close_path()
    else:
        cr.rectangle(x, y, w, h)
    cr.fill()


def _text(cr, x, y, text, color, size, bold=False, max_width=None):
    layout = PangoCairo.create_layout(cr)
    font = Pango.FontDescription.from_string(f"Sans {'Bold ' if bold else ''}{size}")
    layout.set_font_description(font)
    layout.set_text(text, -1)
    if max_width is not None:
        layout.set_width(int(max(1, max_width) * Pango.SCALE))
        layout.set_ellipsize(Pango.EllipsizeMode.END)
    cr.set_source_rgb(*_rgb(color))
    cr.move_to(x, y)
    PangoCairo.show_layout(cr, layout)


def draw_preview(cr, width, height, colors, labels):
    """Paint the app in ``colors`` (theme key -> hex) on ``cr``.

    ``labels`` gives the words drawn: ``title``, ``consoles`` (three names),
    ``favorites``, ``games`` (three titles), ``console`` (the console's short
    name), ``played`` and ``play``. The layout drops the details pane, then
    shrinks the sidebar, as the width runs out, as the app does.
    """
    c = colors
    _rect(cr, 0, 0, width, height, c["window_bg"])
    header = 30
    _rect(cr, 0, 0, width, header, c["headerbar_bg"])
    _text(cr, 10, 8, labels["title"], c["text_primary"], 8, bold=True, max_width=width - 20)

    sidebar = 120 if width >= 420 else 90
    details = 130 if width >= 520 else 0
    body_y, body_h = header, height - header
    _rect(cr, 0, body_y, sidebar, body_h, c["sidebar_bg"])
    y = body_y + 8
    for index, name in enumerate(labels["consoles"]):
        if index == 0:
            _rect(cr, 6, y - 2, sidebar - 12, 22, c["selection_bg"], radius=5)
        _text(cr, 14, y + 2, name, c["sidebar_text_primary"], 7, max_width=sidebar - 24)
        y += 24
    _text(cr, 14, y + 2, labels["favorites"], c["sidebar_text_secondary"], 7,
          max_width=sidebar - 24)

    library_x = sidebar
    library_w = width - sidebar - details
    _rect(cr, library_x, body_y, library_w, body_h, c["library_bg"])
    columns = 3 if library_w >= 240 else 2
    gap = 8
    card_w = (library_w - gap * (columns + 1)) / columns
    cover_h = min(70, card_w * 1.1)
    for index, title in enumerate(labels["games"][:columns]):
        x = library_x + gap + index * (card_w + gap)
        y = body_y + gap
        if index == 0:
            _rect(cr, x - 2, y - 2, card_w + 4, cover_h + 42, c["accent"], radius=9)
        _rect(cr, x, y, card_w, cover_h + 38, c["card_bg"], radius=8)
        _rect(cr, x + 5, y + 5, card_w - 10, cover_h - 5, c["selection_bg"], radius=4)
        _text(cr, x + 6, y + cover_h + 4, title, c["text_primary"], 7, max_width=card_w - 12)
        _text(cr, x + 6, y + cover_h + 19, labels["console"], c["text_secondary"], 6,
              max_width=card_w - 12)

    if details:
        x = width - details
        _rect(cr, x, body_y, details, body_h, c["details_bg"])
        _rect(cr, x + 10, body_y + 10, details - 20, 70, c["card_bg"], radius=6)
        _text(cr, x + 10, body_y + 88, labels["games"][0], c["text_primary"], 8, bold=True,
              max_width=details - 20)
        _text(cr, x + 10, body_y + 106, labels["played"], c["text_secondary"], 6,
              max_width=details - 20)
        _rect(cr, x + 10, body_y + 126, details - 20, 22, c["accent_button_bg"], radius=11)
        layout_w = details - 20
        _text(cr, x + 10 + layout_w / 2 - 10, body_y + 130, labels["play"],
              c["accent_button_fg"], 7, bold=True)

    # The popover color has nowhere to show in the window itself: a small
    # menu opened from the header, as the app's own menus are.
    menu_w = 74
    _rect(cr, width - menu_w - 8, header - 4, menu_w, 26, c["popover_bg"], radius=6)
    _text(cr, width - menu_w, header + 2, "• • •", c["text_primary"], 7)


class ThemePreview(Gtk.DrawingArea):
    """The drawing, as a widget; ``set_colors`` repaints it."""

    def __init__(self, labels, colors):
        super().__init__()
        self.labels = labels
        self.colors = colors
        self.set_content_height(PREVIEW_HEIGHT)
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.add_css_class("theme-preview")
        self.set_draw_func(self._draw)

    def set_colors(self, colors):
        self.colors = colors
        self.queue_draw()

    def _draw(self, _area, cr, width, height):
        # The rounded window the drawing sits in.
        cr.save()
        radius = 12
        cr.new_sub_path()
        cr.arc(width - radius, radius, radius, -math.pi / 2, 0)
        cr.arc(width - radius, height - radius, radius, 0, math.pi / 2)
        cr.arc(radius, height - radius, radius, math.pi / 2, math.pi)
        cr.arc(radius, radius, radius, math.pi, 3 * math.pi / 2)
        cr.close_path()
        cr.clip()
        draw_preview(cr, width, height, self.colors, self.labels)
        cr.restore()
