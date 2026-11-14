"""The pieces every Big Picture page is made of.

Rows a D-pad walks (a switch, a choice, a number, a text field, an action),
tiles, chips, the view switch, the task banners, the hint bar and the page
frame with its safe inset (issue 957: the Android gamepad layout's pieces). Every one is a real ``Gtk.Button``
or a box of them, so GTK's own focus chain, the window's ``.keynav-active``
ring and the navigator's ``activate`` all work without special cases.
"""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Graphene, Gsk, Gtk, Pango


#: Row kinds. The kind decides what sits at the end of the row and what the
#: pad's A and Left/Right do on it.
ROW_ACTION = "action"      # A opens something: a chevron at the end
ROW_SWITCH = "switch"      # A toggles: a switch at the end
ROW_CHOICE = "choice"      # A opens a chooser: the current value and a chevron
ROW_NUMBER = "number"      # Left/Right step: ‹ value ›
ROW_TEXT = "text"          # A opens the on-screen keyboard: the value and a pencil
ROW_INFO = "info"          # Not focusable: a line of information

#: How many hint slots the bar draws at most; the navigator never sends more.
MAX_HINTS = 8


def once(callback, *args):
    """``callback`` as a one-shot idle: whatever it returns, it runs once.

    ``grab_focus`` and friends return True on success, which an idle source
    reads as "call me again" -- for ever, and the test harness's idle pump
    with it.
    """
    def _run():
        callback(*args)
        return GLib.SOURCE_REMOVE
    return _run


