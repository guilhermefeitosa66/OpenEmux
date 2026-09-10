"""The X11 layer the game window adopts RetroArch through.

No real X server is needed for any of it: every method goes through one
display object, so a fake one covers the whole file -- the tri-state "is the
game still inside our window?" check, whose point is that "unknown" and "no"
mean opposite things (issue #267), the pointer the wrapper defines on the
adopted window (issue #276), the hotkey grab and the focus reclaim (issue
#236), which window a launch decides is *its* RetroArch (issue #245), and the
detach that has to happen before our own window dies (X destroys children with
their parent, and RetroArch aborts on losing its window).

Every method here is best-effort by design and must never raise to the UI, so
each one is also driven with a display that fails.
"""

import unittest
from unittest import mock

from openemux.core import x11_embed
from openemux.core.input_actions import RETROARCH_KEY_NAMES
from openemux.core.x11_embed import RetroArchWindowEmbedder, _keysym_candidates
from tests.platform_marks import linux_only


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


class _FakeClient:
    """A toplevel in _NET_CLIENT_LIST, with the two properties the search reads."""

    def __init__(self, xid, pid=None, wm_class=None):
        self.id = xid
        self._pid = pid
        self._wm_class = wm_class

    def get_full_property(self, atom, _type):
        if atom == "_NET_WM_PID" and self._pid is not None:
            return _FakeProperty([self._pid])
        return None

    def get_wm_class(self):
        return self._wm_class


class _FakeClientList:
    """A display whose _NET_CLIENT_LIST is exactly the windows handed to it."""

    def __init__(self, clients):
        self._clients = {client.id: client for client in clients}
        self._order = [client.id for client in clients]

    def screen(self):
        return _FakeScreen(self)

    @property
    def root(self):
        return self

    def get_full_property(self, atom, _type):
        if atom == "_NET_CLIENT_LIST":
            return _FakeProperty(list(self._order))
        return None

    def intern_atom(self, name):
        return name

    def create_resource_object(self, _kind, xid):
        client = self._clients.get(xid)
        if client is None:
            raise RuntimeError(f"window {xid} is gone")
        return client


def _embedder_over(clients):
    embedder = RetroArchWindowEmbedder()
    embedder._display = _FakeClientList(clients)
    embedder._dpy = lambda: embedder._display
    return embedder


