"""tests/gtk_display.py: widget tests never draw on the developer's desktop (issue #528)."""

import io
import re
import unittest
from pathlib import Path
import unittest.mock
from unittest.mock import Mock

from tests import gtk_display

TESTS_DIR = Path(__file__).resolve().parent


class OnDeveloperDesktopTests(unittest.TestCase):
    def test_each_session_signal_is_a_desktop(self):
        for env in ({"WAYLAND_DISPLAY": "wayland-0"},
                    {"XDG_SESSION_TYPE": "x11"},
                    {"XDG_SESSION_TYPE": "wayland"},
                    {"XDG_CURRENT_DESKTOP": "GNOME"}):
            with self.subTest(env=env):
                self.assertTrue(gtk_display.on_developer_desktop(env, "linux"))

    def test_a_ci_like_environment_is_not(self):
        self.assertFalse(gtk_display.on_developer_desktop({}, "linux"))
        self.assertFalse(gtk_display.on_developer_desktop(
            {"DISPLAY": ":99", "XDG_SESSION_TYPE": "tty"}, "linux"))

    def test_the_opt_in_and_the_private_marker_are_not(self):
        desktop = {"WAYLAND_DISPLAY": "wayland-0", "XDG_SESSION_TYPE": "wayland"}
        for marker in ("OPENEMUX_TESTS_ON_DESKTOP", "OPENEMUX_TESTS_PRIVATE_DISPLAY"):
            with self.subTest(marker=marker):
                env = dict(desktop, **{marker: "1"})
                self.assertFalse(gtk_display.on_developer_desktop(env, "linux"))

    def test_other_platforms_are_left_alone(self):
        self.assertFalse(gtk_display.on_developer_desktop(
            {"WAYLAND_DISPLAY": "w"}, "win32"))

    def test_defaults_read_the_process(self):
        with unittest.mock.patch.dict(gtk_display.os.environ,
                                      {"OPENEMUX_TESTS_ON_DESKTOP": "1"}):
            self.assertFalse(gtk_display.on_developer_desktop())


class ProbeTests(unittest.TestCase):
    def test_a_refused_desktop_never_initialises_gtk(self):
        available = Mock(return_value=True)
        have, reason = gtk_display.probe({"XDG_SESSION_TYPE": "x11"}, "linux", available)
        self.assertFalse(have)
        available.assert_not_called()
        self.assertIn("make test", reason)
        self.assertIn("OPENEMUX_TESTS_ON_DESKTOP=1", reason)

    def test_no_display_keeps_the_old_reason(self):
        self.assertEqual(gtk_display.probe({}, "linux", lambda: False),
                         (False, gtk_display.NO_DISPLAY_REASON))

    def test_a_private_display_builds_widgets(self):
        self.assertEqual(gtk_display.probe({}, "linux", lambda: True), (True, ""))


class AnnounceTests(unittest.TestCase):
    def test_a_refused_desktop_is_explained(self):
        stream = io.StringIO()
        gtk_display.announce(gtk_display.DESKTOP_REASON, stream)
        self.assertEqual(stream.getvalue(), gtk_display.DESKTOP_NOTE)
        self.assertIn("make test", stream.getvalue())

    def test_anything_else_is_silent(self):
        for reason in ("", gtk_display.NO_DISPLAY_REASON):
            stream = io.StringIO()
            gtk_display.announce(reason, stream)
            self.assertEqual(stream.getvalue(), "")

    def test_the_default_stream_is_stderr(self):
        stream = io.StringIO()
        with unittest.mock.patch.object(gtk_display.sys, "stderr", stream):
            gtk_display.announce(gtk_display.DESKTOP_REASON)
        self.assertEqual(stream.getvalue(), gtk_display.DESKTOP_NOTE)


class EveryWindowGoesThroughTheGuardTests(unittest.TestCase):
    """A widget test outside gtk_display would still draw on a bare run."""

    BUILDS_WINDOWS = re.compile(
        # Any Gtk/Adw window or dialog constructor, but not one quoted in a string.
        r"\.present\(|(?<![\"'])(?:Gtk|Adw)\.\w*(?:Window|Dialog)\(")

    def test_files_that_build_windows_import_the_guard(self):
        unguarded = [
            path.name for path in sorted(TESTS_DIR.glob("test_*.py"))
            if path.name != Path(__file__).name
            and self.BUILDS_WINDOWS.search(path.read_text(encoding="utf-8"))
            and "tests.gtk_display" not in path.read_text(encoding="utf-8")
        ]
        self.assertEqual(unguarded, [])

    def test_the_scan_still_finds_window_builders(self):
        builders = [
            path for path in TESTS_DIR.glob("test_*.py")
            if self.BUILDS_WINDOWS.search(path.read_text(encoding="utf-8"))
        ]
        self.assertTrue(builders, "the pattern no longer matches anything")


if __name__ == "__main__":
    unittest.main()
