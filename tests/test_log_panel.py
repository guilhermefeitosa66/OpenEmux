"""The log panel, its "Log" button and the "Report a Bug" dialog (issue #461).

Built on a real window (``tests.window_harness``): the panel lives in the
window's bottom bars and the button in its tip bar, and what is worth testing
is how the three stay in step.
"""

import logging
import unittest
import urllib.parse
from unittest import mock

from tests.gtk_display import HAVE_DISPLAY, needs_display
from tests.window_harness import WindowCase

if HAVE_DISPLAY:
    from gi.repository import Adw

    from openemux.core.log_buffer import LogBuffer, LogLine
    from openemux.ui import log_panel as panel_module
    from openemux.ui.log_panel import BugReportDialog, LogPanel, issue_url, report_text


def _line(level, text):
    return LogLine(level, f"2026-10-04 17:02:03,426 {logging.getLevelName(level)} [demo] {text}")


@needs_display
class _PanelCase(WindowCase):
    def setUp(self):
        super().setUp()
        self.buffer = LogBuffer()
        self.panel = LogPanel(self.win, buffer=self.buffer)

    def shown(self):
        text = self.panel.text
        return text.get_text(text.get_start_iter(), text.get_end_iter(), False)


@needs_display
class WhatThePanelShowsTests(_PanelCase):
    def test_lines_logged_before_it_was_built_are_there(self):
        buffer = LogBuffer()
        buffer.emit(logging.LogRecord("demo", logging.INFO, __file__, 1, "early", None, None))
        panel = LogPanel(self.win, buffer=buffer)
        text = panel.text
        self.assertIn("early", text.get_text(text.get_start_iter(), text.get_end_iter(), False))

    def test_a_line_shows_its_time_level_and_message(self):
        self.panel._append(_line(logging.WARNING, "careful"))
        self.panel._append(_line(logging.ERROR, "broken"))
        self.panel._append(_line(logging.INFO, "fine"))
        shown = self.shown()
        self.assertIn("17:02:03  WARNING [demo] careful", shown)
        self.assertIn("ERROR", shown)

    def test_a_line_of_another_shape_is_shown_whole(self):
        self.panel._append(LogLine(logging.INFO, "plain"), scroll=True)
        self.assertEqual(self.shown(), "plain\n")

    def test_a_line_from_any_thread_lands_on_the_main_loop(self):
        with mock.patch.object(panel_module.GLib, "idle_add") as idle_add:
            self.panel._on_line(_line(logging.INFO, "x"))
        self.assertEqual(idle_add.call_args[0][0], self.panel._append_from_idle)

    def test_closing_the_window_stops_listening(self):
        self.panel._on_close()
        self.assertNotIn(self.panel._on_line, self.buffer._listeners)


@needs_display
class TheErrorCountTests(_PanelCase):
    def test_an_error_with_the_panel_closed_shows_the_count(self):
        self.panel.set_open(False)
        self.buffer.errors_since_seen = 2
        self.panel._append_from_idle(_line(logging.ERROR, "boom"))
        self.assertTrue(self.win.log_badge.get_visible())
        self.assertEqual(self.win.log_badge.get_label(), "2")

    def test_an_error_with_the_panel_open_shows_no_count(self):
        self.panel.set_open(True)
        with mock.patch.object(self.win, "update_log_badge") as badge:
            self.panel._append_from_idle(_line(logging.ERROR, "boom"))
        badge.assert_not_called()

    def test_opening_the_panel_clears_the_count(self):
        self.buffer.errors_since_seen = 3
        self.panel.set_open(True)
        self.assertEqual(self.buffer.errors_since_seen, 0)
        self.assertFalse(self.win.log_badge.get_visible())

    def test_a_large_count_is_capped(self):
        self.win.update_log_badge(150)
        self.assertEqual(self.win.log_badge.get_label(), "99+")


