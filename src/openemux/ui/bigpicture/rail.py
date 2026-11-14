"""The navigation rail of Big Picture: Android's tabs, down the left (issue 957).

The app's logo on top, then Library, Recent, Import and Settings, each an
icon over its label; the tab on screen sits on an accent pill. LB and RB
walk the tabs from a tab's first page; A, or a click, opens one.
"""

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

TAB_LIBRARY = "library"
TAB_RECENT = "recent"
TAB_IMPORT = "import"
TAB_SETTINGS = "settings"

#: The tabs, top to bottom: id, label key, icon.
TABS = (
    (TAB_LIBRARY, "big_picture.tab.library", "view-grid-symbolic"),
    (TAB_RECENT, "big_picture.tab.recent", "document-open-recent-symbolic"),
    (TAB_IMPORT, "big_picture.tab.import", "folder-download-symbolic"),
    (TAB_SETTINGS, "big_picture.tab.settings", "emblem-system-symbolic"),
)
TAB_IDS = tuple(tab_id for tab_id, _key, _icon in TABS)

#: The app's icon, the rail's logo.
LOGO_ICON = "io.github.guilhermefeitosa66.OpenEmux"


class TabButton(Gtk.Button):
    """One tab: the icon on its pill, the label under it."""

    def __init__(self, tab_id, label, icon_name):
        super().__init__()
        self.tab_id = tab_id
        self.add_css_class("bp-tab")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_halign(Gtk.Align.CENTER)
        pill = Gtk.Box()
        pill.add_css_class("bp-tab-pill")
        pill.set_halign(Gtk.Align.CENTER)
        icon = Gtk.Image.new_from_icon_name(icon_name)
        icon.set_hexpand(True)
        icon.set_halign(Gtk.Align.CENTER)
        pill.append(icon)
        box.append(pill)
        self.label = Gtk.Label(label=label)
        self.label.add_css_class("bp-tab-label")
        box.append(self.label)
        self.set_child(box)

    def set_current(self, current):
        if current:
            self.add_css_class("bp-current")
        else:
            self.remove_css_class("bp-current")


class NavRail(Gtk.Box):
    """The rail. ``on_select(tab_id)`` runs when a tab is activated."""

    def __init__(self, t, on_select):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        self.add_css_class("bp-rail")
        # Set, not left to the children: an expanding icon inside a tab
        # would make the whole rail take the screen's spare width.
        self.set_hexpand(False)
        self.on_select = on_select
        self.current = TAB_LIBRARY
        logo = Gtk.Image.new_from_icon_name(LOGO_ICON)
        logo.add_css_class("bp-rail-logo")
        logo.set_halign(Gtk.Align.CENTER)
        logo.set_pixel_size(64)
        self.append(logo)
        self.buttons = {}
        for tab_id, key, icon in TABS:
            button = TabButton(tab_id, t(key), icon)
            button.connect("clicked", lambda _b, tab_id=tab_id: self.on_select(tab_id))
            self.append(button)
            self.buttons[tab_id] = button
        self.mark(TAB_LIBRARY)

    def mark(self, tab_id):
        """Put the pill on ``tab_id`` without selecting it."""
        self.current = tab_id
        for button_id, button in self.buttons.items():
            button.set_current(button_id == tab_id)

    def neighbour(self, delta):
        """The tab ``delta`` steps from the current one, wrapping around."""
        index = TAB_IDS.index(self.current) if self.current in TAB_IDS else 0
        return TAB_IDS[(index + delta) % len(TAB_IDS)]

    def focus_current(self):
        return self.buttons[self.current].grab_focus()

    def retranslate(self, t):
        for tab_id, key, _icon in TABS:
            self.buttons[tab_id].label.set_label(t(key))


__all__ = [
    "NavRail", "TabButton", "TABS", "TAB_IDS",
    "TAB_LIBRARY", "TAB_RECENT", "TAB_IMPORT", "TAB_SETTINGS",
]
