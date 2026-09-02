"""One ROM card: the widget, its async artwork pipeline, and its model row.

`RomItem` is the card the grid recycles -- cover or cartridge or list row --
and everything that happens to it between binding a ROM and having artwork on
screen: the placeholder, the cover fetch on a worker, the cartridge composite,
the reveal animation, the favourite star, hover, focus and selection.

It was the first eight hundred lines of `ui/grid.py`, ahead of the grid that
recycles it (issue #238). The menu it opens is assembled in
`ui/rom_context.py`; the sizes it is drawn at come from `ui/card_layout.py`.
"""

import logging

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, GObject, Gio, Gtk, Pango

from openemux.core import cartridge_render, cover_cache
from openemux.core.config import COVER_ART_TYPE_BOXART, COVER_ART_TYPE_CARTRIDGE_LABEL
from openemux.core.library_view import list_thumb_column_width, normalize_zoom, scale_length
from openemux.core.paths import display_text
from openemux.core.scraper import COVER_ART, LABEL_ART, fetch_cover
from openemux.core.systems import get_system_display_name
from openemux.ui.card_layout import (
    CARTRIDGE_RENDER_SCALE,
    FixedSizePicture,
    cartridge_frame_svg,
)
from openemux.ui.context_menu import (
    build_context_popover,
    present_context_popover,
    unparent_when_idle,
)
from openemux.ui.rom_context import card_menu_entries

logger = logging.getLogger(__name__)


class RomEntry(GObject.Object):
    """One library row, as the grid's model sees it.

    Everything that has to outlive a *card* lives here. A virtualized grid
    keeps only a screenful of widgets and re-binds them to other games as the
    view scrolls, so state parked on the widget -- whether this game is
    selected, whether its artwork resolved -- would follow the widget to a
    different game (issue #219).

    The lowercased name is precomputed because it is what the search filter
    compares against, once per keystroke per ROM.
    """

    __gtype_name__ = "OpenEmuxRomEntry"

    def __init__(self, rom):
        super().__init__()
        self.rom = rom
        self.path = str(rom.get("path", ""))
        # Escaped where GTK can see it: rom["name"] keeps the filesystem's own
        # bytes for the lookups that need them (issue #214).
        self.display_name = display_text(rom.get("name", ""))
        self.search_name = self.display_name.lower()
        self.selected = False
        # None until the cover fetch resolves; the "without artwork" filter
        # and the badge only act on False (issue #127).
        self.has_artwork = None


def entry_matches(entry, query="", only_missing_artwork=False):
    """Whether a ROM survives the search box and the "no artwork" filter.

    ``query`` is expected already lowercased -- it is compared against the
    name the entry precomputed, once per ROM instead of once per keystroke
    per ROM.
    """
    if query and query not in entry.search_name:
        return False
    if only_missing_artwork and entry.has_artwork is not False:
        # `None` means the fetch has not resolved yet: hide it rather than
        # flash it in and out as state arrives.
        return False
    return True


def item_for_widget(widget):
    """The :class:`RomItem` for ``widget``, whether it is inside one or wraps one.

    Keyboard/gamepad focus sits on the list-item wrapper, whose RomItem is its
    *child*; a pointer press lands on a widget *inside* the RomItem. Both have
    to resolve, so the walk checks downwards at every step and upwards until it
    runs out of parents.

    A module function because the grid, the window, the navigation controller
    and the grid *group* (issue #384) all ask, and only one of them owns a
    grid. ``RomGrid.item_for_widget`` stays as the name the callers already
    use.
    """
    node = widget
    while node is not None:
        if isinstance(node, RomItem):
            return node
        if isinstance(node.get_first_child(), RomItem):
            return node.get_first_child()
        node = node.get_parent()
    return None


class CardContext:
    """What every card on a page shares, resolved once instead of per card.

    A card can no longer be built around one ROM: the factory makes a handful
    of them and re-binds them as the user scrolls. So the constructor takes
    what is true for the whole page -- sizes, callbacks, the view mode -- and
    the ROM arrives later, in ``RomItem.bind``.
    """

    def __init__(
        self,
        *,
        t,
        roms_dir,
        cover_size,
        card_size,
        mixed_consoles,
        compact,
        zoom,
        cartridge,
        frame_for_rom,
        context_services,
        on_launch,
        on_toggle_favorite,
        on_reveal_in_files,
        on_choose_cover,
        on_remove_cover,
        is_favorite,
        has_local_cover,
        on_rename_rom,
        on_delete_rom,
        on_toggle_selection,
        on_artwork_state,
    ):
        self.t = t
        self.roms_dir = roms_dir
        self.cover_size = cover_size
        self.card_size = card_size
        self.mixed_consoles = mixed_consoles
        self.compact = compact
        self.zoom = zoom
        # Whether this page draws cards as cartridges at all. The shell of an
        # individual ROM (its color variant) comes from frame_for_rom.
        self.cartridge = cartridge
        self.frame_for_rom = frame_for_rom
        self.context_services = context_services
        self.on_launch = on_launch
        self.on_toggle_favorite = on_toggle_favorite
        self.on_reveal_in_files = on_reveal_in_files
        self.on_choose_cover = on_choose_cover
        self.on_remove_cover = on_remove_cover
        self.is_favorite = is_favorite
        self.has_local_cover = has_local_cover
        self.on_rename_rom = on_rename_rom
        self.on_delete_rom = on_delete_rom
        self.on_toggle_selection = on_toggle_selection
        self.on_artwork_state = on_artwork_state


