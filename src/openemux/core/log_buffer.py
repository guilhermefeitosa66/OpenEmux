"""The log the app keeps in memory, for the log panel and bug reports.

The startup log on disk (``startup_logging``) is the record; this is the view.
A bounded ring of formatted lines fed by a handler on the root logger, so the
panel can show what happened since the app started without reading the file
back, and a listener per window to be told about each new line.

Kept free of GTK: the handler runs on whatever thread logged, and the UI
decides how to get back to its own thread.
"""

import collections
import logging
import threading

#: How many lines the panel can scroll back through. Enough for a session's
#: worth of launches and syncs; the file on disk keeps the rest.
MAX_LINES = 2000

#: The lines a bug report carries. A report is read by a person, and the last
#: few hundred lines are where the problem is.
REPORT_LINES = 300

LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"


class LogLine:
    """One formatted record, with what the panel needs to colour it."""

    __slots__ = ("level", "text")

    def __init__(self, level, text):
        self.level = level
        self.text = text

    @property
    def is_error(self):
        return self.level >= logging.ERROR


class LogBuffer(logging.Handler):
    """A root-logger handler that remembers the last ``MAX_LINES`` lines."""

    def __init__(self, max_lines=MAX_LINES):
        super().__init__(level=logging.INFO)
        self.setFormatter(logging.Formatter(LOG_FORMAT))
        self._lines = collections.deque(maxlen=max_lines)
        self._listeners = []
        self._lock_lines = threading.Lock()
        self.errors_since_seen = 0

    def emit(self, record):
        try:
            line = LogLine(record.levelno, self.format(record))
        except Exception:  # noqa: BLE001 - logging must never raise
            self.handleError(record)
            return
        with self._lock_lines:
            self._lines.append(line)
            if line.is_error:
                self.errors_since_seen += 1
            listeners = list(self._listeners)
        for listener in listeners:
            listener(line)

    def lines(self):
        with self._lock_lines:
            return list(self._lines)

    def tail(self, count=REPORT_LINES):
        lines = self.lines()
        return lines[-count:] if count else lines

    def clear(self):
        """Empty the view. The file on disk is left alone."""
        with self._lock_lines:
            self._lines.clear()
            self.errors_since_seen = 0

    def mark_seen(self):
        with self._lock_lines:
            self.errors_since_seen = 0

    def add_listener(self, listener):
        with self._lock_lines:
            self._listeners.append(listener)

    def remove_listener(self, listener):
        with self._lock_lines:
            if listener in self._listeners:
                self._listeners.remove(listener)


#: The one buffer of the process, installed on the root logger by
#: ``startup_logging.configure_startup_logging``.
BUFFER = LogBuffer()