class FindGameWindowTests(unittest.TestCase):
    """Which toplevel a launch decides is *its* RetroArch.

    Getting this wrong does not look like a bug in the search: the wrapper
    adopts somebody else's window, or none, and the user sees a game that
    opened outside its frame.
    """

    def test_the_pid_match_wins(self):
        embedder = _embedder_over([
            _FakeClient(0x10, pid=111, wm_class=("retroarch", "RetroArch")),
            _FakeClient(0x20, pid=222, wm_class=("retroarch", "RetroArch")),
        ])
        self.assertEqual(embedder.find_game_window(222), 0x20)

    def test_the_pid_match_wins_even_over_an_earlier_class_match(self):
        # The class candidate is collected while scanning, so a later PID hit
        # still has to beat it.
        embedder = _embedder_over([
            _FakeClient(0x10, pid=999, wm_class=("retroarch", "RetroArch")),
            _FakeClient(0x20, pid=222, wm_class=("retroarch", "RetroArch")),
        ])
        self.assertEqual(embedder.find_game_window(222), 0x20)

    def test_a_forked_launcher_is_found_by_its_class_instead(self):
        # AppImage wrappers and flatpak-spawn fork, so the Popen PID is not
        # the window's process and _NET_WM_PID never matches.
        embedder = _embedder_over([
            _FakeClient(0x10, pid=1, wm_class=("firefox", "Firefox")),
            _FakeClient(0x20, pid=2, wm_class=("retroarch", "RetroArch")),
        ])
        self.assertEqual(embedder.find_game_window(4242), 0x20)

    def test_a_retroarch_that_predates_the_launch_is_never_adopted(self):
        # Someone's own RetroArch, already open: adopting it would rip their
        # session into our frame (issue #227 is the same concern for the port).
        embedder = _embedder_over([
            _FakeClient(0x10, pid=1, wm_class=("retroarch", "RetroArch")),
        ])
        embedder.snapshot_existing()
        self.assertIsNone(embedder.find_game_window(4242))

    def test_the_snapshot_does_not_block_a_pid_match(self):
        # A pre-existing window that *is* our process is still ours.
        embedder = _embedder_over([
            _FakeClient(0x10, pid=777, wm_class=("retroarch", "RetroArch")),
        ])
        embedder.snapshot_existing()
        self.assertEqual(embedder.find_game_window(777), 0x10)

    def test_the_first_new_retroarch_window_is_the_one_taken(self):
        embedder = _embedder_over([
            _FakeClient(0x10, pid=1, wm_class=("retroarch", "RetroArch")),
            _FakeClient(0x20, pid=2, wm_class=("retroarch", "RetroArch")),
        ])
        self.assertEqual(embedder.find_game_window(None), 0x10)

    def test_nothing_matching_is_none_rather_than_a_wrong_window(self):
        embedder = _embedder_over([
            _FakeClient(0x10, pid=1, wm_class=("firefox", "Firefox")),
        ])
        self.assertIsNone(embedder.find_game_window(4242))

    def test_a_window_with_no_wm_class_is_not_a_candidate(self):
        embedder = _embedder_over([_FakeClient(0x10, pid=1, wm_class=None)])
        self.assertIsNone(embedder.find_game_window(4242))

    def test_the_class_match_ignores_case(self):
        embedder = _embedder_over([_FakeClient(0x10, pid=1, wm_class=("RETROARCH", ""))])
        self.assertEqual(embedder.find_game_window(4242), 0x10)

    def test_a_window_that_vanishes_mid_scan_does_not_end_the_search(self):
        # The list is a snapshot; a window can close between reading it and
        # inspecting it, and that must not cost us the real match.
        clients = [
            _FakeClient(0x10, pid=1, wm_class=("retroarch", "RetroArch")),
            _FakeClient(0x20, pid=222, wm_class=("retroarch", "RetroArch")),
        ]
        embedder = _embedder_over(clients)
        embedder._display._clients.pop(0x10)  # gone, still listed
        self.assertEqual(embedder.find_game_window(222), 0x20)

    def test_no_display_finds_nothing(self):
        embedder = RetroArchWindowEmbedder()
        embedder._dpy = lambda: None
        self.assertIsNone(embedder.find_game_window(222))
        embedder.snapshot_existing()  # and does not raise


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


class KeysymResolutionTests(unittest.TestCase):
    """Bindings are stored in RetroArch's vocabulary, not X's (issue #236)."""

    def test_a_retroarch_token_maps_to_its_x_spelling_first(self):
        self.assertEqual(_keysym_candidates("enter")[0], "Return")
        self.assertEqual(_keysym_candidates("pageup")[0], "Prior")
        self.assertEqual(_keysym_candidates("del")[0], "Delete")
        self.assertEqual(_keysym_candidates("kp_plus")[0], "KP_Add")
        self.assertEqual(_keysym_candidates("num1")[0], "1")
        self.assertEqual(_keysym_candidates("rshift")[0], "Shift_R")

    def test_a_plain_letter_is_left_alone(self):
        self.assertEqual(_keysym_candidates("f"), ["f", "F"])

    def test_function_keys_still_get_the_capitalized_retry(self):
        self.assertIn("F11", _keysym_candidates("f11"))

    def test_an_empty_binding_offers_nothing(self):
        self.assertEqual(_keysym_candidates(""), [])
        self.assertEqual(_keysym_candidates(None), [])

    @linux_only("the X keysym tables, from python-xlib")
    def test_every_retroarch_key_name_can_be_resolved(self):
        # The guarantee that matters: whatever an input profile stores, the
        # wrapper can grab it. Uses the real Xlib tables, no server needed.
        from Xlib import X, XK

        unresolvable = [
            token
            for token in sorted(set(RETROARCH_KEY_NAMES.values()))
            if not any(
                XK.string_to_keysym(candidate) != X.NoSymbol
                for candidate in _keysym_candidates(token)
            )
        ]
        self.assertEqual(unresolvable, [])


