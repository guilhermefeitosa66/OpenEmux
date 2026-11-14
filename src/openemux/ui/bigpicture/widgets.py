"""The pieces every Big Picture page is made of.

Rows a D-pad walks (a switch, a choice, a number, a text field, an action),
tiles for the home rows and the quick menu, the console rail, the hint bar
and the page frame with its safe inset. Every one is a real ``Gtk.Button``
or a box of them, so GTK's own focus chain, the window's ``.keynav-active``
ring and the navigator's ``activate`` all work without special cases.
"""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk, Pango

from openemux.ui.console_icons import console_texture

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


class Tile(Gtk.Button):
    """A big square-ish button: a badge or icon, a name, a count under it."""

    def __init__(self, name, count=None, badge=None, texture=None, icon_name=None,
                 on_activate=None, style=None, wide=False):
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
        box.set_halign(Gtk.Align.START if wide else Gtk.Align.CENTER)
        box.set_valign(Gtk.Align.CENTER)
        self.badge = make_badge(badge, texture, icon_name)
        box.append(self.badge)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        text.set_valign(Gtk.Align.CENTER)
        self.name_label = Gtk.Label(label=name)
        self.name_label.add_css_class("bp-tile-name")
        # Two lines before an ellipsis: "Jogados recentemente" and "Back to
        # desktop" are longer than a tile is wide, and a cut name is worse
        # than a taller tile.
        self.name_label.set_wrap(True)
        self.name_label.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self.name_label.set_lines(2)
        self.name_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.name_label.set_max_width_chars(16)
        self.name_label.set_justify(Gtk.Justification.LEFT if wide else Gtk.Justification.CENTER)
        self.name_label.set_xalign(0.0 if wide else 0.5)
        text.append(self.name_label)
        self.count_label = Gtk.Label(label=count or "")
        self.count_label.add_css_class("bp-tile-count")
        self.count_label.set_visible(bool(count))
        self.count_label.set_xalign(0.0 if wide else 0.5)
        text.append(self.count_label)
        box.append(text)
        self.set_child(box)
        self.connect("clicked", lambda _b: self.on_activate() if self.on_activate else None)

    def set_count(self, count):
        self.count_label.set_label(count or "")
        self.count_label.set_visible(bool(count))


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


class RailTile(Gtk.Button):
    """One stop on the console rail."""

    def __init__(self, scope_id, name, badge_text=None, texture=None, icon_name=None,
                 style=None):
        super().__init__()
        self.scope_id = scope_id
        self.add_css_class("bp-rail-tile")
        self.add_css_class("flat")
        if style:
            self.add_css_class(style)
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        box.set_valign(Gtk.Align.CENTER)
        box.append(make_badge(badge_text, texture, icon_name))
        # Not ellipsized: inside the rail's scroller a tile is allocated its
        # minimum width, and an ellipsizable label's minimum is the ellipsis.
        self.name_label = Gtk.Label(label=name)
        box.append(self.name_label)
        self.set_child(box)

    def set_current(self, current):
        if current:
            self.add_css_class("bp-current")
        else:
            self.remove_css_class("bp-current")


