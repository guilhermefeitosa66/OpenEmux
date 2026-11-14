"""The filter chips of the Big Picture games page (issue 957).

The Android gamepad layout puts four chips over a console's games --
Favorites, Has save state, Missing artwork, Never played -- each with how
many games it would leave, and any number of them on at once narrows the
list to the games that have every fact. This module knows the facts and
counts them; the grid applies ``matches`` as one more predicate next to the
search text.

The facts are gathered once per page, not per game: a whole console's
states are found with one directory listing per console
(``save_states.stems_with_states``) rather than one per game.

Pure and widget-free: one test file, the repo's core-module convention.
"""

from pathlib import Path

from openemux.core.save_states import stems_with_states

FAVORITES = "favorites"
HAS_STATE = "has_state"
MISSING_ARTWORK = "missing_artwork"
NEVER_PLAYED = "never_played"

#: The chips, in the order the page shows them (Android's).
FACETS = (FAVORITES, HAS_STATE, MISSING_ARTWORK, NEVER_PLAYED)


class RomFacts:
    """What the chips need to know about each game of a page.

    ``favorites``: the favorite paths. ``states_dir_for(console)``: the
    console's states directory. ``has_artwork(rom)``: whether the game has
    the art the page shows. ``last_played(path)``: epoch seconds, 0 when
    never played. The states are listed lazily, once per console.
    """

    def __init__(self, favorites, states_dir_for, has_artwork, last_played):
        self.favorites = frozenset(str(path) for path in favorites or ())
        self._states_dir_for = states_dir_for
        self._has_artwork = has_artwork
        self._last_played = last_played
        self._stems = {}

    def _stems_for(self, console):
        if console not in self._stems:
            directory = self._states_dir_for(console)
            self._stems[console] = stems_with_states(directory) if directory else set()
        return self._stems[console]

    def has(self, rom, facet):
        """Whether ``rom`` has ``facet``; an unknown facet is never had."""
        path = str(rom.get("path", ""))
        if facet == FAVORITES:
            return path in self.favorites
        if facet == HAS_STATE:
            return Path(path).stem in self._stems_for(rom.get("console", ""))
        if facet == MISSING_ARTWORK:
            return not self._has_artwork(rom)
        if facet == NEVER_PLAYED:
            return not self._last_played(path)
        return False


def normalize(active):
    """The chips that are on, as a frozenset of known facets."""
    return frozenset(facet for facet in active or () if facet in FACETS)


def matches(rom, active, facts):
    """Whether ``rom`` has every facet in ``active`` (no chip on: every game)."""
    return all(facts.has(rom, facet) for facet in normalize(active))


def facet_counts(roms, facts):
    """``{facet: how many of roms have it}``, for every chip."""
    counts = dict.fromkeys(FACETS, 0)
    for rom in roms:
        for facet in FACETS:
            if facts.has(rom, facet):
                counts[facet] += 1
    return counts


def toggle(active, facet):
    """``active`` with ``facet`` flipped; an unknown facet changes nothing."""
    active = normalize(active)
    if facet not in FACETS:
        return active
    return active - {facet} if facet in active else active | {facet}


__all__ = [
    "FACETS",
    "FAVORITES",
    "HAS_STATE",
    "MISSING_ARTWORK",
    "NEVER_PLAYED",
    "RomFacts",
    "facet_counts",
    "matches",
    "normalize",
    "toggle",
]
