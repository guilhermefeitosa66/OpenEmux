#!/usr/bin/env python3
"""Browse the symbolic icons OpenEmux is allowed to use, with their names.

A dev utility for picking icons for the UI (header buttons, menu rows): a
searchable grid rendered through the app's own theme and stylesheet, with the
icon name under each one. Clicking an icon copies its name to the clipboard.

**Only Adwaita ships here.** The developer's desktop usually has extra icon
themes installed (Papirus, Numix, Mint's XApp set…) and the running GTK theme
happily lists all of them -- but an icon from those renders as a broken image
on a stock GNOME system, inside the Flatpak's GNOME runtime, or on any distro
without that theme package. ``adwaita-icon-theme`` is what the packages
declare as a dependency, so Adwaita plus GTK's own built-ins is exactly the
safe set, and the only thing this browser offers.

The icons the view-mode segmented control uses today are marked, so a
candidate can be compared against what is already there.

    PYTHONPATH=src python3 tools/icon_browser.py [initial filter]
    make icons                       # same thing
    make icons FILTER=view           # opening on a filter
"""

import sys
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GObject, Gtk

#: Where the adwaita-icon-theme package installs its icons.
ADWAITA_DIRS = [
    Path("/usr/share/icons/Adwaita"),
    Path("/app/share/icons/Adwaita"),  # inside the Flatpak sandbox
]

#: GTK bundles a handful of icons in its own gresource, always present.
GTK_ICON_RESOURCE = "/org/gtk/libgtk/icons/"


def safe_icon_names():
    """Symbolic icons guaranteed to exist wherever OpenEmux is installed."""
    names = set()
    for directory in ADWAITA_DIRS:
        if directory.is_dir():
            names |= {path.stem for path in directory.rglob("*.svg")}

    def walk(path):
        try:
            children = Gio.resources_enumerate_children(path, Gio.ResourceLookupFlags.NONE)
        except Exception:
            return
        for child in children:
            if child.endswith("/"):
                walk(path + child)
            elif child.endswith((".svg", ".png")):
                names.add(child.rsplit(".", 1)[0])

    walk(GTK_ICON_RESOURCE)
    # ".symbolic" is how GTK names the recolorable copies in its resource.
    return sorted(
        n for n in names if n.endswith("-symbolic") and not n.endswith(".symbolic")
    )

#: Where each icon is used today, shown as the badge under the name.
IN_USE = {
    "view-grid-symbolic": "Cover grid",
    "input-gaming-symbolic": "Cartridge grid",
    "view-list-symbolic": "Compact list",
}

#: One-click filters, ordered by how likely they are to hold a view-mode icon.
QUICK_FILTERS = [
    "view", "grid", "list", "column", "image", "media",
    "input", "object", "emblem", "application",
]

ICON_SIZE = 32
CELL_WIDTH = 132


