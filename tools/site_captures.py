#!/usr/bin/env python3
"""The site's high-resolution desktop captures (issue #683), taken in the devbox.

    ./devbox/devbox.sh exec env DEVBOX_REPO="$PWD" /usr/bin/python3 tools/site_captures.py OUT_DIR

Runs **inside the devbox** (display :77, never the developer's screen): it
resets the container's throwaway config, points the app at the fictional demo
library (``tools/demo_library.py --configure``), starts it with
``GDK_SCALE=2`` on a 2800x1900 virtual screen and writes, into ``OUT_DIR``:

    grid-sfc.png                     SNES library, cover grid
    cart-{sfc,fc,gba,n64,md,ps}.png  each console in the cartridge view

Each is the window content only (no device chrome), 2640x1756: the
1320x878 layout of the README captures at twice the pixels. Check them by eye
(no toast, no red Log badge, no "Search artwork..." placeholder), copy them to
``docs/assets/desktop/`` and run ``tools/build_site.py --images`` on the host.
The app is driven with xdotool and captured with ImageMagick's ``import``,
both provisioned in the devbox.
"""

import os
import re
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCALE = 2
#: The 1x window of the README captures; its content is 1320x878.
WINDOW = (1322, 880)
SCREEN = "2800x1900"
#: Sidebar rows (y at x=120, the refresh-screenshots coordinates) in the demo library, 1x content coordinates.
SIDEBAR = {"FC": 161, "GBA": 311, "N64": 361, "MD": 461, "PS": 561, "SFC": 611}
#: (view mode, shots): the view mode is set in the config between two runs of
#: the app, rather than clicked, so a header bar redesign cannot break this.
PHASES = [
    ("cartridge", [(f"cart-{c.lower()}", c) for c in ("SFC", "FC", "GBA", "N64", "MD", "PS")]),
    ("cover", [("grid-sfc", "SFC")]),
]
#: Cartridge composites render on a background thread; an early shot catches
#: the "Search artwork..." placeholder.
SETTLE = 8


def run(*cmd, **kw):
    return subprocess.run(cmd, check=True, text=True, capture_output=True, **kw).stdout


def window_id():
    # devbox-win finds the window of the app this kit launched (by its pid,
    # never by name: the PID namespace is the host's).
    for _ in range(30):
        out = subprocess.run(["devbox-win"], capture_output=True, text=True).stdout.split()
        if out:
            return out[0]
        time.sleep(1)
    raise SystemExit("no OpenEmux window on the devbox display")


def geometry(wid):
    info = run("xwininfo", "-id", wid)
    grab = lambda label: int(re.search(label + r":\s+(-?\d+)", info).group(1))  # noqa: E731
    return grab("Absolute upper-left X"), grab("Absolute upper-left Y")


def shot(wid, path):
    run("import", "-window", wid, str(path))
    # Trim the 1px window edge so only the content is left.
    run("convert", str(path), "-bordercolor", "black", "-fuzz", "8%", "-trim", "+repage",
        "-define", "png:compression-level=9", str(path))
    return run("identify", "-format", "%wx%h", str(path))


def main(out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    # The devbox's own X server. distrobox forwards the host's DISPLAY and
    # XAUTHORITY, which must never be the one driven here.
    os.environ["DISPLAY"] = os.environ.get("DEVBOX_DISPLAY", ":77")
    os.environ["XAUTHORITY"] = str(Path.home() / ".devbox" / "Xauthority")
    py = os.environ.get("DEVBOX_PYTHON", "/usr/bin/python3")
    subprocess.run(["devbox-app", "stop"], check=True)
    subprocess.run(["devbox-seed", "--wipe"], check=True)
    subprocess.run([py, str(REPO / "tools" / "demo_library.py"),
                    str(Path.home() / "games" / "demo"), "--configure"], check=True)
    # Put the screen back the way it was found, not to a guessed default.
    before = run("xdotool", "getdisplaygeometry").split()
    subprocess.run(["devbox-res", SCREEN], check=True)
    try:
        for view_mode, shots in PHASES:
            subprocess.run([py, "-c", "import sys; sys.path.insert(0, sys.argv[1]); "
                            "from openemux.core.config import ConfigManager; c = ConfigManager(); "
                            "c.set_theme('dark'); c.set_view_mode(sys.argv[2])",
                            str(REPO / "src"), view_mode], check=True)
            capture(out, shots)
    finally:
        subprocess.run(["devbox-app", "stop"])
        subprocess.run(["devbox-res", "x".join(before)])
        # The devbox is shared (the pipeline's QA runs use it too): hand it
        # back on its synthetic library and default settings, not on the demo
        # library in dark mode and the cover view this run left behind.
        subprocess.run(["devbox-seed", "--wipe"])


def capture(out, shots):
    subprocess.run(["devbox-app", "stop"], check=True)
    subprocess.run(["devbox-app", "start"], check=True, env={**os.environ, "GDK_SCALE": str(SCALE)})
    wid = window_id()
    # xdotool, not wmctrl: `wmctrl -i` wants a hex id and devbox-win hands out
    # the decimal one, so it silently did nothing (see devbox/bin/devbox-res).
    for state in ("MAXIMIZED_VERT", "MAXIMIZED_HORZ"):
        subprocess.run(["xdotool", "windowstate", "--remove", state, wid])
    run("xdotool", "windowsize", wid, str(WINDOW[0] * SCALE), str(WINDOW[1] * SCALE))
    run("xdotool", "windowmove", wid, "40", "40")
    time.sleep(2)
    x0, y0 = geometry(wid)

    def point(cx, cy):
        run("xdotool", "mousemove", str(x0 + cx * SCALE), str(y0 + cy * SCALE))
        time.sleep(0.4)  # GTK 4 drops a click that arrives with no motion before it

    for name, console in shots:
        point(120, SIDEBAR[console])
        run("xdotool", "click", "1")
        time.sleep(SETTLE)
        point(1280, 850)  # park the pointer where nothing reacts to hover
        size = shot(wid, out / f"{name}.png")
        expected = f"{(WINDOW[0] - 2) * SCALE}x{(WINDOW[1] - 2) * SCALE}"
        # The trim works on colour, so a dark edge of content can go with the
        # window border: say so rather than hand over a short capture.
        note = "" if size == expected else f"  (expected {expected}: retake it)"
        print(f"{name}.png  {size}{note}")

if __name__ == "__main__":  # pragma: no cover - a devbox tool, driven by hand
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    main(sys.argv[1])
