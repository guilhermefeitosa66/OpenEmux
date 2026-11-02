#!/usr/bin/env python3
"""Import the Android relief cartridge frames into the desktop frame SVGs.

The relief frames (real height, cast shadows, embossed lettering) are rendered
by the Android app's generator, `pkg/android/openemux/tools/render-cartridge-
frames.py` in openemux-android: one 800 px WebP per console and shell colour,
`cart_<console>[_<colour>].webp` in `src/main/res/drawable-nodpi`. That script
is their only source. This one puts each of those rasters, as is, into the
matching `<CONSOLE>[-<colour>].svg` here, so both apps show the same pixels.

Per SVG it swaps the embedded art for the WebP and, on a colour variant, drops
the "Colorize" filter `gen_cartridge_colors.py` added: the WebP is already
coloured, and coloured better than the filter can (the label window's shadow
and the metal contacts keep their own colour). Everything else, the
`label-clip` marker first, is left byte for byte as it was.

The SVG frame units are the Android `CartFrame` units, so the raster has to
have the frame's aspect; one that does not is refused.

    tools/import_cartridge_frames.py                     # every relief frame
    tools/import_cartridge_frames.py GB FC               # only these consoles
    tools/import_cartridge_frames.py --from DIR          # drawables elsewhere
"""

import argparse
import base64
import re
import struct
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ASSETS = REPO / "src" / "openemux" / "ui" / "assets" / "images" / "cartridges"
DEFAULT_SOURCE = (
    REPO.parent / "openemux-android" / "pkg" / "android" / "openemux"
    / "src" / "main" / "res" / "drawable-nodpi"
)

# Hand-drawn frames the Android generator does not redo; never touched here.
KEEP = {"SFC"}

# How far each side of the raster may be from the frame's shape, in raster
# pixels: the generator rounds the short side to a whole pixel.
ASPECT_TOLERANCE_PX = 1.0

WEBP_NAME_RE = re.compile(r"^cart_([a-z0-9]+?)(?:_([a-z]+))?\.webp$")
HREF_RE = re.compile(r'(xlink:href="data:image/)(?:png|webp)(;base64,)[^"]*(")', re.S)
FILTER_DEFS_RE = re.compile(
    r'<defs\s+id="defs1">\s*<filter\b[^>]*\bid="colorize-[a-z]+"[^>]*>.*?</filter>\s*</defs>', re.S
)
FILTER_STYLE_RE = re.compile(r'\s+style="filter:url\(#colorize-[a-z]+\)"')
VIEWBOX_RE = re.compile(r'viewBox="\s*[-\d.]+\s+[-\d.]+\s+([\d.]+)\s+([\d.]+)\s*"')


class FrameImportError(Exception):
    """A frame that cannot be imported; the message says which and why."""


def webp_size(data: bytes) -> tuple[int, int]:
    """Width and height of a WebP (lossy, lossless or extended), from its header."""
    if len(data) < 30 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        raise FrameImportError("not a WebP file")
    chunk = data[12:16]
    if chunk == b"VP8X":
        w = int.from_bytes(data[24:27], "little") + 1
        h = int.from_bytes(data[27:30], "little") + 1
        return w, h
    if chunk == b"VP8 ":
        w, h = struct.unpack("<HH", data[26:30])
        return w & 0x3FFF, h & 0x3FFF
    if chunk == b"VP8L":
        bits = int.from_bytes(data[21:25], "little")
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    raise FrameImportError(f"unknown WebP chunk {chunk!r}")


def svg_name(webp_name: str) -> str | None:
    """`cart_gb_red.webp` -> `GB-red.svg`; None for a name that is not a frame."""
    m = WEBP_NAME_RE.match(webp_name)
    if not m:
        return None
    console, color = m.group(1).upper(), m.group(2)
    return f"{console}-{color}.svg" if color else f"{console}.svg"


def console_of(svg_filename: str) -> str:
    """`GB-red.svg` -> `GB`."""
    return svg_filename.removesuffix(".svg").split("-")[0]


def import_frame(svg_text: str, webp: bytes, name: str) -> str:
    """The SVG with its art replaced by `webp` and any colorize filter removed."""
    vb = VIEWBOX_RE.search(svg_text)
    if not vb:
        raise FrameImportError(f"{name}: no viewBox")
    vw, vh = float(vb.group(1)), float(vb.group(2))
    w, h = webp_size(webp)
    # The generator sizes the long side and rounds the other: compare like that.
    k = max(w, h) / max(vw, vh)
    if abs(vw * k - w) > ASPECT_TOLERANCE_PX or abs(vh * k - h) > ASPECT_TOLERANCE_PX:
        raise FrameImportError(f"{name}: raster {w}x{h} does not have the frame's {vw:g}x{vh:g} shape")
    payload = base64.b64encode(webp).decode("ascii")
    text, n = HREF_RE.subn(lambda m: f"{m.group(1)}webp{m.group(2)}{payload}{m.group(3)}", svg_text)
    if n != 1:
        raise FrameImportError(f"{name}: expected one embedded image, found {n}")
    text = FILTER_DEFS_RE.sub('<defs\n     id="defs1" />', text, count=1)
    return FILTER_STYLE_RE.sub("", text, count=1)


def plan(source: Path, assets: Path, consoles=None):
    """(webp path, svg path) for every frame to import, sorted by SVG name."""
    pairs = []
    for webp in sorted(source.glob("cart_*.webp")):
        name = svg_name(webp.name)
        if name is None:
            continue
        console = console_of(name)
        if console in KEEP or (consoles and console not in consoles):
            continue
        target = assets / name
        if not target.is_file():
            raise FrameImportError(f"{webp.name}: no {name} to put it in")
        pairs.append((webp, target))
    return pairs


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("consoles", nargs="*", metavar="CONSOLE")
    ap.add_argument("--from", dest="source", type=Path, default=DEFAULT_SOURCE,
                    help="the Android drawable-nodpi directory (default: %(default)s)")
    ap.add_argument("--assets", type=Path, default=ASSETS, help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    consoles = {c.upper() for c in args.consoles}
    kept = consoles & KEEP
    if kept:
        ap.error(f"{' '.join(sorted(kept))}: hand-drawn frames, not imported")
    if not args.source.is_dir():
        print(f"import_cartridge_frames: no such directory: {args.source}", file=sys.stderr)
        return 1
    try:
        pairs = plan(args.source, args.assets, consoles)
        missing = consoles - {console_of(svg.name) for _w, svg in pairs}
        if missing:
            raise FrameImportError(f"no relief frame for {' '.join(sorted(missing))} in {args.source}")
        if not pairs:
            raise FrameImportError(f"no cart_*.webp in {args.source}")
        # A relief console's frame left out (a colour the generator does not
        # render) would keep the old flat art next to the new relief.
        imported = {svg.name for _w, svg in pairs}
        left = sorted(
            svg.name for svg in args.assets.glob("*.svg")
            if console_of(svg.name) not in KEEP
            and (not consoles or console_of(svg.name) in consoles)
            and svg.name not in imported
        )
        if left:
            raise FrameImportError(f"no WebP in {args.source} for {' '.join(left)}")
        updates = [(svg, import_frame(svg.read_text(), webp.read_bytes(), svg.name)) for webp, svg in pairs]
    except FrameImportError as exc:
        print(f"import_cartridge_frames: {exc}", file=sys.stderr)
        return 1
    for svg, text in updates:
        svg.write_text(text)
    print(f"{len(updates)} frames imported into {args.assets}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
