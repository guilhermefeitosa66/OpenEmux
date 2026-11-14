"""A real window with Big Picture on, for the couch layout's tests.

Builds on :class:`tests.window_harness.WindowCase`: the same throwaway home,
the same held-back threads. On top of it the mode is entered in ``setUp``
with the fullscreen calls patched out (the display the suite runs on has a
window manager, but a test must not depend on one), so every test starts on
the home page with ``self.shell`` in hand.
"""

from unittest import mock

from tests.gtk_display import HAVE_DISPLAY
from tests.window_harness import WindowCase

if HAVE_DISPLAY:
    from gi.repository import GLib, Gtk  # noqa: F401 - re-exported for the tests


class BigPictureCase(WindowCase):
    """``self.win`` with Big Picture on, ``self.shell`` its shell."""

    #: Whether ``setUp`` enters the mode; a test of the way in sets it off.
    enter_mode = True

    def setUp(self):
        super().setUp()
        self._fullscreen = mock.patch.object(self.win, "fullscreen")
        self._unfullscreen = mock.patch.object(self.win, "unfullscreen")
        self.fullscreen_calls = self._fullscreen.start()
        self.unfullscreen_calls = self._unfullscreen.start()
        self.addCleanup(self._fullscreen.stop)
        self.addCleanup(self._unfullscreen.stop)
        self.shell = None
        if self.enter_mode:
            self.enter()

    def enter(self):
        if not self.win.big_picture:
            self.win.toggle_big_picture()
        self.shell = self.win.big_picture_shell
        self.pump()
        return self.shell

    def leave(self):
        if self.win.big_picture:
            self.win.toggle_big_picture()
        self.pump()

    def press(self, action):
        """One pad action through the navigator, then the idle loop."""
        self.win.navigation.on_gamepad_action(action)
        self.pump()

    def focus_widget(self):
        return self.win.get_focus()

    def visible_page(self):
        return self.shell.visible_page()
