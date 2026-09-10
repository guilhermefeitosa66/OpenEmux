"""A real `OpenEmuxWindow`, built over a throwaway home, for the UI tests.

The window and its six collaborators -- the sidebar, the page cache, the
import flow, the game session, the task banner, the navigation controller --
only exist together: each of them holds the window and calls back into it
(issue #237). Testing any of them against a stub window proves nothing about
the pairing, which is exactly where the mistakes are, so they are all tested
against the real thing.

Three things are held back, because a unit test must not do them: the gamepad
navigator thread, the startup rescan thread, and the network (the update check
is off in the throwaway config).
"""

import shutil
import tempfile
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from tests.gtk_display import HAVE_DISPLAY
from tests.isolated_home import IsolatedHome

if HAVE_DISPLAY:
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gdk, Gio, GLib, Gtk

    Adw.init()

    from openemux.core.playlist_manager import PlaylistManager
    from openemux.core.scanner import RomScanner
    from openemux.ui import window as window_module
    from openemux.ui.window import OpenEmuxWindow

    #: The real startup scan, captured before `WindowCase` patches it out.
    REAL_STARTUP_SCAN = OpenEmuxWindow._start_startup_scan

    class _Application(Adw.Application):
        """The one thing the window needs from its application.

        NON_UNIQUE so registering never tries to hand the run over to a copy
        of OpenEmux the developer happens to have open.
        """

        def __init__(self):
            super().__init__(
                application_id="io.github.openemux.WindowTests",
                flags=Gio.ApplicationFlags.NON_UNIQUE,
            )
            self.config_manager = None

else:  # pragma: no cover - the whole harness is skipped without a display
    REAL_STARTUP_SCAN = None


_APPLICATION = None


def shared_application():
    """The single registered application every window test builds on.

    Registering exports an object on the session bus under the application id,
    and doing that twice fails -- so the application is built once and each
    test points it at its own throwaway config.
    """
    global _APPLICATION
    if _APPLICATION is None:
        _APPLICATION = _Application()
        _APPLICATION.register()
    return _APPLICATION


#: Two consoles, three games: enough for an order to be wrong, a group to be
#: empty, and a selection to span more than one page.
DEFAULT_LIBRARY = {
    "SFC": ["Chrono Trigger.sfc", "Super Metroid.sfc"],
    "FC": ["Metroid.nes"],
}


