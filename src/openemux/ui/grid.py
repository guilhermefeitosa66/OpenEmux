import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, Gdk, GdkPixbuf, GLib, Graphene, Pango, Gio
from pathlib import Path
import logging

from openemux.core import cartridge_render
from openemux.core.scraper import COVER_ART, LABEL_ART, fetch_cover
from openemux.core.systems import get_system_display_name
from openemux.ui.context_menu import SEPARATOR, build_context_popover

logger = logging.getLogger(__name__)

CARTRIDGE_ASSETS_DIR = Path(__file__).parent / "assets" / "images" / "cartridges"

# The composite is rendered above the logical card size so it stays sharp on
# HiDPI displays; GTK scales the texture down when it is not needed.
CARTRIDGE_RENDER_SCALE = 2


DEFAULT_ITEM_SIZE = (200, 200)
FIXED_ITEM_WIDTH = 200

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


def cover_size_for_console(console):
    """Card size for a console when no cartridge frame is drawn."""
    aspect = CONSOLE_COVER_ASPECTS.get(console, DEFAULT_COVER_ASPECT)
    height = int(round(FIXED_ITEM_WIDTH / aspect)) if aspect > 0 else FIXED_ITEM_WIDTH
    return FIXED_ITEM_WIDTH, max(1, height)


def cartridge_frame_svg(console):
    """The pre-render frame for a console, when one was authored as SVG."""
    candidate = CARTRIDGE_ASSETS_DIR / f"{console}.svg"
    if not candidate.exists() or not cartridge_render.rsvg_available():
        return None
    return candidate if cartridge_render.load_frame(candidate) else None


class CartridgePicture(Gtk.Picture):
    """A Picture that measures as the card, not as the image it holds.

    Gtk.Picture reports its paintable's pixel size as the natural size, and
    set_size_request only raises the minimum, so the HiDPI composite (rendered
    at CARTRIDGE_RENDER_SCALE) would blow the card up by that factor. The card
    size comes from the frame proportions, so it is reported here directly and
    GTK still draws from the full-resolution texture.
    """

    __gtype_name__ = "OpenEmuxCartridgePicture"

    def __init__(self, width, height):
        super().__init__()
        self._card_size = (width, height)

    def do_measure(self, orientation, for_size):
        size = (
            self._card_size[0]
            if orientation == Gtk.Orientation.HORIZONTAL
            else self._card_size[1]
        )
        return size, size, -1, -1