class Row(Gtk.Button):
    """One focusable row: a title, an optional subtitle, a value at the end.

    ``on_activate`` runs on A (or Enter, or a click). A ``ROW_NUMBER`` row
    also takes ``on_step(delta)`` from Left/Right; a ``ROW_SWITCH`` row flips
    its switch and reports the new state through ``on_activate(active)``.
    """

    def __init__(self, title, subtitle=None, kind=ROW_ACTION, value=None,
                 on_activate=None, on_step=None, active=False, destructive=False,
                 primary=False, icon_name=None):
        super().__init__()
        self.kind = kind
        self.on_activate = on_activate
        self.on_step = on_step
        self.add_css_class("bp-row")
        self.add_css_class("flat")
        if destructive:
            self.add_css_class("bp-danger")
        if primary:
            self.add_css_class("bp-primary")
        self.set_hexpand(True)
        self.set_halign(Gtk.Align.FILL)

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        box.set_valign(Gtk.Align.CENTER)
        if icon_name:
            icon = Gtk.Image.new_from_icon_name(icon_name)
            icon.set_pixel_size(28)
            box.append(icon)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        text.set_hexpand(True)
        text.set_valign(Gtk.Align.CENTER)
        self.title_label = Gtk.Label(label=title, xalign=0.0)
        self.title_label.add_css_class("bp-row-title")
        self.title_label.set_ellipsize(Pango.EllipsizeMode.END)
        text.append(self.title_label)
        self.subtitle_label = Gtk.Label(xalign=0.0)
        self.subtitle_label.add_css_class("bp-row-subtitle")
        self.subtitle_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.subtitle_label.set_visible(bool(subtitle))
        if subtitle:
            self.subtitle_label.set_label(subtitle)
        text.append(self.subtitle_label)
        box.append(text)

        # Android's "DEFAULT" tag before a value the console decides.
        self.tag_label = Gtk.Label()
        self.tag_label.add_css_class("bp-tag")
        self.tag_label.set_valign(Gtk.Align.CENTER)
        self.tag_label.set_visible(False)
        box.append(self.tag_label)
        self.value_label = Gtk.Label(xalign=1.0)
        self.value_label.add_css_class("bp-row-value")
        self.value_label.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
        self.value_label.set_max_width_chars(36)
        self.switch = None
        self.number_label = None
        if kind == ROW_SWITCH:
            self.switch = Gtk.Switch()
            self.switch.set_active(bool(active))
            self.switch.set_can_focus(False)
            self.switch.set_valign(Gtk.Align.CENTER)
            box.append(self.switch)
        elif kind == ROW_NUMBER:
            stepper = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            minus = Gtk.Label(label="‹")
            minus.add_css_class("bp-step")
            self.number_label = Gtk.Label(label=str(value if value is not None else ""))
            self.number_label.add_css_class("bp-number")
            self.number_label.set_justify(Gtk.Justification.CENTER)
            plus = Gtk.Label(label="›")
            plus.add_css_class("bp-step")
            stepper.append(minus)
            stepper.append(self.number_label)
            stepper.append(plus)
            box.append(stepper)
        else:
            if value is not None:
                self.value_label.set_label(str(value))
            box.append(self.value_label)
            if kind == ROW_TEXT:
                pencil = Gtk.Image.new_from_icon_name("document-edit-symbolic")
                pencil.add_css_class("bp-row-chevron")
                box.append(pencil)
            elif kind in (ROW_ACTION, ROW_CHOICE):
                chevron = Gtk.Label(label="›")
                chevron.add_css_class("bp-row-chevron")
                box.append(chevron)
        self.set_child(box)
        if kind == ROW_INFO:
            self.set_can_focus(False)
            self.set_sensitive(False)
            self.add_css_class("bp-disabled")
        self.connect("clicked", self._on_clicked)
        if kind == ROW_NUMBER:
            keys = Gtk.EventControllerKey()
            keys.connect("key-pressed", self._on_key_pressed)
            self.add_controller(keys)

    # -- state ---------------------------------------------------------------
    def set_value(self, value):
        """The text at the end of a choice, text or action row."""
        if self.number_label is not None:
            self.number_label.set_label(str(value))
        else:
            self.value_label.set_label("" if value is None else str(value))

    def set_tag(self, text):
        """A small caps tag before the value ("DEFAULT"); None hides it."""
        self.tag_label.set_label(text or "")
        self.tag_label.set_visible(bool(text))

    def set_subtitle(self, subtitle):
        self.subtitle_label.set_label(subtitle or "")
        self.subtitle_label.set_visible(bool(subtitle))

    def set_active(self, active):
        """A switch row's state, without reporting it."""
        if self.switch is not None:
            self.switch.set_active(bool(active))

    def get_active(self):
        return bool(self.switch is not None and self.switch.get_active())

    # -- input ---------------------------------------------------------------
    def _on_clicked(self, _button):
        if self.kind == ROW_SWITCH:
            self.switch.set_active(not self.switch.get_active())
            if self.on_activate is not None:
                self.on_activate(self.switch.get_active())
            return
        if self.on_activate is not None:
            self.on_activate()

    def step(self, delta):
        """Left/Right on a number row. True when the row took the move."""
        if self.kind != ROW_NUMBER or self.on_step is None:
            return False
        self.on_step(delta)
        return True

    def _on_key_pressed(self, _controller, keyval, _keycode, _state):
        if keyval in (Gdk.KEY_Left, Gdk.KEY_KP_Left):
            return self.step(-1)
        if keyval in (Gdk.KEY_Right, Gdk.KEY_KP_Right):
            return self.step(1)
        return False


#: The longest name, in characters, a wide tile grows to hold before it
#: ellipsizes. The longest shipped ones are 27 (Tamil, where combining marks
#: count as characters) and 26 ("Synchroniser les jaquettes").
TILE_NAME_CHARS = 28


