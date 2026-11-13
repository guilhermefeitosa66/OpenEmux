#!/usr/bin/python3 -I
"""A synthetic library for the performance checks: zero-byte ROMs with PNG art.

    tools/perf/gen_library.py <roms_dir> <total_roms> [cover_fraction=0.8] [w=512] [h=720]

Every ROM is an empty file named like a No-Intro dump, spread over sixteen
consoles; a fraction of them get a box cover under ``<console>/covers/`` and
the same image as a cartridge label under ``<console>/labels/``, hard-linked
from a small pool of generated images, so the decode cost per file is real
and the generation takes seconds instead of minutes.

Run it inside the devbox so the library lands in the container's own home:

    ./devbox/devbox.sh exec env OPENEMUX_SRC=$PWD/src /usr/bin/python3 -I \\
        tools/perf/gen_library.py ~/games/big 3000 0.8

Deterministic (seeded), so two runs produce the same names.
"""

import os
import random
import sys
from pathlib import Path

sys.path.insert(0, os.environ.get("OPENEMUX_SRC", "src"))
import gi  # noqa: E402

gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf, GLib  # noqa: E402

from openemux.core.systems import SYSTEMS  # noqa: E402

CONSOLES = [
    "FC", "SFC", "MD", "GBA", "GB", "GBC", "PS", "N64",
    "SMS", "PCE", "NGP", "A2600", "ARCADE", "SATURN", "DC", "NDS",
]
FIRST = [
    "Super", "Mega", "Ultra", "Final", "Dragon", "Castle", "Star", "Shadow", "Metal",
    "Sonic", "Phantom", "Chrono", "Golden", "Street", "Ninja", "Battle", "Space",
    "Secret", "Legend", "Wonder", "Rocket", "Crystal", "Silent", "Dark", "Thunder",
    "Mystic", "Royal", "Pocket", "Turbo", "Alpha",
]
SECOND = [
    "Quest", "Fighter", "Kart", "World", "Saga", "Force", "Storm", "Knight", "Hunter",
    "Racer", "Legends", "Warriors", "Tactics", "Chronicles", "Adventure", "Odyssey",
    "Rush", "Blaster", "Strike", "Island", "Fantasy", "Trigger", "Soldier", "Puzzle",
    "Heroes", "Kingdom", "Zone", "Tales", "Arena", "Rangers",
]
SUFFIX = [
    "", " II", " III", " IV", " 64", " Deluxe", " Advance", " Turbo", " Returns",
    " Gaiden", " - The Lost Levels", " - Rise of the Robots", " Collection", " Special",
]
REGION = [
    "(USA)", "(Europe)", "(Japan)", "(World)", "(USA, Europe)", "(USA) (Rev 1)",
    "(Japan) (Rev A)",
]
POOL_SIZE = 48
SKIP_EXTENSIONS = (".bin", ".rom", ".zip", ".7z", ".cue", ".chd", ".iso")


def names_for(total, rng):
    names = set()
    while len(names) < total:
        names.add(
            f"{rng.choice(FIRST)} {rng.choice(SECOND)}{rng.choice(SUFFIX)} {rng.choice(REGION)}"
        )
    return sorted(names)


def base_image(path, width, height, rng):
    """A gradient with noise, so every file decodes like a real cover."""
    if path.exists():
        return path
    buf = bytearray(width * height * 3)
    r0, g0, b0 = rng.randrange(256), rng.randrange(256), rng.randrange(256)
    for y in range(height):
        row = y * width * 3
        for x in range(0, width, 4):
            i = row + x * 3
            v = rng.randrange(0, 64)
            buf[i] = (r0 + y // 3 + v) & 255
            buf[i + 1] = (g0 + x // 3 + v) & 255
            buf[i + 2] = (b0 + v) & 255
            buf[i + 3:i + 12] = buf[i:i + 3] * 3
    pixbuf = GdkPixbuf.Pixbuf.new_from_bytes(
        GLib.Bytes.new(bytes(buf)), GdkPixbuf.Colorspace.RGB, False, 8, width, height, width * 3
    )
    pixbuf.savev(str(path), "png", ["compression"], ["3"])
    return path


def main(argv):
    if len(argv) < 3:
        sys.exit(__doc__)
    roms_dir = Path(argv[1])
    total = int(argv[2])
    fraction = float(argv[3]) if len(argv) > 3 else 0.8
    width = int(argv[4]) if len(argv) > 4 else 512
    height = int(argv[5]) if len(argv) > 5 else 720
    rng = random.Random(42)
    by_id = {system["id"]: system for system in SYSTEMS}
    consoles = [console for console in CONSOLES if console in by_id]

    per_console = {console: [] for console in consoles}
    for index, name in enumerate(names_for(total, rng)):
        per_console[consoles[index % len(consoles)]].append(name)

    pool_dir = roms_dir / "_art_pool"
    pool_dir.mkdir(parents=True, exist_ok=True)
    pool = [base_image(pool_dir / f"base{k}.png", width, height, rng) for k in range(POOL_SIZE)]

    made = covers = 0
    for console, names in per_console.items():
        extensions = [e for e in by_id[console]["extensions"] if e not in SKIP_EXTENSIONS]
        extension = extensions[0] if extensions else by_id[console]["extensions"][0]
        folder = roms_dir / console
        folder.mkdir(parents=True, exist_ok=True)
        art_dirs = [folder / "covers", folder / "labels"]
        for art_dir in art_dirs:
            art_dir.mkdir(exist_ok=True)
        for name in names:
            (folder / f"{name}{extension}").touch()
            made += 1
            if rng.random() < fraction:
                source = rng.choice(pool)
                for art_dir in art_dirs:
                    target = art_dir / f"{name}.png"
                    if not target.exists():
                        os.link(source, target)
                covers += 1
    print(f"roms={made} with_art={covers} consoles={len(consoles)} dir={roms_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
