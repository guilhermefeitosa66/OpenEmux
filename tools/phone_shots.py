#!/usr/bin/env python3
"""Android in-game shots for the site: a bundled controller skin over a frame.

    .venv/bin/python tools/phone_shots.py SKINS_DIR FRAMES_DIR OUT_DIR
                                          [--shot CONSOLE:ORIENTATION ...]

The fictional games of the demo catalogue cannot run inside the Android app
(there is no ROM behind them), and real game content may not appear on the
site. So an in-game shot is drawn the way the app draws one: the gameplay
frame from ``tools/demo_gameplay.py``, scaled with nearest-neighbour sampling
into each screen rectangle of the app's own skin, with the skin art on top.

SKINS_DIR is the app's ``pkg/android/openemux/src/main/assets/skins/``: the
``<CONSOLE>.deltaskin`` / ``.manicskin`` archives are read as they are, no
unzipping. FRAMES_DIR holds ``demo_gameplay.py`` output (``<console>-<slug>.png``;
the DS frame is both screens stacked, top first). The layout is the skin's
``representations.iphone.edgeToEdge.<orientation>``, the one the app picks on a
phone.

Writes ``OUT_DIR/game-<console>-<orientation>.png`` at the skin art's size
(1080 px on the short side). Deterministic; the PNGs carry no metadata.
Needs Pillow (a development dependency, never shipped).
"""

import argparse
import io
import json
import re
import sys
import zipfile
from pathlib import Path

from PIL import Image

#: The site's set (issue 684): every console portrait, the wide skins landscape.
DEFAULT_SHOTS = [
    ("SFC", "portrait"), ("GBA", "portrait"), ("N64", "portrait"),
    ("MD", "portrait"), ("PS", "portrait"), ("NDS", "portrait"),
    ("GBA", "landscape"), ("NDS", "landscape"),
]

#: The file names the site uses, per console id.
SLUG = {"SFC": "snes", "GBA": "gba", "N64": "n64", "MD": "megadrive",
        "PS": "ps", "NDS": "nds", "FC": "nes", "GB": "gb"}


def open_skin(skins_dir, console):
    """The console's skin archive, as a ZipFile."""
    for ext in ("deltaskin", "manicskin"):
        path = Path(skins_dir) / f"{console}.{ext}"
        if path.is_file():
            return zipfile.ZipFile(path)
    raise SystemExit(f"no skin for {console} in {skins_dir}")


def frame_for(frames_dir, console):
    """The single still for a console (clip frames, ``-NN``, are skipped)."""
    matches = [m for m in sorted(Path(frames_dir).glob(f"{console.lower()}-*.png"))
               if not re.search(r"-\d\d$", m.stem)]
    if not matches:
        raise SystemExit(f"no frame for {console} in {frames_dir}")
    return Image.open(matches[0]).convert("RGB")


def _box(screen, sx, sy):
    f = screen["outputFrame"]
    return (round(f["x"] * sx), round(f["y"] * sy),
            round((f["x"] + f["width"]) * sx), round((f["y"] + f["height"]) * sy))


def compose(skin, frame, orientation):
    """The skin's art over ``frame``, as the app layers a game screen."""
    info = json.loads(skin.read("info.json"))
    rep = info["representations"]["iphone"]["edgeToEdge"][orientation]
    art = Image.open(io.BytesIO(skin.read(rep["assets"]["large"]))).convert("RGBA")
    sx = art.width / rep["mappingSize"]["width"]
    sy = art.height / rep["mappingSize"]["height"]
    screens = rep["screens"]
    # A two-screen skin (the DS) takes the stacked frame's halves in order.
    half = frame.height // 2
    parts = ([frame.crop((0, 0, frame.width, half)),
              frame.crop((0, half, frame.width, frame.height))]
             if len(screens) == 2 else [frame])
    game = Image.new("RGBA", art.size, (0, 0, 0, 255))
    for part, screen in zip(parts, screens):
        box = _box(screen, sx, sy)
        game.paste(part.resize((box[2] - box[0], box[3] - box[1]), Image.NEAREST), box[:2])
    if art.getextrema()[3][0] < 255:
        # The screen rectangle is a hole in the art: the art goes on top.
        return Image.alpha_composite(game, art).convert("RGB")
    # Opaque art: the game goes on top, inside the screen rectangles.
    out = art.convert("RGB")
    for screen in screens:
        box = _box(screen, sx, sy)
        out.paste(game.crop(box).convert("RGB"), box[:2])
    return out


def parse_shot(text):
    console, _, orientation = text.partition(":")
    if orientation not in ("portrait", "landscape"):
        raise argparse.ArgumentTypeError(f"expected CONSOLE:portrait|landscape, got {text!r}")
    return console.upper(), orientation


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("skins", type=Path)
    parser.add_argument("frames", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--shot", type=parse_shot, action="append",
                        help="CONSOLE:ORIENTATION, repeatable (default: the site's set)")
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    for console, orientation in args.shot or DEFAULT_SHOTS:
        with open_skin(args.skins, console) as skin:
            image = compose(skin, frame_for(args.frames, console), orientation)
        path = args.out / f"game-{SLUG.get(console, console.lower())}-{orientation}.png"
        image.save(path, optimize=True)
        print(path)


if __name__ == "__main__":
    sys.exit(main())