class FocusReclaimDecisionTests(unittest.TestCase):
    """When the reclaim tick may take X focus back for the game (#236)."""

    CHILD = 0x200
    TOPLEVEL = 0x100

    def _should(self, active_xid, focus_xid):
        return RetroArchWindowEmbedder().should_reclaim_focus(
            active_xid, focus_xid, self.CHILD, self.TOPLEVEL
        )

    def test_our_window_is_the_active_one(self):
        self.assertTrue(self._should(self.TOPLEVEL, self.TOPLEVEL))

    def test_another_application_is_active_so_hands_off(self):
        self.assertFalse(self._should(0x999, self.TOPLEVEL))

    def test_no_active_window_property_falls_back_to_the_input_focus(self):
        # Not every (XWayland) window manager keeps _NET_ACTIVE_WINDOW
        # current, and reading a missing property as "not us" meant the
        # reclaim loop never fired at all -- RetroArch went input-dead after
        # any click on the wrapper chrome.
        self.assertTrue(self._should(None, self.TOPLEVEL))
        self.assertTrue(self._should(None, self.CHILD))

    def test_the_fallback_still_refuses_to_steal_from_someone_else(self):
        self.assertFalse(self._should(None, 0x999))

    def test_the_missing_property_is_logged_once(self):
        embedder = RetroArchWindowEmbedder()
        with self.assertLogs("openemux.core.x11_embed", level="WARNING") as logs:
            embedder.should_reclaim_focus(None, self.TOPLEVEL, self.CHILD, self.TOPLEVEL)
            embedder.should_reclaim_focus(None, self.TOPLEVEL, self.CHILD, self.TOPLEVEL)
        # A 200 ms tick would otherwise fill the log with the same line.
        self.assertEqual(len(logs.output), 1)
        self.assertIn("_NET_ACTIVE_WINDOW", logs.output[0])


class EnsureFocusWithoutActiveWindowTests(unittest.TestCase):
    def test_focus_is_reclaimed_when_the_property_is_missing(self):
        server = _FakeServer(active_xid=None, focused_xid=0x100)
        embedder = _embedder_on(server)

        self.assertTrue(embedder.ensure_focus(0x200, 0x100))
        self.assertEqual(server.focus_calls, [0x200])

    def test_focus_elsewhere_and_no_property_leaves_it_alone(self):
        server = _FakeServer(active_xid=None, focused_xid=0x999)
        embedder = _embedder_on(server)

        self.assertFalse(embedder.ensure_focus(0x200, 0x100))
        self.assertEqual(server.focus_calls, [])


class _BrokenDisplay:
    """A display that fails whatever it is asked. Every method must survive one."""

    def __init__(self, error=None):
        self.error = error or RuntimeError("BadWindow")
        self.closed = 0

    def _fail(self, *_args, **_kwargs):
        raise self.error

    create_resource_object = _fail
    screen = _fail
    intern_atom = _fail
    get_input_focus = _fail
    set_input_focus = _fail
    open_font = _fail
    pending_events = _fail
    sync = _fail

    def close(self):
        self.closed += 1
        raise self.error


def _embedder_with_no_display():
    embedder = RetroArchWindowEmbedder()
    embedder._dpy = lambda: None
    return embedder


class OpeningAndClosingTheDisplayTests(unittest.TestCase):
    """The one place `Xlib.display` is reached for (issue #364)."""

    def test_a_machine_without_python_xlib_offers_no_display(self):
        embedder = RetroArchWindowEmbedder()
        with mock.patch.object(x11_embed, "XLIB_AVAILABLE", False):
            self.assertFalse(embedder.available)
            self.assertIsNone(embedder._dpy())

    def test_the_first_call_opens_one_and_the_rest_reuse_it(self):
        opened = []

        class _Module:
            @staticmethod
            def Display():
                opened.append(1)
                return "the display"

        embedder = RetroArchWindowEmbedder()
        with mock.patch.object(x11_embed, "XLIB_AVAILABLE", True):
            with _xlib_display(_Module):
                self.assertEqual(embedder._dpy(), "the display")
                self.assertEqual(embedder._dpy(), "the display")
        self.assertEqual(len(opened), 1)

    def test_a_display_that_will_not_open_is_reported_not_raised(self):
        class _Module:
            @staticmethod
            def Display():
                raise RuntimeError("no DISPLAY")

        embedder = RetroArchWindowEmbedder()
        with mock.patch.object(x11_embed, "XLIB_AVAILABLE", True):
            with _xlib_display(_Module):
                with self.assertLogs("openemux.core.x11_embed", level="WARNING"):
                    self.assertIsNone(embedder._dpy())

    def test_closing_drops_the_display_and_the_cursor_with_it(self):
        # The cursor belongs to the display, so it dies with it.
        server = _FakeServer()
        embedder = _embedder_on(server)
        embedder._display.close = lambda: None
        embedder._cursor = _FakeCursor()
        embedder.close()
        self.assertIsNone(embedder._display)
        self.assertIsNone(embedder._cursor)

    def test_a_display_that_will_not_close_is_dropped_anyway(self):
        embedder = RetroArchWindowEmbedder()
        embedder._display = _BrokenDisplay()
        embedder.close()
        self.assertIsNone(embedder._display)

    def test_closing_with_no_display_open_is_harmless(self):
        RetroArchWindowEmbedder().close()


