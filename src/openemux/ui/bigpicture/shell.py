"""The Big Picture shell: the pages, the hint bar, the way in and out.

One widget the window swaps in for its desktop layout while the mode is
on. It owns a navigation stack of Big Picture pages (home at the root, the
library, a game's details, Settings, the tasks), the hint bar under them,
the status every page shows in its corner (the pad, the task running, the
clock) and the generated stylesheet that sizes it all for the window.

The desktop layout is never torn down: the window's page stack is borrowed
by the library page for the duration and handed back on the way out, so
leaving the mode lands on exactly the desktop that was there.
"""

import logging

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk, Pango

from openemux.ui import theming
from openemux.ui.bigpicture import theme
from openemux.ui.bigpicture.home import HomePage, scope_kind
from openemux.ui.bigpicture.library import LibraryPage
from openemux.ui.bigpicture.widgets import HintBar
from openemux.ui.scopes import ALL_CONSOLES_ID, FAVORITES_ID, RECENT_ID, collection_slug

logger = logging.getLogger(__name__)

#: Navigation contexts the shell reports to the navigator, by where the
#: focus is. The grid and the dialogs are the navigator's own contexts.
CTX_HOME = "bp-home"
CTX_LIBRARY = "bp-library"
CTX_RAIL = "bp-rail"
CTX_OSK = "bp-osk"
CTX_PAGE = "bp-page"

# The focus after a push is placed twice: once on the idle right after it,
# once more when the page's transition ends (``_on_page_shown``).

#: The quick menu's and the home row's action ids.
QUICK_ACTIONS = (
    "search", "import", "covers", "share", "receive", "rescan", "settings", "desktop", "quit", "stop",
)


