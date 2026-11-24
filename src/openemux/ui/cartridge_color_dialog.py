"""The Custom Color dialog: any shell color for one game (issue 983).

Besides the named shell colors, a game's "Cartridge color" can be any color.
The dialog shows that game's cartridge -- its own label, in the color being
picked -- beside a saturation/brightness plane, a hue slider, a hex field and
the named colors as places to start from. GTK 4 has no color wheel, and its
own color chooser can neither show the cartridge nor sit inside this dialog,
so the plane is drawn here, the way GNOME's color editor lays it out.

The preview is a mix of the game's composites in the black and white shells
(`cartridge_render.mix_shell`): rendered once when the dialog opens, then a
worker-thread mix per change, the latest color winning. "Apply" generates the full-size shell off the
main thread and only then stores the color, so the card re-draws at once.
"""

import sys
import threading

import cairo
from gi.repository import Adw, Gdk, GLib, Gtk

from openemux.core import cartridge_colors, cartridge_render
from openemux.core.scraper import LABEL_ART, resolve_local_art
from openemux.ui.context_menu import _swatch_widget

#: Width of the cartridge preview, and of the plane's height, in pixels.
PREVIEW_WIDTH = 160
NARROW_PREVIEW_WIDTH = 106
#: The preview's height when stacked: a picture may shrink to nothing, and
#: in a short column it would, so it keeps this much.
NARROW_PREVIEW_HEIGHT = 140
PLANE_HEIGHT = 180

#: Below this the preview stacks above the controls.
NARROW_BREAKPOINT = "max-width: 500sp"

#: How far one arrow key moves the plane's knob.
KEY_STEP = 0.01

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


class SvPlane(Gtk.DrawingArea):
    """Saturation left to right, brightness bottom to top, for one hue."""

    def __init__(self, on_changed):
        super().__init__()
        self.on_changed = on_changed
        self.hue = 0.0
        self.saturation = 0.0
        self.value = 1.0
        self.set_content_height(PLANE_HEIGHT)
        self.set_hexpand(True)
        self.set_focusable(True)
        self.set_can_focus(True)
        self.add_css_class("sv-plane")
        self.set_draw_func(self._draw)
        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", self._on_drag_begin)
        drag.connect("drag-update", self._on_drag_update)
        self.add_controller(drag)
        self._drag_origin = (0.0, 0.0)
        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_key)
        self.add_controller(keys)

    def set_hsv(self, hue, saturation, value):
        self.hue, self.saturation, self.value = hue, saturation, value
        self.queue_draw()

    def _draw(self, _area, cr, width, height):
        radius = 10
        cr.new_sub_path()
        cr.arc(width - radius, radius, radius, -1.5708, 0)
        cr.arc(width - radius, height - radius, radius, 0, 1.5708)
        cr.arc(radius, height - radius, radius, 1.5708, 3.1416)
        cr.arc(radius, radius, radius, 3.1416, 4.7124)
        cr.close_path()
        cr.save()
        cr.clip()
        r, g, b = cartridge_colors.hex_to_rgb(cartridge_colors.hsv_to_hex(self.hue, 1, 1))
        cr.set_source_rgb(r / 255, g / 255, b / 255)
        cr.paint()
        across = cairo.LinearGradient(0, 0, width, 0)
        across.add_color_stop_rgba(0, 1, 1, 1, 1)
        across.add_color_stop_rgba(1, 1, 1, 1, 0)
        cr.set_source(across)
        cr.paint()
        down = cairo.LinearGradient(0, 0, 0, height)
        down.add_color_stop_rgba(0, 0, 0, 0, 0)
        down.add_color_stop_rgba(1, 0, 0, 0, 1)
        cr.set_source(down)
        cr.paint()
        cr.restore()
        x = self.saturation * width
        y = (1 - self.value) * height
        r, g, b = cartridge_colors.hex_to_rgb(
            cartridge_colors.hsv_to_hex(self.hue, self.saturation, self.value)
        )
        cr.arc(x, y, 8, 0, 6.2832)
        cr.set_source_rgb(r / 255, g / 255, b / 255)
        cr.fill_preserve()
        cr.set_line_width(2)
        cr.set_source_rgb(1, 1, 1)
        cr.stroke_preserve()
        cr.set_line_width(1)
        cr.set_source_rgba(0, 0, 0, 0.5)
        cr.stroke()

    def pick(self, x, y):
        """Point (x, y) in the widget as the new saturation and brightness."""
        width = max(1, self.get_width())
        height = max(1, self.get_height())
        self.saturation = min(1.0, max(0.0, x / width))
        self.value = min(1.0, max(0.0, 1 - y / height))
        self.queue_draw()
        self.on_changed(self.saturation, self.value)

    def _on_drag_begin(self, _gesture, x, y):
        self._drag_origin = (x, y)
        self.grab_focus()
        self.pick(x, y)

    def _on_drag_update(self, _gesture, dx, dy):
        self.pick(self._drag_origin[0] + dx, self._drag_origin[1] + dy)

    def _on_key(self, _controller, keyval, _keycode, _state):
        steps = {
            Gdk.KEY_Left: (-KEY_STEP, 0),
            Gdk.KEY_Right: (KEY_STEP, 0),
            Gdk.KEY_Up: (0, KEY_STEP),
            Gdk.KEY_Down: (0, -KEY_STEP),
        }
        if keyval not in steps:
            return False
        ds, dv = steps[keyval]
        self.saturation = min(1.0, max(0.0, self.saturation + ds))
        self.value = min(1.0, max(0.0, self.value + dv))
        self.queue_draw()
        self.on_changed(self.saturation, self.value)
        return True


