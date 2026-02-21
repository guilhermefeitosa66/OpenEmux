import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from opemux.core.startup_logging import append_startup_error, get_startup_log_path


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
            self.assertEqual(path, Path(tmp_dir) / "opemux_startup.log")


if __name__ == "__main__":
    unittest.main()
