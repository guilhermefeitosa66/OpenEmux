#!/usr/bin/python3
"""Generate the fictional demo library every published screenshot is taken from.

The project's site, README, AppStream screenshots and welcome wizard used to be
captured from a real library, so they showed commercial box art and cartridge
labels. This builds a library whose artwork the project draws itself (issues
#513 and #523): zero-byte ROMs with No-Intro-shaped names, and for each one a
cover in ``<roms>/<CONSOLE>/covers/`` and a cartridge label in
``<roms>/<CONSOLE>/labels/`` -- the paths ``core/scraper.py`` already reads.

    demo_library.py <roms_dir>                     # ROMs, covers and labels
    demo_library.py <roms_dir> --configure         # ...and point the app at it
    demo_library.py <roms_dir> --wall docs/assets/carts   # site cartridge wall

``--wall`` composites the labels already in ``<roms_dir>`` and writes nothing
else: the labels are drawn in the devbox, where the captures are taken, and the
wall can then be encoded on a machine whose GdkPixbuf WebP saver honours
``quality`` -- the one the devbox's Ubuntu resolves first is lossless only,
which makes the 84 files four times their size.

The art follows the #513 spec: a flat GNOME-palette ground, one geometric
emblem, the title in bold sans, and an era word ("16-BIT") in the top band --
never a console or company name. The SVG is rendered through librsvg, the same
way ``tools/gen_cartridge_colors.py`` builds its frames.

Deterministic and offline: palettes and emblems are picked by position, never
by ``random``, and the PNGs are written with no metadata chunks, so a rerun in
the same environment is byte-identical. The text is drawn with whatever bold
sans fontconfig resolves, so another machine with other fonts draws other
bytes; captures are taken in the devbox for that reason.

Every title was checked against a web search on 2026-10-24 and no published
game matched it. A title added later gets the same check before it lands.

Tooling only: nothing under ``src/`` imports this and it is not packaged. Run
it with ``/usr/bin/python3`` in the devbox (the pyenv ``python3`` there has no
PyGObject).
"""

import argparse
import io
import re
import sys
from pathlib import Path
from xml.sax.saxutils import escape

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

import gi  # noqa: E402

gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gio, GLib, GdkPixbuf  # noqa: E402

from openemux.core.cartridge_render import CartridgeFrame, frame_asset_for, has_frame  # noqa: E402
from openemux.core.scraper import COVER_ART, LABEL_ART, get_art_path_candidates  # noqa: E402
from openemux.core.systems import get_supported_extensions  # noqa: E402

