"""The games of a console, the Android gamepad layout's list-detail (issue 957).

On the left, top to bottom: "‹ Shelf" with the search and filter buttons;
the scope's eyebrow (ALL CONSOLES, FAVORITES, the console's short code),
its big title and how many games it has; the task banners; the console
chips (All · Favorites · the playlists · every console), which LB and RB
walk; the filter chips (Favorites · N, Has save state · N, Missing artwork
· N, Never played · N); the view's name with the Cartridges / Covers /
List switch; and the games themselves -- the window's own page for the
scope, borrowed while the mode is on, so its grids, its per-console
sections in "All" and its empty states are the desktop's.

On the right, the detail pane: "Select a game to see it here" until A
picks a game, then ``details.GameDetail``.
"""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import GLib, Gtk, Pango

from openemux.core import library_facets
from openemux.core.big_picture_shelf import short_name
from openemux.core.library_view import (
    VIEW_MODE_CARTRIDGE as CARTRIDGE,
    VIEW_MODE_COVER as COVER,
    VIEW_MODE_LIST as LIST,
)
from openemux.core.scraper import COVER_ART, LABEL_ART
from openemux.core.systems import get_icon_name
from openemux.ui.bigpicture.banners import TaskBanners
from openemux.ui.bigpicture.details import GameDetail
from openemux.ui.bigpicture.widgets import (
    BigPage,
    Chip,
    PixelIcon,
    Segments,
    empty_state,
    icon_button,
    once,
)
from openemux.ui.console_icons import console_texture, console_texture_1x, scope_icon_name
from openemux.ui.scopes import ALL_CONSOLES_ID, FAVORITES_ID, RECENT_ID

#: The view switch: id, icon, the key of its tooltip and heading.
VIEWS = (
    (CARTRIDGE, "media-floppy-symbolic", "big_picture.view.cartridge"),
    (COVER, "view-grid-symbolic", "big_picture.view.cover"),
    (LIST, "view-list-symbolic", "big_picture.view.list"),
)
VIEW_KEYS = {view_id: key for view_id, _icon, key in VIEWS}

#: The filter chips' labels.
FACET_KEYS = {
    library_facets.FAVORITES: "big_picture.facet.favorites",
    library_facets.HAS_STATE: "big_picture.facet.has_state",
    library_facets.MISSING_ARTWORK: "big_picture.facet.missing_artwork",
    library_facets.NEVER_PLAYED: "big_picture.facet.never_played",
}


