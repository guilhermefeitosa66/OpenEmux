#!/usr/bin/env python3
"""Draw the site's composed images from the committed captures (issue #686).

Two outputs, both under ``docs/assets/``:

* ``og-opening.png`` -- the link-preview image (``og:image``, 1200x630): the
  opening's composition, the desktop SNES library in its window with the
  Android SNES library over the window's lower right corner, on the site's
  dark stage. Drawn from ``desktop/grid-sfc.png`` and
  ``android/library-snes.png``, so retaking those captures (issues 683 and
  684) and running this again refreshes the preview too.
* ``logo-128.png`` -- the header and favicon logo at the size the page uses
  it; ``logo.png`` is 579 KB, most of the first screen's weight budget.

    tools/site_art.py            write both
    tools/site_art.py --out DIR  write them somewhere else (the tests do)

Needs Pillow, like ``build_site.py --images`` (``requirements-dev.lock``).
Colours are the page's own tokens (``--bg``, ``--bg-2``, ``--panel``,
``--violet``).
"""

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ASSETS = REPO / "docs" / "assets"

OG_SIZE = (1200, 630)
LOGO_SIZE = 128

BG = (8, 6, 15)
BG_2 = (14, 10, 28)
PANEL = (21, 16, 41)
VIOLET = (139, 92, 246)


def _rounded(image, radius):
    """``image`` with its corners cut round (an alpha mask)."""
    from PIL import Image, ImageDraw

    mask = Image.new("L", image.size, 0)
    # Pillow boxes are inclusive: the last pixel is size - 1.
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, image.width - 1, image.height - 1), radius, fill=255)
    out = image.convert("RGBA")
    out.putalpha(mask)
    return out


def _shadow(canvas, box, radius, blur, alpha):
    """A soft dark shadow under ``box`` on ``canvas`` (RGBA, in place)."""
    from PIL import Image, ImageDraw, ImageFilter

    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).rounded_rectangle(box, radius, fill=(0, 0, 0, alpha))
    canvas.alpha_composite(layer.filter(ImageFilter.GaussianBlur(blur)))


def stage_background(size):
    """The opening's dark stage: the page's gradient plus its violet glow."""
    from PIL import Image, ImageDraw, ImageFilter

    width, height = size
    bg = Image.new("RGB", size, BG)
    draw = ImageDraw.Draw(bg)
    for y in range(height):
        t = min(1.0, y / (height * 0.78))
        draw.line((0, y, width, y), fill=tuple(round(a + (b - a) * t) for a, b in zip(BG_2, BG)))
    glow = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((width * 0.05, -height * 0.45, width * 0.75, height * 0.55),
                                 fill=(*VIOLET, 110))
    bg = bg.convert("RGBA")
    bg.alpha_composite(glow.filter(ImageFilter.GaussianBlur(120)))
    return bg


def og_image(desktop_path, phone_path, size=OG_SIZE):
    """The 1200x630 link preview of the opening's final composition."""
    from PIL import Image, ImageDraw

    width, height = size
    canvas = stage_background(size)

    # The desktop window: the capture already carries the app's header bar
    # and window buttons, so the frame is only the rounded corners and the
    # shadow.
    win_w = round(width * 0.68)
    with Image.open(desktop_path) as shot:
        window = shot.convert("RGB").resize((win_w, round(shot.height * win_w / shot.width)), Image.LANCZOS)
    window = _rounded(window, 12)
    win_x, win_y = round(width * 0.06), round(height * 0.06)
    _shadow(canvas, (win_x, win_y + 24, win_x + win_w, win_y + window.height + 24), 12, 30, 190)
    canvas.alpha_composite(window, (win_x, win_y))

    # The phone: a 6 px --panel bezel, landing over the window's lower right
    # corner as on the page.
    phone_h = round(height * 0.80)
    bezel = 6
    with Image.open(phone_path) as shot:
        shot = shot.convert("RGB")
        inner_h = phone_h - 2 * bezel
        inner_w = round(shot.width * inner_h / shot.height)
        # Concentric with the body: its radius minus the 1 px outline and the bezel.
        shot = _rounded(shot.resize((inner_w, inner_h), Image.LANCZOS), 22 - 1 - bezel)
    phone = Image.new("RGBA", (inner_w + 2 * bezel, phone_h), (0, 0, 0, 0))
    ImageDraw.Draw(phone).rounded_rectangle((0, 0, phone.width - 1, phone_h - 1), 22, fill=PANEL,
                                            outline=(52, 46, 72), width=1)
    phone.alpha_composite(shot, (bezel, bezel))
    phone_x = width - round(width * 0.07) - phone.width
    phone_y = height - round(height * 0.06) - phone_h
    _shadow(canvas, (phone_x, phone_y + 18, phone_x + phone.width, phone_y + phone_h + 18), 22, 24, 200)
    canvas.alpha_composite(phone, (phone_x, phone_y))
    return canvas.convert("RGB")


def small_logo(logo_path, side=LOGO_SIZE):
    """``logo.png`` fitted in a ``side`` px square, transparency kept."""
    from PIL import Image

    with Image.open(logo_path) as logo:
        logo = logo.convert("RGBA")
        scale = side / max(logo.size)
        fitted = logo.resize((round(logo.width * scale), round(logo.height * scale)), Image.LANCZOS)
    square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    square.alpha_composite(fitted, ((side - fitted.width) // 2, (side - fitted.height) // 2))
    return square


def build(assets=None, out=None):
    """Write both images into ``out`` (default: ``assets``); returns their paths."""
    try:
        import PIL  # noqa: F401
    except ImportError:
        raise SystemExit("site_art.py needs Pillow: pip install -r requirements-dev.lock") from None
    assets = Path(assets) if assets is not None else ASSETS
    out = Path(out) if out is not None else assets
    out.mkdir(parents=True, exist_ok=True)
    og = out / "og-opening.png"
    og_image(assets / "desktop" / "grid-sfc.png", assets / "android" / "library-snes.png").save(
        og, "PNG", optimize=True)
    logo = out / "logo-128.png"
    small_logo(assets / "logo.png").save(logo, "PNG", optimize=True)
    return [og, logo]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", help="write the images here instead of docs/assets/")
    args = parser.parse_args(argv)
    for path in build(out=args.out):
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
