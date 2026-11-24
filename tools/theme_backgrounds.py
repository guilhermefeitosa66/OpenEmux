#!/usr/bin/env python3
"""The ready-made themes' background illustrations (issue 1012).

Every picture is drawn here, from shapes, for OpenEmux: no image from another
project, wallpaper site or desktop is used or traced. The script writes an SVG
(the source, kept beside the result) and renders it to the PNG the app paints:
``src/openemux/ui/assets/themes/<id>/library.svg`` and ``images/library.png``.
Licensed as the app (MIT).

The scenes are the Android app's (``openemux-android``,
``pkg/android/openemux/art/themes/``, drawn for a phone held upright), laid out
again for a desktop window, which is wide: the same motifs -- Pastel's clouds
and pastel waves, Dracula's moon, bats and pines, Kitty's cat by a ball of
yarn, Neon's striped sun and grid, Tokyo Night's skyline -- where a wide
window shows them.

    PYTHONPATH=src python3 tools/theme_backgrounds.py

Run it again after changing a drawing; the output is deterministic (seeded).
"""

import math
import random
import sys
from pathlib import Path

import gi

gi.require_version("Rsvg", "2.0")
import cairo
from gi.repository import Rsvg

WIDTH, HEIGHT = 1600, 1000
OUT = Path(__file__).resolve().parents[1] / "src" / "openemux" / "ui" / "assets" / "themes"


def svg(body, defs=""):
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" '
        f'viewBox="0 0 {WIDTH} {HEIGHT}">\n<defs>{defs}</defs>\n{body}\n</svg>\n'
    )


def gradient(name, stops, vertical=True):
    coords = 'x1="0" y1="0" x2="0" y2="1"' if vertical else 'x1="0" y1="0" x2="1" y2="0"'
    inner = "".join(f'<stop offset="{o}" stop-color="{c}"/>' for o, c in stops)
    return f'<linearGradient id="{name}" {coords}>{inner}</linearGradient>'


def stars(rng, count, color, top, bottom, size=(1, 3), opacity=(0.4, 1.0)):
    out = []
    for _ in range(count):
        x = rng.uniform(0, WIDTH)
        y = rng.uniform(top, bottom)
        r = rng.uniform(*size)
        o = rng.uniform(*opacity)
        out.append(f'<circle cx="{x:.0f}" cy="{y:.0f}" r="{r:.1f}" fill="{color}" opacity="{o:.2f}"/>')
    return "\n".join(out)


def pastel():
    rng = random.Random(1)
    defs = gradient("sky", [(0, "#FDE2F3"), (0.55, "#E7E3FF"), (1, "#DDF3FF")])
    clouds = []
    for cx, cy, s in ((260, 220, 1.0), (980, 150, 1.3), (1380, 300, 0.8), (620, 380, 0.7)):
        clouds.append(
            f'<g fill="#FFFFFF" opacity="0.85" transform="translate({cx} {cy}) scale({s})">'
            '<ellipse cx="0" cy="0" rx="110" ry="42"/><ellipse cx="-60" cy="-18" rx="60" ry="46"/>'
            '<ellipse cx="45" cy="-30" rx="70" ry="56"/></g>'
        )
    hills = (
        '<path d="M0 700 Q400 620 800 700 T1600 690 V1000 H0Z" fill="#DDD6FE"/>'
        '<path d="M0 770 Q420 690 820 770 T1600 760 V1000 H0Z" fill="#BFDBFE"/>'
        '<path d="M0 840 Q380 770 800 840 T1600 830 V1000 H0Z" fill="#BBF7D0"/>'
        '<path d="M0 910 Q420 850 900 910 T1600 900 V1000 H0Z" fill="#FED7AA"/>'
    )
    flowers = []
    for _ in range(26):
        x, y = rng.uniform(40, WIDTH - 40), rng.uniform(870, 980)
        color = rng.choice(["#FFFFFF", "#FEF08A", "#BFDBFE", "#DDD6FE"])
        flowers.append(f'<circle cx="{x:.0f}" cy="{y:.0f}" r="{rng.uniform(4, 8):.1f}" fill="{color}"/>')
    sun = '<circle cx="1320" cy="160" r="70" fill="#FEF08A" opacity="0.9"/>'
    return svg('<rect width="100%" height="100%" fill="url(#sky)"/>' + sun + "".join(clouds)
               + hills + "".join(flowers), defs)