class Tile(Gtk.Button):
    """A big square-ish button: a badge or icon, a name, a count under it."""

    def __init__(self, name, count=None, badge=None, texture=None, icon_name=None,
                 on_activate=None, style=None, wide=False, fit_name=True):
        super().__init__()
        self.on_activate = on_activate
        self.add_css_class("bp-tile")
        self.add_css_class("flat")
        if style:
            self.add_css_class(style)
        if wide:
            self.add_css_class("bp-wide")
        box = Gtk.Box(
            orientation=Gtk.Orientation.HORIZONTAL if wide else Gtk.Orientation.VERTICAL,
            spacing=14,
        )
        # A wide tile is as wide as what it holds; a tall one is the width
        # the stylesheet gives every console tile, and its text fills it.
        # In a fixed grid (fit_name off) it fills its cell instead, or a name
        # with no count under it would shrink to its ellipsis.
        box.set_halign(Gtk.Align.START if wide and fit_name else Gtk.Align.FILL)
        box.set_valign(Gtk.Align.CENTER)
        self.badge = make_badge(badge, texture, icon_name)
        # Centred, not filled: a console picture given the tile's whole width
        # would draw as tall as it is wide.
        self.badge.set_halign(Gtk.Align.START if wide else Gtk.Align.CENTER)
        box.append(self.badge)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        text.set_valign(Gtk.Align.CENTER)
        # One line, never wrapped: a wrapping label's minimum is a few
        # characters, a strip wider than the screen hands every tile its
        # minimum, and Pango then broke the words ("Bu-scar", issue 955).
        # A name that still does not fit ends in an ellipsis.
        self.name_label = Gtk.Label(label=name)
        self.name_label.add_css_class("bp-tile-name")
        self._single_line(self.name_label, wide, name, fit_name)
        text.append(self.name_label)
        self.count_label = Gtk.Label(label=count or "")
        self.count_label.add_css_class("bp-tile-count")
        self.count_label.set_visible(bool(count))
        self.count_label.set_ellipsize(Pango.EllipsizeMode.END)
        if not wide:
            self.count_label.set_max_width_chars(1)
        self.count_label.set_xalign(0.0 if wide else 0.5)
        text.append(self.count_label)
        box.append(text)
        self.set_child(box)
        self.connect("clicked", lambda _b: self.on_activate() if self.on_activate else None)

    def set_count(self, count):
        self.count_label.set_label(count or "")
        self.count_label.set_visible(bool(count))

    @staticmethod
    def _single_line(label, wide, text, fit_name=True):
        label.set_single_line_mode(True)
        label.set_xalign(0.0 if wide else 0.5)
        if not wide:
            # Never wider than the tile: every console tile is one width, and
            # a name longer than that ends in an ellipsis.
            label.set_ellipsize(Pango.EllipsizeMode.END)
            # No hexpand: the vertical box already gives the label the tile's
            # width, and an expanding child makes the tile expand too, so a
            # short Consoles row would stretch its tiles across the screen.
            label.set_max_width_chars(1)
        elif not fit_name:
            # A tile in a fixed grid (the quick menu, a dialog of one width):
            # the grid decides the width, and a longer name ends in "…".
            label.set_ellipsize(Pango.EllipsizeMode.END)
            label.set_max_width_chars(1)
            label.set_hexpand(True)
        elif len(text or "") > TILE_NAME_CHARS:
            # Past the cap a wide tile stops growing and ellipsizes.
            label.set_ellipsize(Pango.EllipsizeMode.END)
            label.set_width_chars(TILE_NAME_CHARS)
            label.set_max_width_chars(TILE_NAME_CHARS)
        # Otherwise not ellipsized at all, so the label's minimum is the whole
        # name: squeezed is what broke it, and the row scrolls instead.


def make_badge(text=None, texture=None, icon_name=None):
    """The square at the head of a tile: a console icon, a glyph or letters."""
    if texture is not None:
        picture = Gtk.Picture.new_for_paintable(texture)
        picture.set_content_fit(Gtk.ContentFit.CONTAIN)
        picture.set_can_shrink(True)
        picture.add_css_class("bp-badge")
        picture.set_valign(Gtk.Align.CENTER)
        return picture
    if icon_name:
        image = Gtk.Image.new_from_icon_name(icon_name)
        image.set_pixel_size(36)
        image.add_css_class("bp-badge")
        image.set_valign(Gtk.Align.CENTER)
        return image
    label = Gtk.Label(label=text or "")
    label.add_css_class("bp-badge")
    label.set_valign(Gtk.Align.CENTER)
    return label


def console_badge_text(console_id):
    """Letters for a console with no icon asset: the id, cut to four."""
    return str(console_id or "")[:4].upper()


