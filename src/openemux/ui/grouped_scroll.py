"""The scrollable body of a grouped page: every group's grid kept virtual.

"All", "Favorites" and the collections stack one ``RomGrid`` per console
under a header (issue #384). They used to sit in a plain vertical box inside
the page's ``Gtk.ScrolledWindow`` -- which wraps a box in a ``Gtk.Viewport``,
so no grid ever saw the page's scroll. A ``GtkGridView`` only builds the cards
around its own anchor, about thirty rows' worth, and that anchor followed an
adjustment nothing moved: past those rows a big console's group was allocated
as blank cells, and the games "disappeared" (issue #511).

This container is the scroller's child instead. It is ``Gtk.Scrollable``, so
the scroller hands it the page's adjustments directly, and it hands each grid
only the slice of the viewport the grid covers, together with a vertical
adjustment set to where that slice falls inside the grid. Each grid then
builds exactly the cards on screen, as it does on a console page, where it is
the scroller's own child.

The page is the only thing that scrolls. A grid moving its own adjustment
-- GTK does that whenever a card takes the keyboard focus -- is put back to
its slice, and the page is scrolled to the focused card instead, from the
card's index (``reveal_position``). Letting the two scroll each other made the
page drift away from the card while focus walked down a tall group (issue
#511, QA round 1).

A grid that is off screen is still allocated -- one pixel, just outside the
viewport, where the clip hides it -- rather than hidden: hiding a widget
unmaps it, and a grid attaches its selection and its focus watcher on map and
dismisses its popovers on unmap, which scrolling must never trigger.
"""

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gdk, GObject, Gtk

from openemux.core.grouped_layout import item_span, scroll_to_show, slice_for


