#!/usr/bin/python3
"""Generate the fictional demo library every published screenshot is taken from.

The project's site, README, AppStream screenshots and welcome wizard used to be
captured from a real library, so they showed commercial box art and cartridge
labels. This builds a library whose artwork the project draws itself (issues
#513, #523 and #551): zero-byte ROMs with No-Intro-shaped names, and for each
one a cover in ``<roms>/<CONSOLE>/covers/`` and a cartridge label in
``<roms>/<CONSOLE>/labels/`` -- the paths ``core/scraper.py`` already reads.

    demo_library.py <roms_dir>                     # ROMs, covers and labels
    demo_library.py <roms_dir> --configure         # ...and point the app at it
    demo_library.py <roms_dir> --wall docs/assets/carts   # site cartridge wall

``--wall`` composites the labels already in ``<roms_dir>`` and writes nothing
else: the labels are drawn in the devbox, where the captures are taken, and the
wall can then be encoded on a machine whose GdkPixbuf WebP saver honours
``quality`` -- the one the devbox's Ubuntu resolves first is lossless only,
which makes the 84 files four times their size.

The catalogue is a parody one (#551): every title winks at a genre or a premise
("Super Plumber Man" is a platformer about a plumber) and names no real game.
Each title has a genre, and each genre a scene -- hero, setting, props -- built
once from plain shapes whose colours are *roles* (sky, ground, hero...). An era
renderer then draws that scene the way the console's own boxes looked:

* ``pixel`` (FC, SMS, GB, GBC): the scene sampled on a coarse grid of square
  cells, a small fixed palette (four greens on the GB), a blocky bitmap title;
* ``painted`` (SFC, MD): gradient skies and ground, a rim light on the hero;
* ``cartoon`` (GBA, NDS): flat saturated fills, every shape outlined;
* ``lowpoly`` (N64, PS): round shapes cut into polygons, every facet flat-shaded
  from one light, a CG sky -- dusk and fog on the PS.

The cover shows the whole scene; the label crops it around its hero. No real
character, logo or box design is drawn: the heroes are generic figures. The art
is authored as SVG by the project's AI tooling and rendered through librsvg,
the same way ``tools/gen_cartridge_colors.py`` builds its frames -- no image
model, no network, no new dependency.

Deterministic and offline: palettes and scene variations are picked by
position, never by ``random``, and the PNGs are written with no metadata
chunks, so a rerun in the same environment is byte-identical. The sans titles
are drawn with whatever bold sans fontconfig resolves, so another machine with
other fonts draws other bytes; captures are taken in the devbox for that reason.

Every title was checked against a web search on 2026-10-25 and no published
game matched it. A title added later gets the same check before it lands.

Tooling only: nothing under ``src/`` imports this and it is not packaged. Run
it with ``/usr/bin/python3`` in the devbox (the pyenv ``python3`` there has no
PyGObject).
"""

import argparse
import io
import math
import re
import sys
from collections import namedtuple
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
        "Castle Bat Hunter", "Galaxy Bug Blaster", "Ice Rink Rumble", "Jungle Commando Run",
        "Kung Fu Alley", "Ninja Rooftop Dash", "Rally Road Rush", "Super Plumber Man",
        "Sword Hero Saga", "Tiny Biplane Ace", "Tower Of Gems", "Treasure Map Kid",
    ],
    "SFC": [
        "Alien Planet Quest", "Ancient Sword Legend", "Beach Volley Stars", "Blade Of The Crystal",
        "Boxing Ring Champ", "Brawl City Streets", "Bubble Pop Parade", "Desert Tank Strike",
        "Dragon Sky Rider", "Dungeon Party Quest", "Forest Spirit Path", "Galaxy Star Patrol",
        "Gem Drop Frenzy", "Golf Course Pro", "Haunted Manor Night", "Jungle Vine Swing",
        "Kart Cup Grand Prix", "Magic Boot Hopper", "Mecha Pilot Zero", "Ninja Twin Strike",
        "Rhythm Drum Party", "Robot Man X", "Sky Fortress Siege", "Super Kart Buddies",
        "The Car Racing Game", "The Fighter Game", "Time Knight Saga", "Turbo Highway Run",
        "Wizard Tower Tales", "Zero Grav Speedster",
    ],
    "GB": [
        "Block Drop Zone", "Critter Catch Club", "Island Hero Quest", "Mole Mine Digger",
        "Pocket Kart Dash", "Pocket Putt Champ", "Puzzle Tile Tower", "Robo Duel Arena",
        "Space Pod Blaster", "Spooky Crypt Walk", "Tiny Racer Cup", "Wild Cave Explorer",
    ],
    "GBC": [
        "Bug Catcher Trek", "Color Gem Match", "Dance Pocket Party", "Dino Egg Dash",
        "Frog Hop Valley", "Ghost Mansion Kid", "Heli Rescue Team", "Monster Ranch Pals",
        "Pirate Cove Treasure", "Skate Park Stunt", "Star Shooter Pocket", "Street Dash Racer",
    ],
    "GBA": [
        "Alien Ninja Squad", "Anime Card Duel", "Baseball Bash Kids", "Bounce Ball Hero",
        "Bubble Town Pop", "Castle Siege Tactics", "Cosmic Fox Pilot", "Crystal Sword Saga",
        "Desert Raider Kid", "Disco Robot Dance", "Dragon Egg Ranger", "Fire Fist Fury",
        "Gem Mine Mania", "Go Kart Galaxy", "Hamster Ball Run", "Hip Hop Step",
        "Jet Ski Splash", "Knight Of Hearts", "Laser Ship Omega", "Mud Truck Mayhem",
        "Ninja Shadow Path", "Pocket Karate Champ", "Robot Arena Clash", "Ski Slope Slalom",
        "Space Cadet Zero", "Street Kick Brawl", "Super Kart Turbo", "Swamp Witch House",
        "Tiny Wizard Trail", "Zombie Night Out",
    ],
    "N64": [
        "Bear Bird Buddies", "Cloud Glider Pilot", "Comet Squadron Zero", "Gold Agent Mission",
        "Jungle Island Rescue", "Kart Kingdom Cup", "Mountain Snow Board", "Ocean Wave Racer",
        "Party Board Bash", "Super Plumber Man 3D", "The Wrestling Match", "Turbo Pod Racer",
    ],
    "NDS": [
        "Brain Math Trainer", "Court Case Lawyer", "Dual Screen Dragon", "Fairy Garden Story",
        "Kitchen Chef Rush", "Puzzle Detective Kid", "Sky Pirate Flight", "Space Bounty Hunter",
        "Stylus Racer Tour", "Super Plumber Pocket", "Tap Beat Heroes", "Zombie School Night",
    ],
    "MD": [
        "Barbarian Axe Quest", "Coast Road Cruiser", "Cyber Ninja Revenge", "Funky Alien Groove",
        "Gridiron Smash", "Hyper Space Fighter", "Jungle Heli Strike", "Mutant Tomato Panic",
        "Rage City Brawl", "Sword Force Tactics", "The Fighter Game II", "Turbo Cheetah Dash",
    ],
    "SMS": ["Island Kid Hop"],
    "PS": [
        "Bandit Fox Jungle", "Blood Mansion Terror", "Cyber Fist Arena", "Dance Floor Fever",
        "Eternal Crystal Saga", "Ghost Fog Hill", "Hover Speed League", "Little Dragon Glide",
        "Metal Sneak Agent", "Pro Skate Legend", "Pro Street Racing", "Rhythm Rapper Dog",
    ],
}