def dracula():
    rng = random.Random(2)
    defs = gradient("night", [(0, "#1E1F29"), (0.6, "#282A36"), (1, "#3A2E4F")])
    moon = (
        '<circle cx="1260" cy="210" r="110" fill="#F8F8F2" opacity="0.92"/>'
        '<circle cx="1305" cy="180" r="100" fill="#282A36"/>'
    )
    hills = (
        '<path d="M0 820 Q260 700 520 790 T1040 760 T1600 780 V1000 H0Z" fill="#44475A"/>'
        '<path d="M0 900 Q400 820 820 890 T1600 870 V1000 H0Z" fill="#21222C"/>'
    )
    pines = []
    for i in range(22):
        x = 30 + i * 74 + rng.uniform(-14, 14)
        h = rng.uniform(70, 150)
        base_y = 820 + 30 * math.sin(i / 3.0)
        pines.append(f'<polygon points="{x - h / 5:.0f},{base_y:.0f} {x:.0f},{base_y - h:.0f} '
                     f'{x + h / 5:.0f},{base_y:.0f}" fill="#191A21"/>')
    castle = "".join(pines)
    bats = []
    for _ in range(7):
        x, y, s = rng.uniform(700, 1150), rng.uniform(220, 520), rng.uniform(0.6, 1.2)
        bats.append(
            f'<path transform="translate({x:.0f} {y:.0f}) scale({s:.2f})" fill="#BD93F9" opacity="0.7" '
            'd="M0 0 Q10 -14 22 -4 Q30 -16 36 -2 Q42 -16 50 -4 Q62 -14 72 0 Q54 -2 44 10 Q36 4 28 10 Q18 -2 0 0Z"/>'
        )
    return svg('<rect width="100%" height="100%" fill="url(#night)"/>'
               + stars(rng, 140, "#F8F8F2", 0, 600) + moon + "".join(bats) + hills + castle, defs)


