#!/usr/bin/env python3
"""Fictional gameplay frames for the demo catalogue (issue #553).

The site's gameplay shots and the promo video used to show real homebrew. They
now show the demo library's own invented games "running": for one title per
console, this draws a frame at the console's native resolution, in the era
style its cover art already uses (``tools/demo_library.py``), with a HUD on
top. Nintendo DS frames are both screens stacked, the top one playing and the
bottom one a menu.

    .venv/bin/python tools/demo_gameplay.py OUT_DIR [--scale N] [--frames N]
                                                    [--console ID ...]

writes ``OUT_DIR/<console>-<slug>.png`` (``-NN`` per frame with ``--frames``:
the camera pans up the scene, a short clip for the promo video). ``--scale``
enlarges by an integer factor with nearest-neighbour sampling, so the pixels
stay sharp. Deterministic and offline; the PNGs carry no metadata.
"""

import argparse
import importlib.util
import sys
from pathlib import Path

_LIBRARY = Path(__file__).resolve().parent / "demo_library.py"
_spec = importlib.util.spec_from_file_location("demo_library", _LIBRARY)
demo_library = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(demo_library)

from gi.repository import GdkPixbuf, GLib  # noqa: E402  (gi set up by demo_library)

#: The title shown playing, per console: one each, taken from the catalogue.
GAMEPLAY = {
    "FC": "Super Plumber Man",
    "GB": "Island Hero Quest",
    "GBA": "Cosmic Fox Pilot",
    "SFC": "Robot Man X",
    "MD": "Barbarian Axe Quest",
    "N64": "Jungle Island Rescue",
    "NDS": "Dual Screen Dragon",
    "PS": "Cyber Fist Arena",
}

#: Native output size (width, height) of one screen. FC is the 224 visible
#: lines an NTSC set shows, not the 240 the PPU draws.
NATIVE = {
    "FC": (256, 224), "GB": (160, 144), "GBA": (240, 160), "SFC": (256, 224),
    "MD": (320, 224), "N64": (320, 240), "NDS": (256, 192), "PS": (320, 240),
}

#: The bitmap font's cell, in native pixels.
HUD_CELL = 1
#: The pixel-art cell at native resolution: the labels' cell is sized for a
#: 512-pixel label and would turn a 160-pixel screen into a dozen blocks.
PIXEL_CELL = 2
#: Height of the HUD strip, in native pixels.
HUD_H = 11
#: How far the camera travels over a clip, as a share of the room there is
#: around the framed view.
PAN = 0.6
#: The Nintendo DS lower screen's menu, per genre of the title shown.
DS_MENU = {"rpg": ["ATTACK", "MAGIC", "ITEM", "RUN"]}
DS_MENU_DEFAULT = ["PLAY", "MAP", "ITEM", "SAVE"]


def size(console):
    """(width, height) of the whole frame: both screens for the DS."""
    w, h = NATIVE[console]
    return (w, h * 2) if console == "NDS" else (w, h)


def palette(console):
    """The playing title's palette, the same one its cover and label use."""
    title = GAMEPLAY[console]
    return demo_library.palette_for(console, demo_library.TITLES[console].index(title))


def view(console, step, steps):
    """The window of the scene the camera shows at ``step`` of ``steps``.

    Framed on the scene's focal shapes, like the cartridge label, and panning
    across the room left around the framed view (sideways or up and down,
    whichever has more) as the clip runs.
    """
    w, h = NATIVE[console]
    title = GAMEPLAY[console]
    shapes = demo_library.scene(title, demo_library.TITLES[console].index(title))
    x, y, vw, vh = demo_library.crop_view(shapes, w / (h - HUD_H))
    room_x = min(x, demo_library.SCENE_W - vw - x)
    room_y = min(y, demo_library.SCENE_H - vh - y)
    t = 2 * step / (steps - 1) - 1 if steps > 1 else 0
    if room_x >= room_y:
        return x + room_x * PAN * t, y, vw, vh
    return x, y + room_y * PAN * t, vw, vh


