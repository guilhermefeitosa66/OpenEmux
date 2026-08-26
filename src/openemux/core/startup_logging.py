import faulthandler
import logging
import os
import sys
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path


#: How log output handles a character its encoder cannot represent.
#:
#: The app logs ROM paths, and a filename is bytes: one carrying a non-UTF-8
#: byte reaches logging as a lone surrogate ('Contra \udcff.nes'). A strict
#: handler raises inside emit(), and Python answers with a "--- Logging
#: error ---" traceback on stderr and drops the line -- once per log call, for
#: every such ROM (issue #214). Escaped is readable and cannot fail.
LOG_ERRORS = "backslashreplace"


def _reconfigure_stream(stream):
    """Make a stream tolerate un-encodable characters, if it can be told to."""
    try:
        stream.reconfigure(errors=LOG_ERRORS)
    except (AttributeError, ValueError, OSError):  # pragma: no cover - stream dependent
        pass


def get_startup_log_path(runtime_dir=None):
    if runtime_dir:
        base_dir = Path(runtime_dir).expanduser()
    else:
        base_dir = Path.home() / ".openemux" / "runtime"
    try:
        base_dir.mkdir(parents=True, exist_ok=True)
        return base_dir / "openemux_startup.log"
    except OSError:
        fallback_dir = Path(tempfile.gettempdir()) / "openemux"
        fallback_dir.mkdir(parents=True, exist_ok=True)
        return fallback_dir / "openemux_startup.log"


def append_startup_error(message, exc_text=None, runtime_dir=None):
    try:
        log_path = get_startup_log_path(runtime_dir=runtime_dir)
        timestamp = datetime.now(timezone.utc).isoformat()
        lines = [f"{timestamp} ERROR {message}"]
        if exc_text:
            lines.append(exc_text.rstrip())
        with open(log_path, "a", encoding="utf-8", errors=LOG_ERRORS) as handle:
            handle.write("\n".join(lines) + "\n")
        return log_path
    except OSError:
        print(f"openemux startup error: {message}", file=sys.stderr)
        if exc_text:
            print(exc_text.rstrip(), file=sys.stderr)
        return None


def install_crash_handlers(log_path=None):
    """Leave a trace behind when the process dies instead of just vanishing.

    Two different failures are covered. A Python exception nobody caught goes
    through ``sys.excepthook`` (and the threading one) into the log. A crash in
    the GTK/GDK C stack cannot be caught at all -- the process is gone -- but
    ``faulthandler`` writes the native and Python stacks to the log file on the
    way down, which is the difference between a bare "segmentation fault" in
    the terminal and knowing where it happened.
    """
    if log_path is not None:
        try:
            # Kept open for the lifetime of the process: faulthandler writes to
            # this descriptor from a signal handler, so it cannot be reopened.
            handle = open(log_path, "a", encoding="utf-8", errors=LOG_ERRORS)
            faulthandler.enable(file=handle, all_threads=True)
        except OSError:
            faulthandler.enable(all_threads=True)
    else:
        faulthandler.enable(all_threads=True)

    def _log_exception(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        logging.getLogger("openemux").critical(
            "unhandled exception", exc_info=(exc_type, exc_value, exc_tb)
        )

    sys.excepthook = _log_exception
    threading.excepthook = lambda args: _log_exception(
        args.exc_type, args.exc_value, args.exc_traceback
    )


def configure_startup_logging(runtime_dir=None):
    log_path = get_startup_log_path(runtime_dir=runtime_dir)
    # stderr is what the console handler writes to; a surrogate in a ROM path
    # would otherwise raise inside its emit() on every line that names one.
    _reconfigure_stream(sys.stderr)
    handlers = [logging.StreamHandler()]
    try:
        handlers.append(
            logging.FileHandler(log_path, encoding="utf-8", errors=LOG_ERRORS)
        )
    except OSError:
        pass
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        handlers=handlers,
        force=True,
    )
    logging.getLogger(__name__).info(
        "startup context: appimage=%s appdir=%s project_root_env=%s display=%s wayland=%s session=%s gsk_renderer=%s gdk_backend=%s python=%s",
        os.environ.get("APPIMAGE"),
        os.environ.get("APPDIR"),
        os.environ.get("OPENEMUX_PROJECT_ROOT"),
        os.environ.get("DISPLAY"),
        os.environ.get("WAYLAND_DISPLAY"),
        os.environ.get("XDG_SESSION_TYPE"),
        os.environ.get("GSK_RENDERER"),
        os.environ.get("GDK_BACKEND"),
        sys.version.split()[0],
    )
    install_crash_handlers(log_path)
    return log_path
