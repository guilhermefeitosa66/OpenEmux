"""Whether this process can construct GTK widgets at all -- and whether it should.

A few tests need real GTK objects rather than stubs -- an ``isinstance``
check against ``Gtk.Popover`` is only worth making against a real popover.
Constructing one with no display does not raise: GTK **segfaults**, taking the
whole run down mid-suite with no failing test to point at. That is how CI ran
red for weeks (issue #242).

So: import GTK, ask whether a display opened, and let a module that needs
widgets skip itself when one did not. CI runs the suite under ``xvfb-run``, so
there the answer is yes and nothing is skipped.

Having a display is not the same as being allowed to use it. On a developer's
desktop session the display *is* their screen, and every widget test flashes a
window across it and steals focus for the length of the run (issue #528). So a
run that looks like it is sitting on a real session -- Wayland, an X11 session
type, a desktop name -- does not even open GTK: the widget tests skip with a
reason that says what to run instead. ``make test`` and ``make coverage`` go
through ``scripts/run_tests.py``, which puts the run on a private Xvfb display
and marks it with ``OPENEMUX_TESTS_PRIVATE_DISPLAY=1``; the devbox marks its own
Xvnc the same way. ``OPENEMUX_TESTS_ON_DESKTOP=1`` is the way to watch anyway.

GitHub's runners set none of the session variables, so CI is not refused. If a
runner ever does, the widget tests skip there and the 100% coverage floor turns
the run red -- loudly, not silently.
"""

import os
import sys
import unittest

#: Set to 1 to run the widget tests on the desktop you are sitting at.
OPT_IN = "OPENEMUX_TESTS_ON_DESKTOP"
#: Set to 1 by whoever put the run on a display nobody is looking at.
PRIVATE_DISPLAY = "OPENEMUX_TESTS_PRIVATE_DISPLAY"

NO_DISPLAY_REASON = (
    "no display: constructing GTK widgets here segfaults rather than failing"
)
DESKTOP_REASON = (
    "would draw on your desktop: run `make test` (private Xvfb display) "
    f"or set {OPT_IN}=1"
)
DESKTOP_NOTE = (
    "tests/gtk_display.py: this run is on your desktop session, so the tests "
    "that build GTK widgets are skipped instead of opening windows on it. "
    f"`make test` runs them on a private Xvfb display; {OPT_IN}=1 runs them "
    "here anyway.\n"
)


def on_developer_desktop(env=None, platform=None):
    """True when a widget built now would land on somebody's real screen.

    Linux only: Windows and macOS have no Xvfb to send the run to instead, and
    their behaviour is left as it was.
    """
    env = os.environ if env is None else env
    platform = sys.platform if platform is None else platform
    if not platform.startswith("linux"):
        return False
    if env.get(OPT_IN) == "1" or env.get(PRIVATE_DISPLAY) == "1":
        return False
    return bool(
        env.get("WAYLAND_DISPLAY")
        or env.get("XDG_SESSION_TYPE") in ("x11", "wayland")
        or env.get("XDG_CURRENT_DESKTOP")
    )


def display_available():
    """True when GDK actually opened a display.

    ``Gtk.init_check()`` is not the question to ask: it comes back True with no
    DISPLAY set at all, and only ``Gdk.Display.get_default()`` says whether
    anything was really opened. Building a widget against the None it returns
    is the segfault.
    """
    try:
        import gi

        gi.require_version("Gtk", "4.0")
        gi.require_version("Gdk", "4.0")
        from gi.repository import Gdk, Gtk

        Gtk.init_check()
        return Gdk.Display.get_default() is not None
    except Exception:
        return False


def probe(env=None, platform=None, available=display_available):
    """``(may build widgets, why not)``.

    A refused desktop never reaches ``available``: initialising GTK is what
    opens the connection to the developer's display in the first place.
    """
    if on_developer_desktop(env, platform):
        return False, DESKTOP_REASON
    if not available():
        return False, NO_DISPLAY_REASON
    return True, ""


def announce(reason, stream=None):
    """Say once, up front, why a bare run on a desktop skips so much."""
    if reason == DESKTOP_REASON:
        (sys.stderr if stream is None else stream).write(DESKTOP_NOTE)


HAVE_DISPLAY, SKIP_REASON = probe()
announce(SKIP_REASON)

#: Decorator for a TestCase whose widgets cannot be built without a display.
needs_display = unittest.skipUnless(HAVE_DISPLAY, SKIP_REASON)
