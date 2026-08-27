"""What is selected on a ROM grid, and the band the pointer draws over it.

Mouse, keyboard and gamepad all drive the same pure `SelectionModel`
(`core/selection.py`); this is the layer between that model, which counts in
indices over the *visible* entries, and the cards on screen, which are
recycled and mostly not there. The search filter changes the visible set, so
the model is re-seeded whenever it does -- skipping that is how a selection
desyncs into indices for a list that no longer exists.

The rubber band belongs here for the same reason: it selects by rectangle
rather than by index, and its result has to be adopted back into the model so
a Shift-range right after behaves as if the band had used it.

Two hundred and fifty lines of `ui/grid.py` (issue #238). It reads the grid
through a small interface -- ``entries()``, ``visible_entries()``,
``bound_cards()`` and the widget itself, for coordinates and for queueing a
redraw -- and never touches the list model or the factory.
"""

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, Graphene, Gtk

from openemux.core.selection import SelectionModel

#: How far the pointer may travel between press and release and still count as
#: a click on empty space rather than the beginning of a drag.
CLICK_SLOP_PX = 8

BAND_FILL = "rgba(53, 132, 228, 0.18)"
BAND_EDGE = "rgba(53, 132, 228, 0.75)"


class GridSelection:
    """The selection of one `RomGrid`, and its rubber band.

    ``grid`` must provide ``entries()``, ``visible_entries()``,
    ``bound_cards()`` and ``card_class``, and be the widget the band is drawn
    in. ``on_changed`` is called with the selected ROMs whenever the set moves.
    """

    def __init__(self, grid, on_changed=None):
        self.grid = grid
        self.on_changed = on_changed
        self._model = SelectionModel(0)
        #: Identity of the visible list the model was last seeded from.
        self._key = None
        #: (x, y, w, h) in grid space while a band is being dragged.
        self._band = None
        self._band_origin = None
        self._band_base = ()
        #: Every on-screen card's rectangle, frozen for the length of a drag.
        self._band_bounds = []
        #: What the band gestures are attached to; see :meth:`attach`.
        self._host = None
        self._press_at = None

    # ----- the model over the visible entries ------------------------------
    def _model_and_entries(self):
        """The model, re-seeded when the visible set changed (search filter)."""
        entries = self.grid.visible_entries()
        key = tuple(id(entry) for entry in entries)
        if key != self._key:
            self._key = key
            self._model.reset(len(entries))
            self._model.replace(
                [index for index, entry in enumerate(entries) if entry.selected]
            )
        return self._model, entries

    def _paint(self, model, entries):
        self._apply({entries[index] for index in model.selected})

    def _apply(self, entries):
        chosen = set(entries)
        changed = False
        for entry in self.grid.entries():
            wanted = entry in chosen
            if entry.selected != wanted:
                entry.selected = wanted
                card = self.grid.card_for(entry)
                if card is not None:
                    card.set_selected(wanted)
                changed = True
        if changed and self.on_changed:
            self.on_changed(self.selected_roms())

    def _entry_for(self, target):
        """Accept an entry or the card showing one; the callers mix both."""
        if isinstance(target, self.grid.card_class):
            return target.entry
        return target

    def _index_of(self, item):
        """``(model, entries, index)``, or ``None`` when it is not visible."""
        entry = self._entry_for(item)
        model, entries = self._model_and_entries()
        if entry not in entries:
            return None
        return model, entries, entries.index(entry)

    # ----- the verbs -------------------------------------------------------
    def selected_roms(self):
        return [entry.rom for entry in self.grid.entries() if entry.selected]

    def any_selected(self):
        return any(entry.selected for entry in self.grid.entries())

    def clear(self):
        model, entries = self._model_and_entries()
        model.clear()
        self._paint(model, entries)

    def select_all(self):
        model, entries = self._model_and_entries()
        model.select_all()
        self._paint(model, entries)

    def toggle_select_all(self):
        """Select every visible ROM, or clear when everything already is."""
        model, entries = self._model_and_entries()
        if model.all_selected():
            model.clear()
        else:
            model.select_all()
        self._paint(model, entries)

    def sync_visible(self):
        """Re-seed the selection model after the visible set changed.

        Filtering and skipping this is how selection desyncs: the model would
        still hold indices into the previous visible list.
        """
        model, entries = self._model_and_entries()
        self._paint(model, entries)

    def toggle_entry(self, entry, ctrl=True, shift=False):
        """A card's click gesture: Ctrl toggles, Shift ranges (issue #78).

        A plain click (no modifier) does not touch the selection -- it
        launches, elsewhere -- but it does move the anchor, so a Shift+click
        right after ranges from the game the user just clicked, the way a
        file manager roots ranges at the last click.
        """
        found = self._index_of(entry)
        if found is None:
            return
        model, entries, index = found
        if shift and ctrl:
            model.extend_additive(index)
        elif shift:
            model.extend(index)
        elif ctrl:
            model.toggle(index)
        else:
            model.move_cursor(index)
            return
        self._paint(model, entries)

    def extend_to(self, item, additive=False):
        """Shift+arrows: grow the range from the anchor to ``item``."""
        found = self._index_of(item)
        if found is None:
            return
        model, entries, index = found
        if additive:
            model.extend_additive(index)
        else:
            model.extend(index)
        self._paint(model, entries)

    def begin_range_from(self, item):
        """Root a keyboard Shift-range at the focused card (issue #78).

        Plain arrows move the *focus* without the model hearing about it, so
        without this the first Shift+arrow would range from wherever the
        anchor last was -- some earlier click -- instead of from the card the
        user is standing on, the way a file manager ranges. Called with the
        pre-move focus: when it differs from the model's cursor a new Shift
        sequence is starting there and the anchor re-roots; when it matches,
        the sequence is already running and the anchor must hold so the range
        keeps growing from the same root.
        """
        found = self._index_of(item)
        if found is None:
            return
        model, _entries, index = found
        if index != model.cursor:
            model.move_cursor(index)

    def toggle_item(self, item):
        """Ctrl+Space / gamepad Ⓐ in selection mode: flip one card."""
        self.toggle_entry(self._entry_for(item))

    def select_item(self, item):
        """Make ``item`` the whole selection (entering gamepad selection mode)."""
        found = self._index_of(item)
        if found is None:
            return
        model, entries, index = found
        model.select(index)
        self._paint(model, entries)

    def note_cursor(self, item, keep_anchor=False):
        """Follow plain/Ctrl movement so the next Shift range roots correctly."""
        found = self._index_of(item)
        if found is None:
            return
        model, _entries, index = found
        model.move_cursor(index, keep_anchor=keep_anchor)

    def _adopt_view(self):
        """Adopt a selection made outside the model (the rubber band)."""
        model, entries = self._model_and_entries()
        model.replace([index for index, entry in enumerate(entries) if entry.selected])

    # ----- the rubber band --------------------------------------------------
    def attach(self, *_args):
        """Put the rubber band on the whole page, not just the cards.

        The grid packs to the top and left and its own margins hold the slack
        the column maths leaves over, so a good deal of a page's empty space is
        outside it -- and a band naturally starts from there. The scroller is
        what covers all of it.

        Pages keep their ScrolledWindow across re-renders while the grid is
        rebuilt, so the previous grid's gestures are dropped before these
        attach; leaving them on would keep that grid, its cards and their
        textures alive (issue #218).

        A press in the *gap between two cards* reaches here too, because the
        item wrappers deny presses -- see RomGrid._on_factory_setup.
        """
        grid = self.grid
        scroller = grid.get_ancestor(Gtk.ScrolledWindow)
        if scroller is None:
            return
        # A GtkGridView is a scrollable, so the ScrolledWindow gives it the
        # viewport directly rather than wrapping it in a GtkViewport. The
        # ancestor lookup keeps working either way.
        host = grid.get_ancestor(Gtk.Viewport) or scroller
        self._host = host

        previous = getattr(host, "_openemux_band_gesture", None)
        if previous is not None:
            host.remove_controller(previous)
        drag = Gtk.GestureDrag()
        drag.set_button(Gdk.BUTTON_PRIMARY)
        drag.connect("drag-begin", self._on_begin)
        drag.connect("drag-update", self._on_update)
        drag.connect("drag-end", self._on_end)
        host.add_controller(drag)
        host._openemux_band_gesture = drag

        # A stationary press never reliably reaches drag-begin, so the plain
        # click on empty space -- which must clear the selection, like a file
        # manager -- gets its own click gesture on the same host.
        previous_click = getattr(host, "_openemux_clear_gesture", None)
        if previous_click is not None:
            host.remove_controller(previous_click)
        click = Gtk.GestureClick()
        click.set_button(Gdk.BUTTON_PRIMARY)
        click.connect("pressed", self._on_press)
        click.connect("released", self._on_release)
        host.add_controller(click)
        host._openemux_clear_gesture = click

    def _to_grid_coords(self, x, y):
        """Host space -> grid space (the band maths live in grid space)."""
        if self._host is None or self._host is self.grid:
            return x, y
        ok, point = self._host.compute_point(self.grid, Graphene.Point().init(x, y))
        return (point.x, point.y) if ok else (x, y)

    def _on_press(self, _gesture, _n_press, x, y):
        self._press_at = (x, y)

    def _on_release(self, gesture, _n_press, x, y):
        """A plain click on empty page space clears the selection.

        Not after a drag (that is the rubber band, whose result must survive
        its own release), not with Ctrl/Shift held (selection gestures), and
        only on true background (no card under the pointer).
        """
        pressed_at = self._press_at
        self._press_at = None
        if pressed_at is not None:
            travelled = abs(x - pressed_at[0]) + abs(y - pressed_at[1])
            if travelled > CLICK_SLOP_PX:
                return
        state = gesture.get_current_event_state()
        if state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK):
            return
        if not self.is_background(x, y):
            return
        if self.any_selected():
            self.clear()

    def is_background(self, x, y):
        """True when (x, y) -- in host space -- is empty page, not a card.

        The scrollbars count as "not background" too: a drag on one must keep
        scrolling, never start a band.
        """
        host = self._host or self.grid
        target = host.pick(x, y, Gtk.PickFlags.DEFAULT)
        while target is not None and target is not host:
            if isinstance(target, (self.grid.card_class, Gtk.Scrollbar)):
                return False
            target = target.get_parent()
        return True

    def _on_begin(self, gesture, start_x, start_y):
        if not self.is_background(start_x, start_y):
            gesture.set_state(Gtk.EventSequenceState.DENIED)
            return
        state = gesture.get_current_event_state()
        # Ctrl keeps what was already picked, so a band can be added to it.
        self._band_base = (
            tuple(e for e in self.grid.entries() if e.selected)
            if state & Gdk.ModifierType.CONTROL_MASK
            else ()
        )
        self._band_origin = self._to_grid_coords(start_x, start_y)
        self._band = None
        self._freeze_bounds()
        if not self._band_base:
            # A plain press on empty space clears -- which also makes a plain
            # *click* there clear the selection, the file-manager behavior.
            self._apply(())

    def _on_update(self, _gesture, offset_x, offset_y):
        if self._band_origin is None:
            return
        start_x, start_y = self._band_origin
        self._band = (
            min(start_x, start_x + offset_x),
            min(start_y, start_y + offset_y),
            abs(offset_x),
            abs(offset_y),
        )
        self._apply(list(self._band_base) + self.entries_in_band())
        self.grid.queue_draw()

    def _on_end(self, _gesture, _offset_x, _offset_y):
        self._band = None
        self._band_origin = None
        self._band_base = ()
        self._band_bounds = []
        # The band bypassed the model; adopt its result so a Shift range or
        # Ctrl toggle right after behaves as if the band had used it.
        self._adopt_view()
        self.grid.queue_draw()

    def _freeze_bounds(self):
        """Freeze every on-screen card's rectangle for the length of one drag.

        The cards that exist are the right set to ask: the band is dragged
        with the pointer, so it never leaves the viewport, and everything the
        viewport shows is realized. Nothing relayouts while the pointer is
        down, so the bounds cannot move -- and asking GTK for them per card on
        every drag-update was a compute_bounds call per card per motion event
        (issue #231).
        """
        frozen = []
        for entry, card in self.grid.bound_cards():
            ok, bounds = card.compute_bounds(self.grid)
            if not ok:
                continue
            frozen.append(
                (
                    entry,
                    bounds.get_x(),
                    bounds.get_y(),
                    bounds.get_width(),
                    bounds.get_height(),
                )
            )
        self._band_bounds = frozen

    def entries_in_band(self):
        if self._band is None:
            return []
        return entries_intersecting(self._band, self._band_bounds)

    def draw(self, snapshot):
        """Paint the band, if one is being dragged."""
        if self._band is None:
            return
        x, y, width, height = self._band
        if width < 1 or height < 1:
            return
        fill = Gdk.RGBA()
        fill.parse(BAND_FILL)
        edge = Gdk.RGBA()
        edge.parse(BAND_EDGE)
        snapshot.append_color(fill, Graphene.Rect().init(x, y, width, height))
        for rect in (
            (x, y, width, 1),
            (x, y + height - 1, width, 1),
            (x, y, 1, height),
            (x + width - 1, y, 1, height),
        ):
            snapshot.append_color(edge, Graphene.Rect().init(*rect))


def entries_intersecting(band, bounds):
    """Which of ``bounds`` the ``(x, y, w, h)`` ``band`` touches, in order.

    Pure rectangle maths, so the rule the band selects by can be checked
    without a display: a card counts as caught when the two rectangles
    overlap at all, not when the band covers it.
    """
    bx, by, bw, bh = band
    return [
        entry
        for entry, x, y, width, height in bounds
        if x < bx + bw and bx < x + width and y < by + bh and by < y + height
    ]
