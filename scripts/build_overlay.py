#!/usr/bin/env python3
"""Render the in-game control bar: RetroArch overlay pages and their PNGs.

The bar is drawn by RetroArch itself, as an input overlay, so the game no
longer has to be captured into a GTK window to carry its controls. This
script turns the design (dock "A" on the design canvas) into what RetroArch
reads: one PNG per button, rendered from the same SVG paths, and
``openemux-bar.cfg`` with one overlay page per combination of the toggles
(pause, mute, fast-forward, slow motion, turbo) and shown/hidden: 64 pages.

Overlays have no state of their own, so a toggle is a page swap: the pause
button sends ``pause_toggle|overlay_next`` with a ``next_target`` naming the
page that shows the other icon. The state is only what the bar was told: a
toggle flipped from the keyboard or the menu leaves its icon behind. Hiding the bar is a jump to a page holding
only the small "show" button, one per state, so showing it again comes back
to the state it left.

Geometry is authored in pixels of a 960x720 (4:3) reference and normalized
at the end, and the overlay runs with ``input_overlay_auto_scale``. 4:3 on
purpose: narrower than any landscape window, so auto-scaling always fits the
overlay to the window's full *height* -- the bar sits on the bottom edge at
any shape, and its height is always the same fraction of the screen as the
margin the ``margin`` shader keeps clear (STRIP / H). The bar's background is
a flat strip drawn far wider than the overlay, so it spans the whole window
whatever is left and right of the 4:3 box.

Hiding the bar frees that strip for the game: the hide and show buttons also
send ``shader_next``, and the launcher points RetroArch's shader directory
at a folder holding exactly two presets, with and without the margin pass.

Output is committed (``src/openemux/data/overlay``): building it needs
GdkPixbuf's SVG loader, which the app does not. Run it again after changing
anything here:

    /usr/bin/python3 scripts/build_overlay.py
"""
import itertools
from pathlib import Path

import gi

gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "src" / "openemux" / "data" / "overlay"
W, H = 960.0, 720.0
#: The bottom margin kept for the bar, in reference pixels. Must agree with
#: ``MARGIN`` in the margin shaders (STRIP / H).
STRIP = 60.0
CY = H - STRIP / 2
SCALE = 2

TILE_BG = "#383838"
ICON = {
    "close": '<path d="M12 3v8"/><path d="M6.3 6.8a8 8 0 1 0 11.4 0"/>',
    "menu": '<path d="M4 7h16M4 12h16M4 17h16"/>',
    "pause": '<path d="M9 5v14M15 5v14" stroke-width="2.6"/>',
    "play": '<path d="M7 5l12 7-12 7z" fill="currentColor" stroke-width="1.5"/>',
    "reset": '<path d="M4 12a8 8 0 1 0 2.4-5.7"/><path d="M4 3.5V8h4.5"/>',
    "ff": '<path d="M3.5 6.5l8 5.5-8 5.5zM12.5 6.5l8 5.5-8 5.5z" fill="currentColor" stroke-width="1.5"/>',
    # A lightning bolt: turbo, the button that fires by itself.
    "turbo": '<path d="M13 2.5L5 13.5h6l-1 8 8-11h-6z"/>',
    # A speedometer with its needle low: slow motion.
    "slow": '<path d="M4.5 17.5a8.5 8.5 0 1 1 15 0"/><path d="M12 15.5L7.8 11.3"/><circle cx="12" cy="15.5" r="1.4" fill="currentColor"/>',
    "save": ('<g stroke-width="1.8"><path d="M3.5 2h9l3.5 3.5v9.5a1.5 1.5 0 0 1-1.5 1.5H3.5A1.5 1.5 0 0 1 2 15V3.5A1.5 1.5 0 0 1 3.5 2z"/>'
             '<path d="M6 2v4h6V2"/><path d="M5.5 16.5V12h7v4.5"/><circle cx="18.5" cy="18.5" r="5" fill="{bg}"/>'
             '<path d="M18.5 16v5M16.5 19l2 2 2-2"/></g>'),
    "load": ('<g stroke-width="1.8"><path d="M3.5 2h9l3.5 3.5v9.5a1.5 1.5 0 0 1-1.5 1.5H3.5A1.5 1.5 0 0 1 2 15V3.5A1.5 1.5 0 0 1 3.5 2z"/>'
             '<path d="M6 2v4h6V2"/><path d="M5.5 16.5V12h7v4.5"/><circle cx="18.5" cy="18.5" r="5" fill="{bg}"/>'
             '<path d="M18.5 21v-5M16.5 18l2-2 2 2"/></g>'),
    "sound": '<path d="M11 5L6 9H3v6h3l5 4z"/><path d="M15.5 8.5a5 5 0 0 1 0 7M18.5 5.5a9 9 0 0 1 0 13"/>',
    "muted": '<path d="M11 5L6 9H3v6h3l5 4z"/><path d="M16 9l5 6M21 9l-5 6"/>',
    "minus": '<path d="M6 12h12" stroke-width="2.4"/>',
    "plus": '<path d="M12 6v12M6 12h12" stroke-width="2.4"/>',
    "fullscreen": '<path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5"/>',
    "hide": '<path d="M6 9l6 6 6-6" stroke-width="2.2"/>',
    "show": '<path d="M6 15l6-6 6 6" stroke-width="2.2"/>',
}

