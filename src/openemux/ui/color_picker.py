"""A color picker: saturation/brightness plane, hue slider and hex field.

Made for the Custom Color dialog (issue 983) and shared with the theme editor
(issue 1011). GTK 4 has no color wheel, and its own color chooser cannot sit
inside another dialog, so the plane is drawn here, the way GNOME's color
editor lays it out.
"""

from gi.repository import Adw, Gdk, Gtk

import cairo

from openemux.core import cartridge_colors

#: The plane's height, in pixels.
PLANE_HEIGHT = 180

#: How far one arrow key moves the plane's knob.
KEY_STEP = 0.01


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


class ColorPicker(Gtk.Box):
    """The three controls, kept in step around one ``#rrggbb`` color.

    ``on_changed(color)`` runs whenever the color changes, whatever moved
    it; ``on_validity(valid)`` when the hex field starts or stops holding
    something that is not a color (the last good color is kept meanwhile);
    ``on_activate()`` when Enter is pressed in the hex field.
    """

    def __init__(self, t, color, on_changed=None, on_validity=None, on_activate=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.on_changed = on_changed
        self.on_validity = on_validity
        self._syncing = False
        self.color = color
        self.hue, self.saturation, self.value = cartridge_colors.hex_to_hsv(color)

        self.plane = SvPlane(self._on_plane_changed)
        self.plane.update_property(
            [Gtk.AccessibleProperty.LABEL], [t("cartridge_color.dialog.plane")]
        )
        self.append(self.plane)

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
        self.append(hue_box)

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
        if on_activate is not None:
            self.hex_entry.connect("activate", lambda _e: on_activate())
        hex_row.add_suffix(self.hex_entry)
        hex_row.set_activatable_widget(self.hex_entry)
        hex_list.append(hex_row)
        self.append(hex_list)
        self._sync_controls(notify=False)

    def set_color(self, color_hex):
        """Make ``color_hex`` the picked color, every control following it."""
        self.color = color_hex
        hue, saturation, value = cartridge_colors.hex_to_hsv(color_hex)
        # A grey has no hue of its own: keep the slider where it was.
        if saturation != 0:
            self.hue = hue
        self.saturation, self.value = saturation, value
        self._sync_controls()

    def _from_hsv(self):
        self.color = cartridge_colors.hsv_to_hex(self.hue, self.saturation, self.value)
        self._sync_controls()

    def _sync_controls(self, notify=True):
        self._syncing = True
        try:
            self.plane.set_hsv(self.hue, self.saturation, self.value)
            if round(self.hue_scale.get_value()) != round(self.hue):
                self.hue_scale.set_value(self.hue)
            if cartridge_colors.parse_hex(self.hex_entry.get_text()) != self.color:
                self.hex_entry.set_text(self.color.upper())
            self.hex_entry.remove_css_class("error")
        finally:
            self._syncing = False
        if notify:
            self._validity(True)
            if self.on_changed is not None:
                self.on_changed(self.color)

    def _validity(self, valid):
        if self.on_validity is not None:
            self.on_validity(valid)

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
            self._validity(False)
            return
        entry.remove_css_class("error")
        self._validity(True)
        if parsed != self.color:
            self.set_color(parsed)
