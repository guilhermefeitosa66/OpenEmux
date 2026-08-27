#!/usr/bin/env python3
"""Does the library grid still build only a screenful of cards?

The grid used to be a ``Gtk.FlowBox`` with one live widget per ROM: opening
"All consoles" on a few thousand games built tens of thousands of widgets
before the first frame and then held a decoded texture per card for as long as
the page existed (issue #219). It is a ``Gtk.GridView`` now, which recycles a
handful of cards as the view scrolls.

That is not something ``tests/`` can check: without a display, constructing a
GTK widget segfaults the interpreter. So this probe puts the production grid on
a nested X server, twice -- once on a small library and once on one ten times
bigger -- and asserts the two build the *same* number of cards.

Usage:
    Xephyr :9 -screen 900x650 &
    DISPLAY=:9 GDK_BACKEND=x11 PYTHONPATH=src python3 tools/grid_virtualization_probe.py

Exit code 0 and ``RT-034 OK`` on stdout when the grid virtualizes.
"""

import os
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk

from openemux.ui.grid import RomGrid

SMALL = int(os.environ.get("PROBE_SMALL", "250"))
LARGE = int(os.environ.get("PROBE_LARGE", "2500"))


def roms(count):
    return [
        {
            "name": f"Game {index:05d}",
            "path": f"/tmp/fake/Game {index:05d}.sfc",
            "console": "SFC",
        }
        for index in range(count)
    ]


def build_grid(count):
    return RomGrid(
        "SFC",
        roms(count),
        lambda rom: None,                       # on_launch
        lambda rom: False,                      # toggle favorite
        lambda rom: None,                       # reveal
        lambda *a, **k: None,                   # choose cover
        lambda *a, **k: None,                   # remove cover
        lambda rom: False,                      # is_favorite
        lambda rom, kind=None: None,            # has_local_cover
        lambda key, **kw: key,                  # t
        "/tmp/fake-roms",
        ui_settings={"view_mode": "cover", "zoom": 1.0},
    )


class Probe(Adw.Application):
    def __init__(self):
        super().__init__(application_id="io.test.GridVirtualization")
        self.live = {}

    def do_activate(self):
        window = Gtk.ApplicationWindow(application=self)
        window.set_default_size(900, 650)
        self.scroll = Gtk.ScrolledWindow(vexpand=True)
        window.set_child(self.scroll)
        window.present()
        self.measure(SMALL, then=lambda: self.measure(LARGE, then=self.quit))

    def measure(self, count, then):
        """Show a library of ``count`` ROMs and count the cards it built."""
        grid = build_grid(count)
        self.scroll.set_child(grid)

        def read():
            self.live[count] = len(grid._bound)
            print(f"INFO {count} ROMs -> {self.live[count]} live cards", flush=True)
            then()
            return False

        # Two frames' grace: the first allocation settles the column count and
        # the second lays the cards out on it.
        GLib.timeout_add(1500, read)


def main():
    app = Probe()
    app.run([])
    small, large = app.live.get(SMALL), app.live.get(LARGE)
    if small is None or large is None:
        print("BLOCKED: the grid never laid out", flush=True)
        sys.exit(2)
    # The bound is the viewport, so it cannot follow the library. GTK keeps a
    # margin of spare rows around the visible ones, so the number is not the
    # screenful exactly -- what matters is that it does not grow with the page.
    assert large == small, f"live cards grew with the library: {small} -> {large}"
    assert large < SMALL, f"the whole {SMALL}-ROM page is live: {large} cards"
    print(f"RT-034 OK — {small} live cards at {SMALL} ROMs and at {LARGE}", flush=True)


if __name__ == "__main__":
    main()
