"""The cover grid: what it shows, how it is laid out, and what is selected.

`RomGrid` is a `Gtk.GridView` over a filtered list model, so a library of
several thousand ROMs costs a screenful of widgets rather than one per game
(issue #219). It owns the model and the filter, the column packing GTK's own
does not do, the keyboard and gamepad focus plumbing, and the selection --
including the rubber band drawn over it.

The card it recycles is `ui/rom_card.py`; the sizes both measure themselves
against are in `ui/card_layout.py` (issue #238). The names those two used to
live under here are re-exported, since the window, the artwork manager and the
tests already import them from this module.
"""

import logging

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gdk, GLib, Gio, Gtk

from openemux.core import cartridge_render
from openemux.core.library_view import (
    DEFAULT_ZOOM,
    is_grid_view,
    list_thumb_size,
    normalize_view_mode,
    normalize_zoom,
    renders_cartridge,
    scale_length,
    scale_spacing,
)
from openemux.ui.card_layout import (  # noqa: F401  (re-exported)
    ACTIVATION_DEBOUNCE_US,
    CARTRIDGE_RENDER_SCALE,
    CONSOLE_COVER_ASPECTS,
    DEFAULT_COVER_ASPECT,
    DEFAULT_ITEM_SIZE,
    FIXED_ITEM_WIDTH,
    GRID_MARGIN,
    GRID_SPACING,
    LIST_MARGIN,
    LIST_ROW_SPACING,
    FixedSizePicture,
    card_size_for,
    cartridge_frame_for,
    cartridge_frame_svg,
    columns_and_slack,
    cover_size_for_console,
    default_item_size,
)
from openemux.ui.context_menu import dismiss_context_popover
from openemux.ui.grid_selection import GridSelection
from openemux.ui.rom_card import (  # noqa: F401  (re-exported)
    CardContext,
    RomEntry,
    RomItem,
    entry_matches,
    item_for_widget,
)

logger = logging.getLogger(__name__)


