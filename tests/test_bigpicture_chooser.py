"""The two pages every settings row borrows: a list to pick from, a keyboard.

Both are single instances the shell reuses, so what matters is that
``open`` resets them, that A picks exactly once and pops, and that B (or
Cancel) pops without handing anything back.
"""

# Builds real windows through tests.window_harness (via BigPictureCase): CI runs this
# module in the windowed process, with the other window tests.

import unittest

from tests.bigpicture_harness import BigPictureCase
from tests.gtk_display import HAVE_DISPLAY, needs_display

if HAVE_DISPLAY:
    from openemux.ui.bigpicture import chooser as chooser_module


OPTIONS = [
    {"id": "a", "label": "Alpha"},
    {"id": "b", "label": "Beta", "subtitle": "The second one"},
    {"id": "c", "label": "Gamma"},
]


@needs_display
class TheChooserPage(BigPictureCase):
    def test_the_current_option_is_marked_and_focused_and_a_picks_once(self):
        self.show()
        picked = []
        page = self.shell.open_chooser(
            "Pick one", OPTIONS, "b", picked.append, crumbs=["Settings", "Pick one"], lead="Which?"
        )
        self.pump()
        self.assertIs(self.visible_page(), page)
        self.assertIs(page, self.shell._chooser)
        self.assertEqual(page.get_tag(), "bp-chooser")
        self.assertEqual([row.option_id for row in page.rows], ["a", "b", "c"])
        self.assertEqual(page.rows[1].mark.get_label(), chooser_module.MARK_CURRENT)
        self.assertEqual(page.rows[0].mark.get_label(), chooser_module.MARK_OTHER)
        self.assertTrue(page.rows[1].has_css_class("bp-current"))
        self.assertFalse(page.rows[0].has_css_class("bp-current"))
        self.assertTrue(page.rows[0].has_css_class("bp-row"))
        self.assertTrue(page.lead_label.get_visible())
        self.assertEqual(page.lead_label.get_label(), "Which?")
        self.assertIs(self.focus_widget(), page.rows[1])
        glyphs = self.win.navigation.glyphs()
        hints = page.hints(glyphs, self.win.t)
        self.assertEqual(hints[0], (glyphs["confirm"], self.said("big_picture.hints.pick")))
        self.assertEqual(hints[1], (glyphs["back"], self.said("big_picture.hints.keep")))

        page.rows[2].emit("clicked")
        self.pump()
        self.assertEqual(picked, ["c"])
        self.assertIs(self.visible_page(), self.shell.home)
        # A second A before the pop lands picks nothing and pops nothing.
        page.rows[2].emit("clicked")
        self.pump()
        self.assertEqual(picked, ["c"])
        self.assertIs(self.visible_page(), self.shell.home)

    def test_b_keeps_what_was_there(self):
        self.show()
        picked = []
        page = self.shell.open_chooser("Pick one", OPTIONS, "a", picked.append)
        self.pump()
        self.assertFalse(page.lead_label.get_visible())
        self.assertEqual(page.get_title(), "Pick one")
        self.press("back")
        self.assertEqual(picked, [])
        self.assertIs(self.visible_page(), self.shell.home)

    def test_reopening_resets_the_list_and_an_unknown_current_lands_on_the_first_row(self):
        self.show()
        page = self.shell.open_chooser("One", OPTIONS, "c", lambda _id: None, lead="x")
        self.pump()
        self.shell.pop()
        self.pump()
        self.assertIs(self.shell.open_chooser("Two", OPTIONS[:2], "zzz", lambda _id: None), page)
        self.pump()
        self.assertEqual(len(page.rows), 2)
        self.assertFalse(page.lead_label.get_visible())
        self.assertIs(page.current_row(), page.rows[0])
        self.assertIs(self.focus_widget(), page.rows[0])
        self.shell.pop()
        self.pump()
        page.open("Empty", [], None, lambda _id: None)
        self.assertIsNone(page.current_row())
        self.assertFalse(page.focus_default())


@needs_display
class TheTextEntryPage(BigPictureCase):
    def test_done_hands_the_text_back_and_pops(self):
        self.show()
        done = []
        page = self.shell.open_text_entry(
            "Name", "abc", done.append, subtitle="Shown to others", crumbs=["Settings", "Name"]
        )
        self.pump()
        self.assertIs(page, self.shell._text_entry)
        self.assertEqual(page.get_tag(), "bp-text")
        self.assertEqual(page.osk.text, "abc")
        self.assertEqual(page.osk.mode, chooser_module.MODE_TEXT)
        self.assertFalse(page.osk.password)
        self.assertIs(self.focus_widget(), page.osk.keys[0])
        # X and Y reach the keyboard through the navigator.
        self.press("context")
        self.assertEqual(page.osk.text, "ab")
        page.osk.type_char("x")
        self.press("favorite")
        self.assertEqual(page.osk.text, "abx ")
        glyphs = self.win.navigation.glyphs()
        hints = page.hints(glyphs, self.win.t)
        self.assertEqual(hints[0], (glyphs["confirm"], self.said("big_picture.hints.type")))
        self.assertEqual(hints[3], (glyphs["range"], self.said("big_picture.settings.hints.shift")))
        self.assertEqual(hints[-1], (glyphs["back"], self.said("big_picture.osk.cancel")))

        page.osk.done()
        self.pump()
        self.assertEqual(done, ["abx "])
        self.assertIs(self.visible_page(), self.shell.home)
        # The page is gone: nothing more is handed back.
        page.osk.done()
        self.assertEqual(done, ["abx "])

    def test_cancel_and_b_hand_nothing_back_and_reopening_starts_fresh(self):
        self.show()
        done = []
        page = self.shell.open_text_entry("Password", "", done.append, password=True, max_length=8)
        self.pump()
        self.assertTrue(page.osk.password)
        self.assertEqual(page.osk.max_length, 8)
        first = page.osk
        page.osk.type_char("a")
        page.osk.cancel()
        self.pump()
        self.assertEqual(done, [])
        self.assertIs(self.visible_page(), self.shell.home)
        page.osk.cancel()  # already popped: nothing happens
        self.assertIs(self.visible_page(), self.shell.home)

        self.shell.open_text_entry("Name", "q", done.append)
        self.pump()
        self.assertIsNot(page.osk, first)
        self.assertEqual(page.osk.text, "q")
        self.assertIs(self.visible_page(), page)
        self.press("back")
        self.assertEqual(done, [])
        self.assertIs(self.visible_page(), self.shell.home)


if __name__ == "__main__":
    unittest.main()
