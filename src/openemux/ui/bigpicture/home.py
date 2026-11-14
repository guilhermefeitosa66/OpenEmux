"""The home page of Big Picture: what to play, where to go, what to do.

Three rows, top to bottom, each a horizontal strip the D-pad walks:
"Continue playing" (the last games launched, as cards), "Consoles" (every
library scope -- All, Recently played, Favorites, the playlists, the
consoles with games) and "System" (search, import, covers, sharing,
Settings, the desktop). Up and Down move between the rows; Left and Right
within one. A, on anything, opens it.
"""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import GLib, Gtk, Pango

from openemux.core import cover_cache
from openemux.core.scraper import COVER_ART, find_local_art
from openemux.ui.bigpicture.widgets import BigPage, Tile, eyebrow, rail_entry_for_scope
from openemux.ui.scopes import (
    ALL_CONSOLES_ID,
    FAVORITES_ID,
    RECENT_ID,
    collection_slug,
    is_collection_scope,
)

#: How many "continue playing" cards the row shows.
CONTINUE_LIMIT = 5
#: The card's cover, at scale 1.0: wide, like a screenshot, not a box.
CONTINUE_COVER = (264, 198)


class ContinueCard(Gtk.Button):
    """A recently played game: its cover, its name and when it was played."""

    def __init__(self, win, rom, caption):
        super().__init__()
        self.win = win
        self.rom = rom
        self.add_css_class("bp-tile")
        self.add_css_class("flat")
        self.add_css_class("bp-continue")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.picture = Gtk.Picture()
        self.picture.set_content_fit(Gtk.ContentFit.COVER)
        self.picture.set_can_shrink(True)
        self.picture.add_css_class("rom-cover")
        self.picture.set_size_request(*CONTINUE_COVER)
        box.append(self.picture)
        name = Gtk.Label(label=rom.get("name", ""), xalign=0.0)
        name.add_css_class("bp-tile-name")
        name.set_ellipsize(Pango.EllipsizeMode.END)
        name.set_max_width_chars(22)
        box.append(name)
        self.caption = Gtk.Label(label=caption or "", xalign=0.0)
        self.caption.add_css_class("bp-tile-count")
        self.caption.set_ellipsize(Pango.EllipsizeMode.END)
        self.caption.set_max_width_chars(28)
        box.append(self.caption)
        self.set_child(box)
        # Looked up at click time, not bound at construction: the window's
        # launch is what a test patches, and what a relaunch replaces.
        self.connect("clicked", lambda _b: self.win.on_launch_game(self.rom))
        self._load_cover()

    def _load_cover(self):
        rom = self.rom
        roms_dir = self.win.roms_path
        width, height = CONTINUE_COVER

        def _worker():
            path = find_local_art(roms_dir, rom.get("console", ""), rom.get("name", ""), COVER_ART)
            pixbuf = cover_cache.load_cover(str(path), width * 2, height * 2) if path else None
            GLib.idle_add(self._apply, pixbuf)

        cover_cache.submit(_worker)

    def _apply(self, pixbuf):
        if pixbuf is not None and self.get_root() is not None:
            from openemux.ui.rom_card import texture_for

            self.picture.set_paintable(texture_for(pixbuf))
        return GLib.SOURCE_REMOVE


