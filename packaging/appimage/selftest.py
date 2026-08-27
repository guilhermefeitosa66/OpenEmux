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
    from openemux.core.scraper import SUPPORTED_COVER_EXTS
    names = {f.get_name() for f in GdkPixbuf.Pixbuf.get_formats()}
    # Every format a cover can arrive in, plus svg for the symbolic icons.
    # webp is the one the libretro thumbnail sync downloads and the one
    # gdk-pixbuf has no built-in decoder for, so it is a separate package on
    # every distribution and the first to go missing (issue #251).
    required = {{"jpg": "jpeg"}.get(ext, ext) for ext in SUPPORTED_COVER_EXTS}
    required.add("svg")
    missing = required - names
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

    assets_dir = cartridge_render.CARTRIDGE_ASSETS_DIR
    # The base shells only: a "<CONSOLE>-<colour>.svg" variant is a shell for a
    # console already covered, and rendering one proves nothing extra.
    frames = sorted(p for p in assets_dir.glob("*.svg") if "-" not in p.stem)
    if not frames:
        raise RuntimeError(f"no cartridge frames in {assets_dir}")

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


def bundled_symbolic_icons():
    """Every symbolic name the UI uses must have its vendored fallback SVG.

    The bundle also ships adwaita-icon-theme, but the fallback set is what
    keeps icons rendering when the host's active theme shadows it; a build
    where the directory went missing must not ship.
    """
    from openemux.ui.icons import SYMBOLIC_ICON_DIR
    svgs = list(SYMBOLIC_ICON_DIR.glob("*.svg"))
    if not svgs:
        raise RuntimeError(f"no vendored symbolic icons in {SYMBOLIC_ICON_DIR}")
    return f"{len(svgs)} icons in {SYMBOLIC_ICON_DIR.name}/"


def ui_imports():
    from openemux.ui import window  # noqa: F401  - exercises the whole chain
    import openemux
    return f"version {openemux.__version__}"


print(f"self-check inside {os.environ.get('APPDIR', '?')}")
check("image loaders (png/jpeg/webp/svg)", image_loaders)
check("Rsvg bindings", rsvg_bindings)
check("cartridge render (cairo <-> GI)", cartridge_render_works)
check("bundled symbolic icons", bundled_symbolic_icons)
check("UI import chain", ui_imports)

if failures:
    print(f"\n{len(failures)} self-check failure(s):")
    for line in failures:
        print(f"  - {line}")
    sys.exit(1)
print("\nall bundle self-checks passed")