def hud(console, step, width):
    """The HUD strip: score on the left, lives on the right."""
    pal = palette(console)
    score = f"SCORE {1200 + 50 * step:06d}"
    lives = "X3"
    left = 4 + demo_library.pixel_text_width(score, HUD_CELL) // 2
    right = width - 4 - demo_library.pixel_text_width(lives, HUD_CELL) // 2
    return (
        f'<rect x="0" y="0" width="{width}" height="{HUD_H}" fill="{pal["dark"]}"/>'
        + demo_library.pixel_text([score], left, 2, HUD_CELL, pal["light"])
        + demo_library.pixel_text([lives], right, 2, HUD_CELL, pal["accent"])
    )


def screen(console, step, steps):
    """One playing screen: the scene under the HUD, as an SVG fragment."""
    title = GAMEPLAY[console]
    index = demo_library.TITLES[console].index(title)
    w, h = NATIVE[console]
    shapes = demo_library.scene(title, index)
    box = (0, HUD_H, w, h - HUD_H)
    if demo_library.ERA_STYLE[console][0] == "pixel":
        body = demo_library.render_pixel(shapes, palette(console), view(console, step, steps),
                                         box, PIXEL_CELL)
    else:
        body = demo_library.render_scene(console, shapes, palette(console),
                                         view(console, step, steps), box)
    return body + hud(console, step, w)


def ds_menu(top):
    """The DS lower screen at ``top``: a framed close-up and the menu."""
    w, h = NATIVE["NDS"]
    pal = palette("NDS")
    title = GAMEPLAY["NDS"]
    index = demo_library.TITLES["NDS"].index(title)
    shapes = demo_library.scene(title, index)
    close = demo_library.crop_view(shapes, 1.0)
    side = h - 72
    items = DS_MENU.get(demo_library.GENRE[title], DS_MENU_DEFAULT)
    menu_x = 20 + side + (w - 20 - side) // 2
    return (
        f'<rect x="0" y="{top}" width="{w}" height="{h}" fill="{pal["dark"]}"/>'
        f'<rect x="10" y="{top + 34}" width="{side + 4}" height="{side + 4}" fill="{pal["light"]}"/>'
        + demo_library.render_scene("NDS", shapes, pal, close, (12, top + 36, side, side))
        + "".join(
            demo_library.pixel_text([item], menu_x, top + 40 + n * 30, 2,
                                    pal["accent"] if n == 0 else pal["light"])
            for n, item in enumerate(items))
    )


def frame_svg(console, step=0, steps=1):
    """The whole frame for ``console`` as an SVG document."""
    if console not in GAMEPLAY:
        raise KeyError(f"no gameplay title for {console!r}")
    w, h = size(console)
    body = screen(console, step, steps)
    if console == "NDS":
        body += ds_menu(NATIVE["NDS"][1])
    return demo_library._svg(w, h, body)


def render(console, step=0, steps=1, scale=1):
    """The frame as PNG bytes, enlarged ``scale`` times with no smoothing."""
    png = demo_library.render_png(frame_svg(console, step, steps))
    if scale == 1:
        return png
    loader = GdkPixbuf.PixbufLoader.new_with_type("png")
    loader.write(png)
    loader.close()
    pixbuf = loader.get_pixbuf()
    big = pixbuf.scale_simple(pixbuf.get_width() * scale, pixbuf.get_height() * scale,
                              GdkPixbuf.InterpType.NEAREST)
    ok, data = big.save_to_bufferv("png", [], [])
    if not ok:  # pragma: no cover - GdkPixbuf raises instead of returning False
        raise GLib.Error("could not encode PNG")
    return bytes(data)


def write(out_dir, consoles=None, frames=1, scale=1):
    """Write the frames; returns the paths written."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for console in consoles or GAMEPLAY:
        stem = f"{console.lower()}-{demo_library.slug(GAMEPLAY[console])}"
        for step in range(frames):
            name = f"{stem}-{step:02d}.png" if frames > 1 else f"{stem}.png"
            path = out / name
            path.write_bytes(render(console, step, frames, scale))
            written.append(path)
    return written


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out_dir")
    parser.add_argument("--scale", type=int, default=1)
    parser.add_argument("--frames", type=int, default=1)
    parser.add_argument("--console", action="append", choices=sorted(GAMEPLAY))
    args = parser.parse_args(argv)
    if args.scale < 1 or args.frames < 1:
        parser.error("--scale and --frames must be at least 1")
    for path in write(args.out_dir, args.console, args.frames, args.scale):
        print(path)
    return 0


if __name__ == "__main__":  # pragma: no cover - the CLI is main()
    sys.exit(main())
