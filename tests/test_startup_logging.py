import contextlib
import faulthandler
import io
import logging
import logging.handlers
import sys
import threading
import unittest
from unittest import mock
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


class WhereTheLogGoesWhenTheHomeIsUnusableTests(unittest.TestCase):
    """Refusing to start because a *log* cannot be written would be worse."""

    def test_without_a_runtime_dir_it_lands_beside_the_other_state(self):
        with mock.patch.object(
            startup_logging, "store_path", return_value=Path("/tmp/openemux-store")
        ) as store:
            path = get_startup_log_path()
        store.assert_called_once_with("runtime")
        self.assertEqual(path.name, "openemux_startup.log")

    def test_a_directory_that_cannot_be_created_falls_back_to_the_temp_dir(self):
        with TemporaryDirectory() as tmp_dir:
            real_mkdir = Path.mkdir
            refused = Path(tmp_dir) / "runtime"

            def _mkdir(self, *args, **kwargs):
                if self == refused:
                    raise OSError("read-only")
                return real_mkdir(self, *args, **kwargs)

            with mock.patch.object(Path, "mkdir", _mkdir):
                path = get_startup_log_path(runtime_dir=refused)

        self.assertEqual(path.parent.name, "openemux")
        self.assertEqual(path.name, "openemux_startup.log")

    def test_an_error_that_cannot_be_written_anywhere_goes_to_stderr(self):
        stderr = io.StringIO()
        with mock.patch.object(
            startup_logging, "get_startup_log_path", side_effect=OSError("read-only")
        ), contextlib.redirect_stderr(stderr):
            self.assertIsNone(
                append_startup_error("startup failed", exc_text="traceback line")
            )
        self.assertIn("startup failed", stderr.getvalue())
        self.assertIn("traceback line", stderr.getvalue())


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

    def test_a_log_file_that_cannot_be_opened_still_leaves_a_console(self):
        # A read-only runtime directory: the app starts, and everything it
        # logs still reaches the terminal.
        with TemporaryDirectory() as tmp_dir:
            with mock.patch.object(
                logging.handlers,
                "RotatingFileHandler",
                side_effect=OSError("read-only"),
            ):
                configure_startup_logging(runtime_dir=tmp_dir)
            self.assertFalse(
                any(
                    isinstance(handler, logging.handlers.RotatingFileHandler)
                    for handler in logging.getLogger().handlers
                )
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


class TheCrashHandlersTests(unittest.TestCase):
    """The difference between "segmentation fault" and knowing where."""

    def setUp(self):
        self._saved_excepthook = sys.excepthook
        self._saved_thread_excepthook = threading.excepthook
        self.addCleanup(setattr, sys, "excepthook", self._saved_excepthook)
        self.addCleanup(
            setattr, threading, "excepthook", self._saved_thread_excepthook
        )
        self.addCleanup(faulthandler.enable, sys.__stderr__, True)
        self.addCleanup(startup_logging._release_crash_log)

    def test_with_no_log_file_the_traces_still_go_to_the_terminal(self):
        startup_logging.install_crash_handlers()
        self.assertTrue(faulthandler.is_enabled())
        self.assertIsNone(startup_logging._crash_log_handle)

    def test_a_log_file_that_cannot_be_opened_is_not_fatal(self):
        with mock.patch("builtins.open", side_effect=OSError("read-only")):
            startup_logging.install_crash_handlers(Path("/nowhere/at/all.log"))
        self.assertTrue(faulthandler.is_enabled())
        self.assertIsNone(startup_logging._crash_log_handle)

    def test_an_uncaught_exception_is_written_to_the_log(self):
        startup_logging.install_crash_handlers()
        try:
            raise RuntimeError("boom")
        except RuntimeError:
            info = sys.exc_info()
        with self.assertLogs("openemux", level="CRITICAL") as caught:
            sys.excepthook(*info)
        self.assertIn("boom", "\n".join(caught.output))

    def test_ctrl_c_is_left_to_python_rather_than_logged_as_a_crash(self):
        startup_logging.install_crash_handlers()
        called = []
        with mock.patch.object(sys, "__excepthook__", lambda *a: called.append(a)):
            sys.excepthook(KeyboardInterrupt, KeyboardInterrupt(), None)
        self.assertEqual(len(called), 1)

    def test_a_thread_that_dies_reports_through_the_same_hook(self):
        startup_logging.install_crash_handlers()
        try:
            raise RuntimeError("boom in a worker")
        except RuntimeError:
            info = sys.exc_info()
        args = threading.ExceptHookArgs(
            [info[0], info[1], info[2], None]
        )
        with self.assertLogs("openemux", level="CRITICAL") as caught:
            threading.excepthook(args)
        self.assertIn("boom in a worker", "\n".join(caught.output))


if __name__ == "__main__":
    unittest.main()
