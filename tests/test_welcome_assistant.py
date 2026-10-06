"""The onboarding tour, built and stepped through.

`tests/test_welcome_keys.py` covers the one decision that could be made
without a dialog -- whether the arrow keys belong to the carousel or to an open
popup (issue #259). The rest of `ui/welcome.py` needs the real thing: the
carousel, the topic list beside it, the language picker that has to change the
whole assistant, and the slideshow timer that must only run for the slide on
screen.

Built against the real window, so the language change goes through the window
that owns the locale, exactly as it does in the app.
"""

import unittest
from unittest import mock

from tests.gtk_display import HAVE_DISPLAY, needs_display
from tests.window_harness import WindowCase

if HAVE_DISPLAY:
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Gdk, Gtk

    from openemux.ui import welcome as welcome_module
    from openemux.ui.welcome import SLIDES, WelcomeAssistant


class _WelcomeCase(WindowCase):
    def setUp(self):
        super().setUp()
        self.assistant = WelcomeAssistant(self.win)
        self.addCleanup(self.assistant.force_close)

    def slide_on_screen(self):
        """Which slide the tour is showing, read off the topic list.

        The carousel animates, and the dialog is never presented here, so its
        own position stays where it started; the topic selection is what
        `_select_index` sets there and then.
        """
        row = self.assistant.topics.get_selected_row()
        return row.get_index() if row is not None else None

    def standing_on(self, index):
        """Report the tour as being on ``index``, whatever the animation did."""
        patcher = mock.patch.object(
            self.assistant, "_current_index", return_value=index
        )
        patcher.start()
        self.addCleanup(patcher.stop)


@needs_display
class TheTourIsBuiltFromItsSlidesTests(_WelcomeCase):
    def test_every_slide_gets_a_page_and_a_topic_row(self):
        self.assertEqual(self.assistant.carousel.get_n_pages(), len(SLIDES))
        rows = 0
        row = self.assistant.topics.get_first_child()
        while row is not None:
            rows += 1
            row = row.get_next_sibling()
        self.assertEqual(rows, len(SLIDES))

    def test_it_opens_on_the_first_slide(self):
        self.assertEqual(self.slide_on_screen(), 0)
        self.assertFalse(self.assistant.back_button.get_sensitive())

    def test_an_image_the_build_does_not_ship_is_simply_not_drawn(self):
        self.assertIsNone(self.assistant._picture("not-an-image.png"))

    def test_an_image_that_is_there_is_drawn(self):
        existing = next(
            (path.name for path in welcome_module._IMAGE_DIR.glob("*.png")), None
        )
        if existing is None:
            self.skipTest("this build ships no welcome images")
        self.assertIsNotNone(self.assistant._picture(existing))


@needs_display
class SteppingThroughTheTourTests(_WelcomeCase):
    def test_next_moves_one_slide_on(self):
        self.assistant._on_next(None)
        self.assertEqual(self.slide_on_screen(), 1)
        self.assertTrue(self.assistant.back_button.get_sensitive())

    def test_the_last_slide_finishes_rather_than_going_further(self):
        self.assistant._select_index(len(SLIDES) - 1)
        self.assertEqual(
            self.assistant.next_button.get_label(), self.said("welcome.finish")
        )
        self.standing_on(len(SLIDES) - 1)
        with mock.patch.object(self.assistant, "close") as close:
            self.assistant._on_next(None)
        close.assert_called_once()

    def test_a_step_past_either_end_stops_at_it(self):
        self.assistant._step(-5)
        self.assertEqual(self.slide_on_screen(), 0)
        self.assistant._step(len(SLIDES) + 5)
        self.assertEqual(self.slide_on_screen(), len(SLIDES) - 1)

    def test_picking_a_topic_moves_the_carousel_to_it(self):
        row = self.assistant.topics.get_row_at_index(2)
        self.assistant._on_topic_selected(self.assistant.topics, row)
        self.assertEqual(self.slide_on_screen(), 2)

    def test_a_topic_selection_the_carousel_caused_is_not_acted_on_twice(self):
        self.assistant._syncing = True
        with mock.patch.object(self.assistant, "_select_index") as select:
            self.assistant._on_topic_selected(
                self.assistant.topics, self.assistant.topics.get_row_at_index(1)
            )
        select.assert_not_called()
        self.assistant._syncing = False

    def test_an_empty_topic_selection_does_nothing(self):
        with mock.patch.object(self.assistant, "_select_index") as select:
            self.assistant._on_topic_selected(self.assistant.topics, None)
        select.assert_not_called()

    def test_swiping_the_carousel_moves_the_topic_list_with_it(self):
        self.assistant._on_page_changed(self.assistant.carousel, 2)
        self.assertEqual(
            self.assistant.topics.get_selected_row().get_index(), 2
        )

    def test_a_page_change_the_topic_list_caused_is_not_acted_on_twice(self):
        self.assistant._syncing = True
        with mock.patch.object(self.assistant, "_update_controls") as update:
            self.assistant._on_page_changed(self.assistant.carousel, 1)
        update.assert_not_called()
        self.assistant._syncing = False


