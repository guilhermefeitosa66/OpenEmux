"""Self-check run *inside* the AppImage by packaging/appimage/build.sh.

The bundle can start and still be unable to draw anything: the pieces the grid
leans on -- the SVG and image loaders, the Rsvg bindings, the GI<->cairo bridge
-- are separate packages, and a missing one only shows up as blank cards at
runtime. Each is exercised here for real, against a frame shipped in the
bundle, so a broken bundle fails the build instead of the user.

Reached through the normal entry point (openemux-run honours OPENEMUX_SELFTEST),
so it sees exactly the environment the app sees.
"""
import os
import sys
import tempfile
from pathlib import Path

failures = []


def check(label, fn):
    try:
        detail = fn()
    except Exception as exc:  # noqa: BLE001 - report, do not abort the run
        failures.append(f"{label}: {type(exc).__name__}: {exc}")
        print(f"[FAIL] {label}: {type(exc).__name__}: {exc}")
        return None
    print(f"[ OK ] {label}{f' -- {detail}' if detail else ''}")
    return detail


def image_loaders():
    import gi
    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf
    names = {f.get_name() for f in GdkPixbuf.Pixbuf.get_formats()}
    # png/jpeg carry the box art, svg every symbolic icon in the UI.
    missing = {"png", "jpeg", "svg"} - names
    if missing:
        raise RuntimeError(f"missing pixbuf loaders: {sorted(missing)}")
    return f"{len(names)} loaders"


def rsvg_bindings():
    from openemux.core import cartridge_render
    if not cartridge_render.rsvg_available():
        raise RuntimeError("Rsvg typelib did not import")
    return "Rsvg available"


def cartridge_render_works():
    """The one that matters: a real frame composited through cairo.

    This is what catches a missing gi-cairo bridge, which raises
    KeyError('could not find foreign type Context') the moment a cairo.Context
    is handed to Rsvg.
    """
    from openemux.core import cartridge_render
    from openemux.ui import grid as gridmod

    frames = sorted(gridmod.CARTRIDGE_ASSETS_DIR.glob("*.svg"))
    if not frames:
        raise RuntimeError(f"no cartridge frames in {gridmod.CARTRIDGE_ASSETS_DIR}")

    with tempfile.TemporaryDirectory() as cache:
        out = cartridge_render.render_cartridge(
            None, frames[0], "SELFTEST", "probe", width=200, scale=2, cache_dir=cache
        )
        if not out or not Path(out).exists() or Path(out).stat().st_size == 0:
            raise RuntimeError(
                f"render_cartridge produced nothing for {frames[0].name} "
                "(see the warning logged above for the cause)"
            )
        size = Path(out).stat().st_size
    return f"{frames[0].name} -> {size} bytes"


def ui_imports():
    from openemux.ui import window  # noqa: F401  - exercises the whole chain
    import openemux
    return f"version {openemux.__version__}"


print(f"self-check inside {os.environ.get('APPDIR', '?')}")
check("image loaders (png/jpeg/svg)", image_loaders)
check("Rsvg bindings", rsvg_bindings)
check("cartridge render (cairo <-> GI)", cartridge_render_works)
check("UI import chain", ui_imports)

if failures:
    print(f"\n{len(failures)} self-check failure(s):")
    for line in failures:
        print(f"  - {line}")
    sys.exit(1)
print("\nall bundle self-checks passed")
