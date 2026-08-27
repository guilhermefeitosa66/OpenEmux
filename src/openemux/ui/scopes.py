"""The id space the sidebar, the page cache and the navigation share.

"Where the user is" is one string throughout the UI: a console id (`SFC`), one
of the two sentinels below, or a collection's `col:<slug>`. Keeping collections
in the same id space as the consoles is what lets one selection handler, one
page cache and the controller's console cycling treat them uniformly.

These lived in `ui/window.py`, which meant every module that needed the
vocabulary had to import the 3,800-line window -- `ui/rom_context.py` did it
from inside a method to dodge the cycle. They are their own module now
(issue #237); `ui/window.py` re-exports them, so
`from openemux.ui.window import FAVORITES_ID` keeps working.
"""

#: The "All" view: every console's ROMs in one grid.
ALL_CONSOLES_ID = "__all__"
#: The "Favorites" view.
FAVORITES_ID = "__favorites__"
#: The onboarding page a library with nothing in it lands on (issue #224).
LIBRARY_EMPTY_ID = "library-empty"
#: A collection's sidebar/scope id is this prefix plus its slug.
COLLECTION_ID_PREFIX = "col:"


def is_collection_scope(scope):
    return isinstance(scope, str) and scope.startswith(COLLECTION_ID_PREFIX)


def collection_slug(scope):
    return scope[len(COLLECTION_ID_PREFIX):] if is_collection_scope(scope) else None


def collection_scope(slug):
    return f"{COLLECTION_ID_PREFIX}{slug}"


def sidebar_row_ids(consoles, collection_slugs=()):
    """The rows the sidebar shows for this library, in order.

    With nothing in the library there are none. Every row here is a view
    *over* ROMs, so they would all lead to an empty page -- and leaving
    Favorites behind is what buried the onboarding page: the list selects
    its first row as soon as it takes focus, so a fresh install landed on
    "No favorites yet: right-click a game", about a game the user does not
    have (issue #224). The rows come back with the first import.
    """
    if not consoles:
        return []
    return [
        ALL_CONSOLES_ID,
        FAVORITES_ID,
        # Collections sit between Favorites and the consoles: user groupings
        # above the hardware, mixing consoles like All does.
        *[collection_scope(slug) for slug in collection_slugs],
        *consoles,
    ]


def landing_view(visible_consoles, target_view, collection_slugs=()):
    """Which page a rebuilt library lands on.

    With nothing in it, the onboarding page -- that state's whole reason
    for existing, and unreachable until now (issue #224).

    A collection counts as somewhere to land. It never did: the set tested
    here held only the consoles and the two virtual views, so a rescan
    threw the user out of a collection and into Favorites, losing the view
    and the scroll position -- and the startup scan rescans on every single
    launch (issue #225).
    """
    if not visible_consoles:
        return LIBRARY_EMPTY_ID
    if is_collection_scope(target_view):
        # Only if it still exists: a collection deleted since is no more a
        # destination than a console that is gone.
        if collection_slug(target_view) in set(collection_slugs):
            return target_view
        return FAVORITES_ID
    if target_view in set(visible_consoles) | {ALL_CONSOLES_ID, FAVORITES_ID}:
        return target_view
    return FAVORITES_ID
