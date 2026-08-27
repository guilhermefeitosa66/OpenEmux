#!/usr/bin/env python3
"""Start the real app headlessly, wait for its window, and quit.

The unit suite never constructs an ``Adw.Application`` or an
``OpenEmuxWindow``, and ``main.py`` does real work at import time -- the
renderer pick, the legacy config migration, startup logging, the GTK typelib
check. A crash in any of that, or in window construction, used to pass CI green
and be caught only by the pre-release smoke gate, by hand, on a desktop
(issue #242).

This is that gate, reduced to what a container can run:

* a throwaway ``HOME``, so nothing touches the developer's real ``~/.openemux``;
* the bootstrap marked done in that throwaway config, so the app goes straight
  to the main window instead of downloading every libretro core;
* the window is waited for, not slept on, and the process quits as soon as it
  is up.

Needs a display -- ``xvfb-run -a scripts/smoke_start.py`` in CI.

Exit codes:
    0  the app started, the window appeared, the startup log is clean
    1  a check failed
    2  the check could not be made (no display, no GTK stack)
"""

import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

TIMEOUT_SECONDS = int(os.environ.get("OPENEMUX_SMOKE_TIMEOUT", "60"))
#: Seconds to keep the app up after the window appears. The window is visible
#: well before start-up is done -- the playlist rebuild runs on a background
#: thread -- so quitting on sight both misses late failures and pulls the
#: throwaway HOME out from under a thread still writing into it.
SETTLE_SECONDS = int(os.environ.get("OPENEMUX_SMOKE_SETTLE", "6"))
REPO_ROOT = Path(__file__).resolve().parents[1]

#: What in the startup log means the app did not really start well, however
#: healthy the window looks.
LOG_FAILURES = ("Traceback (most recent call last)", "CRITICAL", " ERROR ",
                "Fatal Python error")


def _prepare_home():
    """Redirect HOME and pre-complete the bootstrap in the copy it points at.

    Everything the app writes hangs off ``Path.home()``, which honours ``HOME``
    on POSIX, so one variable moves the whole config, runtime and desktop-entry
    footprint into a directory this script owns and deletes.
    """
    home = Path(tempfile.mkdtemp(prefix="openemux-smoke-home-"))
    os.environ["HOME"] = str(home)
    os.environ.pop("XDG_CONFIG_HOME", None)
    os.environ.pop("XDG_DATA_HOME", None)

    from openemux.core.config import ConfigManager

    config = ConfigManager()
    # Without this the first activation opens FirstBootWindow and downloads
    # every core from the RetroArch buildbot: minutes of network for a check
    # about whether the app starts.
    config.finish_bootstrap_success()
    # The startup update check calls the GitHub API. Whether it can reach it
    # says nothing about whether the app starts, and a rate-limited or offline
    # runner should not make this red.
    config.config.setdefault("updates", {})["check_on_startup"] = False
    config.save_config()
    return home


def _run_app():
    from gi.repository import GLib
    from openemux.main import OpenEmuxApplication

    app = OpenEmuxApplication()
    state = {"window": False}

    def _quit():
        app.quit()
        return GLib.SOURCE_REMOVE

    def _poll():
        window = getattr(app, "main_window", None)
        if window is not None and window.get_visible():
            state["window"] = True
            print(f"smoke: window up; watching it for {SETTLE_SECONDS}s")
            GLib.timeout_add_seconds(SETTLE_SECONDS, _quit)
            return GLib.SOURCE_REMOVE
        return GLib.SOURCE_CONTINUE

    def _give_up():
        if state["window"]:
            return GLib.SOURCE_REMOVE
        print(f"smoke: no window after {TIMEOUT_SECONDS}s", file=sys.stderr)
        app.quit()
        return GLib.SOURCE_REMOVE

    GLib.timeout_add(200, _poll)
    GLib.timeout_add_seconds(TIMEOUT_SECONDS, _give_up)
    status = app.run([])
    # Daemon threads outlive app.run(); reading the log (and deleting the home)
    # while one is mid-write is how this script produced its own failures.
    time.sleep(1)
    return state["window"], status


def _startup_log_errors(home):
    log = home / ".openemux" / "runtime" / "openemux_startup.log"
    if not log.exists():
        return []
    lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
    return [line for line in lines if any(bad in line for bad in LOG_FAILURES)]


def _dump_startup_log(home, lines=60):
    log = home / ".openemux" / "runtime" / "openemux_startup.log"
    if not log.exists():
        print(f"smoke: no startup log at {log}", file=sys.stderr)
        return
    tail = log.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:]
    print(f"smoke: last {len(tail)} lines of {log.name}:", file=sys.stderr)
    for line in tail:
        print(f"       {line}", file=sys.stderr)


def main():
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        print("smoke: no DISPLAY/WAYLAND_DISPLAY; run under xvfb-run", file=sys.stderr)
        return 2

    sys.path.insert(0, str(REPO_ROOT / "src"))
    try:
        import gi  # noqa: F401
    except ImportError as exc:
        print(f"smoke: no GTK stack ({exc})", file=sys.stderr)
        return 2

    home = _prepare_home()
    try:
        try:
            window_seen, status = _run_app()
        except Exception:
            import traceback
            traceback.print_exc()
            print("smoke: the app raised on startup", file=sys.stderr)
            return 1

        failed = False
        if not window_seen:
            print("smoke: FAIL the main window never became visible", file=sys.stderr)
            failed = True
        else:
            print("smoke: OK   the main window came up")

        if status != 0:
            print(f"smoke: FAIL the app exited with status {status}", file=sys.stderr)
            failed = True

        errors = _startup_log_errors(home)
        if errors:
            print("smoke: FAIL errors in the startup log:", file=sys.stderr)
            for line in errors[:20]:
                print(f"       {line}", file=sys.stderr)
            failed = True
        else:
            print("smoke: OK   the startup log is clean")

        if failed:
            # The throwaway home goes away with this process, so whatever the
            # log has to say has to be said now -- a CI step reading it
            # afterwards would find nothing.
            _dump_startup_log(home)
        return 1 if failed else 0
    finally:
        shutil.rmtree(home, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
