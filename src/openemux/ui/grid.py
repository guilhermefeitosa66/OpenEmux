import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, Gdk, GLib, GObject, Graphene, Pango, Gio
import logging

from openemux.core import cartridge_render, cover_cache
from openemux.core.paths import display_text
from openemux.core.selection import SelectionModel
from openemux.core.library_view import (
    DEFAULT_ZOOM,
    LIST_ROW_MIN_WIDTH,
    is_grid_view,
    list_thumb_column_width,
    list_thumb_size,
    normalize_view_mode,
    normalize_zoom,
    renders_cartridge,
    scale_length,
    scale_spacing,
)
from openemux.core.config import COVER_ART_TYPE_BOXART, COVER_ART_TYPE_CARTRIDGE_LABEL
from openemux.core.scraper import COVER_ART, LABEL_ART, fetch_cover
from openemux.core.systems import get_system_display_name
from openemux.ui.context_menu import (
    SEPARATOR,
    Submenu,
    build_context_popover,
    dismiss_context_popover,
    present_context_popover,
    unparent_when_idle,
)

logger = logging.getLogger(__name__)

# The composite is rendered above the logical card size so it stays sharp on
# HiDPI displays; GTK scales the texture down when it is not needed.
CARTRIDGE_RENDER_SCALE = 2


DEFAULT_ITEM_SIZE = (200, 200)
FIXED_ITEM_WIDTH = 200

#: Gap between cards, and the grid's padding inside the viewport.
#: How long after a launch the same card's activation is treated as the
#: second half of a double-click rather than a new launch (issue #236).
ACTIVATION_DEBOUNCE_US = 500_000

GRID_SPACING = 24
GRID_MARGIN = 28

#: The same, for the compact list: rows sit close together and closer to the
#: edges, like a file manager's list view.
LIST_ROW_SPACING = 4
LIST_MARGIN = 12

# Box art proportions (width / height) per console, so a card matches the shape
# of the artwork it holds instead of forcing every console into a square.
# Measured as the median of libretro Named_Boxarts samples per system (~30
# scans each), which is where synced covers come from.
DEFAULT_COVER_ASPECT = 1.0
CONSOLE_COVER_ASPECTS = {
    "A2600": 0.73,
    "A5200": 0.73,
    "A7800": 0.73,
    "CV": 0.73,
    "FC": 0.73,
    "FDS": 0.98,
    "GB": 1.00,
    "GBA": 1.00,
    "GBC": 1.00,
    "GC": 0.71,
    "GG": 0.71,
    "INTV": 0.72,
    "LYNX": 1.12,
    "MCD": 0.71,
    "MD": 0.70,
    "N64": 1.37,
    "NDS": 1.11,
    "NGP": 0.88,
    "O2": 0.74,
    "PCE": 1.03,
    "PCECD": 1.00,
    "PS": 1.00,
    "PSP": 0.58,
    "S32X": 0.73,
    "SATURN": 1.00,
    "SFC": 1.41,
    "SG1000": 0.73,
    "SMS": 0.71,
    "VB": 1.00,
    "VECTREX": 0.74,
    "WS": 0.81,
}


def cover_size_for_console(console, zoom=DEFAULT_ZOOM):
    """Card size for a console when no cartridge frame is drawn."""
    width = scale_length(FIXED_ITEM_WIDTH, zoom)
    aspect = CONSOLE_COVER_ASPECTS.get(console, DEFAULT_COVER_ASPECT)
    height = int(round(width / aspect)) if aspect > 0 else width
    return width, max(1, height)


def default_item_size(zoom=DEFAULT_ZOOM):
    """The uniform square box pages that mix consoles lay their covers in."""
    return scale_length(DEFAULT_ITEM_SIZE[0], zoom), scale_length(DEFAULT_ITEM_SIZE[1], zoom)


def card_size_for(cover_size, mixed_consoles=False, compact=False):
    """Full card size for a cover: the artwork plus the caption below it.

    The grid needs this to lay out its columns and the card needs it to pin its
    own size, so it is computed in one place. Pages that mix consoles carry a
    second caption line for the console name.

    A compact row puts the caption *beside* the thumbnail instead, so its
    height is the thumbnail's and its width is only a minimum -- the row
    stretches to the viewport.
    """
    if compact:
        return LIST_ROW_MIN_WIDTH, cover_size[1]
    caption_height = 44 + (18 if mixed_consoles else 0)
    return cover_size[0], cover_size[1] + caption_height


