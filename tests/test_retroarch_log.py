"""Reading a finished RetroArch log to say why a launch died (issues #226, #248)."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from openemux.core.retroarch_log import (
    failure_reason,
    is_fuse_failure,
    read_failure_reason,
    read_is_fuse_failure,
)

class FailureReasonTests(unittest.TestCase):
    """Why a launch died, out of the log it left behind (issue #226)."""

    def test_the_missing_libfuse_case_is_explained_in_words(self):
        # The raw dlopen line means nothing to a user; the sentence does.
        reason = failure_reason("dlopen(): error loading libfuse.so.2\n")
        self.assertIn("libfuse2", reason)
        self.assertNotIn("dlopen", reason)

    def test_the_appimage_runtimes_own_wording_is_recognised_too(self):
        reason = failure_reason("AppImages require FUSE to run.\n")
        self.assertIn("libfuse2", reason)

    def test_a_healthy_x11_run_has_no_reason_to_report(self):
        # The trap this module exists for: a good run logs a Wayland error on
        # its way to X11. That must never be reported as a failure.
        healthy = (
            '[ERROR] [Wayland]: Failed to connect to Wayland server.\n'
            '[INFO] [GL] Found GL context: "x".\n'
            "[INFO] [Video]: Started video\n"
        )
        self.assertIsNone(failure_reason(healthy))

    def test_a_real_error_line_is_reported_verbatim(self):
        reason = failure_reason("[INFO] fine\n[ERROR] Failed to open libretro core: /x/y.so\n")
        self.assertEqual(reason, "[ERROR] Failed to open libretro core: /x/y.so")

    def test_the_last_error_wins_over_an_earlier_one(self):
        reason = failure_reason("[ERROR] first thing\n[ERROR] the thing that killed it\n")
        self.assertEqual(reason, "[ERROR] the thing that killed it")

    def test_an_empty_log_says_nothing(self):
        self.assertIsNone(failure_reason(""))
        self.assertIsNone(failure_reason(None))

    def test_a_very_long_line_is_trimmed(self):
        reason = failure_reason("[ERROR] " + "x" * 500)
        self.assertLessEqual(len(reason), 200)


class FuseFailureTests(unittest.TestCase):
    """Which deaths are worth a second, unpacked attempt (issue #248)."""

    def test_the_loader_wording_counts(self):
        self.assertTrue(is_fuse_failure("dlopen(): error loading libfuse.so.2"))

    def test_the_runtimes_own_wording_counts(self):
        self.assertTrue(is_fuse_failure("AppImages require FUSE to run."))
        self.assertTrue(
            is_fuse_failure("Cannot mount AppImage, please check your FUSE setup.")
        )

    def test_a_kernel_without_dev_fuse_counts(self):
        # libfuse2 loads fine here -- the probe says yes and the mount still
        # fails, which is the whole reason the retry exists.
        self.assertTrue(is_fuse_failure("fuse: device not found, try 'modprobe fuse' first"))

    def test_a_missing_fusermount_counts(self):
        self.assertTrue(is_fuse_failure("fusermount3: not found"))

    def test_an_ordinary_failure_is_not_a_mount_failure(self):
        self.assertFalse(
            is_fuse_failure("[ERROR] Failed to open libretro core: no such file")
        )

    def test_a_healthy_log_is_not_a_mount_failure(self):
        self.assertFalse(is_fuse_failure('[INFO] [Video]: Found display server: "x11".'))

    def test_no_log_is_not_a_reason_to_retry(self):
        self.assertFalse(is_fuse_failure(""))
        self.assertFalse(is_fuse_failure(None))


class ReadIsFuseFailureTests(unittest.TestCase):
    def test_it_reads_the_tail_of_a_finished_log(self):
        with TemporaryDirectory() as tmp_dir:
            log_path = Path(tmp_dir) / "launch.log"
            log_path.write_text(
                "[INFO] noise\n" * 5000 + "AppImages require FUSE to run.\n",
                encoding="utf-8",
            )
            self.assertTrue(read_is_fuse_failure(log_path))

    def test_an_unreadable_log_is_not_a_reason_to_retry(self):
        with TemporaryDirectory() as tmp_dir:
            self.assertFalse(read_is_fuse_failure(Path(tmp_dir) / "gone.log"))
        self.assertFalse(read_is_fuse_failure(None))


class ReadFailureReasonTests(unittest.TestCase):
    def test_it_reads_the_tail_of_a_file(self):
        with TemporaryDirectory() as tmp_dir:
            log_path = Path(tmp_dir) / "launch.log"
            log_path.write_text(
                "[INFO] noise\n" * 5000 + "dlopen(): error loading libfuse.so.2\n",
                encoding="utf-8",
            )
            self.assertIn("libfuse2", read_failure_reason(log_path))

    def test_a_missing_log_is_not_an_error(self):
        with TemporaryDirectory() as tmp_dir:
            self.assertIsNone(read_failure_reason(Path(tmp_dir) / "nope.log"))
        self.assertIsNone(read_failure_reason(None))


if __name__ == "__main__":
    unittest.main()
