"""The X11 layer the game window adopts RetroArch through.

Only the parts that can be answered without a real X server: the tri-state
"is the game still inside our window?" check, whose whole point is that
"unknown" and "no" mean opposite things (issue #267), and the pointer the
wrapper defines on the adopted window (issue #276).
"""

import unittest

from openemux.core import x11_embed
from openemux.core.x11_embed import RetroArchWindowEmbedder


class _FakeWindow:
    def __init__(self, parent_id=None, error=None):
        self._parent_id = parent_id
        self._error = error

    def query_tree(self):
        if self._error is not None:
            raise self._error
        return _FakeTree(self._parent_id)


class _FakeTree:
    def __init__(self, parent_id):
        self.parent = _FakeParent(parent_id)


class _FakeParent:
    def __init__(self, parent_id):
        self.id = parent_id


class _FakeDisplay:
    def __init__(self, window):
        self._window = window

    def create_resource_object(self, _kind, _xid):
        return self._window


class IsChildOfTests(unittest.TestCase):
    def _embedder(self, window):
        embedder = RetroArchWindowEmbedder()
        embedder._display = _FakeDisplay(window)
        # _dpy() only opens a real display when the cached one is None.
        embedder._dpy = lambda: embedder._display
        return embedder

    def test_still_ours(self):
        embedder = self._embedder(_FakeWindow(parent_id=4242))
        self.assertIs(embedder.is_child_of(0x1234, 4242), True)

    def test_reparented_away_is_a_definite_no(self):
        embedder = self._embedder(_FakeWindow(parent_id=1))
        self.assertIs(embedder.is_child_of(0x1234, 4242), False)

    def test_a_window_that_is_gone_is_unknown_not_drifted(self):
        # A BadWindow means the game's window was destroyed -- the game is
        # ending. Reading that as "it drifted" would re-parent and steal X
        # focus every second for the rest of the session.
        embedder = self._embedder(_FakeWindow(error=RuntimeError("BadWindow")))
        self.assertIsNone(embedder.is_child_of(0x1234, 4242))

    def test_no_display_is_unknown(self):
        embedder = RetroArchWindowEmbedder()
        embedder._dpy = lambda: None
        self.assertIsNone(embedder.is_child_of(0x1234, 4242))


class _FakeCursor:
    pass


class _FakeFont:
    def __init__(self):
        self.created = 0
        self.args = None

    def create_glyph_cursor(self, mask, source_char, mask_char, foreground, background):
        self.created += 1
        self.args = (mask, source_char, mask_char, foreground, background)
        return _FakeCursor()


class _FakeChild:
    """A window the embedder reparents, maps and defines a cursor on."""

    def __init__(self, xid):
        self.id = xid
        self.attributes = []
        self.mapped = False

    def change_attributes(self, **kwargs):
        self.attributes.append(kwargs)

    def reparent(self, _parent, _x, _y):
        pass

    def configure(self, **_kwargs):
        pass

    def map(self):
        self.mapped = True


class _FakeProperty:
    def __init__(self, value):
        self.value = value


class _FakeRoot:
    def __init__(self, active_xid):
        self._active_xid = active_xid

    def get_full_property(self, _atom, _type):
        if self._active_xid is None:
            return None
        return _FakeProperty([self._active_xid])


class _FakeScreen:
    def __init__(self, root):
        self.root = root


class _FakeFocus:
    def __init__(self, focus):
        self.focus = focus


class _FakeServer:
    """A display rich enough for the cursor and focus paths."""

    def __init__(self, active_xid=None, focused_xid=None, font=None):
        self.font = _FakeFont() if font is None else font
        self.windows = {}
        self.focus_calls = []
        self._root = _FakeRoot(active_xid)
        self._focused_xid = focused_xid

    def open_font(self, name):
        assert name == "cursor"
        return self.font

    def create_resource_object(self, _kind, xid):
        return self.windows.setdefault(xid, _FakeChild(xid))

    def screen(self):
        return _FakeScreen(self._root)

    def intern_atom(self, name):
        return name

    def get_input_focus(self):
        return _FakeFocus(self._focused_xid)

    def set_input_focus(self, window, _revert_to, _time):
        self.focus_calls.append(window.id)
        self._focused_xid = window.id

    def sync(self):
        pass


