"""The Big Picture shell: the rail, the pages, the hint bar, the way in and out.

One widget the window swaps in for its desktop layout while the mode is on.
It follows the Android app's gamepad layout (issue 957): a navigation rail
down the left (Library, Recent, Import, Settings), and beside it a
navigation stack whose root is the tab's first page -- the Shelf, the
recently played games, Import, Settings -- with the games of a console, a
game expanded, the choosers and the keyboard pushed over it. The hint bar
runs under the pages; the search keyboard slides up over them.

The desktop layout is never torn down: the window's page stack is borrowed
by the games page for the duration and handed back on the way out, so
leaving the mode lands on exactly the desktop that was there.
"""

import logging

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk

from openemux.ui.bigpicture import theme
from openemux.ui.bigpicture.osk import MODE_SEARCH, OnScreenKeyboard
from openemux.ui.bigpicture.rail import (
    TAB_IDS,
    TAB_IMPORT,
    TAB_LIBRARY,
    TAB_RECENT,
    TAB_SETTINGS,
    NavRail,
)
from openemux.ui.bigpicture.widgets import HintBar, once
from openemux.ui.scopes import ALL_CONSOLES_ID, FAVORITES_ID, RECENT_ID, collection_slug, is_collection_scope

logger = logging.getLogger(__name__)

#: Navigation contexts the shell reports to the navigator, by where the
#: focus is. The grid and the dialogs are the navigator's own contexts.
CTX_SHELF = "bp-shelf"
CTX_GAMES = "bp-games"
CTX_PANE = "bp-pane"
CTX_RAIL = "bp-rail"
CTX_OSK = "bp-osk"
CTX_PAGE = "bp-page"


def scope_kind(scope_id):
    """What a library scope is: all, favorites, recent, a playlist, a console."""
    if scope_id == ALL_CONSOLES_ID:
        return "all"
    if scope_id == FAVORITES_ID:
        return "favorites"
    if scope_id == RECENT_ID:
        return "recent"
    if is_collection_scope(scope_id):
        return "collection"
    return "console"


