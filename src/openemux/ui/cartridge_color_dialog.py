"""The Custom Color dialog: any shell color for one game (issue 983).

Besides the named shell colors, a game's "Cartridge color" can be any color.
The dialog shows that game's cartridge -- its own label, in the color being
picked -- beside a saturation/brightness plane, a hue slider, a hex field and
places to start from: the colors saved from earlier picks and a palette
(`cartridge_palettes.PaletteArea`). GTK 4 has no color wheel, and its
own color chooser can neither show the cartridge nor sit inside this dialog,
so the plane is drawn here, the way GNOME's color editor lays it out
(``color_picker``, shared with the theme editor since issue 1011).

The preview is a mix of the game's composites in the black and white shells
(`cartridge_render.mix_shell`): rendered once when the dialog opens, then a
worker-thread mix per change, the latest color winning. "Apply" generates the full-size shell off the
main thread and only then stores the color, so the card re-draws at once.
"""

import sys
import threading

from gi.repository import Adw, Gdk, GLib, Gtk

from openemux.core import cartridge_colors, cartridge_render
from openemux.core.scraper import LABEL_ART, resolve_local_art
from openemux.ui.color_picker import ColorPicker
from openemux.ui.cartridge_palettes import PaletteArea

#: Width of the cartridge preview, in pixels.
PREVIEW_WIDTH = 160
NARROW_PREVIEW_WIDTH = 106
#: The preview's height when stacked: a picture may shrink to nothing, and
#: in a short column it would, so it keeps this much.
NARROW_PREVIEW_HEIGHT = 140
#: Below this the preview stacks above the controls.
NARROW_BREAKPOINT = "max-width: 500sp"

#: Where the dialog starts when the game draws the authored shell: the shell
#: has no color id of its own, and white is the most neutral of the named.
NEUTRAL_START = "white"


def start_color(config, rom):
    """The hex the dialog opens on: the shell the game draws today."""
    current = config.get_cartridge_color_for_rom(rom["path"], rom["console"])
    if cartridge_colors.is_custom_color(current):
        return cartridge_colors.normalize_color_id(current)
    named = current if current in _named_ids() else NEUTRAL_START
    return cartridge_colors.parse_hex(cartridge_colors.color_swatch(named))


def _named_ids():
    return [
        entry[0]
        for entry in cartridge_colors.CARTRIDGE_COLOR_TABLE
        if entry[0] != cartridge_colors.DEFAULT_COLOR_ID
    ]


def surface_texture(surface, byteorder=None):
    """A cairo ARGB32 surface as a Gdk texture, without a PNG round trip."""
    surface.flush()
    fmt = (
        Gdk.MemoryFormat.B8G8R8A8_PREMULTIPLIED
        if (byteorder or sys.byteorder) == "little"
        else Gdk.MemoryFormat.A8R8G8B8_PREMULTIPLIED
    )
    return Gdk.MemoryTexture.new(
        surface.get_width(), surface.get_height(), fmt,
        GLib.Bytes.new(bytes(surface.get_data())), surface.get_stride(),
    )


def _spawn(target):
    threading.Thread(target=target, daemon=True).start()