class HintBar(Gtk.Box):
    """The bar along the bottom: what the pad's buttons do right now.

    Centered under the content, as on Android: the confirm key a round
    accent, the others dark, the shoulders on one pill.
    """

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL)
        self.add_css_class("bp-hints")
        self.set_valign(Gtk.Align.END)
        self.row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=28)
        self.row.set_halign(Gtk.Align.CENTER)
        self.row.set_hexpand(True)
        self.append(self.row)
        self.slots = []
        for _ in range(MAX_HINTS):
            slot = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
            slot.set_valign(Gtk.Align.CENTER)
            key = Gtk.Label()
            key.add_css_class("bp-key")
            text = Gtk.Label()
            text.add_css_class("bp-hint")
            # Ellipsizable, so seven hints never ask for more width than a
            # 1280 px window has: the bar shrinks before the window does.
            text.set_ellipsize(Pango.EllipsizeMode.END)
            slot.append(key)
            slot.append(text)
            slot.set_visible(False)
            self.row.append(slot)
            self.slots.append((slot, key, text))

    def set_hints(self, pairs, confirm_glyph=None):
        pairs = list(pairs)[:MAX_HINTS]
        for index, (slot, key, text) in enumerate(self.slots):
            if index < len(pairs):
                glyph, label = pairs[index]
                key.set_label(glyph)
                text.set_label(label)
                if confirm_glyph is not None and glyph == confirm_glyph:
                    key.add_css_class("bp-confirm")
                else:
                    key.remove_css_class("bp-confirm")
                slot.set_visible(True)
            else:
                slot.set_visible(False)


def icon_button(icon_name, tooltip=None, on_click=None):
    """A round button with one icon: the pane's expand, star and share."""
    widget = Gtk.Button.new_from_icon_name(icon_name)
    widget.add_css_class("bp-icon-button")
    if tooltip:
        widget.set_tooltip_text(tooltip)
    if on_click is not None:
        widget.connect("clicked", lambda _b: on_click())
    return widget


def pixel_icon_geometry(width, height, native):
    """Where a ``native``-px pixel-art icon goes in a ``width`` x ``height`` slot.

    ``(x, y, size, nearest)``: the largest whole multiple of ``native`` that
    fits, nearest-neighbour, so every source pixel stays a sharp square
    (issue 962). A slot smaller than the art draws it at the slot's size with
    the smooth filter instead: nearest-neighbour shrinking drops pixel rows
    unevenly. Centred on whole pixels.
    """
    side = max(0, min(width, height))
    multiple = side // native
    nearest = multiple >= 1
    size = multiple * native if nearest else side
    return (width - size) // 2, (height - size) // 2, size, nearest


class PixelIcon(Gtk.Widget):
    """A console's pixel art, scaled crisp: the console chips' icon (issue 962).

    ``Gtk.Picture`` scales with a linear filter, which blurs 32-px art; this
    draws the texture itself with ``pixel_icon_geometry``. The slot's size
    comes from the stylesheet (``min-width``/``min-height``).
    """

    def __init__(self, texture):
        super().__init__()
        self.texture = texture
        self.add_css_class("bp-chip-art")
        self.set_valign(Gtk.Align.CENTER)

    def do_snapshot(self, snapshot):
        texture = self.texture
        x, y, size, nearest = pixel_icon_geometry(
            self.get_width(), self.get_height(), max(texture.get_width(), texture.get_height()))
        if size <= 0:
            return
        scaling = Gsk.ScalingFilter.NEAREST if nearest else Gsk.ScalingFilter.TRILINEAR
        snapshot.append_scaled_texture(texture, scaling, Graphene.Rect().init(x, y, size, size))


class Chip(Gtk.Button):
    """A pill: a console chip, a filter chip. ``set_state`` marks it.

    With an ``icon`` widget, it sits at the left of the label (the console
    chips, issue 962); ``get_label``/``set_label`` still read the text.
    """

    def __init__(self, label, on_activate=None, icon=None):
        super().__init__()
        self.add_css_class("bp-chip")
        self.icon = icon
        self.text = None
        if icon is None:
            super().set_label(label)
        else:
            self.add_css_class("bp-chip-icon")
            self.text = Gtk.Label(label=label)
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
            box.add_css_class("bp-chip-content")
            box.set_halign(Gtk.Align.CENTER)
            box.append(icon)
            box.append(self.text)
            self.set_child(box)
        self.on_activate = on_activate
        self.connect("clicked", lambda _b: self.on_activate() if self.on_activate else None)

    def get_label(self):
        if self.text is None:
            return super().get_label()
        return self.text.get_label()

    def set_label(self, label):
        if self.text is None:
            super().set_label(label)
        else:
            self.text.set_label(label)

    def set_current(self, current):
        """The chip of the scope on screen: white, as on Android."""
        _set_class(self, "bp-current", current)

    def set_on(self, on):
        """A filter chip that is on: the accent's soft tone."""
        _set_class(self, "bp-on", on)

    def is_on(self):
        return self.has_css_class("bp-on")


