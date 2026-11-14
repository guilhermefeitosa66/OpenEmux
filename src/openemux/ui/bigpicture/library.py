"""The library page of Big Picture: the console rail over the games.

The rail is the sidebar, laid on its side: every scope the desktop lists --
All, Recently played, Favorites, the playlists, the consoles with games --
as one row of tiles, the current one marked, LB and RB stepping through it
from anywhere on the page. Under it, the very same page the desktop shows
for that scope: the window's content stack, with its grids, its grouped
pages and its empty states, moved under the rail while the mode is on and
handed back when it ends. The search keyboard slides up over the games.
"""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import GLib, Gtk

from openemux.ui.bigpicture.osk import MODE_SEARCH, OnScreenKeyboard
from openemux.ui.bigpicture.widgets import BigPage, Rail, once, rail_entry_for_scope
from openemux.ui.scopes import ALL_CONSOLES_ID


class LibraryPage(BigPage):
    context = "bp-library"

    def __init__(self, shell):
        t = shell.win.t
        super().__init__(shell, t("big_picture.home.library"), tag="bp-library")
        self.rail = Rail(self._on_rail_select)
        self.body.append(self.rail)
        self.content_host = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.content_host.set_vexpand(True)
        self.overlay = Gtk.Overlay()
        self.overlay.set_vexpand(True)
        self.overlay.set_child(self.content_host)
        self.osk_revealer = Gtk.Revealer()
        self.osk_revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_UP)
        self.osk_revealer.set_valign(Gtk.Align.END)
        self.osk_revealer.set_reveal_child(False)
        self.osk = OnScreenKeyboard(
            t, MODE_SEARCH, on_change=self._on_search_typed, on_done=self._on_search_done
        )
        sheet = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        sheet.add_css_class("bp-sheet")
        sheet.append(self.osk)
        self.osk_revealer.set_child(sheet)
        self.overlay.add_overlay(self.osk_revealer)
        self.body.append(self.overlay)
        self._attached = False
        self._rail_ids = None

    # -- the desktop's content, borrowed ------------------------------------
    def attach_content(self):
        """Move the window's page stack under the rail."""
        if self._attached:
            return
        win = self.win
        win.content_toolbar.set_content(None)
        self.content_host.append(win.content_overlay)
        self._attached = True

    def detach_content(self):
        """Give the page stack back to the desktop layout."""
        if not self._attached:
            return
        win = self.win
        self.content_host.remove(win.content_overlay)
        win.content_toolbar.set_content(win.content_overlay)
        self._attached = False
        self.hide_search()

    # -- the rail ----------------------------------------------------------------
    def sync(self):
        """Rebuild the rail when the scopes changed; mark the current one."""
        win = self.win
        ids = self.shell.library_scopes()
        if ids != self._rail_ids:
            entries = []
            for scope_id in ids:
                from openemux.ui.bigpicture.home import scope_kind

                entries.append(
                    rail_entry_for_scope(scope_id, win.sidebar.label_for(scope_id), scope_kind(scope_id))
                )
            self.rail.set_entries(entries)
            self._rail_ids = ids
        self.rail.mark_current(win.current_console)
        self.set_crumbs([win.t("big_picture.home.library"), win.sidebar.label_for(win.current_console)])

    def _on_rail_select(self, scope_id):
        win = self.win
        if win.current_console != scope_id:
            win.sidebar.select(scope_id)
        self.set_crumbs([win.t("big_picture.home.library"), win.sidebar.label_for(scope_id)])

    def step_console(self, delta):
        """LB/RB: the previous or next scope, the focus staying where it is."""
        focus = self.win.get_focus()
        in_rail = focus is not None and focus.is_ancestor(self.rail)
        moved = self.rail.move(delta)
        if moved and not in_rail:
            GLib.idle_add(once(self.win.navigation._cmd_focus_grid))
        elif moved:
            GLib.idle_add(once(self.rail.focus_current))
        return moved

    def focus_default(self):
        grid = self.win.pages.grid_for(self.win.current_console)
        if grid is not None and grid.count() > 0:
            self.win.navigation._cmd_focus_grid()
            return True
        return self.rail.focus_current()

    # -- search --------------------------------------------------------------------
    @property
    def search_open(self):
        return self.osk_revealer.get_reveal_child()

    def toggle_search(self):
        if self.search_open:
            self.hide_search()
            return False
        return self.show_search()

    def show_search(self):
        win = self.win
        if not win.search_entry.get_sensitive():
            return False
        if not win.search_button.get_active():
            win.search_button.set_active(True)
        self.osk.set_text(win.search_entry.get_text())
        self.osk_revealer.set_reveal_child(True)
        GLib.idle_add(once(self.osk.focus_first_key))
        return True

    def hide_search(self):
        if not self.search_open:
            return
        self.osk_revealer.set_reveal_child(False)
        win = self.win
        grid = win._visible_grid()
        if grid is not None and grid.count() > 0:
            GLib.idle_add(once(grid.focus_first_card))
        else:
            GLib.idle_add(once(self.rail.focus_current))
        if not win.search_entry.get_text():
            win.search_button.set_active(False)

    def _on_search_typed(self, text):
        win = self.win
        if not win.search_button.get_active():
            win.search_button.set_active(True)
        win.search_entry.set_text(text)

    def _on_search_done(self, _text):
        self.hide_search()

    def search_scope_label(self):
        win = self.win
        if win.current_console == ALL_CONSOLES_ID:
            return win.t("big_picture.search.everywhere")
        return win.t("big_picture.search.in", scope=win.sidebar.label_for(win.current_console))

    def hints(self, g, t):
        return [
            (g["confirm"], t("hints.open")),
            (g["back"], t("hints.back")),
            (g["context"], t("hints.details")),
            (g["favorite"], t("hints.favorite")),
            (g["consoles"], t("hints.console_switch")),
            (g["start"], t("hints.search")),
            (g["menu"], t("big_picture.hints.quick_menu")),
        ]