#: The scene each title's art shows; every key of ``SCENES`` is used.
GENRE = {
    # FC
    "Castle Bat Hunter": "horror", "Galaxy Bug Blaster": "shmup", "Ice Rink Rumble": "sports",
    "Jungle Commando Run": "action", "Kung Fu Alley": "brawler", "Ninja Rooftop Dash": "platformer",
    "Rally Road Rush": "racer", "Super Plumber Man": "platformer", "Sword Hero Saga": "rpg",
    "Tiny Biplane Ace": "flight", "Tower Of Gems": "puzzle", "Treasure Map Kid": "adventure",
    # SFC
    "Alien Planet Quest": "adventure", "Ancient Sword Legend": "rpg", "Beach Volley Stars": "sports",
    "Blade Of The Crystal": "adventure", "Boxing Ring Champ": "fighter", "Brawl City Streets": "brawler",
    "Bubble Pop Parade": "puzzle", "Desert Tank Strike": "action", "Dragon Sky Rider": "flight",
    "Dungeon Party Quest": "rpg", "Forest Spirit Path": "adventure", "Galaxy Star Patrol": "shmup",
    "Gem Drop Frenzy": "puzzle", "Golf Course Pro": "sports", "Haunted Manor Night": "horror",
    "Jungle Vine Swing": "platformer", "Kart Cup Grand Prix": "kart", "Magic Boot Hopper": "platformer",
    "Mecha Pilot Zero": "action", "Ninja Twin Strike": "brawler", "Rhythm Drum Party": "rhythm",
    "Robot Man X": "action", "Sky Fortress Siege": "shmup", "Super Kart Buddies": "kart",
    "The Car Racing Game": "racer", "The Fighter Game": "fighter", "Time Knight Saga": "rpg",
    "Turbo Highway Run": "racer", "Wizard Tower Tales": "puzzle", "Zero Grav Speedster": "racer",
    # GB
    "Block Drop Zone": "puzzle", "Critter Catch Club": "rpg", "Island Hero Quest": "adventure",
    "Pocket Putt Champ": "sports", "Mole Mine Digger": "platformer", "Pocket Kart Dash": "kart",
    "Puzzle Tile Tower": "puzzle", "Robo Duel Arena": "fighter", "Space Pod Blaster": "shmup",
    "Spooky Crypt Walk": "horror", "Tiny Racer Cup": "racer", "Wild Cave Explorer": "adventure",
    # GBC
    "Bug Catcher Trek": "rpg", "Color Gem Match": "puzzle", "Dance Pocket Party": "rhythm",
    "Dino Egg Dash": "adventure", "Frog Hop Valley": "platformer", "Ghost Mansion Kid": "horror",
    "Heli Rescue Team": "flight", "Monster Ranch Pals": "rpg", "Pirate Cove Treasure": "adventure",
    "Skate Park Stunt": "sports", "Star Shooter Pocket": "shmup", "Street Dash Racer": "racer",
    # GBA
    "Alien Ninja Squad": "brawler", "Anime Card Duel": "rpg", "Baseball Bash Kids": "sports",
    "Bounce Ball Hero": "platformer", "Bubble Town Pop": "puzzle", "Castle Siege Tactics": "rpg",
    "Cosmic Fox Pilot": "flight", "Crystal Sword Saga": "rpg", "Desert Raider Kid": "adventure",
    "Disco Robot Dance": "rhythm", "Dragon Egg Ranger": "adventure", "Fire Fist Fury": "fighter",
    "Gem Mine Mania": "puzzle", "Go Kart Galaxy": "kart", "Hamster Ball Run": "platformer",
    "Hip Hop Step": "rhythm", "Jet Ski Splash": "racer", "Knight Of Hearts": "rpg",
    "Laser Ship Omega": "shmup", "Mud Truck Mayhem": "racer", "Ninja Shadow Path": "action",
    "Pocket Karate Champ": "fighter", "Robot Arena Clash": "action", "Ski Slope Slalom": "sports",
    "Space Cadet Zero": "shmup", "Street Kick Brawl": "brawler", "Super Kart Turbo": "kart",
    "Swamp Witch House": "horror", "Tiny Wizard Trail": "adventure", "Zombie Night Out": "horror",
    # N64
    "Bear Bird Buddies": "platformer", "Cloud Glider Pilot": "flight", "Comet Squadron Zero": "shmup",
    "Gold Agent Mission": "action", "Jungle Island Rescue": "adventure", "Kart Kingdom Cup": "kart",
    "Mountain Snow Board": "sports", "Ocean Wave Racer": "racer", "Party Board Bash": "puzzle",
    "Super Plumber Man 3D": "platformer", "The Wrestling Match": "fighter", "Turbo Pod Racer": "racer",
    # NDS
    "Brain Math Trainer": "puzzle", "Court Case Lawyer": "adventure", "Dual Screen Dragon": "rpg",
    "Fairy Garden Story": "rpg", "Kitchen Chef Rush": "rhythm", "Puzzle Detective Kid": "puzzle",
    "Sky Pirate Flight": "flight", "Space Bounty Hunter": "action", "Stylus Racer Tour": "kart",
    "Super Plumber Pocket": "platformer", "Tap Beat Heroes": "rhythm", "Zombie School Night": "horror",
    # MD
    "Barbarian Axe Quest": "brawler", "Coast Road Cruiser": "racer", "Cyber Ninja Revenge": "action",
    "Funky Alien Groove": "rhythm", "Gridiron Smash": "sports", "Hyper Space Fighter": "shmup",
    "Jungle Heli Strike": "flight", "Mutant Tomato Panic": "horror", "Rage City Brawl": "brawler",
    "Sword Force Tactics": "rpg", "The Fighter Game II": "fighter", "Turbo Cheetah Dash": "platformer",
    # SMS
    "Island Kid Hop": "platformer",
    # PS
    "Bandit Fox Jungle": "platformer", "Blood Mansion Terror": "horror", "Cyber Fist Arena": "fighter",
    "Dance Floor Fever": "rhythm", "Eternal Crystal Saga": "rpg", "Ghost Fog Hill": "horror",
    "Hover Speed League": "racer", "Little Dragon Glide": "flight", "Metal Sneak Agent": "action",
    "Pro Skate Legend": "sports", "Pro Street Racing": "racer", "Rhythm Rapper Dog": "rhythm",
}

#: The word in a cover's top band: an era, never a console or company name.
ERA = {
    "FC": "8-BIT", "SMS": "8-BIT",
    "SFC": "16-BIT", "MD": "16-BIT",
    "N64": "64-BIT",
    "GB": "HANDHELD", "GBC": "HANDHELD", "GBA": "HANDHELD", "NDS": "HANDHELD",
    "PS": "CD",
}

#: How a console's art is drawn: (renderer, palette set).
ERA_STYLE = {
    "FC": ("pixel", "nes"), "SMS": ("pixel", "nes"),
    "GB": ("pixel", "dmg"), "GBC": ("pixel", "gbc"),
    "SFC": ("painted", "sfc"), "MD": ("painted", "md"),
    "GBA": ("cartoon", "gba"), "NDS": ("cartoon", "nds"),
    "N64": ("lowpoly", "n64"), "PS": ("lowpoly", "ps"),
}

#: Favorited by ``--configure``, so the site's Favorites shot needs no hand
#: edits: (console, title).
FAVORITES = [
    ("FC", "Super Plumber Man"),
    ("SFC", "Robot Man X"),
    ("SFC", "The Fighter Game"),
    ("GBA", "Cosmic Fox Pilot"),
    ("GBA", "Knight Of Hearts"),
    ("N64", "Super Plumber Man 3D"),
    ("MD", "The Fighter Game II"),
    ("PS", "Eternal Crystal Saga"),
]

#: The consoles on the site's cartridge wall, which ``site/page.html`` lists.
WALL = ["GBA", "SFC", "N64", "MD"]
WALL_WIDTH = 400
WALL_QUALITY = "80"

#: What each colour of a palette variant paints. ``band`` and ``era`` are the
#: cover's top band and its word; ``plate`` and ``ink`` the title and its plate.
ROLES = ("sky", "sky2", "far", "ground", "ground2", "hero", "hero2", "prop", "prop2",
         "accent", "dark", "light", "band", "era", "plate", "ink")

# Four variants per set, light and dark grounds alternating, so neighbouring
# covers differ in lightness and not only in hue. One string per variant, the
# colours in ``ROLES`` order.
_NES = ["#fcfcfc", "#000000", "#f8b800", "#e45c10", "#a81000", "#0058f8", "#3cbcfc", "#00a800",
        "#b8f818", "#6844fc", "#7c7c7c", "#bcbcbc", "#503000", "#fca044", "#0000bc", "#940084",
        "#d800cc", "#004058", "#008888", "#a4e4fc", "#fce0a8"]
_GBC = ["#f8f8f8", "#181830", "#f83838", "#f8e030", "#f8a830", "#3868f8", "#78c8f8", "#48a048",
        "#283880", "#a838a8", "#78f8f8", "#f8b8d8", "#186048", "#784020", "#c86020", "#f8d8b0"]
