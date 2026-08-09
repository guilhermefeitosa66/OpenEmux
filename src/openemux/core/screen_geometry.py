"""Geometry for the embedded-RetroArch game screen (POC).

Pure math, no GTK: the game-window widget asks this module where the
RetroArch X11 window should sit inside its allocation, both in plain mode
(the whole allocation) and in CRT-frame mode (inside the TV's screen
cutout).

The frame constants describe ``tv-frame.png``: the screen area is a
transparent cutout in the artwork, measured as the bounding box of the
alpha-0 region around the image center. The cutout has rounded CRT
corners, so the video rect is inset a little past the bounding box --
the straight edges of the cutout start ~1.5% in from the bbox.
"""

#: tv-frame.png pixel dimensions (width, height).
FRAME_IMAGE_SIZE = (1633, 1559)

#: The screen cutout inside the frame image, normalized to image size:
#: (x, y, width, height) as fractions.
FRAME_SCREEN_RECT = (0.1121, 0.1097, 0.7820, 0.6042)

#: Fraction of the cutout's own size to inset the video on each edge, so
#: the rectangular video tucks behind the cutout's rounded corners.
FRAME_SCREEN_INSET = 0.015


def fit_contain(content_w, content_h, box_w, box_h):
    """Scale content into a box keeping aspect; centered (x, y, w, h)."""
    if content_w <= 0 or content_h <= 0 or box_w <= 0 or box_h <= 0:
        return (0.0, 0.0, 0.0, 0.0)
    scale = min(box_w / content_w, box_h / content_h)
    w = content_w * scale
    h = content_h * scale
    return ((box_w - w) / 2.0, (box_h - h) / 2.0, w, h)


def frame_paint_rect(alloc_w, alloc_h):
    """Where the TV frame artwork is drawn inside the widget allocation."""
    img_w, img_h = FRAME_IMAGE_SIZE
    return fit_contain(img_w, img_h, alloc_w, alloc_h)


def screen_rect(alloc_w, alloc_h, frame_enabled):
    """Where the game video goes, in widget coordinates: (x, y, w, h)."""
    if not frame_enabled:
        return (0.0, 0.0, float(alloc_w), float(alloc_h))
    fx, fy, fw, fh = frame_paint_rect(alloc_w, alloc_h)
    rx, ry, rw, rh = FRAME_SCREEN_RECT
    hx = rx + rw * FRAME_SCREEN_INSET
    hy = ry + rh * FRAME_SCREEN_INSET
    hw = rw * (1.0 - 2.0 * FRAME_SCREEN_INSET)
    hh = rh * (1.0 - 2.0 * FRAME_SCREEN_INSET)
    return (fx + hx * fw, fy + hy * fh, hw * fw, hh * fh)