class HomePage(BigPage):
    context = "bp-home"

    def __init__(self, shell):
        t = shell.win.t
        super().__init__(shell, t("big_picture.home.library"), tag="bp-home")
        self.continue_row = self._row(t("big_picture.home.continue"))
        self.console_row = self._row(t("big_picture.home.consoles"))
        self.system_row = self._row(t("big_picture.home.system"))
        self.body.append(self.scrolled(self._rows_box))
        self.continue_cards = []
        self.console_tiles = []
        self.system_tiles = []
        self._build_system_row()

    def _row(self, title):
        if not hasattr(self, "_rows_box"):
            self._rows_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=28)
        section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        section.append(eyebrow(title))
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.EXTERNAL, Gtk.PolicyType.NEVER)
        strip = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=24)
        scroller.set_child(strip)
        section.append(scroller)
        section.strip = strip
        self._rows_box.append(section)
        return section

    @staticmethod
    def _clear(strip):
        child = strip.get_first_child()
        while child is not None:
            following = child.get_next_sibling()
            strip.remove(child)
            child = following

    # -- rows ------------------------------------------------------------------
    def refresh(self):
        """Rebuild the rows from the library as it is now."""
        self._build_continue_row()
        self._build_console_row()

    def _build_continue_row(self):
        win = self.win
        strip = self.continue_row.strip
        self._clear(strip)
        self.continue_cards = []
        paths = win.play_history.recent(CONTINUE_LIMIT)
        entries = win.playlist_manager.entries_for_paths(paths) if paths else []
        for rom in entries[:CONTINUE_LIMIT]:
            caption = win.play_caption(rom) or win.t("details.never_played")
            console = win.sidebar.label_for(rom.get("console", ""))
            card = ContinueCard(win, rom, f"{console} · {caption}")
            strip.append(card)
            self.continue_cards.append(card)
        self.continue_row.set_visible(bool(self.continue_cards))

    def _build_console_row(self):
        win = self.win
        strip = self.console_row.strip
        self._clear(strip)
        self.console_tiles = []
        for scope_id in self.shell.library_scopes():
            kind = scope_kind(scope_id)
            entry = rail_entry_for_scope(scope_id, win.sidebar.label_for(scope_id), kind)
            _id, name, badge_text, texture, icon_name, style = entry
            tile = Tile(
                name,
                self._count_label(scope_id, kind),
                badge=badge_text,
                texture=texture,
                icon_name=icon_name,
                style=style,
                on_activate=lambda scope_id=scope_id: self.shell.open_library(scope_id),
            )
            tile.scope_id = scope_id
            strip.append(tile)
            self.console_tiles.append(tile)

    def _count_label(self, scope_id, kind):
        t = self.win.t
        count = self.shell.game_count(scope_id)
        if kind == "collection":
            return t("big_picture.home.playlist_count", count=count)
        if count is None:
            return None
        if count == 1:
            return t("header.subtitle.one_game")
        return t("header.subtitle.games", count=count)

    def _build_system_row(self):
        t = self.win.t
        strip = self.system_row.strip
        for entry_id, key, icon in (
            ("search", "big_picture.tile.search", "system-search-symbolic"),
            ("import", "big_picture.tile.import", "folder-download-symbolic"),
            ("covers", "big_picture.tile.covers", "emblem-photos-symbolic"),
            ("share", "big_picture.tile.share", "send-to-symbolic"),
            ("settings", "big_picture.tile.settings", "preferences-system-symbolic"),
            ("desktop", "big_picture.tile.desktop", "video-display-symbolic"),
        ):
            tile = Tile(
                t(key),
                icon_name=icon,
                wide=True,
                on_activate=lambda entry_id=entry_id: self.shell.run_quick_action(entry_id),
            )
            tile.entry_id = entry_id
            strip.append(tile)
            self.system_tiles.append(tile)

    def focus_default(self):
        if self.continue_cards:
            return self.continue_cards[0].grab_focus()
        if self.console_tiles:
            return self.console_tiles[0].grab_focus()
        return self.system_tiles[0].grab_focus()

    def hints(self, g, t):
        return [
            (g["confirm"], t("big_picture.hints.open")),
            (g["consoles"], t("hints.console_switch")),
            (g["start"], t("hints.search")),
            (g["menu"], t("big_picture.hints.quick_menu")),
            (g["guide"], t("big_picture.hints.desktop")),
        ]


def scope_kind(scope_id):
    if scope_id == ALL_CONSOLES_ID:
        return "all"
    if scope_id == FAVORITES_ID:
        return "favorites"
    if scope_id == RECENT_ID:
        return "recent"
    if is_collection_scope(scope_id):
        return "collection"
    return "console"


__all__ = ["HomePage", "ContinueCard", "scope_kind", "collection_slug"]
