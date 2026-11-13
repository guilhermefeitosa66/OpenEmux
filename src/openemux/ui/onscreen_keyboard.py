"""An on-screen keyboard for the search box, for a pad with no keyboard (issue 914).

A letter grid the D-pad walks: every press goes straight into the window's
search entry, so the library filters as the letters go in -- which is also
the letter jump, in a 3000-game library as in a 50-game one. Done (or the
pad's B) closes it and puts the focus on the first match.
"""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

ROWS = (
    "1234567890",
    "ABCDEFGHIJ",
    "KLMNOPQRST",
    "UVWXYZ-.'&",
)


class OnScreenKeyboard(Adw.Dialog):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.t = win.t
        self.set_title(self.t("osk.title"))
        self.set_content_width(620)

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle.new(self.t("osk.title"), ""))
        toolbar.add_top_bar(header)

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        body.set_margin_top(12)
        body.set_margin_bottom(18)
        body.set_margin_start(18)
        body.set_margin_end(18)

        self.query_label = Gtk.Label()
        self.query_label.add_css_class("title-2")
        self.query_label.set_xalign(0.0)
        self.query_label.set_halign(Gtk.Align.START)
        self.query_label.set_selectable(False)
        body.append(self.query_label)

        self.keys = []
        grid = Gtk.Grid(row_spacing=6, column_spacing=6)
        grid.set_halign(Gtk.Align.CENTER)
        for row_index, row in enumerate(ROWS):
            for column, char in enumerate(row):
                key = Gtk.Button(label=char)
                key.add_css_class("osk-key")
                key.set_size_request(48, 48)
                key.connect("clicked", self._on_key, char)
                grid.attach(key, column, row_index, 1, 1)
                self.keys.append(key)
        body.append(grid)

        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        controls.set_halign(Gtk.Align.CENTER)
        self.space_button = Gtk.Button(label=self.t("osk.space"))
        self.space_button.set_size_request(180, 48)
        self.space_button.connect("clicked", self._on_key, " ")
        controls.append(self.space_button)
        self.backspace_button = Gtk.Button(label=self.t("osk.backspace"))
        self.backspace_button.set_size_request(48, 48)
        self.backspace_button.connect("clicked", self._on_backspace)
        controls.append(self.backspace_button)
        self.clear_button = Gtk.Button(label=self.t("osk.clear"))
        self.clear_button.set_size_request(48, 48)
        self.clear_button.connect("clicked", self._on_clear)
        controls.append(self.clear_button)
        self.done_button = Gtk.Button(label=self.t("osk.done"))
        self.done_button.add_css_class("suggested-action")
        self.done_button.set_size_request(96, 48)
        self.done_button.connect("clicked", self._on_done)
        controls.append(self.done_button)
        body.append(controls)

        toolbar.set_content(body)
        self.set_child(toolbar)
        self._sync_query()
        self.connect("closed", self._on_closed)

    # ----- typing -----------------------------------------------------------
    def query(self):
        return self.win.search_entry.get_text()

    def _set_query(self, text):
        if not self.win.search_button.get_active():
            self.win.search_button.set_active(True)
        self.win.search_entry.set_text(text)
        self._sync_query()

    def _sync_query(self):
        text = self.query()
        self.query_label.set_label(text if text else self.t("osk.empty"))
        self.backspace_button.set_sensitive(bool(text))
        self.clear_button.set_sensitive(bool(text))

    def _on_key(self, _button, char):
        self._set_query(self.query() + char.lower())

    def _on_backspace(self, _button):
        self._set_query(self.query()[:-1])

    def _on_clear(self, _button):
        self._set_query("")

    def _on_done(self, _button):
        self.close()

    def _on_closed(self, _dialog):
        # Back on the games, on the first match: the point of the search.
        grid = self.win._visible_grid()
        if grid is not None and grid.count() > 0:
            grid.focus_first_card()
