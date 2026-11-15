"""Big Picture's on-screen keyboard: search and text modes (issue 914)."""

import unittest

from tests.gtk_display import HAVE_DISPLAY, needs_display

if HAVE_DISPLAY:
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw

    Adw.init()

    gi.require_version("Graphene", "1.0")
    from gi.repository import Graphene, Gtk

    from openemux.ui.bigpicture.osk import (
        MODE_SEARCH,
        MODE_TEXT,
        ROWS_SEARCH,
        ROWS_TEXT,
        OnScreenKeyboard,
    )

from openemux.i18n import tr


def _t(key, **kwargs):
    return tr("en", key, **kwargs)


@needs_display
class SearchModeTests(unittest.TestCase):
    def test_every_key_lowercases_into_the_query(self):
        changes = []
        done = []
        osk = OnScreenKeyboard(_t, MODE_SEARCH, on_change=changes.append, on_done=done.append)
        self.assertEqual(osk.field_label.get_label(), _t("osk.empty"))
        self.assertFalse(osk.backspace_button.get_sensitive())
        osk.keys[20].emit("clicked")  # "A", first of the home row
        self.assertEqual(osk.text, "a")
        osk.space()
        osk.type_char("B")
        self.assertEqual(changes, ["a", "a ", "a b"])
        self.assertTrue(osk.backspace_button.get_sensitive())
        osk.backspace()
        self.assertEqual(osk.text, "a ")
        osk.clear()
        self.assertEqual(osk.text, "")
        osk.space()  # a leading space is never typed
        osk.backspace()
        osk.clear()
        self.assertEqual(changes, ["a", "a ", "a b", "a ", ""])
        osk.done()
        self.assertEqual(done, [""])
        self.assertEqual(osk.field_hint.get_label(), "")
        self.assertFalse(osk.toggle_shift())  # search has no shift

    def test_the_pad_shortcuts(self):
        done = []
        osk = OnScreenKeyboard(_t, MODE_SEARCH, on_done=done.append)
        osk.set_text("ab")
        self.assertTrue(osk.handle_action("context"))  # X: backspace
        self.assertEqual(osk.text, "a")
        self.assertTrue(osk.handle_action("favorite"))  # Y: space
        self.assertEqual(osk.text, "a ")
        self.assertTrue(osk.handle_action("search"))  # Start: done
        self.assertTrue(osk.handle_action("back"))  # B: done as well in search
        self.assertEqual(done, ["a ", "a "])
        self.assertFalse(osk.handle_action("range"))
        self.assertFalse(osk.handle_action("menu"))
        self.assertTrue(osk.focus_first_key() in (True, False))

    def test_quiet_callbacks(self):
        osk = OnScreenKeyboard(_t, MODE_SEARCH)
        osk.type_char("x")
        osk.done()
        osk.cancel()
        osk.keys = []
        self.assertFalse(osk.focus_first_key())


@needs_display
class TextModeTests(unittest.TestCase):
    def test_shift_capitalises_one_letter_and_the_limit_holds(self):
        done = []
        cancelled = []
        osk = OnScreenKeyboard(
            _t, MODE_TEXT, on_done=done.append, on_cancel=lambda: cancelled.append(1),
            title="Device name", subtitle="What others see", initial="Sala", max_length=6,
        )
        self.assertEqual(osk.text, "Sala")
        self.assertEqual(osk.field_hint.get_label(), _t("big_picture.osk.remaining", count=2))
        self.assertTrue(osk.toggle_shift())
        self.assertEqual(osk.letter_keys[0].get_label(), "Q")
        self.assertEqual(osk.shift_button.get_label(), _t("big_picture.osk.shift_on"))
        osk.type_char("b")
        self.assertEqual(osk.text, "SalaB")
        self.assertFalse(osk._shift)  # one capital, then back to lower case
        self.assertEqual(osk.letter_keys[0].get_label(), "q")
        osk.type_char("c")
        osk.type_char("d")  # over the limit: dropped
        self.assertEqual(osk.text, "SalaBc")
        self.assertTrue(osk.handle_action("range"))  # LT: shift
        self.assertTrue(osk._shift)
        osk.toggle_shift()
        osk.type_char("1")  # a digit never shifts
        self.assertEqual(osk.text, "SalaBc")
        osk.done()
        self.assertEqual(done, ["SalaBc"])
        self.assertTrue(osk.handle_action("back"))  # B: cancel in text mode
        self.assertEqual(cancelled, [1])
        osk.cancel_button.emit("clicked")
        self.assertEqual(cancelled, [1, 1])

    def test_a_password_is_masked(self):
        osk = OnScreenKeyboard(_t, MODE_TEXT, password=True, initial="abc", title="Password")
        self.assertEqual(osk.field_label.get_label(), "•••")
        osk.set_text("", notify=False)
        self.assertEqual(osk.field_label.get_label(), _t("osk.empty"))
        osk.set_text(None)
        self.assertEqual(osk.text, "")


