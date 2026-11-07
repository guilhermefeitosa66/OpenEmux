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

The widget takes the whole width of its card, and the art is narrower than
that. What shows on either side is the controller's own body, carried on from
the edges of the art (``controller_targets.body_stops``), so the card reads as
the controller and not as a picture pasted on a card.

A target can be *lit* (issue 816): the control's own image is drawn again,
brightened, inside the target's shape, with a glow around it in the widget's
``color`` -- which the stylesheet sets to the accent -- and the target takes
the ``lit`` style class. The dialog lights the button being captured and,
while nothing is, every button whose input is held down
(:meth:`ControllerDrawing.set_lit`). Nothing is animated.

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

from openemux.core.controller_targets import (
    MAX_WIDTH,
    MIN_WIDTH,
    body_stops,
    drawn_size,
    target_box,
    targets_for,
)

logger = logging.getLogger(__name__)

#: How much brighter a lit control's own image is drawn: every channel scaled
#: and then lifted, so a black D-pad lights as visibly as a white button.
LIT_SCALE = 1.2
LIT_LIFT = 0.16
#: The corner radius of a lit target that is not round, as the stylesheet has it.
LIT_RADIUS = 8
#: The glow around a lit target: the target's shape grown by so many pixels
#: and filled with the accent at that opacity, the widest and faintest first,
#: so it fades outwards. Whole shapes, one under the other, rather than rings
#: or a blurred shadow: both of those are drawn in slices, and around a fully
#: round target the slices meet in visible lines at its four sides.
LIT_GLOW = ((13, 0.2), (9, 0.4))


def _load_texture(path):
    try:
        return Gdk.Texture.new_from_filename(str(path))
    except GLib.Error as error:
        logger.warning("Controller art %s could not be loaded: %s", path, error.message)
        return None


def _body_gradients(texture):
    """The body colour down the left and the right edge of the background.

    Two lists of ``Gsk.ColorStop``, ready for a vertical gradient each.
    """
    downloader = Gdk.TextureDownloader.new(texture)
    downloader.set_format(Gdk.MemoryFormat.R8G8B8A8)
    data, stride = downloader.download_bytes()
    pixels = data.get_data()
    width, height = texture.get_width(), texture.get_height()
    sides = []
    for right in (False, True):
        stops = []
        for offset, (red, green, blue) in body_stops(pixels, width, height, stride, right=right):
            stop = Gsk.ColorStop()
            stop.offset = offset
            color = Gdk.RGBA()
            color.red, color.green, color.blue, color.alpha = red / 255, green / 255, blue / 255, 1.0
            stop.color = color
            stops.append(stop)
        sides.append(stops)
    return sides


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
        #: element id -> its own layers, to draw a lit control again brightened.
        self._element_layers = {}
        #: The actions lit right now (see :meth:`set_lit`).
        self._lit = frozenset()
        #: The body colour beside the art: (left stops, right stops), or None
        #: when the background did not load and there is no body to carry on.
        self._body = None
        background = _load_texture(layout.background)
        if background is not None:
            self._layers.append((background, 0, 0, layout.width, layout.height))
            self._body = _body_gradients(background)
        for element in layout.elements:
            for role in ("base", "pad", "button", "knob"):
                path = element.images.get(role)
                texture = _load_texture(path) if path else None
                if texture is not None:
                    layer = (texture, element.x, element.y, element.width, element.height)
                    self._layers.append(layer)
                    self._element_layers.setdefault(element.id, []).append(layer)

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

    def set_lit(self, actions):
        """Light the targets of `actions`, and only those (issue 816).

        The control's own image is drawn brightened inside each lit target,
        with a glow around it, and the target gets the ``lit`` style class. An
        action the drawing has no target for is ignored.
        """
        lit = frozenset(action for action in actions if action in self.buttons)
        if lit == self._lit:
            return
        self._lit = lit
        for action, buttons in self.buttons.items():
            for button in buttons:
                if action in lit:
                    button.add_css_class("lit")
                else:
                    button.remove_css_class("lit")
        self.queue_draw()

    @property
    def lit(self):
        """The actions lit right now."""
        return self._lit

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

    def _snapshot_body(self, snapshot, stops, x, width, height):
        """A stretch of the card in the body's colour: a top-to-bottom gradient."""
        snapshot.append_linear_gradient(
            Graphene.Rect().init(x, 0, width, height),
            Graphene.Point().init(x, 0),
            Graphene.Point().init(x, height),
            stops,
        )

    def do_snapshot(self, snapshot):
        width = self.get_width()
        drawn_w, drawn_h, scale, offset_x = self._geometry(width)
        if self._body is not None:
            # The body across the whole width, each side's shade up to the
            # middle of the art. Beside the art it is what shows; under it, it
            # keeps the art's last row -- covered only in part when the scaled
            # height is not a whole number -- from letting the card through.
            left, right = self._body
            middle = offset_x + drawn_w / 2
            self._snapshot_body(snapshot, left, 0, middle, drawn_h)
            self._snapshot_body(snapshot, right, middle, width - middle, drawn_h)
        for texture, x, y, w, h in self._layers:
            bounds = Graphene.Rect().init(offset_x + x * scale, y * scale, w * scale, h * scale)
            snapshot.append_scaled_texture(texture, Gsk.ScalingFilter.TRILINEAR, bounds)
        if self._lit:
            brighten = Graphene.Matrix().init_scale(LIT_SCALE, LIT_SCALE, LIT_SCALE)
            lift = Graphene.Vec4().init(LIT_LIFT, LIT_LIFT, LIT_LIFT, 0)
            accent = self.get_color()
            for target, _child in self._children:
                if target.action not in self._lit:
                    continue
                x, y, w, h = target_box(target, scale, offset_x, drawn_w, drawn_h)
                radius = min(w, h) / 2 if target.round else LIT_RADIUS
                # The glow: the accent around the target, fading outwards.
                for grow, opacity in LIT_GLOW:
                    bounds = Graphene.Rect().init(x - grow, y - grow, w + 2 * grow, h + 2 * grow)
                    halo = Gsk.RoundedRect()
                    halo.init_from_rect(bounds, radius + grow)
                    color = Gdk.RGBA()
                    color.red, color.green, color.blue = accent.red, accent.green, accent.blue
                    color.alpha = opacity
                    snapshot.push_rounded_clip(halo)
                    snapshot.append_color(color, bounds)
                    snapshot.pop()
                # The control's own image again, brighter, and only inside the
                # target: one arm of a pad lights, not the whole pad.
                shape = Gsk.RoundedRect()
                shape.init_from_rect(Graphene.Rect().init(x, y, w, h), radius)
                snapshot.push_rounded_clip(shape)
                snapshot.push_color_matrix(brighten, lift)
                for texture, ex, ey, ew, eh in self._element_layers.get(target.element_id, ()):
                    bounds = Graphene.Rect().init(
                        offset_x + ex * scale, ey * scale, ew * scale, eh * scale
                    )
                    snapshot.append_scaled_texture(texture, Gsk.ScalingFilter.TRILINEAR, bounds)
                snapshot.pop()
                snapshot.pop()
        for _target, child in self._children:
            self.snapshot_child(child, snapshot)
