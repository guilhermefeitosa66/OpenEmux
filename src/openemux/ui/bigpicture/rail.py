"""The navigation rail of Big Picture: Android's tabs, down the left (issues 957, 975).

The app's logo on top, then Library, Recent, Import and Settings, each an
icon over its label; the tab on screen sits on an accent pill. LB and RB
walk the tabs from a tab's first page; A, or a click, opens one.

Last, after Settings, "Back to desktop" (issue 978): drawn like a tab and
reached with Down from Settings, but an action, not a tab -- it never takes
the pill, LB and RB skip it, and A leaves the mode as Guide and F11 do.
"""

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Pango

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

#: The way out, after the tabs: id, label key, icon (the header button's screen).
DESKTOP = ("desktop", "big_picture.tab.desktop", "video-display-symbolic")

#: How wide, in characters, the way out's label may run before it wraps.
DESKTOP_LABEL_CHARS = 9

#: The app's icon, the rail's logo.
LOGO_ICON = "io.github.guilhermefeitosa66.OpenEmux"


class TabButton(Gtk.Button):
    """One tab: the icon on its pill, the label under it."""

    def __init__(self, tab_id, label, icon_name):
        super().__init__()
        self.tab_id = tab_id
        self.add_css_class("bp-tab")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
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
    """The rail. ``on_select(tab_id)`` runs when a tab is activated,
    ``on_leave()`` when "Back to desktop" is."""

    def __init__(self, t, on_select, on_leave=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.add_css_class("bp-rail")
        # Set, not left to the children: an expanding icon inside a tab
        # would make the whole rail take the screen's spare width.
        self.set_hexpand(False)
        self.on_select = on_select
        self.on_leave = on_leave
        self.current = TAB_LIBRARY
        logo = Gtk.Image.new_from_icon_name(LOGO_ICON)
        logo.add_css_class("bp-rail-logo")
        logo.set_halign(Gtk.Align.CENTER)
        self.append(logo)
        self.buttons = {}
        for tab_id, key, icon in TABS:
            button = TabButton(tab_id, t(key), icon)
            button.connect("clicked", lambda _b, tab_id=tab_id: self.on_select(tab_id))
            self.append(button)
            self.buttons[tab_id] = button
        desktop_id, desktop_key, desktop_icon = DESKTOP
        self.desktop = TabButton(desktop_id, t(desktop_key), desktop_icon)
        # Two short lines rather than a wider rail (issue 975 slimmed it).
        label = self.desktop.label
        label.set_wrap(True)
        label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        label.set_justify(Gtk.Justification.CENTER)
        label.set_max_width_chars(DESKTOP_LABEL_CHARS)
        self.desktop.connect("clicked", self._on_desktop)
        self.append(self.desktop)
        self.mark(TAB_LIBRARY)

    def _on_desktop(self, _button):
        if self.on_leave is not None:
            self.on_leave()

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
        self.desktop.label.set_label(t(DESKTOP[1]))


__all__ = [
    "NavRail", "TabButton", "TABS", "TAB_IDS", "DESKTOP",
    "TAB_LIBRARY", "TAB_RECENT", "TAB_IMPORT", "TAB_SETTINGS",
]
