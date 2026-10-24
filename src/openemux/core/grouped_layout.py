"""Where each part of a grouped page lands on screen (issue #511).

The arithmetic behind ``openemux.ui.grouped_scroll``: a grouped page is a
column of headers and grids scrolled as one, and each grid is handed only the
part of it the viewport covers. Kept apart from the widget so it can be
checked without a display.
"""


def slice_for(top, height, scroll, viewport):
    """Where a child laid out at ``top`` lands in the viewport.

    ``top`` and ``height`` are the child's place in the content, ``scroll`` is
    how far the page is scrolled and ``viewport`` how tall it is. Returns
    ``(y, visible_height, inner_scroll)`` -- where to allocate the child, how
    much of it to allocate, and how far into the child that slice starts -- or
    None when no part of the child is on screen.
    """
    y = top - scroll
    start = max(y, 0)
    end = min(y + height, viewport)
    if end <= start:
        return None
    return start, end - start, max(0, scroll - top)


def scroll_to_show(scroll, viewport, top, height):
    """The scroll that brings ``[top, top + height)`` into the viewport.

    The least movement that does it, like GTK's own focus scrolling: nothing
    when it is already in view, its top at the top of the viewport when it is
    above, its bottom at the bottom when it is below. Something taller than the
    viewport is shown from its top.
    """
    if top < scroll or height >= viewport:
        return top
    if top + height > scroll + viewport:
        return top + height - viewport
    return scroll