_DMG = ["#0f380f", "#306230", "#8bac0f", "#9bbc0f"]
_VARIANTS = {
    "nes": [
        "#3cbcfc #a4e4fc #00a800 #503000 #e45c10 #a81000 #fca044 #e45c10 #f8b800 #f8b800 #000000 #fcfcfc #a81000 #fcfcfc #000000 #fcfcfc",
        "#0000bc #6844fc #004058 #7c7c7c #bcbcbc #fca044 #a81000 #00a800 #b8f818 #f8b800 #000000 #fcfcfc #000000 #fcfcfc #fcfcfc #0000bc",
        "#fca044 #fce0a8 #e45c10 #00a800 #b8f818 #0058f8 #fcfcfc #a81000 #f8b800 #fcfcfc #000000 #fcfcfc #0058f8 #fcfcfc #000000 #f8b800",
        "#6844fc #d800cc #940084 #004058 #008888 #f8b800 #fcfcfc #e45c10 #fca044 #b8f818 #000000 #fcfcfc #940084 #fcfcfc #fcfcfc #000000",
    ],
    "dmg": [
        "#9bbc0f #8bac0f #8bac0f #306230 #0f380f #0f380f #306230 #306230 #0f380f #0f380f #0f380f #9bbc0f #0f380f #9bbc0f #0f380f #9bbc0f",
        "#306230 #0f380f #0f380f #0f380f #8bac0f #9bbc0f #8bac0f #8bac0f #9bbc0f #9bbc0f #0f380f #9bbc0f #0f380f #9bbc0f #9bbc0f #0f380f",
        "#8bac0f #9bbc0f #306230 #0f380f #306230 #0f380f #9bbc0f #306230 #0f380f #9bbc0f #0f380f #9bbc0f #0f380f #8bac0f #0f380f #8bac0f",
        "#0f380f #306230 #306230 #306230 #0f380f #8bac0f #9bbc0f #9bbc0f #8bac0f #8bac0f #0f380f #9bbc0f #306230 #9bbc0f #8bac0f #0f380f",
    ],
    "gbc": [
        "#78c8f8 #f8d8b0 #48a048 #f8a830 #c86020 #f83838 #f8d8b0 #3868f8 #f8f8f8 #f8e030 #181830 #f8f8f8 #283880 #f8f8f8 #181830 #f8f8f8",
        "#283880 #a838a8 #181830 #48a048 #186048 #f8e030 #f8a830 #f83838 #f8f8f8 #78f8f8 #181830 #f8f8f8 #784020 #f8f8f8 #f8f8f8 #283880",
        "#f8b8d8 #f8d8b0 #a838a8 #48a048 #186048 #3868f8 #f8f8f8 #f8a830 #f8e030 #f83838 #181830 #f8f8f8 #a838a8 #f8f8f8 #181830 #f8e030",
        "#186048 #48a048 #181830 #784020 #c86020 #f8f8f8 #f83838 #f8e030 #f8a830 #78f8f8 #181830 #f8f8f8 #181830 #f8f8f8 #f8e030 #181830",
    ],
    "sfc": [
        "#8ec5f0 #fde8c8 #8aa8d0 #6aa860 #3f7a48 #d24a4a #f4d0a8 #c08850 #f2c84b #ffe066 #2a2440 #fff6d8 #5a4a9a #ffffff #2a2440 #ffffff",
        "#2c2f6b #b4669a #4a3f7a #3a4f6a #22344a #f0b84a #ffe6b0 #8a5ab0 #e080c0 #ffd86a #141428 #ffe6b0 #7a3a6a #ffffff #fff6d8 #2c2f6b",
        "#f9c98a #fff2c4 #d99a6a #c9a46a #8a6a40 #3a6ab0 #ffffff #b05050 #ffd36a #ffffff #3a2a2a #fffbe8 #a04848 #ffffff #3a2a2a #ffd36a",
        "#1f4a5a #6ab0a0 #2f6a6a #2a3a2a #4a6a3a #e86a4a #ffd0a0 #c0c070 #f0f0a0 #a0f0e0 #0a1a1a #e0fff0 #0a1a1a #ffffff #e0fff0 #1f4a5a",
    ],
    "md": [
        "#0a0a3a #e04020 #3a0a4a #1a1a1a #606060 #00a0ff #ffffff #ff2060 #ffe000 #ffe000 #000000 #80ffff #000000 #ffffff #ffe000 #000000",
        "#20a0e0 #ffffa0 #2060a0 #e0a020 #a04000 #e00000 #ffffff #00a040 #ffffff #ffff00 #000000 #ffffff #000000 #ffffff #000000 #ffff00",
        "#400020 #ff6000 #200010 #302010 #804020 #e0e0e0 #ff2000 #ffa000 #ffe000 #ff4000 #000000 #ffd080 #000000 #ffffff #ffffff #400020",
        "#ff9020 #fff060 #a03000 #303030 #808080 #2040ff #ffffff #00c0c0 #ffffff #ffffff #000000 #ffffff #2040ff #ffffff #000000 #ffffff",
    ],
    "gba": [
        "#7ad7ff #d8f6ff #6fcf6f #5bbf3a #3a8f2a #ff5a3c #ffd166 #ffb000 #ffffff #ffe600 #1d1d3a #ffffff #c0302a #ffffff #1d1d3a #ffffff",
        "#3a2a8a #7a4ad0 #24206a #2a6a8a #1a4a6a #ffd23c #ff7a3c #ff4fa0 #ffffff #5affd0 #10102a #ffffff #10102a #ffffff #ffffff #3a2a8a",
        "#ffd36e #fff2c0 #ff9f5a #c97a3a #8a4a1a #3c7aff #ffffff #ff3c6e #ffe600 #ffffff #2a1a10 #ffffff #8a4a1a #ffffff #2a1a10 #ffd36e",
        "#0f5a4a #2fa07a #0a3a30 #4a3a2a #2a2018 #ff7ac0 #ffffff #ffd23c #ff8a2a #7affff #08201a #ffffff #0a3a30 #ffffff #ffd23c #08201a",
    ],
    "nds": [
        "#9be7ff #ffffff #b0b8ff #ffb6d9 #ff7ab0 #2a6aff #ffe08a #3cd070 #ffffff #ff3c3c #20203a #ffffff #2a5ad0 #ffffff #20203a #ffffff",
        "#2a1a4a #6a3a9a #1a1030 #3a2a6a #5a4a9a #ff9a3c #ffffff #3cffb0 #ffe63c #ff3c9a #0a0818 #ffffff #c02070 #ffffff #ffe63c #2a1a4a",
        "#c8f07a #f8ffd8 #7ac850 #8ad0ff #4a90d0 #e8402a #ffffff #ffb03c #ffffff #ff40a0 #1a2a10 #ffffff #4a7a20 #ffffff #1a2a10 #c8f07a",
        "#5a1a2a #c0503a #3a0a1a #2a2a3a #4a4a5a #3cc8ff #ffffff #ffd23c #ffffff #ffe63c #10060a #ffffff #10060a #ffffff #ffffff #5a1a2a",
    ],
    "n64": [
        "#3a8aff #bfe6ff #5aa05a #4ac04a #2a8a3a #ff3a3a #ffe0b0 #ffc83a #ffffff #ffe83a #1a1a40 #ffffff #c02a2a #ffffff #1a1a40 #ffe83a",
        "#1a1050 #8a3ac0 #2a1a6a #5a3aa0 #3a2a80 #ffd23a #ff6a3a #3affd0 #ffffff #ff3aff #0a0820 #ffffff #0a0820 #ffffff #ffffff #1a1050",
        "#ffb03a #fff0a0 #c0603a #e0c060 #a08030 #2a6aff #ffe0b0 #3ac05a #ffffff #ffffff #3a1a0a #ffffff #2a4ac0 #ffffff #3a1a0a #ffffff",
        "#0a3a3a #3aa0a0 #0a2a2a #3a6a2a #2a4a1a #ff8a3a #ffe83a #ff3a8a #ffffff #8affff #041414 #ffffff #0a2a2a #ffffff #ffe83a #041414",
    ],
    "ps": [
        "#1a1428 #6a3a4a #0e0a18 #2a2630 #4a4450 #c8b8a0 #8a2a2a #5a6a7a #d8c890 #ffd070 #050408 #ffe8c0 #050408 #ffffff #d8c890 #1a1428",
        "#c07a5a #f0c890 #6a3a3a #4a3a30 #7a5a40 #2a2a3a #a0a0b0 #8a4a2a #f0d0a0 #fff0c0 #140c0a #fff0d0 #4a2a2a #ffffff #140c0a #f0c890",
        "#0a1a2a #2a5a6a #06101a #1a2a2a #2a4040 #e0e0d0 #3a8aa0 #4a5a5a #c0d0c0 #80e0ff #020608 #e0ffff #06101a #ffffff #c0d0c0 #0a1a2a",
        "#a0a8b0 #e0e0d8 #606870 #3a3a3a #5a5a5a #8a1a1a #e0d0c0 #2a2a2a #c0b090 #ffffff #101010 #ffffff #2a2a2a #ffffff #101010 #e0e0d8",
    ],
}
PALETTES = {name: [dict(zip(ROLES, v.split())) for v in variants] for name, variants in _VARIANTS.items()}
#: The colours a pixel-era palette set may use, as its hardware could.
PIXEL_COLOURS = {"nes": set(_NES), "dmg": set(_DMG), "gbc": set(_GBC)}

COVER_W, COVER_H = 512, 768
BAND_H = round(COVER_H * 0.14)
TITLE_SIZE = 46
LABEL_LONG_SIDE = 512
#: What a title's plate allows per glyph of bold sans, in ems: there is no text
#: measuring in an SVG string, so sizing goes by this. A little wider than the
#: average advance (about 0.6): capitals run wider, and a title must not leave
#: its plate.
PLATE_EM = 0.68
FONT = 'font-family="sans-serif" font-weight="bold"'

#: The scene's own coordinate space; the cover shows all of it.
SCENE_W, SCENE_H = 100, 130
#: Side of a pixel-era cell, in output pixels, on covers and labels alike.
CELL = {"nes": 8, "dmg": 8, "gbc": 6}
#: Largest cell of the blocky pixel-era title.
TITLE_CELL = 6
#: Where the light comes from (up and to the left), for the low-poly facets.
LIGHT = (-0.6, -0.8)