class GamesPage(BigPage):
    context = "bp-games"

    def __init__(self, shell):
        t = shell.win.t
        super().__init__(shell, t("big_picture.tab.library"), crumbs=[], tag="bp-games")
        self.active_facets = frozenset()
        self._facts = None
        self._facts_scope = None
        self._facet_serial = 0
        self._chip_ids = None
        self._attached = False
        self.console_chips = {}
        self.facet_chips = {}

        self.body.set_orientation(Gtk.Orientation.HORIZONTAL)
        self.body.set_spacing(0)
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        left.set_hexpand(True)
        left.set_margin_end(24)

        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.back_button = Gtk.Button(label=t("big_picture.games.back"))
        self.back_button.add_css_class("bp-back-link")
        self.back_button.connect("clicked", lambda _b: self.shell.pop())
        top.append(self.back_button)
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        top.append(spacer)
        self.search_button = icon_button("system-search-symbolic", t("hints.search"), self.shell.open_search)
        top.append(self.search_button)
        self.filter_button = icon_button("view-more-horizontal-symbolic", t("big_picture.games.filters"),
                                         self.toggle_filters)
        top.append(self.filter_button)
        left.append(top)

        heading = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        titles = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        titles.set_hexpand(True)
        self.eyebrow_label = Gtk.Label(xalign=0.0)
        self.eyebrow_label.add_css_class("bp-eyebrow")
        titles.append(self.eyebrow_label)
        self.title_label = Gtk.Label(xalign=0.0)
        self.title_label.add_css_class("bp-page-title")
        self.title_label.set_ellipsize(Pango.EllipsizeMode.END)
        titles.append(self.title_label)
        heading.append(titles)
        self.count_label = Gtk.Label(xalign=1.0)
        self.count_label.add_css_class("bp-page-subtitle")
        self.count_label.set_valign(Gtk.Align.END)
        heading.append(self.count_label)
        left.append(heading)

        self.banners = TaskBanners(shell)
        left.append(self.banners)

        self.chips_scroller = Gtk.ScrolledWindow()
        self.chips_scroller.set_policy(Gtk.PolicyType.EXTERNAL, Gtk.PolicyType.NEVER)
        self.chips_scroller.set_propagate_natural_height(True)
        self.chips_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.chips_scroller.set_child(self.chips_box)
        left.append(self.chips_scroller)

        # In a scroller of its own, like the console chips: four chips with
        # their counts are wider than the column on a 1280 px screen, and a
        # row that cannot shrink pushes the whole window wider than itself.
        self.facets_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        for facet in library_facets.FACETS:
            chip = Chip(t(FACET_KEYS[facet]), on_activate=lambda facet=facet: self.toggle_facet(facet))
            chip.facet = facet
            self.facets_box.append(chip)
            self.facet_chips[facet] = chip
        self.facets_scroller = Gtk.ScrolledWindow()
        self.facets_scroller.set_policy(Gtk.PolicyType.EXTERNAL, Gtk.PolicyType.NEVER)
        self.facets_scroller.set_propagate_natural_height(True)
        self.facets_scroller.set_child(self.facets_box)
        left.append(self.facets_scroller)

        self.search_label = Gtk.Label(xalign=0.0)
        self.search_label.add_css_class("bp-pane-meta")
        self.search_label.set_visible(False)
        left.append(self.search_label)

        view_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.view_label = Gtk.Label(xalign=0.0)
        self.view_label.add_css_class("bp-section-title")
        self.view_label.set_hexpand(True)
        view_row.append(self.view_label)
        self.segments = Segments(
            [(view_id, icon, t(key)) for view_id, icon, key in VIEWS], self.set_view
        )
        view_row.append(self.segments)
        left.append(view_row)

        self.content_host = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.content_host.set_vexpand(True)
        left.append(self.content_host)
        self.body.append(left)

        self.pane = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.pane.add_css_class("bp-pane")
        self.pane_stack = Gtk.Stack()
        self.pane_stack.set_vexpand(True)
        self.pane_empty = empty_state("view-reveal-symbolic", t("big_picture.pane.empty"))
        self.pane_stack.add_named(self.pane_empty, "empty")
        self.detail = GameDetail(shell)
        self.detail.set_margin_start(28)
        self.detail.set_margin_end(28)
        self.detail.set_margin_top(12)
        self.detail.set_margin_bottom(12)
        self.pane_scroller = Gtk.ScrolledWindow()
        self.pane_scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.pane_scroller.set_child(self.detail)
        self.pane_stack.add_named(self.pane_scroller, "game")
        self.pane.append(self.pane_stack)
        self.body.append(self.pane)
        self.sync_view()

    # -- the desktop's content, borrowed ------------------------------------
    def attach_content(self):
        """Move the window's page stack under the chips."""
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
        self.clear_game()
        self.set_facets(frozenset())

    # -- the scope -------------------------------------------------------------------
    def chip_scopes(self):
        """The console chips, in the sidebar's order: everything but Recently played."""
        return [scope for scope in self.shell.library_scopes() if scope != RECENT_ID]

    def sync(self):
        """Rebuild the chips when the scopes changed; mark the current one; recount."""
        win = self.win
        ids = self.chip_scopes()
        if ids != self._chip_ids:
            child = self.chips_box.get_first_child()
            while child is not None:
                following = child.get_next_sibling()
                self.chips_box.remove(child)
                child = following
            self.console_chips = {}
            for scope_id in ids:
                chip = Chip(self._chip_label(scope_id),
                            on_activate=lambda scope_id=scope_id: self.select_scope(scope_id),
                            icon=self._chip_icon(scope_id))
                chip.scope_id = scope_id
                self.chips_box.append(chip)
                self.console_chips[scope_id] = chip
            self._chip_ids = ids
        scope = win.current_console
        for scope_id, chip in self.console_chips.items():
            chip.set_current(scope_id == scope)
        self._sync_heading()
        self._facts = None
        self.sync_facets()
        if self.active_facets and self._attached:
            # The grid's predicate holds the facts it was given: a star or a
            # state that changed since must reach the games, not only the counts.
            self.win.apply_library_filters()
        self.sync_search()
        self.sync_banners()

    def _chip_label(self, scope_id):
        from openemux.ui.bigpicture.shell import scope_kind

        t = self.win.t
        kind = scope_kind(scope_id)
        if kind == "all":
            return t("big_picture.games.all")
        if kind == "console":
            return short_name(scope_id)
        return self.win.sidebar.label_for(scope_id)

    def _chip_icon(self, scope_id):
        """The chip's icon (issue 962): the console's pixel art, as on the shelf.

        All, Favorites and the playlists take their glyphs (the sidebar's); a
        console with no art, its symbolic icon (the sidebar's fallback).
        """
        icon_name = scope_icon_name(scope_id)
        if icon_name is None:
            textures = [t for t in (console_texture(scope_id), console_texture_1x(scope_id)) if t is not None]
            if textures:
                return PixelIcon(textures)
            icon_name = get_icon_name(scope_id)
        image = Gtk.Image.new_from_icon_name(icon_name)
        image.add_css_class("bp-chip-glyph")
        return image

    def _sync_heading(self):
        from openemux.ui.bigpicture.shell import scope_kind

        win, t = self.win, self.win.t
        scope = win.current_console
        kind = scope_kind(scope)
        if kind == "all":
            eyebrow, title = t("big_picture.games.eyebrow.all"), t("big_picture.shelf.all_games")
        elif kind == "favorites":
            eyebrow, title = t("big_picture.games.eyebrow.favorites"), win.sidebar.label_for(scope)
        elif kind == "collection":
            eyebrow, title = t("big_picture.shelf.playlist"), win.sidebar.label_for(scope)
        else:
            eyebrow, title = short_name(scope), win.sidebar.label_for(scope)
        self.eyebrow_label.set_label(eyebrow.upper())
        self.title_label.set_label(title)
        count = self.shell.game_count(scope)
        self.count_label.set_label(
            t("header.subtitle.one_game") if count == 1 else t("header.subtitle.games", count=count)
        )
        self.set_title(title)

    def on_scope_changed(self, scope_id):
        """The window moved to another scope: the chips and the heading follow."""
        for chip_scope, chip in self.console_chips.items():
            chip.set_current(chip_scope == scope_id)
        chip = self.console_chips.get(scope_id)
        if chip is not None:
            GLib.idle_add(once(self._scroll_chip_into_view, chip))
        self._sync_heading()
        self._facts = None
        self.sync_facets()

    def _scroll_chip_into_view(self, chip):
        adjustment = self.chips_scroller.get_hadjustment()
        allocation = chip.get_allocation()
        if allocation.width <= 0:
            return
        page = adjustment.get_page_size()
        target = allocation.x + allocation.width / 2 - page / 2
        adjustment.set_value(max(0.0, min(target, adjustment.get_upper() - page)))

    def select_scope(self, scope_id):
        win = self.win
        if win.current_console != scope_id:
            win.sidebar.select(scope_id)
        return True

    def step_section(self, delta):
        """LB and RB: the chip before or after the current one, the focus kept."""
        ids = self.chip_scopes()
        if not ids:
            return False
        win = self.win
        index = ids.index(win.current_console) if win.current_console in ids else 0
        target = ids[(index + delta) % len(ids)]
        if target == win.current_console:
            return False
        focus = win.get_focus()
        in_grid = focus is not None and focus.is_ancestor(self.content_host)
        self.select_scope(target)
        if in_grid:
            GLib.idle_add(once(self.win.navigation._cmd_focus_grid))
        return True

    # -- the filter chips -------------------------------------------------------------
    def _scope_roms(self):
        grid = self.win.pages.grid_for(self.win.current_console)
        if grid is None:
            return []
        return [entry.rom for entry in grid.entries()]

    def _art_kind(self):
        return LABEL_ART if self.view_mode() == CARTRIDGE else COVER_ART

    def facts(self):
        """What the chips know about the scope's games, read once per scope."""
        win = self.win
        if self._facts is None or self._facts_scope != win.current_console:
            kind = self._art_kind()
            favorites = [rom.get("path") for rom in win.playlist_manager.load_favorites_playlist()]
            self._facts = library_facets.RomFacts(
                favorites,
                win.config_manager.get_console_states_dir,
                lambda rom: win._has_local_cover(rom, kind),
                win.play_history.last_played,
            )
            self._facts_scope = win.current_console
        return self._facts

    def sync_facets(self):
        """The chips' counts and marks, for the scope on screen."""
        t = self.win.t
        counts = library_facets.facet_counts(self._scope_roms(), self.facts())
        for facet, chip in self.facet_chips.items():
            chip.set_label(t("big_picture.facet.count", name=t(FACET_KEYS[facet]), count=counts[facet]))
            chip.set_on(facet in self.active_facets)

    def toggle_facet(self, facet):
        self.set_facets(library_facets.toggle(self.active_facets, facet))

    def set_facets(self, active):
        active = library_facets.normalize(active)
        if active == self.active_facets:
            return False
        self.active_facets = active
        self._facet_serial += 1
        for facet, chip in self.facet_chips.items():
            chip.set_on(facet in active)
        if self._attached:
            self.win.apply_library_filters()
        return True

    def facet_filter(self):
        """``(key, predicate)`` for the grid, or None with no chip on."""
        if not self.active_facets:
            return None
        active = self.active_facets
        facts = self.facts()
        key = (self.win.current_console, active, self._facet_serial, id(facts))
        return (key, lambda rom: library_facets.matches(rom, active, facts))

    def toggle_filters(self):
        """The filter button: the chips row in and out (the filters stay on)."""
        self.facets_scroller.set_visible(not self.facets_scroller.get_visible())

    # -- search --------------------------------------------------------------------------
    def sync_search(self):
        text = self.win.search_entry.get_text()
        if text:
            self.search_label.set_label(self.win.t("big_picture.games.searching", query=text))
        self.search_label.set_visible(bool(text))

    # -- the view ------------------------------------------------------------------------
    def view_mode(self):
        return self.win.config_manager.get_big_picture_settings()["view_mode"]

    def sync_view(self):
        mode = self.view_mode()
        self.segments.set_current(mode)
        self.view_label.set_label(self.win.t(VIEW_KEYS[mode]))

    def set_view(self, mode):
        """The switch: Big Picture's own view, the desktop's left as it was."""
        if mode == self.view_mode():
            return False
        self.win.config_manager.set_big_picture_view_mode(mode)
        self.sync_view()
        self._facts = None
        self.win._reload_current_page()
        self.sync_facets()
        return True

    # -- the detail pane -----------------------------------------------------------------
    def show_game(self, rom):
        """A on a game: its detail on the right, the focus on Play."""
        self.detail.load(rom)
        self.pane_stack.set_visible_child_name("game")
        self.pane_scroller.get_vadjustment().set_value(0)
        GLib.idle_add(once(self.detail.focus_default))
        return True

    def clear_game(self):
        self.detail.rom = None
        self.pane_stack.set_visible_child_name("empty")

    def forget_games(self, paths):
        if (self.detail.rom or {}).get("path") in paths:
            self.clear_game()
            GLib.idle_add(once(self.win.navigation._cmd_focus_grid))

    def pane_has_focus(self, focus=None):
        focus = focus if focus is not None else self.win.get_focus()
        return focus is not None and focus.is_ancestor(self.pane)

    def handle_back(self):
        """B in the pane goes back to the grid; anywhere else the page pops."""
        if self.pane_has_focus():
            self.win.navigation._cmd_focus_grid()
            return True
        return False

    def on_pad_action(self, action):
        if self.pane_has_focus():
            return self.detail.on_pad_action(action)
        return False

    def open_options(self, rom):
        """Y on a game: Android's options sheet."""
        self.detail.load(rom)
        self.pane_stack.set_visible_child_name("game")
        self.detail.open_options()
        return True

    # -- the shell's view of it -----------------------------------------------------------
    def context_for(self, focus):
        if self.pane_has_focus(focus):
            return "bp-pane"
        return self.context

    def sync_banners(self):
        self.banners.sync()

    def focus_above_grid(self):
        """Up from the games' top row: the view switch, the nearest control above.

        A grid view keeps the focus on its own top row, so without this the
        chips, the switch and the search above the games were out of the
        D-pad's reach (issue 957, QA round 1).
        """
        return self.segments.focus_current()

    def focus_default(self):
        grid = self.win.pages.grid_for(self.win.current_console)
        if grid is not None and grid.count() > 0:
            self.win.navigation._cmd_focus_grid()
            return True
        chip = self.console_chips.get(self.win.current_console)
        if chip is not None:
            return chip.grab_focus()
        return self.back_button.grab_focus()

    def hints(self, g, t):
        if self.pane_has_focus():
            return self.detail.hints(g, t)
        return [
            (g["confirm"], t("big_picture.hints.open")),
            (g["back"], t("big_picture.hints.shelf")),
            (g["consoles"], t("big_picture.hints.console")),
            (g["search"], t("hints.search")),
        ]

    def grid_hints(self, g, t):
        """The grid's, Android's: Details, Favorite, Options, Console, Select, Shelf."""
        return [
            (g["confirm"], t("big_picture.hints.details")),
            (g["context"], t("hints.favorite")),
            (g["favorite"], t("big_picture.hints.options")),
            (g["consoles"], t("big_picture.hints.console")),
            (g["select"], t("big_picture.hints.select")),
            (g["back"], t("big_picture.hints.shelf")),
        ]


__all__ = ["GamesPage", "VIEWS", "FACET_KEYS", "ALL_CONSOLES_ID", "FAVORITES_ID"]
