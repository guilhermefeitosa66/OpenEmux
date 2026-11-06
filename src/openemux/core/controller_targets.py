"""Where the targets go on a controller drawing (issue 815).

``ui/controller_drawing.py`` draws a console's controller art
(``controller_layouts.layout_for``) and lays a button over each control that
remaps something. This is that widget's arithmetic, with no GTK in it: which
targets a layout has and in which order the keyboard walks them, how big the
art is drawn in a given width, where each target lands on screen, and which
colour the controller's body has down each side of the art.
"""

import math
from dataclasses import dataclass

#: The widest the drawing is ever drawn: a portrait controller at the dialog's
#: full width would be taller than the window.
MAX_WIDTH = 360
#: The narrowest it asks for, so it never forces the dialog wider.
MIN_WIDTH = 120
#: The smallest a target is on screen, either way, whatever the art's size.
MIN_TARGET = 24
#: Controls whose tops fall in the same band of this many art pixels read as
#: one row when ordering the targets for the keyboard.
ROW_BAND = 32
#: How many shades describe the body's colour from the top of the art to the
#: bottom: the bodies carry a soft top-to-bottom gradient, not one flat colour.
BODY_STOPS = 16
#: How many pixel columns at the edge of the art are read for the body colour.
#: Kept thin: on some consoles a control's shadow starts a few pixels in.
BODY_BAND = 2


@dataclass(frozen=True)
class Target:
    """One place on the drawing: a control, or one arm of a pad or stick."""

    #: The desktop action it remaps, or None for a control that remaps nothing.
    action: object
    #: The control's id in the layout.
    element_id: str
    #: Its rect in the art's own pixels.
    x: float
    y: float
    width: float
    height: float
    #: Drawn as a circle (a square-ish button) rather than a rounded box.
    round: bool = False


def _arms(element):
    """The four arms of a pad or a stick, as (action, x, y, w, h), in reading order."""
    up, down, left, right = element.actions
    third_w, third_h = element.width / 3, element.height / 3
    x, y = element.x, element.y
    return (
        (up, x + third_w, y, third_w, third_h),
        (left, x, y + third_h, third_w, third_h),
        (right, x + 2 * third_w, y + third_h, third_w, third_h),
        (down, x + third_w, y + 2 * third_h, third_w, third_h),
    )


def _is_round(element):
    return element.type == "button" and abs(element.width - element.height) <= 0.1 * max(
        element.width, element.height
    )


def targets_for(layout):
    """Every target of `layout`, in the order Tab walks them.

    Controls are taken row by row (tops in the same :data:`ROW_BAND` band
    share a row), left to right; a pad's arms follow each other, up, left,
    right, down. A pad or stick with its four directions gets an arm each; a
    control with exactly one action, one target over its whole rect; anything
    else is drawn but not remappable.
    """
    elements = sorted(layout.elements, key=lambda e: (e.y // ROW_BAND, e.x))
    targets = []
    for element in elements:
        if element.type in ("dpad", "stick") and len(element.actions) == 4:
            for action, x, y, w, h in _arms(element):
                targets.append(Target(action, element.id, x, y, w, h))
        elif len(element.actions) == 1:
            targets.append(Target(
                element.actions[0], element.id,
                element.x, element.y, element.width, element.height, _is_round(element),
            ))
        else:
            targets.append(Target(
                None, element.id, element.x, element.y, element.width, element.height,
            ))
    return targets


def drawn_size(layout_width, layout_height, available_width):
    """The size the art is drawn at in `available_width`: (width, height, scale)."""
    width = max(1, min(available_width, MAX_WIDTH, layout_width))
    scale = width / layout_width
    return width, math.ceil(layout_height * scale), scale


def target_box(target, scale, offset_x, drawn_width, drawn_height):
    """Where `target` lands on screen: (x, y, w, h), whole pixels.

    Scaled with the art, grown about its centre to :data:`MIN_TARGET` when it
    would be smaller, and kept inside the drawing.
    """
    w = max(MIN_TARGET, target.width * scale)
    h = max(MIN_TARGET, target.height * scale)
    cx = (target.x + target.width / 2) * scale
    cy = (target.y + target.height / 2) * scale
    w, h = min(w, drawn_width), min(h, drawn_height)
    x = min(max(0, cx - w / 2), drawn_width - w)
    y = min(max(0, cy - h / 2), drawn_height - h)
    return round(offset_x + x), round(y), round(w), round(h)


def body_stops(pixels, width, height, stride, right=False):
    """The body colour down one side of the art: [(offset, (r, g, b)), ...].

    `pixels` is the background as RGBA rows of `stride` bytes. The art is
    narrower than the card it sits in, and whatever shows beside it has to be
    the controller's own body or the drawing reads as a picture pasted on a
    card. The body is a soft gradient with a faint texture, so one colour would
    leave a seam; this reads the art's left edge (its right one with `right`)
    in :data:`BODY_STOPS` slices, top to bottom, and answers the average colour
    of each at the slice's centre (offset 0 is the top, 1 the bottom), ready to
    be the stops of a vertical gradient. Averaging a whole slice also smooths
    the texture away, a pattern of diagonal stripes included.
    """
    band = min(BODY_BAND, width)
    first = (width - band) * 4 if right else 0
    slices = min(BODY_STOPS, height)
    stops = []
    for index in range(slices):
        top, bottom = index * height // slices, (index + 1) * height // slices
        total = [0, 0, 0]
        for y in range(top, bottom):
            start = y * stride + first
            for x in range(band):
                for channel in range(3):
                    total[channel] += pixels[start + x * 4 + channel]
        count = (bottom - top) * band
        stops.append((
            (top + bottom) / 2 / height,
            tuple(round(value / count) for value in total),
        ))
    return stops
