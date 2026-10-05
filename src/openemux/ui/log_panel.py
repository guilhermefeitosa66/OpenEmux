"""The log panel under the library, and the "Report a Bug" dialog.

Both exist so a person who is not a developer can hand the developer what a
bug report needs: what OpenEmux was doing (the log) and what it was doing it
on (``core.sysinfo``). Nothing leaves the machine by itself -- the user copies
the text and pastes it into a GitHub issue form that opens pre-filled.
"""

import logging
import urllib.parse

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from openemux import __version__  # noqa: E402
from openemux.core import log_buffer, sysinfo  # noqa: E402

logger = logging.getLogger(__name__)

ISSUE_FORM_URL = "https://github.com/guilhermefeitosa66/OpenEmux/issues/new"

#: The panel's height when open: tall enough for a dozen lines and the
#: buttons, short enough to leave the library in view above it.
PANEL_HEIGHT = 280


def collect_facts(win):
    """The machine's facts, with the toolkit versions only the UI can read."""
    gtk = f"{Gtk.get_major_version()}.{Gtk.get_minor_version()}.{Gtk.get_micro_version()}"
    adw = f"{Adw.get_major_version()}.{Adw.get_minor_version()}.{Adw.get_micro_version()}"
    binary = None
    try:
        binary = win.runtime_manager.retroarch_launcher._resolve_retroarch_binary()
    except Exception:  # noqa: BLE001 - the report goes on without it
        logger.debug("log panel: retroarch binary not resolved", exc_info=True)
    return sysinfo.collect(gtk=gtk, adwaita=adw, retroarch_binary=binary)


def report_text(facts, lines):
    """What "copy" puts on the clipboard: the facts, then the log tail."""
    log = "\n".join(line.text for line in lines) or "(the log is empty)"
    return (
        "### System\n"
        f"{sysinfo.as_text(facts)}\n\n"
        f"### Log (last {len(lines)} lines)\n"
        f"{log}\n"
    )


def issue_url(facts):
    """The bug form, with what the URL can carry already filled in.

    GitHub issue forms take a field's value from the query string by the
    field's ``id`` (``.github/ISSUE_TEMPLATE/bug_report.yml``). The log does
    not go in the URL -- it would blow past any sane URL length -- so the
    user pastes it from the clipboard.
    """
    by_label = dict(facts)
    query = {
        "template": "bug_report.yml",
        "labels": "bug",
        "version": __version__,
        "os": by_label.get("System", ""),
    }
    return f"{ISSUE_FORM_URL}?{urllib.parse.urlencode(query)}"


class LogPanel:
    """The panel itself; ``widget`` is what the window docks."""

    def __init__(self, win, buffer=None):
        self.win = win
        self.buffer = buffer or log_buffer.BUFFER
        t = win.t

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.add_css_class("log-panel")
        box.set_size_request(-1, PANEL_HEIGHT)

        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        title = Gtk.Label(label=t("log.title"))
        title.add_css_class("heading")
        header.append(title)
        live = Gtk.Label(label=t("log.live"))
        live.add_css_class("caption")
        live.add_css_class("log-live")
        header.append(live)
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        header.append(spacer)

        clear = Gtk.Button(label=t("log.clear"))
        clear.connect("clicked", lambda _b: self.clear())
        header.append(clear)
        copy = Gtk.Button(label=t("log.copy"))
        copy.connect("clicked", lambda _b: self.copy_report())
        header.append(copy)
        report = Gtk.Button(label=t("log.report"))
        report.add_css_class("suggested-action")
        report.connect("clicked", lambda _b: self.win.show_bug_report())
        header.append(report)
        close = Gtk.Button.new_from_icon_name("window-close-symbolic")
        close.add_css_class("flat")
        close.set_tooltip_text(t("log.hide"))
        close.connect("clicked", lambda _b: self.win.set_log_panel_visible(False))
        header.append(close)
        box.append(header)

        notice = Gtk.Label(label=t("log.notice"))
        notice.set_wrap(True)
        notice.set_xalign(0)
        notice.add_css_class("log-notice")
        box.append(notice)

        self.view = Gtk.TextView()
        self.view.set_editable(False)
        self.view.set_cursor_visible(False)
        self.view.set_monospace(True)
        self.view.add_css_class("log-view")
        self.text = self.view.get_buffer()
        self.text.create_tag("warning-level", weight=700, foreground="#c46f00")
        self.text.create_tag("error-level", weight=700, foreground="#e01b24")
        self.text.create_tag("info-level", weight=700, foreground="#26a269")

        scroll = Gtk.ScrolledWindow()
        scroll.set_vexpand(True)
        scroll.set_child(self.view)
        scroll.add_css_class("log-scroll")
        self.scroll = scroll
        box.append(scroll)

        self.revealer = Gtk.Revealer()
        self.revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_UP)
        self.revealer.set_child(box)
        self.widget = self.revealer

        for line in self.buffer.lines():
            self._append(line)
        self.buffer.add_listener(self._on_line)
        win.connect("close-request", self._on_close)

    # ----- the lines ------------------------------------------------------
    def _on_line(self, line):
        # Any thread can log; the text buffer belongs to the main loop.
        GLib.idle_add(self._append_from_idle, line)

    def _append_from_idle(self, line):
        self._append(line, scroll=True)
        if line.is_error and not self.revealer.get_reveal_child():
            self.win.update_log_badge(self.buffer.errors_since_seen)
        return GLib.SOURCE_REMOVE

    def _append(self, line, scroll=False):
        end = self.text.get_end_iter()
        if line.level >= logging.ERROR:
            tag = "error-level"
        elif line.level >= logging.WARNING:
            tag = "warning-level"
        else:
            tag = "info-level"
        # "2026-10-04 17:02:00,394 INFO [module] message": the level is the
        # third field, and it is the one worth colouring.
        parts = line.text.split(" ", 3)
        if len(parts) == 4:
            self.text.insert(end, f"{parts[1][:8]}  ")
            self.text.insert_with_tags_by_name(self.text.get_end_iter(), f"{parts[2]:<7}", tag)
            self.text.insert(self.text.get_end_iter(), f" {parts[3]}\n")
        else:
            self.text.insert(end, line.text + "\n")
        if scroll:
            mark = self.text.create_mark(None, self.text.get_end_iter(), False)
            self.view.scroll_mark_onscreen(mark)
            self.text.delete_mark(mark)

    def _on_close(self, *_args):
        self.buffer.remove_listener(self._on_line)
        return False

    # ----- the buttons ----------------------------------------------------
    def set_open(self, opened):
        self.revealer.set_reveal_child(bool(opened))
        if opened:
            self.buffer.mark_seen()
            self.win.update_log_badge(0)

    def clear(self):
        self.buffer.clear()
        self.text.set_text("")

    def copy_report(self):
        text = report_text(collect_facts(self.win), self.buffer.tail())
        self.win.get_clipboard().set(text)
        self.win._toast(self.win.t("log.copied"), timeout=3)
        return text