def kitty():
    rng = random.Random(3)
    defs = gradient("dusk", [(0, "#2A2438"), (0.7, "#352B45"), (1, "#3E3050")])
    sparkles = []
    for _ in range(40):
        x, y = rng.uniform(0, WIDTH), rng.uniform(0, 700)
        color = rng.choice(["#F5C2E7", "#B4BEFE", "#F9E2AF", "#A6E3A1"])
        r = rng.uniform(2, 5)
        sparkles.append(f'<circle cx="{x:.0f}" cy="{y:.0f}" r="{r:.1f}" fill="{color}" opacity="0.7"/>')
    hearts = []
    for x, y, s in ((300, 260, 1.0), (760, 180, 0.7), (520, 520, 0.6)):
        hearts.append(
            f'<path transform="translate({x} {y}) scale({s})" fill="#F5C2E7" opacity="0.5" '
            'd="M0 12 C-20 -8 -40 12 0 44 C40 12 20 -8 0 12Z"/>'
        )
    # The cat, sitting beside a ball of yarn in the lower right: our shapes.
    cat = (
        '<ellipse cx="1210" cy="910" rx="300" ry="50" fill="#4A3B5C"/>'
        '<g transform="translate(1250 760)">'
        # tail
        '<path d="M110 120 Q200 110 190 30 Q182 -10 150 0" fill="none" stroke="#F2CDCD" '
        'stroke-width="30" stroke-linecap="round"/>'
        # body
        '<ellipse cx="20" cy="80" rx="120" ry="95" fill="#F2CDCD"/>'
        '<ellipse cx="20" cy="105" rx="70" ry="60" fill="#FFE4E1"/>'
        # head
        '<circle cx="20" cy="-40" r="85" fill="#F2CDCD"/>'
        '<polygon points="-50,-90 -60,-175 5,-118" fill="#F2CDCD"/>'
        '<polygon points="35,-118 100,-175 90,-90" fill="#F2CDCD"/>'
        '<polygon points="-42,-100 -48,-150 -10,-115" fill="#F5C2E7"/>'
        '<polygon points="50,-115 88,-150 82,-100" fill="#F5C2E7"/>'
        # eyes open, nose, mouth, blush, whiskers
        '<circle cx="-12" cy="-45" r="10" fill="#45475A"/><circle cx="52" cy="-45" r="10" fill="#45475A"/>'
        '<circle cx="-9" cy="-49" r="3" fill="#FFFFFF"/><circle cx="55" cy="-49" r="3" fill="#FFFFFF"/>'
        '<path d="M13 -22 L27 -22 L20 -13Z" fill="#E78284"/>'
        '<path d="M20 -13 Q13 -2 3 -6 M20 -13 Q27 -2 37 -6" stroke="#45475A" stroke-width="4" fill="none" stroke-linecap="round"/>'
        '<ellipse cx="-38" cy="-18" rx="15" ry="8" fill="#F5C2E7" opacity="0.8"/>'
        '<ellipse cx="78" cy="-18" rx="15" ry="8" fill="#F5C2E7" opacity="0.8"/>'
        '<path d="M-60 -25 L-110 -35 M-60 -15 L-110 -12 M100 -25 L150 -35 M100 -15 L150 -12" '
        'stroke="#C9B8D6" stroke-width="3" stroke-linecap="round"/>'
        # front paws
        '<ellipse cx="-20" cy="165" rx="30" ry="18" fill="#FFE4E1"/>'
        '<ellipse cx="55" cy="165" rx="30" ry="18" fill="#FFE4E1"/>'
        '</g>'
        # the ball of yarn and its loose thread
        '<circle cx="1030" cy="880" r="46" fill="#94E2D5"/>'
        '<path d="M995 860 Q1030 840 1065 870 M990 885 Q1030 865 1072 893 M1000 905 Q1030 890 1060 912" '
        'stroke="#6CBFB2" stroke-width="5" fill="none"/>'
        '<path d="M1074 890 Q1110 930 1150 905" stroke="#94E2D5" stroke-width="5" fill="none"/>'
    )
    paws = []
    for x, y, a in ((180, 900, -20), (330, 860, -10), (480, 905, -25)):
        paws.append(
            f'<g transform="translate({x} {y}) rotate({a})" fill="#F5C2E7" opacity="0.35">'
            '<ellipse cx="0" cy="0" rx="22" ry="18"/><circle cx="-20" cy="-24" r="8"/>'
            '<circle cx="-6" cy="-32" r="8"/><circle cx="10" cy="-32" r="8"/><circle cx="23" cy="-23" r="8"/></g>'
        )
    return svg('<rect width="100%" height="100%" fill="url(#dusk)"/>' + "".join(sparkles)
               + "".join(hearts) + "".join(paws) + cat, defs)