class BigPictureShell(Gtk.Box):
    def __init__(self, win):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.win = win
        self.t = win.t
        self.add_css_class("bp-shell")
        self.set_vexpand(True)
        self._status_boxes = []
        self._provider = None
        self._clock_source = 0
        self._scale = None
        self._active = False
        self._pushed = set()

        self.nav = Adw.NavigationView()
        self.nav.set_vexpand(True)
        self.nav.connect("popped", self._on_popped)
        # The slide between pages follows the desktop's animation setting,
        # as the card transitions do (issue 915).
        settings = Gtk.Settings.get_default()
        if settings is not None:
            settings.connect("notify::gtk-enable-animations", self._sync_animations)
        self._sync_animations()
        self.append(self.nav)
        self.hint_bar = HintBar()
        self.append(self.hint_bar)

        self.home = HomePage(self)
        self.library = LibraryPage(self)
        self.nav.add(self.home)
        self._watch_page(self.home)
        self._watch_page(self.library)
        self._details = None
        self._settings = None
        self._import = None
        self._covers = None
        self._chooser = None
        self._text_entry = None

        banner = win.banner
        banner.connect("notify::title", lambda *_: self.sync_status())
        banner.connect("notify::revealed", lambda *_: self.sync_status())
        style = Adw.StyleManager.get_default()
        style.connect("notify::dark", lambda *_: self.apply_scale())
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
        """The mode just turned on: borrow the pages, size up, land on home."""
        self._active = True
        self.apply_scale()
        self.library.attach_content()
        self.library.sync()
        self.home.refresh()
        self.sync_status()
        self._start_clock()
        self.nav.pop_to_page(self.home)
        GLib.idle_add(self._focus_visible)

    def leave(self):
        """The mode is ending: give the pages back, stop the clock."""
        self._active = False
        self._stop_clock()
        self.nav.pop_to_page(self.home)
        self.library.detach_content()
        self.hint_bar.set_hints([])

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
        dark = theming.is_dark()
        if (scale, dark) == self._scale:
            return scale
        self._scale = (scale, dark)
        display = Gdk.Display.get_default()
        provider = Gtk.CssProvider()
        provider.load_from_string(theme.stylesheet(scale, dark))
        if self._provider is not None and display is not None:
            Gtk.StyleContext.remove_provider_for_display(display, self._provider)
        if display is not None:
            Gtk.StyleContext.add_provider_for_display(
                display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1
            )
        self._provider = provider
        logger.info("big picture scale: %.3f (%s)", scale, "dark" if dark else "light")
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

    # -- status ---------------------------------------------------------------------
    def make_status_box(self):
        """The corner every page shows: the pad, the task running, the clock."""
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=20)
        box.set_halign(Gtk.Align.END)
        box.set_valign(Gtk.Align.CENTER)
        pad = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        pad.add_css_class("bp-chip")
        pad.append(Gtk.Image.new_from_icon_name("input-gaming-symbolic"))
        pad_label = Gtk.Label()
        pad_label.set_ellipsize(Pango.EllipsizeMode.END)
        pad_label.set_max_width_chars(28)
        pad.append(pad_label)
        box.append(pad)
        task = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        task.add_css_class("bp-chip")
        task.append(Gtk.Spinner(spinning=True))
        task_label = Gtk.Label()
        task_label.set_ellipsize(Pango.EllipsizeMode.END)
        task_label.set_max_width_chars(40)
        task.append(task_label)
        task.set_visible(False)
        box.append(task)
        clock = Gtk.Label()
        clock.add_css_class("bp-clock")
        box.append(clock)
        self._status_boxes.append((pad, pad_label, task, task_label, clock))
        self._sync_status_box(self._status_boxes[-1])
        return box

    def sync_status(self):
        for entry in self._status_boxes:
            self._sync_status_box(entry)

    def _sync_status_box(self, entry):
        pad, pad_label, task, task_label, clock = entry
        navigation = self.win.navigation
        if getattr(navigation, "gamepad_connected", False):
            pad_label.set_label(getattr(navigation, "gamepad_name", "") or self.t("big_picture.status.pad"))
            pad.set_visible(True)
        else:
            pad.set_visible(False)
        banner = self.win.banner
        if banner.get_revealed() and banner.get_title():
            task_label.set_label(banner.get_title())
            task.set_visible(True)
        else:
            task.set_visible(False)
        clock.set_label(GLib.DateTime.new_now_local().format("%H:%M"))

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
        """How many games a scope holds, or None when that is not cheap to know."""
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
        """The window rebuilt its library: the rail and the home rows follow."""
        if not self._active:
            return
        self.library.sync()
        self.home.refresh()

    def on_scope_changed(self, scope_id):
        """The window moved to another page (the sidebar, a shoulder)."""
        if self._active:
            self.library.rail.mark_current(scope_id)
            self.library.set_crumbs(
                [self.t("big_picture.home.library"), self.win.sidebar.label_for(scope_id)]
            )

    def open_library(self, scope_id=None):
        win = self.win
        if scope_id is not None and win.current_console != scope_id:
            win.sidebar.select(scope_id)
        self.library.sync()
        self.push(self.library)
        return True

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
        wanted (the current option of a chooser, the accent row of a game's
        details). The page's own ``shown`` is the last word.
        """
        if getattr(page, "_bp_watched", False):
            return
        page._bp_watched = True
        page.connect("shown", self._on_page_shown)

    def _on_page_shown(self, page):
        if self._active and self.visible_page() is page:
            page.on_shown()
            self.win.navigation.refresh_hints(force=True)

    def pop(self):
        if self.visible_page() is self.home:
            return False
        return bool(self.nav.pop())

    def _on_popped(self, _nav, page):
        self._pushed.discard(page)
        if self.visible_page() is self.home:
            self.home.refresh()
        GLib.idle_add(self._focus_visible)

    def _focus_visible(self):
        page = self.visible_page()
        if page is not None and self._active:
            # Mid-transition a page cannot take the focus yet: the page's
            # ``shown`` (_on_page_shown) is the last word, so a miss here is
            # not retried -- a timed retry stole the focus from the user.
            page.focus_default()
        self.win.navigation.refresh_hints(force=True)
        return GLib.SOURCE_REMOVE

    def go_home(self):
        self.nav.pop_to_page(self.home)
        self.home.refresh()
        GLib.idle_add(self._focus_visible)

    def handle_back(self):
        """B, or Escape: the search sheet, then the page, then nothing."""
        if self.library.search_open and self.visible_page() is self.library:
            self.library.hide_search()
            return True
        return self.pop()

    def step_console(self, delta):
        """LB and RB: the rail on the library; a page's own sections elsewhere.

        A page that has something for the shoulders to walk -- Settings has
        its sections, a game's details the games beside it -- implements
        ``step_section(delta)``.
        """
        page = self.visible_page()
        if page is self.library:
            return self.library.step_console(delta)
        step = getattr(page, "step_section", None)
        if step is not None:
            return bool(step(delta))
        return False

    # -- contexts and hints -----------------------------------------------------------------
    def context_for(self, focus):
        """Where the focus is, for the navigator: the keyboard, the rail or the page."""
        if focus is not None:
            if focus.is_ancestor(self.library.osk):
                return CTX_OSK
            if focus.is_ancestor(self.library.rail):
                return CTX_RAIL
        page = self.visible_page()
        return getattr(page, "context", CTX_PAGE)

    def set_hints(self, pairs):
        glyphs = self.win.navigation.glyphs()
        self.hint_bar.set_hints(pairs, confirm_glyph=glyphs.get("confirm"))

    def hints_for(self, context, glyphs):
        """The hint pairs for a shell context, by the page that owns it."""
        t = self.t
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
                (glyphs["back"], t("hints.back")),
                (glyphs["consoles"], t("hints.console_switch")),
                (glyphs["start"], t("hints.search")),
                (glyphs["menu"], t("big_picture.hints.quick_menu")),
            ]
        page = self.visible_page()
        if page is not None:
            return page.hints(glyphs, t)
        return []

    # -- the actions ------------------------------------------------------------------------
    def run_quick_action(self, entry_id):
        win = self.win
        if entry_id == "search":
            return self.open_search()
        if entry_id == "import":
            return self.open_import()
        if entry_id == "covers":
            return self.open_covers()
        if entry_id == "share":
            return self.open_share()
        if entry_id == "receive":
            win.receive_games()
            return True
        if entry_id == "rescan":
            win._rescan_all_consoles(show_toast=True)
            return True
        if entry_id == "settings":
            return self.open_settings()
        if entry_id == "desktop":
            win.toggle_big_picture()
            return True
        if entry_id == "quit":
            win.get_application().quit()
            return True
        if entry_id == "stop":
            task = win.tasks.current_task()
            if task is not None:
                win.tasks.cancel(task["id"])
            return True
        return False

    def open_quick_menu(self):
        from openemux.ui.bigpicture.quick_menu import QuickMenuDialog

        dialog = QuickMenuDialog(self)
        logger.info("big picture: quick menu")
        dialog.present(self.win)
        return dialog

    def open_search(self):
        if self.visible_page() is not self.library:
            self.open_library()
            GLib.idle_add(self._show_search_idle)
            return True
        return self.library.toggle_search()

    def _show_search_idle(self):
        self.library.show_search()
        return GLib.SOURCE_REMOVE

    def open_details(self, rom):
        from openemux.ui.bigpicture.details import GameDetailsPage

        if self._details is None:
            self._details = GameDetailsPage(self)
        self._details.load(rom)
        self.push(self._details)
        return self._details

    def open_settings(self, section=None, console=None):
        from openemux.ui.bigpicture.settings import SettingsPage

        if self._settings is None:
            self._settings = SettingsPage(self)
        if section is not None:
            self._settings.show_section(section, console=console)
        self.push(self._settings)
        return self._settings

    def open_import(self):
        from openemux.ui.bigpicture.tasks import ImportPage

        if self._import is None:
            self._import = ImportPage(self)
        self._import.refresh()
        self.push(self._import)
        return self._import

    def open_covers(self):
        from openemux.ui.bigpicture.tasks import CoversPage

        if self._covers is None:
            self._covers = CoversPage(self)
        self._covers.refresh()
        self.push(self._covers)
        return self._covers

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

    def open_share(self):
        """Share the current scope's games, or what is selected."""
        win = self.win
        roms = list(getattr(win, "_selected_roms", []) or [])
        if not roms:
            grid = win._visible_grid()
            if grid is not None:
                roms = [entry.rom for entry in grid.entries()]
        if not roms:
            win.receive_games()
            return True
        win.share_roms(roms)
        return True


__all__ = [
    "BigPictureShell", "CTX_HOME", "CTX_LIBRARY", "CTX_RAIL", "CTX_OSK", "CTX_PAGE",
    "QUICK_ACTIONS", "ALL_CONSOLES_ID", "FAVORITES_ID", "RECENT_ID",
]
