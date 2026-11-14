"""The pad file browser behind Big Picture's Import (issue 957).

GTK's file chooser cannot be driven with a pad, so Import opens this page
instead (maintainer decision 3), in the Android list style: the folder on
top, then its folders and the files OpenEmux can import. A enters a folder
or marks a file, X marks too, B goes up a folder (at the root of the
disk, it closes), Y hands over what is marked -- or, choosing a whole
folder, the folder on screen.
"""

from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk, Pango

from openemux.core import pad_browser
from openemux.core.systems import SYSTEMS
from openemux.ui.bigpicture.import_page import MODE_FILES, MODE_FOLDER
from openemux.ui.bigpicture.widgets import BigPage, body, empty_state, once


class EntryRow(Gtk.Button):
    """A folder or a file of the listing; a marked file shows a check."""

    def __init__(self, entry, on_activate):
        super().__init__()
        self.entry = entry
        self.add_css_class("bp-row")
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        box.set_valign(Gtk.Align.CENTER)
        box.append(Gtk.Image.new_from_icon_name("folder-symbolic" if entry.is_dir else "text-x-generic-symbolic"))
        name = Gtk.Label(label=entry.name, xalign=0.0)
        name.add_css_class("bp-row-title")
        name.set_hexpand(True)
        name.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        box.append(name)
        self.mark = Gtk.Image.new_from_icon_name("object-select-symbolic")
        self.mark.set_visible(False)
        box.append(self.mark)
        if entry.is_dir:
            chevron = Gtk.Label(label="›")
            chevron.add_css_class("bp-row-chevron")
            box.append(chevron)
        self.set_child(box)
        self.connect("clicked", lambda _b: on_activate(self))

    def set_marked(self, marked):
        self.mark.set_visible(bool(marked))
        if marked:
            self.add_css_class("bp-current")
        else:
            self.remove_css_class("bp-current")


class FileBrowserPage(BigPage):
    context = "bp-browser"

    def __init__(self, shell):
        t = shell.win.t
        super().__init__(shell, t("big_picture.browser.files"), tag="bp-browser")
        self.mode = MODE_FILES
        self.on_pick = None
        self.folder = None
        self.start = None
        self.marked = set()
        self.rows = []
        self._extensions = {
            ext.lower().lstrip(".") for system in SYSTEMS for ext in system.get("extensions", ())
        } | {"zip"}
        self.path_label = body("")
        self.path_label.set_ellipsize(Pango.EllipsizeMode.START)
        self.path_label.set_wrap(False)
        self.body.append(self.path_label)
        self.list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.empty = empty_state("folder-symbolic", t("big_picture.browser.empty"))
        column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        column.append(self.list_box)
        column.append(self.empty)
        self.body.append(self.scrolled(column))

    def open(self, mode, on_pick, folder=None):
        """Start browsing: ``mode`` picks files or a folder; ``on_pick(paths)`` takes the result."""
        t = self.win.t
        self.mode = mode
        self.on_pick = on_pick
        title = t("big_picture.browser.files" if mode == MODE_FILES else "big_picture.browser.folder")
        self.set_title(title)
        self.set_crumbs([t("big_picture.tab.import"), title])
        self.start = pad_browser.start_folder(folder or self.win.config_manager.get_roms_path())
        self.load(self.start)

    def load(self, folder, focus_name=None):
        self.folder = Path(folder)
        self.marked = set()
        self.path_label.set_label(str(self.folder))
        child = self.list_box.get_first_child()
        while child is not None:
            following = child.get_next_sibling()
            self.list_box.remove(child)
            child = following
        self.rows = []
        target = None
        for entry in pad_browser.list_dir(self.folder, self._extensions):
            if self.mode == MODE_FOLDER and not entry.is_dir:
                continue
            row = EntryRow(entry, self._on_row)
            self.list_box.append(row)
            self.rows.append(row)
            if focus_name is not None and entry.name == focus_name:
                target = row
        self.empty.set_visible(not self.rows)
        if target is not None:
            GLib.idle_add(once(target.grab_focus))
        elif self.get_root() is not None:
            GLib.idle_add(once(self.focus_default))

    def _on_row(self, row):
        if row.entry.is_dir:
            self.load(row.entry.path)
        else:
            self.toggle_mark(row)

    def toggle_mark(self, row):
        if row is None or row.entry.is_dir:
            return False
        path = row.entry.path
        if path in self.marked:
            self.marked.discard(path)
        else:
            self.marked.add(path)
        row.set_marked(path in self.marked)
        return True

    def _focused_row(self):
        focus = self.win.get_focus()
        for row in self.rows:
            if focus is not None and (focus is row or focus.is_ancestor(row)):
                return row
        return None

    def confirm(self):
        """Y: the marked files (or the one focused), or the folder on screen."""
        if self.mode == MODE_FOLDER:
            paths = [self.folder]
        else:
            paths = sorted(self.marked)
            if not paths:
                row = self._focused_row()
                if row is None or row.entry.is_dir:
                    return False
                paths = [row.entry.path]
        on_pick = self.on_pick
        self.shell.pop()
        if on_pick is not None:
            on_pick(paths)
        return True

    def handle_back(self):
        """B: up a folder, past where it opened (a download folder, a USB
        drive are outside the library); at the root, close."""
        if self.folder is None:
            return False
        above = pad_browser.parent(self.folder)
        if above is None:
            return False
        self.load(above, focus_name=self.folder.name)
        return True

    def on_pad_action(self, action):
        if action == "context":
            return self.toggle_mark(self._focused_row())
        if action == "favorite":
            return self.confirm()
        return False

    def focus_default(self):
        if self.rows:
            return self.rows[0].grab_focus()
        return False

    def hints(self, g, t):
        if self.mode == MODE_FOLDER:
            return [
                (g["confirm"], t("big_picture.hints.open")),
                (g["favorite"], t("big_picture.browser.import_folder")),
                (g["back"], t("big_picture.browser.up")),
            ]
        return [
            (g["confirm"], t("big_picture.hints.open")),
            (g["context"], t("big_picture.browser.mark")),
            (g["favorite"], t("big_picture.browser.import")),
            (g["back"], t("big_picture.browser.up")),
        ]


__all__ = ["EntryRow", "FileBrowserPage"]