#: The A-Z boards this layout replaced: nothing they could type may be lost.
_OLD_SEARCH = "1234567890ABCDEFGHIJKLMNOPQRSTUVWXYZ-.'&"
_OLD_TEXT = "1234567890-_@abcdefghijklmnopqrstuvwxyz.,:/!?'\"()&#+"


def _chars(osk):
    return "".join(key.osk_char for key in osk.keys)


@needs_display
class TheQwertyLayout(unittest.TestCase):
    """Issue 961: QWERTY, staggered, every old character still there."""

    def test_search_is_qwerty_and_keeps_every_character(self):
        osk = OnScreenKeyboard(_t, MODE_SEARCH)
        self.assertEqual(ROWS_SEARCH[1], "QWERTYUIOP")
        self.assertEqual(ROWS_SEARCH[2][:9], "ASDFGHJKL")
        self.assertEqual(ROWS_SEARCH[3][:7], "ZXCVBNM")
        self.assertEqual(sorted(_chars(osk)), sorted(_OLD_SEARCH))
        self.assertEqual([len(row) for row in osk.rows[:-1]], [10, 10, 10, 10])
        self.assertEqual(osk.rows[-1], osk.function_keys)
        self.assertEqual(osk.width, 23)

    def test_text_is_qwerty_and_keeps_every_character(self):
        osk = OnScreenKeyboard(_t, MODE_TEXT)
        self.assertEqual(ROWS_TEXT[1][:10], "qwertyuiop")
        self.assertEqual(ROWS_TEXT[2][:9], "asdfghjkl")
        self.assertEqual(ROWS_TEXT[3][:7], "zxcvbnm")
        self.assertEqual(sorted(_chars(osk)), sorted(_OLD_TEXT))
        self.assertEqual(osk.function_keys[0], osk.shift_button)
        self.assertEqual(osk.width, 29)

    def test_each_row_starts_half_a_key_right_of_the_one_above(self):
        osk = OnScreenKeyboard(_t, MODE_SEARCH)
        grid = osk.rows[0][0].get_parent()
        for row, keys in enumerate(osk.rows[:-1]):
            column, top, width, _height = grid.query_child(keys[0])
            self.assertEqual((column, top, width), (row, row, 2))
        self.assertEqual(grid.query_child(osk.rows[1][1])[0], 3)


