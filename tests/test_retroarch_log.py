"""Reading a running RetroArch's log to learn which display server it took.

The game window can only adopt an X11 window, and on Wayland none will ever
appear -- so waiting the full twenty-second search budget is twenty seconds
of black screen for an answer RetroArch already gave (issue #267).
"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from openemux.core import retroarch_log

#: A real, *successful* X11 run. RetroArch probes wayland first and says so
#: loudly when it fails -- searching the log for "wayland" would abandon a
#: perfectly good embed, which is the whole reason this module parses instead
#: of matching substrings.
X11_LOG_WITH_WAYLAND_ERROR = """\
[INFO] [Environ]: SYSTEM_DIRECTORY: "/home/u/.openemux/bios/SFC".
[ERROR] [Wayland]: Failed to connect to Wayland server.
[INFO] [GL] Found GL context: "x".
[INFO] [Video] Found display server: "x11".
[INFO] [GL]: Vendor: AMD, Renderer: AMD Radeon Graphics.
"""

WAYLAND_LOG = """\
[INFO] [Environ]: SYSTEM_DIRECTORY: "/home/u/.openemux/bios/SFC".
[INFO] [Video] Found display server: "wayland".
[INFO] [GL] Found GL context: "wayland".
"""


class VerdictTests(unittest.TestCase):
    def test_a_wayland_probe_failure_does_not_condemn_an_x11_run(self):
        # The regression this module exists for.
        self.assertEqual(
            retroarch_log.verdict(X11_LOG_WITH_WAYLAND_ERROR), retroarch_log.X11
        )

    def test_a_real_wayland_run_is_recognized(self):
        self.assertEqual(retroarch_log.verdict(WAYLAND_LOG), retroarch_log.NOT_X11)

    def test_the_gl_context_alone_is_enough(self):
        # "x" is the registered ident; "x11" is not, despite reading like one.
        self.assertEqual(
            retroarch_log.verdict('[INFO] [GL] Found GL context: "x".'),
            retroarch_log.X11,
        )
        self.assertEqual(
            retroarch_log.verdict('[INFO] [GL] Found GL context: "wayland".'),
            retroarch_log.NOT_X11,
        )

    def test_nothing_said_yet_is_not_an_answer(self):
        # A slow core load must read as "keep waiting", never as a failure.
        for text in ("", None, "[INFO] [Core]: Loading dynamic libretro core"):
            self.assertEqual(retroarch_log.verdict(text), retroarch_log.UNKNOWN, text)

    def test_a_half_written_line_is_not_an_answer(self):
        # The file is being appended to by another process as we read it.
        self.assertEqual(
            retroarch_log.verdict('[INFO] [Video] Found display serv'),
            retroarch_log.UNKNOWN,
        )
        self.assertEqual(
            retroarch_log.verdict('[INFO] [Video] Found display server: "way'),
            retroarch_log.UNKNOWN,
        )

    def test_an_unknown_backend_name_waits_rather_than_guessing(self):
        # A future RetroArch naming something new must degrade to waiting.
        self.assertEqual(
            retroarch_log.verdict('[INFO] [Video] Found display server: "mir".'),
            retroarch_log.UNKNOWN,
        )


class ReadVerdictTests(unittest.TestCase):
    def test_reads_a_file(self):
        with TemporaryDirectory() as tmp_dir:
            log = Path(tmp_dir) / "retroarch_sfc.log"
            log.write_text(WAYLAND_LOG, encoding="utf-8")
            self.assertEqual(retroarch_log.read_verdict(log), retroarch_log.NOT_X11)

    def test_undecodable_bytes_do_not_raise(self):
        with TemporaryDirectory() as tmp_dir:
            log = Path(tmp_dir) / "retroarch_sfc.log"
            log.write_bytes(b'\xff\xfe garbage\n[INFO] [GL] Found GL context: "x".\n')
            self.assertEqual(retroarch_log.read_verdict(log), retroarch_log.X11)

    def test_a_missing_or_unnamed_log_is_unknown(self):
        self.assertEqual(retroarch_log.read_verdict(None), retroarch_log.UNKNOWN)
        with TemporaryDirectory() as tmp_dir:
            missing = Path(tmp_dir) / "nope.log"
            self.assertEqual(retroarch_log.read_verdict(missing), retroarch_log.UNKNOWN)

    def test_only_the_head_of_a_huge_log_is_read(self):
        # The log grows for the whole session; the lines we want are first.
        with TemporaryDirectory() as tmp_dir:
            log = Path(tmp_dir) / "retroarch_sfc.log"
            log.write_text(
                WAYLAND_LOG + ("[INFO] noise\n" * 200_000), encoding="utf-8"
            )
            self.assertEqual(retroarch_log.read_verdict(log), retroarch_log.NOT_X11)


class ShouldAbandonTests(unittest.TestCase):
    def test_a_non_x11_retroarch_is_hopeless_immediately(self):
        # No window will ever appear; waiting out the budget is 20 s of black.
        self.assertTrue(
            retroarch_log.should_abandon(retroarch_log.NOT_X11, 1, 100)
        )

    def test_an_unanswered_log_waits_out_the_budget(self):
        self.assertFalse(retroarch_log.should_abandon(retroarch_log.UNKNOWN, 99, 100))
        self.assertTrue(retroarch_log.should_abandon(retroarch_log.UNKNOWN, 101, 100))

    def test_a_confirmed_x11_retroarch_still_gets_its_whole_budget(self):
        # It is an X client; the window is just slow. That is what the
        # budget is for.
        self.assertFalse(retroarch_log.should_abandon(retroarch_log.X11, 99, 100))


if __name__ == "__main__":
    unittest.main()