def columns_and_slack(available, card_width, item_count, spacing=GRID_SPACING):
    """How many cards fit on a line, and the width left over after them.

    ``available`` is the viewport width minus the grid's margins. GtkGridView
    splits its own width evenly between its columns, so the way to get an even
    lattice is to hand it a width that divides evenly: one **cell** is a card
    plus one gap, and a card centred in a cell sits exactly ``spacing`` from
    its neighbour. The leftover is what the caller gives to the end margin --
    see RomGrid._retune_columns.

    A page with fewer cards than fit on a line is sized for the cards it
    actually has, otherwise those few get spread across the full width.
    """
    cell = card_width + spacing
    columns = max(1, available // cell)
    filled = max(1, min(columns, item_count))
    return columns, max(0, available - filled * cell)


def cartridge_frame_svg(console, color=None):
    """The pre-render frame for a console, when one was authored as SVG.

    ``color`` picks a shell variant when one exists on disk; the default (and
    any color with no file) is the authored ``<CONSOLE>.svg``.
    """
    return cartridge_render.cartridge_frame(console, color=color)


class FixedSizePicture(Gtk.Picture):
    """A Picture that measures as the slot it sits in, not as its image.

    Gtk.Picture reports its paintable's pixel size as the natural size, and
    set_size_request only raises the minimum. Two places need the slot to win
    instead:

    * the cartridge composite is rendered at CARTRIDGE_RENDER_SCALE for HiDPI,
      and would blow the card up by that factor;
    * a list thumbnail asked to fit a fixed height reports the width its aspect
      implies, so each console would indent its titles differently.

    Reporting the slot directly fixes both, and GTK still draws from the
    full-resolution image.
    """

    __gtype_name__ = "OpenEmuxFixedSizePicture"

    def __init__(self, width, height):
        super().__init__()
        self._slot_size = (width, height)

    def do_measure(self, orientation, for_size):
        size = (
            self._slot_size[0]
            if orientation == Gtk.Orientation.HORIZONTAL
            else self._slot_size[1]
        )
        return size, size, -1, -1


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

    def _supports_label(self):
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
        """Star or unstar this card's ROM, as the context entry would."""
        self.toggle_favorite()

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

        is_favorite = self.is_favorite(rom)
        entries = [
            (
                self.t("context.favorite.remove") if is_favorite else self.t("context.favorite.add"),
                "rom.toggle-favorite",
                "starred-symbolic" if is_favorite else "non-starred-symbolic",
            ),
        ]
        # One artwork kind at a time, following what the card is actually
        # showing: the label inside a cartridge, the box art everywhere else
        # (issue #77).
        #
        # Everything that acts on that artwork lives in one submenu. Choose,
        # remove and manage were three sibling rows at the top level, which is
        # most of the menu's length spent on something that is not the common
        # case. Sync stays outside: it is the one-click "just fetch it".
        showing_label = bool(self.cartridge_frame_path) and self._supports_label()
        if showing_label:
            kind, art_dir = "label", LABEL_ART
        else:
            kind, art_dir = "cover", COVER_ART

        if self.context_services is not None:
            entries.append(
                (
                    self.t(f"context.{kind}.sync"),
                    f"rom.sync-{kind}",
                    "folder-download-symbolic",
                )
            )

        artwork_entries = []
        if self.context_services is not None:
            artwork_entries.append(
                (
                    self.t(f"context.{kind}.manage"),
                    f"rom.manage-{kind}",
                    "document-properties-symbolic",
                )
            )
        artwork_entries.append(
            (
                self.t(f"context.{kind}.choose"),
                f"rom.choose-{kind}",
                "insert-image-symbolic" if showing_label else "image-x-generic-symbolic",
            )
        )
        if self.has_local_cover(rom, art_dir):
            artwork_entries.append(
                (
                    self.t(f"context.{kind}.remove"),
                    f"rom.remove-{kind}",
                    "user-trash-symbolic",
                )
            )
        entries.append(
            Submenu(
                self.t(f"context.{kind}.artwork"),
                artwork_entries,
                "image-x-generic-symbolic",
            )
        )
        # Data-driven submenus (shader today; core/collection later). Their own
        # section, between the cover rows and the file actions.
        if self.context_services is not None:
            extra = self.context_services.build_submenus(rom)
            if extra:
                entries.append(SEPARATOR)
                entries.extend(extra)
        # Own section: these act on the file on disk, not on the library entry.
        entries.append(SEPARATOR)
        entries.append((self.t("context.reveal"), "rom.reveal-in-files", "folder-open-symbolic"))
        if self.on_rename_rom:
            entries.append((self.t("context.rename"), "rom.rename", "document-edit-symbolic"))
        if self.on_delete_rom:
            entries.append((self.t("context.delete"), "rom.delete", "user-trash-symbolic"))

        popover = build_context_popover(entries)
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
        self.on_launch_callback = on_launch_callback
        self.roms_dir = roms_dir
        self.ui_settings = ui_settings or {}
        self.on_selection_changed = on_selection_changed
        # Focus memory: coming back from the sidebar restores this game. The
        # entry, not the widget -- the widget may be showing another game by
        # then (issue #219).
        self._focused_entry = None
        # Rubber band state: the rectangle being dragged, and the selection it
        # started from so a ctrl-drag can extend instead of replace.
        self._band = None
        self._band_origin = None
        self._band_base = ()
        # Card rectangles, frozen for the length of a drag (issue #231).
        self._band_bounds = []
        # One selection model shared by every input method (issue #78); the
        # key detects when the search filter changed the visible set.
        self._selection_model = SelectionModel(0)
        self._selection_key = None
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
        # What the band gesture is attached to; see _attach_band_gesture.
        self._band_host = None
        self._clear_press_at = None

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

        cartridge_frame_path = None
        # One fixed card size for the whole page, so the grid lays out on an
        # even lattice. Per console it follows that console's box-art
        # proportions; pages mixing consoles have no single shape to follow, so
        # they use a uniform square box and centre each cover inside it.
        cover_size = (
            default_item_size(self.zoom)
            if mixed_consoles
            else cover_size_for_console(console, self.zoom)
        )
        if not mixed_consoles and not self.compact and renders_cartridge(self.view_mode):
            # The card shape comes from the frame art itself: fixed width, and
            # the height that keeps the cartridge's own proportions.
            cartridge_frame_path = cartridge_frame_svg(console)
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
            on_toggle_selection=self._toggle_entry_selection,
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
        self._attach_band_gesture()

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
        """The RomItem for ``widget``, whether it is inside one or wraps one.

        Keyboard/gamepad focus sits on the list-item wrapper, whose RomItem is
        its *child*; a pointer press lands on a widget *inside* the RomItem.
        Both have to resolve, so the walk checks downwards at every step and
        upwards until it runs out of parents.
        """
        node = widget
        while node is not None:
            if isinstance(node, RomItem):
                return node
            if isinstance(node.get_first_child(), RomItem):
                return node.get_first_child()
            node = node.get_parent()
        return None

    def focus_first_card(self):
        return self._focus_position(0)

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
    # (core/selection.py); this section maps entries to indices over the
    # *visible* ones and paints whichever of them has a card on screen. The
    # search filter changes the visible set, so the model is re-seeded
    # whenever it does.

    def selected_roms(self):
        return [entry.rom for entry in self._entries if entry.selected]

    def clear_selection(self):
        model, entries = self._model_and_entries()
        model.clear()
        self._paint_selection(model, entries)

    def select_all(self):
        model, entries = self._model_and_entries()
        model.select_all()
        self._paint_selection(model, entries)

    def toggle_select_all(self):
        """Select every visible ROM, or clear when everything already is."""
        model, entries = self._model_and_entries()
        if model.all_selected():
            model.clear()
        else:
            model.select_all()
        self._paint_selection(model, entries)

    def sync_visible_selection(self):
        """Re-seed the selection model after the visible set changed.

        Filtering and skipping this is how selection desyncs: the model would
        still hold indices into the previous visible list.
        """
        model, entries = self._model_and_entries()
        self._paint_selection(model, entries)

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

    def _model_and_entries(self):
        """The model, re-seeded when the visible set changed (search filter)."""
        entries = self.visible_entries()
        key = tuple(id(entry) for entry in entries)
        if key != self._selection_key:
            self._selection_key = key
            self._selection_model.reset(len(entries))
            self._selection_model.replace(
                [index for index, entry in enumerate(entries) if entry.selected]
            )
        return self._selection_model, entries

    def _paint_selection(self, model, entries):
        selected = {entries[index] for index in model.selected}
        self._apply_selection(selected)

    def _apply_selection(self, entries):
        chosen = set(entries)
        changed = False
        for entry in self._entries:
            wanted = entry in chosen
            if entry.selected != wanted:
                entry.selected = wanted
                card = self._bound.get(entry)
                if card is not None:
                    card.set_selected(wanted)
                changed = True
        if changed and self.on_selection_changed:
            self.on_selection_changed(self.selected_roms())

    def _entry_for(self, target):
        """Accept an entry or the card showing one; the callers mix both."""
        if isinstance(target, RomItem):
            return target.entry
        return target

    def _toggle_entry_selection(self, entry, ctrl=True, shift=False):
        """A card's click gesture: Ctrl toggles, Shift ranges (issue #78).

        A plain click (no modifier) does not touch the selection -- it
        launches, elsewhere -- but it does move the anchor, so a Shift+click
        right after ranges from the game the user just clicked, the way a
        file manager roots ranges at the last click.
        """
        entry = self._entry_for(entry)
        model, entries = self._model_and_entries()
        if entry not in entries:
            return
        index = entries.index(entry)
        if shift and ctrl:
            model.extend_additive(index)
        elif shift:
            model.extend(index)
        elif ctrl:
            model.toggle(index)
        else:
            model.move_cursor(index)
            return
        self._paint_selection(model, entries)

    def extend_selection_to(self, item, additive=False):
        """Shift+arrows: grow the range from the anchor to ``item``."""
        entry = self._entry_for(item)
        model, entries = self._model_and_entries()
        if entry not in entries:
            return
        index = entries.index(entry)
        if additive:
            model.extend_additive(index)
        else:
            model.extend(index)
        self._paint_selection(model, entries)

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
        entry = self._entry_for(item)
        model, entries = self._model_and_entries()
        if entry not in entries:
            return
        index = entries.index(entry)
        if index != model.cursor:
            model.move_cursor(index)

    def toggle_item(self, item):
        """Ctrl+Space / gamepad Ⓐ in selection mode: flip one card."""
        self._toggle_entry_selection(self._entry_for(item))

    def select_item(self, item):
        """Make ``item`` the whole selection (entering gamepad selection mode)."""
        entry = self._entry_for(item)
        model, entries = self._model_and_entries()
        if entry not in entries:
            return
        model.select(entries.index(entry))
        self._paint_selection(model, entries)

    def note_cursor(self, item, keep_anchor=False):
        """Follow plain/Ctrl movement so the next Shift range roots correctly."""
        entry = self._entry_for(item)
        model, entries = self._model_and_entries()
        if entry in entries:
            model.move_cursor(entries.index(entry), keep_anchor=keep_anchor)

    def _sync_model_from_view(self):
        """Adopt a selection made outside the model (the rubber band)."""
        model, entries = self._model_and_entries()
        model.replace([index for index, entry in enumerate(entries) if entry.selected])

    # -- rubber band -------------------------------------------------------

    def _attach_band_gesture(self, *_args):
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
        item wrappers deny presses -- see _on_factory_setup.
        """
        scroller = self.get_ancestor(Gtk.ScrolledWindow)
        if scroller is None:
            return
        # A GtkGridView is a scrollable, so the ScrolledWindow gives it the
        # viewport directly rather than wrapping it in a GtkViewport. The
        # ancestor lookup keeps working either way.
        host = self.get_ancestor(Gtk.Viewport) or scroller
        self._band_host = host

        previous = getattr(host, "_openemux_band_gesture", None)
        if previous is not None:
            host.remove_controller(previous)
        drag = Gtk.GestureDrag()
        drag.set_button(Gdk.BUTTON_PRIMARY)
        drag.connect("drag-begin", self._on_band_begin)
        drag.connect("drag-update", self._on_band_update)
        drag.connect("drag-end", self._on_band_end)
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
        click.connect(
            "pressed", lambda _g, _n, x, y: setattr(self, "_clear_press_at", (x, y))
        )
        click.connect("released", self._on_background_click_released)
        host.add_controller(click)
        host._openemux_clear_gesture = click

    def _to_grid_coords(self, x, y):
        """Host space -> grid space (the band maths live in grid space)."""
        if self._band_host is None or self._band_host is self:
            return x, y
        ok, point = self._band_host.compute_point(self, Graphene.Point().init(x, y))
        return (point.x, point.y) if ok else (x, y)

    def _on_background_click_released(self, gesture, _n_press, x, y):
        """A plain click on empty page space clears the selection.

        Not after a drag (that is the rubber band, whose result must survive
        its own release), not with Ctrl/Shift held (selection gestures), and
        only on true background (no card under the pointer).
        """
        pressed_at = self._clear_press_at
        self._clear_press_at = None
        if pressed_at is not None and abs(x - pressed_at[0]) + abs(y - pressed_at[1]) > 8:
            return
        state = gesture.get_current_event_state()
        if state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.SHIFT_MASK):
            return
        if not self._is_background(x, y):
            return
        if any(entry.selected for entry in self._entries):
            self.clear_selection()

    def _is_background(self, x, y):
        """True when (x, y) -- in host space -- is empty page, not a card.

        The scrollbars count as "not background" too: a drag on one must keep
        scrolling, never start a band.
        """
        host = self._band_host or self
        target = host.pick(x, y, Gtk.PickFlags.DEFAULT)
        while target is not None and target is not host:
            if isinstance(target, (RomItem, Gtk.Scrollbar)):
                return False
            target = target.get_parent()
        return True

    def _on_band_begin(self, gesture, start_x, start_y):
        if not self._is_background(start_x, start_y):
            gesture.set_state(Gtk.EventSequenceState.DENIED)
            return
        state = gesture.get_current_event_state()
        # Ctrl keeps what was already picked, so a band can be added to it.
        self._band_base = tuple(e for e in self._entries if e.selected) if (
            state & Gdk.ModifierType.CONTROL_MASK
        ) else ()
        self._band_origin = self._to_grid_coords(start_x, start_y)
        self._band = None
        self._snapshot_band_bounds()
        if not self._band_base:
            # A plain press on empty space clears -- which also makes a plain
            # *click* there clear the selection, the file-manager behavior.
            self._apply_selection(())

    def _on_band_update(self, gesture, offset_x, offset_y):
        if self._band_origin is None:
            return
        start_x, start_y = self._band_origin
        self._band = (
            min(start_x, start_x + offset_x),
            min(start_y, start_y + offset_y),
            abs(offset_x),
            abs(offset_y),
        )
        self._apply_selection(list(self._band_base) + self._entries_in_band())
        self.queue_draw()

    def _on_band_end(self, gesture, offset_x, offset_y):
        self._band = None
        self._band_origin = None
        self._band_base = ()
        self._band_bounds = []
        # The band bypassed the model; adopt its result so a Shift range or
        # Ctrl toggle right after behaves as if the band had used it.
        self._sync_model_from_view()
        self.queue_draw()

    def _snapshot_band_bounds(self):
        """Freeze every on-screen card's rectangle for the length of one drag.

        The cards that exist are the right set to ask: the band is dragged
        with the pointer, so it never leaves the viewport, and everything the
        viewport shows is realized. Nothing relayouts while the pointer is
        down, so the bounds cannot move -- and asking GTK for them per card on
        every drag-update was a compute_bounds call per card per motion event
        (issue #231).
        """
        frozen = []
        for entry, card in self._bound.items():
            ok, bounds = card.compute_bounds(self)
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

    def _entries_in_band(self):
        if self._band is None:
            return []
        bx, by, bw, bh = self._band
        hits = []
        for entry, x, y, width, height in self._band_bounds:
            if x < bx + bw and bx < x + width and y < by + bh and by < y + height:
                hits.append(entry)
        return hits

    def do_snapshot(self, snapshot):
        Gtk.GridView.do_snapshot(self, snapshot)
        if self._band is None:
            return
        x, y, width, height = self._band
        if width < 1 or height < 1:
            return
        fill = Gdk.RGBA()
        fill.parse("rgba(53, 132, 228, 0.18)")
        edge = Gdk.RGBA()
        edge.parse("rgba(53, 132, 228, 0.75)")
        snapshot.append_color(fill, Graphene.Rect().init(x, y, width, height))
        for rect in (
            (x, y, width, 1),
            (x, y + height - 1, width, 1),
            (x, y, 1, height),
            (x + width - 1, y, 1, height),
        ):
            snapshot.append_color(edge, Graphene.Rect().init(*rect))
