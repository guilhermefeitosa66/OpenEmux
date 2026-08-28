"""The Wayland cost of the game window is stated where the switch is (#258).

Turning the game window on forces ``GDK_BACKEND=x11`` before GTK is imported,
because the embed is ``XReparentWindow`` between two X clients. GTK4 cannot
pick a backend per window, so on a Wayland session that puts the *library*
through XWayland too -- for the whole run, not only while a game is up. The
switch reads as "show the game inside OpenEmux" and said nothing about it.

The subtitle is assembled by a module-level function precisely so this can be
checked without a display: building the ``Adw.SwitchRow`` it feeds segfaults
on a headless box.
"""

import unittest
from unittest import mock

from openemux.core import game_window_support
from openemux.i18n import LOCALE_TRANSLATIONS, SUPPORTED_LOCALES, tr
from openemux.ui.preferences import game_window_subtitle

_KEY = "prefs.game_window.subtitle.xwayland"


def _english(key):
    return tr("en", key)


class TheSubtitleTests(unittest.TestCase):
    def test_a_wayland_session_is_told(self):
        with mock.patch.object(game_window_support, "session_is_wayland", lambda: True):
            subtitle = game_window_subtitle(_english)

        self.assertIn(_english("prefs.game_window.subtitle"), subtitle)
        self.assertIn(_english(_KEY), subtitle)

    def test_an_x11_session_is_not(self):
        # The sentence is about a cost X11 users do not pay; on that session it
        # would be noise in a subtitle that is already three lines long.
        with mock.patch.object(game_window_support, "session_is_wayland", lambda: False):
            self.assertEqual(
                game_window_subtitle(_english),
                _english("prefs.game_window.subtitle"),
            )

    def test_the_two_sentences_are_separated(self):
        with mock.patch.object(game_window_support, "session_is_wayland", lambda: True):
            subtitle = game_window_subtitle(_english)

        joined = _english("prefs.game_window.subtitle") + _english(_KEY)
        self.assertNotIn(joined, subtitle)

    def test_it_asks_the_compositor_not_the_toolkit(self):
        # The regression this guards: on the session the notice is *for*,
        # GDK_BACKEND is already x11 because the setting is on. Asking GTK
        # what backend it opened answers "X11" and the notice never appears.
        env = {"WAYLAND_DISPLAY": "wayland-0", "DISPLAY": ":0", "GDK_BACKEND": "x11"}
        with mock.patch.dict("os.environ", env, clear=True):
            self.assertIn(_english(_KEY), game_window_subtitle(_english))


class TheNoticeIsTranslatedTests(unittest.TestCase):
    def test_every_locale_carries_it(self):
        for locale in SUPPORTED_LOCALES:
            with self.subTest(locale=locale):
                self.assertIn(_KEY, LOCALE_TRANSLATIONS[locale])

    def test_no_locale_left_it_in_english(self):
        english = LOCALE_TRANSLATIONS["en"][_KEY]
        for locale in SUPPORTED_LOCALES:
            if locale == "en":
                continue
            with self.subTest(locale=locale):
                self.assertNotEqual(LOCALE_TRANSLATIONS[locale][_KEY], english)

    def test_each_one_names_xwayland(self):
        # The word is the whole point: a user searching for why their fonts
        # look soft is searching for "XWayland", in any language.
        for locale in SUPPORTED_LOCALES:
            with self.subTest(locale=locale):
                self.assertIn("XWayland", LOCALE_TRANSLATIONS[locale][_KEY])


if __name__ == "__main__":
    unittest.main()
