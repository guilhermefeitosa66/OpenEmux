"""The selection model behind the ROM grid (issue #78).

Pure maths over indices of the *visible* items, in visual order. Mouse,
keyboard and gamepad all drive these same operations, so their semantics
cannot drift apart; the GTK side (``RomGrid``) is a thin adapter that maps
items to indices and paints the result.

File-manager vocabulary:

- ``select(i)``    - the selection becomes exactly ``{i}``.
- ``toggle(i)``    - Ctrl+click / Ctrl+Space: flips one item.
- ``extend(i)``    - Shift: the contiguous range anchor..i replaces the
                     selection.
- ``extend_additive(i)`` - Ctrl+Shift: the range is added to what was
                     selected before the Shift sequence started.
- ``select_all()`` / ``clear()``.

The *anchor* is where a range starts: the last item picked without Shift.
The *cursor* is where the user is; ``move_cursor`` follows plain movement
without touching the selection, ``set_anchor`` additionally re-roots ranges.
"""


class SelectionModel:
    def __init__(self, count=0):
        self.reset(count)

    def reset(self, count):
        """A new (or re-filtered) item list: everything is forgotten."""
        self.count = int(count)
        self.selected = set()
        self.anchor = None
        self.cursor = None
        # What extend_additive unions with: the selection as it stood before
        # the current Shift sequence began.
        self._base = set()

    # -- helpers -----------------------------------------------------------
    def _valid(self, index):
        return index is not None and 0 <= index < self.count

    def _range(self, index):
        start = self.anchor if self._valid(self.anchor) else index
        low, high = sorted((start, index))
        return set(range(low, high + 1))

    def _commit_base(self):
        self._base = set(self.selected)

    # -- operations ----------------------------------------------------------
    def select(self, index):
        if not self._valid(index):
            return
        self.selected = {index}
        self.anchor = self.cursor = index
        self._commit_base()

    def toggle(self, index):
        if not self._valid(index):
            return
        self.selected ^= {index}
        self.anchor = self.cursor = index
        self._commit_base()

    def extend(self, index):
        if not self._valid(index):
            return
        self.selected = self._range(index)
        self.cursor = index
        if not self._valid(self.anchor):
            self.anchor = index

    def extend_additive(self, index):
        if not self._valid(index):
            return
        self.selected = self._base | self._range(index)
        self.cursor = index
        if not self._valid(self.anchor):
            self.anchor = index

    def select_all(self):
        self.selected = set(range(self.count))
        self._commit_base()

    def clear(self):
        self.selected = set()
        self._commit_base()

    def move_cursor(self, index, keep_anchor=False):
        """Plain / Ctrl movement: the cursor travels, the selection stays.

        Without ``keep_anchor`` the anchor follows the cursor (a later Shift
        ranges from here); with it (Ctrl+arrows) the anchor stays put so
        Ctrl+Space toggling and a later Shift range keep their root.
        """
        if not self._valid(index):
            return
        self.cursor = index
        if not keep_anchor:
            self.anchor = index
            self._commit_base()

    def replace(self, indices):
        """Adopt a selection made outside the model (the rubber band)."""
        self.selected = {i for i in indices if self._valid(i)}
        self._commit_base()

    def all_selected(self):
        return self.count > 0 and len(self.selected) == self.count
