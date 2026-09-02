"""Splitting a mixed page into one group per console (issue #384).

"All", "Favorites" and the collections used to be one flat grid sorted A-Z, so
a Mega Drive game sat between two SNES ones and the eye had nothing to hold on
to. They are grouped by console instead, each group under its own header, in
**the order the consoles have in the sidebar** -- so when the user rearranges
that order (#386) the groups follow for free.

Pure logic, deliberately: the window passes its ``visible_consoles`` and gets
back a list of groups, and nothing here knows what a grid is.
"""

#: The group a ROM with no console id falls into. It should not happen -- the
#: playlists always carry one -- but dropping such a ROM would make it
#: invisible on the page instead of merely oddly placed.
UNKNOWN_CONSOLE = ""


def group_roms_by_console(roms, console_order=()):
    """``[(console_id, [rom, ...]), ...]`` for ``roms``.

    Groups follow ``console_order``; a console that order does not mention
    comes after the ones it does, in the order the ROMs first mention it, so a
    freshly imported console lands at the end rather than at a position nobody
    chose.

    A console with no games on this page produces no group at all: a header
    over nothing is worse than no header. The order *within* a group is the
    order ``roms`` arrived in, which is the page's sort order already applied
    -- grouping never moves a game past another game of the same console.
    """
    grouped = {}
    first_seen = []
    for rom in roms or ():
        console = _console_of(rom)
        if console not in grouped:
            grouped[console] = []
            first_seen.append(console)
        grouped[console].append(rom)

    known = [console for console in (console_order or ()) if console in grouped]
    rest = [console for console in first_seen if console not in set(known)]
    return [(console, grouped[console]) for console in known + rest]


def _console_of(rom):
    return (rom or {}).get("console") or UNKNOWN_CONSOLE
