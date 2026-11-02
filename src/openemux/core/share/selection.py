"""What the user picked to send, on top of a built manifest (#589).

The "What to Send" page lists each game's items in seven groups -- the game
itself, its battery save, its save states, the cover, the cartridge label, the
console's BIOS files and the library details -- and the user unchecks whole
groups. A game and its
groups are keyed by the game's main file (the ROM, or its cue or m3u), which
stays the same when the manifest is built again for the real send, unlike the
positional item ids.

BIOS files belong to a console, not a game: the first game of each console
carries them (issue 677). Their group is keyed by the console instead, so
unchecking it holds for the console whichever game carries the files, and a
carrier left out hands them to the next game of its console.

Pure: no GTK, no files read.
"""

import copy

from openemux.core.share.manifest import BuiltManifest
from openemux.core.share.protocol import (
    KIND_BATTERY_SAVE,
    KIND_BIOS,
    KIND_COVER,
    KIND_LABEL,
    KIND_ROM,
    KIND_STATE,
)

GAME = "game"
BATTERY = "battery"
STATES = "states"
COVER = "cover"
LABEL = "label"
BIOS = "bios"
DETAILS = "details"
#: The groups in the order the page lists them.
CATEGORIES = (GAME, BATTERY, STATES, COVER, LABEL, BIOS, DETAILS)
_CATEGORY_OF = {
    KIND_ROM: GAME,
    KIND_BATTERY_SAVE: BATTERY,
    KIND_STATE: STATES,
    KIND_COVER: COVER,
    KIND_LABEL: LABEL,
    KIND_BIOS: BIOS,
}


def roms_for_console(playlists, console):
    """Every game of ``console``, as the scanner's rom dicts."""
    return list(playlists.load_playlist(console))


def game_key(built, game):
    """The main file a manifest game was built from."""
    return str(built.sources[game["items"][0]["id"]])


def bios_key(console):
    """The key a console's BIOS group is unchecked under."""
    return f"bios:{console}"


def group_key(game, category):
    """The ``(key, category)`` pair unchecking ``category`` of an inventory ``game`` records."""
    if category == BIOS:
        return (bios_key(game["console"]), BIOS)
    return (game["key"], category)


def _unchecked_item(key, console, item, unchecked):
    category = _CATEGORY_OF[item["kind"]]
    if category == BIOS:
        return (bios_key(console), BIOS) in unchecked
    return (key, category) in unchecked


def inventory(built):
    """``(games, excluded)`` for the "What to Send" page.

    Each game is ``{key, title, console, size, groups}``, ``groups`` mapping
    each category the game has to ``{size, count, name, mtime}`` (``name`` and
    ``mtime`` of the group's first and newest file). ``excluded`` lists
    ``{title, console, reason}`` for the games that cannot be sent.
    """
    games = []
    for game in built.manifest["games"]:
        groups = {}
        for item in game["items"]:
            group = groups.setdefault(
                _CATEGORY_OF[item["kind"]], {"size": 0, "count": 0, "name": item["name"], "mtime": 0}
            )
            group["size"] += item["size"]
            group["count"] += 1
            group["mtime"] = max(group["mtime"], item["mtime"])
        if game.get("metadata"):
            groups[DETAILS] = {"size": 0, "count": 0, "name": "", "mtime": 0}
        games.append({
            "key": game_key(built, game),
            "title": game["title"],
            "console": game["console"],
            "size": sum(item["size"] for item in game["items"]),
            "groups": {category: groups[category] for category in CATEGORIES if category in groups},
        })
    excluded = [
        {"title": entry["rom"].get("name", ""), "console": entry["rom"].get("console", ""),
         "reason": entry["reason"]}
        for entry in built.excluded
    ]
    return games, excluded


def apply_selection(built, unchecked):
    """A copy of ``built`` without what ``unchecked`` names.

    ``unchecked`` holds ``(game key, category)`` pairs. Unchecking ``game``
    leaves the whole game out -- a game travels with its ROM, which is what
    the receiver places everything else next to -- and ``details`` drops the
    game's metadata. The BIOS of a game left out go with the next kept game of
    its console. Totals are counted again.
    """
    unchecked = set(unchecked)
    manifest = {"games": [], "total_size": 0, "file_count": 0}
    sources = {}
    #: BIOS items whose carrier was left out, by console, waiting for the next game.
    orphans = {}
    for game in built.manifest["games"]:
        key = game_key(built, game)
        if (key, GAME) in unchecked:
            orphans.setdefault(game["console"], []).extend(
                item for item in game["items"] if item["kind"] == KIND_BIOS
            )
            continue
        kept = copy.deepcopy(game)
        kept["items"] += copy.deepcopy(orphans.pop(game["console"], []))
        kept["items"] = [
            item for item in kept["items"] if not _unchecked_item(key, game["console"], item, unchecked)
        ]
        if (key, DETAILS) in unchecked:
            kept.pop("metadata", None)
        for item in kept["items"]:
            sources[item["id"]] = built.sources[item["id"]]
            manifest["total_size"] += item["size"]
            manifest["file_count"] += 1
        manifest["games"].append(kept)
    return BuiltManifest(manifest, sources, list(built.excluded))


def kept_roms(built, roms, unchecked):
    """The ``roms`` whose game ``unchecked`` leaves in, for the real send.

    ``built`` is the inventory made from ``roms``: its games follow ``roms``
    in order, less the excluded ones. Building the real manifest from these
    alone hashes nothing the user left out, and a game the inventory
    excluded stays out.
    """
    left_out = {id(entry["rom"]) for entry in built.excluded}
    included = [rom for rom in roms if id(rom) not in left_out]
    unchecked = set(unchecked)
    return [
        rom for rom, game in zip(included, built.manifest["games"])
        if (game_key(built, game), GAME) not in unchecked
    ]


def summarize(built):
    """``{titles, games, files, size}`` of what ``built`` would send."""
    manifest = built.manifest
    return {
        "titles": [game["title"] for game in manifest["games"]],
        "games": len(manifest["games"]),
        "files": manifest["file_count"],
        "size": manifest["total_size"],
    }