class WindowCase(unittest.TestCase):
    """A real window over a throwaway home, with the threads held back."""

    library = DEFAULT_LIBRARY

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.home = IsolatedHome(self.tmp / "home")
        self.config = self.home.start()
        self.addCleanup(self.home.stop)

        for console, roms in self.library.items():
            for name in roms:
                self.home.add_rom(console, name)
        # The window reads playlists, not the directory tree: build them once
        # here so construction has a library to open on without a scan thread.
        playlists = PlaylistManager(
            self.config, RomScanner(self.config.get_roms_path())
        )
        summary = playlists.scan_and_rebuild_all_playlists()
        for console, roms in self.library.items():
            built = len(playlists.load_playlist(console))
            if built != len(roms):
                # The last line is not idle: a playlist reads back empty when
                # the scan found nothing *and* when the entries were dropped
                # for pointing at files that do not exist, and the two are
                # different bugs.
                rom_path = self.home.console_dir(console) / roms[0]
                raise AssertionError(
                    "the throwaway library came out wrong: "
                    f"{console} has {built} of {len(roms)} games. "
                    f"roms={self.config.get_roms_path()} "
                    f"playlists={self.config.get_playlists_dir()} "
                    f"on disk={sorted(p.name for p in self.home.console_dir(console).iterdir())} "
                    f"failed={summary['failed']} "
                    f"exists={rom_path.exists()}"
                )

        self.app = shared_application()
        self.app.config_manager = self.config

        self._release_style_providers()
        navigator_patch = mock.patch.object(
            window_module, "make_navigator", lambda **kwargs: mock.Mock()
        )
        navigator_patch.start()
        self.addCleanup(navigator_patch.stop)
        scan_patch = mock.patch.object(OpenEmuxWindow, "_start_startup_scan")
        scan_patch.start()
        self.addCleanup(scan_patch.stop)

        # Drained after the window is destroyed and before the throwaway home
        # goes away: a window leaves idle callbacks behind, and one that runs
        # later runs *inside another test*, against a directory that no longer
        # exists. Cleanups are LIFO, so this one is registered first and runs
        # after the destroy.
        self.addCleanup(self.pump)
        self.win = OpenEmuxWindow(self.app)
        self.addCleanup(self._close_window)

        self.toasts = []
        toast_patch = mock.patch.object(
            self.win.toast_overlay,
            "add_toast",
            lambda toast: self.toasts.append(toast.get_title()),
        )
        toast_patch.start()
        self.addCleanup(toast_patch.stop)


    def _close_window(self):
        """Close it the way a user does, then destroy what is left.

        `destroy()` alone does not emit ``close-request``, and neither does
        `close()` on a window nothing ever mapped -- but that signal is where
        the window lets go of `Adw.StyleManager`, which lives as long as the
        process. A handler left on it holds the closure, the closure holds the
        window, and the window holds its whole widget tree (issue #237). One
        window is nothing; a thousand is a gigabyte.
        """
        self.win.emit("close-request")
        self.win.destroy()

    def _release_style_providers(self):
        """Take the window's stylesheet off the display again afterwards.

        `load_css` adds a provider to the *display*, which outlives the window
        that added it: in the app that happens once, here it happens per test.
        A thousand providers is a thousand stylesheets matched against every
        widget of every later window -- hundreds of megabytes and a suite that
        slows down as it goes.
        """
        display = Gdk.Display.get_default()
        added = []
        real_add = Gtk.StyleContext.add_provider_for_display

        def _add(target, provider, priority):
            added.append((target, provider))
            return real_add(target, provider, priority)

        patcher = mock.patch.object(
            Gtk.StyleContext, "add_provider_for_display", _add
        )
        patcher.start()
        self.addCleanup(patcher.stop)

        def _release():
            for target, provider in added:
                Gtk.StyleContext.remove_provider_for_display(target, provider)

        self.addCleanup(_release)
        return display

    # -- helpers ----------------------------------------------------------
    @contextmanager
    def caught_dialog(self):
        """Catch the `Adw.AlertDialog` the window is about to show.

        The prompts are built and presented in one call, and none of them is
        parented anywhere a test could find it, so presenting is where they
        are intercepted -- which also keeps every dialog off the screen.
        """
        caught = []
        with mock.patch.object(
            Adw.AlertDialog, "present", lambda dialog, *args: caught.append(dialog)
        ):
            yield caught

    def rom(self, console="SFC", index=0):
        return self.win.playlist_manager.load_playlist(console)[index]

    def said(self, key, **kwargs):
        """The translated text of a message, for comparing against a toast."""
        return self.win.t(key, **kwargs)

    def pump(self):
        """Run whatever the window queued on the idle loop."""
        context = GLib.MainContext.default()
        while context.pending():
            context.iteration(False)

    def pump_until(self, predicate, timeout=5.0):
        """Run the idle loop until ``predicate`` holds, or give up.

        A fixed number of iterations is not enough: how many turns GTK needs
        to lay a page out and realize its cards depends on what else the
        machine is doing, and a whole-suite run is exactly when it needs more.
        """
        deadline = time.monotonic() + timeout
        context = GLib.MainContext.default()
        while time.monotonic() < deadline:
            if predicate():
                return True
            while context.pending():
                context.iteration(False)
            time.sleep(0.005)
        return predicate()

    def show(self):
        """Map the window, for the tests that need real focus and geometry.

        Focus only moves inside a window the display has actually mapped, so
        anything asserting where the focus went has to present first.
        """
        self.win.present()
        self.pump()

    def show_with_cards(self, console):
        """Map the window and wait for that console's page to realize a card.

        Returns the grid. A card exists only once GTK has laid the page out,
        and that is what every test about a card, a selection or the focus
        needs to be true before it starts.
        """
        self.win.sidebar.select(console)
        self.show()
        grid = self.win.pages.grid_for(console)
        entries = grid.entries()
        self.pump_until(
            lambda: grid.count() == len(entries)
            and bool(entries)
            and grid.card_for(entries[0]) is not None
        )
        return grid