def _xlib_display(module):
    """Put ``module`` where ``from Xlib import display`` will find it."""
    import Xlib

    return mock.patch.object(Xlib, "display", module, create=True)


class ListingTheToplevelsTests(unittest.TestCase):
    def test_no_display_lists_nothing(self):
        self.assertEqual(_embedder_with_no_display()._client_xids(), [])

    def test_a_root_window_that_cannot_be_read_lists_nothing(self):
        embedder = RetroArchWindowEmbedder()
        embedder._display = _BrokenDisplay()
        embedder._dpy = lambda: embedder._display
        with self.assertLogs("openemux.core.x11_embed", level="WARNING"):
            self.assertEqual(embedder._client_xids(), [])

    def test_a_desktop_with_no_client_list_lists_nothing(self):
        embedder = _embedder_over([])
        self.assertEqual(embedder._client_xids(), [])

    def test_a_window_with_no_pid_property_reports_none(self):
        embedder = _embedder_over([_FakeClient(1)])
        window = embedder._dpy().create_resource_object("window", 1)
        self.assertIsNone(embedder._window_pid(window))

    def test_no_display_snapshots_nothing(self):
        embedder = _embedder_with_no_display()
        embedder.snapshot_existing()
        self.assertEqual(embedder._preexisting_xids, set())

    def test_a_window_that_vanishes_mid_snapshot_is_skipped(self):
        # The window can go between the listing and the inspection.
        embedder = _embedder_over([_FakeClient(1, wm_class=("retroarch", "RetroArch"))])
        embedder._display._clients.clear()
        embedder.snapshot_existing()
        self.assertEqual(embedder._preexisting_xids, set())


class ThePointerCursorFallbackTests(unittest.TestCase):
    def test_a_display_with_no_cursor_font_defines_no_pointer(self):
        server = _FakeServer()
        server.open_font = lambda _name: None
        embedder = _embedder_on(server)
        self.assertIsNone(embedder._pointer_cursor(server))

    def test_no_display_defines_no_pointer(self):
        self.assertFalse(_embedder_with_no_display().set_child_cursor(0x200))

    def test_a_window_that_refuses_the_cursor_is_reported_not_raised(self):
        server = _FakeServer()
        embedder = _embedder_on(server)
        child = server.create_resource_object("window", 0x200)
        child.change_attributes = _raise
        with self.assertLogs("openemux.core.x11_embed", level="WARNING"):
            self.assertFalse(embedder.set_child_cursor(0x200))


def _raise(*_args, **_kwargs):
    raise RuntimeError("BadWindow")


class ReparentingTests(unittest.TestCase):
    def test_a_window_is_reparented_mapped_and_given_a_pointer(self):
        server = _FakeServer()
        embedder = _embedder_on(server)
        self.assertTrue(embedder.embed(0x200, 0x100, 10, 20, 300, 200))
        child = server.windows[0x200]
        self.assertTrue(child.mapped)
        self.assertTrue(child.attributes)

    def test_no_display_reparents_nothing(self):
        self.assertFalse(_embedder_with_no_display().embed(0x200, 0x100, 0, 0, 1, 1))

    def test_a_reparent_that_fails_is_reported_not_raised(self):
        server = _FakeServer()
        embedder = _embedder_on(server)
        server.create_resource_object("window", 0x200).reparent = _raise
        with self.assertLogs("openemux.core.x11_embed", level="WARNING"):
            self.assertFalse(embedder.embed(0x200, 0x100, 0, 0, 1, 1))

    def test_moving_the_game_asks_x_to_configure_it(self):
        server = _FakeServer()
        embedder = _embedder_on(server)
        configured = []
        server.create_resource_object("window", 0x200).configure = (
            lambda **kwargs: configured.append(kwargs)
        )
        self.assertTrue(embedder.move_resize(0x200, 10, 20, 300, 200))
        self.assertEqual(
            configured[-1], {"x": 10, "y": 20, "width": 300, "height": 200}
        )

    def test_a_degenerate_rect_is_clamped_to_one_pixel(self):
        # X refuses a zero-sized window outright.
        server = _FakeServer()
        embedder = _embedder_on(server)
        configured = []
        server.create_resource_object("window", 0x200).configure = (
            lambda **kwargs: configured.append(kwargs)
        )
        embedder.move_resize(0x200, 0, 0, 0, -5)
        self.assertEqual(configured[-1]["width"], 1)
        self.assertEqual(configured[-1]["height"], 1)

    def test_no_display_moves_nothing(self):
        self.assertFalse(
            _embedder_with_no_display().move_resize(0x200, 0, 0, 1, 1)
        )

    def test_a_move_that_fails_is_reported_not_raised(self):
        server = _FakeServer()
        embedder = _embedder_on(server)
        server.create_resource_object("window", 0x200).configure = _raise
        with self.assertLogs("openemux.core.x11_embed", level="WARNING"):
            self.assertFalse(embedder.move_resize(0x200, 0, 0, 1, 1))


