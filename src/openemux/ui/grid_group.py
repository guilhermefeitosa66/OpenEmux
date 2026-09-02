"""One page, several grids, spoken to as if it were one (issue #384).

"All", "Favorites" and the collections are grouped by console, and each group
is a ``RomGrid`` of its own -- bound to one console, so it can follow that
console's box-art proportions and, later, draw its cartridge frame (#385). A
single ``Gtk.GridView`` cannot: it lays every item out on one lattice, so the
whole page would keep one card size.

The cost is that "the grid of this page" is no longer one object, and a dozen
places in the window and the navigation controller assume it is. This is the
façade they talk to instead: the same verbs, fanned out over the groups.

The trade-off worth stating plainly: each group's grid is allocated its
natural height inside the page's scroller, so it builds a card per ROM instead
of a screenful. Virtualization (issue #219) still applies *within* a console
page, which is where a single console's few thousand ROMs live; a mixed page
now pays for what it shows. Fixing that needs a layout that can virtualize
across sections, which is a different piece of work from grouping.
"""

import logging

from openemux.ui.rom_card import RomItem, item_for_widget

logger = logging.getLogger(__name__)


class GridSection:
    """One console's group: its header, its grid, and the box holding both."""

    def __init__(self, console, grid, container, header, set_count=None):
        self.console = console
        self.grid = grid
        self.container = container
        self.header = header
        #: Writes the header's game count; the search changes it.
        self._set_count = set_count

    def set_visible(self, visible):
        self.container.set_visible(bool(visible))

    def update_count(self):
        if self._set_count is not None:
            self._set_count(self.grid.count())


class GridGroup:
    """The grids of one scope, with the surface of a single ``RomGrid``.

    Only the verbs the window and the navigation controller actually use are
    here; anything reached per-grid (artwork refreshes, cartridge frames) goes
    through :meth:`grids` instead.
    """

    #: Same contract as RomGrid: GridSelection and the window ask so they can
    #: tell a card from the page under the pointer.
    card_class = RomItem

    #: How a caller tells a group from a single grid. A name check is not
    #: enough -- every Gtk.Widget already answers to a surprising number of
    #: names, and RomGrid is one.
    is_group = True

    def __init__(self, on_selection_changed=None):
        #: Filled by :meth:`add_section` as the page is built -- the grids need
        #: the group to exist before they do, so they can report into it.
        self.sections = []
        self.compact = False
        #: No single console: this page is several of them.
        self.console = None
        self.on_selection_changed = on_selection_changed

    def add_section(self, section):
        self.sections.append(section)
        return section

    # ----- the grids ------------------------------------------------------
    def grids(self):
        return [section.grid for section in self.sections]

    def consoles(self):
        return [section.console for section in self.sections]

    def visible_grids(self):
        """The grids of the groups the search has not emptied."""
        return [s.grid for s in self.sections if s.container.get_visible()]

    def grid_after(self, grid):
        """The next group's grid, or None at the bottom of the page."""
        return self._neighbour(grid, +1)

    def grid_before(self, grid):
        """The previous group's grid, or None at the top of the page."""
        return self._neighbour(grid, -1)

    def _neighbour(self, grid, step):
        grids = self.visible_grids()
        if grid not in grids:
            return None
        index = grids.index(grid) + step
        if not 0 <= index < len(grids):
            return None
        return grids[index]

    def holds_widget(self, widget):
        """Whether ``widget`` is one of this page's grids.

        Deliberately not ``contains``: every ``Gtk.Widget`` already has one,
        taking a point, so a name check against a plain grid would have found
        GTK's and called it with the wrong arguments.

        The navigation controller walks up from the focused widget to decide
        whether focus is "in the grid"; with several of them the question is
        no longer an identity check.
        """
        return any(widget is grid for grid in self.grids())

    def grid_for_item(self, item):
        """The grid an entry or a card belongs to, or None."""
        entry = item.entry if isinstance(item, RomItem) else item
        if entry is None:
            return None
        for grid in self.grids():
            if entry in grid.entries():
                return grid
        return None

    # ----- what the page contains -----------------------------------------
    def entries(self):
        return [entry for grid in self.grids() for entry in grid.entries()]

    def visible_entries(self):
        return [entry for grid in self.grids() for entry in grid.visible_entries()]

    def count(self):
        return sum(grid.count() for grid in self.grids())

    # ----- filtering ------------------------------------------------------
    def set_filter(self, query="", only_missing_artwork=False):
        """Filter every group, and hide the ones the search leaves empty.

        A header over no games is exactly the state the grouping exists to
        avoid, so it goes with its group and comes back when the search is
        cleared.
        """
        for section in self.sections:
            section.grid.set_filter(query, only_missing_artwork=only_missing_artwork)
            section.update_count()
            section.set_visible(bool(section.grid.visible_entries()))

    # ----- selection ------------------------------------------------------
    def selected_roms(self):
        return [rom for grid in self.grids() for rom in grid.selected_roms()]

    def clear_selection(self):
        for grid in self.grids():
            grid.clear_selection()

    def select_all(self):
        for grid in self.grids():
            grid.select_all()

    def toggle_select_all(self):
        # The page's own tri-state, not each group's: Ctrl+A on a page where
        # one group is fully selected must still select the rest.
        if self.selected_roms() and len(self.selected_roms()) == self.count():
            self.clear_selection()
        else:
            self.select_all()

    def sync_visible_selection(self):
        for grid in self.grids():
            grid.sync_visible_selection()

    def note_cursor(self, item, keep_anchor=False):
        grid = self.grid_for_item(item)
        if grid is not None:
            grid.note_cursor(item, keep_anchor=keep_anchor)

    def begin_range_from(self, item):
        grid = self.grid_for_item(item)
        if grid is not None:
            grid.begin_range_from(item)

    def extend_selection_to(self, item, additive=False):
        # A range lives inside the group it was started in: the anchor is an
        # index over that grid's visible entries.
        grid = self.grid_for_item(item)
        if grid is not None:
            grid.extend_selection_to(item, additive=additive)

    def toggle_item(self, item):
        grid = self.grid_for_item(item)
        if grid is not None:
            grid.toggle_item(item)

    def select_item(self, item):
        grid = self.grid_for_item(item)
        if grid is not None:
            grid.select_item(item)

    def on_child_selection_changed(self, _roms=None):
        """One group's selection moved; the page reports all of them.

        Each grid tells its own callback about its own ROMs, and the window
        keeps one list for the whole page -- so without this, selecting in the
        second group silently dropped what was picked in the first.
        """
        if self.on_selection_changed:
            self.on_selection_changed(self.selected_roms())

    # ----- focus ----------------------------------------------------------
    @staticmethod
    def item_for_widget(widget):
        return item_for_widget(widget)

    def focus_first_card(self):
        for grid in self.grids():
            if grid.focus_first_card():
                return True
        return False

    def focus_restore(self):
        """Come back to the group the user was last in, else the first one."""
        for grid in self.grids():
            if grid.has_focus_memory() and grid.focus_restore():
                return True
        return self.focus_first_card()

    # ----- per-ROM refreshes ----------------------------------------------
    def refresh_rom_frame(self, rom):
        return any(grid.refresh_rom_frame(rom) for grid in self.grids())

    def refresh_rom_artwork(self, rom, fade=False):
        return any(grid.refresh_rom_artwork(rom, fade=fade) for grid in self.grids())
