"""The order the consoles are in, and the user's say over it (issue #386).

The sidebar walked ``SYSTEM_IDS`` and kept the consoles that had ROMs, so the
order was the declaration order of ``SYSTEMS`` -- an implementation detail of a
Python list that nobody chose and nobody could change. The user's arrangement
is a list of console ids in ``ui.console_order``, and this is the one place
that turns it into an order.

One stored order feeds everything: the sidebar rows, the console groups on
"All", "Favorites" and the collections (#384), and the console cycling the
keyboard and the gamepad do -- they all read the same ``visible_consoles``.

Pure on purpose. It used to be a loop inside the window; the rules below are
worth stating once and testing, not re-deriving at three call sites.
"""

from openemux.core.systems import SYSTEM_IDS, resolve_system_id


def normalize_console_order(stored):
    """A stored order, cleaned: canonical ids, no duplicates, nothing unknown.

    A hand-edited or older config can hold anything. Everything this cannot
    make sense of is dropped rather than allowed to reorder the sidebar into
    something nobody asked for.
    """
    if not isinstance(stored, (list, tuple)):
        return []
    order = []
    seen = set()
    for value in stored:
        if not isinstance(value, str):
            continue
        console = resolve_system_id(value.strip())
        if console not in SYSTEM_IDS or console in seen:
            continue
        seen.add(console)
        order.append(console)
    return order


def apply_console_order(consoles, stored_order=()):
    """``consoles`` arranged the way the user asked.

    The ids the stored order mentions come first, in that order; the ones it
    does not come after them, in ``SYSTEMS`` order. So a console imported after
    the order was saved lands at the end instead of at a position nobody chose,
    and stays there until the user moves it.

    An id in the stored order with no games right now is simply not in
    ``consoles`` -- it keeps its *slot*, though, because the order is a list of
    ids and not a snapshot of the library: delete every Mega Drive ROM, import
    one again, and it comes back where it was.
    """
    present = [console for console in consoles or ()]
    remaining = set(present)
    ordered = []
    for console in normalize_console_order(stored_order):
        if console in remaining:
            ordered.append(console)
            remaining.discard(console)
    ordered.extend(
        console for console in SYSTEM_IDS if console in remaining
    )
    # Anything the systems list does not know -- it should not happen, but
    # losing a console the user has games for would be worse than an odd
    # position at the end.
    ordered.extend(
        console for console in present if console not in set(ordered)
    )
    return ordered


def merge_visible_into_order(stored, visible_order):
    """Fold a rearrangement of the *visible* consoles back into the stored one.

    The sidebar only shows the consoles that have games, so a drag rearranges a
    subset. The consoles the stored order knows but the library does not have
    right now keep their slots -- the list is the user's arrangement, not a
    snapshot of the library, so deleting every Mega Drive ROM and importing one
    again brings it back where it was.

    The visible ids fill the slots the stored order already gave them, in their
    new order; a console the stored order has never seen lands at the end.
    """
    stored = normalize_console_order(stored)
    queue = normalize_console_order(visible_order)
    if not stored:
        return queue
    visible = set(queue)
    merged = []
    for console in stored:
        if console not in visible:
            merged.append(console)
        elif queue:
            merged.append(queue.pop(0))
    merged.extend(queue)
    return merged


def move_console(order, console, delta):
    """``order`` with ``console`` moved ``delta`` places, clamped to the ends.

    The keyboard's ``Ctrl+Up``/``Ctrl+Down`` and the Preferences buttons; the
    drag uses :func:`place_console` instead, which knows where it was dropped.
    Returns a new list, and the same list when there is nowhere to go.
    """
    order = list(order or ())
    if console not in order:
        return order
    index = order.index(console)
    target = index + delta
    if not 0 <= target < len(order):
        return order
    order.pop(index)
    order.insert(target, console)
    return order


def place_console(order, console, before=None):
    """``order`` with ``console`` moved to sit just before ``before``.

    ``before=None`` puts it last. This is what a drop means: the row was let go
    above some other row, or past the last one.
    """
    order = list(order or ())
    if console not in order or console == before:
        return order
    order.remove(console)
    if before is None or before not in order:
        order.append(console)
    else:
        order.insert(order.index(before), console)
    return order