# 5x7 bitmap font of the pixel-era titles: seven rows of five cells per glyph.
_FONT_ROWS = {
    "A": "01110 10001 10001 11111 10001 10001 10001",
    "B": "11110 10001 10001 11110 10001 10001 11110",
    "C": "01110 10001 10000 10000 10000 10001 01110",
    "D": "11110 10001 10001 10001 10001 10001 11110",
    "E": "11111 10000 10000 11110 10000 10000 11111",
    "F": "11111 10000 10000 11110 10000 10000 10000",
    "G": "01110 10001 10000 10111 10001 10001 01111",
    "H": "10001 10001 10001 11111 10001 10001 10001",
    "I": "01110 00100 00100 00100 00100 00100 01110",
    "J": "00111 00010 00010 00010 00010 10010 01100",
    "K": "10001 10010 10100 11000 10100 10010 10001",
    "L": "10000 10000 10000 10000 10000 10000 11111",
    "M": "10001 11011 10101 10101 10001 10001 10001",
    "N": "10001 10001 11001 10101 10011 10001 10001",
    "O": "01110 10001 10001 10001 10001 10001 01110",
    "P": "11110 10001 10001 11110 10000 10000 10000",
    "Q": "01110 10001 10001 10001 10101 10010 01101",
    "R": "11110 10001 10001 11110 10100 10010 10001",
    "S": "01111 10000 10000 01110 00001 00001 11110",
    "T": "11111 00100 00100 00100 00100 00100 00100",
    "U": "10001 10001 10001 10001 10001 10001 01110",
    "V": "10001 10001 10001 10001 10001 01010 00100",
    "W": "10001 10001 10001 10101 10101 10101 01010",
    "X": "10001 10001 01010 00100 01010 10001 10001",
    "Y": "10001 10001 01010 00100 00100 00100 00100",
    "Z": "11111 00001 00010 00100 01000 10000 11111",
    "0": "01110 10001 10011 10101 11001 10001 01110",
    "1": "00100 01100 00100 00100 00100 00100 01110",
    "2": "01110 10001 00001 00010 00100 01000 11111",
    "3": "11111 00010 00100 00010 00001 10001 01110",
    "4": "00010 00110 01010 10010 11111 00010 00010",
    "5": "11111 10000 11110 00001 00001 10001 01110",
    "6": "00110 01000 10000 11110 10001 10001 01110",
    "7": "11111 00001 00010 00100 01000 01000 01000",
    "8": "01110 10001 10001 01110 10001 10001 01110",
    "9": "01110 10001 10001 01111 00001 00010 01100",
    "-": "00000 00000 00000 11111 00000 00000 00000",
    " ": "00000 00000 00000 00000 00000 00000 00000",
}
FONT_5X7 = {char: rows.split() for char, rows in _FONT_ROWS.items()}


def slug(title):
    """``"Robot Man X"`` -> ``"robot-man-x"``, the cartridge wall's file key."""
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