#: Titles per console, in the order the grid shows them (alphabetical): the
#: palette is assigned by position, and neighbours on screen must differ. The
#: counts fill the frames the published images show -- about thirty for the
#: two consoles the site's wall and carousel lead with, one for SMS to keep the
#: single-card case.
TITLES = {
    "FC": [
        "Barrel Bay", "Brick Bandit", "Cobble Climb", "Comet Courier",
        "Copper Rocket", "Gumdrop Gate", "Ladder Lagoon", "Moonbeam Mile",
        "Pepper Plateau", "Pinecone Panic", "Sprocket Sprint", "Tin Toad",
    ],
    "SFC": [
        "Biscuit Brigade", "Cinder Bay", "Clockwork Orchard", "Cobalt Caravan",
        "Copper Lighthouse", "Ferris Fortress", "Granite Garden", "Harbor Hopscotch",
        "Hazel Hollow", "Juniper Station", "Kettle Knights", "Lagoon Lullaby",
        "Lantern Keep", "Mango Monsoon", "Marble Meadow Rally", "Meadow Mechanic",
        "Orchard Siege", "Paprika Pass", "Pebble Patrol", "Puddle Pilots",
        "Rooftop Regatta", "Saffron Skyway", "Spindle Spire", "Sundial Saga",
        "Thimble Quest", "Tundra Tailors", "Turnip Tactics", "Velvet Glacier",
        "Walnut Wanderers", "Willow Circuit",
    ],
    "GB": [
        "Brick Orbit", "Button Burrow", "Dew Drop Drift", "Fern Fable",
        "Graphite Grove", "Lantern Lane", "Pebble Prince", "Pickle Pier",
        "Puddle Pocket", "Puzzle Pavilion", "Soap Bubble Bay", "Tiny Trellis",
    ],
    "GBC": [
        "Berry Bridge", "Cherry Cog", "Citrus Circus", "Coral Carnival",
        "Kiwi Keepers", "Lime Lighthouse", "Marigold Maze", "Mint Mansion",
        "Peach Pagoda", "Rainbow Ravine", "Sherbet Ships", "Toffee Tower",
    ],
    "GBA": [
        "Acorn Arcade", "Basalt Bells", "Brass Beetles", "Cactus Courier",
        "Chalk Comets", "Driftwood Diaries", "Fennel Fields", "Glass Canyon",
        "Gondola Gambit", "Hollow Harp", "Ivy Ironworks", "Kite Kingdom",
        "Lemon Lightning", "Lychee Lane", "Maple Mosaic", "Moss Knight",
        "Nimbus Noodles", "Pixel Pantry", "Plum Parade", "Pocket Planetarium",
        "Pumice Patrol", "Raincoat Rangers", "Ripple Runners", "Saltmarsh Sprint",
        "Sorrel Speedway", "Sparrow Signal", "Tangerine Tides", "Teacup Tempest",
        "Tinker Tram", "Velvet Vortex",
    ],
    "N64": [
        "Canyon Carousel", "Glacier Grand Prix", "Hover Hamlet", "Lunar Laundry",
        "Neon Harbor", "Orbit Orchard", "Polygon Prairie", "Prism Pagoda",
        "Skyline Sledders", "Thunder Teapot", "Velvet Voltage", "Zephyr Zoo",
    ],
    "NDS": [
        "Bento Blitz", "Doodle Dunes", "Folding Fable", "Glimmer Garage",
        "Hinge Harbor", "Lantern Lab", "Murmur Mesa", "Origami Outpost",
        "Pocket Parliament", "Sketch Sailors", "Stylus Sprouts", "Twin Tide Towers",
    ],
    "MD": [
        "Blast Bayou", "Chrome Canyon", "Granite Gale", "Harbor Havoc",
        "Iron Iguana", "Magma Mailman", "Nitro Nectar", "Rapid Reef",
        "Static Sunset", "Tidepool Racers", "Turbo Tortoise", "Voltage Valley",
    ],
    "SMS": ["Cinder Dash"],
    "PS": [
        "Ashen Archive", "Cobalt Requiem", "Distant Lighthouse", "Faint Transmission",
        "Glass Orchard", "Lantern District", "Midnight Ferry", "Northern Tram",
        "Paper Pinwheels", "Quiet Observatory", "Silver Cartographer", "Velvet Monolith",
    ],
}

#: The word in a cover's top band: an era, never a console or company name.
ERA = {
    "FC": "8-BIT", "SMS": "8-BIT",
    "SFC": "16-BIT", "MD": "16-BIT",
    "N64": "64-BIT",
    "GB": "HANDHELD", "GBC": "HANDHELD", "GBA": "HANDHELD", "NDS": "HANDHELD",
    "PS": "CD",
}

#: Favorited by ``--configure``, so the site's Favorites shot needs no hand
#: edits: (console, title).
FAVORITES = [
    ("FC", "Comet Courier"),
    ("SFC", "Lantern Keep"),
    ("SFC", "Saffron Skyway"),
    ("GBA", "Moss Knight"),
    ("GBA", "Teacup Tempest"),
    ("N64", "Neon Harbor"),
    ("MD", "Tidepool Racers"),
    ("PS", "Paper Pinwheels"),
]

#: The consoles on the site's cartridge wall, which ``site/page.html`` lists.
WALL = ["GBA", "SFC", "N64", "MD"]
WALL_WIDTH = 400
WALL_QUALITY = "80"

# (bg, band, fg, fg2, title), from the GNOME palette and its shades. Dark and
# light grounds alternate, so neighbouring titles differ in lightness and not
# only in hue.
PALETTE = [
    ("#1a5fb4", "#c01c28", "#f6d32d", "#f5c211", "#ffffff"),
    ("#f9f06b", "#3d3846", "#e66100", "#c64600", "#241f31"),
    ("#613583", "#813d9c", "#ffbe6f", "#f66151", "#ffffff"),
    ("#f6f5f4", "#241f31", "#e66100", "#ffa348", "#241f31"),
    ("#11585c", "#000000", "#57e389", "#26a269", "#ffffff"),
    ("#99c1f1", "#1a5fb4", "#1a5fb4", "#ffffff", "#241f31"),
    ("#a51d2d", "#000000", "#ffa348", "#f8e45c", "#ffffff"),
    ("#ffa348", "#63452c", "#f9f06b", "#c64600", "#241f31"),
    ("#241f31", "#e01b24", "#f66151", "#62a0ea", "#ffffff"),
    ("#dc8add", "#613583", "#613583", "#ffffff", "#241f31"),
    ("#1f5c3a", "#241f31", "#8ff0a4", "#57e389", "#ffffff"),
    ("#deddda", "#1a5fb4", "#2ec27e", "#1a5fb4", "#241f31"),
    ("#63452c", "#3d3846", "#f6d32d", "#cdab8f", "#ffffff"),
    ("#8ff0a4", "#26a269", "#26a269", "#1f5c3a", "#241f31"),
]