#: RetroArch hotkey per stateless button. The toggles are wired below.
ACTION = {"close": "exit_emulator", "menu": "menu_toggle", "reset": "reset",
          "save": "save_state", "load": "load_state",
          "vdown": "volume_down", "vup": "volume_up", "fullscreen": "toggle_fullscreen"}

# Dock layout, the artboard's measurements: 44px buttons, 6px gaps, 8px
# padding, dividers 1px wide with 4px either side.
GAP, PAD, DIV = 6, 8, 9
ITEMS = [("btn", "close"), ("div",), ("btn", "menu"), ("div",),
         ("btn", "pause"), ("btn", "reset"), ("btn", "slow"), ("btn", "ff"), ("btn", "turbo"), ("div",),
         ("btn", "save"), ("btn", "load"), ("div",), ("vol",), ("div",),
         ("btn", "fullscreen"), ("btn", "hide")]
#: The volume pill: mute first, then - and + (volume option A).
VOL = [("mute", 48), ("sep", 1), ("vdown", 40), ("vup", 40)]
VOL_W = sum(w for _, w in VOL)


def render(svg, path):
    loader = GdkPixbuf.PixbufLoader.new_with_type("svg")
    loader.write(svg.encode())
    loader.close()
    loader.get_pixbuf().savev(str(path), "png", [], [])


def tile_png(name, icon, w=44, h=44, bg=TILE_BG, fg="#ffffff", radius=12,
             icon_px=22, opacity=1.0, border=None):
    """One button: a rounded tile (or none) with its icon centered."""
    body = ICON[icon].replace("{bg}", bg if bg != "none" else TILE_BG)
    rect = ""
    if bg != "none":
        stroke = f' stroke="{border}" stroke-width="1"' if border else ""
        rect = f'<rect x="0.5" y="0.5" width="{w-1}" height="{h-1}" rx="{radius}" fill="{bg}"{stroke}/>'
    ix, iy = (w - icon_px) / 2, (h - icon_px) / 2
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w*SCALE}" height="{h*SCALE}" viewBox="0 0 {w} {h}">'
           f'<g opacity="{opacity}">{rect}'
           f'<svg x="{ix}" y="{iy}" width="{icon_px}" height="{icon_px}" viewBox="0 0 24 24" fill="none" '
           f'stroke="{fg}" color="{fg}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">{body}</svg>'
           f'</g></svg>')
    fname = f"btn_{name}.png"
    render(svg, OUT / fname)
    return fname