def mix(hex_a, hex_b, t):
    """``hex_a`` moved ``t`` (0..1) of the way to ``hex_b``."""
    a = [int(hex_a[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(hex_b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(a, b))


def shade(hex_color, amount):
    """Lighter towards white for a positive ``amount``, darker for a negative."""
    return mix(hex_color, "#ffffff" if amount > 0 else "#000000", abs(amount))


def palette_for(console, index):
    """The palette variant (role -> colour) of a console's ``index``-th title.

    Each console starts somewhere else in its set, so two consoles' shelves do
    not open on the same colours.
    """
    variants = PALETTES[ERA_STYLE[console][1]]
    return variants[(list(TITLES).index(console) * 3 + index) % len(variants)]


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


# Scenes ---------------------------------------------------------------------
#
# A scene is a list of shapes in paint order, in a SCENE_W x SCENE_H space.
# ``kind`` is "rect" (x, y, w, h), "ellipse" (cx, cy, rx, ry) or "poly"
# (a tuple of points); ``focal`` marks what a label's crop keeps in view.

Shape = namedtuple("Shape", "kind geom role focal")


def R(x, y, w, h, role, focal=False):
    return Shape("rect", (x, y, w, h), role, focal)


def E(cx, cy, rx, ry, role, focal=False):
    return Shape("ellipse", (cx, cy, rx, ry), role, focal)


def P(points, role, focal=False):
    return Shape("poly", tuple(points), role, focal)


def bbox(shape):
    """(x0, y0, x1, y1) of a shape."""
    if shape.kind == "rect":
        x, y, w, h = shape.geom
        return x, y, x + w, y + h
    if shape.kind == "ellipse":
        cx, cy, rx, ry = shape.geom
        return cx - rx, cy - ry, cx + rx, cy + ry
    xs = [p[0] for p in shape.geom]
    ys = [p[1] for p in shape.geom]
    return min(xs), min(ys), max(xs), max(ys)


def contains(shape, x, y):
    """Whether the point lies inside the shape (even-odd rule for polygons)."""
    if shape.kind == "rect":
        sx, sy, w, h = shape.geom
        return sx <= x < sx + w and sy <= y < sy + h
    if shape.kind == "ellipse":
        cx, cy, rx, ry = shape.geom
        return ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1
    inside = False
    points = shape.geom
    for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1]):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside


def mirror(shape):
    """The shape flipped left to right across the scene."""
    if shape.kind == "rect":
        x, y, w, h = shape.geom
        return shape._replace(geom=(SCENE_W - x - w, y, w, h))
    if shape.kind == "ellipse":
        cx, cy, rx, ry = shape.geom
        return shape._replace(geom=(SCENE_W - cx, cy, rx, ry))
    return shape._replace(geom=tuple((SCENE_W - x, y) for x, y in shape.geom))


def _backdrop(horizon):
    """Sky over the whole scene, and its glow band down to the horizon."""
    return [R(0, 0, SCENE_W, SCENE_H, "sky"), R(0, horizon - 24, SCENE_W, 24, "sky2")]


def _figure(cx, foot, height, role="hero", role2="hero2", pose=0, facing=1, focal=True):
    """A generic person: 0 standing, 1 running or jumping, 2 fighting stance."""
    u = height / 10
    hip, shoulder = foot - 4.4 * u, foot - 7.8 * u

    def at(dx, y):
        return cx + facing * dx * u, y

    shapes = []
    if pose == 0:
        shapes += [P([at(-1.1, hip), at(-0.1, hip), at(-0.3, foot), at(-1.3, foot)], role, focal),
                   P([at(0.1, hip), at(1.1, hip), at(1.3, foot), at(0.3, foot)], role, focal)]
        arms = [P([at(-1.5, shoulder), at(-2.3, shoulder + 0.3 * u), at(-2.6, hip + 0.3 * u), at(-1.8, hip)], role2, focal),
                P([at(1.5, shoulder), at(2.3, shoulder + 0.3 * u), at(2.6, hip + 0.3 * u), at(1.8, hip)], role2, focal)]
    elif pose == 1:
        shapes += [P([at(-1.1, hip), at(0, hip), at(-2.4, foot - 0.6 * u), at(-3.4, foot - 1.4 * u)], role, focal),
                   P([at(0, hip), at(1.1, hip), at(2.8, hip + 2.0 * u), at(2.2, hip + 3.2 * u)], role, focal)]
        arms = [P([at(1.0, shoulder), at(1.8, shoulder + 0.6 * u), at(3.4, shoulder - 2.2 * u), at(2.6, shoulder - 2.8 * u)], role2, focal),
                P([at(-1.0, shoulder), at(-1.8, shoulder + 0.2 * u), at(-3.4, hip), at(-2.6, hip + 0.6 * u)], role2, focal)]
    else:
        shapes += [P([at(-1.1, hip), at(0, hip), at(-2.6, foot), at(-3.6, foot)], role, focal),
                   P([at(0, hip), at(1.1, hip), at(2.8, foot), at(1.8, foot)], role, focal)]
        arms = [P([at(1.2, shoulder + 0.2 * u), at(1.2, shoulder + 1.2 * u), at(4.2, shoulder + 1.0 * u), at(4.2, shoulder + 0.2 * u)], role2, focal),
                E(*at(4.7, shoulder + 0.6 * u), 0.8 * u, 0.8 * u, role2, focal),
                P([at(-1.2, shoulder), at(-1.2, shoulder + 1.2 * u), at(0.6, shoulder + 2.6 * u), at(1.0, shoulder + 1.6 * u)], role2, focal)]
    shapes.append(P([at(-1.5, shoulder), at(1.5, shoulder), at(1.1, hip), at(-1.1, hip)], role, focal))
    shapes += arms
    shapes.append(E(cx + facing * 0.2 * u, foot - 9 * u, 1.2 * u, 1.25 * u, role2, focal))
    shapes.append(R(cx - 1.2 * u, hip - 0.5 * u, 2.4 * u, 0.5 * u, "dark", focal))
    return shapes


def _platformer(i):
    k = i % 3
    shapes = _backdrop(84) + [
        E(18, 26 + 4 * k, 9, 4, "light"), E(26, 24 + 4 * k, 7, 5, "light"), E(78, 16, 8, 3.5, "light"),
        E(20, 86, 30, 14, "far"), E(76, 88, 34, 17, "far"),
        R(0, 84, SCENE_W, 46, "ground"), R(0, 84, SCENE_W, 3, "ground2"),
    ]
    for x, y, w in [(6 + 2 * k, 58, 26), (64 - 2 * k, 44, 28), (28, 26, 18)]:
        shapes += [R(x, y, w, 6, "prop"), R(x, y + 2.6, w, 0.8, "prop2")]
        shapes += [R(x + j * w / 3, y, 0.8, 6, "prop2") for j in (1, 2)]
        shapes += [E(x + w * (j + 1) / 3, y - 5, 1.8, 2.6, "accent") for j in range(2)]
    shapes += [E(50, 90, 8, 1.6, "dark")] + _figure(50, 72, 28, pose=1)
    return shapes


def _racer(i):
    k = i % 3
    shapes = _backdrop(56) + [
        E(78 - 6 * k, 34, 9, 9, "accent"),
        P([(0, 56), (18, 40), (36, 56)], "far"), P([(28, 56), (56, 34), (84, 56)], "far"),
        P([(68, 56), (88, 44), (100, 50), (100, 56)], "far"),
        R(0, 56, SCENE_W, 74, "ground2"),
        P([(47, 56), (53, 56), (100, 106), (100, 130), (0, 130), (0, 106)], "ground"),
    ]
    for y0, y1 in [(58, 62), (66, 74), (82, 96), (106, 130)]:
        w0, w1 = 0.3 + (y0 - 56) * 0.05, 0.3 + (y1 - 56) * 0.05
        shapes.append(P([(50 - w0, y0), (50 + w0, y0), (50 + w1, y1), (50 - w1, y1)], "light"))
    shapes += [
        R(29, 86, 8, 7, "dark", True), R(63, 86, 8, 7, "dark", True),
        P([(31, 88), (69, 88), (67, 72), (33, 72)], "hero", True),
        P([(38, 72), (62, 72), (58, 61), (42, 61)], "hero", True),
        P([(40, 71), (60, 71), (57, 63), (43, 63)], "dark", True),
        R(32, 69, 36, 2.4, "hero2", True),
        R(34, 77, 8, 3.4, "accent", True), R(58, 77, 8, 3.4, "accent", True),
        R(45, 81, 10, 3, "light", True),
    ]
    return shapes


def _fighter(i):
    k = i % 2
    shapes = _backdrop(78) + [
        R(0, 54, SCENE_W, 24, "far"),
        R(8, 26, 7, 52, "prop"), R(85, 26, 7, 52, "prop"),
        P([(15, 30), (30, 30), (22.5, 42)], "accent"), P([(70, 30), (85, 30), (77.5, 42)], "accent"),
        R(0, 78, SCENE_W, 52, "ground"), R(0, 78, SCENE_W, 1.5, "ground2"),
        E(34, 94, 10, 1.8, "dark"), E(68, 94, 10, 1.8, "dark"),
    ]
    shapes += [E(6 + 9 * j, 60 + 3 * ((j + k) % 2), 3, 3, "dark") for j in range(11)]
    shapes += _figure(33, 93, 36, pose=2) + _figure(68, 93, 34, "prop", "hero2", pose=2, facing=-1)
    return shapes


def _action(i):
    k = i % 3
    shapes = _backdrop(80) + [
        R(2, 50, 14, 30, "far"), R(16, 58, 12, 22, "far"), R(70, 44, 12, 36, "far"), R(84, 56, 14, 24, "far"),
        R(74, 30 + 4 * k, 4, 16, "far"), E(76, 26 + 4 * k, 5, 3, "light"), E(80, 21 + 4 * k, 4, 2.4, "light"),
        R(0, 80, SCENE_W, 50, "ground"),
    ]
    shapes += [P([(x, 80), (x + 4, 80), (x + 1, 84), (x - 3, 84)], "accent") for x in range(4, 100, 12)]
    shapes += [
        E(50, 92, 14, 2, "dark", True),
        R(41, 72, 6, 17, "hero", True), R(53, 72, 6, 17, "hero", True),
        R(39, 88, 9, 4, "dark", True), R(52, 88, 9, 4, "dark", True),
        R(38, 46, 24, 27, "hero", True), R(43, 51, 14, 9, "hero2", True),
        R(43, 33, 14, 12, "hero", True), R(45, 37, 10, 3.5, "accent", True),
        R(49.4, 26, 1.2, 7, "dark", True), E(50, 25, 2, 2, "accent", True),
        R(32, 48, 6, 20, "hero2", True),
        R(62, 50, 20, 7, "hero2", True), R(82, 51.5, 4, 4, "dark", True),
        P([(86, 53.5), (92, 48), (90, 53.5), (96, 55), (90, 56), (92, 61)], "accent"),
    ]
    return shapes


def _shmup(i):
    k = i % 3
    shapes = _backdrop(130)
    shapes += [R((j * 37 + 11 * k) % 97, (j * 23) % 120, 1, 1, "light") for j in range(26)]
    shapes += [E(78, 34, 16, 16, "far"), E(78, 34, 24, 3.4, "prop2"), E(78, 32, 16, 3, "far")]
    for row in range(2):
        for col in range(4):
            x, y = 22 + col * 14 + 7 * row, 12 + row * 10
            shapes += [P([(x, y), (x + 4.5, y + 3), (x, y + 6), (x - 4.5, y + 3)], "prop"),
                       R(x - 1, y + 2, 2, 2, "dark")]
    shapes += [
        R(41.5, 24, 1.4, 28, "accent"), R(57.1, 24, 1.4, 28, "accent"),
        P([(46, 80), (50, 92), (54, 80)], "accent", True),
        P([(43, 70), (26, 86), (45, 81)], "hero2", True), P([(57, 70), (74, 86), (55, 81)], "hero2", True),
        P([(50, 50), (58, 80), (50, 76), (42, 80)], "hero", True),
        E(50, 64, 2.6, 5, "accent", True),
    ]
    return shapes


def _rpg(i):
    k = i % 2
    shapes = _backdrop(80) + [
        E(70, 84, 40, 24, "far"),
        R(60, 46, 22, 22, "prop"), R(56, 36, 7, 32, "prop"), R(79, 36, 7, 32, "prop"),
        P([(55, 36), (59.5, 26), (64, 36)], "hero"), P([(78, 36), (82.5, 26), (87, 36)], "hero"),
        R(68, 56, 6, 12, "dark"), R(62, 50, 3, 4, "accent"), R(77, 50, 3, 4, "accent"),
    ]
    shapes += [R(60 + 4.4 * j, 43, 2.4, 3, "prop") for j in range(5)]
    dx = 12 * k
    shapes += [
        P([(14 + dx, 22), (24 + dx, 18), (34 + dx, 22), (28 + dx, 26), (20 + dx, 26)], "dark"),
        P([(20 + dx, 21), (26 + dx, 8), (28 + dx, 21)], "dark"),
        P([(34 + dx, 22), (40 + dx, 17), (38 + dx, 23)], "dark"),
        R(0, 86, SCENE_W, 44, "ground"), R(0, 86, SCENE_W, 2, "ground2"),
    ]
    shapes += _figure(16, 98, 22, "prop", "hero2", pose=0)
    shapes += _figure(30, 100, 26, pose=0) + [R(36, 66, 1.4, 22, "light", True)]
    shapes += _figure(44, 98, 21, "prop2", "hero2", pose=0) + [R(48, 72, 1.2, 26, "dark", True),
                                                               E(48.6, 72, 2, 2, "accent", True)]
    return shapes


def _puzzle(i):
    roles = ["hero", "prop", "accent", "prop2", "hero2"]
    shapes = _backdrop(100) + [R(20, 10, 60, 90, "dark", True), R(22, 12, 56, 86, "far", True)]
    w, h = 56 / 6, 86 / 8
    for row in range(8):
        for col in range(6):
            filled = row >= 3 + (col * 2 + i) % 3
            if not filled:
                continue
            x, y = 22 + col * w, 12 + row * h
            role = roles[(row * 7 + col * 3 + i) % 5]
            if (row + col) % 2:
                shapes.append(P([(x + w / 2, y + 1), (x + w - 1, y + h / 2), (x + w / 2, y + h - 1), (x + 1, y + h / 2)], role, True))
            else:
                shapes.append(E(x + w / 2, y + h / 2, w / 2 - 1, h / 2 - 1.2, role, True))
            shapes.append(E(x + w / 2 - 1.2, y + h / 2 - 1.6, 1, 1, "light"))
    x = 22 + w * (2 + i % 2)
    shapes += [E(x + w / 2, 12 + h / 2, w / 2 - 1, h / 2 - 1.2, roles[i % 5], True),
               E(x + w * 1.5, 12 + h / 2, w / 2 - 1, h / 2 - 1.2, roles[(i + 2) % 5], True)]
    return shapes


def _sports(i):
    k = i % 3
    shapes = _backdrop(50) + [R(0, 26, SCENE_W, 24, "far")]
    shapes += [E(4 + 6 * j, 32 + 6 * (j % 3), 2, 2, "prop2" if (j + k) % 3 else "accent") for j in range(16)]
    shapes += [
        R(0, 50, SCENE_W, 80, "ground"), R(0, 74, SCENE_W, 1.2, "light"),
        E(50, 92, 24, 7.5, "light"), E(50, 92, 22.4, 6.2, "ground"),
        R(0, 58, SCENE_W, 4, "ground2"), R(0, 106, SCENE_W, 4, "ground2"),
        E(44, 96, 9, 1.6, "dark"),
    ]
    shapes += _figure(42, 95, 36, pose=1)
    shapes += [E(66 - 4 * k, 60, 5, 5, "light", True), E(66 - 4 * k, 60, 2, 2, "dark", True)]
    return shapes


def _adventure(i):
    k = i % 2
    shapes = _backdrop(80) + [
        E(12, 64, 16, 14, "far"), E(88, 62, 18, 16, "far"), E(50, 70, 20, 10, "far"),
        R(8, 38, 7, 42, "prop"), R(6, 36, 11, 3, "prop2"),
        R(22, 52, 7, 28, "prop"), P([(22, 52), (29, 52), (29, 49), (25, 47)], "prop"),
        P([(64, 80), (64, 50), (70, 44), (80, 44), (86, 50), (86, 80), (81, 80), (81, 52), (69, 52), (69, 80)], "prop"),
        R(0, 80, SCENE_W, 50, "ground"), R(0, 80, SCENE_W, 2, "ground2"),
        E(56, 96, 9, 1.6, "dark"),
    ]
    shapes += _figure(54, 95, 32, pose=k)
    shapes += [E(54.6, 63, 7, 1.6, "prop2", True), R(51.6, 57.5, 6, 5, "prop2", True)]
    shapes += [E(80, 66, 8, 8, "accent", True), E(80, 66, 6.2, 6.2, "light", True),
               P([(80, 60.5), (81.5, 66), (80, 71.5), (78.5, 66)], "hero", True), E(80, 66, 1, 1, "dark", True)]
    return shapes


def _kart_shape(cx, cy, s, role, role2, focal):
    return [
        R(cx - 7 * s, cy - 1 * s, 4 * s, 4 * s, "dark", focal), R(cx + 3 * s, cy - 1 * s, 4 * s, 4 * s, "dark", focal),
        P([(cx - 6 * s, cy), (cx + 6 * s, cy), (cx + 5 * s, cy - 4 * s), (cx - 5 * s, cy - 4 * s)], role, focal),
        R(cx - 6.5 * s, cy - 6 * s, 13 * s, 1.6 * s, role2, focal),
        E(cx, cy - 7 * s, 2.6 * s, 2.6 * s, role2, focal), R(cx - 2 * s, cy - 7.6 * s, 4 * s, 1.2 * s, "dark", focal),
    ]


def _kart(i):
    k = i % 2
    shapes = _backdrop(54) + [
        E(20, 30, 10, 4, "light"), E(70 + 6 * k, 24, 12, 4, "light"),
        R(0, 54, SCENE_W, 76, "ground2"),
        P([(0, 90), (30, 76), (62, 68), (100, 64), (100, 80), (68, 86), (38, 98), (0, 114)], "ground"),
    ]
    shapes += [P([(x, y), (x + 5, y - 1.6), (x + 5, y + 0.4), (x, y + 2)], "accent" if j % 2 else "light")
               for j, (x, y) in enumerate([(2, 88), (12, 83.4), (22, 79), (32, 75), (42, 72.6), (52, 70.4), (62, 68.2), (72, 66.4), (82, 65), (92, 64)])]
    shapes += _kart_shape(70, 74, 0.8, "prop", "prop2", False) + _kart_shape(40, 88, 1.6, "hero", "hero2", True)
    return shapes


def _brawler(i):
    k = i % 3
    shapes = _backdrop(84)
    for x, top in [(0, 30), (16, 44), (30, 24), (66, 36), (82, 20)]:
        shapes.append(R(x, top, 15, 84 - top, "far"))
        shapes += [R(x + 2 + 5 * c, top + 4 + 8 * r, 3, 4, "accent" if (r + c + k) % 3 == 0 else "dark")
                   for r in range(int((80 - top) / 8)) for c in range(3)]
    shapes += [
        R(0, 84, SCENE_W, 46, "ground"), R(0, 84, SCENE_W, 2, "ground2"),
        R(88, 40, 1.6, 44, "dark"), E(86, 40, 4, 2, "accent"),
        E(46, 97, 11, 1.8, "dark"),
    ]
    shapes += _figure(80, 92, 26, "prop", "hero2", pose=0, facing=-1, focal=False)
    shapes += _figure(44, 96, 38, pose=2)
    return shapes


def _rhythm(i):
    k = i % 3
    shapes = _backdrop(86) + [
        P([(18, 0), (25, 0), (46, 86), (30, 86)], "prop2"), P([(75, 0), (82, 0), (70, 86), (54, 86)], "prop2"),
        R(3, 58, 13, 28, "dark"), E(9.5, 66, 4, 4, "far"), E(9.5, 78, 4.6, 4.6, "far"),
        R(84, 58, 13, 28, "dark"), E(90.5, 66, 4, 4, "far"), E(90.5, 78, 4.6, 4.6, "far"),
        R(0, 86, SCENE_W, 44, "ground"), R(0, 86, SCENE_W, 2, "accent"),
    ]
    for x, y in [(18 + 4 * k, 30), (76 - 4 * k, 22), (66, 46)]:
        shapes += [E(x, y, 3, 2.4, "accent"), R(x + 2.2, y - 10, 1, 10, "accent"),
                   P([(x + 3.2, y - 10), (x + 7, y - 7), (x + 3.2, y - 6)], "accent")]
    shapes += [E(50, 90, 10, 1.8, "dark")] + _figure(50, 88, 40, pose=1)
    return shapes


def _horror(i):
    k = i % 2
    shapes = _backdrop(82) + [
        E(76, 24, 11, 11, "light"),
        E(50, 102, 74, 28, "far"),
        R(30, 50, 40, 30, "prop", True), P([(26, 50), (50, 32), (74, 50)], "dark", True),
        R(58, 34, 9, 20, "prop", True), P([(57, 34), (62.5, 22), (68, 34)], "dark", True),
        R(47, 66, 6, 14, "dark", True),
    ]
    shapes += [R(x, y, 5, 6, "accent" if (j + k) % 3 == 0 else "dark", True)
               for j, (x, y) in enumerate([(34, 55), (42, 55), (55, 55), (63, 55), (34, 67), (61, 67), (60.5, 40)])]
    shapes += [
        P([(10, 90), (13, 90), (13, 62), (20, 50), (18.5, 49), (12, 58), (11, 44), (9.5, 44), (10, 60), (4, 52), (3, 53.5), (10, 64)], "dark"),
        P([(80, 44), (84, 40), (86, 43), (88, 40), (92, 44), (86, 45)], "dark"),
        P([(18 + 50 * k, 30), (21 + 50 * k, 27), (22 + 50 * k, 29.5), (23 + 50 * k, 27), (26 + 50 * k, 30), (22 + 50 * k, 31)], "dark"),
        R(0, 90, SCENE_W, 40, "ground"),
    ]
    return shapes


def _flight(i):
    k = i % 3
    shapes = _backdrop(72) + [
        E(16, 30 + 3 * k, 12, 4.4, "light"), E(24, 27 + 3 * k, 8, 4, "light"),
        E(80, 22, 13, 4.4, "light"), E(70, 82, 16, 4, "light"),
        R(0, 72, SCENE_W, 58, "ground"),
    ]
    shapes += [R((j * 29) % 90, 78 + j * 5, 10, 1, "ground2") for j in range(8)]
    shapes += [
        R(6, 50.5, 16, 1.2, "light"), R(2, 53.5, 18, 1.2, "light"),
        P([(28, 51), (33, 51), (27, 38), (23, 38)], "hero2", True),
        E(50, 52, 23, 5.4, "hero", True), R(36, 50.5, 26, 1.6, "hero2", True),
        P([(44, 53), (57, 53), (49, 72), (40, 72)], "hero2", True),
        E(57, 48, 5, 3, "dark", True), E(73, 52, 2, 2, "dark", True), E(74, 52, 1.2, 9, "dark", True),
    ]
    return shapes


#: Genre -> scene builder ``(index) -> [Shape]``.
SCENES = {
    "platformer": _platformer, "racer": _racer, "fighter": _fighter, "action": _action,
    "shmup": _shmup, "rpg": _rpg, "puzzle": _puzzle, "sports": _sports,
    "adventure": _adventure, "kart": _kart, "brawler": _brawler, "rhythm": _rhythm,
    "horror": _horror, "flight": _flight,
}


def scene(title, index):
    """The shapes of a title's art; every other title is mirrored."""
    shapes = SCENES[GENRE[title]](index)
    return [mirror(s) for s in shapes] if index % 2 else shapes


def crop_view(shapes, aspect):
    """The (x, y, w, h) window of the scene a label shows, of the given aspect.

    Around the focal shapes with some room, as large as the aspect lets it be
    inside the scene, and never past its edges.
    """
    focal = [bbox(s) for s in shapes if s.focal] or [(0, 0, SCENE_W, SCENE_H)]
    x0, y0 = min(b[0] for b in focal), min(b[1] for b in focal)
    x1, y1 = max(b[2] for b in focal), max(b[3] for b in focal)
    w, h = (x1 - x0) * 1.3, (y1 - y0) * 1.3
    if w / h < aspect:
        w = h * aspect
    else:
        h = w / aspect
    if w > SCENE_W:
        w, h = SCENE_W, SCENE_W / aspect
    if h > SCENE_H:
        w, h = SCENE_H * aspect, SCENE_H
    x = min(max((x0 + x1) / 2 - w / 2, 0), SCENE_W - w)
    y = min(max((y0 + y1) / 2 - h / 2, 0), SCENE_H - h)
    return x, y, w, h


# Era renderers ---------------------------------------------------------------
#
# Each takes the shapes, the palette, the window of the scene to show and the
# pixel box (x, y, w, h) to draw it in, and returns an SVG fragment.

def _f(value):
    return f"{value:.1f}"


def _shape_svg(shape, fill, extra=""):
    if shape.kind == "rect":
        x, y, w, h = shape.geom
        return f'<rect x="{_f(x)}" y="{_f(y)}" width="{_f(w)}" height="{_f(h)}" fill="{fill}"{extra}/>'
    if shape.kind == "ellipse":
        cx, cy, rx, ry = shape.geom
        return f'<ellipse cx="{_f(cx)}" cy="{_f(cy)}" rx="{_f(rx)}" ry="{_f(ry)}" fill="{fill}"{extra}/>'
    points = " ".join(f"{_f(x)},{_f(y)}" for x, y in shape.geom)
    return f'<polygon points="{points}" fill="{fill}"{extra}/>'


def _viewport(view, box, body):
    """``body`` (scene units) shown through ``view`` in the pixel ``box``."""
    vx, vy, vw, vh = view
    x, y, w, h = box
    return (
        f'<svg x="{x}" y="{y}" width="{w}" height="{h}" viewBox="{_f(vx)} {_f(vy)} {_f(vw)} {_f(vh)}" '
        f'preserveAspectRatio="xMidYMid slice">{body}</svg>'
    )


def _gradients(pal, ground_depth=None):
    """The sky and glow gradients, and the ground's when ``ground_depth`` is given."""
    ground = "" if ground_depth is None else (
        f'<linearGradient id="ground" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{pal["ground"]}"/>'
        f'<stop offset="1" stop-color="{mix(pal["ground"], pal["dark"], ground_depth)}"/></linearGradient>'
    )
    return (
        '<defs>'
        f'<linearGradient id="sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{pal["sky"]}"/>'
        f'<stop offset="1" stop-color="{pal["sky2"]}"/></linearGradient>'
        f'<linearGradient id="glow" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{pal["sky2"]}" stop-opacity="0"/>'
        f'<stop offset="1" stop-color="{pal["sky2"]}"/></linearGradient>'
        + ground + '</defs>'
    )


def _gradient_fill(shape, pal):
    """The gradient a painted or low-poly backdrop shape takes, if any."""
    if shape.role == "sky" and shape.geom == (0, 0, SCENE_W, SCENE_H):
        return "url(#sky)"
    if shape.role == "sky2":
        return "url(#glow)"
    return None


def render_pixel(shapes, pal, view, box, cell):
    """The scene sampled on a grid of ``cell``-pixel squares.

    Each cell takes the colour of the topmost shape under its centre, and a run
    of equal cells in a row becomes one rect.
    """
    vx, vy, vw, vh = view
    x0, y0, w, h = box
    scale = max(w / vw, h / vh)
    boxes = [bbox(s) for s in shapes]
    rows = []
    for r in range(math.ceil(h / cell)):
        sy = vy + vh / 2 + ((r + 0.5) * cell - h / 2) / scale
        colours = []
        for c in range(math.ceil(w / cell)):
            sx = vx + vw / 2 + ((c + 0.5) * cell - w / 2) / scale
            colour = pal["sky"]
            for shape, (bx0, by0, bx1, by1) in zip(reversed(shapes), reversed(boxes)):
                if bx0 <= sx <= bx1 and by0 <= sy <= by1 and contains(shape, sx, sy):
                    colour = pal[shape.role]
                    break
            colours.append(colour)
        rows.append(colours)
    body = "".join(
        f'<rect x="{c * cell}" y="{r * cell}" width="{n * cell}" height="{cell}" fill="{colour}"/>'
        for r, colours in enumerate(rows) for c, n, colour in runs(colours)
    )
    return f'<svg x="{x0}" y="{y0}" width="{w}" height="{h}" shape-rendering="crispEdges">{body}</svg>'


def runs(values):
    """``[(start, length, value), ...]`` of the equal runs of a sequence."""
    out = []
    for i, value in enumerate(values):
        if out and out[-1][2] == value:
            start, length, _ = out[-1]
            out[-1] = (start, length + 1, value)
        else:
            out.append((i, 1, value))
    return out


def render_painted(shapes, pal, view, box, hard=False):
    """Gradient sky and ground, a rim light on the hero; ``hard`` for MD."""
    rim = (
        f' stroke="{pal["light"]}" stroke-width="{0.9 if hard else 0.5}" stroke-linejoin="round"'
        + ("" if hard else ' stroke-opacity="0.8"')
    )
    body = _gradients(pal, 0.7 if hard else 0.4)
    for shape in shapes:
        fill = _gradient_fill(shape, pal) or ("url(#ground)" if shape.role == "ground" else pal[shape.role])
        body += _shape_svg(shape, fill, rim if shape.role in ("hero", "hero2") else "")
    return _viewport(view, box, body)


def render_cartoon(shapes, pal, view, box):
    """Flat fills, every shape outlined, a highlight on the round ones."""
    outline = f' stroke="{pal["dark"]}" stroke-width="0.9" stroke-linejoin="round"'
    body = ""
    for shape in shapes:
        backdrop = shape.role in ("sky", "sky2")
        body += _shape_svg(shape, pal[shape.role], "" if backdrop else outline)
        if shape.kind == "ellipse" and shape.role in ("hero", "hero2", "prop", "accent") and shape.geom[2] > 1.5:
            cx, cy, rx, ry = shape.geom
            body += _shape_svg(E(cx - rx * 0.35, cy - ry * 0.4, rx * 0.25, ry * 0.18, "light"), pal["light"])
    return _viewport(view, box, body)


def polygon_of(shape):
    """A shape's outline as points: ellipses become 6- or 8-gons."""
    if shape.kind == "rect":
        x, y, w, h = shape.geom
        return [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
    if shape.kind == "ellipse":
        cx, cy, rx, ry = shape.geom
        sides = 8 if max(rx, ry) > 4 else 6
        return [(cx + rx * math.cos(2 * math.pi * (j + 0.5) / sides), cy + ry * math.sin(2 * math.pi * (j + 0.5) / sides))
                for j in range(sides)]
    return list(shape.geom)


def facets(points):
    """The polygon fanned from its centroid: ``[(triangle, light), ...]``.

    ``light`` is -1..1, how squarely the facet's outer edge faces ``LIGHT``.
    """
    cx = sum(p[0] for p in points) / len(points)
    cy = sum(p[1] for p in points) / len(points)
    out = []
    for a, b in zip(points, points[1:] + points[:1]):
        mx, my = (a[0] + b[0]) / 2 - cx, (a[1] + b[1]) / 2 - cy
        length = math.hypot(mx, my) or 1
        out.append((((cx, cy), a, b), (mx * LIGHT[0] + my * LIGHT[1]) / length))
    return out


def is_convex(points):
    """Whether the polygon turns the same way at every corner."""
    signs = set()
    count = len(points)
    for j in range(count):
        (ax, ay), (bx, by), (cx, cy) = points[j], points[(j + 1) % count], points[(j + 2) % count]
        cross = (bx - ax) * (cy - by) - (by - ay) * (cx - bx)
        if cross:
            signs.add(cross > 0)
    return len(signs) <= 1


def render_lowpoly(shapes, pal, view, box, fog=False):
    """Flat-shaded facets under a CG sky; ``fog`` lays a band over the horizon.

    A convex outline is fanned into facets from its centroid. A concave one
    (an arch, a bare tree) is drawn as one flat facet instead: fanning it would
    fill its notches.
    """
    body = _gradients(pal)
    for shape in shapes:
        fill = _gradient_fill(shape, pal)
        if fill:
            body += _shape_svg(shape, fill)
            continue
        points = polygon_of(shape)
        if not is_convex(points):
            colour = pal[shape.role]
            body += _shape_svg(P(points, shape.role), colour, f' stroke="{colour}" stroke-width="0.2" stroke-linejoin="round"')
            continue
        for triangle, light in facets(points):
            colour = shade(pal[shape.role], 0.22 * light)
            body += _shape_svg(P(triangle, shape.role), colour, f' stroke="{colour}" stroke-width="0.2" stroke-linejoin="round"')
    if fog:
        body += f'<rect x="0" y="66" width="{SCENE_W}" height="22" fill="{pal["sky2"]}" fill-opacity="0.28"/>'
    return _viewport(view, box, body)


def render_scene(console, shapes, pal, view, box):
    """The scene in the console's era style."""
    renderer, palette_set = ERA_STYLE[console]
    if renderer == "pixel":
        return render_pixel(shapes, pal, view, box, CELL[palette_set])
    if renderer == "painted":
        return render_painted(shapes, pal, view, box, hard=palette_set == "md")
    if renderer == "cartoon":
        return render_cartoon(shapes, pal, view, box)
    return render_lowpoly(shapes, pal, view, box, fog=palette_set == "ps")


# Titles ----------------------------------------------------------------------

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


def pixel_text_width(text, cell):
    """Width of a line of the bitmap font: 5 cells a glyph, 1 between them."""
    return (6 * len(text) - 1) * cell


def pixel_text(lines, cx, top, cell, colour):
    """Lines of the 5x7 bitmap font, each centred on ``cx``, as cell rects.

    Lower case is drawn in capitals; a character the font lacks raises
    ``ValueError`` rather than silently leaving a gap in a title.
    """
    out = []
    for n, line in enumerate(lines):
        line = line.upper()
        missing = [char for char in line if char not in FONT_5X7]
        if missing:
            raise ValueError(f"no glyph for {missing[0]!r} in {line!r}")
        x0 = cx - pixel_text_width(line, cell) // 2
        y0 = top + n * 9 * cell
        for r in range(7):
            cells = "".join(FONT_5X7[char][r] + "0" for char in line)
            out += [f'<rect x="{x0 + c * cell}" y="{y0 + r * cell}" width="{k * cell}" height="{cell}" fill="{colour}"/>'
                    for c, k, value in runs(cells) if value == "1"]
    return "".join(out)


def title_layout(title, renderer, width, height, max_size):
    """Fit a title in ``width`` x ``height``: ``(lines, size, plate_w, plate_h)``.

    ``size`` is the cell of the bitmap font for the pixel eras, the font size
    for the others. One line or two, whichever lets the title be larger.
    """
    best = None
    for lines in ([title], wrap(title, len(title) - 1)):
        longest, count = max(len(line) for line in lines), len(lines)
        if renderer == "pixel":
            size = min(max_size, width // (6 * longest + 3), height // (9 * count + 2))
            plate_w, plate_h = (6 * longest + 3) * size, (9 * count + 2) * size
        else:
            size = int(min(max_size, width / (longest * PLATE_EM + 0.8), height / (1.15 * count + 0.7)))
            plate_w, plate_h = round(longest * size * PLATE_EM + 0.8 * size), round((1.15 * count + 0.7) * size)
        if best is None or size > best[1]:
            best = (lines, size, plate_w, plate_h)
    return best


def title_svg(console, pal, title, box, align="center", max_size=TITLE_SIZE):
    """The title on its era plate, fitted into the pixel ``box``.

    ``align`` "start" sits the plate at the box's bottom left (the cover),
    "center" in its middle (the label). The ink is always drawn on the plate's
    one solid colour, so its contrast does not depend on the scene behind.
    """
    renderer = ERA_STYLE[console][0]
    bx, by, bw, bh = box
    if renderer == "pixel":
        max_size = min(max_size, TITLE_CELL)
    lines, size, pw, ph = title_layout(title, renderer, bw, bh, max_size)
    px = bx if align == "start" else bx + (bw - pw) // 2
    py = by + bh - ph if align == "start" else by + (bh - ph) // 2
    plate, ink = pal["plate"], pal["ink"]
    if renderer == "pixel":
        return (
            f'<g shape-rendering="crispEdges"><rect x="{px}" y="{py}" width="{pw}" height="{ph}" fill="{ink}"/>'
            f'<rect x="{px + size}" y="{py + size}" width="{pw - 2 * size}" height="{ph - 2 * size}" fill="{plate}"/>'
            + pixel_text(lines, px + pw // 2, py + 2 * size, size, ink) + "</g>"
        )
    if renderer == "painted":
        frame = (f'<rect x="{px}" y="{py}" width="{pw}" height="{ph}" fill="{plate}"/>'
                 f'<rect x="{px}" y="{py}" width="{pw}" height="3" fill="{pal["light"]}"/>')
    elif renderer == "cartoon":
        frame = (f'<rect x="{px}" y="{py}" width="{pw}" height="{ph}" rx="{min(ph // 3, 18)}" fill="{plate}" '
                 f'stroke="{pal["dark"]}" stroke-width="4"/>')
    else:
        b = max(3, size // 6)
        frame = (
            f'<rect x="{px}" y="{py}" width="{pw}" height="{ph}" fill="{plate}"/>'
            f'<polygon points="{px},{py} {px + pw},{py} {px + pw - b},{py + b} {px + b},{py + b}" fill="{shade(plate, 0.25)}"/>'
            f'<polygon points="{px + b},{py + ph - b} {px + pw - b},{py + ph - b} {px + pw},{py + ph} {px},{py + ph}" '
            f'fill="{shade(plate, -0.25)}"/>'
        )
    baseline = py + ph - round(0.35 * size) - round(size * 0.22)
    return frame + _text_lines(lines, px + pw // 2, baseline, size, ink, anchor="middle")


# Covers and labels -----------------------------------------------------------

def cover_svg(console, index, title):
    """The 512x768 box cover of a console's ``index``-th title."""
    pal = palette_for(console, index)
    era_size = 26
    pad = 24
    body = (
        render_scene(console, scene(title, index), pal, (0, 0, SCENE_W, SCENE_H),
                     (0, BAND_H, COVER_W, COVER_H - BAND_H))
        + f'<rect width="{COVER_W}" height="{BAND_H}" fill="{pal["band"]}"/>'
        f'<text x="{pad}" y="{BAND_H // 2 + round(era_size * 0.36)}" {FONT} font-size="{era_size}" '
        f'letter-spacing="{era_size * 0.12:.1f}" fill="{pal["era"]}">{ERA[console]}</text>'
        + title_svg(console, pal, title, (pad, COVER_H - 28 - 170, COVER_W - 2 * pad, 170), align="start")
    )
    return _svg(COVER_W, COVER_H, body)


def label_size(aspect):
    """Pixel size of a label: its long side is ``LABEL_LONG_SIDE``."""
    if aspect >= 1:
        return LABEL_LONG_SIDE, round(LABEL_LONG_SIDE / aspect)
    return round(LABEL_LONG_SIDE * aspect), LABEL_LONG_SIDE


def label_regions(width, height, aspect):
    """``(scene_box, title_box)`` of a label, in pixels.

    A wide window puts the scene left of the title (SMS's thin strip keeps the
    scene narrow so the title can take its whole height); a tall or square one
    (FC, N64, the handhelds) stacks the scene above the title.
    """
    if aspect >= 1.3:
        split = round(width * (0.24 if aspect > 4 else 0.42))
        margin = round(height * 0.06)
        return (0, 0, split, height), (split + margin, margin, width - split - 2 * margin, height - 2 * margin)
    split = round(height * 0.6)
    margin = round(width * 0.06)
    return (0, 0, width, split), (margin, split + margin, width - 2 * margin, height - split - 2 * margin)


def label_svg(console, index, title, aspect):
    """The cartridge label: the cover's scene cropped around its hero, and the title."""
    pal = palette_for(console, index)
    width, height = label_size(aspect)
    scene_box, title_box = label_regions(width, height, aspect)
    shapes = scene(title, index)
    view = crop_view(shapes, scene_box[2] / scene_box[3])
    body = (
        f'<rect width="{width}" height="{height}" fill="{pal["band"]}"/>'
        + render_scene(console, shapes, pal, view, scene_box)
        + title_svg(console, pal, title, title_box)
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
            if not label.is_file():
                # The compositor draws a blank sticker for a missing cover, so
                # a wrong roms_dir would quietly publish blank cartridges.
                raise FileNotFoundError(f"{label} is missing: run demo_library.py {roms_dir} first")
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
    if args.wall and args.configure:
        parser.error("--wall only composites the labels; run --configure separately")

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