COVER_W, COVER_H = 512, 768
BAND_H = round(COVER_H * 0.14)
TITLE_SIZE = 46
LABEL_LONG_SIDE = 512
#: Average advance of a bold sans glyph, in ems: there is no text measuring in
#: an SVG string, so wrapping and sizing go by this.
GLYPH_EM = 0.6
FONT = 'font-family="sans-serif" font-weight="bold"'


def slug(title):
    """``"Comet Courier"`` -> ``"comet-courier"``, the cartridge wall's file key."""
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


def rom_filename(title, console):
    """A No-Intro-shaped name with the console's first extension."""
    return f"{title} (World){get_supported_extensions(console)[0]}"


def contrast_ratio(hex_a, hex_b):
    """WCAG 2 contrast ratio between two ``#rrggbb`` colours."""
    def luminance(hex_color):
        channels = [int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    high, low = sorted((luminance(hex_a), luminance(hex_b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def palette_for(console, index):
    """The colour tuple of a console's ``index``-th title.

    Each console starts somewhere else in the palette, so two consoles' shelves
    do not open on the same colour.
    """
    return PALETTE[(list(TITLES).index(console) * 3 + index) % len(PALETTE)]


def label_aspect(console):
    """width / height of the console's label window, from its frame SVG."""
    frame = CartridgeFrame(frame_asset_for(console))
    _x, _y, width, height = frame._label_bbox(frame.width, frame.height)
    return width / height


def wrap(title, max_chars):
    """At most two lines, split at the space that balances them best."""
    if len(title) <= max_chars or " " not in title:
        return [title]
    words = title.split(" ")
    splits = [(" ".join(words[:i]), " ".join(words[i:])) for i in range(1, len(words))]
    return list(min(splits, key=lambda pair: abs(len(pair[0]) - len(pair[1]))))


# Emblems: (cx, cy, size, fg, fg2) -> SVG fragment, size being the motif's width.

def _sun(cx, cy, s, fg, fg2):
    return (
        f'<circle cx="{cx}" cy="{cy}" r="{s * 0.5:.1f}" fill="none" stroke="{fg2}" '
        f'stroke-width="{s * 0.06:.1f}" stroke-dasharray="{s * 0.07:.1f} {s * 0.07:.1f}"/>'
        f'<circle cx="{cx}" cy="{cy}" r="{s * 0.33:.1f}" fill="{fg}"/>'
    )


def _peak(cx, cy, s, fg, fg2):
    h = s * 0.62
    base = cy + h / 2
    return (
        f'<polygon points="{cx - s * 0.5:.1f},{base:.1f} {cx - s * 0.08:.1f},{base - h:.1f} '
        f'{cx + s * 0.34:.1f},{base:.1f}" fill="{fg}"/>'
        f'<polygon points="{cx - s * 0.04:.1f},{base:.1f} {cx + s * 0.23:.1f},{base - h * 0.62:.1f} '
        f'{cx + s * 0.5:.1f},{base:.1f}" fill="{fg2}"/>'
    )


def _rings(cx, cy, s, fg, fg2):
    return (
        f'<circle cx="{cx}" cy="{cy}" r="{s * 0.46:.1f}" fill="none" stroke="{fg2}" stroke-width="{s * 0.08:.1f}"/>'
        f'<circle cx="{cx}" cy="{cy}" r="{s * 0.29:.1f}" fill="none" stroke="{fg}" stroke-width="{s * 0.08:.1f}"/>'
        f'<circle cx="{cx}" cy="{cy}" r="{s * 0.1:.1f}" fill="{fg}"/>'
    )


def _blocks(cx, cy, s, fg, fg2):
    b = s * 0.4
    return (
        f'<rect x="{cx - b / 2:.1f}" y="{cy - b:.1f}" width="{b:.1f}" height="{b:.1f}" fill="{fg}"/>'
        f'<rect x="{cx - b:.1f}" y="{cy:.1f}" width="{b:.1f}" height="{b:.1f}" fill="{fg2}"/>'
        f'<rect x="{cx:.1f}" y="{cy:.1f}" width="{b:.1f}" height="{b:.1f}" fill="{fg}"/>'
    )


EMBLEMS = [_sun, _peak, _rings, _blocks]


def _svg(width, height, body):
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">{body}</svg>'
    )


def _text_lines(lines, x, last_baseline, size, color, anchor="start"):
    step = round(size * 1.15)
    first = last_baseline - step * (len(lines) - 1)
    return "".join(
        f'<text x="{x}" y="{first + i * step}" {FONT} font-size="{size}" fill="{color}" '
        f'text-anchor="{anchor}">{escape(line)}</text>'
        for i, line in enumerate(lines)
    )


def cover_svg(console, index, title):
    """The 512x768 box cover of a console's ``index``-th title."""
    bg, band, fg, fg2, ink = palette_for(console, index)
    era_size = 26
    pad = 24
    lines = wrap(title, int((COVER_W - 2 * pad) / (TITLE_SIZE * GLYPH_EM)) - 4)
    baseline = COVER_H - 44
    title_top = baseline - round(TITLE_SIZE * 1.15) * (len(lines) - 1) - TITLE_SIZE
    emblem_cy = (BAND_H + title_top) // 2
    body = (
        f'<rect width="{COVER_W}" height="{COVER_H}" fill="{bg}"/>'
        f'<rect width="{COVER_W}" height="{BAND_H}" fill="{band}"/>'
        f'<text x="{pad}" y="{BAND_H // 2 + round(era_size * 0.36)}" {FONT} font-size="{era_size}" '
        f'letter-spacing="{era_size * 0.12:.1f}" fill="#ffffff">{ERA[console]}</text>'
        + EMBLEMS[index % len(EMBLEMS)](COVER_W // 2, emblem_cy, 280, fg, fg2)
        + _text_lines(lines, pad, baseline, TITLE_SIZE, ink)
    )
    return _svg(COVER_W, COVER_H, body)


def label_size(aspect):
    """Pixel size of a label: its long side is ``LABEL_LONG_SIDE``."""
    if aspect >= 1:
        return LABEL_LONG_SIDE, round(LABEL_LONG_SIDE / aspect)
    return round(LABEL_LONG_SIDE * aspect), LABEL_LONG_SIDE


def label_svg(console, index, title, aspect):
    """The cartridge label: same ground and title, the emblem reduced to a disc.

    A wide window puts the disc left of the title; a tall or square one (FC,
    N64, the handhelds) stacks the disc above it.
    """
    bg, _band, fg, _fg2, ink = palette_for(console, index)
    width, height = label_size(aspect)
    body = f'<rect width="{width}" height="{height}" fill="{bg}"/>'
    if aspect >= 1.3:
        # SMS's window is a thin strip: there the height is all there is.
        strip = aspect > 4
        radius = round(height * (0.3 if strip else 0.16))
        disc_x = round(width * 0.07) + radius
        text_x = disc_x + radius + round(width * 0.05)
        room = width - text_x - round(width * 0.04)
        size = min(round(height * (0.45 if strip else 0.2)), int(room / (len(title) * GLYPH_EM)))
        body += (
            f'<circle cx="{disc_x}" cy="{height // 2}" r="{radius}" fill="{fg}"/>'
            + _text_lines([title], text_x, height // 2 + round(size * 0.36), size, ink)
        )
    else:
        radius = round(width * 0.16)
        size = round(width * 0.13)
        lines = wrap(title, int(width * 0.86 / (size * GLYPH_EM)))
        block = 2 * radius + round(size * 0.9) + round(size * 1.15) * len(lines)
        top = (height - block) // 2
        baseline = top + 2 * radius + round(size * 0.9) + round(size * 1.15) * len(lines) - round(size * 0.25)
        body += (
            f'<circle cx="{width // 2}" cy="{top + radius}" r="{radius}" fill="{fg}"/>'
            + _text_lines(lines, width // 2, baseline, size, ink, anchor="middle")
        )
    return _svg(width, height, body)


def plan(roms_dir):
    """Everything to write: ``(path, kind, svg)``, ``svg`` empty for a ROM.

    Art paths come from the app's own resolver, so the files land exactly where
    the grid looks for them. Labels only for consoles that have a cartridge
    frame (PS has none).
    """
    roms_dir = Path(roms_dir)
    entries = []
    for console, titles in TITLES.items():
        aspect = label_aspect(console) if has_frame(console) else None
        for index, title in enumerate(titles):
            filename = rom_filename(title, console)
            stem = Path(filename).stem
            entries.append((roms_dir / console / filename, "rom", ""))
            cover = get_art_path_candidates(roms_dir, console, stem, COVER_ART)[0]
            entries.append((cover, COVER_ART, cover_svg(console, index, title)))
            if aspect is not None:
                label = get_art_path_candidates(roms_dir, console, stem, LABEL_ART)[0]
                entries.append((label, LABEL_ART, label_svg(console, index, title, aspect)))
    return entries


def render_png(svg):
    """SVG string -> PNG bytes, with no metadata chunks (byte-stable)."""
    stream = Gio.MemoryInputStream.new_from_bytes(GLib.Bytes.new(svg.encode("utf-8")))
    pixbuf = GdkPixbuf.Pixbuf.new_from_stream(stream, None)
    ok, data = pixbuf.save_to_bufferv("png", [], [])
    if not ok:  # pragma: no cover - GdkPixbuf raises instead of returning False
        raise RuntimeError("could not encode PNG")
    return bytes(data)


def write(roms_dir):
    """Write the library; returns how many files were written."""
    entries = plan(roms_dir)
    for path, kind, svg in entries:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"" if kind == "rom" else render_png(svg))
    return len(entries)


def configure(roms_dir, config=None):
    """Point the app at the library and mark ``FAVORITES``.

    Through ``ConfigManager`` and ``PlaylistManager``, never by editing their
    files, so this cannot drift from what the app reads. Rerunning it leaves a
    favorite a favorite (``toggle_favorite`` alone would flip it back).
    """
    from openemux.core.config import ConfigManager
    from openemux.core.playlist_manager import PlaylistManager

    config = config or ConfigManager()
    config.set_roms_path(roms_dir)
    playlists = PlaylistManager(config, None)
    config.get_playlists_dir().mkdir(parents=True, exist_ok=True)
    for console, title in FAVORITES:
        path = str(Path(roms_dir).expanduser() / console / rom_filename(title, console))
        if not playlists.is_favorite(path):
            playlists.toggle_favorite({"path": path})
    return config


def wall(roms_dir, out_dir):
    """The site's cartridge wall: each demo label on its console's frame.

    Reads the labels ``write()`` left in ``roms_dir``; it never draws them, so
    the wall shows exactly the labels the screenshots show.

    Rendered by the app's own compositor at ``WALL_WIDTH`` and saved as WebP,
    named ``<console>-<slug>.webp``. Returns ``{console: [slug, ...]}``, the
    ``games`` lists ``site/page.html`` needs.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    games = {}
    for console in WALL:
        frame = CartridgeFrame(frame_asset_for(console))
        games[console] = []
        for title in TITLES[console]:
            stem = Path(rom_filename(title, console)).stem
            label = get_art_path_candidates(roms_dir, console, stem, LABEL_ART)[0]
            png = io.BytesIO()
            frame.render(label, width=WALL_WIDTH).write_to_png(png)
            stream = Gio.MemoryInputStream.new_from_bytes(GLib.Bytes.new(png.getvalue()))
            pixbuf = GdkPixbuf.Pixbuf.new_from_stream(stream, None)
            name = f"{console.lower()}-{slug(title)}"
            pixbuf.savev(str(out_dir / f"{name}.webp"), "webp", ["quality"], [WALL_QUALITY])
            games[console].append(slug(title))
    return games


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("roms_dir", type=Path)
    parser.add_argument("--configure", action="store_true", help="point the app's config at the library")
    parser.add_argument(
        "--wall", type=Path, metavar="OUT_DIR",
        help="render the site's cartridge wall from the labels already in roms_dir, and nothing else",
    )
    args = parser.parse_args(argv)

    roms_dir = args.roms_dir.expanduser().resolve()
    if args.wall:
        for console, slugs in wall(roms_dir, args.wall).items():
            print(f"{console.lower()}: " + ", ".join(f'"{s}"' for s in slugs))
        return 0
    print(f"{write(roms_dir)} files written to {roms_dir}")
    if args.configure:
        config = configure(roms_dir)
        print(f"roms_path set in {config.config_file}")
    return 0


if __name__ == "__main__":  # pragma: no cover - the script entry; the tests call main()
    raise SystemExit(main())