def item_width(item):
    return {"btn": 44, "div": DIV, "vol": VOL_W}[item[0]]


def layout():
    """Where every button sits: ({name: (center_x, width)}, divider xs, volume x)."""
    row = sum(item_width(i) for i in ITEMS) + GAP * (len(ITEMS) - 1)
    slots, dividers, vol_x = {}, [], None
    x = (W - row) / 2
    for item in ITEMS:
        w = item_width(item)
        if item[0] == "btn":
            slots[item[1]] = (x + w / 2, w)
        elif item[0] == "div":
            dividers.append(x + DIV / 2)
        else:
            vol_x = x
            vx = x
            for name, vw in VOL:
                if name != "sep":
                    slots[name] = (vx + vw / 2, vw)
                vx += vw
        x += w + GAP
    return slots, dividers, vol_x


def render_pieces():
    """The bar's background strip, a divider, and the volume segment.

    Separate images rather than one, because the strip is stretched across
    the whole window and anything drawn on it would stretch with it.
    """
    render(f'<svg xmlns="http://www.w3.org/2000/svg" width="{16*SCALE}" height="{STRIP*SCALE:.0f}" '
           f'viewBox="0 0 16 {STRIP}"><rect width="16" height="{STRIP}" fill="#1e1e1e"/>'
           f'<rect width="16" height="1" fill="#ffffff" fill-opacity="0.10"/></svg>',
           OUT / "btn_bar.png")
    render(f'<svg xmlns="http://www.w3.org/2000/svg" width="{2*SCALE}" height="{24*SCALE}" viewBox="0 0 2 24">'
           f'<rect x="0.5" width="1" height="24" fill="#ffffff" fill-opacity="0.12"/></svg>',
           OUT / "btn_div.png")
    render(f'<svg xmlns="http://www.w3.org/2000/svg" width="{VOL_W*SCALE}" height="{44*SCALE}" '
           f'viewBox="0 0 {VOL_W} 44"><rect width="{VOL_W}" height="44" rx="12" fill="{TILE_BG}"/>'
           f'<rect x="48" y="11" width="1" height="22" fill="#ffffff" fill-opacity="0.14"/></svg>',
           OUT / "btn_volbg.png")
    return "btn_bar.png", "btn_div.png", "btn_volbg.png"


#: How far past the 4:3 box the background strip reaches, in overlay widths
#: either side: enough for a 32:9 screen.
BAR_REACH = 3.0


def desc(action, cx, cy, w, h):
    return (f'"{action},{cx / W:.5f},{cy / H:.5f},rect,'
            f'{w / 2 / W:.5f},{h / 2 / H:.5f}"')


#: The toggles, in page-name order: button -> (hotkey, image off, image on).
#: A page's state is one bit per toggle.
TOGGLES = {
    "pause": ("pause_toggle", "pause", "play"),
    "mute": ("audio_mute", "sound", "muted"),
    "ff": ("toggle_fast_forward", "ff", "ff_on"),
    "slow": ("toggle_slowmotion", "slow", "slow_on"),
    # RetroArch's own turbo bind. With input_turbo_mode at "Single Button
    # (Toggle)" (overlay_bar.runtime_overrides) one press starts the turbo
    # button firing by itself and the next stops it.
    "turbo": ("turbo", "turbo", "turbo_on"),
}


