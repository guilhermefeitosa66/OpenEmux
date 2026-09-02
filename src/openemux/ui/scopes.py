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


def sidebar_row_ids(consoles, collection_slugs=(), has_favorites=False):
    """The rows the sidebar shows for this library, in order.

    With nothing in the library there are none. Every row here is a view
    *over* ROMs, so they would all lead to an empty page -- and leaving
    Favorites behind is what buried the onboarding page: the list selects
    its first row as soon as it takes focus, so a fresh install landed on
    "No favorites yet: right-click a game", about a game the user does not
    have (issue #224). The rows come back with the first import.

    ``has_favorites`` is the same argument on a smaller scale: the row only
    exists while something is in it. A place to go should exist because
    there is something there, and "Favorites" over an empty favorites list
    is a view of ROMs the user does not have in it, sitting above every
    console that does have games (issue #382). It defaults to *off* on
    purpose -- a caller that has not looked gets no row rather than a row
    that leads nowhere.

    A collection is not the same case: the *user* made it, and it shows
    while empty because they would otherwise have nowhere to drop games.
    Favorites is built in; nobody asked for it.
    """
    if not consoles:
        return []
    return [
        ALL_CONSOLES_ID,
        *([FAVORITES_ID] if has_favorites else []),
        # Collections sit between Favorites and the consoles: user groupings
        # above the hardware, mixing consoles like All does.
        *[collection_scope(slug) for slug in collection_slugs],
        *consoles,
    ]


def default_landing_view(has_favorites=False):
    """Where the library opens when it has no view to go back to.

    Favorites when there is at least one favorite, All otherwise. It used to
    be Favorites unconditionally, which is a row that may not even be in the
    sidebar any more (issue #382) -- and All is the more honest destination
    for a library nobody has told us anything about yet.
    """
    return FAVORITES_ID if has_favorites else ALL_CONSOLES_ID


def landing_view(visible_consoles, target_view, collection_slugs=(), has_favorites=False):
    """Which page a rebuilt library lands on.

    With nothing in it, the onboarding page -- that state's whole reason
    for existing, and unreachable until now (issue #224).

    A collection counts as somewhere to land. It never did: the set tested
    here held only the consoles and the two virtual views, so a rescan
    threw the user out of a collection and into Favorites, losing the view
    and the scroll position -- and the startup scan rescans on every single
    launch (issue #225).

    "Favorites" is only a destination while the row exists, so a target of
    ``FAVORITES_ID`` over an empty favorites list falls back like any other
    view that is gone (issue #382).
    """
    if not visible_consoles:
        return LIBRARY_EMPTY_ID
    fallback = default_landing_view(has_favorites)
    if is_collection_scope(target_view):
        # Only if it still exists: a collection deleted since is no more a
        # destination than a console that is gone.
        if collection_slug(target_view) in set(collection_slugs):
            return target_view
        return fallback
    known = set(visible_consoles) | {ALL_CONSOLES_ID}
    if has_favorites:
        known.add(FAVORITES_ID)
    if target_view in known:
        return target_view
    return fallback