class IconBrowser(Adw.Application):
    def __init__(self):
        super().__init__(application_id="io.github.guilhermefeitosa66.OpenEmux.IconBrowser")
        self._cells = []

    def do_activate(self):
        window = Adw.ApplicationWindow(application=self)
        window.set_title("OpenEmux — icon browser")
        window.set_default_size(1040, 720)

        self.search = Gtk.SearchEntry()
        self.search.set_placeholder_text("Filter icons…")
        self.search.set_hexpand(True)
        self.search.connect("search-changed", lambda _e: self._refilter())

        header = Adw.HeaderBar()
        header.set_title_widget(self.search)

        chips = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        chips.set_margin_top(10)
        chips.set_margin_bottom(4)
        chips.set_margin_start(12)
        chips.set_margin_end(12)
        for term in QUICK_FILTERS:
            chip = Gtk.Button(label=term)
            chip.add_css_class("pill")
            chip.connect("clicked", lambda _b, t=term: self.search.set_text(t))
            chips.append(chip)
        clear = Gtk.Button(label="all")
        clear.add_css_class("pill")
        clear.connect("clicked", lambda _b: self.search.set_text(""))
        chips.append(clear)

        self.count_label = Gtk.Label()
        self.count_label.add_css_class("dim-label")
        self.count_label.set_hexpand(True)
        self.count_label.set_xalign(1.0)
        chips.append(self.count_label)

        self.flow = Gtk.FlowBox()
        self.flow.set_valign(Gtk.Align.START)
        self.flow.set_selection_mode(Gtk.SelectionMode.NONE)
        self.flow.set_homogeneous(True)
        self.flow.set_row_spacing(4)
        self.flow.set_column_spacing(4)
        self.flow.set_margin_start(12)
        self.flow.set_margin_end(12)
        self.flow.set_margin_bottom(12)
        self.flow.set_filter_func(self._filter_cell)

        # In-use icons first, so the comparison is the first thing on screen.
        names = sorted(safe_icon_names(), key=lambda n: (n not in IN_USE, n))
        for name in names:
            self.flow.append(self._make_cell(name))

        scroller = Gtk.ScrolledWindow(vexpand=True)
        scroller.set_child(self.flow)

        self.toast_overlay = Adw.ToastOverlay()
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        body.append(chips)
        body.append(scroller)
        self.toast_overlay.set_child(body)

        view = Adw.ToolbarView()
        view.add_top_bar(header)
        view.set_content(self.toast_overlay)
        window.set_content(view)

        self._apply_css()
        if len(sys.argv) > 1:
            self.search.set_text(sys.argv[1])
        self._refilter()
        window.present()
        self.search.grab_focus()

    def _apply_css(self):
        css = Gtk.CssProvider()
        css.load_from_data(b"""
            .icon-cell { padding: 10px 4px; border-radius: 8px; }
            .icon-cell:hover { background: alpha(currentColor, 0.08); }
            .icon-cell-used { background: alpha(@accent_bg_color, 0.16); }
            .icon-name { font-size: 0.78em; }
            .icon-badge { font-size: 0.7em; }
        """)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def _make_cell(self, name):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.add_css_class("icon-cell")
        box.set_size_request(CELL_WIDTH, -1)

        image = Gtk.Image.new_from_icon_name(name)
        image.set_pixel_size(ICON_SIZE)
        box.append(image)

        label = Gtk.Label(label=name.removesuffix("-symbolic"))
        label.add_css_class("icon-name")
        label.set_wrap(True)
        label.set_justify(Gtk.Justification.CENTER)
        label.set_max_width_chars(16)
        label.set_tooltip_text(name)
        box.append(label)

        if name in IN_USE:
            box.add_css_class("icon-cell-used")
            badge = Gtk.Label(label=f"● {IN_USE[name]}")
            badge.add_css_class("icon-badge")
            badge.add_css_class("accent")
            box.append(badge)

        button = Gtk.Button()
        button.set_child(box)
        button.add_css_class("flat")
        button.set_tooltip_text(f"{name} — click to copy")
        button.connect("clicked", lambda _b, n=name: self._copy(n))

        child = Gtk.FlowBoxChild()
        child.set_child(button)
        child.icon_name = name
        self._cells.append(child)
        return child

    def _copy(self, name):
        clipboard = Gdk.Display.get_default().get_clipboard()
        clipboard.set_content(Gdk.ContentProvider.new_for_value(GObject.Value(str, name)))
        self.toast_overlay.add_toast(Adw.Toast(title=f"Copied {name}", timeout=2))

    def _filter_cell(self, child):
        query = self.search.get_text().strip().lower()
        return not query or query in child.icon_name.lower()

    def _refilter(self):
        self.flow.invalidate_filter()
        query = self.search.get_text().strip().lower()
        shown = sum(1 for c in self._cells if not query or query in c.icon_name.lower())
        self.count_label.set_label(
            f"{shown} of {len(self._cells)} Adwaita symbolic icons (safe everywhere)"
        )


if __name__ == "__main__":
    # argv is consumed as the initial filter, not by GApplication.
    IconBrowser().run([])