def _embedder_on(server):
    embedder = RetroArchWindowEmbedder()
    embedder._display = server
    embedder._dpy = lambda: embedder._display
    return embedder


class PointerCursorTests(unittest.TestCase):
    """The wrapper owns the game window's pointer (issue #276).

    RetroArch defines an invisible cursor on its own window and only redefines
    it on a menu toggle, a video re-init or a focus transition; X resolves the
    pointer from the innermost window, so nothing GTK sets on our side is ever
    seen over the game.
    """

    def test_the_cursor_is_defined_on_the_child_window(self):
        server = _FakeServer()
        self.assertTrue(_embedder_on(server).set_child_cursor(0x400))
        self.assertIn("cursor", server.windows[0x400].attributes[0])

    def test_the_left_ptr_glyph_and_its_mask_are_asked_for(self):
        server = _FakeServer()
        _embedder_on(server).set_child_cursor(0x400)
        mask, source_char, mask_char, _fore, _back = server.font.args
        # The cursor font is its own mask, and the mask glyph follows the
        # source glyph -- the standard X idiom.
        self.assertIs(mask, server.font)
        self.assertEqual(source_char, x11_embed.CURSOR_GLYPH)
        self.assertEqual(mask_char, x11_embed.CURSOR_GLYPH + 1)

    def test_the_cursor_resource_is_created_once_and_reused(self):
        server = _FakeServer()
        embedder = _embedder_on(server)
        embedder.set_child_cursor(0x400)
        embedder.set_child_cursor(0x400)
        embedder.set_child_cursor(0x401)
        self.assertEqual(server.font.created, 1)

    def test_a_cursor_that_cannot_be_created_is_not_fatal(self):
        class _BrokenFont:
            def create_glyph_cursor(self, *_args):
                raise RuntimeError("no such font")

        self.assertFalse(
            _embedder_on(_FakeServer(font=_BrokenFont())).set_child_cursor(0x400)
        )

    def test_no_display_means_no_cursor(self):
        embedder = RetroArchWindowEmbedder()
        embedder._dpy = lambda: None
        self.assertFalse(embedder.set_child_cursor(0x400))


class EmbedCursorTests(unittest.TestCase):
    """Every adoption defines the pointer, the re-adoptions included."""

    def test_embedding_defines_the_cursor(self):
        server = _FakeServer()
        self.assertTrue(_embedder_on(server).embed(0x400, 0x100, 0, 0, 640, 480))
        self.assertTrue(server.windows[0x400].mapped)
        self.assertEqual(len(server.windows[0x400].attributes), 1)

    def test_a_failed_reparent_still_reports_failure(self):
        class _Broken(_FakeServer):
            def create_resource_object(self, _kind, _xid):
                raise RuntimeError("BadWindow")

        self.assertFalse(_embedder_on(_Broken()).embed(0x400, 0x100, 0, 0, 640, 480))


class EnsureFocusCursorTests(unittest.TestCase):
    """Reclaiming focus is the unlock edge, and where the pointer is restored."""

    def test_reclaiming_focus_redefines_the_cursor(self):
        # Focus back on the toplevel with our window still active: what a
        # screen unlock leaves behind.
        server = _FakeServer(active_xid=0x100, focused_xid=0x100)
        self.assertTrue(_embedder_on(server).ensure_focus(0x400, 0x100))
        self.assertEqual(server.focus_calls, [0x400])
        self.assertEqual(len(server.windows[0x400].attributes), 1)

    def test_focus_already_on_the_game_costs_nothing(self):
        server = _FakeServer(active_xid=0x100, focused_xid=0x400)
        self.assertTrue(_embedder_on(server).ensure_focus(0x400, 0x100))
        self.assertEqual(server.focus_calls, [])
        self.assertEqual(server.windows, {})

    def test_another_application_is_active_so_focus_is_left_alone(self):
        server = _FakeServer(active_xid=0x999, focused_xid=0x999)
        self.assertFalse(_embedder_on(server).ensure_focus(0x400, 0x100))
        self.assertEqual(server.focus_calls, [])


if __name__ == "__main__":
    unittest.main()