class Rail(Gtk.Box):
    """The console rail: every library scope in a row, one of them current.

    ``on_select(scope_id)`` fires when a tile is activated or the shoulders
    move the current one. The current tile is marked and scrolled into view.
    """

    def __init__(self, on_select, shoulder_labels=("LB", "RB")):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.on_select = on_select
        self.tiles = []
        self.current_id = None
        self.left_shoulder = Gtk.Label(label=shoulder_labels[0])
        self.left_shoulder.add_css_class("bp-shoulder")
        self.left_shoulder.set_valign(Gtk.Align.CENTER)
        self.append(self.left_shoulder)
        self.scroller = Gtk.ScrolledWindow()
        self.scroller.set_policy(Gtk.PolicyType.EXTERNAL, Gtk.PolicyType.NEVER)
        self.scroller.set_hexpand(True)
        self.strip = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.scroller.set_child(self.strip)
        self.append(self.scroller)
        self.right_shoulder = Gtk.Label(label=shoulder_labels[1])
        self.right_shoulder.add_css_class("bp-shoulder")
        self.right_shoulder.set_valign(Gtk.Align.CENTER)
        self.append(self.right_shoulder)

    def set_shoulder_labels(self, left, right):
        self.left_shoulder.set_label(left)
        self.right_shoulder.set_label(right)

    def set_entries(self, entries):
        """``entries``: ``(scope_id, name, badge_text, texture, icon_name, style)``."""
        for tile in self.tiles:
            self.strip.remove(tile)
        self.tiles = []
        for scope_id, name, badge_text, texture, icon_name, style in entries:
            tile = RailTile(scope_id, name, badge_text, texture, icon_name, style)
            tile.connect("clicked", self._on_tile_clicked)
            self.strip.append(tile)
            self.tiles.append(tile)
        self.mark_current(self.current_id)

    def ids(self):
        return [tile.scope_id for tile in self.tiles]

    def tile_for(self, scope_id):
        for tile in self.tiles:
            if tile.scope_id == scope_id:
                return tile
        return None

    def mark_current(self, scope_id):
        """Highlight ``scope_id`` without selecting it (the page did)."""
        self.current_id = scope_id
        for tile in self.tiles:
            tile.set_current(tile.scope_id == scope_id)
        tile = self.tile_for(scope_id)
        if tile is not None:
            GLib.idle_add(self._scroll_to, tile)

    def _scroll_to(self, tile):
        adjustment = self.scroller.get_hadjustment()
        allocation = tile.get_allocation()
        if allocation.width <= 0:
            return GLib.SOURCE_REMOVE
        page = adjustment.get_page_size()
        target = allocation.x + allocation.width / 2 - page / 2
        adjustment.set_value(max(0.0, min(target, adjustment.get_upper() - page)))
        return GLib.SOURCE_REMOVE

    def select(self, scope_id):
        if scope_id is None or scope_id == self.current_id:
            return False
        if self.tile_for(scope_id) is None:
            return False
        self.mark_current(scope_id)
        self.on_select(scope_id)
        return True

    def move(self, delta):
        """The shoulders: the previous or next stop, wrapping around."""
        ids = self.ids()
        if not ids:
            return False
        index = ids.index(self.current_id) if self.current_id in ids else 0
        return self.select(ids[(index + delta) % len(ids)])

    def focus_current(self):
        tile = self.tile_for(self.current_id) or (self.tiles[0] if self.tiles else None)
        if tile is None:
            return False
        return tile.grab_focus()

    def _on_tile_clicked(self, tile):
        self.select(tile.scope_id)


class HintBar(Gtk.Box):
    """The bar along the bottom: what the pad's buttons do right now."""

    def __init__(self):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=28)
        self.add_css_class("bp-hints")
        self.set_valign(Gtk.Align.END)
        self.context_label = Gtk.Label(xalign=0.0)
        self.context_label.add_css_class("bp-hint")
        self.context_label.set_hexpand(True)
        self.context_label.set_ellipsize(Pango.EllipsizeMode.END)
        self.append(self.context_label)
        self.slots = []
        for _ in range(MAX_HINTS):
            slot = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
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
            self.append(slot)
            self.slots.append((slot, key, text))

    def set_context(self, text):
        self.context_label.set_label(text or "")

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


def rail_entry_for_scope(scope_id, name, kind, texture=None):
    """A rail or tile description for a library scope.

    ``kind`` is ``"all"``, ``"favorites"``, ``"recent"``, ``"collection"`` or
    ``"console"``; the styling and the badge follow it.
    """
    if kind == "all":
        return (scope_id, name, "ALL", None, None, "bp-all")
    if kind == "favorites":
        return (scope_id, name, "★", None, None, "bp-favorites")
    if kind == "recent":
        return (scope_id, name, None, None, "document-open-recent-symbolic", None)
    if kind == "collection":
        return (scope_id, name, None, None, "user-bookmarks-symbolic", None)
    if texture is None:
        texture = console_texture(scope_id)
    if texture is not None:
        return (scope_id, name, None, texture, None, None)
    return (scope_id, name, console_badge_text(scope_id), None, None, None)


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
        self.set_crumbs(crumbs or [title])
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
