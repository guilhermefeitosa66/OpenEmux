import faulthandler
import logging
import logging.handlers
import sys
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from openemux.core import startup_logging
from openemux.core.startup_logging import (
    LOG_BACKUP_COUNT,
    LOG_MAX_BYTES,
    append_startup_error,
    configure_startup_logging,
    get_startup_log_path,
)


class StartupLoggingTests(unittest.TestCase):
    def test_append_startup_error_creates_log_file(self):
        with TemporaryDirectory() as tmp_dir:
            log_path = append_startup_error(
                "startup failed",
                exc_text="traceback line",
                runtime_dir=tmp_dir,
            )
            self.assertTrue(log_path.exists())
            text = log_path.read_text(encoding="utf-8")
            self.assertIn("startup failed", text)
            self.assertIn("traceback line", text)

    def test_get_startup_log_path_uses_runtime_dir(self):
        with TemporaryDirectory() as tmp_dir:
            path = get_startup_log_path(runtime_dir=tmp_dir)
            self.assertEqual(path, Path(tmp_dir) / "openemux_startup.log")


class RotatingStartupLogTests(unittest.TestCase):
    """The startup log has a ceiling (issue #221).

    It used to be an append-mode ``FileHandler``, so the file only ever grew --
    260,000 lines on the development machine.
    """

    def setUp(self):
        self._saved = list(logging.getLogger().handlers)
        self._saved_level = logging.getLogger().level
        self._saved_excepthook = sys.excepthook
        self._saved_thread_excepthook = threading.excepthook

    def tearDown(self):
        root = logging.getLogger()
        for handler in list(root.handlers):
            handler.close()
        root.handlers = self._saved
        root.setLevel(self._saved_level)
        # configure_startup_logging installs the crash handlers; leaving them
        # behind would make every later test report through this module.
        sys.excepthook = self._saved_excepthook
        threading.excepthook = self._saved_thread_excepthook
        # It also holds the log file open for faulthandler; hand it back so
        # the temp directory can go away cleanly.
        faulthandler.enable(file=sys.__stderr__, all_threads=True)
        startup_logging._release_crash_log()

    @staticmethod
    def _rotating_handler():
        return next(
            handler
            for handler in logging.getLogger().handlers
            if isinstance(handler, logging.handlers.RotatingFileHandler)
        )

    def test_the_file_handler_rotates(self):
        with TemporaryDirectory() as tmp_dir:
            configure_startup_logging(runtime_dir=tmp_dir)
            handler = self._rotating_handler()
            self.assertEqual(handler.maxBytes, LOG_MAX_BYTES)
            self.assertEqual(handler.backupCount, LOG_BACKUP_COUNT)

    def test_total_size_stays_bounded(self):
        with TemporaryDirectory() as tmp_dir:
            log_path = configure_startup_logging(runtime_dir=tmp_dir)
            handler = self._rotating_handler()
            handler.maxBytes = 1024
            # Keep 2000 lines of test output off the terminal.
            logging.getLogger().handlers = [handler]
            logger = logging.getLogger("openemux.test")
            for index in range(2000):
                logger.info("a line that is long enough to matter %d %s", index, "x" * 60)

            written = sorted(Path(tmp_dir).glob("openemux_startup.log*"))
            self.assertLessEqual(len(written), LOG_BACKUP_COUNT + 1)
            self.assertLess(sum(p.stat().st_size for p in written), 64 * 1024)
            self.assertTrue(log_path.exists())


if __name__ == "__main__":
    unittest.main()
