#!/usr/bin/env python3
"""Render OpenEmux's built-in bezel: the "Simple" frame (issue #507).

A bezel decorates the black bars beside a 4:3 game on a wide window. It is
drawn by RetroArch as one more image of the in-game bar's overlay (see
``core/bezels.py`` and ``overlay_bar.write_bezel_overlay``), so it is a 16:9
picture with a fully transparent 4:3 hole in the middle, where the game shows
through: 640x360, hole 480x360.

Small on purpose: RetroArch decodes the image once for every page of the
bar (64 of them) and keeps each copy, so a 1920x1080 frame would hold about
half a gigabyte. A soft gradient scales up to any screen without showing it.

The art is OpenEmux's own, drawn here from an SVG: a dark radial gradient, a
thin rim around the hole and a soft shadow falling into the frame. No
third-party bezel pack is bundled -- their licenses are mixed or unstated --
and a user who wants one picks it with "Custom image...".

Output is committed (``src/openemux/data/bezels``): building it needs
GdkPixbuf's SVG loader, which the app does not. Run it again after changing
anything here:

    /usr/bin/python3 scripts/build_bezels.py
"""
from pathlib import Path

import gi

gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "src" / "openemux" / "data" / "bezels"
#: Must fit in ``bezels.MAX_DECODED``.
W, H = 640, 360
#: The 4:3 hole the game shows through. Must agree with the geometry in
#: ``core/bezels.py``: the bezel is the 16:9 box around the 4:3 one.
HOLE_W = H * 4 // 3
HOLE_X = (W - HOLE_W) // 2
RIM = 2
SHADOW = 10


def simple_svg():
    hole = f"M{HOLE_X},0 h{HOLE_W} v{H} h-{HOLE_W} z"
    frame = f"M0,0 h{W} v{H} h-{W} z {hole}"
    left, right = HOLE_X, HOLE_X + HOLE_W
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}">
  <defs>
    <radialGradient id="bg" cx="50%" cy="50%" r="70%">
      <stop offset="0" stop-color="#3a3a40"/>
      <stop offset="1" stop-color="#141416"/>
    </radialGradient>
    <linearGradient id="shadow-l" x1="1" y1="0" x2="0" y2="0">
      <stop offset="0" stop-color="#000" stop-opacity="0.55"/>
      <stop offset="1" stop-color="#000" stop-opacity="0"/>
    </linearGradient>
    <linearGradient id="shadow-r" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="#000" stop-opacity="0.55"/>
      <stop offset="1" stop-color="#000" stop-opacity="0"/>
    </linearGradient>
  </defs>
  <path d="{frame}" fill="url(#bg)" fill-rule="evenodd"/>
  <rect x="{left - RIM - SHADOW}" y="0" width="{SHADOW}" height="{H}" fill="url(#shadow-l)"/>
  <rect x="{right + RIM}" y="0" width="{SHADOW}" height="{H}" fill="url(#shadow-r)"/>
  <rect x="{left - RIM}" y="0" width="{RIM}" height="{H}" fill="#4a4a52"/>
  <rect x="{right}" y="0" width="{RIM}" height="{H}" fill="#4a4a52"/>
</svg>"""


def render(svg, path):
    loader = GdkPixbuf.PixbufLoader.new_with_type("svg")
    loader.write(svg.encode())
    loader.close()
    loader.get_pixbuf().savev(str(path), "png", [], [])


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    render(simple_svg(), OUT / "simple.png")
    print(f"wrote {OUT / 'simple.png'}")


if __name__ == "__main__":
    main()
