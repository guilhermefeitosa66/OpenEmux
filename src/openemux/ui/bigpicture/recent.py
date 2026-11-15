"""The Recent tab: the games played last, Android's way (issue 957).

One row per game, the newest first, with the screenshot of its last save
state (or its cover) and "Console · played 2 h ago". At most twelve, the
play history's own limit (issue 942). A on a row opens the game's detail.
With nothing played yet, Android's empty state.
"""

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk, Pango

from openemux.core import cover_cache, save_states
from openemux.core.play_history import RECENT_LIMIT
from openemux.core.scraper import COVER_ART, LABEL_ART, resolve_local_art
from openemux.ui.bigpicture.widgets import BigPage, empty_state, page_heading

#: The thumbnail of a row, at scale 1.0.
THUMB = (128, 96)


class RecentRow(Gtk.Button):
    """A played game: its picture, its name, where and when it was played."""

    def __init__(self, rom, caption, on_activate):
        super().__init__()
        self.rom = rom
        self.add_css_class("bp-row")
        self.add_css_class("bp-list-row")
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=20)
        box.set_valign(Gtk.Align.CENTER)
        self.picture = Gtk.Picture()
        self.picture.set_content_fit(Gtk.ContentFit.COVER)
        self.picture.set_can_shrink(True)
        self.picture.set_size_request(*THUMB)
        box.append(self.picture)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        text.set_valign(Gtk.Align.CENTER)
        text.set_hexpand(True)
        name = Gtk.Label(label=rom.get("name", ""), xalign=0.0)
        name.add_css_class("bp-row-title")
        name.set_ellipsize(Pango.EllipsizeMode.END)
        text.append(name)
        self.caption = Gtk.Label(label=caption, xalign=0.0)
        self.caption.add_css_class("bp-row-subtitle")
        self.caption.set_ellipsize(Pango.EllipsizeMode.END)
        text.append(self.caption)
        box.append(text)
        chevron = Gtk.Label(label="›")
        chevron.add_css_class("bp-row-chevron")
        box.append(chevron)
        self.set_child(box)
        self.connect("clicked", lambda _b: on_activate(self.rom))

    def show_pixbuf(self, pixbuf):
        if pixbuf is not None:
            from openemux.ui.rom_card import texture_for

            self.picture.set_paintable(texture_for(pixbuf))


def latest_picture(win, rom):
    """The newest save state's screenshot, else the game's cover or label."""
    states_dir = win.config_manager.get_console_states_dir(rom.get("console", ""))
    states = [state for state in save_states.list_states(states_dir, rom.get("path", "")) if state.thumbnail]
    if states:
        return max(states, key=lambda state: state.mtime).thumbnail
    return resolve_local_art(rom, win.roms_path, kinds=(COVER_ART, LABEL_ART))


class RecentPage(BigPage):
    context = "bp-page"

    def __init__(self, shell):
        t = shell.win.t
        super().__init__(shell, t("big_picture.tab.recent"), crumbs=[], tag="bp-recent")
        self.rows = []
        column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        column.append(page_heading(t("big_picture.recent.title")))
        self.list_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.list_box.set_margin_top(12)
        column.append(self.list_box)
        self.empty = empty_state("document-open-recent-symbolic", t("big_picture.recent.empty"))
        column.append(self.empty)
        self.body.append(self.scrolled(column))

    def refresh(self):
        win, t = self.win, self.win.t
        child = self.list_box.get_first_child()
        while child is not None:
            following = child.get_next_sibling()
            self.list_box.remove(child)
            child = following
        self.rows = []
        paths = win.play_history.recent(RECENT_LIMIT)
        roms = win.playlist_manager.entries_for_paths(paths) if paths else []
        for rom in roms[:RECENT_LIMIT]:
            console = win.sidebar.label_for(rom.get("console", ""))
            caption = f"{console} · {win.play_caption(rom) or t('details.never_played')}"
            row = RecentRow(rom, caption, self.shell.open_details)
            self.list_box.append(row)
            self.rows.append(row)
            self._load_picture(row)
        self.empty.set_visible(not self.rows)
        self.list_box.set_visible(bool(self.rows))

    def _load_picture(self, row):
        win = self.win
        width, height = THUMB

        def _worker():
            path = latest_picture(win, row.rom)
            pixbuf = cover_cache.load_cover(str(path), width * 2, height * 2) if path else None
            GLib.idle_add(self._apply, row, pixbuf)

        cover_cache.submit(_worker)

    @staticmethod
    def _apply(row, pixbuf):
        row.show_pixbuf(pixbuf)
        return GLib.SOURCE_REMOVE

    def focus_default(self):
        if self.rows:
            return self.rows[0].grab_focus()
        return self.shell.rail.focus_current()

    def hints(self, g, t):
        return [
            (g["confirm"], t("big_picture.hints.details")),
            (g["consoles"], t("big_picture.hints.tabs")),
        ]


__all__ = ["RecentPage", "RecentRow", "latest_picture"]