class RomGrid(Gtk.GridView):
    """The library grid: a GtkGridView over the page's ROMs.

    Virtualized on purpose (issue #219). The previous GtkFlowBox built one
    live widget per ROM -- roughly twenty widgets each -- and mapped every one
    of them, so opening "All consoles" on a few thousand games spent seconds
    building widgets before the first frame and then held a decoded texture
    per card for as long as the page existed. A GridView builds only what is
    on screen and re-binds those few cards as the view scrolls.

    What that costs, and where it is paid:

    * per-ROM state moved to ``RomEntry`` -- selection and the resolved
      artwork state would otherwise follow a recycled widget to another game;
    * filtering is a ``Gtk.FilterListModel`` over that model rather than a
      walk that hides child wrappers;
    * focus memory remembers the *entry*, and restores it through
      ``scroll_to``, because the widget it was on may be showing something
      else by then;
    * the rubber band reads the bounds of the cards that exist, which is
      sound because the band is drawn inside the viewport and everything the
      viewport shows is realized.
    """

    #: The widget a bound item is. GridSelection asks so it can tell a card
    #: from the empty page under the pointer without importing the card.
    card_class = RomItem

    #: One console's grid, not a page of several (see ui/grid_group.py).
    is_group = False

    def __init__(
        self,
        console,
        roms,
        on_launch_callback,
        on_toggle_favorite,
        on_reveal_in_files,
        on_choose_cover,
        on_remove_cover,
        is_favorite,
        has_local_cover,
        t,
        roms_dir,
        ui_settings=None,
        mixed_consoles=False,
        on_rename_rom=None,
        on_delete_rom=None,
        on_selection_changed=None,
        context_services=None,
        frame_color_for_rom=None,
        band_host=None,
    ):
        # Before anything else: the GObject has to exist before this widget
        # can be configured. The model and the factory are attached at the
        # end, once everything they call back into is in place.
        super().__init__()
        self.console = console
        self.context_services = context_services
        self.mixed_consoles = mixed_consoles
        # Resolves a ROM's cartridge shell color (issue #79); None keeps every
        # card on the authored shell.
        self._frame_color_for_rom = frame_color_for_rom
        # Where the rubber band and the click-on-empty-space gesture live.
        # Normally the page's scroller, so a drag anywhere on the page starts
        # a band; a grid that shares its scroller with the other groups of a
        # mixed page (issue #384) hands its own widget instead, or the last
        # group to be mapped would take the gesture from all the others.
        self.band_host = band_host
        self.on_launch_callback = on_launch_callback
        self.roms_dir = roms_dir
        self.ui_settings = ui_settings or {}
        self.on_selection_changed = on_selection_changed
        # Focus memory: coming back from the sidebar restores this game. The
        # entry, not the widget -- the widget may be showing another game by
        # then (issue #219).
        self._focused_entry = None
        # One selection shared by every input method (issue #78), and the
        # rubber band that is another way of driving it (issue #238).
        self.selection = GridSelection(self, on_changed=on_selection_changed)
        # Coalesces the burst of artwork-state callbacks into one filter pass.
        self._artwork_filter_pending = False
        # Columns are recomputed from the viewport width; see _retune_columns.
        self._column_state = None
        self._measured_card_width = None
        # (path, monotonic microseconds) of the last launch this grid started.
        self._last_activation = (None, 0)
        # The cards that exist right now, by the entry each is showing.
        self._bound = {}
        # Focus is followed from the window; see _watch_root_focus.
        self._focused_card = None
        self._focus_root = None
        self._root_focus_handler = None

        self.view_mode = normalize_view_mode(self.ui_settings.get("view_mode"))
        self.compact = not is_grid_view(self.view_mode)
        # Zoom scales the artwork and, with it, the gaps: bigger cards further
        # apart, smaller cards packed tighter -- the grid density the user is
        # really asking for when they zoom out.
        self.zoom = normalize_zoom(self.ui_settings.get("zoom", DEFAULT_ZOOM))
        self._spacing = scale_spacing(
            LIST_ROW_SPACING if self.compact else GRID_SPACING, self.zoom
        )
        # GtkGridView has no row/column spacing of its own: the horizontal gap
        # comes from a cell being one gap wider than the card centred in it,
        # and the vertical gap from half of it on each card. The grid's own
        # margin gives back the half-gap that leaves at the four edges.
        self._card_margin = self._spacing // 2
        self._margin = max(0, (LIST_MARGIN if self.compact else GRID_MARGIN) - self._card_margin)

        # One fixed card size for the whole page, so the grid lays out on an
        # even lattice. Per console it follows that console's box-art
        # proportions; pages mixing consoles have no single shape to follow, so
        # they use a uniform square box and centre each cover inside it.
        cover_size = (
            default_item_size(self.zoom)
            if mixed_consoles
            else cover_size_for_console(console, self.zoom)
        )
        # The card shape comes from the frame art itself: fixed width, and the
        # height that keeps the cartridge's own proportions. Since issue #384 a
        # mixed page is one grid per console, so this reaches "All", "Favorites"
        # and the collections too (issue #385).
        cartridge_frame_path = cartridge_frame_for(
            console, self.view_mode, mixed_consoles=mixed_consoles, compact=self.compact
        )
        if cartridge_frame_path:
            frame = cartridge_render.load_frame(cartridge_frame_path)
            cover_size = frame.size_for_width(scale_length(FIXED_ITEM_WIDTH, self.zoom))

        if self.compact:
            # Rows show the box art itself, never a cartridge: a frame drawn at
            # thumbnail size is an unreadable smudge.
            cover_size = list_thumb_size(cover_size, self.zoom)

        self._card_size = card_size_for(cover_size, mixed_consoles, compact=self.compact)
        # The console's authored shell; per-ROM colors swap in a variant of it.
        self._base_frame_path = cartridge_frame_path

        self._card_ctx = CardContext(
            t=t,
            roms_dir=roms_dir,
            cover_size=cover_size,
            card_size=self._card_size,
            mixed_consoles=mixed_consoles,
            compact=self.compact,
            zoom=self.zoom,
            cartridge=bool(cartridge_frame_path),
            frame_for_rom=self._frame_path_for_rom,
            context_services=context_services,
            on_launch=self._launch_rom,
            on_toggle_favorite=on_toggle_favorite,
            on_reveal_in_files=on_reveal_in_files,
            on_choose_cover=on_choose_cover,
            on_remove_cover=on_remove_cover,
            is_favorite=is_favorite,
            has_local_cover=has_local_cover,
            on_rename_rom=on_rename_rom,
            on_delete_rom=on_delete_rom,
            on_toggle_selection=self.selection.toggle_entry,
            on_artwork_state=self._on_entry_artwork_state,
        )

        # -- the model ------------------------------------------------------
        self._entries = [RomEntry(rom) for rom in roms]
        self._by_path = {entry.path: entry for entry in self._entries}
        self._store = Gio.ListStore.new(RomEntry)
        self._store.splice(0, 0, self._entries)
        self._query = ""
        self._only_missing_artwork = False
        self._filter = Gtk.CustomFilter.new(self._match_entry)
        self._filtered = Gtk.FilterListModel(model=self._store, filter=self._filter)
        self._visible_cache = None
        self._filtered.connect("items-changed", self._on_filtered_changed)

        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._on_factory_setup)
        factory.connect("bind", self._on_factory_bind)
        factory.connect("unbind", self._on_factory_unbind)
        factory.connect("teardown", self._on_factory_teardown)

        self.set_factory(factory)
        self.set_model(Gtk.NoSelection(model=self._filtered))
        # Zeroes the theme's padding on the item wrappers, so a cell is exactly
        # the card and the gaps are exactly _spacing.
        self.add_css_class("rom-grid")
        self.set_margin_top(self._margin)
        self.set_margin_bottom(self._margin)
        self.set_margin_start(self._margin)
        self.set_margin_end(self._margin)
        # One column until the viewport is known. The default is seven, which
        # would lay the page out in a shape it is about to lose -- and bind a
        # screenful of cards for that shape first.
        self.set_max_columns(1)
        self.set_min_columns(1)

        # Menu key / Shift+F10 opens the focused card's context menu, and
        # Return launches it: the keyboard counterparts of the pointer. Both
        # used to come free with GtkFlowBox's own child activation.
        key = Gtk.EventControllerKey()
        key.connect("key-pressed", self._on_grid_key_pressed)
        self.add_controller(key)

        # A page switch replaces the whole grid. A context menu still up is
        # parented to a card that is about to be disposed, so close it while
        # its anchor is still alive (issue #275). "unmap" and not "unroot":
        # GtkWidget's unroot is a vfunc with no signal behind it, and
        # connecting to a name GObject does not know raises -- which is how
        # this took the whole grid down with it (issue #286).
        self.connect("map", self._on_map)
        self.connect("unmap", self._on_unmap)

    def _on_map(self, *_args):
        # Both want an ancestry that only exists once the grid is in a window.
        self._watch_root_focus()
        self.selection.attach()

    def _on_unmap(self, *_args):
        self._unwatch_root_focus()
        dismiss_context_popover()

    # -- the model ---------------------------------------------------------

    def _match_entry(self, entry):
        """The filter predicate, run by GtkFilterListModel per entry."""
        return entry_matches(entry, self._query, self._only_missing_artwork)

    def set_filter(self, query="", only_missing_artwork=False):
        """Restrict the page to what the search and the artwork filter allow.

        The window decides *what* the filter is; matching happens here, over
        the model, because a virtualized grid has no widget to hide for a ROM
        that is off screen.
        """
        query = (query or "").lower()
        only_missing = bool(only_missing_artwork)
        if (query, only_missing) == (self._query, self._only_missing_artwork):
            # Still re-seed: a card's artwork state may have settled since.
            self.sync_visible_selection()
            return
        self._query = query
        self._only_missing_artwork = only_missing
        self._filter.changed(Gtk.FilterChange.DIFFERENT)
        self.sync_visible_selection()

    def _on_filtered_changed(self, *_args):
        self._visible_cache = None

    def entries(self):
        """Every ROM on this page, in model order."""
        return list(self._entries)

    def count(self):
        """How many ROMs this grid is showing -- what the filter lets through."""
        return len(self.visible_entries())

    def visible_entries(self):
        """The ROMs the filter currently lets through, in visual order."""
        if self._visible_cache is None:
            self._visible_cache = [
                self._filtered.get_item(index)
                for index in range(self._filtered.get_n_items())
            ]
        return self._visible_cache

    def card_for(self, entry):
        """The card showing ``entry`` right now, or None when it is off screen."""
        return self._bound.get(entry)

    def card_at(self, position):
        """The card at ``position`` in the visible order, when it is realized."""
        visible = self.visible_entries()
        if not 0 <= position < len(visible):
            return None
        return self._bound.get(visible[position])

    def _position_of(self, entry):
        if entry is None:
            return None
        try:
            return self.visible_entries().index(entry)
        except ValueError:
            return None

    # -- the factory -------------------------------------------------------

    def _on_factory_setup(self, _factory, list_item):
        card = RomItem(self._card_ctx)
        # GtkGridView has no row spacing of its own, so the vertical gap is
        # half of it on each card. The horizontal gap comes from the cell
        # being one gap wider than the card centred in it.
        card.set_margin_top(self._card_margin)
        card.set_margin_bottom(self._card_margin)
        # Neither: GtkListItemWidget claims a press on the whole cell when it
        # is activatable or selectable, and the cell includes the gap around
        # the card -- which would swallow the press that starts a rubber band,
        # and the card's own click gesture with it. Selection and launching
        # are ours anyway; only focus is left to GTK.
        list_item.set_activatable(False)
        list_item.set_selectable(False)
        list_item.set_child(card)

    def _on_factory_bind(self, _factory, list_item):
        card = list_item.get_child()
        entry = list_item.get_item()
        if card is None or entry is None:
            return
        card.bind(entry)
        self._bound[entry] = card
        if self._focused_card is card:
            # It kept the focus through the rebind, so this is where the user
            # stands now.
            self._focused_entry = entry

    def _on_factory_unbind(self, _factory, list_item):
        card = list_item.get_child()
        if card is None:
            return
        entry = card.entry
        if entry is not None and self._bound.get(entry) is card:
            del self._bound[entry]
        card.unbind()

    def _on_factory_teardown(self, _factory, list_item):
        card = list_item.get_child()
        if card is not None:
            entry = card.entry
            if entry is not None and self._bound.get(entry) is card:
                del self._bound[entry]
            card.unbind()
        list_item.set_child(None)

    def _watch_root_focus(self, *_args):
        """Follow focus from the window, not from the cards.

        Focus lands on the list-item wrapper, which is the card's *parent*, so
        a controller on the card never sees it -- and one on the wrapper is not
        an option: GtkGridView recycles those, and adding a controller to one
        from the factory's bind handler crashes the item manager mid-layout
        (it walks tiles whose widgets it is still moving around). The window
        already publishes where focus is, and one signal on it covers every
        card this grid will ever build.

        Connected on map and dropped on unmap: the window outlives the grid,
        and a handler left on it would keep this grid, its cards and their
        textures alive for good -- the leak #218 was about, on a longer-lived
        object.
        """
        root = self.get_root()
        if root is None or self._root_focus_handler is not None:
            return
        self._focus_root = root
        self._root_focus_handler = root.connect(
            "notify::focus-widget", self._on_root_focus_changed
        )
        self._on_root_focus_changed(root, None)

    def _unwatch_root_focus(self):
        if self._root_focus_handler is not None and self._focus_root is not None:
            self._focus_root.disconnect(self._root_focus_handler)
        self._root_focus_handler = None
        self._focus_root = None
        self._focused_card = None

    def _on_root_focus_changed(self, root, _param):
        card = self.item_for_widget(root.get_focus())
        if card is not None and card.ctx is not self._card_ctx:
            card = None  # another page's grid; not ours to paint
        previous = self._focused_card
        if previous is not None and previous is not card:
            previous.set_focus_visual(False)
        self._focused_card = card
        if card is None:
            return
        if card.entry is not None:
            self._focused_entry = card.entry
        card.set_focus_visual(True)

    # -- cartridge shells ----------------------------------------------------

    def _frame_path_for_rom(self, rom):
        """This ROM's shell: the console frame in the ROM's chosen color."""
        if not self._base_frame_path:
            return None
        if self._frame_color_for_rom is None:
            return self._base_frame_path
        color = self._frame_color_for_rom(rom)
        return cartridge_frame_svg(rom["console"], color) or self._base_frame_path

    def refresh_rom_frame(self, rom):
        """Re-resolve one card's shell after its cartridge color changed.

        A ROM with no card on screen needs nothing done: the colour is read
        from the config when its card is next bound.
        """
        entry = self._by_path.get(str(rom.get("path", "")))
        if entry is None or not self._base_frame_path:
            return False
        card = self._bound.get(entry)
        if card is not None:
            card.set_cartridge_frame(self._frame_path_for_rom(entry.rom))
        return True

    def refresh_rom_artwork(self, rom, fade=False):
        """Re-fetch one card's artwork after a cover or label file changed."""
        entry = self._by_path.get(str(rom.get("path", "")))
        if entry is None:
            return False
        card = self._bound.get(entry)
        if card is not None:
            card._refresh_cover_after_change(fade=fade)
        else:
            # Off screen: the state is stale until something shows it again,
            # and the cover cache is keyed by mtime, so the next bind re-reads
            # the new file by itself.
            entry.has_artwork = None
        return True

    # -- layout ------------------------------------------------------------

    def do_measure(self, orientation, for_size):
        if orientation == Gtk.Orientation.VERTICAL and 0 <= for_size < self._card_size[0]:
            # Asked how tall the page is at a width no card fits in -- which
            # the content stack does for a frame while it swaps pages.
            # GtkGridView divides that width between its columns and measures
            # every card for what is left, so a zero here becomes a screenful
            # of "needs at least 216" warnings and a negative for_size once the
            # card's padding comes off. -1 is the honest answer: the width is
            # not known yet.
            for_size = -1
        minimum, natural, min_baseline, nat_baseline = Gtk.GridView.do_measure(
            self, orientation, for_size
        )
        if orientation == Gtk.Orientation.HORIZONTAL:
            # A width has no baseline, and GTK says so out loud when one is
            # reported. Chaining up through PyGObject hands back whatever was
            # in the out parameters, so they are cleared here.
            min_baseline = nat_baseline = -1
        return minimum, natural, min_baseline, nat_baseline

    def do_size_allocate(self, width, height, baseline):
        if width <= 0 or height <= 0:
            # A degenerate allocation, which the content stack hands out for a
            # frame while it swaps pages. GtkGridView divides its width by its
            # columns, so passing it on gives every card a zero-width cell and
            # a screenful of "needs at least 216" warnings; there is nothing to
            # lay out at this size, and the real allocation follows.
            return
        # Before the chain-up, so the cards are laid out on the column count
        # this width actually calls for. Deciding afterwards means GtkGridView
        # lays the page out twice, and the cards it built for the first shape
        # are allocated an empty cell on the way to the second.
        self._retune_columns(width)
        Gtk.GridView.do_size_allocate(self, width, height, baseline)

    def _retune_columns(self, width=None):
        """Pack the cards left-to-right with fixed gaps, like an icon view.

        GtkGridView splits its width evenly between its columns, so cards
        drift apart as the window widens unless the width divides evenly. The
        fix is to leave it nothing to spread: the number of columns that fit is
        computed here and the leftover handed to the end margin, so the grid is
        allocated exactly ``columns`` cells of one card plus one gap.

        The width fed in is the viewport's, never the reduced one: the end
        margin changes our own allocation, so feeding that back in would make
        the two oscillate. What the margin took is added back below.
        """
        if self.compact:
            # One row per line, and the row itself absorbs the width: there is
            # no slack to hand to the margin.
            return
        available = self._available_width(width)
        if available <= 0:
            return
        columns, slack = columns_and_slack(
            available,
            self._card_allocation_width(),
            len(self._entries),
            spacing=self._spacing,
        )
        filled = max(1, min(columns, len(self._entries) or 1))
        if self._column_state == (filled, slack):
            return
        self._column_state = (filled, slack)
        # Order matters: max_columns must never be asked to sit below
        # min_columns, which GTK refuses.
        if filled >= self.get_min_columns():
            self.set_max_columns(filled)
            self.set_min_columns(filled)
        else:
            self.set_min_columns(filled)
            self.set_max_columns(filled)
        # Deferred: this runs from size-allocate, and changing a margin there
        # re-enters allocation.
        GLib.idle_add(self.set_margin_end, self._margin + slack)

    def _available_width(self, width=None):
        """The width the cells may use: the viewport, less the base margins.

        Never our own reduced allocation fed back in -- the end margin changes
        it, so the two would oscillate. What the allocation is missing is
        exactly the slack parked on that margin, so it is added back.
        """
        if width is None:
            width = self.get_width()
        if width <= 0:
            return 0
        # ``width`` is what is left after our own margins, so the viewport's
        # inner width is that plus both of them -- and the space the cells may
        # use is the viewport's minus the base margin on each side. Only the
        # slack we parked on the end margin has to be added back.
        return width + max(0, self.get_margin_end() - self._margin)

    def _card_allocation_width(self):
        """How wide a card really is, CSS padding included.

        ``_card_size`` is the artwork plus caption; the theme then adds the
        card's own padding on top, so laying columns out on the raw value packs
        them tighter than they fit and the grid wraps a column early.
        """
        if self._measured_card_width is None:
            card = next(iter(self._bound.values()), None)
            if card is None:
                # Before the first card exists; recomputed once one does.
                return self._card_size[0]
            self._measured_card_width = max(
                self._card_size[0], card.measure(Gtk.Orientation.HORIZONTAL, -1)[0]
            )
        return self._measured_card_width

    # -- keyboard / gamepad focus -----------------------------------------

    def _launch_rom(self, rom):
        """Start a game, once per click.

        Activation is on a single click, so a double-click asks twice. The
        second launch is correctly refused -- but the refusal is an error
        toast, so anyone who habitually double-clicks got "a game is already
        running" on every launch (issue #236).
        """
        if rom is None or not self.on_launch_callback:
            return
        path = rom.get("path")
        now = GLib.get_monotonic_time()
        if self._is_repeat_activation(path, now):
            return
        self._last_activation = (path, now)
        self.on_launch_callback(rom)

    def _is_repeat_activation(self, path, now):
        """Whether this activation is the second half of a double-click."""
        last_path, last_at = self._last_activation
        return last_path == path and (now - last_at) < ACTIVATION_DEBOUNCE_US

    def _on_grid_key_pressed(self, _controller, keyval, _keycode, state):
        is_menu_key = keyval == Gdk.KEY_Menu or (
            keyval == Gdk.KEY_F10 and state & Gdk.ModifierType.SHIFT_MASK
        )
        launches = keyval in (
            Gdk.KEY_Return,
            Gdk.KEY_KP_Enter,
            Gdk.KEY_ISO_Enter,
            Gdk.KEY_space,
            Gdk.KEY_KP_Space,
        ) and not (state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK))
        if not (is_menu_key or launches):
            return False
        root = self.get_root()
        card = self.item_for_widget(root.get_focus()) if root else None
        if card is None or card.entry is None:
            return False
        if is_menu_key:
            card.show_context_menu()
        else:
            self._launch_rom(card.rom)
        return True

    @staticmethod
    def item_for_widget(widget):
        """The RomItem for ``widget``, whether it is inside one or wraps one."""
        return item_for_widget(widget)

    def has_focus_memory(self):
        """Whether this grid remembers a card the user was last on.

        A grouped page asks each of its grids in turn, so coming back from the
        sidebar lands in the group the user actually left (issue #384).
        """
        return self._focused_entry is not None

    def focus_first_card(self):
        return self._focus_position(0)

    def focus_last_card(self):
        """The last card the filter lets through; for entering from below."""
        return self._focus_position(len(self.visible_entries()) - 1)

    def focus_restore(self):
        """Focus the last card the user was on, else the first one."""
        position = self._position_of(self._focused_entry)
        if position is not None and self._focus_position(position):
            return True
        return self.focus_first_card()

    def _focus_position(self, position):
        """Focus the card at ``position``, scrolling it into view if need be.

        A card that is off screen has no widget to grab -- that is the whole
        point of a virtualized grid -- so the view is asked to bring it in and
        take the focus with it, and the grab is retried once the item exists.
        """
        visible = self.visible_entries()
        if not 0 <= position < len(visible):
            return False
        entry = visible[position]
        if self._grab_focus_on(entry):
            return True
        self.scroll_to(position, Gtk.ListScrollFlags.FOCUS, None)
        GLib.idle_add(self._grab_focus_when_realized, entry)
        return True

    def _grab_focus_on(self, entry):
        card = self._bound.get(entry)
        wrapper = card.get_parent() if card is not None else None
        if wrapper is None:
            return False
        return wrapper.grab_focus()

    def _grab_focus_when_realized(self, entry):
        """One retry, once the scroll has built the card. Never repeats."""
        self._grab_focus_on(entry)
        return False

    # -- selection ---------------------------------------------------------
    #
    # Mouse, keyboard and gamepad all drive the pure SelectionModel
    # (core/selection.py) through GridSelection, which maps entries to indices
    # over the *visible* ones and paints whichever of them has a card on
    # screen. These stay here because the window and the navigation
    # controller call them on the grid.

    def selected_roms(self):
        return self.selection.selected_roms()

    def clear_selection(self):
        self.selection.clear()

    def select_all(self):
        self.selection.select_all()

    def toggle_select_all(self):
        self.selection.toggle_select_all()

    def sync_visible_selection(self):
        self.selection.sync_visible()

    def extend_selection_to(self, item, additive=False):
        self.selection.extend_to(item, additive=additive)

    def begin_range_from(self, item):
        self.selection.begin_range_from(item)

    def toggle_item(self, item):
        self.selection.toggle_item(item)

    def select_item(self, item):
        self.selection.select_item(item)

    def note_cursor(self, item, keep_anchor=False):
        self.selection.note_cursor(item, keep_anchor=keep_anchor)

    def bound_cards(self):
        """``(entry, card)`` for every card currently on screen.

        The grid recycles cards, so this is a screenful, not the library --
        which is exactly the set the rubber band measures against.
        """
        return list(self._bound.items())

    def _on_entry_artwork_state(self, _entry):
        """A ROM resolved its artwork state; the filter may need re-applying.

        Coalesced onto one idle pass: a page of cards resolves as a burst and
        re-filtering per card would walk the whole page N times (#127).
        """
        if self._artwork_filter_pending:
            return
        self._artwork_filter_pending = True
        GLib.idle_add(self._flush_artwork_filter)

    def _flush_artwork_filter(self):
        self._artwork_filter_pending = False
        if self._only_missing_artwork:
            self._filter.changed(Gtk.FilterChange.DIFFERENT)
            self.sync_visible_selection()
        win = getattr(self.context_services, "win", None)
        if win is not None and hasattr(win, "apply_library_filters"):
            win.apply_library_filters()
        return False

    def do_snapshot(self, snapshot):
        Gtk.GridView.do_snapshot(self, snapshot)
        self.selection.draw(snapshot)
