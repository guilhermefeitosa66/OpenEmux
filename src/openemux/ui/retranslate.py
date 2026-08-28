"""Text that has to be built again when the language changes.

Every translated label, tooltip and title outside the widgets the library
rebuilds wholesale registers a callback here, next to the widget it belongs
to. It used to be a list of `set_tooltip_text` calls inside
`_apply_language_change`, far from where each widget was built -- so every
widget added since had to be remembered there, and one of them was not: the
"New collection" button kept the old language until the app restarted.

The registry grows for the life of the window, which is fine for a control
built once and wrong for one the app rebuilds. The layout menu's zoom stepper
is rebuilt every time the menu is repopulated -- which is every single sidebar
click -- and left two closures behind each time, replayed in full on every
language change (issue #237). Registering with an ``owner`` ties the entry to
that widget's lifetime instead.
"""

import weakref


class RetranslateRegistry:
    """Callbacks that re-apply translated text, some of them owned."""

    def __init__(self):
        self._entries = []

    def add(self, apply, owner=None):
        """Apply translated text now, and again on every language change.

        With ``owner``, the registration lives only as long as that widget:
        once it is gone the entry is dropped at the next :meth:`apply_all`
        rather than accumulating one copy per rebuild.
        """
        apply()
        self._entries.append((weakref.ref(owner) if owner is not None else None, apply))

    def apply_all(self):
        """Re-apply every live entry, forgetting the ones whose owner is gone."""
        live = []
        for ref, apply in self._entries:
            if ref is not None and ref() is None:
                continue
            apply()
            live.append((ref, apply))
        self._entries = live

    def __len__(self):
        return len(self._entries)