def _set_class(widget, name, present):
    if present:
        widget.add_css_class(name)
    else:
        widget.remove_css_class(name)


class Segments(Gtk.Box):
    """Android's segmented control: one icon button per choice, one current.

    ``choices`` are ``(id, icon_name, tooltip)``; ``on_pick(id)`` runs when
    a segment is activated.
    """

    def __init__(self, choices, on_pick):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        self.add_css_class("bp-segments")
        self.set_valign(Gtk.Align.CENTER)
        self.on_pick = on_pick
        self.buttons = {}
        self.current = None
        for choice_id, icon_name, tooltip in choices:
            button = Gtk.Button.new_from_icon_name(icon_name)
            button.add_css_class("bp-segment")
            button.set_tooltip_text(tooltip)
            button.connect("clicked", lambda _b, choice_id=choice_id: self.on_pick(choice_id))
            self.append(button)
            self.buttons[choice_id] = button

    def set_current(self, choice_id):
        self.current = choice_id
        for button_id, button in self.buttons.items():
            _set_class(button, "bp-current", button_id == choice_id)

    def focus_current(self):
        """The pad arriving from below: the segment that is on, else the first."""
        button = self.buttons.get(self.current)
        if button is None:
            button = next(iter(self.buttons.values()), None)
        return button.grab_focus() if button is not None else False


class Banner(Gtk.Button):
    """A task banner, Android's: an icon, the task, its progress, a chevron.

    A on it opens what it is about (``on_activate``); the line under it is
    the progress, hidden while the task does not know its total.
    """

    def __init__(self, icon_name="emblem-synchronizing-symbolic", on_activate=None):
        super().__init__()
        self.add_css_class("bp-banner")
        self.on_activate = on_activate
        column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        column.set_valign(Gtk.Align.CENTER)
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        self.icon = Gtk.Image.new_from_icon_name(icon_name)
        row.append(self.icon)
        self.title_label = Gtk.Label(xalign=0.0)
        self.title_label.add_css_class("bp-banner-title")
        self.title_label.set_ellipsize(Pango.EllipsizeMode.END)
        row.append(self.title_label)
        self.detail_label = Gtk.Label(xalign=0.0)
        self.detail_label.add_css_class("bp-banner-detail")
        self.detail_label.set_hexpand(True)
        self.detail_label.set_ellipsize(Pango.EllipsizeMode.END)
        row.append(self.detail_label)
        chevron = Gtk.Label(label="›")
        chevron.add_css_class("bp-row-chevron")
        row.append(chevron)
        column.append(row)
        self.progress = Gtk.ProgressBar()
        self.progress.set_visible(False)
        column.append(self.progress)
        self.set_child(column)
        self.connect("clicked", lambda _b: self.on_activate() if self.on_activate else None)

    def show(self, title, detail=None, fraction=None):
        self.title_label.set_label(title or "")
        self.detail_label.set_label(f"· {detail}" if detail else "")
        if fraction is None:
            self.progress.set_visible(False)
        else:
            self.progress.set_fraction(max(0.0, min(1.0, float(fraction))))
            self.progress.set_visible(True)


def empty_state(icon_name, text):
    """Android's empty pane: an icon on a tile and one line under it."""
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
    box.add_css_class("bp-empty")
    box.set_halign(Gtk.Align.CENTER)
    box.set_valign(Gtk.Align.CENTER)
    box.set_vexpand(True)
    tile = Gtk.Box()
    tile.add_css_class("bp-empty-icon")
    tile.set_halign(Gtk.Align.CENTER)
    image = Gtk.Image.new_from_icon_name(icon_name)
    image.set_hexpand(True)
    image.set_halign(Gtk.Align.CENTER)
    tile.append(image)
    box.append(tile)
    label = Gtk.Label(label=text)
    label.set_wrap(True)
    label.set_justify(Gtk.Justification.CENTER)
    box.append(label)
    box.label = label
    return box