@needs_display
class WalkingTheBoard(unittest.TestCase):
    """The D-pad over the staggered rows (issue 961)."""

    def setUp(self):
        self.window = Gtk.Window()
        self.osk = OnScreenKeyboard(_t, MODE_SEARCH)
        self.window.set_child(self.osk)
        self.addCleanup(self.window.destroy)
        self.focused = None
        for row in self.osk.rows:
            for key in row:
                key.grab_focus = lambda key=key: self._land(key)

    def _land(self, key):
        self.focused = key
        return True

    def key(self, char):
        return next(key for key in self.osk.keys if key.osk_char == char)

    def walk(self, start, *moves):
        focus = start
        for move in moves:
            self.assertTrue(self.osk.pad_move(move, focus))
            focus = self.focused
        return focus

    def test_down_takes_the_nearest_key_and_up_comes_back(self):
        self.assertIs(self.walk(self.key("Q"), "down"), self.key("A"))
        self.assertIs(self.walk(self.key("Q"), "down", "down"), self.key("Z"))
        self.assertIs(self.walk(self.key("W"), "down"), self.key("S"))
        self.assertIs(self.walk(self.key("S"), "up"), self.key("W"))
        self.assertIs(self.walk(self.key("1"), "down", "down", "up", "up"), self.key("1"))
        self.assertIs(self.walk(self.key("&"), "up"), self.key("'"))

    def test_left_and_right_wrap_inside_the_row(self):
        self.assertIs(self.walk(self.key("P"), "right"), self.key("Q"))
        self.assertIs(self.walk(self.key("Q"), "left"), self.key("P"))
        self.assertIs(self.walk(self.key("G"), "right"), self.key("H"))

    def test_the_top_row_holds_the_focus(self):
        self.assertTrue(self.osk.pad_move("up", self.key("5")))
        self.assertIsNone(self.focused)

    def test_the_function_row_is_the_last_row_of_the_walk(self):
        osk = self.osk
        osk.set_text("mario")  # Backspace and Clear can take the focus
        self.assertIs(self.walk(self.key("Z"), "down"), osk.space_button)
        self.assertIs(self.walk(self.key("M"), "down"), osk.clear_button)
        self.assertIs(self.walk(self.key("&"), "down"), osk.done_button)
        self.assertIs(self.walk(osk.clear_button, "up"), self.key("N"))
        self.assertIs(self.walk(osk.done_button, "right"), osk.space_button)
        self.focused = None
        self.assertTrue(osk.pad_move("down", osk.done_button))
        self.assertIsNone(self.focused)

    def test_grey_function_keys_are_stepped_over(self):
        osk = self.osk
        self.assertEqual(osk.text, "")  # Backspace and Clear are grey
        self.assertIs(self.walk(self.key("M"), "down"), osk.done_button)
        self.assertIs(self.walk(self.key("Z"), "down"), osk.space_button)
        self.assertIs(self.walk(osk.space_button, "right"), osk.done_button)
        self.assertIs(self.walk(osk.done_button, "left"), osk.space_button)
        for key in osk.function_keys:
            key.set_sensitive(False)
        self.focused = None
        self.assertTrue(osk.pad_move("down", self.key("M")))
        self.assertTrue(osk.pad_move("right", osk.space_button))
        self.assertIsNone(self.focused)

    def lay_out(self, row, spans):
        """Pretend the row is on screen: ``spans`` is each key's (left, right) in pixels."""
        for key, (left, right) in zip(self.osk.rows[row], spans):
            rect = Graphene.Rect().init(left, 0, right - left, 40)
            key.compute_bounds = lambda _other, rect=rect: (True, rect)
            key.get_width = lambda width=right - left: width

    def test_on_screen_the_function_row_is_walked_by_what_shows(self):
        # The search sheet at 1280x720: Space and Done stretch, the two
        # in the middle are narrow, so Done is what sits under "M".
        osk = self.osk
        osk.set_text("mario")
        self.lay_out(3, [(330 + 92 * i, 416 + 92 * i) for i in range(10)])
        self.assertIs(self.walk(self.key("M"), "down"), osk.clear_button)  # not laid out yet
        self.lay_out(4, [(189, 651), (661, 712), (722, 778), (788, 1243)])
        self.assertIs(self.walk(self.key("M"), "down"), osk.done_button)
        self.assertIs(self.walk(osk.done_button, "up"), self.key("-"))
        self.assertIs(self.walk(self.key("X"), "down"), osk.space_button)
        self.assertIs(self.walk(osk.backspace_button, "up"), self.key("V"))
        # Letter rows keep the grid's exact half keys, whatever is measured.
        self.assertIs(self.walk(self.key("S"), "down"), self.key("X"))
        # A key that cannot be measured against the board, or has no width
        # yet, is not laid out.
        osk.done_button.compute_bounds = lambda _other: (False, None)
        self.assertIs(self.walk(self.key("M"), "down"), osk.clear_button)
        osk.done_button.get_width = lambda: 0
        self.assertIs(self.walk(self.key("M"), "down"), osk.clear_button)

    def test_emptying_the_field_from_a_grey_key_keeps_the_focus_on_the_board(self):
        osk = self.osk
        osk.set_text("a")
        osk.clear_button.has_focus = lambda: True
        osk.clear()
        self.assertIs(self.focused, osk.space_button)
        self.assertFalse(osk.clear_button.get_sensitive())
        self.focused = None
        osk.set_text("ab")
        osk.backspace()  # text left: Backspace stays live and keeps the focus
        self.assertIsNone(self.focused)
        osk.clear_button.has_focus = lambda: False
        osk.backspace_button.has_focus = lambda: True
        osk.backspace()
        self.assertIs(self.focused, osk.space_button)

    def test_a_widget_it_does_not_own_is_left_alone(self):
        self.assertFalse(self.osk.pad_move("down", Gtk.Button()))
        self.assertFalse(self.osk.pad_move("down", None))
        self.assertFalse(self.osk.pad_move("sideways", self.key("Q")))
        self.assertIsNone(self.focused)


if __name__ == "__main__":
    unittest.main()