class BigPictureShell(Gtk.Box):
    def __init__(self, win):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL)
        self.win = win
        self.t = win.t
        self.add_css_class("bp-shell")
        self.set_vexpand(True)
        self._clocks = []
        self._provider = None
        self._clock_source = 0
        self._scale = None
        self._active = False
        self._pushed = set()
        self._color_scheme = None
        self.tab = TAB_LIBRARY

        self.rail = NavRail(self.t, self.switch_tab)
        self.append(self.rail)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        content.add_css_class("bp-content")
        content.set_hexpand(True)
        self.nav = Adw.NavigationView()
        self.nav.set_vexpand(True)
        self.nav.connect("popped", self._on_popped)
        # The slide between pages follows the desktop's animation setting,
        # as the card transitions do (issue 915).
        settings = Gtk.Settings.get_default()
        if settings is not None:
            settings.connect("notify::gtk-enable-animations", self._sync_animations)
        self._sync_animations()

        # The search keyboard, over whichever page is showing.
        self.overlay = Gtk.Overlay()
        self.overlay.set_vexpand(True)
        self.overlay.set_child(self.nav)
        self.osk_revealer = Gtk.Revealer()
        self.osk_revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_UP)
        self.osk_revealer.set_valign(Gtk.Align.END)
        self.osk_revealer.set_reveal_child(False)
        self.osk = OnScreenKeyboard(
            self.t, MODE_SEARCH, on_change=self._on_search_typed, on_done=self._on_search_done
        )
        sheet = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        sheet.add_css_class("bp-sheet")
        sheet.append(self.osk)
        typing = Gtk.EventControllerKey()
        typing.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        typing.connect("key-pressed", self._on_sheet_key)
        sheet.add_controller(typing)
        self.osk_revealer.set_child(sheet)
        self.overlay.add_overlay(self.osk_revealer)
        content.append(self.overlay)
        self.hint_bar = HintBar()
        content.append(self.hint_bar)
        self.append(content)

        from openemux.ui.bigpicture.games import GamesPage
        from openemux.ui.bigpicture.shelf import ShelfPage

        from openemux.ui.bigpicture.splash import LaunchSplash

        self.shelf = ShelfPage(self)
        self.library = GamesPage(self)
        #: The launch splash; the window puts it in its mode stack.
        self.splash = LaunchSplash(self)
        self.nav.add(self.shelf)
        self._watch_page(self.shelf)
        self._watch_page(self.library)
        self._roots = {TAB_LIBRARY: self.shelf}
        self._details = None
        self._settings = None
        self._import = None
        self._recent = None
        self._covers = None
        self._chooser = None
        self._text_entry = None
        self._browser = None

        banner = win.banner
        banner.connect("notify::title", lambda *_: self.sync_status())
        banner.connect("notify::revealed", lambda *_: self.sync_status())
        win.connect("notify::default-height", lambda *_: self.apply_scale())
        win.connect("notify::fullscreened", lambda *_: GLib.idle_add(self._apply_scale_idle))

    def _sync_animations(self, *_args):
        settings = Gtk.Settings.get_default()
        animate = bool(settings.get_property("gtk-enable-animations")) if settings is not None else True
        self.nav.set_animate_transitions(animate)

    # -- in and out --------------------------------------------------------------
    @property
    def active(self):
        return self._active

    def enter(self):
        """The mode just turned on: dark, sized up, the games borrowed, the Shelf."""
        self._active = True
        self._force_dark(True)
        self.apply_scale()
        self.library.attach_content()
        self.shelf.refresh()
        self.sync_status()
        self._start_clock()
        self.switch_tab(TAB_LIBRARY, focus=False)
        GLib.idle_add(self._focus_visible)

    def leave(self):
        """The mode is ending: give the pages back, the theme back, stop the clock."""
        self._active = False
        self._stop_clock()
        self.splash.close()
        self.hide_search()
        self.switch_tab(TAB_LIBRARY, focus=False)
        self.library.detach_content()
        self.hint_bar.set_hints([])
        self._force_dark(False)

    def adopt_color_scheme(self):
        """The desktop theme just changed from inside Big Picture.

        The new scheme is the one to give back on the way out, and Big
        Picture stays dark meanwhile.
        """
        self._color_scheme = None
        self._force_dark(True)

    def _force_dark(self, on):
        """Big Picture is always dark, as Android's gamepad layout is (issue 957).

        The desktop's own choice is put back on the way out.
        """
        style = Adw.StyleManager.get_default()
        if on:
            if self._color_scheme is None:
                self._color_scheme = style.get_color_scheme()
            style.set_color_scheme(Adw.ColorScheme.FORCE_DARK)
        elif self._color_scheme is not None:
            style.set_color_scheme(self._color_scheme)
            self._color_scheme = None

    # -- scale --------------------------------------------------------------------
    def scale(self):
        height = self.win.get_height() or 0
        if height <= 0:
            surface = self.win.get_surface()
            monitor = self.win.get_display().get_monitor_at_surface(surface) if surface else None
            if monitor is not None:
                height = monitor.get_geometry().height
        text_size = self.win.config_manager.get_big_picture_settings()["text_size"]
        return theme.scale_for(height, text_size)

    def apply_scale(self):
        """Regenerate the stylesheet for the window's height and text size."""
        scale = self.scale()
        if scale == self._scale:
            return scale
        self._scale = scale
        display = Gdk.Display.get_default()
        provider = Gtk.CssProvider()
        provider.load_from_string(theme.stylesheet(scale))
        if self._provider is not None and display is not None:
            Gtk.StyleContext.remove_provider_for_display(display, self._provider)
        if display is not None:
            Gtk.StyleContext.add_provider_for_display(
                display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1
            )
        self._provider = provider
        logger.info("big picture scale: %.3f", scale)
        return scale

    def _apply_scale_idle(self):
        self.apply_scale()
        return GLib.SOURCE_REMOVE

    def release(self):
        """Drop the stylesheet from the display (the window is going away)."""
        display = Gdk.Display.get_default()
        if self._provider is not None and display is not None:
            Gtk.StyleContext.remove_provider_for_display(display, self._provider)
        self._provider = None
        self._scale = None
        self._stop_clock()

    # -- the clock -------------------------------------------------------------------
    def make_status_box(self):
        """The corner every page shows: the clock (maintainer decision 1)."""
        clock = Gtk.Label()
        clock.add_css_class("bp-clock")
        clock.set_halign(Gtk.Align.END)
        clock.set_valign(Gtk.Align.CENTER)
        self._clocks.append(clock)
        self._sync_clock(clock)
        return clock

    @staticmethod
    def _sync_clock(clock):
        clock.set_label(GLib.DateTime.new_now_local().format("%H:%M"))

    def sync_status(self):
        """The clock, and the task banners the library pages show (issue 957)."""
        for clock in self._clocks:
            self._sync_clock(clock)
        for page in (self.shelf, self.library):
            page.sync_banners()

    def _start_clock(self):
        if not self._clock_source:
            self._clock_source = GLib.timeout_add_seconds(30, self._on_clock)

    def _stop_clock(self):
        if self._clock_source:
            GLib.source_remove(self._clock_source)
            self._clock_source = 0

    def _on_clock(self):
        self.sync_status()
        return GLib.SOURCE_CONTINUE

    # -- the library ----------------------------------------------------------------
    def library_scopes(self):
        """The scopes the sidebar lists, in its order."""
        ids = []
        row = self.win.console_list.get_first_child()
        while row is not None:
            scope_id = getattr(row, "id", None)
            if scope_id is not None:
                ids.append(scope_id)
            row = row.get_next_sibling()
        return ids

    def game_count(self, scope_id):
        """How many games a scope holds."""
        win = self.win
        kind = scope_kind(scope_id)
        if kind == "console":
            roms = win._initial_roms.get(scope_id)
            if roms is None:
                roms = win.playlist_manager.load_playlist(scope_id)
            return len(roms)
        if kind == "all":
            return sum(self.game_count(console) for console in win.visible_consoles)
        if kind == "recent":
            return len(win.play_history.recent())
        if kind == "favorites":
            return len(win.playlist_manager.load_favorites_playlist())
        return len(win.collection_manager.paths(collection_slug(scope_id)))

    def on_library_changed(self):
        """The window rebuilt its library: the shelf, the chips and the recent list follow."""
        if not self._active:
            return
        self.library.sync()
        self.shelf.refresh()
        if self._recent is not None:
            self._recent.refresh()
        # A game that just ended has new states and a new "played" line.
        self.library.detail.refresh()
        if self._details is not None:
            self._details.detail.refresh()

    def on_scope_changed(self, scope_id):
        """The window moved to another page (the sidebar, a shoulder)."""
        if self._active:
            self.library.on_scope_changed(scope_id)

    def open_library(self, scope_id=None):
        """A shelf card: the games of ``scope_id``, over the Shelf."""
        win = self.win
        if self.tab != TAB_LIBRARY:
            self.switch_tab(TAB_LIBRARY, focus=False)
        if scope_id is not None and win.current_console != scope_id:
            win.sidebar.select(scope_id)
        self.library.sync()
        self.push(self.library)
        return True

    def facet_filter(self):
        """The games page's filter chips, as the window's grid filter wants them."""
        if not self._active:
            return None
        return self.library.facet_filter()

    def show_game(self, rom):
        """A game activated in the grid: its detail pane (Android's A)."""
        logger.info("big picture: show %s", rom.get("name", ""))
        if self.visible_page() is self.library:
            self.library.show_game(rom)
            return True
        return self.open_details(rom)

    def forget_games(self, paths):
        """Games just removed: whatever shows one of them lets it go."""
        self.library.forget_games(paths)
        if self._details is not None and (self._details.rom or {}).get("path") in paths:
            if self.visible_page() is self._details:
                self.pop()

    # -- tabs ----------------------------------------------------------------------------
    def _root_for(self, tab):
        if tab not in self._roots:
            if tab == TAB_RECENT:
                from openemux.ui.bigpicture.recent import RecentPage

                self._recent = RecentPage(self)
                self._roots[tab] = self._recent
            elif tab == TAB_IMPORT:
                from openemux.ui.bigpicture.import_page import ImportPage

                self._import = ImportPage(self)
                self._roots[tab] = self._import
            else:
                from openemux.ui.bigpicture.settings import SettingsPage

                self._settings = SettingsPage(self)
                self._roots[tab] = self._settings
            self._watch_page(self._roots[tab])
            self.nav.add(self._roots[tab])
        return self._roots[tab]

    def switch_tab(self, tab, focus=True):
        """Show a tab's first page; the pages pushed over the last one go."""
        if tab not in TAB_IDS:
            return False
        root = self._root_for(tab)
        self.tab = tab
        self.rail.mark(tab)
        self.hide_search()
        refresh = getattr(root, "refresh", None)
        if refresh is not None:
            refresh()
        if self.nav.get_navigation_stack().get_n_items() != 1 or self.visible_page() is not root:
            self.nav.replace([root])
        self._pushed.clear()
        if focus:
            GLib.idle_add(self._focus_visible)
        return True

    def step_tab(self, delta):
        """LB and RB on a tab's first page: the tab above or below."""
        return self.switch_tab(self.rail.neighbour(delta))

    def is_root(self, page=None):
        page = page or self.visible_page()
        return page is not None and page is self._roots.get(self.tab)

    # -- the stack ---------------------------------------------------------------------
    def visible_page(self):
        return self.nav.get_visible_page()

    def push(self, page):
        if self.visible_page() is page:
            GLib.idle_add(self._focus_visible)
            return
        self._watch_page(page)
        if page in self._pushed:
            self.nav.pop_to_page(page)
        else:
            self._pushed.add(page)
            self.nav.push(page)
        GLib.idle_add(self._focus_visible)

    def _watch_page(self, page):
        """Land the focus again once a page's transition ends.

        The navigation view moves the focus to the page's first focusable
        when the slide is over, after the idle that put it where the page
        wanted. The page's own ``on_shown`` is the last word.
        """
        if getattr(page, "_bp_watched", False):
            return
        page._bp_watched = True
        page.connect("shown", self._on_page_shown)

    def _on_page_shown(self, page):
        if self._active and self.visible_page() is page:
            if self.search_open:
                # Search opened on the way here (View on the Shelf): the
                # keyboard keeps the focus, or the page's own default takes
                # it back from under the keyboard (issue 957, QA round 1).
                self.osk.focus_first_key()
            else:
                page.on_shown()
            self.win.navigation.refresh_hints(force=True)

    def pop(self):
        if self.is_root():
            return False
        return bool(self.nav.pop())

    def _on_popped(self, _nav, page):
        self._pushed.discard(page)
        if self.visible_page() is self.shelf:
            self.shelf.refresh()
        GLib.idle_add(self._focus_visible)

    def _focus_visible(self):
        page = self.visible_page()
        if self.search_open:
            self.osk.focus_first_key()
        elif page is not None and self._active:
            # Mid-transition a page cannot take the focus yet: the page's
            # ``shown`` (_on_page_shown) is the last word, so a miss here is
            # not retried -- a timed retry stole the focus from the user.
            page.focus_default()
        self.win.navigation.refresh_hints(force=True)
        return GLib.SOURCE_REMOVE

    def go_home(self):
        self.switch_tab(TAB_LIBRARY)

    def handle_back(self):
        """B, or Escape: the splash, the keyboard, the page's own back, the page, the Library tab."""
        if self.splash.shown:
            self.splash.close()
            return True
        if self.search_open:
            self.hide_search()
            return True
        page = self.visible_page()
        back = getattr(page, "handle_back", None)
        if back is not None and back():
            return True
        if self.pop():
            return True
        if self.tab != TAB_LIBRARY:
            # Android: B on another tab's first page goes back to the Library.
            return self.switch_tab(TAB_LIBRARY)
        return False

    def step_console(self, delta):
        """LB and RB: the page's own sections, else the tabs.

        The games page walks its console chips; a game expanded walks the
        games beside it (``step_section(delta)``); a tab's first page walks
        the tabs.
        """
        page = self.visible_page()
        step = getattr(page, "step_section", None)
        if step is not None and step(delta):
            return True
        if self.is_root(page):
            return self.step_tab(delta)
        return False

    # -- search ------------------------------------------------------------------------
    @property
    def search_open(self):
        return self.osk_revealer.get_reveal_child()

    def open_search(self):
        """View (or Ctrl+F): the keyboard, over the games.

        From anywhere but a games page, Android's "Search all consoles":
        All games opens, and the keyboard over it.
        """
        win = self.win
        if not win.search_entry.get_sensitive():
            return False
        if self.search_open:
            self.hide_search()
            return False
        if self.visible_page() is not self.library:
            self.open_library(ALL_CONSOLES_ID)
            GLib.idle_add(once(self.show_search))
            return True
        return self.show_search()

    def show_search(self):
        win = self.win
        if not win.search_button.get_active():
            win.search_button.set_active(True)
        self.osk.set_text(win.search_entry.get_text())
        self.osk_revealer.set_reveal_child(True)
        GLib.idle_add(once(self.osk.focus_first_key))
        self.win.navigation.refresh_hints(force=True)
        return True

    def hide_search(self):
        if not self.search_open:
            return
        self.osk_revealer.set_reveal_child(False)
        win = self.win
        if not win.search_entry.get_text():
            win.search_button.set_active(False)
        GLib.idle_add(once(self._focus_visible))

    def _on_search_typed(self, text):
        win = self.win
        if not win.search_button.get_active():
            win.search_button.set_active(True)
        win.search_entry.set_text(text)
        self.library.sync_search()

    def _on_search_done(self, _text):
        self.hide_search()

    def _on_sheet_key(self, _controller, keyval, _keycode, state):
        """A real keyboard types into the search too, while the keyboard shows."""
        if state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.ALT_MASK):
            return False
        if keyval == Gdk.KEY_BackSpace:
            self.osk.backspace()
            return True
        code = Gdk.keyval_to_unicode(keyval)
        char = chr(code) if code else ""
        if not char.isprintable() or not char:
            return False
        self.osk.type_char(char.upper())
        return True

    # -- contexts and hints -----------------------------------------------------------------
    def context_for(self, focus):
        """Where the focus is, for the navigator: the keyboard, the rail, the page's part."""
        if self.splash.shown:
            return CTX_PAGE
        if focus is not None:
            if focus.is_ancestor(self.osk):
                return CTX_OSK
            if focus.is_ancestor(self.rail):
                return CTX_RAIL
        page = self.visible_page()
        part = getattr(page, "context_for", None)
        if part is not None:
            return part(focus)
        return getattr(page, "context", CTX_PAGE)

    def set_hints(self, pairs):
        glyphs = self.win.navigation.glyphs()
        self.hint_bar.set_hints(pairs, confirm_glyph=glyphs.get("confirm"))

    def hints_for(self, context, glyphs):
        """The hint pairs for a shell context, by the page that owns it."""
        t = self.t
        if self.splash.shown:
            return self.splash.hints(glyphs, t)
        if context == CTX_OSK:
            return [
                (glyphs["confirm"], t("big_picture.hints.type")),
                (glyphs["context"], t("big_picture.hints.backspace")),
                (glyphs["favorite"], t("big_picture.hints.space")),
                (glyphs["start"], t("big_picture.hints.done")),
                (glyphs["back"], t("big_picture.hints.close_search")),
            ]
        if context == CTX_RAIL:
            return [
                (glyphs["confirm"], t("big_picture.hints.open")),
                (glyphs["consoles"], t("big_picture.hints.tabs")),
            ]
        page = self.visible_page()
        if page is not None:
            return page.hints(glyphs, t)
        return []

    # -- the pages ------------------------------------------------------------------------
    def open_details(self, rom):
        from openemux.ui.bigpicture.details import GameDetailsPage

        if self._details is None:
            self._details = GameDetailsPage(self)
        self._details.load(rom)
        self.push(self._details)
        return self._details

    def open_settings(self, section=None, console=None):
        settings = self._root_for(TAB_SETTINGS)
        self.switch_tab(TAB_SETTINGS, focus=section is None)
        if section is not None:
            settings.show_section(section, console=console)
        return settings

    def open_import(self):
        self.switch_tab(TAB_IMPORT)
        return self._root_for(TAB_IMPORT)

    def open_recent(self):
        self.switch_tab(TAB_RECENT)
        return self._root_for(TAB_RECENT)

    def open_covers(self):
        from openemux.ui.bigpicture.tasks import CoversPage

        if self._covers is None:
            self._covers = CoversPage(self)
        self._covers.refresh()
        self.push(self._covers)
        return self._covers

    def open_browser(self, mode, on_pick):
        """The pad file browser: ``mode`` is "files" or "folder"."""
        from openemux.ui.bigpicture.file_browser import FileBrowserPage

        if self._browser is None:
            self._browser = FileBrowserPage(self)
        self._browser.open(mode, on_pick)
        self.push(self._browser)
        return self._browser

    def run_task_action(self):
        """A task banner's A: stop what runs (the quick menu's Stop, moved here)."""
        task = self.win.tasks.current_task()
        if task is None:
            return False
        self.confirm(
            task.get("label") or "",
            None,
            self.t("big_picture.banner.stop"),
            lambda: self.win.tasks.cancel(task["id"]),
        )
        return True

    # -- the pieces every page borrows ---------------------------------------
    def open_chooser(self, title, options, current, on_pick, crumbs=None, lead=None):
        """A full-page list to pick one option from.

        ``options`` are ``{"id", "label", "subtitle"?}`` dicts; A on one
        calls ``on_pick(id)`` and pops the page, B keeps ``current``.
        """
        from openemux.ui.bigpicture.chooser import ChooserPage

        if self._chooser is None:
            self._chooser = ChooserPage(self)
        self._chooser.open(title, options, current, on_pick, crumbs=crumbs, lead=lead)
        self.push(self._chooser)
        return self._chooser

    def open_text_entry(self, title, initial, on_done, subtitle=None, password=False,
                        max_length=64, crumbs=None):
        """The on-screen keyboard over a settings value; Done hands it to ``on_done``."""
        from openemux.ui.bigpicture.chooser import TextEntryPage

        if self._text_entry is None:
            self._text_entry = TextEntryPage(self)
        self._text_entry.open(
            title, initial, on_done, subtitle=subtitle, password=password,
            max_length=max_length, crumbs=crumbs,
        )
        self.push(self._text_entry)
        return self._text_entry

    def confirm(self, heading, body, confirm_label, on_confirm, destructive=True,
                cancel_label=None):
        """A yes/no question, the safe answer focused, B as Cancel."""
        t = self.t
        dialog = Adw.AlertDialog(heading=heading, body=body or "")
        dialog.add_css_class("bp-dialog")
        dialog.add_response("cancel", cancel_label or t("dialog.cancel"))
        dialog.add_response("confirm", confirm_label)
        dialog.set_response_appearance(
            "confirm",
            Adw.ResponseAppearance.DESTRUCTIVE if destructive else Adw.ResponseAppearance.SUGGESTED,
        )
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect("response", lambda _d, response: on_confirm() if response == "confirm" else None)
        dialog.present(self.win)
        return dialog

    def open_share(self, roms=None):
        """Share ``roms``, or what is selected; with nothing, receive."""
        win = self.win
        roms = list(roms or getattr(win, "_selected_roms", []) or [])
        if not roms:
            win.receive_games()
            return True
        win.share_roms(roms)
        return True


__all__ = [
    "BigPictureShell", "CTX_SHELF", "CTX_GAMES", "CTX_PANE", "CTX_RAIL", "CTX_OSK", "CTX_PAGE",
    "TAB_LIBRARY", "TAB_RECENT", "TAB_IMPORT", "TAB_SETTINGS", "scope_kind",
]