class HandingOverKeyboardFocusTests(unittest.TestCase):
    def test_focus_goes_to_the_game_so_retroarch_sees_key_input(self):
        server = _FakeServer()
        embedder = _embedder_on(server)
        self.assertTrue(embedder.focus(0x200))
        self.assertEqual(server.focus_calls, [0x200])

    def test_no_display_focuses_nothing(self):
        self.assertFalse(_embedder_with_no_display().focus(0x200))

    def test_a_focus_that_fails_is_reported_not_raised(self):
        server = _FakeServer()
        embedder = _embedder_on(server)
        server.set_input_focus = _raise
        with self.assertLogs("openemux.core.x11_embed", level="WARNING"):
            self.assertFalse(embedder.focus(0x200))

    def test_no_display_reclaims_nothing(self):
        self.assertFalse(_embedder_with_no_display().ensure_focus(0x200, 0x100))

    def test_a_tick_that_finds_focus_already_on_the_game_costs_nothing(self):
        server = _FakeServer(active_xid=0x100, focused_xid=0x200)
        embedder = _embedder_on(server)
        self.assertTrue(embedder.ensure_focus(0x200, 0x100))
        self.assertEqual(server.focus_calls, [])

    def test_a_reclaim_that_fails_is_reported_not_raised(self):
        server = _FakeServer(active_xid=0x100, focused_xid=0x100)
        embedder = _embedder_on(server)
        server.set_input_focus = _raise
        with self.assertLogs("openemux.core.x11_embed", level="WARNING"):
            self.assertFalse(embedder.ensure_focus(0x200, 0x100))

    def test_a_focus_answered_as_a_bare_xid_is_read_the_same_way(self):
        # python-xlib answers PointerRoot/None as an int rather than a window.
        server = _FakeServer(active_xid=0x100, focused_xid=0x200)
        server.get_input_focus = lambda: _FakeFocus(0x200)
        embedder = _embedder_on(server)
        self.assertTrue(embedder.ensure_focus(0x200, 0x100))


