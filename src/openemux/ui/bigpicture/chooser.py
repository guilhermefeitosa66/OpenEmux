"""The two pages every settings row borrows: a list to pick from, a keyboard.

A choice in Big Picture is not a drop-down -- a popover is a small target
on a big screen, and the pad has nowhere to rest while it is open. It is a
page: every option a full-width row, the current one marked and focused, A
picks and pops, B keeps what was there. A text value is the same idea with
the on-screen keyboard in the body: Done hands the text back and pops,
Cancel (or B) pops and hands back nothing.

Both pages are single instances the shell reuses, so ``open`` resets all
of their state every time.
"""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Pango

from openemux.ui.bigpicture.osk import MAX_TEXT_LENGTH, MODE_TEXT, OnScreenKeyboard
from openemux.ui.bigpicture.widgets import BigPage, body

#: The radio marks: the option in force, and the others.
MARK_CURRENT = "●"
MARK_OTHER = "○"


def clear_children(box):
    child = box.get_first_child()
    while child is not None:
        following = child.get_next_sibling()
        box.remove(child)
        child = following


def scroll_to_focus(scroller):
    """Make the scroller follow the focus; GTK before 4.6.2 defaulted this off."""
    viewport = scroller.get_child()
    if isinstance(viewport, Gtk.Viewport):
        viewport.set_scroll_to_focus(True)
    return scroller


class OptionRow(Gtk.Button):
    """One option: a radio mark, a label, a subtitle when there is one."""

    def __init__(self, option_id, label, subtitle=None, current=False):
        super().__init__()
        self.option_id = option_id
        self.add_css_class("bp-row")
        self.add_css_class("flat")
        self.set_hexpand(True)
        self.set_halign(Gtk.Align.FILL)
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=18)
        box.set_valign(Gtk.Align.CENTER)
        self.mark = Gtk.Label()
        self.mark.add_css_class("bp-row-title")
        box.append(self.mark)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        text.set_hexpand(True)
        text.set_valign(Gtk.Align.CENTER)
        title = Gtk.Label(label=label, xalign=0.0)
        title.add_css_class("bp-row-title")
        title.set_ellipsize(Pango.EllipsizeMode.END)
        text.append(title)
        if subtitle:
            sub = Gtk.Label(label=subtitle, xalign=0.0)
            sub.add_css_class("bp-row-subtitle")
            sub.set_ellipsize(Pango.EllipsizeMode.END)
            text.append(sub)
        box.append(text)
        self.set_child(box)
        self.set_current(current)

    def set_current(self, current):
        self.mark.set_label(MARK_CURRENT if current else MARK_OTHER)
        if current:
            self.add_css_class("bp-current")
        else:
            self.remove_css_class("bp-current")


class ChooserPage(BigPage):
    context = "bp-page"

    def __init__(self, shell):
        super().__init__(shell, shell.t("big_picture.hints.choose"), tag="bp-chooser")
        self.lead_label = body("")
        self.lead_label.set_visible(False)
        self.list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        column.append(self.lead_label)
        column.append(self.list)
        self.body.append(scroll_to_focus(self.scrolled(column)))
        self.rows = []
        self.current = None
        self.on_pick = None

    def open(self, title, options, current, on_pick, crumbs=None, lead=None):
        """Show ``options`` (``{"id", "label", "subtitle"?}``), ``current`` marked.

        A on a row calls ``on_pick(id)`` and pops the page; B pops it and
        calls nothing.
        """
        self.set_title(title)
        self.set_crumbs(crumbs or [title])
        self.lead_label.set_label(lead or "")
        self.lead_label.set_visible(bool(lead))
        clear_children(self.list)
        self.rows = []
        self.current = current
        self.on_pick = on_pick
        for option in options:
            row = OptionRow(option["id"], option["label"], option.get("subtitle"),
                            current=option["id"] == current)
            row.connect("clicked", self._on_row_clicked)
            self.list.append(row)
            self.rows.append(row)

    def current_row(self):
        for row in self.rows:
            if row.option_id == self.current:
                return row
        return self.rows[0] if self.rows else None

    def _on_row_clicked(self, row):
        on_pick = self.on_pick
        # Once: a second A before the pop lands must not pick twice.
        self.on_pick = None
        if on_pick is not None:
            on_pick(row.option_id)
        if self.shell.visible_page() is self:
            self.shell.pop()

    def focus_default(self):
        row = self.current_row()
        return row.grab_focus() if row is not None else False

    def hints(self, g, t):
        return [(g["confirm"], t("big_picture.hints.pick")), (g["back"], t("big_picture.hints.keep"))]


class TextEntryPage(BigPage):
    context = "bp-text"

    def __init__(self, shell):
        super().__init__(shell, shell.t("big_picture.hints.type"), tag="bp-text")
        self.host = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.host.set_valign(Gtk.Align.START)
        self.body.append(self.host)
        self.osk = None
        self.on_done = None

    def open(self, title, initial, on_done, subtitle=None, password=False,
             max_length=MAX_TEXT_LENGTH, crumbs=None):
        """Edit ``initial``; Done calls ``on_done(text)`` and pops, Cancel only pops."""
        self.set_title(title)
        self.set_crumbs(crumbs or [title])
        if self.osk is not None:
            self.host.remove(self.osk)
        # A new keyboard per value: the mode, the mask and the limit are
        # construction-time, and a fresh grid has no shift left on.
        self.osk = OnScreenKeyboard(
            self.shell.t, MODE_TEXT, on_done=self._on_osk_done, on_cancel=self._on_osk_cancel,
            password=password, title=title, subtitle=subtitle, initial=initial, max_length=max_length,
        )
        self.host.append(self.osk)
        self.on_done = on_done

    def _on_osk_done(self, text):
        on_done = self.on_done
        self.on_done = None
        if on_done is not None:
            on_done(text)
        if self.shell.visible_page() is self:
            self.shell.pop()

    def _on_osk_cancel(self):
        self.on_done = None
        if self.shell.visible_page() is self:
            self.shell.pop()

    def on_pad_action(self, action):
        """X and Y from the navigator: backspace and space, as on the search keyboard."""
        return self.osk.handle_action(action)

    def focus_default(self):
        return self.osk.focus_first_key()

    def hints(self, g, t):
        return [
            (g["confirm"], t("big_picture.hints.type")),
            (g["context"], t("big_picture.hints.backspace")),
            (g["favorite"], t("big_picture.hints.space")),
            (g["range"], t("big_picture.settings.hints.shift")),
            (g["start"], t("big_picture.hints.done")),
            (g["back"], t("big_picture.osk.cancel")),
        ]


__all__ = ["ChooserPage", "TextEntryPage", "OptionRow", "MARK_CURRENT", "MARK_OTHER"]