def neon():
    defs = (
        gradient("sky", [(0, "#0D0221"), (0.6, "#1B0838"), (1, "#2A0B4A")])
        + gradient("sun", [(0, "#F9C80E"), (0.5, "#FF2A6D"), (1, "#7B2FF7")])
    )
    sun = ['<circle cx="800" cy="520" r="230" fill="url(#sun)"/>']
    for i, y in enumerate(range(560, 760, 26)):
        sun.append(f'<rect x="560" y="{y}" width="480" height="{6 + i * 2}" fill="#1B0838"/>')
    horizon = 640
    grid = ['<rect x="0" y="640" width="1600" height="360" fill="#0D0221"/>']
    for i in range(-14, 15):
        x = 800 + i * 120
        grid.append(f'<line x1="800" y1="{horizon}" x2="{x * 3 - 1600}" y2="1000" stroke="#FF2A6D" '
                    'stroke-width="2" opacity="0.7"/>')
    y, step = horizon + 6, 6
    while y < HEIGHT:
        grid.append(f'<line x1="0" y1="{y:.0f}" x2="1600" y2="{y:.0f}" stroke="#05D9E8" stroke-width="2" opacity="0.6"/>')
        step *= 1.35
        y += step
    mountains = (
        '<path d="M0 640 L180 520 L320 600 L470 480 L620 640Z" fill="#2A0B4A" stroke="#05D9E8" stroke-width="2" opacity="0.9"/>'
        '<path d="M980 640 L1130 470 L1280 590 L1420 500 L1600 640Z" fill="#2A0B4A" stroke="#05D9E8" stroke-width="2" opacity="0.9"/>'
    )
    rng = random.Random(4)
    return svg('<rect width="100%" height="100%" fill="url(#sky)"/>'
               + stars(rng, 90, "#D1F7FF", 0, 420) + "".join(sun) + mountains + "".join(grid), defs)


def tokyo_night():
    rng = random.Random(5)
    defs = gradient("night", [(0, "#16161E"), (0.55, "#1A1B26"), (1, "#24283B")])
    moon = '<circle cx="250" cy="180" r="60" fill="#C0CAF5" opacity="0.85"/>'
    city = []
    for layer, (color, base, low, high, wmin, wmax) in enumerate((
        ("#1F2335", 760, 180, 420, 60, 140),
        ("#16161E", 860, 120, 360, 50, 120),
    )):
        x = -20
        while x < WIDTH:
            w = rng.randint(wmin, wmax)
            h = rng.randint(low, high)
            top = base - h
            city.append(f'<rect x="{x}" y="{top}" width="{w}" height="{HEIGHT - top}" fill="{color}"/>')
            for wy in range(top + 18, base - 10, 26):
                for wx in range(x + 10, x + w - 14, 20):
                    if rng.random() < 0.28:
                        lit = rng.choice(["#7AA2F7", "#BB9AF7", "#FF9E64", "#E0AF68", "#7DCFFF"])
                        city.append(f'<rect x="{wx}" y="{wy}" width="8" height="12" fill="{lit}" '
                                    f'opacity="{0.5 + 0.4 * layer:.2f}"/>')
            x += w + rng.randint(4, 18)
    water = ('<rect x="0" y="860" width="1600" height="140" fill="#1A1B26"/>'
             '<rect x="0" y="860" width="1600" height="3" fill="#7AA2F7" opacity="0.4"/>')
    return svg('<rect width="100%" height="100%" fill="url(#night)"/>'
               + stars(rng, 110, "#C0CAF5", 0, 520) + moon + "".join(city) + water, defs)


DRAWINGS = {
    "pastel": pastel,
    "dracula": dracula,
    "kitty": kitty,
    "neon": neon,
    "tokyo-night": tokyo_night,
}


def render(svg_path, png_path):
    handle = Rsvg.Handle.new_from_file(str(svg_path))
    surface = cairo.ImageSurface(cairo.FORMAT_RGB24, WIDTH, HEIGHT)
    context = cairo.Context(surface)
    viewport = Rsvg.Rectangle()
    viewport.x, viewport.y, viewport.width, viewport.height = 0, 0, WIDTH, HEIGHT
    handle.render_document(context, viewport)
    surface.write_to_png(str(png_path))


def main():
    for theme_id, draw in DRAWINGS.items():
        folder = OUT / theme_id
        (folder / "images").mkdir(parents=True, exist_ok=True)
        source = folder / "library.svg"
        source.write_text(draw(), encoding="utf-8")
        png = folder / "images" / "library.png"
        render(source, png)
        print(png, png.stat().st_size)
    return 0


if __name__ == "__main__":
    sys.exit(main())
