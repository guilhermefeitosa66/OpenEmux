"""Finding RetroArch's X11 window and titling it (issue #469).

No real X server is needed: every method goes through one display object, so
a fake one covers the file -- which window a launch decides is *its*
RetroArch (issue #245), the deferred ``Xlib.display`` (issue #364), and the
title the window is given. Every method is best-effort and must never raise,
so each is also driven with a display that fails.
"""

import unittest
from unittest import mock

from openemux.core import x11_windows
from openemux.core.x11_windows import RetroArchWindows


class _FakeProperty:
    def __init__(self, value):
        self.value = value




class _FakeScreen:
    def __init__(self, root):
        self.root = root



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
    embedder = RetroArchWindows()
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
        embedder = RetroArchWindows()
        embedder._dpy = lambda: None
        self.assertIsNone(embedder.find_game_window(222))
        embedder.snapshot_existing()  # and does not raise


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
    embedder = RetroArchWindows()
    embedder._dpy = lambda: None
    return embedder


class OpeningAndClosingTheDisplayTests(unittest.TestCase):
    """The one place `Xlib.display` is reached for (issue #364)."""

    def test_a_machine_without_python_xlib_offers_no_display(self):
        embedder = RetroArchWindows()
        with mock.patch.object(x11_windows, "XLIB_AVAILABLE", False):
            self.assertIsNone(embedder._dpy())

    def test_the_first_call_opens_one_and_the_rest_reuse_it(self):
        opened = []

        class _Module:
            @staticmethod
            def Display():
                opened.append(1)
                return "the display"

        embedder = RetroArchWindows()
        with mock.patch.object(x11_windows, "XLIB_AVAILABLE", True):
            with _xlib_display(_Module):
                self.assertEqual(embedder._dpy(), "the display")
                self.assertEqual(embedder._dpy(), "the display")
        self.assertEqual(len(opened), 1)

    def test_a_display_that_will_not_open_is_reported_not_raised(self):
        class _Module:
            @staticmethod
            def Display():
                raise RuntimeError("no DISPLAY")

        embedder = RetroArchWindows()
        with mock.patch.object(x11_windows, "XLIB_AVAILABLE", True):
            with _xlib_display(_Module):
                with self.assertLogs("openemux.core.x11_windows", level="WARNING"):
                    self.assertIsNone(embedder._dpy())

    def test_closing_drops_the_display(self):
        embedder = RetroArchWindows()
        embedder._display = mock.Mock()
        embedder.close()
        self.assertIsNone(embedder._display)

    def test_a_display_that_will_not_close_is_dropped_anyway(self):
        embedder = RetroArchWindows()
        embedder._display = _BrokenDisplay()
        embedder.close()
        self.assertIsNone(embedder._display)

    def test_closing_with_no_display_open_is_harmless(self):
        RetroArchWindows().close()


def _xlib_display(module):
    """Put ``module`` where ``from Xlib import display`` will find it."""
    import Xlib

    return mock.patch.object(Xlib, "display", module, create=True)


class ListingTheToplevelsTests(unittest.TestCase):
    def test_no_display_lists_nothing(self):
        self.assertEqual(_embedder_with_no_display()._client_xids(), [])

    def test_a_root_window_that_cannot_be_read_lists_nothing(self):
        embedder = RetroArchWindows()
        embedder._display = _BrokenDisplay()
        embedder._dpy = lambda: embedder._display
        with self.assertLogs("openemux.core.x11_windows", level="WARNING"):
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


@unittest.skipUnless(x11_windows.XLIB_AVAILABLE, "python-xlib is not installed")
class WindowTitleTests(unittest.TestCase):
    """Reading and writing RetroArch's title (issue #469)."""

    def _embedder(self, window=None, display=True):
        embedder = RetroArchWindows()
        dpy = None
        if display:
            dpy = mock.Mock()
            dpy.intern_atom.side_effect = lambda name: name
            dpy.create_resource_object.return_value = window or mock.Mock()
        embedder._dpy = lambda: dpy
        return embedder, dpy

    def test_reads_the_utf8_title(self):
        window = mock.Mock()
        window.get_full_property.return_value = mock.Mock(value="Asterix — Snes9x".encode())
        embedder, _ = self._embedder(window)
        self.assertEqual(embedder.window_title(7), "Asterix — Snes9x")
        window.get_full_property.assert_called_once_with("_NET_WM_NAME", "UTF8_STRING")

    def test_a_missing_title_or_a_failing_display_reads_as_none(self):
        window = mock.Mock()
        window.get_full_property.return_value = None
        self.assertIsNone(self._embedder(window)[0].window_title(7))
        window.get_full_property.side_effect = RuntimeError("BadWindow")
        self.assertIsNone(self._embedder(window)[0].window_title(7))
        self.assertIsNone(self._embedder(display=False)[0].window_title(7))

    def test_writes_both_the_ewmh_and_the_legacy_name(self):
        window = mock.Mock()
        embedder, dpy = self._embedder(window)
        self.assertTrue(embedder.set_window_title(7, "Asterix — Snes9x"))
        calls = window.change_property.call_args_list
        self.assertEqual(calls[0], mock.call("_NET_WM_NAME", "UTF8_STRING", 8,
                                             "Asterix — Snes9x".encode()))
        self.assertEqual(calls[1], mock.call(x11_windows.Xatom.WM_NAME, x11_windows.Xatom.STRING, 8,
                                             "Asterix ? Snes9x".encode("latin-1")))
        dpy.flush.assert_called_once()

    def test_a_failed_write_is_reported_not_raised(self):
        window = mock.Mock()
        window.change_property.side_effect = RuntimeError("BadWindow")
        self.assertFalse(self._embedder(window)[0].set_window_title(7, "T"))
        self.assertFalse(self._embedder(display=False)[0].set_window_title(7, "T"))


if __name__ == "__main__":
    unittest.main()
