"""The on-screen keyboard of Big Picture: a QWERTY board the D-pad walks.

Two jobs, one widget. In *search* mode every key goes straight into the
library's search box, so the games filter as the letters go in and Done
lands on the first match. In *text* mode it edits one value -- a device
name, a ScreenScraper login -- and hands it over on Done, or drops it on
Cancel, with lower case, capitals, numbers and the symbols a name or an
address needs. The pad's X is backspace and Y is space in both, so the two
most frequent corrections never cost a trip across the grid.

The keys sit where a phone or a desk keyboard puts them (issue 961), each
row half a key to the right of the one above, and the keyboard walks its own
focus: Up and Down land on the nearest key of the next row, Left and Right
wrap inside a row, and the function row is the last row of the walk.
"""

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Pango

MODE_SEARCH = "search"
MODE_TEXT = "text"

#: Search: what a game title is made of, capitals only, one screen.
ROWS_SEARCH = (
    "1234567890",
    "QWERTYUIOP",
    "ASDFGHJKL'",
    "ZXCVBNM-.&",
)

#: Text: lower case by default, Shift (LT) flips the letters to capitals.
ROWS_TEXT = (
    "1234567890-_@",
    "qwertyuiop()&",
    "asdfghjkl:'\"#",
    "zxcvbnm,./!?+",
)

#: How far each row starts to the right of the one above, in half keys.
ROW_STAGGER = 1

_STEPS = {"up": -1, "down": 1, "left": -1, "right": 1}

#: The widest a text value may grow: a device name, a username, an address.
MAX_TEXT_LENGTH = 64


