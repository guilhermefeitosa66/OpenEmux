#!/usr/bin/env python3
"""Assemble the Windows bundle tree from an extracted MSYS2 prefix.

Runs inside the container, after ``msys2_packages.py`` has unpacked the MINGW64
runtime. Produces the directory that becomes both artifacts -- the portable zip
and the Inno Setup installer read the same tree.

Layout::

    OpenEmux/
      OpenEmux.exe                  the launcher (built separately, by build.sh)
      bin/  lib/  share/  etc/      the relocated MSYS2 prefix
      src/openemux/                 the app
      vendors/RetroArch-Win64/      the bundled RetroArch
      LICENSE  THIRD_PARTY_NOTICES.md  README.md

The layout deliberately mirrors a source checkout rather than the ``lib/openemux
+ retroarch/`` sketch in issue #118: ``core/platform.py`` resolves the bundled
RetroArch at ``vendors/RetroArch-Win64/retroarch.exe`` *relative to the project
root*, and its cores directory the same way. Keeping those relative paths
identical to the checkout means the shipped app takes no code path that has
never been run during development -- the alternative was a second layout, known
only to the installer, that nothing else exercises.
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent

#: Build-time-only files inside the MSYS2 prefix. Headers, static libraries and
#: pkg-config metadata exist to compile against this stack; the bundle only runs
#: it. Documentation is the same story and is the larger half.
PREFIX_PRUNE_DIRS = [
    "include",
    "share/man",
    "share/doc",
    "share/gtk-doc",
    "share/info",
    "share/aclocal",
    "share/bash-completion",
    "share/gir-1.0",
    "lib/pkgconfig",
    "share/pkgconfig",
    "lib/cmake",
    "share/vala",
    # SQLite's loadable-extension *examples* -- .c sources and the .dll built
    # from each. Nothing in OpenEmux calls load_extension, and their README
    # spells an absolute C:/msys64 path, which is exactly what the bundle must
    # never carry: a file that resolves on the build machine and nowhere else.
    "share/sqlite",
]

#: Python's standard library carries things this app never imports. tkinter (and
#: the Tcl/Tk runtime behind it) is the big one -- a second, unused GUI toolkit.
PYTHON_PRUNE = [
    "tkinter",
    "test",
    "idlelib",
    "lib2to3",
    "ensurepip",
    "distutils",
]

#: Dropped from the vendored RetroArch.
#:
#: ``cores`` is not a size decision. Cores carry many different licences, and
#: issue #118 keeps them *downloaded at first boot* precisely so none of them
#: end up inside the installer; OpenEmux downloads what a console needs into
#: this same directory on first run. It also happens to be 1.8 GB.
#:
#: ``database`` is 169 MB of RDB files feeding RetroArch's own content scanner,
#: which OpenEmux never invokes -- it scans the library itself and launches
#: content by path.
#:
#: ``shaders`` is 101 MB that nothing reads. OpenEmux's shader feature works off
#: ``~/.openemux/runtime/shaders_{glsl,slang}``, downloaded from the buildbot on
#: first boot, with ``vendors/retroarch-assets/shaders_*`` as its local
#: fallback -- neither is this directory.
#:
#: ``overlays`` is 33 MB for a feature OpenEmux exposes no UI for.
#:
#: Together these take the vendored RetroArch from 2.3 GB to roughly 200 MB.
RETROARCH_PRUNE_DIRS = ["cores", "database", "shaders", "overlays"]


def log(message):
    print(f"    {message}", flush=True)


def rmtree(path):
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    elif path.exists():
        path.unlink()


def relocate_prefix(extracted, bundle):
    """Move ``<extracted>/mingw64/*`` up to the bundle root.

    MSYS2 packages unpack into a ``mingw64/`` prefix. The bundle drops that
    level so ``bin/`` sits beside ``OpenEmux.exe``, which is what lets Python
    and GTK find their own prefix without being told where they are.
    """
    prefix = extracted / "mingw64"
    if not prefix.is_dir():
        raise SystemExit(f"{prefix} is missing -- did msys2_packages.py run?")
    bundle.mkdir(parents=True, exist_ok=True)
    for entry in sorted(prefix.iterdir()):
        target = bundle / entry.name
        rmtree(target)
        shutil.move(str(entry), str(target))


def prune_prefix(bundle):
    for relative in PREFIX_PRUNE_DIRS:
        rmtree(bundle / relative)

    # Static libraries and import-library leftovers, wherever they landed.
    lib = bundle / "lib"
    if lib.is_dir():
        for pattern in ("*.a", "*.la"):
            for path in lib.rglob(pattern):
                path.unlink(missing_ok=True)

    for python_dir in (bundle / "lib").glob("python3.*"):
        for name in PYTHON_PRUNE:
            rmtree(python_dir / name)

    # Tcl/Tk itself, now that tkinter is gone.
    for path in list((bundle / "lib").glob("tcl*")) + list((bundle / "lib").glob("tk*")):
        rmtree(path)
    for pattern in ("tcl*.dll", "tk*.dll", "wish*.exe", "tclsh*.exe"):
        for path in (bundle / "bin").glob(pattern):
            path.unlink(missing_ok=True)

    drop_pycache(bundle)


def drop_pycache(root):
    for path in root.rglob("__pycache__"):
        shutil.rmtree(path, ignore_errors=True)


def compile_schemas(bundle):
    """Build ``gschemas.compiled`` so GTK can read its settings.

    GTK aborts at startup without it -- the schemas ship as XML and pacman
    normally compiles them in a post-install hook that never runs here. The
    compiler is the Linux one from the container; its output is GVDB, which
    records its own byte order and is read back correctly on Windows.
    """
    schemas = bundle / "share" / "glib-2.0" / "schemas"
    if not schemas.is_dir():
        raise SystemExit(f"{schemas} is missing -- the GTK packages did not unpack")
    compiler = shutil.which("glib-compile-schemas")
    if not compiler:
        raise SystemExit("glib-compile-schemas is required (Debian: libglib2.0-bin)")
    subprocess.run([compiler, str(schemas)], check=True)
    if not (schemas / "gschemas.compiled").is_file():
        raise SystemExit("glib-compile-schemas produced no gschemas.compiled")


def build_icon_cache(bundle):
    """Index the icon themes.

    Not fatal when the tool is missing: GTK falls back to walking the theme
    directories, which is slower but correct. A broken bundle is worth failing
    on; a slower one is not.
    """
    tool = shutil.which("gtk4-update-icon-cache") or shutil.which("gtk-update-icon-cache")
    if not tool:
        log("no gtk-update-icon-cache; the icon themes ship without an index")
        return
    for theme in ("Adwaita", "hicolor"):
        directory = bundle / "share" / "icons" / theme
        if directory.is_dir():
            subprocess.run([tool, "-q", "-t", "-f", str(directory)], check=False)


def copy_app(bundle):
    """The app itself, with the ScreenScraper credential baked into the copy."""
    target = bundle / "src" / "openemux"
    rmtree(bundle / "src")
    shutil.copytree(REPO / "src" / "openemux", target)
    drop_pycache(bundle / "src")

    # Never the host source tree: the credential goes into the staged copy only.
    # A no-op unless SCREENSCRAPER_DEVID/DEVPASSWORD are in the environment, so
    # a build without them simply ships no embedded credential.
    subprocess.run(
        [
            sys.executable,
            str(REPO / "packaging" / "embed_screenscraper_credentials.py"),
            str(target / "core" / "embedded_credentials.py"),
        ],
        check=True,
    )


def copy_retroarch(bundle):
    source = REPO / "vendors" / "RetroArch-Win64"
    if not (source / "retroarch.exe").is_file():
        raise SystemExit(
            f"{source}/retroarch.exe is missing. Run: make vendor-retroarch"
        )
    target = bundle / "vendors" / "RetroArch-Win64"
    rmtree(bundle / "vendors")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target)
    for relative in RETROARCH_PRUNE_DIRS:
        rmtree(target / relative)

    # Recreated empty: this is where OpenEmux downloads cores on first boot, and
    # RetroArch's own config reads it as a directory that exists.
    (target / "cores").mkdir(parents=True, exist_ok=True)

    # RetroArch is GPLv3 and is redistributed here unmodified. Its own licence
    # text must travel with the binary; THIRD_PARTY_NOTICES.md carries the
    # matching source offer.
    #
    # The upstream archive does not contain it. It ships assets/COPYING, which
    # is CC-BY-4.0 and covers the *assets*, and nothing at the top level -- so
    # this used to stop the build dead, and it is why the Windows bundle had
    # never been built anywhere but the maintainer's own machine (issue #118).
    # vendors/RetroArch-COPYING is that version's own COPYING, committed and
    # recorded in vendors/manifest.json. The archive is still checked first, so
    # an upstream that starts shipping one is used in preference.
    for name in ("COPYING", "COPYING.txt", "LICENSE"):
        candidate = source / name
        if candidate.is_file():
            shutil.copy2(candidate, target / "COPYING")
            break
    else:
        vendored = REPO / "vendors" / "RetroArch-COPYING"
        if not vendored.is_file():
            raise SystemExit(
                f"{vendored} is missing, and the vendored RetroArch ships no "
                "COPYING/LICENSE of its own; GPLv3 redistribution requires "
                "shipping its licence text"
            )
        shutil.copy2(vendored, target / "COPYING")


def copy_documents(bundle):
    for name in ("LICENSE", "THIRD_PARTY_NOTICES.md", "README.md"):
        shutil.copy2(REPO / name, bundle / name)


def directory_size(path):
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += (Path(root) / name).stat().st_size
            except OSError:
                pass
    return total


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--extracted", type=Path, required=True,
                        help="where msys2_packages.py unpacked the prefix")
    parser.add_argument("--bundle", type=Path, required=True,
                        help="the bundle tree to build")
    args = parser.parse_args(argv)

    print("==> relocating the MSYS2 prefix")
    relocate_prefix(args.extracted, args.bundle)

    print("==> pruning build-time and unused files")
    prune_prefix(args.bundle)

    print("==> compiling GLib schemas")
    compile_schemas(args.bundle)

    print("==> indexing icon themes")
    build_icon_cache(args.bundle)

    print("==> copying the app")
    copy_app(args.bundle)

    print("==> copying the bundled RetroArch")
    copy_retroarch(args.bundle)

    copy_documents(args.bundle)

    size = directory_size(args.bundle)
    print(f"==> bundle staged at {args.bundle} ({size / (1 << 20):.0f} MiB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
