"""Big Picture's on-screen keyboard: search and text modes (issue 914)."""

import unittest

from tests.gtk_display import HAVE_DISPLAY, needs_display

if HAVE_DISPLAY:
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw

    Adw.init()

    from openemux.ui.bigpicture.osk import MODE_SEARCH, MODE_TEXT, OnScreenKeyboard

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
        osk.keys[10].emit("clicked")  # "A"
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
        self.assertEqual(osk.letter_keys[0].get_label(), "A")
        self.assertEqual(osk.shift_button.get_label(), _t("big_picture.osk.shift_on"))
        osk.type_char("b")
        self.assertEqual(osk.text, "SalaB")
        self.assertFalse(osk._shift)  # one capital, then back to lower case
        self.assertEqual(osk.letter_keys[0].get_label(), "a")
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


if __name__ == "__main__":
    unittest.main()
