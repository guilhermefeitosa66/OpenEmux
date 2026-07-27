"""Context menus with an icon next to each entry.

GTK4 ignores the ``icon`` attribute of a ``Gio.MenuItem`` when it builds a
``Gtk.PopoverMenu``: the ``GtkModelButton`` keeps its image hidden, so a menu
built from a model can only ever be text. These helpers build the rows by hand
instead, as flat buttons holding an icon plus a label.

Entries passed to :func:`build_context_popover` are one of:

* ``SEPARATOR`` (``None``) -- a divider between sections.
* a ``(label, action, icon_name)`` tuple -- a leaf row. ``action`` is either a
  ``Gtk`` action name string (``"rom.rename"``), a plain callable invoked on
  click, or ``None`` for a display-only (insensitive) row -- an empty save
  slot; ``icon_name`` may be ``None`` to leave the icon column blank, which is
  how radio-style rows mark the ones that are not selected.
* a ``(label, action, icon_name, swatch_hex)`` tuple -- the same row with a
  small color square between the icon and the label (the cartridge-color
  menu); ``swatch_hex`` may be ``None`` to keep the column aligned on rows
  without a color, like the Default entry.
* a :class:`Submenu` -- a row that opens a nested popover of its own entries.
"""

import logging

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, Gtk

logger = logging.getLogger(__name__)

SEPARATOR = None

_SWATCH_SIZE = 14


class Submenu:
    """A row that expands into a nested popover of ``entries``.

    ``entries`` follows the same grammar as :func:`build_context_popover`, so a
    submenu can hold leaves, separators and further submenus.
    """

    def __init__(self, label, entries, icon_name=None):
        self.label = label
        self.entries = list(entries)
        self.icon_name = icon_name


def build_context_popover(entries):
    """Build a menu-styled popover from ``entries``."""
    popover = Gtk.Popover()
    popover.set_has_arrow(False)
    popover.set_halign(Gtk.Align.START)
    popover.add_css_class("menu")
    popover.set_child(_build_menu_box(entries, popover))
    return popover


def _build_menu_box(entries, root_popover):
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
    box.add_css_class("context-menu-box")
    for entry in entries:
        if entry is SEPARATOR:
            box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        elif isinstance(entry, Submenu):
            box.append(_submenu_row(root_popover, entry))
        else:
            box.append(_menu_row(root_popover, *entry))
    return box


def _icon_image(icon_name):
    # An explicit size keeps the icon column aligned even for the blank cells a
    # radio row leaves when it is not the selected one.
    image = Gtk.Image.new_from_icon_name(icon_name) if icon_name else Gtk.Image()
    image.set_size_request(16, 16)
    return image


def _swatch_widget(swatch_hex):
    """A small rounded color square, or a blank spacer to keep rows aligned."""
    area = Gtk.DrawingArea()
    area.set_content_width(_SWATCH_SIZE)
    area.set_content_height(_SWATCH_SIZE)
    area.set_valign(Gtk.Align.CENTER)
    if not swatch_hex:
        return area

    rgba = Gdk.RGBA()
    if not rgba.parse(swatch_hex):
        rgba.parse("#9A9996")

    def _draw(_area, cr, width, height):
        radius = 3
        # Rounded rectangle path, inset one device pixel so the hairline
        # border is not clipped by the widget bounds.
        x0, y0, x1, y1 = 0.5, 0.5, width - 0.5, height - 0.5
        cr.new_sub_path()
        cr.arc(x1 - radius, y0 + radius, radius, -1.5708, 0)
        cr.arc(x1 - radius, y1 - radius, radius, 0, 1.5708)
        cr.arc(x0 + radius, y1 - radius, radius, 1.5708, 3.1416)
        cr.arc(x0 + radius, y0 + radius, radius, 3.1416, 4.7124)
        cr.close_path()
        cr.set_source_rgba(rgba.red, rgba.green, rgba.blue, rgba.alpha)
        cr.fill_preserve()
        # A translucent outline keeps the light swatches (white, clear)
        # visible against a light menu background.
        cr.set_source_rgba(0, 0, 0, 0.25)
        cr.set_line_width(1)
        cr.stroke()

    area.set_draw_func(_draw)
    return area


def _run_after_close(root_popover, callback):
    """Close the whole menu, then run ``callback`` once GTK is done with it.

    Closing a popover tears its surface down and repoints the pointer focus,
    and the grid drops the popover altogether right after. Anything that opens
    a window or relayouts the main window from inside the click runs in the
    middle of that teardown, which is where GTK 4.14 crashes: the pointer focus
    still points into the popover whose surface is already gone, and
    ``gtk_window_native_layout`` asks that surface for a motion event. An idle
    callback runs after the teardown, so the two never overlap.

    The callback is also the last place a context-menu action can raise, so an
    exception is logged here instead of escaping into the main loop.
    """
    root_popover.popdown()

    def _run():
        try:
            callback()
        except Exception:
            logger.exception("context menu action failed")
        return False

    GLib.idle_add(_run)


def _activate_action_row(root_popover, action_name):
    """Fire a named action after the menu is gone.

    The action group lives on the widget the popover hangs off (the ROM card),
    which is looked up now: by the time the idle runs the popover has been
    unparented and can no longer resolve anything.
    """
    anchor = root_popover.get_parent()
    if anchor is None:
        logger.warning("context menu row has no anchor: action=%s", action_name)
        return
    _run_after_close(root_popover, lambda: anchor.activate_action(action_name, None))


def _menu_row(root_popover, label, action, icon_name, swatch_hex=None):
    content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
    content.append(_icon_image(icon_name))
    # "" is a deliberate blank: a spacer that keeps a swatch menu's labels
    # aligned on rows that have no color of their own (the Default entry).
    if swatch_hex is not None:
        content.append(_swatch_widget(swatch_hex))
    text = Gtk.Label(label=label)
    text.set_halign(Gtk.Align.START)
    text.set_hexpand(True)
    content.append(text)

    button = Gtk.Button()
    button.set_child(content)
    button.add_css_class("flat")
    button.add_css_class("context-menu-item")
    if action is None:
        # A display-only row (an empty save slot): visible, not clickable.
        button.set_sensitive(False)
    elif callable(action):
        # Close the whole chain first so the callback's dialog is not covered
        # by a lingering popover, then run it.
        button.connect("clicked", lambda _b, cb=action: _run_after_close(root_popover, cb))
    else:
        # Deliberately not set_action_name: GTK would fire the action from
        # inside the click, while the menu is still coming down. The action is
        # activated by hand once that is over -- see _run_after_close.
        button.connect(
            "clicked", lambda _b, name=action: _activate_action_row(root_popover, name)
        )
    return button


def _submenu_row(root_popover, submenu):
    content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
    content.append(_icon_image(submenu.icon_name))
    text = Gtk.Label(label=submenu.label)
    text.set_halign(Gtk.Align.START)
    text.set_hexpand(True)
    content.append(text)
    content.append(Gtk.Image.new_from_icon_name("go-next-symbolic"))

    button = Gtk.Button()
    button.set_child(content)
    button.add_css_class("flat")
    button.add_css_class("context-menu-item")

    child = Gtk.Popover()
    child.set_has_arrow(False)
    child.add_css_class("menu")
    child.set_position(Gtk.PositionType.RIGHT)
    child.set_child(_build_menu_box(submenu.entries, root_popover))
    child.set_parent(button)

    button.connect("clicked", lambda _b: child.popup())
    # The nested popover is parented to this row; drop it when the row goes so
    # it is not left orphaned when the whole menu is torn down.
    button.connect("destroy", lambda _b: child.unparent())
    return button
