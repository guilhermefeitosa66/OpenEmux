#!/usr/bin/env python3
"""Real-input regression harness for the grid selection behaviors.

Runs the production RomGrid inside a ScrolledWindow on a nested X server and
drives it with XTest-synthesized pointer/keyboard events -- the only way to
exercise the GTK gesture stack (claims, propagation, FlowBox activation) that
unit tests cannot reach.

Usage:
    Xephyr :7 -screen 900x650 &
    DISPLAY=:7 GDK_BACKEND=x11 PYTHONPATH=src python3 tools/selection_input_harness.py
    HARNESS_CARDS=4 (default 12) picks the library size; 4 leaves empty page
    space so the click-on-empty checks run.

Exit code 0 when every check passes.
"""

import ctypes
import os
import sys
import threading
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, GLib, Gtk, Graphene

from openemux.ui.grid import RomGrid, RomItem
from openemux.ui.navigation import NavigationController

# ---- XTest driver ----------------------------------------------------------
xlib = ctypes.CDLL("libX11.so.6")
xtst = ctypes.CDLL("libXtst.so.6")
xlib.XOpenDisplay.restype = ctypes.c_void_p
xlib.XOpenDisplay.argtypes = [ctypes.c_char_p]
xlib.XFlush.argtypes = [ctypes.c_void_p]
xlib.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
xtst.XTestFakeMotionEvent.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_ulong]
xtst.XTestFakeButtonEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
xtst.XTestFakeKeyEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]

XK_Control_L = 0xFFE3
XK_Shift_L = 0xFFE1


class Driver:
    def __init__(self, display_name):
        self.dpy = xlib.XOpenDisplay(display_name.encode())
        assert self.dpy, "cannot open display"

    def move(self, x, y):
        xtst.XTestFakeMotionEvent(self.dpy, 0, int(x), int(y), 0)
        xlib.XFlush(self.dpy)
        time.sleep(0.05)

    def button(self, pressed, button=1):
        xtst.XTestFakeButtonEvent(self.dpy, button, 1 if pressed else 0, 0)
        xlib.XFlush(self.dpy)
        time.sleep(0.05)

    def key(self, keysym, pressed):
        code = xlib.XKeysymToKeycode(self.dpy, keysym)
        xtst.XTestFakeKeyEvent(self.dpy, code, 1 if pressed else 0, 0)
        xlib.XFlush(self.dpy)
        time.sleep(0.05)

    def click(self, x, y, mod=None):
        if mod:
            self.key(mod, True)
        self.move(x, y)
        self.button(True)
        self.button(False)
        if mod:
            self.key(mod, False)
        time.sleep(0.25)

    def drag(self, x1, y1, x2, y2):
        self.move(x1, y1)
        self.button(True)
        steps = 8
        for i in range(1, steps + 1):
            self.move(x1 + (x2 - x1) * i / steps, y1 + (y2 - y1) * i / steps)
        self.button(False)
        time.sleep(0.25)


# ---- Harness app -----------------------------------------------------------
EVENTS = []


def log_event(kind, detail):
    EVENTS.append((kind, detail))
    print(f"EVENT {kind}: {detail}", flush=True)


N_CARDS = int(os.environ.get("HARNESS_CARDS", "12"))
ROMS = [
    {"name": f"Game {i:02d}", "path": f"/tmp/fake/Game {i:02d}.sfc", "console": "SFC"}
    for i in range(N_CARDS)
]


class Harness(Adw.Application):
    def __init__(self):
        super().__init__(application_id="io.test.SelectionHarness")
        self.grid = None
        self.window = None
        self.scroll = None

    def do_activate(self):
        win = Gtk.ApplicationWindow(application=self)
        win.set_default_size(760, 560)
        self.window = win

        grid = RomGrid(
            "SFC",
            ROMS,
            lambda rom: log_event("LAUNCH", rom["name"]),          # on_launch
            lambda rom: False,                                       # toggle favorite
            lambda rom: None,                                        # reveal
            lambda *a, **k: None,                                    # choose cover
            lambda *a, **k: None,                                    # remove cover
            lambda rom: False,                                       # is_favorite
            lambda rom, kind=None: None,                             # has_local_cover
            lambda key, **kw: key,                                   # t
            "/tmp/fake-roms",
            ui_settings={"view_mode": "cover", "zoom": 1.0},
            on_selection_changed=lambda roms: log_event("SELECTED", len(roms)),
        )
        self.grid = grid

        scroll = Gtk.ScrolledWindow(vexpand=True)
        scroll.set_child(grid)
        self.scroll = scroll

        win.set_child(scroll)
        win.present()
        # The production keyboard routing, wired to this window: the
        # controller only needs the grid registry and scope attributes.
        win._grids = {"SFC": grid}
        win.current_console = "SFC"
        self.nav = NavigationController(win)

    def card_center(self, index):
        """Screen coords of card ``index`` (no WM in the nested X: win at 0,0)."""
        item = self.grid._items[index]
        ok, bounds = item.compute_bounds(self.window)
        assert ok
        return (bounds.origin.x + bounds.size.width / 2,
                bounds.origin.y + bounds.size.height / 2)