class OnScreenKeyboard(Gtk.Box):
    """The grid, the field above it and the function row under it.

    ``on_change(text)`` fires on every edit; ``on_done(text)`` on Done;
    ``on_cancel()`` when the value is dropped. ``password`` masks the field.
    """

    def __init__(self, t, mode=MODE_SEARCH, on_change=None, on_done=None,
                 on_cancel=None, password=False, title=None, subtitle=None,
                 initial="", max_length=MAX_TEXT_LENGTH):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        self.t = t
        self.mode = mode
        self.on_change = on_change
        self.on_done = on_done
        self.on_cancel = on_cancel
        self.password = bool(password)
        self.max_length = max_length
        self._text = str(initial or "")
        self._shift = False
        self.add_css_class("bp-osk")

        if title:
            head = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            self.title_label = Gtk.Label(label=title, xalign=0.0)
            self.title_label.add_css_class("bp-row-title")
            head.append(self.title_label)
            if subtitle:
                self.subtitle_label = Gtk.Label(label=subtitle, xalign=0.0)
                self.subtitle_label.add_css_class("bp-row-subtitle")
                self.subtitle_label.set_wrap(True)
                head.append(self.subtitle_label)
            self.append(head)

        field = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        field.add_css_class("bp-osk-field")
        self.field_label = Gtk.Label(xalign=0.0)
        self.field_label.set_hexpand(True)
        self.field_label.set_ellipsize(Pango.EllipsizeMode.START)
        field.append(self.field_label)
        self.field_hint = Gtk.Label(xalign=1.0)
        self.field_hint.add_css_class("bp-row-subtitle")
        field.append(self.field_hint)
        self.append(field)

        rows = ROWS_SEARCH if mode == MODE_SEARCH else ROWS_TEXT
        self.keys = []
        self.letter_keys = []
        #: The keys row by row, the function row last: what the pad walks.
        self.rows = []
        # Half-key columns: a key spans two, so a row can start half a key in.
        # The spacing between columns is also the gap between two keys, so it
        # stays at the 10 px the A-Z grid had.
        grid = Gtk.Grid(row_spacing=10, column_spacing=10)
        grid.set_halign(Gtk.Align.FILL)
        grid.set_column_homogeneous(True)
        for row_index, row in enumerate(rows):
            row_keys = []
            for column, char in enumerate(row):
                key = Gtk.Button(label=char)
                key.add_css_class("bp-osk-key")
                key.add_css_class("flat")
                key.osk_char = char
                key.connect("clicked", self._on_key)
                grid.attach(key, self.key_column(row_index, column), row_index, 2, 1)
                self.keys.append(key)
                row_keys.append(key)
                if char.isalpha():
                    self.letter_keys.append(key)
            self.rows.append(row_keys)
        #: The board's width in half keys, the function row spread across it.
        self.width = max(self.key_column(r, len(row)) for r, row in enumerate(rows))
        self.append(grid)

        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        controls.set_homogeneous(False)
        self.shift_button = None
        if mode == MODE_TEXT:
            self.shift_button = self._function_key(self.t("big_picture.osk.shift"), self.toggle_shift)
            self.shift_button.set_hexpand(True)
            controls.append(self.shift_button)
        self.space_button = self._function_key(self.t("osk.space"), self.space)
        self.space_button.set_hexpand(True)
        controls.append(self.space_button)
        self.backspace_button = self._function_key(self.t("osk.backspace"), self.backspace)
        controls.append(self.backspace_button)
        self.clear_button = self._function_key(self.t("osk.clear"), self.clear)
        controls.append(self.clear_button)
        if mode == MODE_TEXT:
            self.cancel_button = self._function_key(self.t("big_picture.osk.cancel"), self.cancel)
            controls.append(self.cancel_button)
        self.done_button = self._function_key(self.t("osk.done"), self.done)
        self.done_button.add_css_class("suggested-action")
        self.done_button.set_hexpand(True)
        controls.append(self.done_button)
        self.append(controls)
        self.function_keys = []
        child = controls.get_first_child()
        while child is not None:
            self.function_keys.append(child)
            child = child.get_next_sibling()
        self.rows.append(self.function_keys)
        self._sync_field()

    @staticmethod
    def key_column(row, index):
        """The half-key column a key starts at: two per key, plus the row's stagger."""
        return 2 * index + row * ROW_STAGGER

    def _function_key(self, label, callback):
        key = Gtk.Button(label=label)
        key.add_css_class("bp-osk-key")
        key.add_css_class("flat")
        key.connect("clicked", lambda _b: callback())
        return key

    # -- the value -------------------------------------------------------------
    @property
    def text(self):
        return self._text

    def set_text(self, text, notify=False):
        self._text = str(text or "")[: self.max_length]
        self._sync_field()
        if notify and self.on_change is not None:
            self.on_change(self._text)

    def _sync_field(self):
        shown = "•" * len(self._text) if self.password else self._text
        if shown:
            self.field_label.set_label(shown)
            self.field_label.remove_css_class("bp-row-subtitle")
        else:
            self.field_label.set_label(self.t("osk.empty"))
            self.field_label.add_css_class("bp-row-subtitle")
        if self.mode == MODE_TEXT:
            left = self.max_length - len(self._text)
            self.field_hint.set_label(self.t("big_picture.osk.remaining", count=left))
        else:
            self.field_hint.set_label("")
        has_text = bool(self._text)
        self.backspace_button.set_sensitive(has_text)
        self.clear_button.set_sensitive(has_text)

    # -- typing ------------------------------------------------------------------
    def type_char(self, char):
        if len(self._text) >= self.max_length:
            return
        if self.mode == MODE_SEARCH:
            char = char.lower()
        elif self._shift and char.isalpha():
            char = char.upper()
        self.set_text(self._text + char, notify=True)
        if self._shift and self.mode == MODE_TEXT:
            # Shift is one capital, as on a phone: a name has one.
            self.toggle_shift()

    def _on_key(self, key):
        self.type_char(key.osk_char)

    def space(self):
        if self._text:
            self.type_char(" ")

    def backspace(self):
        if self._text:
            self.set_text(self._text[:-1], notify=True)

    def clear(self):
        if self._text:
            self.set_text("", notify=True)

    def toggle_shift(self):
        if self.shift_button is None:
            return False
        self._shift = not self._shift
        for key in self.letter_keys:
            char = key.osk_char
            key.set_label(char.upper() if self._shift else char.lower())
        self.shift_button.set_label(
            self.t("big_picture.osk.shift_on" if self._shift else "big_picture.osk.shift")
        )
        return self._shift

    def done(self):
        if self.on_done is not None:
            self.on_done(self._text)

    def cancel(self):
        if self.on_cancel is not None:
            self.on_cancel()

    # -- the pad -----------------------------------------------------------------
    def handle_action(self, action):
        """The pad's shortcuts over the grid. True when the action was taken."""
        if action == "context":
            self.backspace()
            return True
        if action == "favorite":
            self.space()
            return True
        if action == "search":
            self.done()
            return True
        if action == "back":
            if self.mode == MODE_TEXT:
                self.cancel()
            else:
                self.done()
            return True
        if action == "range" and self.mode == MODE_TEXT:
            self.toggle_shift()
            return True
        return False

    def _centre(self, row, index):
        """Where a key's middle sits, in half keys from the board's left edge."""
        if row == len(self.rows) - 1:
            # The function row spans the board; its keys share it evenly.
            return (index + 0.5) * self.width / len(self.rows[row])
        return self.key_column(row, index) + 1

    def _locate(self, widget):
        for row, keys in enumerate(self.rows):
            for index, key in enumerate(keys):
                if key is widget:
                    return row, index
        return None

    def pad_move(self, direction, focus):
        """The D-pad over the board. True when the move is the keyboard's to make.

        Up and Down take the key of the next row nearest under the one
        left, the same index on a tie, so Down then Up between two letter
        rows comes back to it (the function row is mapped by each key's
        share of the row, so a trip through it lands near, not always on,
        the key it left); Left and Right wrap inside the row. At the top and at the function
        row the focus holds still rather than escaping to the page behind.
        """
        step = _STEPS.get(direction)
        where = self._locate(focus) if step is not None else None
        if where is None:
            return False
        row, index = where
        if direction in ("left", "right"):
            # Backspace and Clear go grey with nothing typed: step over them.
            keys = self.rows[row]
            for hop in range(1, len(keys)):
                key = keys[(index + step * hop) % len(keys)]
                if key.get_sensitive():
                    key.grab_focus()
                    break
            return True
        target = row + step
        if not 0 <= target < len(self.rows):
            return True
        centre = self._centre(row, index)
        live = [i for i, key in enumerate(self.rows[target]) if key.get_sensitive()]
        if not live:
            return True
        best = min(live, key=lambda i: (abs(self._centre(target, i) - centre), i != index))
        self.rows[target][best].grab_focus()
        return True

    def focus_first_key(self):
        if self.keys:
            return self.keys[0].grab_focus()
        return False
