"""The import and cover-sync pages of Big Picture (issue 914).

On the desktop both are a header-bar button and a banner: the button opens
a picker or a dialog, the banner then says what is running. A pad user
never meets a header bar, so here each is a page: the ways in as rows on
the left, and on the right a panel that mirrors the window's banner -- the
task's title, its progress, a Stop button while it can be stopped. The
window's own methods do the work, the pages only ask for it.
"""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Pango

from openemux.ui.bigpicture.widgets import ROW_ACTION, BigPage, Row, body, button, eyebrow, note

#: The widest a wrapping label in the side column asks to be, in characters:
#: a wrapping label's natural width is its whole text on one line, and the
#: box would grow the column to it before the rows got any width at all.
SIDE_CHARS = 44


class ProgressPanel(Gtk.Box):
    """The window's progress banner, as a panel a couch can read.

    Bound to the banner itself rather than to the task registry: the banner
    is what every background task already writes to, so whatever shows up
    there -- a scan, a sync, an import, the drop hint -- shows up here with
    no task having to know about the mode. The registry is read for what
    the banner does not carry: the fraction and whether Stop applies.
    """

    def __init__(self, shell):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.shell = shell
        self.win = shell.win
        t = shell.t
        self.add_css_class("bp-panel")
        self.append(eyebrow(t("big_picture.tasks.progress")))
        self.title_label = Gtk.Label(xalign=0.0)
        self.title_label.add_css_class("bp-row-title")
        self.title_label.set_wrap(True)
        self.title_label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self.title_label.set_max_width_chars(SIDE_CHARS)
        self.append(self.title_label)
        # Not hexpand: a visible expanding child would make the whole side
        # column expand and take the rows' width while a task runs.
        self.bar = Gtk.ProgressBar()
        self.append(self.bar)
        # A task with no total has nothing to fill a bar with; a spinner says
        # "working" without a timer to keep pulsing.
        self.spinner = Gtk.Spinner()
        self.spinner.set_size_request(32, 32)
        self.spinner.set_halign(Gtk.Align.START)
        self.append(self.spinner)
        self.stop_button = button(t("big_picture.tile.stop"), on_click=self.stop, destructive=True)
        self.stop_button.set_halign(Gtk.Align.START)
        self.append(self.stop_button)
        self.idle_label = note(t("big_picture.tasks.idle"))
        self.idle_label.set_max_width_chars(SIDE_CHARS)
        self.append(self.idle_label)
        banner = self.win.banner
        banner.connect("notify::title", lambda *_: self.refresh())
        banner.connect("notify::revealed", lambda *_: self.refresh())
        self.refresh()

    def refresh(self):
        """Re-read the banner and the task behind it."""
        banner = self.win.banner
        task = self.win.tasks.current_task()
        running = bool(banner.get_revealed() and banner.get_title())
        self.idle_label.set_visible(not running)
        self.title_label.set_visible(running)
        if not running:
            self.bar.set_visible(False)
            self.spinner.set_visible(False)
            self.spinner.set_spinning(False)
            self.stop_button.set_visible(False)
            return
        self.title_label.set_label(banner.get_title())
        total = int(task.get("total") or 0) if task else 0
        if total > 0:
            current = int(task.get("current") or 0)
            self.bar.set_fraction(min(1.0, max(0.0, current / total)))
            self.bar.set_visible(True)
            self.spinner.set_visible(False)
            self.spinner.set_spinning(False)
        else:
            self.bar.set_visible(False)
            self.spinner.set_visible(True)
            self.spinner.set_spinning(True)
        self.stop_button.set_visible(
            bool(task and task.get("on_cancel") and not task.get("cancelling"))
        )

    def stop(self):
        """Stop the task the banner shows, when there is one to stop."""
        task = self.win.tasks.current_task()
        if task is not None:
            self.win.tasks.cancel(task["id"])


class _TasksPage(BigPage):
    """The shared frame: rows in a scroller on the left, a side column on the right."""

    context = "bp-page"

    def __init__(self, shell, title, tag, lead_key):
        super().__init__(shell, title, tag=tag)
        self.t = shell.t
        self.body.set_orientation(Gtk.Orientation.HORIZONTAL)
        self.body.set_spacing(48)
        self.column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        lead = body(self.t(lead_key))
        lead.set_margin_bottom(12)
        self.column.append(lead)
        left = self.scrolled(self.column)
        left.set_hexpand(True)
        self.body.append(left)
        self.side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self.side.add_css_class("bp-side")
        self.side.set_valign(Gtk.Align.START)
        self.panel = ProgressPanel(shell)
        self.side.append(self.panel)
        self.body.append(self.scrolled(self.side))

    def _row(self, title, subtitle, on_activate, parent=None):
        row = Row(title, subtitle, kind=ROW_ACTION, on_activate=on_activate)
        (parent or self.column).append(row)
        return row

    def hints(self, g, t):
        return [(g["confirm"], t("big_picture.hints.choose")), (g["back"], t("hints.back"))]