def scenario(app, driver, results):
    def snap(label):
        selected = sum(1 for i in app.grid._items if i.selected)
        results.append((label, selected))
        print(f"CHECK {label}: selected={selected}", flush=True)

    time.sleep(1.5)  # let the window map and cards lay out
    centers = {}
    done = threading.Event()

    def collect():
        for i in (0, 1, 3, 5):
            if i < len(app.grid._items):
                centers[i] = app.card_center(i)
        collect.h = app.window.get_height()
        collect.w = app.window.get_width()
        ok, gb = app.grid.compute_bounds(app.window)
        collect.grid_bottom = gb.origin.y + gb.size.height if ok else None
        done.set()
        return False
    GLib.idle_add(collect)
    done.wait(5)
    print(f"INFO centers={centers} win={collect.w}x{collect.h}", flush=True)

    # 1. Ctrl+click card 0: select, must not launch
    driver.click(*centers[0], mod=XK_Control_L)
    snap("ctrl-click-0")

    # 2. Shift+click card 3: range 0..3
    driver.click(*centers[3], mod=XK_Shift_L)
    snap("shift-click-3")

    # 3. Plain click on empty page space below the cards: must clear. Away
    # from the window edge (no WM: the CSD resize zone eats edge presses) and
    # skipped when the page has no visible empty space.
    empty_y = collect.grid_bottom + 25 if collect.grid_bottom else None
    if empty_y is not None and empty_y < collect.h - 25:
        driver.click(collect.w / 2, empty_y)
        snap("click-empty")
        driver.click(*centers[0], mod=XK_Control_L)  # reselect one
        driver.click(collect.w / 3, empty_y)
        snap("click-below")
    else:
        print("SKIP click-empty/click-below: page is full", flush=True)

    # 4. Rubber band from empty space over the first row
    x0, y0 = centers[0]
    x1, y1 = centers[1]
    driver.drag(collect.w - 40, y0 + 120, x0 - 60, y0 - 60)
    snap("band-drag")

    # 5. Plain click on a card: must launch (once), and root the anchor
    last = max(centers)
    driver.click(*centers[last])
    snap("plain-click-last")

    # 6. Shift+click card 1 right after: range from the plain-clicked card
    driver.click(*centers[1], mod=XK_Shift_L)
    snap("shift-after-plain")

    # --- keyboard: Shift+arrows range from the focused card ---------------
    def on_main(fn):
        done = threading.Event()
        out = {}
        def run():
            out["v"] = fn()
            done.set()
            return False
        GLib.idle_add(run)
        done.wait(5)
        return out.get("v")

    if empty_y is not None and empty_y < collect.h - 25:
        driver.click(collect.w / 2, empty_y)  # clear; the anchor goes stale
        def kb(keyval, shift=False, ctrl=False):
            state = 0
            if shift:
                state |= Gdk.ModifierType.SHIFT_MASK
            if ctrl:
                state |= Gdk.ModifierType.CONTROL_MASK
            return on_main(lambda: app.nav.handle_pane_key(keyval, state))

        on_main(lambda: app.grid._items[0].get_parent().grab_focus())
        time.sleep(0.2)
        kb(Gdk.KEY_Right, shift=True)   # roots at the focused card 0
        snap("kb-shift-right-1")        # {0,1}
        kb(Gdk.KEY_Right, shift=True)   # same sequence, anchor holds
        snap("kb-shift-right-2")        # {0,1,2}
        kb(Gdk.KEY_Left)                # plain move: selection untouched
        snap("kb-plain-left")           # still {0,1,2}
        kb(Gdk.KEY_Left, shift=True)    # new sequence: re-roots at card 1
        snap("kb-shift-left-reroot")    # {0,1}
    else:
        print("SKIP keyboard checks: page is full", flush=True)

    time.sleep(0.5)
    GLib.idle_add(app.quit)


def main():
    app = Harness()
    driver = Driver(os.environ["DISPLAY"])
    results = []
    thread = threading.Thread(target=scenario, args=(app, driver, results), daemon=True)
    GLib.timeout_add(200, lambda: (thread.start(), False)[1])
    app.run([])

    print("\n--- RESULTS ---", flush=True)
    expected = {
        "ctrl-click-0": 1,
        "shift-click-3": 4,
        "click-empty": 0,
        "click-below": 0,
        "band-drag": lambda n: n >= 2,
        "plain-click-last": lambda n: True,
        "shift-after-plain": lambda n: n >= 2,
        "kb-shift-right-1": 2,
        "kb-shift-right-2": 3,
        "kb-plain-left": 3,
        "kb-shift-left-reroot": 2,
    }
    launches = [d for k, d in EVENTS if k == "LAUNCH"]
    failures = []
    for label, count in results:
        want = expected[label]
        ok = want(count) if callable(want) else count == want
        print(f"{'PASS' if ok else 'FAIL'} {label}: selected={count}")
        if not ok:
            failures.append(label)
    if "Game 00" in launches:
        print("FAIL ctrl/shift click must not launch (launched Game 00)")
        failures.append("no-launch-on-modifier")
    if not launches:
        print("FAIL plain click should have launched something")
        failures.append("plain-click-launch")
    if len(launches) != len(set(launches)) or len([l for l in launches if l == launches[0]]) > 1:
        print("FAIL a plain click launched more than once:", launches)
        failures.append("double-launch")
    print("LAUNCHES:", launches)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
