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
#: Sidebar rows (y at x=150) in the demo library, 1x content coordinates.
SIDEBAR = {"FC": 161, "GBA": 311, "N64": 361, "MD": 461, "PS": 561, "SFC": 611}
#: The view switcher in the header bar, measured from the right edge.
COVERS, CARTRIDGE = 1320 - 328, 1320 - 294
SHOTS = [("grid-sfc", "SFC", COVERS)] + [
    (f"cart-{c.lower()}", c, CARTRIDGE) for c in ("SFC", "FC", "GBA", "N64", "MD", "PS")]
#: Cartridge composites render on a background thread; an early shot catches
#: the "Search artwork..." placeholder.
SETTLE = 8


def run(*cmd, **kw):
    return subprocess.run(cmd, check=True, text=True, capture_output=True, **kw).stdout


def window_id():
    for _ in range(30):
        out = subprocess.run(["xdotool", "search", "--name", "^OpenEmux$"],
                             capture_output=True, text=True).stdout.split()
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
    py = os.environ.get("DEVBOX_PYTHON", "/usr/bin/python3")
    subprocess.run(["devbox-app", "stop"], check=True)
    subprocess.run(["devbox-seed", "--wipe"], check=True)
    subprocess.run([py, str(REPO / "tools" / "demo_library.py"),
                    str(Path.home() / "games" / "demo"), "--configure"], check=True)
    subprocess.run([py, "-c", "import sys; sys.path.insert(0, sys.argv[1]); "
                    "from openemux.core.config import ConfigManager; ConfigManager().set_theme('dark')",
                    str(REPO / "src")], check=True)
    subprocess.run(["devbox-res", SCREEN], check=True)
    try:
        subprocess.run(["devbox-app", "start"], check=True, env={**os.environ, "GDK_SCALE": str(SCALE)})
        wid = window_id()
        subprocess.run(["wmctrl", "-i", "-r", wid, "-b", "remove,maximized_vert,maximized_horz"])
        run("xdotool", "windowsize", wid, str(WINDOW[0] * SCALE), str(WINDOW[1] * SCALE))
        run("xdotool", "windowmove", wid, "40", "40")
        time.sleep(2)
        x0, y0 = geometry(wid)

        def click(cx, cy):
            run("xdotool", "mousemove", str(x0 + cx * SCALE), str(y0 + cy * SCALE), "click", "1")

        for name, console, view in SHOTS:
            click(150, SIDEBAR[console])
            time.sleep(2)
            click(view, 27)
            time.sleep(SETTLE)
            # Park the pointer where nothing reacts to hover.
            run("xdotool", "mousemove", str(x0 + 1280 * SCALE), str(y0 + 850 * SCALE))
            time.sleep(0.5)
            print(f"{name}.png  {shot(wid, out / f'{name}.png')}")
    finally:
        subprocess.run(["devbox-app", "stop"])
        subprocess.run(["devbox-res", "1600x1100"])


if __name__ == "__main__":  # pragma: no cover - a devbox tool, driven by hand
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    main(sys.argv[1])