class RomItem(Gtk.Box):
    NAME_PREVIEW_LIMIT = 30

    def __init__(
        self,
        rom,
        on_launch_callback,
        on_toggle_favorite,
        on_reveal_in_files,
        on_choose_cover,
        on_remove_cover,
        is_favorite,
        has_local_cover,
        t,
        roms_dir,
        cover_size,
        cartridge_frame_path=None,
        mixed_consoles=False,
        on_rename_rom=None,
        on_delete_rom=None,
        on_toggle_selection=None,
    ):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.rom = rom
        self.on_launch_callback = on_launch_callback
        self.on_toggle_favorite = on_toggle_favorite
        self.on_reveal_in_files = on_reveal_in_files
        self.on_choose_cover = on_choose_cover
        self.on_remove_cover = on_remove_cover
        self.on_rename_rom = on_rename_rom
        self.on_delete_rom = on_delete_rom
        # Selection lives in the grid (it spans cards); the card only reports
        # the ctrl-click that toggles it.
        self.on_toggle_selection = on_toggle_selection
        self.selected = False
        self.is_favorite = is_favorite
        self.has_local_cover = has_local_cover
        self.t = t
        self.roms_dir = roms_dir
        self.cover_width, self.cover_height = cover_size
        # When set, the card shows a single pre-rendered image: the cover is
        # already composited into the cartridge, so there is no overlay to
        # stack and no geometry to compute here.
        self.cartridge_frame_path = cartridge_frame_path
        # Pages that mix consoles cannot size the card to one box art shape, so
        # the cover is centred at its own proportions over a uniform backdrop.
        self.mixed_consoles = mixed_consoles
        self._backdrop = None
        # Inside a cartridge frame the label sticker is what belongs there, so
        # prefer it and fall back to the box art when none was configured.
        self._art_kinds = (
            (LABEL_ART, COVER_ART) if cartridge_frame_path else (COVER_ART,)
        )
        # A label sticker is only meaningful for a console that has a cartridge
        # to put it on, whether or not the cartridge look is switched on now.
        self.supports_label = cartridge_frame_svg(rom["console"]) is not None
        self.add_css_class("rom-card")
        text_height = 44 + (18 if mixed_consoles else 0)
        # Fixed card size. The grid also pins each FlowBoxChild to this size, so
        # a page with a single row cannot stretch the cell (and with it the
        # focus ring) over the whole viewport.
        self.card_size = (self.cover_width, self.cover_height + text_height)
        self.set_size_request(*self.card_size)
        # Centred rather than START-aligned: the card fills its cell exactly, so
        # its contents sit centred inside the focus/selection ring.
        self.set_halign(Gtk.Align.CENTER)
        self.set_valign(Gtk.Align.CENTER)
        self.set_hexpand(False)
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

        # Cover image (placeholder initially)
        self.cover_image = (
            CartridgePicture(*self._cover_target_size())
            if cartridge_frame_path
            else Gtk.Picture()
        )
        self.cover_image.set_size_request(*self._cover_target_size())
        self.cover_image.set_content_fit(
            Gtk.ContentFit.CONTAIN
            if (mixed_consoles or cartridge_frame_path)
            else Gtk.ContentFit.COVER
        )
        self.cover_image.set_can_shrink(True)
        self.cover_image.add_css_class("rom-cover")
        self._setup_cover_host()
        self._set_placeholder()

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
        play_icon.set_pixel_size(40)
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
        self.favorite_button.add_css_class("rom-menu-button")
        self.favorite_button.add_css_class("circular")
        self.favorite_button.add_css_class("favorite-badge")
        self.favorite_button.set_halign(Gtk.Align.START)
        self.favorite_button.set_valign(Gtk.Align.START)
        self.favorite_button.set_margin_top(6)
        self.favorite_button.set_margin_start(6)
        self.favorite_button.connect("clicked", self._on_favorite_button_clicked)
        self._sync_favorite_button(self.is_favorite(self.rom))
        self.cover_overlay.add_overlay(self.favorite_button)

        # Right-click is not obvious to everyone, so the same menu is one click
        # away from a button that appears on hover.
        self.menu_button = Gtk.Button.new_from_icon_name("view-more-symbolic")
        self.menu_button.add_css_class("rom-menu-button")
        self.menu_button.add_css_class("circular")
        self.menu_button.set_halign(Gtk.Align.END)
        self.menu_button.set_valign(Gtk.Align.START)
        self.menu_button.set_margin_top(6)
        self.menu_button.set_margin_end(6)
        self.menu_button.set_tooltip_text(self.t("context.more_options"))
        self.menu_button.set_visible(False)
        self.menu_button.connect("clicked", self._on_menu_button_clicked)
        self.cover_overlay.add_overlay(self.menu_button)

        self.append(self.cover_overlay)

        full_name = rom["name"]
        display_name = self._truncate_name(full_name)
        self.set_tooltip_text(full_name)

        # ROM name, plus the console it belongs to when the page mixes consoles.
        text_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.name_label = Gtk.Label(label=display_name)
        self.name_label.set_halign(Gtk.Align.CENTER)
        self.name_label.set_max_width_chars(self.NAME_PREVIEW_LIMIT + 3)
        self.name_label.set_ellipsize(Pango.EllipsizeMode.NONE)
        self.name_label.set_tooltip_text(full_name)
        self.name_label.add_css_class("rom-title")
        text_box.append(self.name_label)

        self.console_label = None
        if mixed_consoles:
            self.console_label = Gtk.Label(label=get_system_display_name(rom["console"]))
            self.console_label.set_halign(Gtk.Align.CENTER)
            self.console_label.set_max_width_chars(self.NAME_PREVIEW_LIMIT + 3)
            self.console_label.set_ellipsize(Pango.EllipsizeMode.END)
            self.console_label.add_css_class("caption")
            self.console_label.add_css_class("dim-label")
            self.console_label.add_css_class("rom-console")
            text_box.append(self.console_label)

        self.append(text_box)

        # Trigger async cover art fetch
        fetch_cover(rom, self.roms_dir, self._on_cover_fetched, kinds=self._art_kinds)

        self._context_popover = None

    @classmethod
    def _truncate_name(cls, name):
        if len(name) <= cls.NAME_PREVIEW_LIMIT:
            return name
        return f"{name[:cls.NAME_PREVIEW_LIMIT]}..."

    def _set_placeholder(self):
        """Show a styled placeholder with console-specific icon."""
        icon_name = "applications-games-symbolic"

        placeholder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        placeholder.set_valign(Gtk.Align.CENTER)
        placeholder.set_halign(Gtk.Align.CENTER)
        placeholder.set_hexpand(True)
        placeholder.set_vexpand(True)
        placeholder.set_size_request(*self._cover_target_size())
        placeholder.add_css_class("rom-cover-placeholder")

        icon = Gtk.Image.new_from_icon_name(icon_name)
        icon.set_pixel_size(48)
        icon.set_halign(Gtk.Align.CENTER)
        icon.set_valign(Gtk.Align.CENTER)
        icon.add_css_class("placeholder-icon")
        placeholder_center = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        placeholder_center.set_hexpand(True)
        placeholder_center.set_vexpand(True)
        placeholder_center.set_halign(Gtk.Align.CENTER)
        placeholder_center.set_valign(Gtk.Align.CENTER)
        placeholder_center.append(icon)
        placeholder.append(placeholder_center)

        # Replace cover image with placeholder in the configured cover area.
        self.cover_image.set_visible(False)
        self._set_cover_widget(placeholder)
        self._placeholder_widget = placeholder

    def _on_cover_fetched(self, rom, cover_path):
        """Called from background thread when cover art is ready."""
        if self.cartridge_frame_path:
            # Still on the worker thread: compose the cover into the cartridge
            # (cached on disk, so this only costs anything the first time). A
            # ROM with no cover renders as a blank cartridge instead of the
            # generic icon, keeping the shelf consistent.
            composite = cartridge_render.render_cartridge(
                cover_path,
                self.cartridge_frame_path,
                rom["console"],
                rom["name"],
                width=self.cover_width,
                scale=CARTRIDGE_RENDER_SCALE,
            )
            if composite:
                GLib.idle_add(self._load_cover_image, str(composite))
                return
        if cover_path:
            # Schedule UI update on the main thread
            GLib.idle_add(self._load_cover_image, cover_path)
            return
        # Cover was removed or does not exist: restore placeholder immediately.
        GLib.idle_add(self._restore_placeholder)

    def _restore_placeholder(self):
        self._set_placeholder()
        return False

    def _load_cover_image(self, cover_path):
        """Load cover image into the widget (must run on main thread)."""
        try:
            if self.cartridge_frame_path:
                # The composite is already the card's shape, and handing GTK
                # the full-resolution texture keeps it sharp on HiDPI.
                self.cover_image.set_paintable(Gdk.Texture.new_from_filename(cover_path))
                self.cover_image.set_visible(True)
                if hasattr(self, "_placeholder_widget"):
                    self._set_cover_widget(self.cover_image)
                    del self._placeholder_widget
                return False
            pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(
                cover_path,
                self._cover_target_size()[0],
                self._cover_target_size()[1],
                True,
            )
            if self.mixed_consoles:
                # Shrink the widget to the scaled art so the rounded corners and
                # shadow hug the cover, not the empty area around it.
                self.cover_image.set_size_request(pixbuf.get_width(), pixbuf.get_height())
            self.cover_image.set_pixbuf(pixbuf)
            self.cover_image.set_visible(True)
            # Remove placeholder if present
            if hasattr(self, "_placeholder_widget"):
                self._set_cover_widget(self.cover_image)
                del self._placeholder_widget
        except Exception:
            pass  # Keep placeholder on error
        return False  # Don't repeat idle callback

    def _cover_target_size(self):
        return self.cover_width, self.cover_height

    def _setup_cover_host(self):
        if self.mixed_consoles:
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
        self._act_toggle_favorite(None, None)

    def set_selected(self, selected):
        self.selected = bool(selected)
        if self.selected:
            self.add_css_class("rom-card-selected")
        else:
            self.remove_css_class("rom-card-selected")

    def _on_hover_enter(self, controller, x, y):
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

        Driven by the grid: focus lands on the FlowBoxChild wrapper, which is
        this card's *parent*, so a focus controller on the card itself would
        never see it.
        """
        if focused:
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
        button = gesture.get_current_button()
        logger.info(
            "rom card click: button=%s presses=%s rom=%s console=%s path=%s x=%.1f y=%.1f",
            button,
            n_press,
            self.rom.get("name"),
            self.rom.get("console"),
            self.rom.get("path"),
            x,
            y,
        )
        if button == Gdk.BUTTON_SECONDARY:
            self._show_context_menu(x, y)
            return
        if button != Gdk.BUTTON_PRIMARY:
            return
        # Ctrl-click builds a selection card by card; the rubber band on the
        # empty area is the other way in.
        state = gesture.get_current_event_state()
        if state & Gdk.ModifierType.CONTROL_MASK and self.on_toggle_selection:
            self.on_toggle_selection(self)
            return
        if self.on_launch_callback:
            self.on_launch_callback(self.rom)

    def _ensure_action_group(self):
        if getattr(self, "_action_group", None) is not None:
            return
        group = Gio.SimpleActionGroup()
        for name, handler in (
            ("toggle-favorite", self._act_toggle_favorite),
            ("reveal-in-files", self._act_reveal_in_files),
            ("choose-cover", self._act_choose_cover),
            ("remove-cover", self._act_remove_cover),
            ("choose-label", self._act_choose_label),
            ("remove-label", self._act_remove_label),
            ("rename", self._act_rename),
            ("delete", self._act_delete),
        ):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", handler)
            group.add_action(action)
        self.insert_action_group("rom", group)
        self._action_group = group

    def _show_context_menu(self, x=None, y=None):
        logger.info(
            "rom context menu open: rom=%s console=%s path=%s",
            self.rom.get("name"),
            self.rom.get("console"),
            self.rom.get("path"),
        )
        self._ensure_action_group()
        if self._context_popover is not None:
            self._context_popover.popdown()
            self._context_popover = None

        is_favorite = self.is_favorite(self.rom)
        entries = [
            (
                self.t("context.favorite.remove") if is_favorite else self.t("context.favorite.add"),
                "rom.toggle-favorite",
                "starred-symbolic" if is_favorite else "non-starred-symbolic",
            ),
            (self.t("context.cover.choose"), "rom.choose-cover", "image-x-generic-symbolic"),
        ]
        if self.has_local_cover(self.rom, COVER_ART):
            entries.append(
                (self.t("context.cover.remove"), "rom.remove-cover", "user-trash-symbolic")
            )
        if self.supports_label:
            entries.append(
                (self.t("context.label.choose"), "rom.choose-label", "insert-image-symbolic")
            )
            if self.has_local_cover(self.rom, LABEL_ART):
                entries.append(
                    (self.t("context.label.remove"), "rom.remove-label", "user-trash-symbolic")
                )
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
        popover.popup()

    def _on_context_popover_closed(self, popover):
        if self._context_popover is popover:
            self._context_popover = None
        # The pointer may have left the card while the menu was up.
        if not self.has_css_class("rom-card-hover"):
            self.menu_button.set_visible(False)
        GLib.idle_add(popover.unparent)

    def _act_toggle_favorite(self, _action, _param):
        logger.info("rom context action: toggle_favorite rom=%s", self.rom.get("name"))
        self._sync_favorite_button(self.on_toggle_favorite(self.rom))

    def _act_rename(self, _action, _param):
        logger.info("rom context action: rename rom=%s", self.rom.get("name"))
        if self.on_rename_rom:
            self.on_rename_rom(self.rom)

    def _act_delete(self, _action, _param):
        logger.info("rom context action: delete rom=%s", self.rom.get("name"))
        if self.on_delete_rom:
            self.on_delete_rom([self.rom])

    def _act_reveal_in_files(self, _action, _param):
        logger.info("rom context action: reveal_in_files rom=%s", self.rom.get("name"))
        self.on_reveal_in_files(self.rom)

    def _act_choose_cover(self, _action, _param):
        logger.info("rom context action: choose_cover rom=%s", self.rom.get("name"))
        self.on_choose_cover(self.rom, self._refresh_cover_after_change, COVER_ART)

    def _act_remove_cover(self, _action, _param):
        logger.info("rom context action: remove_cover rom=%s", self.rom.get("name"))
        self.on_remove_cover(self.rom, self._refresh_cover_after_change, COVER_ART)

    def _act_choose_label(self, _action, _param):
        logger.info("rom context action: choose_label rom=%s", self.rom.get("name"))
        self.on_choose_cover(self.rom, self._refresh_cover_after_change, LABEL_ART)

    def _act_remove_label(self, _action, _param):
        logger.info("rom context action: remove_label rom=%s", self.rom.get("name"))
        self.on_remove_cover(self.rom, self._refresh_cover_after_change, LABEL_ART)

    def _refresh_cover_after_change(self):
        fetch_cover(self.rom, self.roms_dir, self._on_cover_fetched, kinds=self._art_kinds)


class RomGrid(Gtk.FlowBox):
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
    ):
        super().__init__()
        self.console = console
        self.mixed_consoles = mixed_consoles
        self.on_launch_callback = on_launch_callback
        self.roms_dir = roms_dir
        self.ui_settings = ui_settings or {}
        self.on_selection_changed = on_selection_changed
        self._items = []
        # Focus memory: coming back from the sidebar restores this card.
        self._last_focused_child = None
        # Rubber band state: the rectangle being dragged, and the selection it
        # started from so a ctrl-drag can extend instead of replace.
        self._band = None
        self._band_origin = None
        self._band_base = ()
        # Fill the viewport instead of hugging the rows: the empty area below
        # the last card is where a rubber-band selection naturally starts, and
        # it only reaches the grid if the grid actually owns it.
        self.set_valign(Gtk.Align.FILL)
        self.set_vexpand(True)
        self.set_row_spacing(24)
        self.set_column_spacing(24)
        self.set_selection_mode(Gtk.SelectionMode.NONE)
        self.set_margin_top(28)
        self.set_margin_bottom(28)
        self.set_margin_start(28)
        self.set_margin_end(28)
        self.set_homogeneous(False)

        cartridge_frame_path = None
        # Without the cartridge frame the card follows the console's box art
        # proportions instead of being squeezed into a cartridge silhouette.
        # Pages mixing consoles have no single shape to follow, so they use a
        # uniform square box and centre each cover inside it.
        cover_size = DEFAULT_ITEM_SIZE if mixed_consoles else cover_size_for_console(console)
        if not mixed_consoles and self.ui_settings.get("render_cartridge_overlay", False):
            # The card shape comes from the frame art itself: fixed width, and
            # the height that keeps the cartridge's own proportions.
            cartridge_frame_path = cartridge_frame_svg(console)
            if cartridge_frame_path:
                frame = cartridge_render.load_frame(cartridge_frame_path)
                cover_size = frame.size_for_width(FIXED_ITEM_WIDTH)

        for rom in roms:
            item = RomItem(
                rom,
                self.on_launch_callback,
                on_toggle_favorite,
                on_reveal_in_files,
                on_choose_cover,
                on_remove_cover,
                is_favorite,
                has_local_cover,
                t,
                self.roms_dir,
                cover_size,
                cartridge_frame_path=cartridge_frame_path,
                mixed_consoles=mixed_consoles,
                on_rename_rom=on_rename_rom,
                on_delete_rom=on_delete_rom,
                on_toggle_selection=self._toggle_item_selection,
            )
            self._items.append(item)
            self.append(item)
            self._prepare_child(item)

        self.connect("child-activated", self._on_child_activated)

        # Menu key / Shift+F10 opens the focused card's context menu, the
        # keyboard counterpart of the right click.
        key = Gtk.EventControllerKey()
        key.connect("key-pressed", self._on_grid_key_pressed)
        self.add_controller(key)

        # Dragging across the empty area selects whatever it sweeps over. The
        # gesture sits on the grid, so it only ever starts on the background --
        # a press that lands on a card is left to the card.
        drag = Gtk.GestureDrag()
        drag.set_button(Gdk.BUTTON_PRIMARY)
        drag.connect("drag-begin", self._on_band_begin)
        drag.connect("drag-update", self._on_band_update)
        drag.connect("drag-end", self._on_band_end)
        self.add_controller(drag)

    # -- keyboard / gamepad focus -----------------------------------------

    def _prepare_child(self, item):
        """Set up the FlowBoxChild wrapping ``item`` as the focus target.

        The wrapper is what GTK focuses and activates, so it carries the
        focusable flag and the focus controller. It is also pinned to the
        card's size: a FlowBoxChild defaults to FILL in both directions, and on
        a page with a single row it would otherwise absorb the whole viewport
        height -- dragging the focus ring out with it.
        """
        child = item.get_parent()
        if child is None:
            return
        child.set_focusable(True)
        child.set_size_request(*item.card_size)
        child.set_halign(Gtk.Align.CENTER)
        child.set_valign(Gtk.Align.CENTER)
        child.set_hexpand(False)
        child.set_vexpand(False)

        focus = Gtk.EventControllerFocus()
        focus.connect("enter", self._on_child_focus_enter, child, item)
        focus.connect("leave", self._on_child_focus_leave, item)
        child.add_controller(focus)

    def _on_child_focus_enter(self, _controller, child, item):
        self._last_focused_child = child
        item.set_focus_visual(True)

    def _on_child_focus_leave(self, _controller, item):
        item.set_focus_visual(False)

    def _on_child_activated(self, _box, child):
        item = child.get_child()
        if isinstance(item, RomItem) and self.on_launch_callback:
            self.on_launch_callback(item.rom)

    def _on_grid_key_pressed(self, _controller, keyval, _keycode, state):
        is_menu_key = keyval == Gdk.KEY_Menu or (
            keyval == Gdk.KEY_F10 and state & Gdk.ModifierType.SHIFT_MASK
        )
        if not is_menu_key:
            return False
        root = self.get_root()
        item = self.item_for_widget(root.get_focus()) if root else None
        if item is None:
            return False
        item._show_context_menu()
        return True

    @staticmethod
    def item_for_widget(widget):
        """The RomItem for ``widget``, whether it is inside one or wraps one.

        Keyboard/gamepad focus sits on the FlowBoxChild, whose RomItem is its
        *child*; a pointer press lands on a widget *inside* the RomItem. Both
        have to resolve, so the walk checks downwards at the wrapper and
        upwards everywhere else.
        """
        node = widget
        while node is not None:
            if isinstance(node, RomItem):
                return node
            if isinstance(node, Gtk.FlowBoxChild):
                child = node.get_child()
                return child if isinstance(child, RomItem) else None
            node = node.get_parent()
        return None

    def _first_visible_child(self):
        child = self.get_first_child()
        while child is not None:
            if child.get_visible():
                return child
            child = child.get_next_sibling()
        return None

    def focus_first_card(self):
        child = self._first_visible_child()
        if child is not None:
            child.grab_focus()
            return True
        return False

    def focus_restore(self):
        """Focus the last card the user was on, else the first one."""
        child = self._last_focused_child
        if child is not None and child.get_visible() and child.get_parent() is self:
            child.grab_focus()
            return True
        return self.focus_first_card()

    # -- selection ---------------------------------------------------------

    def selected_roms(self):
        return [item.rom for item in self._items if item.selected]

    def clear_selection(self):
        self._apply_selection(())

    def _apply_selection(self, items):
        chosen = set(items)
        changed = False
        for item in self._items:
            wanted = item in chosen
            if item.selected != wanted:
                item.set_selected(wanted)
                changed = True
        if changed and self.on_selection_changed:
            self.on_selection_changed(self.selected_roms())

    def _toggle_item_selection(self, item):
        current = [entry for entry in self._items if entry.selected]
        if item in current:
            current.remove(item)
        else:
            current.append(item)
        self._apply_selection(current)

    def _is_background(self, x, y):
        """True when (x, y) is empty grid, not a card."""
        target = self.pick(x, y, Gtk.PickFlags.DEFAULT)
        while target is not None and target is not self:
            if isinstance(target, RomItem):
                return False
            target = target.get_parent()
        return True

    def _on_band_begin(self, gesture, start_x, start_y):
        if not self._is_background(start_x, start_y):
            gesture.set_state(Gtk.EventSequenceState.DENIED)
            return
        state = gesture.get_current_event_state()
        # Ctrl keeps what was already picked, so a band can be added to it.
        self._band_base = tuple(item for item in self._items if item.selected) if (
            state & Gdk.ModifierType.CONTROL_MASK
        ) else ()
        self._band_origin = (start_x, start_y)
        self._band = None
        if not self._band_base:
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
        self._apply_selection(list(self._band_base) + self._items_in_band())
        self.queue_draw()

    def _on_band_end(self, gesture, offset_x, offset_y):
        self._band = None
        self._band_origin = None
        self._band_base = ()
        self.queue_draw()

    def _items_in_band(self):
        if self._band is None:
            return []
        bx, by, bw, bh = self._band
        hits = []
        for item in self._items:
            ok, bounds = item.compute_bounds(self)
            if not ok:
                continue
            if (
                bounds.get_x() < bx + bw
                and bx < bounds.get_x() + bounds.get_width()
                and bounds.get_y() < by + bh
                and by < bounds.get_y() + bounds.get_height()
            ):
                hits.append(item)
        return hits

    def do_snapshot(self, snapshot):
        Gtk.FlowBox.do_snapshot(self, snapshot)
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