def page_name(state, hidden):
    """``b``/``h`` (bar shown/hidden), then one letter per toggle, upper when on."""
    letters = "".join(name[0].upper() if on else name[0]
                      for name, on in zip(TOGGLES, state))
    return ("h" if hidden else "b") + letters


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    slots, dividers, vol_x = layout()
    bar, div, volbg = render_pieces()
    img = {
        "close": tile_png("close", "close", fg="#ff8a80"),
        "menu": tile_png("menu", "menu"),
        "pause": tile_png("pause", "pause"),
        "play": tile_png("play", "play", bg="#3584e4"),
        "reset": tile_png("reset", "reset"),
        "ff": tile_png("ff", "ff"),
        "ff_on": tile_png("ff_on", "ff", bg="#3584e4"),
        "slow": tile_png("slow", "slow"),
        "slow_on": tile_png("slow_on", "slow", bg="#3584e4"),
        "turbo": tile_png("turbo", "turbo"),
        "turbo_on": tile_png("turbo_on", "turbo", bg="#3584e4"),
        "save": tile_png("save", "save"),
        "load": tile_png("load", "load"),
        "sound": tile_png("sound", "sound", w=48, bg="none"),
        "muted": tile_png("muted", "muted", w=48, bg="#c01c28"),
        "vdown": tile_png("vdown", "minus", w=40, bg="none", icon_px=18),
        "vup": tile_png("vup", "plus", w=40, bg="none", icon_px=18),
        "fullscreen": tile_png("fullscreen", "fullscreen"),
        "hide": tile_png("hide", "hide"),
        # Overlay opacity is global, so the faded "show" button carries its
        # 45% in the image itself.
        "show": tile_png("show", "show", w=40, h=40, bg="#2a2a2a", icon_px=20,
                         opacity=0.45, border="#ffffff30"),
    }

    states = list(itertools.product((False, True), repeat=len(TOGGLES)))
    pages = [(state, hidden) for hidden in (False, True) for state in states]
    lines = [
        "# Generated by scripts/build_overlay.py -- edit that, not this.",
        f"overlays = {len(pages)}",
    ]
    for i, (state, hidden) in enumerate(pages):
        o = f"overlay{i}"
        lines += [f'{o}_name = "{page_name(state, hidden)}"',
                  f"{o}_full_screen = true", f"{o}_normalized = true",
                  f"{o}_aspect_ratio = {W / H:.4f}",
                  f"{o}_block_y_separation = true"]
        if hidden:
            # The lone "show" button rides the right half's separation out to
            # the window's right edge, wherever that is.
            lines.append(f"{o}_auto_x_separation = true")
        else:
            # auto_scale treats a window wider than the overlay like a gamepad
            # layout and pushes the halves of the buttons apart. The dock is
            # one block: keep it centered and whole.
            lines.append(f"{o}_block_x_separation = true")
        descs = []  # (spec, image, next_target)
        if hidden:
            descs.append((desc("overlay_next|shader_next", W - 40, CY, 40, 40), img["show"],
                          page_name(state, False)))
        else:
            descs.append((desc("nul", W / 2, CY, W * (1 + 2 * BAR_REACH), STRIP), bar, None))
            for x in dividers:
                descs.append((desc("nul", x, CY, 1, 24), div, None))
            descs.append((desc("nul", vol_x + VOL_W / 2, CY, VOL_W, 44), volbg, None))
            for name, (cx, w) in slots.items():
                if name in TOGGLES:
                    index = list(TOGGLES).index(name)
                    action, off, on = TOGGLES[name]
                    flipped = tuple(not v if k == index else v for k, v in enumerate(state))
                    descs.append((desc(f"{action}|overlay_next", cx, CY, w, 44),
                                  img[on if state[index] else off],
                                  page_name(flipped, False)))
                elif name == "hide":
                    descs.append((desc("overlay_next|shader_next", cx, CY, w, 44), img["hide"],
                                  page_name(state, True)))
                else:
                    descs.append((desc(ACTION[name], cx, CY, w, 44), img[name], None))
        lines.append(f"{o}_descs = {len(descs)}")
        for j, (spec, image, target) in enumerate(descs):
            lines.append(f"{o}_desc{j} = {spec}")
            lines.append(f"{o}_desc{j}_overlay = {image}")
            if target:
                lines.append(f'{o}_desc{j}_next_target = "{target}"')

    (OUT / "openemux-bar.cfg").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{OUT}: {len(pages)} pages, margin {STRIP:.0f}px = {STRIP / H:.4f} of the height")


if __name__ == "__main__":
    main()
