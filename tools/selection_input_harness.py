#!/usr/bin/env python3
"""Real-input regression harness for the grid.

Runs the production RomGrid inside a ScrolledWindow on a nested X server and
drives it with XTest-synthesized pointer/keyboard events -- the only way to
exercise the GTK gesture stack (claims, propagation, item activation) that
unit tests cannot reach. Nothing in ``tests/`` can: without a display,
constructing any GTK widget segfaults the interpreter, so the suite never
builds a RomGrid at all.

Covered here, and nowhere else:

* selection by pointer -- Ctrl-click, Shift-range, click-to-clear, launch;
* selection by keyboard -- Shift+arrow ranges and where they re-root;
* the rubber band, including that it selects exactly the cards it was drawn
  over rather than merely the right *number* of them, and that it still
  starts from the gap between two cards -- which belongs to the item wrapper
  now, and only reaches the band because the wrapper refuses the press;
* one card per ROM on screen, resolvable from the wrapper and from inside
  the card, with no card bound to two games at once;
* filtering -- what the grid reports as visible, and the selection of what is
  filtered out being dropped;
* focus memory across leaving and re-entering the grid;
* per-ROM refresh (artwork and cartridge frame) finding the right ROM;
* one context menu open at a time, whoever opened it (issue #275).

The last five exist because each *was* implemented against "one live widget
per ROM, forever, in a stable list" -- the invariant virtualization deleted
(issue #219). This is the net that migration had to keep green, and it is
what stands guard over the recycling now.

Usage:
    Xephyr :7 -screen 900x650 &
    DISPLAY=:7 GDK_BACKEND=x11 PYTHONPATH=src python3 tools/selection_input_harness.py
    HARNESS_CARDS=4 (default 12) picks the library size; 4 leaves empty page
    space so the click-on-empty and band-geometry checks run.

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
from gi.repository import Adw, Gdk, GLib, Gtk

from openemux.ui import context_menu
from openemux.ui.grid import RomGrid
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
        """Screen coords of card ``index`` (no WM in the nested X: win at 0,0).

        Only cards that are on screen have a widget at all, which is the whole
        point of the grid being virtualized; the scenario picks indices that
        are inside the first screenful.
        """
        item = self.grid.card_at(index)
        assert item is not None, f"card {index} is not on screen"
        ok, bounds = item.compute_bounds(self.window)
        assert ok
        return (bounds.origin.x + bounds.size.width / 2,
                bounds.origin.y + bounds.size.height / 2)

    def cards(self):
        """The cards that exist right now, in visual order."""
        return [c for c in (self.grid.card_at(i) for i in range(N_CARDS)) if c is not None]


def on_main(fn):
    """Run ``fn`` on the GTK main loop and hand its value back."""
    done = threading.Event()
    out = {}

    def run():
        try:
            out["v"] = fn()
        except Exception as exc:  # noqa: BLE001 - reported as a failed check
            out["v"] = f"EXC {exc!r}"
        done.set()
        return False

    GLib.idle_add(run)
    done.wait(5)
    return out.get("v")


def scenario(app, driver, results):
    def snap(label):
        # Counted on the model, not on the widgets: a selected game that has
        # scrolled off screen has no card, and still counts.
        selected = sum(1 for e in app.grid.entries() if e.selected)
        results.append((label, selected))
        print(f"CHECK {label}: selected={selected}", flush=True)

    def record(label, value):
        results.append((label, value))
        print(f"CHECK {label}: {value}", flush=True)

    time.sleep(1.5)  # let the window map and cards lay out
    centers = {}
    done = threading.Event()

    def collect():
        for i in (0, 1, 3, 5):
            if app.grid.card_at(i) is not None:
                centers[i] = app.card_center(i)
        collect.h = app.window.get_height()
        collect.w = app.window.get_width()
        # Where the cards end, not where the grid does: a GtkGridView is the
        # scroller's own child and fills the viewport, so its bounds say
        # nothing about how far down the last row reached.
        bottoms = []
        for card in app.cards():
            ok, b = card.compute_bounds(app.window)
            if ok:
                bottoms.append(b.origin.y + b.size.height)
        collect.grid_bottom = max(bottoms) if bottoms else None
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
    if empty_y is not None and empty_y < collect.h - 25:
        driver.click(collect.w / 2, empty_y)  # clear; the anchor goes stale
        def kb(keyval, shift=False, ctrl=False):
            state = 0
            if shift:
                state |= Gdk.ModifierType.SHIFT_MASK
            if ctrl:
                state |= Gdk.ModifierType.CONTROL_MASK
            return on_main(lambda: app.nav.handle_pane_key(keyval, state))

        on_main(lambda: app.grid.card_at(0).get_parent().grab_focus())
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

    # --- the four things a virtualized grid would have to re-earn --------
    # Each of these is implemented today against "one live widget per ROM,
    # forever, in a stable list" (issue #219). Recycling deletes that
    # invariant, and none of them had any coverage at all.

    # A. The page is the library, every card on screen shows a different
    # game, and a card resolves from either direction of the walk.
    def one_card_per_rom():
        paths = [e.rom["path"] for e in app.grid.entries()]
        if len(paths) != len(set(paths)) or len(paths) != len(ROMS):
            return "the model does not match the library"
        cards = app.cards()
        if not cards:
            return "no card is on screen"
        shown = [c.entry for c in cards]
        if len(shown) != len(set(id(e) for e in shown)):
            return "two cards are bound to the same game"
        if any(c.entry is None for c in cards):
            return "a card on screen is bound to nothing"
        item = cards[0]
        # Both directions of the walk: from the wrapper the pointer and the
        # keyboard land on, and from a widget inside the card. The title
        # label is always in the tree; the cover is swapped for a placeholder
        # when there is no artwork.
        from_wrapper = RomGrid.item_for_widget(item.get_parent())
        from_inside = RomGrid.item_for_widget(item.name_label)
        if from_wrapper is not item:
            return f"from the wrapper: {from_wrapper!r}"
        if from_inside is not item:
            return f"from inside: {from_inside!r}"
        return "ok"

    record("one-card-per-rom", on_main(one_card_per_rom))

    # B. Filtering. The window hands the grid the query; the grid has to
    # agree about what is visible and drop the selection of what is not.
    def filter_to(query):
        app.grid.set_filter(query)
        return len(app.grid.visible_entries())

    on_main(lambda: app.grid.select_all())
    record("filter-visible-count", on_main(lambda: filter_to("Game 00")))
    snap("filter-drops-hidden-selection")
    record("filter-restore-count", on_main(lambda: filter_to("Game")))

    # C. Focus memory. Restoring focus must land on the card that had it.
    def focus_round_trip():
        item = app.grid.card_at(1)
        entry = item.entry
        item.get_parent().grab_focus()
        app.scroll.grab_focus()          # focus leaves the grid
        app.grid.focus_restore()
        focused = app.window.get_focus()
        landed = RomGrid.item_for_widget(focused)
        # The *game*, not the widget: focus memory has to survive the card
        # being handed to another ROM, so what it restores is the entry.
        if landed is not None and landed.entry is entry:
            return "ok"
        return f"landed on {landed!r}"

    record("focus-restore", on_main(focus_round_trip))

    # D. Per-ROM refresh. "Find the widget for this ROM and change it" is
    # exactly what stops existing when items are recycled.
    def per_rom_refresh():
        rom = ROMS[2]
        found_art = app.grid.refresh_rom_artwork(rom)
        found_frame = app.grid.refresh_rom_frame(rom)
        stranger = {"name": "Nope", "path": "/tmp/fake/Nope.sfc", "console": "SFC"}
        if app.grid.refresh_rom_artwork(stranger):
            return "refreshed a ROM that is not on the page"
        # No cartridge frame in this harness's view mode, so refresh_rom_frame
        # reports nothing to do -- what matters is that the artwork refresh
        # found its ROM and a stranger found none.
        if not found_art:
            return f"artwork refresh did not find the ROM (frame={found_frame})"
        return "ok"

    record("per-rom-refresh", on_main(per_rom_refresh))

    # E. The band selects exactly what it was drawn over. A reimplementation
    # that works from indices rather than rectangles passes a count check and
    # fails this one.
    def band_verdict(bx0, by0, bx1, by1):
        """Did the band catch exactly the cards its rectangle covered?"""
        ok, gb = app.grid.compute_bounds(app.window)
        if not ok:
            return "grid has no bounds"
        left, right = sorted((bx0 - gb.origin.x, bx1 - gb.origin.x))
        top, bottom = sorted((by0 - gb.origin.y, by1 - gb.origin.y))
        wrong = []
        for item in app.cards():
            ok, b = item.compute_bounds(app.grid)
            if not ok:
                continue
            inside = (
                b.origin.x < right
                and left < b.origin.x + b.size.width
                and b.origin.y < bottom
                and top < b.origin.y + b.size.height
            )
            if inside != item.selected:
                wrong.append(item.rom["name"])
        return "ok" if not wrong else f"disagreed on {wrong}"

    def band_over(bx0, by0, bx1, by1, label):
        on_main(lambda: app.grid.clear_selection())
        driver.drag(bx0, by0, bx1, by1)
        record(label, on_main(lambda: band_verdict(bx0, by0, bx1, by1)))

    if empty_y is not None and empty_y < collect.h - 25:
        band_over(
            collect.w - 40, centers[0][1] + 120,
            centers[0][0] - 60, centers[0][1] - 60,
            "band-matches-geometry",
        )
    else:
        print("SKIP band-matches-geometry: page is full", flush=True)

    # E2. A band started in the gap *between* two cards. That gap belongs to
    # the item wrapper now, and only because the wrapper refuses the press
    # does it reach the band at all -- so this is the check that a page with
    # no empty space left still bands. It runs on every page size.
    gap_x = (centers[0][0] + centers[1][0]) / 2
    band_over(
        gap_x, centers[0][1] - 45,
        centers[1][0] + 12, centers[0][1] + 45,
        "band-from-card-gap",
    )

    # F. One context menu at a time, whoever opened it (issue #275).
    def two_menus():
        cards = app.cards()
        cards[0]._show_context_menu()
        first = cards[0]._context_popover
        cards[1]._show_context_menu()
        second = cards[1]._context_popover
        open_ones = sum(
            1 for item in cards if item._context_popover is not None
            and item._context_popover.get_visible()
        )
        context_menu.dismiss_context_popover()
        if first is None or second is None:
            return "a menu did not open"
        return open_ones

    record("one-menu-at-a-time", on_main(two_menus))

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
        "one-card-per-rom": "ok",
        "filter-visible-count": 1,
        "filter-drops-hidden-selection": 1,
        "filter-restore-count": N_CARDS,
        "focus-restore": "ok",
        "per-rom-refresh": "ok",
        "band-matches-geometry": "ok",
        "band-from-card-gap": "ok",
        "one-menu-at-a-time": 1,
    }
    launches = [d for k, d in EVENTS if k == "LAUNCH"]
    failures = []
    for label, count in results:
        want = expected[label]
        ok = want(count) if callable(want) else count == want
        print(f"{'PASS' if ok else 'FAIL'} {label}: {count}")
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