class CartridgeColorDialog(Adw.Dialog):
    def __init__(self, win, rom, spawn=None):
        super().__init__()
        self.win = win
        self.t = win.t
        self.rom = rom
        self._spawn = spawn or _spawn
        self._preview_busy = False
        self._preview_color = None
        self._sources = None
        self.applied = False
        self._start = start_color(win.config_manager, rom)

        self.set_title(self.t("cartridge_color.dialog.title"))
        self.set_content_width(600)
        view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_show_start_title_buttons(False)
        header.set_show_end_title_buttons(False)
        self.cancel_button = Gtk.Button(label=self.t("dialog.cancel"))
        self.cancel_button.connect("clicked", lambda _b: self.close())
        header.pack_start(self.cancel_button)
        self.apply_button = Gtk.Button(label=self.t("cartridge_color.dialog.apply"))
        self.apply_button.add_css_class("suggested-action")
        self.apply_button.connect("clicked", self._on_apply)
        header.pack_end(self.apply_button)
        view.add_top_bar(header)
        # The controls scroll when the dialog is shorter than they are, so the
        # last row of swatches stays reachable in a narrow, short window.
        self.scroller = Gtk.ScrolledWindow()
        self.scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.scroller.set_propagate_natural_height(True)
        self.scroller.set_child(self._build_body())
        view.set_content(self.scroller)
        self.set_child(view)
        self.set_default_widget(self.apply_button)

        narrow = Adw.Breakpoint.new(Adw.BreakpointCondition.parse(NARROW_BREAKPOINT))
        narrow.add_setter(self.body, "orientation", Gtk.Orientation.VERTICAL)
        narrow.add_setter(self.preview, "width-request", NARROW_PREVIEW_WIDTH)
        narrow.add_setter(self.preview, "height-request", NARROW_PREVIEW_HEIGHT)
        self.add_breakpoint(narrow)

        # Read here: a worker thread must not touch the widget.
        self._scale = max(1, self.get_scale_factor())
        self._schedule_preview()
        self._spawn(self._load_sources)

    # -- layout ----------------------------------------------------------

    def _build_body(self):
        t = self.t
        self.body = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=24)
        for side in ("top", "bottom", "start", "end"):
            getattr(self.body, f"set_margin_{side}")(24 if side != "top" else 12)

        preview_column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        preview_column.set_valign(Gtk.Align.START)
        preview_column.set_halign(Gtk.Align.CENTER)
        self.preview = Gtk.Picture()
        self.preview.set_content_fit(Gtk.ContentFit.CONTAIN)
        self.preview.set_size_request(PREVIEW_WIDTH, -1)
        self.preview.set_can_shrink(True)
        preview_column.append(self.preview)
        title = Gtk.Label(label=self.rom.get("title") or self.rom.get("name") or "")
        title.add_css_class("dim-label")
        title.set_wrap(True)
        title.set_justify(Gtk.Justification.CENTER)
        title.set_max_width_chars(18)
        preview_column.append(title)
        self.body.append(preview_column)

        controls = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        controls.set_hexpand(True)
        self.picker = ColorPicker(
            t, self._start,
            on_changed=self._on_color_changed,
            on_validity=self._on_validity,
            on_activate=lambda: self._on_apply(None),
        )
        self.plane = self.picker.plane
        self.hue_scale = self.picker.hue_scale
        self.hex_entry = self.picker.hex_entry
        controls.append(self.picker)

        # Saved colors and palettes (issue 983): where a color can start from.
        self.palettes = PaletteArea(
            t, self.win.config_manager.cartridge_colors,
            lambda: self.color, self.set_color, self,
        )
        controls.append(self.palettes.widget)
        self.error_label = Gtk.Label(label=t("cartridge_color.dialog.failed"), xalign=0, wrap=True)
        self.error_label.add_css_class("error")
        self.error_label.set_visible(False)
        controls.append(self.error_label)
        self.body.append(controls)
        return self.body

    # -- the color -------------------------------------------------------

    @property
    def color(self):
        return self.picker.color

    @property
    def hue(self):
        return self.picker.hue

    @property
    def saturation(self):
        return self.picker.saturation

    @property
    def value(self):
        return self.picker.value

    def set_color(self, color_hex):
        """Make ``color_hex`` the picked color, every control following it."""
        self.picker.set_color(color_hex)

    @property
    def swatch_buttons(self):
        """The named shells' swatches, while "Shell Colors" is the palette shown."""
        return self.palettes.swatch_buttons

    def _on_color_changed(self, _color):
        self.palettes.color_changed()
        self._schedule_preview()

    def _on_validity(self, valid):
        self.apply_button.set_sensitive(valid)

    # -- the preview -----------------------------------------------------

    def _load_sources(self):
        """Worker thread: the game's black and white composites."""
        label = resolve_local_art(self.rom, self.win.roms_path, kinds=(LABEL_ART,))
        sources = cartridge_render.custom_preview_sources(
            label, self.rom["console"], self.rom["name"], PREVIEW_WIDTH, scale=self._scale,
        )
        GLib.idle_add(self._sources_ready, sources)

    def _sources_ready(self, sources):
        self._sources = sources
        self._schedule_preview()
        return GLib.SOURCE_REMOVE

    def _schedule_preview(self):
        # One mix at a time, off the main thread; a drag fires many changes
        # while one runs, and only the latest color is mixed next.
        if self._preview_busy or self._sources is None:
            return
        self._preview_busy = True
        color = self.color
        dark, light = self._sources

        def work():
            texture = surface_texture(cartridge_render.mix_shell(dark, light, color))
            GLib.idle_add(self._preview_ready, color, texture)

        self._spawn(work)

    def _preview_ready(self, color, texture):
        self._preview_busy = False
        self._preview_color = color
        self.preview.set_paintable(texture)
        if color != self.color:
            self._schedule_preview()
        return GLib.SOURCE_REMOVE

    # -- apply -----------------------------------------------------------

    def _on_apply(self, _button):
        if not self.apply_button.get_sensitive() or self.applied:
            return
        self.applied = True
        # Nothing else to press while the shell is made: a Cancel here
        # would close the dialog and the color would land anyway.
        self.apply_button.set_sensitive(False)
        self.cancel_button.set_sensitive(False)
        self.set_can_close(False)
        self.error_label.set_visible(False)
        color = self.color
        console = self.rom["console"]

        def work():
            # The full-size shell, generated here rather than on the first
            # card draw, which runs on the main thread.
            made = cartridge_render.custom_frame_for(console, color)
            GLib.idle_add(self._applied, color, made is not None)

        self._spawn(work)

    def _applied(self, color, made):
        self.set_can_close(True)
        self.cancel_button.set_sensitive(True)
        if not made:
            # Storing it would draw the default shell under a "Custom" check.
            self.applied = False
            self.apply_button.set_sensitive(True)
            self.error_label.set_visible(True)
            return GLib.SOURCE_REMOVE
        # Kept for the next game (issue 983): only a color applied here is
        # saved, so one the user removed from "Saved" stays removed when a
        # game that wears it is set to it again from a menu.
        self.win.config_manager.cartridge_colors.remember_color(color)
        self.win.set_rom_cartridge_color(self.rom, color)
        self.close()
        return GLib.SOURCE_REMOVE


def open_cartridge_color_dialog(win, rom, spawn=None):
    dialog = CartridgeColorDialog(win, rom, spawn=spawn)
    dialog.present(win)
    return dialog