class RomItem(Gtk.Box):
    """One card. Built empty, then bound to a ROM -- and re-bound to another.

    Everything below the ``-- binding --`` line is what changes when the same
    widget is handed a different game; everything above it is built once and
    survives every rebind.
    """

    NAME_PREVIEW_LIMIT = 30

    def __init__(self, ctx):
        compact = ctx.compact
        super().__init__(
            orientation=(
                Gtk.Orientation.HORIZONTAL if compact else Gtk.Orientation.VERTICAL
            ),
            spacing=(12 if compact else 8),
        )
        self.ctx = ctx
        self.entry = None
        # Bumped on every bind and every manual refresh: a cover fetch that
        # was in flight when the card moved to another game answers with a
        # stale token and is dropped.
        self._generation = 0
        self.on_launch_callback = ctx.on_launch
        self.on_toggle_favorite = ctx.on_toggle_favorite
        self.on_reveal_in_files = ctx.on_reveal_in_files
        self.on_choose_cover = ctx.on_choose_cover
        self.on_remove_cover = ctx.on_remove_cover
        self.on_rename_rom = ctx.on_rename_rom
        self.on_delete_rom = ctx.on_delete_rom
        # Builds the data-driven submenus (shader, and later core/collection).
        self.context_services = ctx.context_services
        # Selection lives in the grid (it spans cards); the card only reports
        # the ctrl-click that toggles it.
        self.on_toggle_selection = ctx.on_toggle_selection
        self.is_favorite = ctx.is_favorite
        self.has_local_cover = ctx.has_local_cover
        self.t = ctx.t
        self.roms_dir = ctx.roms_dir
        # A compact row is the same card laid out sideways: a thumbnail, the
        # title beside it, and the badges at the far end instead of stacked on
        # the artwork, where they would swallow a 64px thumbnail.
        self.compact = compact
        self.zoom = normalize_zoom(ctx.zoom)
        self.cover_width, self.cover_height = ctx.cover_size
        # When set, the card shows a single pre-rendered image: the cover is
        # already composited into the cartridge, so there is no overlay to
        # stack and no geometry to compute here. Resolved per ROM at bind
        # time, because the shell color is a per-ROM setting (issue #79).
        self.cartridge_frame_path = None
        # Pages that mix consoles cannot size the card to one box art shape, so
        # the cover is centred at its own proportions over a uniform backdrop.
        self.mixed_consoles = ctx.mixed_consoles
        self._backdrop = None
        # Inside a cartridge frame the label sticker is what belongs there, so
        # prefer it and fall back to the box art when none was configured.
        self._art_kinds = (LABEL_ART, COVER_ART) if ctx.cartridge else (COVER_ART,)
        self.add_css_class("rom-card")
        if compact:
            self.add_css_class("rom-row")
        # Fixed card size, so the grid lays out on an even lattice: a cell is
        # this plus one gap, and the card is centred in it.
        self.card_size = ctx.card_size
        self.set_size_request(*self.card_size)
        # Centred rather than START-aligned: the card sits centred inside its
        # cell, which is exactly one gap wider than it. A row is the exception:
        # it spans the viewport, so it fills horizontally.
        self.set_halign(Gtk.Align.FILL if compact else Gtk.Align.CENTER)
        self.set_valign(Gtk.Align.CENTER)
        self.set_hexpand(bool(compact))
        self.set_vexpand(False)

        # Click gesture
        gesture = Gtk.GestureClick()
        # Listen to all mouse buttons (primary + secondary for context menu).
        gesture.set_button(0)
        gesture.connect("released", self.on_click)
        self.add_controller(gesture)

        # Hover effects
        motion = Gtk.EventControllerMotion()
        motion.connect("enter", self._on_hover_enter)
        motion.connect("leave", self._on_hover_leave)
        self.add_controller(motion)

        # Cover art overlay (image + play button on hover)
        self.cover_overlay = Gtk.Overlay()
        self.cover_overlay.set_size_request(self.cover_width, self.cover_height)
        if compact:
            # Pin the thumbnail column: GTK propagates a child's hexpand up, so
            # without this the artwork column absorbs the row's spare width.
            # The width is the column's, not this cover's, so every title in the
            # list starts at the same indent.
            self.cover_overlay.set_size_request(
                list_thumb_column_width(self.zoom), self.cover_height
            )
            self.cover_overlay.set_hexpand(False)
            self.cover_overlay.set_halign(Gtk.Align.START)

        # Cover image (placeholder initially)
        self.cover_image = (
            FixedSizePicture(*self._cover_target_size())
            if (ctx.cartridge or compact)
            else Gtk.Picture()
        )
        self.cover_image.set_size_request(*self._cover_target_size())
        self.cover_image.set_content_fit(
            Gtk.ContentFit.CONTAIN
            if (self.mixed_consoles or ctx.cartridge or compact)
            else Gtk.ContentFit.COVER
        )
        self.cover_image.set_can_shrink(True)
        self.cover_image.add_css_class("rom-cover")
        # Built once and swapped in and out, rather than rebuilt per bind: on
        # a virtualized grid every scroll step would otherwise throw away a
        # small widget tree and build another one just like it.
        self._placeholder = self._build_placeholder()
        self._showing_placeholder = False
        self._setup_cover_host()
        self._show_placeholder()

        # Play button overlay (hidden by default)
        self.play_overlay = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.play_overlay.set_valign(Gtk.Align.FILL)
        self.play_overlay.set_halign(Gtk.Align.FILL)
        self.play_overlay.set_hexpand(True)
        self.play_overlay.set_vexpand(True)
        self.play_overlay.set_size_request(self.cover_width, self.cover_height)
        self.play_overlay.add_css_class("play-overlay")
        self.play_overlay.set_visible(False)

        play_icon = Gtk.Image.new_from_icon_name("media-playback-start-symbolic")
        play_icon.set_pixel_size(scale_length(40, self.zoom))
        play_icon.set_halign(Gtk.Align.CENTER)
        play_icon.set_valign(Gtk.Align.CENTER)
        play_icon.add_css_class("play-icon")
        play_center = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        play_center.set_hexpand(True)
        play_center.set_vexpand(True)
        play_center.set_halign(Gtk.Align.CENTER)
        play_center.set_valign(Gtk.Align.CENTER)
        play_center.append(play_icon)
        self.play_overlay.append(play_center)

        self.cover_overlay.add_overlay(self.play_overlay)

        # Favouriting is one click away, on the card itself. The star stays
        # visible on a favourite (it is the badge that marks it) and otherwise
        # appears on hover, like the menu button on the other corner.
        self.favorite_button = Gtk.Button.new_from_icon_name("starred-symbolic")
        # Pointer-only: a focusable button here would be a focus stop *inside*
        # the card, so an arrow key would step through the badges instead of
        # moving to the next game. Ctrl+D does the same thing from the keyboard.
        self.favorite_button.set_focusable(False)
        self.favorite_button.set_can_focus(False)
        self.favorite_button.add_css_class("rom-menu-button")
        self.favorite_button.add_css_class("circular")
        self.favorite_button.add_css_class("favorite-badge")
        self.favorite_button.set_halign(Gtk.Align.START)
        self.favorite_button.set_valign(Gtk.Align.CENTER if compact else Gtk.Align.START)
        if not compact:
            self.favorite_button.set_margin_top(6)
            self.favorite_button.set_margin_start(6)
        self.favorite_button.connect("clicked", self._on_favorite_button_clicked)
        self._is_favorite_now = False
        if not compact:
            self.cover_overlay.add_overlay(self.favorite_button)

        # "This ROM has no artwork" must be visible in *every* view mode. In
        # the default cartridge shelf a cover-less ROM renders as a blank
        # cartridge rather than the generic placeholder, so nothing
        # distinguished it from one whose art simply had not loaded (#127).
        self.artwork_badge = Gtk.Image.new_from_icon_name("image-missing-symbolic")
        self.artwork_badge.add_css_class("artwork-missing-badge")
        self.artwork_badge.set_tooltip_text(self.t("rom.artwork.missing"))
        self.artwork_badge.set_visible(False)
        self.artwork_badge.set_halign(Gtk.Align.END)
        self.artwork_badge.set_valign(Gtk.Align.END)
        if not compact:
            self.artwork_badge.set_margin_bottom(6)
            self.artwork_badge.set_margin_end(6)
            self.cover_overlay.add_overlay(self.artwork_badge)

        # Right-click is not obvious to everyone, so the same menu is one click
        # away from a button that appears on hover.
        self.menu_button = Gtk.Button.new_from_icon_name("view-more-symbolic")
        # Pointer-only, same as the star: the Menu key opens this menu from the
        # keyboard without turning the button into a focus stop inside the card.
        self.menu_button.set_focusable(False)
        self.menu_button.set_can_focus(False)
        self.menu_button.add_css_class("rom-menu-button")
        self.menu_button.add_css_class("circular")
        self.menu_button.set_halign(Gtk.Align.END)
        self.menu_button.set_valign(Gtk.Align.CENTER if compact else Gtk.Align.START)
        if not compact:
            self.menu_button.set_margin_top(6)
            self.menu_button.set_margin_end(6)
        self.menu_button.set_tooltip_text(self.t("context.more_options"))
        self.menu_button.set_visible(False)
        self.menu_button.connect("clicked", self._on_menu_button_clicked)
        if not compact:
            self.cover_overlay.add_overlay(self.menu_button)

        # List rows carry the inbox idiom: a checkbox at the start of the row,
        # always visible, reflecting and driving this ROM's selection
        # (issue #78). Clicking it must never launch the game.
        self.select_check = None
        if compact:
            self.select_check = Gtk.CheckButton()
            self.select_check.set_valign(Gtk.Align.CENTER)
            self.select_check.set_tooltip_text(self.t("selection.row_checkbox"))
            self._select_check_guard = False
            self.select_check.connect("toggled", self._on_select_check_toggled)
            self.append(self.select_check)

        self.append(self.cover_overlay)

        # A card only has its own width for the title, so the caption is cut to
        # what fits -- which is a function of the zoom, or a zoomed-out card
        # would be stretched wider by its own label. A row has the whole
        # viewport to run the title along and is ellipsized instead.
        self._preview_limit = max(8, int(round(self.NAME_PREVIEW_LIMIT * self.zoom)))

        # ROM name, plus the console it belongs to when the page mixes consoles
        # -- always in a row, where it reads as the platform column.
        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        text_box.set_valign(Gtk.Align.CENTER)
        text_box.set_hexpand(bool(compact))
        label_align = Gtk.Align.START if compact else Gtk.Align.CENTER
        self.name_label = Gtk.Label()
        self.name_label.set_halign(label_align)
        self.name_label.set_xalign(0.0 if compact else 0.5)
        if compact:
            self.name_label.set_ellipsize(Pango.EllipsizeMode.END)
        else:
            self.name_label.set_max_width_chars(self._preview_limit + 3)
            self.name_label.set_ellipsize(Pango.EllipsizeMode.NONE)
        self.name_label.add_css_class("rom-title")
        text_box.append(self.name_label)

        self.console_label = None
        if self.mixed_consoles or compact:
            self.console_label = Gtk.Label()
            self.console_label.set_halign(label_align)
            self.console_label.set_xalign(0.0 if compact else 0.5)
            if not compact:
                self.console_label.set_max_width_chars(self._preview_limit + 3)
            self.console_label.set_ellipsize(Pango.EllipsizeMode.END)
            self.console_label.add_css_class("caption")
            self.console_label.add_css_class("dim-label")
            self.console_label.add_css_class("rom-console")
            text_box.append(self.console_label)

        self.append(text_box)

        if compact:
            # Badges at the end of the row: the star stays put (it marks a
            # favourite) and the menu button appears on hover, as on a card.
            badges = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
            badges.set_valign(Gtk.Align.CENTER)
            badges.append(self.favorite_button)
            badges.append(self.menu_button)
            self.append(badges)

        self._context_popover = None
        self._action_group = None
        self._fade_next_apply = False

    # -- binding -----------------------------------------------------------

    @property
    def rom(self):
        """The ROM this card is showing, or None while it is unbound."""
        return self.entry.rom if self.entry is not None else None

    @property
    def selected(self):
        return bool(self.entry is not None and self.entry.selected)

    def bind(self, entry):
        """Show ``entry``'s game on this card.

        Every piece of per-ROM state is re-established here, because the card
        may be arriving from a completely different game: whatever the last
        bind left behind is wrong now.
        """
        self.entry = entry
        self._generation += 1
        rom = entry.rom
        self.cartridge_frame_path = self.ctx.frame_for_rom(rom)

        full_name = entry.display_name
        self.set_tooltip_text(full_name)
        self.name_label.set_label(
            full_name if self.compact else self._truncate_name(full_name, self._preview_limit)
        )
        self.name_label.set_tooltip_text(full_name)
        if self.console_label is not None:
            self.console_label.set_label(get_system_display_name(rom["console"]))

        self._sync_favorite_button(self.is_favorite(rom))
        self.artwork_badge.set_visible(entry.has_artwork is False)
        self.set_selected(entry.selected)
        # Any hover/focus affordance belongs to the card that just left.
        self.remove_css_class("rom-card-hover")
        self.play_overlay.set_visible(False)
        self.menu_button.set_visible(False)
        self.set_opacity(1.0)
        self._fade_next_apply = False
        # Drops the previous game's texture: on a page of thousands this is
        # what keeps memory bounded by the screenful rather than the library.
        self._show_placeholder()
        self._start_cover_fetch()

    def unbind(self):
        """Release the game this card was showing, texture included."""
        if self._context_popover is not None:
            # Its anchor is about to show another game. Closing it emits
            # "closed", which clears the reference and unparents it.
            self._context_popover.popdown()
        self._generation += 1
        self.entry = None
        self.set_selected(False)
        self.remove_css_class("rom-card-hover")
        self.play_overlay.set_visible(False)
        self.menu_button.set_visible(False)
        self._show_placeholder()

    def _start_cover_fetch(self):
        entry = self.entry
        if entry is None:
            return
        token = self._generation
        fetch_cover(
            entry.rom,
            self.roms_dir,
            lambda rom, cover_path: self._on_cover_fetched(entry, token, rom, cover_path),
            kinds=self._art_kinds,
        )

    def _is_stale(self, token):
        return token != self._generation

    @classmethod
    def _truncate_name(cls, name, limit=None):
        limit = cls.NAME_PREVIEW_LIMIT if limit is None else limit
        if len(name) <= limit:
            return name
        return f"{name[:limit]}..."

    def _build_placeholder(self):
        """The styled "no artwork yet" box shown before (and instead of) a cover."""
        placeholder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        placeholder.set_valign(Gtk.Align.CENTER)
        placeholder.set_halign(Gtk.Align.CENTER)
        placeholder.set_hexpand(True)
        placeholder.set_vexpand(True)
        placeholder.set_size_request(*self._cover_target_size())
        placeholder.add_css_class("rom-cover-placeholder")

        icon = Gtk.Image.new_from_icon_name("applications-games-symbolic")
        icon.set_pixel_size(scale_length(48, self.zoom))
        icon.set_halign(Gtk.Align.CENTER)
        icon.set_valign(Gtk.Align.CENTER)
        icon.add_css_class("placeholder-icon")
        placeholder_center = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        placeholder_center.set_hexpand(True)
        placeholder_center.set_vexpand(True)
        placeholder_center.set_halign(Gtk.Align.CENTER)
        placeholder_center.set_valign(Gtk.Align.CENTER)
        placeholder_center.append(icon)

        # The empty cover is exactly where someone notices art is missing, so
        # the fix starts there rather than through the context menu. Reuses
        # the artwork manager that already ships a name search and a CRC32
        # search -- no new dialog, and no editing filenames by hand (#127).
        if not self.compact and self.context_services is not None:
            search_btn = Gtk.Button(label=self.t("rom.artwork.search"))
            search_btn.add_css_class("flat")
            search_btn.add_css_class("artwork-search-button")
            # Pointer-only, like the other in-card buttons: a focus stop here
            # would make an arrow key step through the card's insides.
            search_btn.set_focusable(False)
            search_btn.set_can_focus(False)
            search_btn.set_halign(Gtk.Align.CENTER)
            search_btn.connect("clicked", self._on_search_artwork_clicked)
            placeholder_center.append(search_btn)

        placeholder.append(placeholder_center)
        return placeholder

    def _show_placeholder(self):
        self.cover_image.set_visible(False)
        # Explicitly dropped rather than left for the next bind to overwrite:
        # the paintable is the card's share of the library's memory, and an
        # unbound card must not keep it.
        self.cover_image.set_paintable(None)
        self.cover_image.set_size_request(*self._cover_target_size())
        if not self._showing_placeholder:
            self._set_cover_widget(self._placeholder)
            self._showing_placeholder = True

    def _show_cover_image(self):
        if self._showing_placeholder:
            self._set_cover_widget(self.cover_image)
            self._showing_placeholder = False
        self.cover_image.set_visible(True)

    def _on_cover_fetched(self, entry, token, rom, cover_path):
        """Called on a worker thread once the cover path is resolved.

        The decode happens *here*, not in the idle callback. It used to be
        handed to the main thread, which serialised every JPEG/PNG decode and
        rescale in the library onto the one thread that cannot afford it
        (issue #128). Only assigning the result to a widget has to be on the
        main loop, and that is all the idle callback does now.

        The answer is recorded on the *entry* even when the card has already
        moved on to another game: it is that ROM's artwork state, which the
        "without artwork" filter needs whether or not anything is showing it.
        """
        # Recorded before the composite branch, so it is right in cartridge
        # mode too -- where a cover-less ROM still takes the normal image
        # path and would otherwise look identical to one with art (#127).
        entry.has_artwork = bool(cover_path)
        GLib.idle_add(self._sync_artwork_state, entry, token)
        if self._is_stale(token):
            # The card is showing a different game now. The decode below would
            # be thrown away, so it is not started at all.
            return
        if self.cartridge_frame_path:
            # Compose the cover into the cartridge (cached on disk, so this
            # only costs anything the first time). A ROM with no cover renders
            # as a blank cartridge instead of the generic icon, keeping the
            # shelf consistent.
            composite = cartridge_render.render_cartridge(
                cover_path,
                self.cartridge_frame_path,
                rom["console"],
                rom["name"],
                width=self.cover_width,
                scale=CARTRIDGE_RENDER_SCALE,
            )
            if composite:
                # Full resolution: the composite is already the card's shape,
                # and the full-size art is what keeps it sharp on HiDPI.
                pixbuf = cover_cache.load_cover(str(composite))
                if pixbuf is not None:
                    GLib.idle_add(self._apply_cover_pixbuf, token, pixbuf, True)
                    return
        if cover_path:
            width, height = self._cover_target_size()
            pixbuf = cover_cache.load_cover(cover_path, width, height)
            if pixbuf is not None:
                GLib.idle_add(self._apply_cover_pixbuf, token, pixbuf, False)
                return
        # No cover, or one that would not decode -- cover_cache logs the
        # latter, so a corrupt file is no longer indistinguishable from a
        # missing one.
        GLib.idle_add(self._restore_placeholder, token)

    def _restore_placeholder(self, token):
        if self._is_stale(token) or self._is_abandoned():
            return False
        self._show_placeholder()
        return False

    def _on_search_artwork_clicked(self, _button):
        rom = self.rom
        if self.context_services is None or rom is None:
            return
        logger.info("rom artwork: search from empty cover rom=%s", rom.get("name"))
        self.context_services.win.open_artwork_manager(rom, COVER_ART)

    def _sync_artwork_state(self, entry, token):
        """Reflect the resolved artwork state (main thread only)."""
        if self._is_abandoned():
            return False
        if not self._is_stale(token):
            self.artwork_badge.set_visible(entry.has_artwork is False)
        if self.ctx.on_artwork_state:
            self.ctx.on_artwork_state(entry)
        return False

    def _is_abandoned(self):
        """Has this card left the window while its cover was being fetched?

        Switching playlist replaces the whole grid, and the covers already in
        flight for the page just left keep finishing and keep scheduling main
        thread work for cards nobody can see. A few quick switches between
        large playlists queued hundreds of those, all competing with the page
        actually on screen (issue #291). The decode itself is not wasted: it
        lands in the shared cover cache, so coming back is faster.
        """
        return self.get_root() is None

    def _apply_cover_pixbuf(self, token, pixbuf, full_resolution):
        """Hand an already-decoded cover to the widget (main thread only)."""
        if self._is_stale(token) or self._is_abandoned():
            return False
        try:
            if full_resolution:
                self.cover_image.set_paintable(Gdk.Texture.new_for_pixbuf(pixbuf))
            else:
                if self.mixed_consoles and not self.compact:
                    # Shrink the widget to the scaled art so the rounded
                    # corners and shadow hug the cover, not the empty area
                    # around it. Not in a row: there the thumbnail box is a
                    # column shared with every other row, and resizing it per
                    # cover would stagger the titles.
                    self.cover_image.set_size_request(
                        pixbuf.get_width(), pixbuf.get_height()
                    )
                self.cover_image.set_pixbuf(pixbuf)
            self._show_cover_image()
            if self._fade_next_apply:
                self._fade_next_apply = False
                self._animate_cover_reveal()
        except Exception:
            logger.exception("cover: could not attach art to the card")
        return False  # Don't repeat idle callback

    def _cover_target_size(self):
        if self.compact:
            # The shared column, so a wide cover can use all of it and a narrow
            # one is centred in it rather than shrinking the slot.
            return list_thumb_column_width(self.zoom), self.cover_height
        return self.cover_width, self.cover_height

    def _setup_cover_host(self):
        # A row never gets the backdrop: it exists to fill a uniform *card* box
        # on pages that mix consoles, and inside a horizontal row its expanding
        # child makes the whole thumbnail column stretch, shoving every title to
        # a different indent.
        if self.mixed_consoles and not self.compact:
            # Uniform box: the cover keeps its own shape and the leftover area
            # is filled by a subtle backdrop instead of cropping the art.
            self._backdrop = Gtk.Box()
            self._backdrop.set_size_request(self.cover_width, self.cover_height)
            self._backdrop.add_css_class("rom-cover-backdrop")
            self.cover_overlay.set_child(self._backdrop)
            self._set_cover_widget(self.cover_image)
            return

        self.cover_overlay.set_child(self.cover_image)

    def _set_cover_widget(self, widget):
        if self._backdrop is not None:
            child = self._backdrop.get_first_child()
            if child is widget:
                return
            if child:
                self._backdrop.remove(child)
            # The expands hand the child the whole box; the aligns then centre it
            # inside that space. Without the expands a Gtk.Box packs it left.
            widget.set_hexpand(True)
            widget.set_vexpand(True)
            widget.set_halign(Gtk.Align.CENTER)
            widget.set_valign(Gtk.Align.CENTER)
            self._backdrop.append(widget)
            return
        self.cover_overlay.set_child(widget)

    def _sync_favorite_button(self, is_favorite):
        self._is_favorite_now = bool(is_favorite)
        self.favorite_button.set_icon_name(
            "starred-symbolic" if is_favorite else "non-starred-symbolic"
        )
        self.favorite_button.set_tooltip_text(
            self.t("context.favorite.remove") if is_favorite else self.t("context.favorite.add")
        )
        if is_favorite:
            self.favorite_button.add_css_class("favorite-on")
        else:
            self.favorite_button.remove_css_class("favorite-on")
        # A favourite says so even when the pointer is elsewhere.
        self.favorite_button.set_visible(
            self._is_favorite_now or self.has_css_class("rom-card-hover")
        )

    def _on_favorite_button_clicked(self, _button):
        self.toggle_favorite()

    def set_selected(self, selected):
        """Paint the selection. The flag itself lives on the entry."""
        selected = bool(selected)
        if selected:
            self.add_css_class("rom-card-selected")
        else:
            self.remove_css_class("rom-card-selected")
        # Keep the list-row checkbox honest without re-entering the toggle
        # handler (the guard breaks the feedback loop).
        if self.select_check is not None and self.select_check.get_active() != selected:
            self._select_check_guard = True
            self.select_check.set_active(selected)
            self._select_check_guard = False

    def _on_select_check_toggled(self, check):
        if self._select_check_guard or self.entry is None:
            return
        if self.on_toggle_selection:
            # A checkbox is a plain toggle: no range semantics.
            self.on_toggle_selection(self.entry, True, False)

    def _on_hover_enter(self, controller, x, y):
        if self.entry is None:
            return
        self.play_overlay.set_visible(True)
        self.menu_button.set_visible(True)
        self.favorite_button.set_visible(True)
        self.add_css_class("rom-card-hover")

    def _on_hover_leave(self, controller):
        self.play_overlay.set_visible(False)
        # Keep the button around while its own menu is open, otherwise it
        # vanishes from under the pointer the moment the popover takes over.
        if self._context_popover is None:
            self.menu_button.set_visible(False)
        self.favorite_button.set_visible(self._is_favorite_now)
        self.remove_css_class("rom-card-hover")

    def set_focus_visual(self, focused):
        """Mirror the hover affordances for keyboard/gamepad focus.

        Driven by the grid: focus lands on the list-item wrapper, which is
        this card's *parent*, so a focus controller on the card itself would
        never see it.
        """
        if focused:
            if self.entry is None:
                return
            self.play_overlay.set_visible(True)
            self.menu_button.set_visible(True)
            self.favorite_button.set_visible(True)
            return
        if self.has_css_class("rom-card-hover"):
            return  # the pointer is still on the card; leave hover in charge
        self.play_overlay.set_visible(False)
        if self._context_popover is None:
            self.menu_button.set_visible(False)
        self.favorite_button.set_visible(self._is_favorite_now)

    def _on_menu_button_clicked(self, button):
        # Anchor the menu under the button. Coordinates are relative to the
        # card, which is what the popover is parented to.
        ok, bounds = button.compute_bounds(self)
        if ok:
            self._show_context_menu(
                bounds.get_x() + bounds.get_width() / 2,
                bounds.get_y() + bounds.get_height(),
            )
        else:
            self._show_context_menu()

    def on_click(self, gesture, n_press, x, y):
        rom = self.rom
        if rom is None:
            return
        button = gesture.get_current_button()
        logger.info(
            "rom card click: button=%s presses=%s rom=%s console=%s path=%s x=%.1f y=%.1f",
            button,
            n_press,
            rom.get("name"),
            rom.get("console"),
            rom.get("path"),
            x,
            y,
        )
        if button == Gdk.BUTTON_SECONDARY:
            self._show_context_menu(x, y)
            return
        if button != Gdk.BUTTON_PRIMARY:
            return
        # Modifier clicks build the selection (issue #78): Ctrl toggles this
        # card, Shift ranges from the anchor, Ctrl+Shift adds the range. A
        # modifier click must never launch the game.
        state = gesture.get_current_event_state()
        ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
        shift = bool(state & Gdk.ModifierType.SHIFT_MASK)
        if self.on_toggle_selection:
            self.on_toggle_selection(self.entry, ctrl, shift)
        if ctrl or shift:
            return
        # A plain click launches. The grid owns the debounce, so a habitual
        # double-click does not try to start the game twice (issue #236).
        if self.on_launch_callback:
            self.on_launch_callback(rom)

    def supports_label(self):
        """Whether this ROM's console has a cartridge to put a sticker on.

        Meaningful whether or not the cartridge look is switched on now, so it
        is asked of the console rather than of the card.
        """
        rom = self.rom
        return rom is not None and cartridge_frame_svg(rom["console"]) is not None

    def _ensure_action_group(self):
        if self._action_group is not None:
            return
        group = Gio.SimpleActionGroup()
        for name, handler in (
            ("toggle-favorite", self._act_toggle_favorite),
            ("reveal-in-files", self._act_reveal_in_files),
            ("choose-cover", self._act_choose_cover),
            ("remove-cover", self._act_remove_cover),
            ("choose-label", self._act_choose_label),
            ("remove-label", self._act_remove_label),
            ("sync-cover", self._act_sync_cover),
            ("sync-label", self._act_sync_label),
            ("manage-cover", self._act_manage_cover),
            ("manage-label", self._act_manage_label),
            ("rename", self._act_rename),
            ("delete", self._act_delete),
        ):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", handler)
            group.add_action(action)
        self.insert_action_group("rom", group)
        self._action_group = group

    def show_context_menu(self, x=None, y=None):
        """Open this card's context menu.

        Public because the gamepad controller and the grid's own key handler
        both open it from outside the card; they used to call the underscored
        name across a module boundary (issue #237).
        """
        self._show_context_menu(x, y)

    @property
    def context_popover(self):
        """The open context popover, or None. Read by the controller, which
        moves focus into it once it is up."""
        return self._context_popover

    def toggle_favorite(self):
        """Star or unstar this card's ROM, as the context entry would.

        Public because the star badge, the grid's ``Ctrl+D`` and the gamepad's
        Ⓨ all come through here rather than through the menu action.

        It called *itself* from the split in issue #238 -- so every one of
        those three paths died with a RecursionError instead of favoriting
        anything, and only the context-menu entry still worked (issue #382).
        """
        self._act_toggle_favorite(None, None)

    def _show_context_menu(self, x=None, y=None):
        rom = self.rom
        if rom is None:
            return
        logger.info(
            "rom context menu open: rom=%s console=%s path=%s",
            rom.get("name"),
            rom.get("console"),
            rom.get("path"),
        )
        self._ensure_action_group()

        popover = build_context_popover(card_menu_entries(self))
        popover.set_parent(self)
        if x is not None and y is not None:
            popover.set_pointing_to(Gdk.Rectangle(x=int(x), y=int(y), width=1, height=1))
        popover.connect("closed", self._on_context_popover_closed)
        self._context_popover = popover
        # Through the shared owner, so the keyboard and gamepad paths cannot
        # stack a second menu on top of one that is already up (issue #275).
        present_context_popover(popover)

    def _on_context_popover_closed(self, popover):
        if self._context_popover is popover:
            self._context_popover = None
        # The pointer may have left the card while the menu was up.
        if not self.has_css_class("rom-card-hover"):
            self.menu_button.set_visible(False)
        unparent_when_idle(popover)

    def _act_toggle_favorite(self, _action, _param):
        rom = self.rom
        if rom is None:
            return
        logger.info("rom context action: toggle_favorite rom=%s", rom.get("name"))
        self._sync_favorite_button(self.on_toggle_favorite(rom))

    def _act_rename(self, _action, _param):
        rom = self.rom
        if rom is None:
            return
        logger.info("rom context action: rename rom=%s", rom.get("name"))
        if self.on_rename_rom:
            self.on_rename_rom(rom)

    def _act_delete(self, _action, _param):
        rom = self.rom
        if rom is None:
            return
        logger.info("rom context action: delete rom=%s", rom.get("name"))
        if self.on_delete_rom:
            self.on_delete_rom([rom])

    def _act_reveal_in_files(self, _action, _param):
        rom = self.rom
        if rom is None:
            return
        logger.info("rom context action: reveal_in_files rom=%s", rom.get("name"))
        self.on_reveal_in_files(rom)

    def _act_choose_cover(self, _action, _param):
        rom = self.rom
        if rom is None:
            return
        logger.info("rom context action: choose_cover rom=%s", rom.get("name"))
        self.on_choose_cover(rom, self._refresh_cover_after_change, COVER_ART)

    def _act_remove_cover(self, _action, _param):
        rom = self.rom
        if rom is None:
            return
        logger.info("rom context action: remove_cover rom=%s", rom.get("name"))
        self.on_remove_cover(rom, self._refresh_cover_after_change, COVER_ART)

    def _act_choose_label(self, _action, _param):
        rom = self.rom
        if rom is None:
            return
        logger.info("rom context action: choose_label rom=%s", rom.get("name"))
        self.on_choose_cover(rom, self._refresh_cover_after_change, LABEL_ART)

    def _act_remove_label(self, _action, _param):
        rom = self.rom
        if rom is None:
            return
        logger.info("rom context action: remove_label rom=%s", rom.get("name"))
        self.on_remove_cover(rom, self._refresh_cover_after_change, LABEL_ART)

    def _act_sync_cover(self, _action, _param):
        rom = self.rom
        if rom is None:
            return
        logger.info("rom context action: sync_cover rom=%s", rom.get("name"))
        if self.context_services is not None:
            self.context_services.win.sync_rom_artwork(rom, COVER_ART_TYPE_BOXART)

    def _act_sync_label(self, _action, _param):
        rom = self.rom
        if rom is None:
            return
        logger.info("rom context action: sync_label rom=%s", rom.get("name"))
        if self.context_services is not None:
            self.context_services.win.sync_rom_artwork(rom, COVER_ART_TYPE_CARTRIDGE_LABEL)

    def _act_manage_cover(self, _action, _param):
        rom = self.rom
        if rom is None:
            return
        logger.info("rom context action: manage_cover rom=%s", rom.get("name"))
        if self.context_services is not None:
            self.context_services.win.open_artwork_manager(rom, COVER_ART)

    def _act_manage_label(self, _action, _param):
        rom = self.rom
        if rom is None:
            return
        logger.info("rom context action: manage_label rom=%s", rom.get("name"))
        if self.context_services is not None:
            self.context_services.win.open_artwork_manager(rom, LABEL_ART)

    def _refresh_cover_after_change(self, fade=False):
        # ``fade`` cross-fades the card when the new art lands (issue #187):
        # what separates covers "filling in" during a sync from glitchy
        # popping. Off for every other refresh path.
        if self.entry is None:
            return
        self._fade_next_apply = bool(fade)
        self._generation += 1
        self._start_cover_fetch()

    def _animate_cover_reveal(self):
        self.set_opacity(0.0)
        target = Adw.PropertyAnimationTarget.new(self, "opacity")
        animation = Adw.TimedAnimation.new(self, 0.0, 1.0, 280, target)
        # Held on the card: the animation object must outlive this frame.
        self._reveal_animation = animation
        animation.play()

    def set_cartridge_frame(self, frame_path):
        """Swap the shell SVG and re-compose the card (per-ROM color change).

        Only meaningful on a card already drawn as a cartridge; the geometry is
        identical across a console's shell variants, so the card size holds.
        """
        if not self.cartridge_frame_path or not frame_path:
            return
        if str(frame_path) == str(self.cartridge_frame_path):
            return
        self.cartridge_frame_path = frame_path
        self._refresh_cover_after_change()


