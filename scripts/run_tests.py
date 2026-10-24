#!/usr/bin/env python3
"""Run a test command on a display nobody is looking at.

    scripts/run_tests.py python -m unittest discover -s tests

The suite builds real GTK widgets (``tests/gtk_display.py``), and on a
developer's machine the display it finds is their own screen: windows flash up
and steal focus for the whole run (issue #528). This is what ``make test`` and
``make coverage`` go through, so they do what CI does instead:

* on Linux with ``xvfb-run`` installed, the command replaces this process under
  ``xvfb-run -a``, with every route back to the real session closed --
  ``WAYLAND_DISPLAY`` unset, GDK pinned to X11, the file-chooser portals off --
  and ``OPENEMUX_TESTS_PRIVATE_DISPLAY=1`` so ``tests/gtk_display.py`` knows
  the display is a private one and runs the widget tests -- on a throwaway
  session bus too (``dbus-run-session``) when that is installed;
* on Linux without it, the command runs as it is after one message saying what
  is missing; ``tests/gtk_display.py`` then skips the widget tests rather than
  drawing on the desktop;
* elsewhere (Windows has no Xvfb), with ``OPENEMUX_TESTS_ON_DESKTOP=1``, or
  when the run is already on a private display (the devbox), it runs as it is.

The exit code is the command's.
"""

import os
import shutil
import subprocess
import sys

OPT_IN = "OPENEMUX_TESTS_ON_DESKTOP"
PRIVATE_DISPLAY = "OPENEMUX_TESTS_PRIVATE_DISPLAY"

MISSING_XVFB = (
    "Xvfb not found: widget tests will be skipped so nothing opens on your "
    "desktop (and `make coverage` will miss its 100% floor without them).\n"
    "Install it with `make install-sys-deps` (Debian/Ubuntu), "
    "`sudo dnf install xorg-x11-server-Xvfb` (Fedora) or "
    "`sudo pacman -S xorg-server-xvfb` (Arch).\n"
    f"Set {OPT_IN}=1 to run them on your screen instead.\n"
)
USAGE = "usage: scripts/run_tests.py <command> [args...]\n"


def decide(env, platform, which=shutil.which):
    """``direct``, ``xvfb`` or ``missing``: how to run the command."""
    if not platform.startswith("linux"):
        return "direct"
    if env.get(OPT_IN) == "1" or env.get(PRIVATE_DISPLAY) == "1":
        return "direct"
    return "xvfb" if which("xvfb-run") else "missing"


def headless_env(env):
    """A copy of ``env`` that cannot reach the developer's session."""
    env = dict(env)
    env.pop("WAYLAND_DISPLAY", None)
    env["GDK_BACKEND"] = "x11"
    env[PRIVATE_DISPLAY] = "1"
    # A file dialog goes through xdg-desktop-portal over the session bus, which
    # is the developer's, and the portal draws on *their* screen whatever
    # DISPLAY says. no-portals is GTK 4's switch; GTK_USE_PORTAL the older one.
    flags = [flag for flag in env.get("GDK_DEBUG", "").split(",") if flag]
    if "no-portals" not in flags:
        flags.append("no-portals")
    env["GDK_DEBUG"] = ",".join(flags)
    env["GTK_USE_PORTAL"] = "0"
    return env


def main(argv=None, env=None, platform=None, which=shutil.which,
         execvpe=os.execvpe, call=subprocess.call, stderr=None):
    argv = sys.argv[1:] if argv is None else argv
    env = dict(os.environ) if env is None else env
    platform = sys.platform if platform is None else platform
    stderr = sys.stderr if stderr is None else stderr
    if not argv:
        stderr.write(USAGE)
        return 2
    mode = decide(env, platform, which)
    if mode == "xvfb":
        command = ["xvfb-run", "-a", *argv]
        # The session bus is the developer's too: an app registered on it, a
        # FileManager1 call or a browser's D-Bus remote reaches their screen
        # whatever DISPLAY says. A throwaway bus closes that, as the devbox does.
        if which("dbus-run-session"):
            command = ["dbus-run-session", "--", *command]
        # Replaces this process, so Ctrl+C and the exit code are the suite's.
        return execvpe(command[0], command, headless_env(env))
    if mode == "missing":
        stderr.write(MISSING_XVFB)
    return call(argv, env=env)


if __name__ == "__main__":
    sys.exit(main())