@needs_display
class TheButtonsTests(_PanelCase):
    def test_clear_empties_the_view(self):
        self.panel._append(_line(logging.INFO, "x"))
        self.panel.clear()
        self.assertEqual(self.shown(), "")
        self.assertEqual(self.buffer.lines(), [])

    def test_copy_puts_the_report_on_the_clipboard_and_says_so(self):
        clipboard = mock.Mock()
        with mock.patch.object(self.win, "get_clipboard", return_value=clipboard), \
                mock.patch.object(panel_module.sysinfo, "retroarch", return_value="1.0 · /ra"):
            text = self.panel.copy_report()
        clipboard.set.assert_called_once_with(text)
        self.assertIn("### System", text)
        self.assertIn(self.said("log.copied"), self.toasts)


@needs_display
class TheWindowKeepsThemInStepTests(WindowCase):
    def test_the_bar_button_opens_the_panel_and_stores_it(self):
        self.win.log_toggle.set_active(True)
        self.assertTrue(self.win.log_panel.revealer.get_reveal_child())
        self.assertTrue(self.config.get_ui_settings()["show_log_panel"])

    def test_closing_from_the_panel_releases_the_button(self):
        self.win.set_log_panel_visible(True)
        self.win.set_log_panel_visible(False)
        self.assertFalse(self.win.log_toggle.get_active())
        self.assertFalse(self.config.get_ui_settings()["show_log_panel"])

    def test_the_startup_state_is_not_written_back(self):
        with mock.patch.object(self.config, "set_show_log_panel") as store:
            self.win.set_log_panel_visible(False, persist=False)
        store.assert_not_called()

    def test_report_a_bug_presents_the_dialog(self):
        with mock.patch.object(Adw.Dialog, "present") as present:
            self.win.activate_action("win.report-bug", None)
        present.assert_called_once()


@needs_display
class TheReportDialogTests(WindowCase):
    def setUp(self):
        super().setUp()
        self.buffer = LogBuffer()
        self.buffer.emit(logging.LogRecord("demo", logging.ERROR, __file__, 1, "boom", None, None))
        with mock.patch.object(panel_module.sysinfo, "retroarch", return_value="1.0 · /ra"):
            self.dialog = BugReportDialog(self.win, buffer=self.buffer)

    def test_copy_says_it_copied(self):
        clipboard = mock.Mock()
        with mock.patch.object(self.win, "get_clipboard", return_value=clipboard):
            self.dialog._on_copy(None)
        self.assertIn("boom", clipboard.set.call_args[0][0])
        self.assertEqual(self.dialog.copy_button.get_label(), self.said("report.copied"))
        self.assertTrue(self.dialog.copied_label.get_visible())

    def test_open_goes_to_the_prefilled_form(self):
        with mock.patch.object(self.win, "_open_uri") as open_uri:
            self.dialog._on_open(None)
        url = open_uri.call_args[0][0]
        self.assertTrue(url.startswith(panel_module.ISSUE_FORM_URL))

    def test_presenting_puts_the_focus_on_copy(self):
        with mock.patch.object(Adw.Dialog, "present"), \
                mock.patch.object(self.dialog.copy_button, "grab_focus") as focus:
            self.dialog.present()
        focus.assert_called_once()

    def test_a_launcher_that_cannot_resolve_still_gives_a_report(self):
        launcher = self.win.runtime_manager.retroarch_launcher
        with mock.patch.object(launcher, "_resolve_retroarch_binary", side_effect=RuntimeError), \
                mock.patch.object(panel_module.sysinfo, "retroarch", return_value="x") as ra:
            panel_module.collect_facts(self.win)
        self.assertIsNone(ra.call_args[0][0])


@needs_display
class TheReportTextTests(unittest.TestCase):
    def test_an_empty_log_says_so(self):
        text = report_text([("OpenEmux", "1.0")], [])
        self.assertIn("(the log is empty)", text)
        self.assertIn("### Log (last 0 lines)", text)

    def test_the_url_carries_the_template_label_version_and_system(self):
        url = issue_url([("OpenEmux", "x"), ("System", "Linux Mint 22.3")])
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        self.assertEqual(query["template"], ["bug_report.yml"])
        self.assertEqual(query["labels"], ["bug"])
        self.assertEqual(query["os"], ["Linux Mint 22.3"])
        self.assertIn("version", query)


if __name__ == "__main__":
    unittest.main()