class ImportPage(_TasksPage):
    def __init__(self, shell):
        t = shell.t
        super().__init__(shell, t("big_picture.tile.import"), "bp-import", "big_picture.tasks.import.lead")
        win = shell.win
        # Looked up at the click, not bound here: the window's flows are what
        # a test patches, and what a relaunch replaces.
        self.pick_row = self._row(
            t("big_picture.tasks.import.files"), t("big_picture.tasks.import.files.subtitle"),
            lambda: win.imports.open_picker(),
        )
        self.folder_row = self._row(
            t("big_picture.tasks.import.folder"), t("big_picture.tasks.import.folder.subtitle"),
            lambda: win._choose_roms_path(),
        )
        self.receive_row = self._row(
            t("big_picture.tile.receive"), t("big_picture.tile.receive.subtitle"),
            lambda: win.receive_games(),
        )
        self.rescan_row = self._row(
            t("big_picture.tile.rescan"), t("big_picture.tile.rescan.subtitle"),
            lambda: win._rescan_all_consoles(show_toast=True),
        )

    def refresh(self):
        self.panel.refresh()

    def focus_default(self):
        return self.pick_row.grab_focus()


class CoversPage(_TasksPage):
    def __init__(self, shell):
        t = shell.t
        super().__init__(shell, t("big_picture.tile.covers"), "bp-covers", "big_picture.tasks.covers.lead")
        self.all_row = self._row(t("big_picture.tasks.covers.all"), None, self._sync_all)
        self.console_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.column.append(self.console_box)
        self.console_rows = []
        self.side.append(eyebrow(t("big_picture.tasks.providers")))
        self.providers_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.side.append(self.providers_box)
        self.provider_rows = []
        self.no_providers = note(t("big_picture.tasks.providers.none"))
        self.no_providers.set_max_width_chars(SIDE_CHARS)
        self.side.append(self.no_providers)
        order_note = note(t("big_picture.tasks.providers.note"))
        order_note.set_max_width_chars(SIDE_CHARS)
        self.side.append(order_note)

    @staticmethod
    def _info_row(title, subtitle):
        """A row to read, not to walk: the row's look on a plain box.

        Not an insensitive ``Row``: that one is drawn dimmed, and a dimmed
        provider reads as one that is off, which is the opposite of what
        this list says.
        """
        row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        row.add_css_class("bp-row")
        row.set_valign(Gtk.Align.CENTER)
        row.title_label = Gtk.Label(label=title, xalign=0.0)
        row.title_label.add_css_class("bp-row-title")
        row.title_label.set_ellipsize(Pango.EllipsizeMode.END)
        row.append(row.title_label)
        row.subtitle_label = Gtk.Label(label=subtitle, xalign=0.0)
        row.subtitle_label.add_css_class("bp-row-subtitle")
        row.subtitle_label.set_ellipsize(Pango.EllipsizeMode.END)
        row.append(row.subtitle_label)
        return row

    @staticmethod
    def _clear(box):
        child = box.get_first_child()
        while child is not None:
            following = child.get_next_sibling()
            box.remove(child)
            child = following

    def refresh(self):
        """One row per console with games, the providers as the config orders them."""
        win, t = self.win, self.t
        self._clear(self.console_box)
        self.console_rows = []
        total = 0
        for console in list(win.visible_consoles):
            count = self.shell.game_count(console) or 0
            total += count
            row = self._row(
                win.sidebar.label_for(console), self._count_label(count),
                lambda console=console: self._sync_console(console), parent=self.console_box,
            )
            row.console = console
            self.console_rows.append(row)
        self.all_row.set_subtitle(self._count_label(total))
        self._clear(self.providers_box)
        self.provider_rows = []
        for entry in win.config_manager.get_artwork_providers():
            if not entry.get("enabled", True):
                continue
            provider_id = entry["id"]
            row = self._info_row(
                t(f"prefs.provider.{provider_id}"), t(f"prefs.provider.{provider_id}.subtitle")
            )
            row.provider_id = provider_id
            self.providers_box.append(row)
            self.provider_rows.append(row)
        self.no_providers.set_visible(not self.provider_rows)
        self.panel.refresh()

    def _count_label(self, count):
        t = self.t
        if count == 1:
            return t("header.subtitle.one_game")
        return t("header.subtitle.games", count=count)

    # The window's own entry points, with the arguments its dialog passes.
    def _sync_all(self):
        self.win._start_cover_sync(scope="all", selected_console=None)

    def _sync_console(self, console):
        self.win._start_cover_sync(scope="console", selected_console=console)

    def focus_default(self):
        return self.all_row.grab_focus()


__all__ = ["ProgressPanel", "ImportPage", "CoversPage"]