class GroupedScroll(Gtk.Widget, Gtk.Scrollable):
    """Headers and grids, top to bottom, scrolled as one page."""

    __gtype_name__ = "OpenEmuxGroupedScroll"

    hscroll_policy = GObject.Property(
        type=Gtk.ScrollablePolicy, default=Gtk.ScrollablePolicy.MINIMUM
    )
    vscroll_policy = GObject.Property(
        type=Gtk.ScrollablePolicy, default=Gtk.ScrollablePolicy.MINIMUM
    )

    def __init__(self):
        super().__init__()
        self._hadjustment = None
        self._vadjustment = None
        self._vadjustment_handler = None
        #: ``(header, grid)`` per group, in page order.
        self._sections = []
        #: Each child's ``(top, height)`` in the content, from the last layout.
        self._layout = {}
        #: Set during a layout pass, when the page's own scroll is not news.
        self._allocating = False
        self.set_overflow(Gtk.Overflow.HIDDEN)
        # Not a bound method: the page can be destroyed after its Python
        # wrapper is gone, and the handler must not need it.
        self.connect("destroy", _unparent_children)

    # -- Gtk.Scrollable ----------------------------------------------------

    @GObject.Property(type=Gtk.Adjustment)
    def hadjustment(self):
        return self._hadjustment

    @hadjustment.setter
    def hadjustment(self, adjustment):
        self._hadjustment = adjustment
        self.queue_allocate()

    @GObject.Property(type=Gtk.Adjustment)
    def vadjustment(self):
        return self._vadjustment

    @vadjustment.setter
    def vadjustment(self, adjustment):
        if self._vadjustment is not None and self._vadjustment_handler is not None:
            self._vadjustment.disconnect(self._vadjustment_handler)
        self._vadjustment = adjustment
        self._vadjustment_handler = None
        if adjustment is not None:
            self._vadjustment_handler = adjustment.connect(
                "value-changed", self._on_page_scrolled
            )
        self.queue_allocate()

    def do_get_border(self):
        return False, None

    # -- the groups --------------------------------------------------------

    def add_section(self, header, grid):
        """Append one group: its header, then its grid."""
        header.set_parent(self)
        grid.set_parent(self)
        # The grid's own adjustment: this widget sets it to the slice on screen.
        grid.set_vadjustment(Gtk.Adjustment())
        self._sections.append((header, grid))

    def _children(self):
        for header, grid in self._sections:
            yield header
            yield grid

    # -- layout ------------------------------------------------------------

    def do_measure(self, orientation, for_size):
        minimum = natural = 0
        for child in self._children():
            if not child.get_visible():
                continue
            child_min, child_nat, _, _ = child.measure(orientation, for_size)
            if orientation == Gtk.Orientation.HORIZONTAL:
                minimum = max(minimum, child_min)
                natural = max(natural, child_nat)
            else:
                minimum += child_min
                natural += child_nat
        return minimum, natural, -1, -1

    def _lay_out(self, width):
        """Each visible child's ``(top, height)`` in the content, and the total."""
        layout = {}
        top = 0
        for child in self._children():
            if not child.get_visible():
                continue
            # Never below the child's own minimum: a grid still holding the
            # column count of a wider window says so before it retunes.
            at = max(width, child.measure(Gtk.Orientation.HORIZONTAL, -1)[0])
            height = child.measure(Gtk.Orientation.VERTICAL, at)[1]
            layout[child] = (top, height)
            top += height
        return layout, top

    def do_size_allocate(self, width, height, baseline):
        layout, total = self._lay_out(width)
        self._layout = layout
        if self._hadjustment is not None:
            self._hadjustment.configure(0, 0, width, width * 0.1, width * 0.9, width)
        vadj = self._vadjustment
        self._allocating = True
        try:
            if vadj is None:
                # Not in a scroller (yet): laid out from the top, unscrolled.
                self._allocate_children(width, height, 0)
                return
            scroll = max(0, min(vadj.get_value(), total - height))
            vadj.configure(scroll, 0, max(total, height), height * 0.1, height * 0.9, height)
            self._allocate_children(width, height, scroll)
            # A card that took focus during the pass may have had the page
            # revealed to it: lay the children out again at that scroll, so
            # they never stay where the adjustment no longer is.
            if vadj.get_value() != scroll:
                self._allocate_children(width, height, vadj.get_value())
        finally:
            self._allocating = False

    def _allocate_children(self, width, height, scroll):
        """Allocate every child at ``scroll``."""
        for header, grid in self._sections:
            if header in self._layout:
                top, child_height = self._layout[header]
                header.size_allocate(_rect(0, top - scroll, width, child_height), -1)
            if grid not in self._layout:
                continue
            top, child_height = self._layout[grid]
            # Only the grid's content is sliced. Its margins are handed back
            # around the slice, or GTK would take them off every slice -- and
            # a slice cut by the top edge would start a margin too low.
            margin_top, margin_bottom = grid.get_margin_top(), grid.get_margin_bottom()
            top += margin_top
            content_height = max(0, child_height - margin_top - margin_bottom)
            visible = slice_for(top, content_height, scroll, height)
            adjustment = grid.get_vadjustment()
            if visible is None:
                # Off screen: one pixel just past the edge it is beyond, kept
                # mapped (see the module docstring) and clipped away.
                above = top + content_height <= scroll
                y, slice_height = (-1, 1) if above else (height, 1)
                inner = max(0, content_height - 1) if above else 0
            else:
                y, slice_height, inner = visible
            adjustment.configure(
                inner, 0, max(content_height, slice_height), 1, slice_height, slice_height
            )
            grid.size_allocate(
                _rect(
                    0,
                    y - margin_top,
                    width,
                    slice_height + margin_top + margin_bottom,
                ),
                -1,
            )
            # A focused card makes GTK scroll the grid to it as the grid is
            # allocated. The scrolling is the page's: back to the slice (GTK
            # follows the adjustment, and lays its cards out again there).
            if abs(adjustment.get_value() - inner) >= 1:
                adjustment.set_value(inner)

    def _on_page_scrolled(self, *_args):
        if not self._allocating:
            self.queue_allocate()

    def do_snapshot(self, snapshot):
        for child in self._children():
            if child.get_visible():
                self.snapshot_child(child, snapshot)

    # -- focus -------------------------------------------------------------

    def reveal_position(self, grid, position):
        """Scroll the page so item ``position`` of ``grid`` is on screen.

        The grids of a grouped page hold one column count (``RomGrid`` sets
        its minimum and maximum together), so the item's place follows from
        its index alone.
        """
        vadj = self._vadjustment
        layout = self._layout.get(grid)
        if vadj is None or layout is None:
            return False
        top, child_height = layout
        margin_top = grid.get_margin_top()
        content_height = max(0, child_height - margin_top - grid.get_margin_bottom())
        model = grid.get_model()
        count = model.get_n_items() if model is not None else 0
        item_top, item_height = item_span(
            position, grid.get_max_columns(), count, content_height
        )
        target = scroll_to_show(
            vadj.get_value(), vadj.get_page_size(), top + margin_top + item_top, item_height
        )
        if target != vadj.get_value():
            vadj.set_value(target)
        return True


def _unparent_children(widget):
    """Let go of every child, walked from GTK's side rather than ``_sections``."""
    child = widget.get_first_child()
    while child is not None:
        child.unparent()
        child = widget.get_first_child()


def _rect(x, y, width, height):
    rect = Gdk.Rectangle()
    rect.x, rect.y, rect.width, rect.height = int(x), int(y), int(width), int(height)
    return rect