@linux_only("the X keysym tables and X.LockMask, from python-xlib")
class GrabbingTheWrapperHotkeyTests(unittest.TestCase):
    """The wrapper's only way to see a key: focus sits on the game (#236)."""

    def _server(self):
        server = _FakeServer()
        server.keysym_to_keycode = lambda keysym: 42 if keysym else 0
        return server

    def test_the_key_is_grabbed_under_every_lock_combination(self):
        # Caps or Num lock must not disable the hotkey.
        server = self._server()
        embedder = _embedder_on(server)
        grabs = []
        toplevel = server.create_resource_object("window", 0x100)
        toplevel.grab_key = lambda *args: grabs.append(args)
        self.assertEqual(embedder.grab_key(0x100, "f"), 42)
        self.assertEqual(len(grabs), 4)

    def test_a_binding_x_cannot_name_falls_back_rather_than_giving_up(self):
        server = self._server()
        server.keysym_to_keycode = lambda keysym: 43 if keysym else 0
        embedder = _embedder_on(server)
        server.create_resource_object("window", 0x100).grab_key = lambda *_a: None
        with self.assertLogs("openemux.core.x11_embed", level="WARNING"):
            self.assertEqual(embedder.grab_key(0x100, "nonsense-key", "f"), 43)

    def test_a_binding_with_no_fallback_grabs_nothing(self):
        server = self._server()
        embedder = _embedder_on(server)
        with self.assertLogs("openemux.core.x11_embed", level="WARNING"):
            self.assertIsNone(embedder.grab_key(0x100, "nonsense-key"))

    def test_no_display_grabs_nothing(self):
        self.assertIsNone(_embedder_with_no_display().grab_key(0x100, "f"))

    def test_a_grab_that_fails_is_reported_not_raised(self):
        server = self._server()
        embedder = _embedder_on(server)
        server.create_resource_object("window", 0x100).grab_key = _raise
        with self.assertLogs("openemux.core.x11_embed", level="WARNING"):
            self.assertIsNone(embedder.grab_key(0x100, "f"))

    def test_a_keycode_is_resolved_through_the_retroarch_spelling(self):
        asked = []

        class _Dpy:
            @staticmethod
            def keysym_to_keycode(keysym):
                asked.append(keysym)
                return 7

        self.assertEqual(RetroArchWindowEmbedder._keycode_for(_Dpy, "enter"), 7)
        self.assertTrue(asked)

    def test_a_keysym_x_maps_to_no_keycode_is_skipped(self):
        class _Dpy:
            @staticmethod
            def keysym_to_keycode(_keysym):
                return 0

        self.assertEqual(RetroArchWindowEmbedder._keycode_for(_Dpy, "f"), 0)

    def test_a_name_x_does_not_know_at_all_resolves_to_nothing(self):
        class _Dpy:
            @staticmethod
            def keysym_to_keycode(_keysym):  # pragma: no cover - never reached
                raise AssertionError("should not be asked")

        self.assertEqual(
            RetroArchWindowEmbedder._keycode_for(_Dpy, "not-a-key-name"), 0
        )


@linux_only("X.KeyPress, from python-xlib")
class ReadingTheGrabbedKeysTests(unittest.TestCase):
    class _Event:
        def __init__(self, event_type, detail):
            self.type = event_type
            self.detail = detail

    def _server(self, events):
        server = _FakeServer()
        queue = list(events)
        server.pending_events = lambda: len(queue)
        server.next_event = lambda: queue.pop(0)
        return server

    def test_a_pressed_grabbed_key_is_reported_once(self):
        from Xlib import X

        server = self._server([self._Event(X.KeyPress, 42)])
        self.assertEqual(_embedder_on(server).pressed_grabbed_keycodes(), [42])

    def test_events_that_are_not_key_presses_are_ignored(self):
        from Xlib import X

        server = self._server([self._Event(X.KeyRelease, 42)])
        self.assertEqual(_embedder_on(server).pressed_grabbed_keycodes(), [])

    def test_no_display_reports_no_keys(self):
        self.assertEqual(
            _embedder_with_no_display().pressed_grabbed_keycodes(), []
        )

    def test_an_event_queue_that_fails_is_reported_not_raised(self):
        server = _FakeServer()
        server.pending_events = _raise
        with self.assertLogs("openemux.core.x11_embed", level="WARNING"):
            self.assertEqual(_embedder_on(server).pressed_grabbed_keycodes(), [])


class DetachingBeforeOurWindowDiesTests(unittest.TestCase):
    """X destroys children with their parent; RetroArch aborts on that."""

    def test_the_game_is_unmapped_and_handed_back_to_the_root(self):
        server = _FakeServer()
        embedder = _embedder_on(server)
        child = server.create_resource_object("window", 0x200)
        moves = []
        child.unmap = lambda: moves.append("unmap")
        child.reparent = lambda *_a: moves.append("reparent")
        self.assertTrue(embedder.release(0x200))
        # Unmapped first, so the freed toplevel does not flash WM-decorated
        # while QUIT is still in flight.
        self.assertEqual(moves, ["unmap", "reparent"])

    def test_no_display_detaches_nothing(self):
        self.assertFalse(_embedder_with_no_display().release(0x200))

    def test_a_detach_that_fails_is_reported_not_raised(self):
        server = _FakeServer()
        embedder = _embedder_on(server)
        server.create_resource_object("window", 0x200).unmap = _raise
        with self.assertLogs("openemux.core.x11_embed", level="WARNING"):
            self.assertFalse(embedder.release(0x200))


if __name__ == "__main__":
    unittest.main()