def page_heading(title, subtitle=None):
    """A big page title ("Shelf", "Settings") with its line under it."""
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
    box.title_label = Gtk.Label(label=title, xalign=0.0)
    box.title_label.add_css_class("bp-page-title")
    box.title_label.set_ellipsize(Pango.EllipsizeMode.END)
    box.append(box.title_label)
    box.subtitle_label = Gtk.Label(label=subtitle or "", xalign=0.0)
    box.subtitle_label.add_css_class("bp-page-subtitle")
    box.subtitle_label.set_ellipsize(Pango.EllipsizeMode.END)
    box.subtitle_label.set_visible(bool(subtitle))
    box.append(box.subtitle_label)
    return box


def caps(text):
    """A section's small caps title ("APPEARANCE", "ACCEPTED FORMATS")."""
    label = Gtk.Label(label=(text or "").upper(), xalign=0.0)
    label.add_css_class("bp-caps")
    return label


def eyebrow(text):
    label = Gtk.Label(label=text, xalign=0.0)
    label.add_css_class("bp-eyebrow")
    return label


def crumb(parts):
    """``Library › Super Nintendo``: every part but the last dimmed."""
    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
    parts = [part for part in parts if part]
    for index, part in enumerate(parts):
        last = index == len(parts) - 1
        label = Gtk.Label(label=part)
        label.add_css_class("bp-crumb" if last else "bp-crumb-dim")
        label.set_ellipsize(Pango.EllipsizeMode.END)
        box.append(label)
        if not last:
            sep = Gtk.Label(label="›")
            sep.add_css_class("bp-crumb-dim")
            box.append(sep)
    return box


def note(text):
    label = Gtk.Label(label=text, xalign=0.0)
    label.add_css_class("bp-note")
    label.set_wrap(True)
    label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
    return label


def body(text):
    label = Gtk.Label(label=text, xalign=0.0)
    label.add_css_class("bp-body")
    label.set_wrap(True)
    label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
    return label


def button(label, on_click=None, suggested=False, destructive=False):
    widget = Gtk.Button(label=label)
    widget.add_css_class("bp-button")
    if suggested:
        widget.add_css_class("suggested-action")
    if destructive:
        widget.add_css_class("destructive-action")
    if on_click is not None:
        widget.connect("clicked", lambda _b: on_click())
    return widget


class BigPage(Adw.NavigationPage):
    """A Big Picture page: the safe inset, a top bar, a body, no header bar.

    Pages are pushed on the shell's navigation view; B pops them. A page that
    wants the pad to land somewhere sensible overrides ``focus_default``.
    """

    #: The context the navigator reports while focus is inside this page,
    #: one of the ``CTX_BP_*`` names in ``ui/navigation.py``.
    context = "bp-page"

    def __init__(self, shell, title, crumbs=None, tag=None):
        super().__init__()
        self.shell = shell
        self.win = shell.win
        self.set_title(title)
        if tag:
            self.set_tag(tag)
        self.frame = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self.frame.add_css_class("bp-safe")
        self.frame.set_vexpand(True)
        self.top_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=24)
        self.crumb_host = Gtk.Box()
        self.crumb_host.set_hexpand(True)
        self.set_crumbs([title] if crumbs is None else crumbs)
        self.top_bar.append(self.crumb_host)
        self.top_bar.append(shell.make_status_box())
        self.frame.append(self.top_bar)
        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self.body.set_vexpand(True)
        self.frame.append(self.body)
        self.set_child(self.frame)

    def set_crumbs(self, parts):
        child = self.crumb_host.get_first_child()
        if child is not None:
            self.crumb_host.remove(child)
        self.crumb_host.append(crumb(parts))

    def scrolled(self, child):
        """``child`` in a vertical scroller that fills the body."""
        scroller = Gtk.ScrolledWindow()
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_vexpand(True)
        scroller.set_child(child)
        return scroller

    def focus_default(self):
        """Put the focus on the first thing the pad should land on."""
        return self.child_focus(Gtk.DirectionType.TAB_FORWARD)

    def on_shown(self):
        """The page's transition is over: the shell asks where the focus goes.

        The navigation view moves the focus to the page's first focusable
        when the slide ends, after the shell's idle put it where the page
        wanted; this is the last word. A page that keeps the view's own
        restore on a return (a game's details) overrides it.
        """
        return self.focus_default()

    def hints(self, glyphs, t):
        """The hint pairs for this page, given the pad's glyphs."""
        return [(glyphs["confirm"], t("hints.confirm")), (glyphs["back"], t("hints.back"))]
