#!/usr/bin/env python3
"""Generate <CONSOLE>-<color>.svg copies of every cartridge frame.

Each copy is the original file plus:
  - a "Colorize" filter in <defs> (Inkscape's Filters > Color > Colorize chain:
    desaturate -> flat colour -> multiply -> clip back to the art's alpha),
    with one extra primitive: a linear luminance ramp between the desaturate
    and the flood.
  - style="filter:url(#colorize-<color>)" on the element labelled "frame"

The ramp exists because `multiply` can only darken: a black shell (MD, SMS)
multiplied by any colour stays black. It normalises each console's own plastic
to the same light-grey band first, measured from the embedded artwork, so the
same colour reads the same across every console -- the issue's "same plastic
under the same light".

The label-clip marker is never touched. Colours come from issue #79.
"""

import base64
import re
import sys
from pathlib import Path

import gi

gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gio, GLib, GdkPixbuf

ASSETS = (
    Path(__file__).resolve().parents[1]
    / "src" / "openemux" / "ui" / "assets" / "images" / "cartridges"
)

# id -> (display name, base hex) -- issue #79 palette, minus `default`
PALETTE = [
    ("black", "Onyx", "#26262A"),
    ("white", "Pearl", "#E8E4DA"),
    ("red", "Crimson", "#B23A34"),
    ("orange", "Amber", "#CC7A29"),
    ("yellow", "Sunflower", "#D9A81F"),
    ("green", "Emerald", "#3F8C5B"),
    ("teal", "Teal", "#2C8A8A"),
    ("blue", "Cobalt", "#3167B0"),
    ("purple", "Amethyst", "#7A4FA3"),
    ("pink", "Rose", "#BE5289"),
    ("gold", "Gold", "#C6A02E"),
    ("clear", "Clear", "#B9C0C7"),
]

BASE_FRAMES = ["FC", "SFC", "GBA", "GB", "GBC", "MD", "N64", "NDS", "SMS"]

# Where the normalised plastic should sit: mid-tone times the flood colour is
# what the shell reads as, so 0.85 lands just under the nominal base, and the
# 0.30 spread puts the shadows near the issue's "base darkened ~25%" shade.
TARGET_MID = 0.85
TARGET_SPREAD = 0.30
SLOPE_LIMITS = (0.80, 3.00)

DEFS_RE = re.compile(r'<defs\s+id="defs1"\s*/>')
IMAGE_OPEN_RE = re.compile(r"<image\b")


def _payload(text, name):
    m = re.search(r'xlink:href="data:image/png;base64,(.*?)"', text, re.S)
    if not m:
        raise SystemExit(f"{name}: no embedded png in the frame art")
    return base64.b64decode(re.sub(r"(&#10;|\s)", "", m.group(1)))


def _luminance_histogram(png_bytes):
    """256-bin luminance histogram over the opaque pixels of the art."""
    stream = Gio.MemoryInputStream.new_from_bytes(GLib.Bytes.new(png_bytes))
    pb = GdkPixbuf.Pixbuf.new_from_stream(stream, None)
    if not pb.get_has_alpha():
        pb = pb.add_alpha(False, 0, 0, 0)
    data = pb.get_pixels()
    stride, nch = pb.get_rowstride(), pb.get_n_channels()
    hist = [0] * 256
    for y in range(pb.get_height()):
        row = y * stride
        for x in range(pb.get_width()):
            i = row + x * nch
            if data[i + 3] < 200:  # the label window and the outside
                continue
            hist[(data[i] * 299 + data[i + 1] * 587 + data[i + 2] * 114) // 1000] += 1
    return hist


def _percentile(hist, q):
    total = sum(hist)
    if not total:
        return 0.0
    target, seen = total * q, 0
    for value, count in enumerate(hist):
        seen += count
        if seen >= target:
            return value / 255.0
    return 1.0


def measure_ramp(svg_text, name):
    """(slope, intercept) putting this console's plastic in the target band."""
    hist = _luminance_histogram(_payload(svg_text, name))
    p5, p50, p95 = (_percentile(hist, q) for q in (0.05, 0.5, 0.95))
    spread = max(p95 - p5, 1e-4)
    slope = min(max(TARGET_SPREAD / spread, SLOPE_LIMITS[0]), SLOPE_LIMITS[1])
    return slope, TARGET_MID - slope * p50


def filter_block(color_id, color_name, base_hex, ramp):
    slope, intercept = ramp
    func = (
        f'\n           type="linear"\n'
        f'           slope="{slope:.4f}"\n'
        f'           intercept="{intercept:.4f}"'
    )
    return (
        '<defs\n'
        '     id="defs1"><filter\n'
        f'       inkscape:label="Colorize {color_name}"\n'
        '       inkscape:menu="Color"\n'
        '       inkscape:menu-tooltip="Blend image or object with a flat colour"\n'
        '       style="color-interpolation-filters:sRGB"\n'
        f'       id="colorize-{color_id}"><feColorMatrix\n'
        '         type="saturate"\n'
        '         values="0"\n'
        '         result="desaturated"\n'
        '         id="feColorMatrix-colorize" /><feComponentTransfer\n'
        '         in="desaturated"\n'
        '         result="plastic"\n'
        '         id="feComponentTransfer-colorize"><feFuncR'
        f'{func} /><feFuncG'
        f'{func} /><feFuncB'
        f'{func} /></feComponentTransfer><feFlood\n'
        '         flood-opacity="1"\n'
        f'         flood-color="{base_hex}"\n'
        '         result="flood"\n'
        '         id="feFlood-colorize" /><feBlend\n'
        '         in="flood"\n'
        '         in2="plastic"\n'
        '         mode="multiply"\n'
        '         result="blend"\n'
        '         id="feBlend-colorize" /><feComposite\n'
        '         in="blend"\n'
        '         in2="desaturated"\n'
        '         operator="in"\n'
        '         result="composite1"\n'
        '         id="feComposite-colorize" /></filter></defs>'
    )


def make_variant(source_text, source_name, color_id, color_name, base_hex, ramp):
    text, n = DEFS_RE.subn(
        lambda _m: filter_block(color_id, color_name, base_hex, ramp), source_text, count=1
    )
    if n != 1:
        raise SystemExit(f'{source_name}: could not find <defs id="defs1" />')

    inject = f'\n       style="filter:url(#colorize-{color_id})"'
    if 'inkscape:label="frame"' not in text:  # GBC's art was never labelled
        inject += '\n       inkscape:label="frame"'
    text, n = IMAGE_OPEN_RE.subn(lambda m: m.group(0) + inject, text, count=1)
    if n != 1:
        raise SystemExit(f"{source_name}: could not find the <image> frame element")

    stem = Path(source_name).stem
    return text.replace(
        f'sodipodi:docname="{source_name}"',
        f'sodipodi:docname="{stem}-{color_id}.svg"',
    )


def main():
    only = sys.argv[1:] or BASE_FRAMES
    written = 0
    for console in only:
        source = ASSETS / f"{console}.svg"
        if not source.is_file():
            raise SystemExit(f"missing base frame: {source}")
        text = source.read_text()
        ramp = measure_ramp(text, source.name)
        print(f"{console:5} ramp: slope={ramp[0]:.3f} intercept={ramp[1]:+.3f}")
        for color_id, color_name, base_hex in PALETTE:
            (ASSETS / f"{console}-{color_id}.svg").write_text(
                make_variant(text, source.name, color_id, color_name, base_hex, ramp)
            )
            written += 1
    print(f"{written} files written to {ASSETS}")


if __name__ == "__main__":
    main()