@needs_display
class TheArrowKeysTests(_WelcomeCase):
    def press(self, keyval):
        return self.assistant._on_key(None, keyval, 0, 0)

    def test_right_and_page_down_step_forward(self):
        self.assertTrue(self.press(Gdk.KEY_Right))
        self.assertEqual(self.slide_on_screen(), 1)
        self.standing_on(1)
        self.assertTrue(self.press(Gdk.KEY_Page_Down))
        self.assertEqual(self.slide_on_screen(), 2)

    def test_left_and_page_up_step_back(self):
        self.standing_on(2)
        self.assertTrue(self.press(Gdk.KEY_Left))
        self.assertEqual(self.slide_on_screen(), 1)
        self.assertTrue(self.press(Gdk.KEY_Page_Up))
        self.assertEqual(self.slide_on_screen(), 1)

    def test_any_other_key_is_left_to_the_dialog(self):
        self.assertFalse(self.press(Gdk.KEY_a))

    def test_no_key_reaches_the_carousel_while_a_popup_is_open(self):
        # Issue #259: the language dropdown's list handles Up/Down but not
        # Left/Right, so those bubbled up and flipped the slide behind it.
        with mock.patch.object(
            self.assistant, "_arrows_step_slides", return_value=False
        ):
            self.assertFalse(self.press(Gdk.KEY_Right))
        self.assertEqual(self.slide_on_screen(), 0)


@needs_display
class TheLanguagePickerTests(_WelcomeCase):
    """Someone who cannot read the first slide cannot find Settings either."""

    def test_it_opens_on_the_locale_the_app_is_running(self):
        self.assertEqual(
            self.assistant._locales[self.assistant._language_row.get_selected()],
            "en",
        )

    def test_seeding_the_picker_never_changes_the_language(self):
        # Without the guard the dialog "changes" the language to whatever it
        # already was the moment it opens, toast and all.
        with mock.patch.object(self.win, "_apply_language_change") as apply_change:
            WelcomeAssistant(self.win).force_close()
        apply_change.assert_not_called()

    def test_choosing_another_language_retranslates_the_whole_assistant(self):
        index = self.assistant._locales.index("pt_BR")
        with mock.patch.object(self.win, "refresh_library"):
            self.assistant._language_row.set_selected(index)
        self.assertEqual(self.win.locale, "pt_BR")
        self.assertEqual(self.assistant.get_title(), self.win.t("welcome.title"))

    def test_choosing_the_language_already_running_changes_nothing(self):
        with mock.patch.object(self.win, "_apply_language_change") as apply_change:
            self.assistant._on_language_selected()
        apply_change.assert_not_called()

    def test_a_selection_while_syncing_is_ignored(self):
        self.assistant._syncing = True
        with mock.patch.object(self.win, "_apply_language_change") as apply_change:
            self.assistant._on_language_selected()
        self.assistant._syncing = False
        apply_change.assert_not_called()

    def test_an_impossible_selection_index_changes_nothing(self):
        with mock.patch.object(
            self.assistant._language_row, "get_selected", return_value=999
        ), mock.patch.object(self.win, "_apply_language_change") as apply_change:
            self.assistant._on_language_selected()
        apply_change.assert_not_called()


@needs_display
class TheSlideshowTimerTests(_WelcomeCase):
    """A multi-image slide cycles, but only while it is the one on screen."""

    def _multi_image_slide(self):
        for slide_id, entry in self.assistant._slideshows.items():
            if entry[1] > 1:
                return slide_id, entry
        return None, None

    def test_a_slide_with_several_images_cycles_through_them(self):
        slide_id, entry = self._multi_image_slide()
        if slide_id is None:
            self.skipTest("this build ships no multi-image slide")
        stack, _count = entry
        with mock.patch.object(
            welcome_module.GLib, "timeout_add", return_value=7
        ) as timeout:
            self.assistant._start_slideshow(slide_id)
        # 7 is not a source anybody registered; leaving it on the assistant
        # would have its teardown hand it to the real GLib.source_remove.
        self.addCleanup(setattr, self.assistant, "_slideshow_timer", None)
        advance = timeout.call_args[0][1]
        first = stack.get_visible_child_name()
        self.assertTrue(advance())
        self.assertNotEqual(stack.get_visible_child_name(), first)

    def test_a_slide_with_one_image_starts_no_timer(self):
        with mock.patch.object(welcome_module.GLib, "timeout_add") as timeout:
            self.assistant._start_slideshow("not-a-slide")
        timeout.assert_not_called()

    def test_moving_to_another_slide_stops_the_previous_timer(self):
        self.assistant._slideshow_timer = 7
        with mock.patch.object(welcome_module.GLib, "source_remove") as remove:
            self.assistant._stop_slideshow()
        remove.assert_called_once_with(7)
        self.assertIsNone(self.assistant._slideshow_timer)

    def test_stopping_a_timer_that_is_not_running_is_harmless(self):
        self.assistant._slideshow_timer = None
        self.assistant._stop_slideshow()


@needs_display
class TheStartupCheckboxTests(_WelcomeCase):
    def test_unticking_it_keeps_the_tour_away_next_launch(self):
        check = Gtk.CheckButton()
        check.set_active(False)
        self.assistant._on_show_startup_toggled(check)
        self.assertFalse(self.config.get_show_welcome_on_startup())

    def test_ticking_it_brings_the_tour_back(self):
        check = Gtk.CheckButton()
        check.set_active(True)
        self.assistant._on_show_startup_toggled(check)
        self.assertTrue(self.config.get_show_welcome_on_startup())


if __name__ == "__main__":
    unittest.main()
