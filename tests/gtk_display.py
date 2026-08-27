"""Whether this process can construct GTK widgets at all.

A few tests need real GTK objects rather than stubs -- an ``isinstance``
check against ``Gtk.Popover`` is only worth making against a real popover.
Constructing one with no display does not raise: GTK **segfaults**, taking the
whole run down mid-suite with no failing test to point at. That is how CI ran
red for weeks (issue #242).

So: import GTK, ask whether a display opened, and let a module that needs
widgets skip itself when one did not. CI runs the suite under ``xvfb-run``, so
there the answer is yes and nothing is skipped.
"""

import unittest


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


HAVE_DISPLAY = display_available()

#: Decorator for a TestCase whose widgets cannot be built without a display.
needs_display = unittest.skipUnless(
    HAVE_DISPLAY,
    "no display: constructing GTK widgets here segfaults rather than failing",
)