class BugReportDialog:
    """Two steps: copy the details, then open the pre-filled form."""

    def __init__(self, win, buffer=None):
        self.win = win
        self.buffer = buffer or log_buffer.BUFFER
        self.facts = collect_facts(win)
        t = win.t

        dialog = Adw.Dialog()
        dialog.set_title(t("report.title"))
        dialog.set_content_width(560)

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(Adw.HeaderBar())

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        body.set_margin_start(28)
        body.set_margin_end(28)
        body.set_margin_bottom(28)

        intro = Gtk.Label(label=t("report.intro"))
        intro.set_wrap(True)
        intro.set_xalign(0)
        body.append(intro)

        # Step 1: what will be copied, shown before it is.
        body.append(self._step("1", t("report.step1")))
        facts_grid = Gtk.Grid(column_spacing=14, row_spacing=4)
        facts_grid.add_css_class("report-facts")
        for row, (label, value) in enumerate(self.facts):
            key = Gtk.Label(label=label, xalign=0)
            key.add_css_class("dim-label")
            key.add_css_class("monospace")
            val = Gtk.Label(label=value, xalign=0)
            val.set_wrap(True)
            val.add_css_class("monospace")
            facts_grid.attach(key, 0, row, 1, 1)
            facts_grid.attach(val, 1, row, 1, 1)
        more = Gtk.Label(
            label=t("report.step1.more", count=len(self.buffer.tail())), xalign=0
        )
        more.add_css_class("dim-label")
        more.add_css_class("monospace")
        facts_grid.attach(more, 0, len(self.facts), 2, 1)
        frame = Gtk.Frame()
        frame.set_child(facts_grid)
        facts_grid.set_margin_top(10)
        facts_grid.set_margin_bottom(10)
        facts_grid.set_margin_start(12)
        facts_grid.set_margin_end(12)
        body.append(frame)

        copy_row = Gtk.Box(spacing=12)
        self.copy_button = Gtk.Button(label=t("report.copy"))
        self.copy_button.add_css_class("suggested-action")
        self.copy_button.add_css_class("pill")
        self.copy_button.set_halign(Gtk.Align.START)
        self.copy_button.connect("clicked", self._on_copy)
        copy_row.append(self.copy_button)
        self.copied_label = Gtk.Label(label=t("report.copied.hint"))
        self.copied_label.add_css_class("success")
        self.copied_label.set_visible(False)
        copy_row.append(self.copied_label)
        body.append(copy_row)

        # Step 2: the form, opened in the browser.
        body.append(self._step("2", t("report.step2")))
        step2 = Gtk.Label(label=t("report.step2.body"))
        step2.set_wrap(True)
        step2.set_xalign(0)
        body.append(step2)
        open_button = Gtk.Button()
        open_button.set_child(
            Adw.ButtonContent(icon_name="web-browser-symbolic", label=t("report.open"))
        )
        open_button.add_css_class("pill")
        open_button.set_halign(Gtk.Align.START)
        open_button.connect("clicked", self._on_open)
        body.append(open_button)

        # Scrolls rather than clips: the dialog is taller than a small window
        # (libadwaita warned at 707 px requested against 625 available).
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_propagate_natural_height(True)
        scroller.set_child(body)
        toolbar.set_content(scroller)
        dialog.set_child(toolbar)
        self.dialog = dialog

    @staticmethod
    def _step(number, text):
        row = Gtk.Box(spacing=10)
        badge = Gtk.Label(label=number)
        badge.add_css_class("report-step")
        row.append(badge)
        title = Gtk.Label(label=text, xalign=0)
        title.add_css_class("heading")
        row.append(title)
        return row

    def present(self):
        self.dialog.present(self.win)
        # The first thing to do is copy, so that is where the focus starts.
        self.copy_button.grab_focus()

    def _on_copy(self, _button):
        text = report_text(self.facts, self.buffer.tail())
        self.win.get_clipboard().set(text)
        self.copy_button.set_label(self.win.t("report.copied"))
        self.copied_label.set_visible(True)

    def _on_open(self, _button):
        url = issue_url(self.facts)
        logger.info("bug report: opening the issue form")
        self.win._open_uri(url)