class CartridgeColorDialog(Adw.Dialog):
    def __init__(self, win, rom, spawn=None):
        super().__init__()
        self.win = win
        self.t = win.t
        self.rom = rom
        self._spawn = spawn or _spawn
        self._syncing = False
        self._preview_busy = False
        self._preview_color = None
        self._sources = None
        self.applied = False
        self.color = start_color(win.config_manager, rom)
        self.hue, self.saturation, self.value = cartridge_colors.hex_to_hsv(self.color)

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
        self._sync_controls()
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
        self.plane = SvPlane(self._on_plane_changed)
        self.plane.update_property(
            [Gtk.AccessibleProperty.LABEL], [t("cartridge_color.dialog.plane")]
        )
        controls.append(self.plane)

        hue_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        hue_label = Gtk.Label(label=t("cartridge_color.dialog.hue"), xalign=0)
        hue_label.add_css_class("dim-label")
        hue_box.append(hue_label)
        self.hue_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 360, 1)
        self.hue_scale.set_draw_value(False)
        self.hue_scale.add_css_class("hue-slider")
        self.hue_scale.update_property(
            [Gtk.AccessibleProperty.LABEL], [t("cartridge_color.dialog.hue")]
        )
        self.hue_scale.connect("value-changed", self._on_hue_changed)
        hue_box.append(self.hue_scale)
        controls.append(hue_box)

        hex_list = Gtk.ListBox()
        hex_list.add_css_class("boxed-list")
        hex_list.set_selection_mode(Gtk.SelectionMode.NONE)
        hex_row = Adw.ActionRow(title=t("cartridge_color.dialog.hex"))
        self.hex_entry = Gtk.Entry()
        self.hex_entry.set_valign(Gtk.Align.CENTER)
        self.hex_entry.set_width_chars(9)
        self.hex_entry.set_max_length(7)
        self.hex_entry.update_property(
            [Gtk.AccessibleProperty.LABEL], [t("cartridge_color.dialog.hex")]
        )
        self.hex_entry.connect("changed", self._on_hex_changed)
        self.hex_entry.connect("activate", lambda _e: self._on_apply(None))
        hex_row.add_suffix(self.hex_entry)
        hex_row.set_activatable_widget(self.hex_entry)
        hex_list.append(hex_row)
        controls.append(hex_list)

        start_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        start_label = Gtk.Label(label=t("cartridge_color.dialog.start_from"), xalign=0)
        start_label.add_css_class("dim-label")
        start_box.append(start_label)
        swatches = Gtk.FlowBox()
        swatches.set_selection_mode(Gtk.SelectionMode.NONE)
        swatches.set_max_children_per_line(12)
        swatches.set_min_children_per_line(6)
        swatches.set_homogeneous(True)
        self.swatch_buttons = {}
        for color_id in _named_ids():
            key = cartridge_colors.color_name_key(color_id)
            button = Gtk.Button()
            button.add_css_class("flat")
            button.add_css_class("color-swatch")
            button.set_halign(Gtk.Align.CENTER)
            button.set_child(_swatch_widget(cartridge_colors.color_swatch(color_id)))
            button.set_tooltip_text(t(key))
            button.update_property([Gtk.AccessibleProperty.LABEL], [t(key)])
            button.connect("clicked", lambda _b, c=color_id: self.pick_named(c))
            swatches.append(button)
            self.swatch_buttons[color_id] = button
        start_box.append(swatches)
        controls.append(start_box)
        self.error_label = Gtk.Label(label=t("cartridge_color.dialog.failed"), xalign=0, wrap=True)
        self.error_label.add_css_class("error")
        self.error_label.set_visible(False)
        controls.append(self.error_label)
        self.body.append(controls)
        return self.body

    # -- the color -------------------------------------------------------

    def set_color(self, color_hex):
        """Make ``color_hex`` the picked color, every control following it."""
        self.color = color_hex
        hue, saturation, value = cartridge_colors.hex_to_hsv(color_hex)
        # A grey has no hue of its own: keep the slider where it was.
        if saturation != 0:
            self.hue = hue
        self.saturation, self.value = saturation, value
        self._sync_controls()

    def pick_named(self, color_id):
        self.set_color(cartridge_colors.parse_hex(cartridge_colors.color_swatch(color_id)))

    def _from_hsv(self):
        self.color = cartridge_colors.hsv_to_hex(self.hue, self.saturation, self.value)
        self._sync_controls()

    def _sync_controls(self):
        self._syncing = True
        try:
            self.plane.set_hsv(self.hue, self.saturation, self.value)
            if round(self.hue_scale.get_value()) != round(self.hue):
                self.hue_scale.set_value(self.hue)
            if cartridge_colors.parse_hex(self.hex_entry.get_text()) != self.color:
                self.hex_entry.set_text(self.color.upper())
            self.hex_entry.remove_css_class("error")
            self.apply_button.set_sensitive(True)
        finally:
            self._syncing = False
        self._schedule_preview()

    def _on_plane_changed(self, saturation, value):
        self.saturation, self.value = saturation, value
        self._from_hsv()

    def _on_hue_changed(self, scale):
        if self._syncing:
            return
        self.hue = scale.get_value()
        self._from_hsv()

    def _on_hex_changed(self, entry):
        if self._syncing:
            return
        parsed = cartridge_colors.parse_hex(entry.get_text())
        if parsed is None:
            # Keep the last good color; only the field says what is wrong.
            entry.add_css_class("error")
            self.apply_button.set_sensitive(False)
            return
        entry.remove_css_class("error")
        self.apply_button.set_sensitive(True)
        if parsed != self.color:
            self.set_color(parsed)

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
        self.win.set_rom_cartridge_color(self.rom, color)
        self.close()
        return GLib.SOURCE_REMOVE


def open_cartridge_color_dialog(win, rom, spawn=None):
    dialog = CartridgeColorDialog(win, rom, spawn=spawn)
    dialog.present(win)
    return dialog
