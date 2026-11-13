"""The on-screen keyboard over the search box (issue 914)."""

import unittest
from unittest import mock

from tests.gtk_display import HAVE_DISPLAY, needs_display
from tests.window_harness import WindowCase

if HAVE_DISPLAY:
    from openemux.ui.onscreen_keyboard import ROWS, OnScreenKeyboard


@needs_display
class TypingWithThePadTests(WindowCase):
    def setUp(self):
        super().setUp()
        self.win.sidebar.select("SFC")
        self.osk = OnScreenKeyboard(self.win)
        self.addCleanup(self.osk.force_close)

    def _press(self, char):
        key = next(k for k in self.osk.keys if k.get_label() == char)
        key.emit("clicked")

    def test_every_letter_and_digit_has_a_key(self):
        labels = {k.get_label() for k in self.osk.keys}
        self.assertEqual(labels, set("".join(ROWS)))

    def test_letters_go_into_the_search_box_as_they_are_pressed(self):
        self.assertEqual(self.osk.query_label.get_label(), self.said("osk.empty"))
        self._press("M")
        self._press("E")
        self.assertEqual(self.win.search_entry.get_text(), "me")
        self.assertEqual(self.osk.query_label.get_label(), "me")
        self.assertTrue(self.win.search_button.get_active())
        self.osk.space_button.emit("clicked")
        self.assertEqual(self.win.search_entry.get_text(), "me ")

    def test_backspace_and_clear_take_letters_back(self):
        self._press("A")
        self._press("B")
        self.osk.backspace_button.emit("clicked")
        self.assertEqual(self.win.search_entry.get_text(), "a")
        self.osk.clear_button.emit("clicked")
        self.assertEqual(self.win.search_entry.get_text(), "")
        self.assertFalse(self.osk.backspace_button.get_sensitive())

    def test_done_closes_and_lands_on_the_first_match(self):
        self._press("M")
        grid = self.win.pages.grid_for("SFC")
        with mock.patch.object(grid, "focus_first_card") as focus, mock.patch.object(
            self.osk, "close", side_effect=lambda: self.osk.emit("closed")
        ):
            self.osk.done_button.emit("clicked")
        focus.assert_called_once()

    def test_closing_with_nothing_matching_moves_no_focus(self):
        self.win.search_entry.set_text("nothing matches this")
        self.win.apply_library_filters()
        grid = self.win.pages.grid_for("SFC")
        with mock.patch.object(grid, "focus_first_card") as focus:
            self.osk.emit("closed")
        focus.assert_not_called()


if __name__ == "__main__":
    unittest.main()
