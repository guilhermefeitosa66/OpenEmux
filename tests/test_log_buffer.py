"""The in-memory log the log panel and bug reports read (issue #461)."""

import logging
import unittest
from unittest import mock

from openemux.core.log_buffer import LogBuffer, LogLine


def _record(level, message):
    return logging.LogRecord("openemux.test", level, __file__, 1, message, None, None)


class TheLinesItKeepsTests(unittest.TestCase):
    def test_a_record_becomes_a_formatted_line(self):
        buffer = LogBuffer()
        buffer.emit(_record(logging.INFO, "hello"))
        (line,) = buffer.lines()
        self.assertIn("INFO [openemux.test] hello", line.text)
        self.assertFalse(line.is_error)

    def test_only_the_last_lines_are_kept(self):
        buffer = LogBuffer(max_lines=3)
        for index in range(5):
            buffer.emit(_record(logging.INFO, f"line {index}"))
        self.assertEqual([line.text[-6:] for line in buffer.lines()], ["line 2", "line 3", "line 4"])

    def test_the_tail_is_the_end_and_zero_means_everything(self):
        buffer = LogBuffer()
        for index in range(4):
            buffer.emit(_record(logging.INFO, f"line {index}"))
        self.assertEqual(len(buffer.tail(2)), 2)
        self.assertTrue(buffer.tail(2)[-1].text.endswith("line 3"))
        self.assertEqual(len(buffer.tail(0)), 4)

    def test_clear_empties_the_view_and_the_count(self):
        buffer = LogBuffer()
        buffer.emit(_record(logging.ERROR, "boom"))
        buffer.clear()
        self.assertEqual(buffer.lines(), [])
        self.assertEqual(buffer.errors_since_seen, 0)

    def test_a_record_that_cannot_be_formatted_never_raises(self):
        buffer = LogBuffer()
        bad = _record(logging.INFO, "%d")
        bad.args = ("not a number",)
        with mock.patch.object(buffer, "handleError") as handle:
            buffer.emit(bad)
        handle.assert_called_once()
        self.assertEqual(buffer.lines(), [])


class TheErrorCountTests(unittest.TestCase):
    def test_errors_are_counted_until_seen(self):
        buffer = LogBuffer()
        buffer.emit(_record(logging.ERROR, "one"))
        buffer.emit(_record(logging.WARNING, "not an error"))
        buffer.emit(_record(logging.CRITICAL, "two"))
        self.assertEqual(buffer.errors_since_seen, 2)
        buffer.mark_seen()
        self.assertEqual(buffer.errors_since_seen, 0)

    def test_a_line_knows_whether_it_is_an_error(self):
        self.assertTrue(LogLine(logging.ERROR, "x").is_error)
        self.assertFalse(LogLine(logging.WARNING, "x").is_error)


class ListenersTests(unittest.TestCase):
    def test_a_listener_hears_every_line_until_removed(self):
        buffer = LogBuffer()
        heard = []
        buffer.add_listener(heard.append)
        buffer.emit(_record(logging.INFO, "one"))
        buffer.remove_listener(heard.append)
        buffer.emit(_record(logging.INFO, "two"))
        self.assertEqual(len(heard), 1)

    def test_removing_a_stranger_is_harmless(self):
        LogBuffer().remove_listener(print)


if __name__ == "__main__":
    unittest.main()
