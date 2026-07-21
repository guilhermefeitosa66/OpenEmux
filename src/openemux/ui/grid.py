import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, Gdk, GdkPixbuf, GLib, Pango, Gio
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

CARTRIDGE_ITEM_SIZES = {
    # Only used while the cartridge frame is drawn: the card has to match the
    # cartridge PNG proportions. Width fixed at 200px.
    # FC: 400x449 -> 200x224
    # SFC: 400x255 -> 200x128
    # GBA: 400x230 -> 200x115
    "FC": (200, 224),
    "SFC": (200, 128),
    "GBA": (200, 115),
}

CARTRIDGE_COVER_FRAMES = {
    # x, y, width, height for cover placement when cartridge overlay is enabled
    "GBA": (26.6, 25.7, 147, 75.3),
    "FC": (80.9, 0, 93.1, 153),
    "SFC": (38.6, 0, 122.5, 57.2),
}

# One decoded texture per console, shared by every card. Loading the PNG per
# card cost ~9ms and a full pixel copy each time, which showed up as lag on
# consoles with large libraries.
_CARTRIDGE_TEXTURES = {}


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


def _cartridge_texture(path):
    key = str(path)
    texture = _CARTRIDGE_TEXTURES.get(key)
    if texture is None:
        texture = Gdk.Texture.new_from_filename(key)
        _CARTRIDGE_TEXTURES[key] = texture
    return texture


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
        cartridge_overlay_path=None,
        cover_frame=None,
        cartridge_frame_path=None,
        mixed_consoles=False,
    ):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.rom = rom
        self.on_launch_callback = on_launch_callback
        self.on_toggle_favorite = on_toggle_favorite
        self.on_reveal_in_files = on_reveal_in_files
        self.on_choose_cover = on_choose_cover
        self.on_remove_cover = on_remove_cover
        self.is_favorite = is_favorite
        self.has_local_cover = has_local_cover
        self.t = t
        self.roms_dir = roms_dir
        self.cover_width, self.cover_height = cover_size
        self.cover_frame = cover_frame
        # When set, the card shows a single pre-rendered image (cover already
        # composited into the cartridge) instead of stacking widgets at
        # runtime, so no overlay or Fixed is built at all.
        self.cartridge_frame_path = cartridge_frame_path
        # Pages that mix consoles cannot size the card to one box art shape, so
        # the cover is centred at its own proportions over a uniform backdrop.
        self.mixed_consoles = mixed_consoles
        self._backdrop = None
        # Inside a cartridge frame the label sticker is what belongs there, so
        # prefer it and fall back to the box art when none was configured.
        in_cartridge = bool(cover_frame or cartridge_frame_path)
        self._art_kinds = (LABEL_ART, COVER_ART) if in_cartridge else (COVER_ART,)
        self.supports_label = in_cartridge or rom["console"] in CARTRIDGE_COVER_FRAMES
        self.add_css_class("rom-card")
        text_height = 44 + (18 if mixed_consoles else 0)
        self.set_size_request(self.cover_width, self.cover_height + text_height)
        self.set_halign(Gtk.Align.START)
        self.set_valign(Gtk.Align.START)
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

        self.cartridge_overlay = None
        if cartridge_overlay_path:
            self.cartridge_overlay = Gtk.Picture.new_for_paintable(
                _cartridge_texture(cartridge_overlay_path)
            )
            self.cartridge_overlay.set_size_request(self.cover_width, self.cover_height)
            # Preserve cartridge image ratio to avoid distortion.
            self.cartridge_overlay.set_content_fit(Gtk.ContentFit.CONTAIN)
            self.cartridge_overlay.set_can_shrink(True)
            self.cover_overlay.add_overlay(self.cartridge_overlay)
        self.cover_overlay.add_overlay(self.play_overlay)
        self.favorite_badge = Gtk.Image.new_from_icon_name("starred-symbolic")
        self.favorite_badge.add_css_class("favorite-badge")
        self.favorite_badge.set_halign(Gtk.Align.START)
        self.favorite_badge.set_valign(Gtk.Align.START)
        self.favorite_badge.set_margin_top(6)
        self.favorite_badge.set_margin_start(6)
        self.favorite_badge.set_visible(bool(self.is_favorite(self.rom)))
        self.cover_overlay.add_overlay(self.favorite_badge)

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
        if self.cover_frame:
            _, _, width, height = self.cover_frame
            return int(round(width)), int(round(height))
        return self.cover_width, self.cover_height

    def _cover_target_position(self):
        if self.cover_frame:
            x, y, _, _ = self.cover_frame
            return int(round(x)), int(round(y))
        return 0, 0

    def _setup_cover_host(self):
        if self.cover_frame:
            self._cover_host = Gtk.Fixed()
            self._cover_host.set_size_request(self.cover_width, self.cover_height)
            self.cover_overlay.set_child(self._cover_host)
            self._set_cover_widget(self.cover_image)
            return

        self._cover_host = None
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
        if self._cover_host is None:
            self.cover_overlay.set_child(widget)
            return
        child = self._cover_host.get_first_child()
        if child:
            self._cover_host.remove(child)
        x, y = self._cover_target_position()
        self._cover_host.put(widget, x, y)

    def _on_hover_enter(self, controller, x, y):
        self.play_overlay.set_visible(True)
        self.menu_button.set_visible(True)
        self.add_css_class("rom-card-hover")

    def _on_hover_leave(self, controller):
        self.play_overlay.set_visible(False)
        # Keep the button around while its own menu is open, otherwise it
        # vanishes from under the pointer the moment the popover takes over.
        if self._context_popover is None:
            self.menu_button.set_visible(False)
        self.remove_css_class("rom-card-hover")

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
        if button == Gdk.BUTTON_PRIMARY and self.on_launch_callback:
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
        # Own section: this acts on the file on disk, not on the library entry.
        entries.append(SEPARATOR)
        entries.append((self.t("context.reveal"), "rom.reveal-in-files", "folder-open-symbolic"))

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
        is_favorite_now = self.on_toggle_favorite(self.rom)
        self.favorite_badge.set_visible(bool(is_favorite_now))

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
    ):
        super().__init__()
        self.console = console
        self.mixed_consoles = mixed_consoles
        self.on_launch_callback = on_launch_callback
        self.roms_dir = roms_dir
        self.ui_settings = ui_settings or {}
        self.set_valign(Gtk.Align.START)
        self.set_row_spacing(24)
        self.set_column_spacing(24)
        self.set_selection_mode(Gtk.SelectionMode.NONE)
        self.set_margin_top(28)
        self.set_margin_bottom(28)
        self.set_margin_start(28)
        self.set_margin_end(28)
        self.set_homogeneous(False)

        cartridge_overlay_path = None
        cartridge_frame_path = None
        # Without the cartridge frame the card follows the console's box art
        # proportions instead of being squeezed into a cartridge silhouette.
        # Pages mixing consoles have no single shape to follow, so they use a
        # uniform square box and centre each cover inside it.
        cover_size = DEFAULT_ITEM_SIZE if mixed_consoles else cover_size_for_console(console)
        if not mixed_consoles and self.ui_settings.get("render_cartridge_overlay", False):
            # Consoles with an SVG frame are pre-rendered: the card is a single
            # flat picture and its shape comes from the art, not from a table.
            cartridge_frame_path = cartridge_frame_svg(console)
            if cartridge_frame_path:
                frame = cartridge_render.load_frame(cartridge_frame_path)
                cover_size = frame.size_for_width(FIXED_ITEM_WIDTH)
            candidate = CARTRIDGE_ASSETS_DIR / f"{console}.png"
            if candidate.exists() and not cartridge_frame_path:
                cartridge_overlay_path = candidate
                cover_size = CARTRIDGE_ITEM_SIZES.get(console, DEFAULT_ITEM_SIZE)
                size_info = GdkPixbuf.Pixbuf.get_file_info(str(candidate))
                if size_info:
                    _, width, height = size_info
                    if width and height:
                        proportional_height = int(round((FIXED_ITEM_WIDTH * height) / width))
                        cover_size = (FIXED_ITEM_WIDTH, max(1, proportional_height))
        cover_frame = CARTRIDGE_COVER_FRAMES.get(console) if cartridge_overlay_path else None

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
                cartridge_overlay_path=cartridge_overlay_path,
                cover_frame=cover_frame,
                cartridge_frame_path=cartridge_frame_path,
                mixed_consoles=mixed_consoles,
            )
            self.append(item)
