"""Context menus with an icon next to each entry.

GTK4 ignores the ``icon`` attribute of a ``Gio.MenuItem`` when it builds a
``Gtk.PopoverMenu``: the ``GtkModelButton`` keeps its image hidden, so a menu
built from a model can only ever be text. These helpers build the rows by hand
instead, as flat buttons holding an icon plus a label.
"""

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

SEPARATOR = None


def build_context_popover(entries):
    """Build a menu-styled popover.

    ``entries`` is a sequence of ``(label, action_name, icon_name)`` tuples;
    ``SEPARATOR`` (None) inserts a divider between sections.
    """
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
    box.add_css_class("context-menu-box")

    popover = Gtk.Popover()
    popover.set_child(box)
    popover.set_has_arrow(False)
    popover.set_halign(Gtk.Align.START)
    popover.add_css_class("menu")

    for entry in entries:
        if entry is SEPARATOR:
            box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
            continue
        box.append(_menu_row(popover, *entry))

    return popover


def _menu_row(popover, label, action_name, icon_name):
    content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
    content.append(Gtk.Image.new_from_icon_name(icon_name))
    text = Gtk.Label(label=label)
    text.set_halign(Gtk.Align.START)
    text.set_hexpand(True)
    content.append(text)

    button = Gtk.Button()
    button.set_child(content)
    button.add_css_class("flat")
    button.add_css_class("context-menu-item")
    button.set_action_name(action_name)
    # The action fires on click; close the menu in the same pass so the popover
    # does not linger over whatever dialog the action opens.
    button.connect("clicked", lambda _b: popover.popdown())
    return button
