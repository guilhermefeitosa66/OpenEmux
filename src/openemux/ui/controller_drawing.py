"""The console's controller, drawn on the input page, as a way in to remapping (issue 815).

``core/controller_layouts.py`` says where each control of a console's
controller sits on its art and which desktop actions it remaps. This widget
draws that art -- the background and each control's image at its rect, scaled
together to the width it is given, never past :data:`MAX_WIDTH` -- and lays a
transparent, focusable button over every control that remaps something. A
D-pad or a stick gets four of them, one per arm. Activating a button hands its
action to ``on_activate``; what happens then (the capture, the prompt, the
commit) belongs to the preferences dialog, which drives this widget back
through :meth:`ControllerDrawing.set_action_state` and
:meth:`ControllerDrawing.set_current`.

A control that remaps nothing on the desktop is drawn all the same and gets an
inert, non-focusable area carrying a tooltip that says so.

The geometry lives in ``core/controller_targets.py``, plain Python, so the
arithmetic is tested without a display.
"""

import logging

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Graphene", "1.0")
gi.require_version("Gsk", "4.0")
from gi.repository import Gdk, GLib, Graphene, Gsk, Gtk

from openemux.core.controller_targets import MAX_WIDTH, MIN_WIDTH, drawn_size, target_box, targets_for

logger = logging.getLogger(__name__)

def _load_texture(path):
    try:
        return Gdk.Texture.new_from_filename(str(path))
    except GLib.Error as error:
        logger.warning("Controller art %s could not be loaded: %s", path, error.message)
        return None


def _rect(x, y, width, height):
    rect = Gdk.Rectangle()
    rect.x, rect.y, rect.width, rect.height = x, y, width, height
    return rect


class ControllerDrawing(Gtk.Widget):
    """A console's controller art with a target over each remappable control."""

    __gtype_name__ = "OpenEmuxControllerDrawing"

    def __init__(self, layout, on_activate, on_highlight=None, not_remappable_text=""):
        super().__init__()
        self.add_css_class("controller-drawing")
        self.set_overflow(Gtk.Overflow.HIDDEN)
        self._layout = layout
        self._on_activate = on_activate
        self._on_highlight = on_highlight or (lambda _action: None)
        self._not_remappable_text = not_remappable_text
        self._layers = []
        background = _load_texture(layout.background)
        if background is not None:
            self._layers.append((background, 0, 0, layout.width, layout.height))
        for element in layout.elements:
            for role in ("base", "pad", "button", "knob"):
                path = element.images.get(role)
                texture = _load_texture(path) if path else None
                if texture is not None:
                    self._layers.append(
                        (texture, element.x, element.y, element.width, element.height)
                    )

        self.targets = targets_for(layout)
        self._children = []
        #: action -> the buttons that remap it (a stick and a pad can share one).
        self.buttons = {}
        for target in self.targets:
            child = self._make_child(target)
            child.set_parent(self)
            self._children.append((target, child))

    # -- children ----------------------------------------------------------

    def _make_child(self, target):
        if target.action is None:
            # Hover only: a tooltip, never in the Tab order.
            area = Gtk.Box()
            area.set_focusable(False)
            area.add_css_class("controller-inert")
            area.set_tooltip_text(self._not_remappable_text)
            return area
        button = Gtk.Button()
        button.add_css_class("controller-target")
        if target.round:
            button.add_css_class("round")
        # The handlers hold the callbacks, never this widget: a closure on a
        # child that points back at its parent is a cycle Python cannot see
        # through, and every console change would leak a drawing and its art.
        action, activate, highlight = target.action, self._on_activate, self._on_highlight
        button.connect("clicked", lambda _b: activate(action))
        motion = Gtk.EventControllerMotion()
        motion.connect("enter", lambda *_a: highlight(action))
        motion.connect("leave", lambda *_a: highlight(None))
        button.add_controller(motion)
        focus = Gtk.EventControllerFocus()
        focus.connect("enter", lambda *_a: highlight(action))
        focus.connect("leave", lambda *_a: highlight(None))
        button.add_controller(focus)
        self.buttons.setdefault(target.action, []).append(button)
        return button

    def do_focus(self, direction):
        """Tab walks the targets in :func:`targets_for`'s order.

        GTK's own focus chain sorts children by where they sit on screen, which
        interleaves a pad's arms with the face buttons beside it.
        """
        if direction not in (Gtk.DirectionType.TAB_FORWARD, Gtk.DirectionType.TAB_BACKWARD):
            return Gtk.Widget.do_focus(self, direction)
        children = [child for _target, child in self._children]
        if direction == Gtk.DirectionType.TAB_BACKWARD:
            children.reverse()
        current = self.get_focus_child()
        start = children.index(current) + 1 if current in children else 0
        return any(child.child_focus(direction) for child in children[start:])

    def do_dispose(self):
        for _target, child in self._children:
            child.unparent()
        self._children = []
        self.buttons = {}
        Gtk.Widget.do_dispose(self)

    # -- what the dialog tells it ------------------------------------------

    def set_action_state(self, action, text, enabled):
        """Tooltip, accessible name and sensitivity of `action`'s targets."""
        for button in self.buttons.get(action, ()):
            button.set_tooltip_text(text)
            button.update_property([Gtk.AccessibleProperty.LABEL], [text])
            button.set_sensitive(enabled)
            button.set_focusable(enabled)

    def set_current(self, action):
        """Mark `action`'s targets as the one being captured (None: none)."""
        for button_action, buttons in self.buttons.items():
            for button in buttons:
                if button_action == action:
                    button.add_css_class("current")
                else:
                    button.remove_css_class("current")

    # -- layout --------------------------------------------------------------

    def do_get_request_mode(self):
        return Gtk.SizeRequestMode.HEIGHT_FOR_WIDTH

    def do_measure(self, orientation, for_size):
        layout = self._layout
        if orientation == Gtk.Orientation.HORIZONTAL:
            natural = min(MAX_WIDTH, layout.width)
            return min(MIN_WIDTH, natural), natural, -1, -1
        width = for_size if for_size >= 0 else MAX_WIDTH
        _w, height, _scale = drawn_size(layout.width, layout.height, width)
        return height, height, -1, -1

    def _geometry(self, width):
        drawn_w, drawn_h, scale = drawn_size(self._layout.width, self._layout.height, width)
        offset_x = max(0, (width - drawn_w) // 2)
        return drawn_w, drawn_h, scale, offset_x

    def do_size_allocate(self, width, height, baseline):
        drawn_w, drawn_h, scale, offset_x = self._geometry(width)
        for target, child in self._children:
            # GTK wants every child measured before it is allocated.
            child.measure(Gtk.Orientation.HORIZONTAL, -1)
            child.measure(Gtk.Orientation.VERTICAL, -1)
            child.size_allocate(_rect(*target_box(target, scale, offset_x, drawn_w, drawn_h)), -1)

    def do_snapshot(self, snapshot):
        _drawn_w, _drawn_h, scale, offset_x = self._geometry(self.get_width())
        for texture, x, y, w, h in self._layers:
            bounds = Graphene.Rect().init(offset_x + x * scale, y * scale, w * scale, h * scale)
            snapshot.append_scaled_texture(texture, Gsk.ScalingFilter.TRILINEAR, bounds)
        for _target, child in self._children:
            self.snapshot_child(child, snapshot)
