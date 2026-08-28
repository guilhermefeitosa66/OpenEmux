#!/usr/bin/env python3
"""Verify that the GTK stack the app needs is importable, and say which parts are not.

Exists as a file rather than a ``python -c`` one-liner because the Windows
bootstrap drives it through PowerShell and then bash, and a Python one-liner
does not survive two layers of quoting intact.

Each import is checked on its own so a missing piece names itself. Importing
them together only ever reports the first failure, and the interesting case --
``Rsvg`` or the ``gi``/cairo bridge missing while GTK itself is fine -- is
exactly the one that then looks like "GTK is broken" and sends you down the
wrong path. Both are real: without Rsvg every symbolic icon is blank, and
without the cairo bridge the cartridge art fails to composite.
"""

import sys

# (label, required, callable returning a version string or "")
CHECKS = []


def _check(label, required=True):
    def register(fn):
        CHECKS.append((label, required, fn))
        return fn

    return register


@_check("PyGObject (gi)")
def _gi():
    import gi

    return gi.__version__


@_check("GTK 4")
def _gtk():
    import gi

    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk

    return f"{Gtk.get_major_version()}.{Gtk.get_minor_version()}.{Gtk.get_micro_version()}"


@_check("libadwaita")
def _adw():
    import gi

    gi.require_version("Adw", "1")
    from gi.repository import Adw

    version = f"{Adw.MAJOR_VERSION}.{Adw.MINOR_VERSION}"
    # The app builds its UI out of widgets that landed in 1.5
    # (Adw.NavigationSplitView, Adw.AboutDialog); anything older starts and
    # then fails at first paint, which is a much worse way to find out.
    if (Adw.MAJOR_VERSION, Adw.MINOR_VERSION) < (1, 5):
        raise RuntimeError(f"libadwaita {version} is too old; OpenEmux needs >= 1.5")
    return version


@_check("librsvg (Rsvg-2.0 typelib)")
def _rsvg():
    import gi

    gi.require_version("Rsvg", "2.0")
    from gi.repository import Rsvg

    return getattr(Rsvg, "MAJOR_VERSION", "") and (
        f"{Rsvg.MAJOR_VERSION}.{Rsvg.MINOR_VERSION}"
    )


@_check("pycairo")
def _cairo():
    import cairo

    return cairo.version


@_check("gi/cairo bridge")
def _gi_cairo():
    # The foreign-struct bridge that lets a cairo.Context cross the gi
    # boundary. Shipped separately from pycairo on some platforms, and its
    # absence only shows up when something actually draws.
    import gi

    gi.require_foreign("cairo")
    return ""


@_check("PyYAML")
def _yaml():
    import yaml

    return yaml.__version__


def main():
    failures = []
    for label, required, probe in CHECKS:
        try:
            version = probe() or ""
        except Exception as exc:  # noqa: BLE001 - report every failure, not the first
            mark = "FAIL" if required else "warn"
            print(f"  {mark}  {label}: {exc}")
            if required:
                failures.append(label)
        else:
            suffix = f" {version}" if version else ""
            print(f"  ok    {label}{suffix}")

    if failures:
        print(f"\n{len(failures)} missing: {', '.join(failures)}", file=sys.stderr)
        print(
            "On Windows, install them with:  make install-sys-deps-windows",
            file=sys.stderr,
        )
        return 1

    print("\nGTK stack OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
