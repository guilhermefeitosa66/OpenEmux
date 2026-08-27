"""File-filter helpers shared by the app's ``Gtk.FileDialog`` call sites.

``Gtk.FileDialog`` (GTK 4.10) takes its filters as a ``Gio.ListStore`` rather
than through ``add_filter``, and every picker that asks for an image builds the
same one out of :data:`SUPPORTED_COVER_EXTS`. It used to be built twice by
hand, in ``ui/window.py`` and ``ui/artwork_manager.py``, which is how the two
drifted apart in the first place (issue #235).
"""

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Gio

from openemux.core.scraper import SUPPORTED_COVER_EXTS


def image_filters(name="Images"):
    """The filter list for a picker that wants a cover, and its default.

    ``Gtk.FileDialog`` wants both: the ``Gio.ListStore`` of filters to offer,
    and which one starts selected. The filter matches every extension in
    :data:`SUPPORTED_COVER_EXTS`, upper-cased as well -- a cover another tool
    saved as ``.PNG`` is one the app reads back happily.
    """
    image_filter = Gtk.FileFilter()
    image_filter.set_name(name)
    for ext in SUPPORTED_COVER_EXTS:
        image_filter.add_pattern(f"*.{ext}")
        image_filter.add_pattern(f"*.{ext.upper()}")
    filters = Gio.ListStore.new(Gtk.FileFilter)
    filters.append(image_filter)
    return filters, image_filter
