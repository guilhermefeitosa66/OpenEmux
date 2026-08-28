"""The content stack's pages, and the one place that knows what is on each.

A page per scope -- "All", "Favorites", each collection, each console -- with
its grid, whether it has been loaded yet, and the signature of what it was
last built from. A page switch that finds the same signature keeps the cards
it has, which is what keeps the scroll position (issue #230).

Four dictionaries keyed by the same scope id, updated from a dozen places in
`OpenEmuxWindow`. One of those places forgot `_grids` when deleting a
collection, so an orphaned grid went on receiving artwork refreshes for a
page nobody could reach -- exactly the class of bug that having one owner
removes rather than fixes (issue #237).
"""

import logging

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from openemux.ui.grid import LIST_MARGIN, RomGrid
from openemux.ui.scopes import (
    ALL_CONSOLES_ID,
    FAVORITES_ID,
    collection_scope,
    collection_slug,
    is_collection_scope,
)

logger = logging.getLogger(__name__)


class LibraryPages:
    """Owns the page, the grid and the load state of every scope.

    The four dictionaries are private and only move together: :meth:`add`,
    :meth:`forget` and :meth:`reset` are the only ways in, so a scope can
    never be half-removed.

    Reads from the window: ``content_stack``, ``config_manager``,
    ``playlist_manager``, ``collection_manager``, ``visible_consoles``,
    ``current_console``, ``locale``, ``roms_path``, ``t``, and the ROM-card
    callbacks a grid is built with.
    """

    def __init__(self, window):
        self.win = window
        #: scope id -> the Gtk.Box page in the content stack
        self._pages = {}
        #: scope id -> whether its ROMs have been read at least once
        self._loaded = {}
        #: scope id -> the RomGrid on it, when it has one (an empty scope
        #: shows a status page instead)
        self._grids = {}
        #: scope id -> what its cards were last built from; see _signature
        self._signatures = {}

    # ----- the registry ---------------------------------------------------
    def reset(self):
        """Forget every page. The caller empties the content stack itself."""
        self._pages = {}
        self._loaded = {}
        self._grids = {}
        self._signatures = {}

    def invalidate_contents(self):
        """Keep the pages, forget what is on them.

        A rescan that finds the same consoles has the right pages already;
        only their contents may have moved. Dropping the signatures is what
        makes the next visit re-read and re-render.
        """
        self._loaded = {}
        self._signatures = {}

    def forget(self, scope):
        """Drop everything about ``scope`` and return its page, if any.

        All four dictionaries, always. Popping three of them and leaving the
        grid behind is how a deleted collection's grid kept receiving artwork
        refreshes for a page that was no longer in the stack.
        """
        self._loaded.pop(scope, None)
        self._grids.pop(scope, None)
        self._signatures.pop(scope, None)
        return self._pages.pop(scope, None)

    def add(self, scope, title):
        """Build ``scope``'s page, register it and put it in the stack."""
        page = self.make_page()
        self._pages[scope] = page
        self._loaded[scope] = False
        self.win.content_stack.add_titled(page, scope, title)
        return page

    def has(self, scope):
        return scope in self._pages

    def page_for(self, scope):
        return self._pages.get(scope)

    def grid_for(self, scope):
        return self._grids.get(scope)

    def grids(self):
        return list(self._grids.values())

    def is_loaded(self, scope):
        return bool(self._loaded.get(scope))

    def mark_loaded(self, scope, loaded=True):
        self._loaded[scope] = loaded

    def any_page(self):
        return bool(self._pages)

    # ----- one page -------------------------------------------------------
    def make_page(self):
        """One content-stack page: a pinned list header above the scroll area.

        The header carries the master checkbox of list view (issue #78); it
        sits outside the ScrolledWindow so it never scrolls away, and stays
        hidden in the grid view modes.
        """
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        check = Gtk.CheckButton()
        check.set_tooltip_text(self.win.t("selection.master_checkbox"))
        label = Gtk.Label(label=self.win.t("selection.select_all"))
        label.add_css_class("dim-label")
        label.add_css_class("caption")
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        header.add_css_class("toolbar")
        header.set_margin_start(LIST_MARGIN)
        header.set_margin_end(LIST_MARGIN)
        header.append(check)
        header.append(label)
        header.set_visible(False)

        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        page.append(header)
        page.append(scroll)
        # Empty-space clicks and the rubber band are handled by the grid's
        # band gesture, which attaches itself to this scroller on map so it
        # covers the whole page, not just the card rows.

        # Stashed for render(); the guard breaks the feedback loop between
        # the master checkbox and the selection it reflects.
        page.scroll = scroll
        page.header = header
        page.master_check = check
        page.master_guard = [False]
        check.connect("toggled", lambda _c, p=page: self._on_master_check_toggled(p))
        return page

    def _on_master_check_toggled(self, page):
        if page.master_guard[0]:
            return
        grid = self.grid_for(self.win.current_console)
        if grid is None:
            return
        if page.master_check.get_active():
            grid.select_all()
        else:
            grid.clear_selection()

    def update_master_check(self):
        """Tri-state: none / some (indeterminate) / all visible selected."""
        scope = self.win.current_console
        page = self.page_for(scope)
        grid = self.grid_for(scope)
        if page is None or grid is None or not hasattr(page, "master_check"):
            return
        visible = grid.visible_entries()
        selected = sum(1 for entry in visible if entry.selected)
        page.master_guard[0] = True
        page.master_check.set_inconsistent(0 < selected < len(visible))
        page.master_check.set_active(bool(visible) and selected == len(visible))
        page.master_guard[0] = False

    # ----- loading --------------------------------------------------------
    def ensure_collection_page(self, slug):
        """Add the content-stack page for a collection if it has none yet."""
        scope = collection_scope(slug)
        if self.has(scope):
            return
        self.add(scope, self.win.sidebar.label_for(scope))

    def ensure_collection_loaded(self, slug):
        scope = collection_scope(slug)
        self.ensure_collection_page(slug)
        entries = self.win.collection_manager.load_entries(slug)
        self.render(scope, entries)
        self.mark_loaded(scope)

    def ensure_loaded(self, console, force_rescan=False):
        if console == ALL_CONSOLES_ID:
            self.ensure_all_loaded(force_rescan=force_rescan)
            return
        if console == FAVORITES_ID:
            self.ensure_favorites_loaded()
            return
        if is_collection_scope(console):
            self.ensure_collection_loaded(collection_slug(console))
            return
        if not self.has(console):
            return

        playlists = self.win.playlist_manager
        created_playlist = False
        if force_rescan:
            roms = playlists.scan_and_rebuild_playlist(console)
            created_playlist = True
        elif not self.is_loaded(console) and console in self.win._initial_roms:
            roms = self.win._initial_roms[console]
        else:
            if not playlists.playlist_exists(console):
                if self.win.config_manager.auto_scan_on_first_open():
                    created_playlist = True
                    roms = playlists.scan_and_rebuild_playlist(console)
                else:
                    roms = []
            else:
                roms = playlists.load_playlist(console)

        self.render(console, roms)
        self.mark_loaded(console)

        if created_playlist and roms and not self.win._cover_sync_running:
            self.win._start_cover_sync(scope="console", selected_console=console)

    def ensure_favorites_loaded(self):
        if not self.has(FAVORITES_ID):
            return
        playlists = self.win.playlist_manager
        playlists.remove_missing_favorites()
        self.render(FAVORITES_ID, playlists.load_favorites_playlist())
        self.mark_loaded(FAVORITES_ID)

    def ensure_all_loaded(self, force_rescan=False):
        if not self.has(ALL_CONSOLES_ID):
            return

        playlists = self.win.playlist_manager
        all_roms = []
        for console in self.win.visible_consoles:
            if force_rescan:
                roms = playlists.scan_and_rebuild_playlist(console)
                self.mark_loaded(console)
            elif not self.is_loaded(console) and console in self.win._initial_roms:
                roms = self.win._initial_roms[console]
            else:
                roms = playlists.load_playlist(console)
            all_roms.extend(roms)

        # Ordering is render()'s job now: it applies whichever sort order the
        # user picked, to every page alike.
        self.render(ALL_CONSOLES_ID, all_roms)
        self.mark_loaded(ALL_CONSOLES_ID)

    # ----- rendering ------------------------------------------------------
    def _signature(self, roms, display_settings):
        """Everything a rebuilt page would be built from.

        Two renders with the same signature produce the same widgets, so the
        second one is pure cost: a page switch used to tear down every card
        and build it again, losing the scroll position on the way (#230).
        Artwork, favourite stars and cartridge colours are refreshed on the
        card itself and are deliberately not in here.
        """
        return (
            tuple(rom.get("path", "") for rom in roms),
            tuple(rom.get("name", "") for rom in roms),
            display_settings["sort_order"],
            display_settings["view_mode"],
            display_settings.get("zoom"),
            self.win.locale,
        )

    def render(self, console, roms):
        win = self.win
        page = self._pages[console]
        scroll = page.scroll
        # Each page follows its own scope's layout, not the one on screen now.
        display_settings = win.config_manager.get_display_settings(console)
        roms = win._sorted_roms(roms, order=display_settings["sort_order"])
        signature = self._signature(roms, display_settings)
        if (
            self._signatures.get(console) == signature
            and scroll.get_child() is not None
        ):
            # Nothing about this page changed, so the cards it already has are
            # the cards it would be given. Keeping them keeps the scroll
            # position too -- the rebuild used to send every page switch back
            # to the top.
            grid = self.grid_for(console)
            if grid is not None:
                win._apply_filters_to(grid)
            if console == win.current_console:
                win._update_window_title(console)
            return
        self._signatures[console] = signature
        page.header.set_visible(False)
        if not roms:
            scroll.set_child(self._empty_page_for(console))
            self._grids.pop(console, None)
            if console == win.current_console:
                win._update_window_title(console)
            return

        grid = RomGrid(
            console,
            roms,
            win.on_launch_game,
            win._toggle_favorite_from_ui,
            win._reveal_rom_in_files,
            win._choose_cover_for_rom,
            win._remove_cover_for_rom,
            win._is_favorite_rom,
            win._has_local_cover,
            win.t,
            win.roms_path,
            ui_settings=display_settings,
            mixed_consoles=console in (ALL_CONSOLES_ID, FAVORITES_ID)
            or is_collection_scope(console),
            on_rename_rom=win._rename_rom_from_ui,
            on_delete_rom=win._confirm_delete_roms,
            on_selection_changed=win._on_selection_changed,
            context_services=win._rom_context_services,
            frame_color_for_rom=win._cartridge_color_for_rom,
        )
        self._grids[console] = grid
        # The page was rebuilt, so whatever was selected on it is gone; the
        # gamepad selection mode goes with it.
        win._on_selection_changed([])
        win.leave_selection_mode(clear=False)
        # The pinned master-checkbox header belongs to list view only.
        page.header.set_visible(grid.compact)
        scroll.set_child(grid)
        if console == win.current_console:
            win._update_window_title(console)

    def _empty_page_for(self, console):
        t = self.win.t
        if console == FAVORITES_ID:
            return Adw.StatusPage(
                icon_name="starred-symbolic",
                title=t("favorites.empty.title"),
                description=t("favorites.empty.body"),
            )
        if console == ALL_CONSOLES_ID:
            return Adw.StatusPage(
                icon_name="folder-open-symbolic",
                title=t("console.empty.title"),
                description=t("empty.all_indexed"),
            )
        if is_collection_scope(console):
            return Adw.StatusPage(
                icon_name="user-bookmarks-symbolic",
                title=t("collections.empty.title"),
                description=t("collections.empty.body"),
            )
        return Adw.StatusPage(
            icon_name="applications-games-symbolic",
            title=t("console.empty.title"),
            description=str(self.win.playlist_manager.get_playlist_path(console)),
        )
