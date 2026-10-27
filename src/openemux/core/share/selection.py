"""What the user picked to send, on top of a built manifest (#589).

The "What to Send" page lists each game's items in six groups -- the game
itself, its battery save, its save states, the cover, the cartridge label and
the library details -- and the user unchecks whole groups. A game and its
groups are keyed by the game's main file (the ROM, or its cue or m3u), which
stays the same when the manifest is built again for the real send, unlike the
positional item ids.

Pure: no GTK, no files read.
"""

import copy

from openemux.core.share.manifest import BuiltManifest
from openemux.core.share.protocol import (
    KIND_BATTERY_SAVE,
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
DETAILS = "details"
#: The groups in the order the page lists them.
CATEGORIES = (GAME, BATTERY, STATES, COVER, LABEL, DETAILS)
_CATEGORY_OF = {
    KIND_ROM: GAME,
    KIND_BATTERY_SAVE: BATTERY,
    KIND_STATE: STATES,
    KIND_COVER: COVER,
    KIND_LABEL: LABEL,
}


def roms_for_console(playlists, console):
    """Every game of ``console``, as the scanner's rom dicts."""
    return list(playlists.load_playlist(console))


def game_key(built, game):
    """The main file a manifest game was built from."""
    return str(built.sources[game["items"][0]["id"]])


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
    game's metadata. Totals are counted again.
    """
    unchecked = set(unchecked)
    manifest = {"games": [], "total_size": 0, "file_count": 0}
    sources = {}
    for game in built.manifest["games"]:
        key = game_key(built, game)
        if (key, GAME) in unchecked:
            continue
        kept = copy.deepcopy(game)
        kept["items"] = [
            item for item in kept["items"] if (key, _CATEGORY_OF[item["kind"]]) not in unchecked
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
