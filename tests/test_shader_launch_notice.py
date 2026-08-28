"""A launch that worked but has no shader says so on screen (#366).

The Windows symptom was invisible: the game came up, nothing looked wrong, and
the only trace that the console's CRT shader had not been applied was an
``INFO`` line in the app log. The launch is not an error -- it succeeded -- so
the message cannot travel in the error slot, and this is the path it takes
instead: launcher -> ``RuntimeManager.launch_notice`` -> a toast.

Core has no locale (issue #232), so what travels is a translation key and its
arguments, resolved by the UI. That is also what these tests assert: the keys
exist in every language the app ships.
"""

import unittest
from unittest.mock import Mock

from openemux.i18n import SUPPORTED_LOCALES, tr
from openemux.ui.game_session import GameSession

NOTICE_KEYS = (
    "toast.shader.preset_missing",
    "toast.shader.driver_has_no_presets",
)


class _StubWindow:
    def __init__(self, notice):
        self.runtime_manager = Mock()
        self.runtime_manager.launch_notice = notice
        self.toasts = []

    def t(self, key, **kwargs):
        return tr("en", key, **kwargs)


class TheToastTests(unittest.TestCase):
    def _session(self, notice):
        window = _StubWindow(notice)
        session = GameSession(window)
        session._toast_now = lambda title, timeout: window.toasts.append(title)
        return session, window

    def test_nothing_is_said_when_there_is_nothing_to_say(self):
        session, window = self._session(None)
        session._announce_launch_notice()
        self.assertEqual(window.toasts, [])

    def test_the_missing_preset_names_the_shader_and_the_driver(self):
        session, window = self._session(
            ("toast.shader.preset_missing", {"shader": "Geom CRT", "driver": "d3d11"})
        )
        session._announce_launch_notice()
        self.assertEqual(len(window.toasts), 1)
        self.assertIn("Geom CRT", window.toasts[0])
        self.assertIn("d3d11", window.toasts[0])

    def test_a_driver_that_reads_no_presets_says_which_one(self):
        session, window = self._session(
            ("toast.shader.driver_has_no_presets", {"shader": "Dot", "driver": "sdl2"})
        )
        session._announce_launch_notice()
        self.assertIn("sdl2", window.toasts[0])

    def test_a_runtime_manager_without_the_attribute_says_nothing(self):
        # The suite hands the UI stub runtime managers, and a launch must never
        # fail because a notice channel was not there to read.
        window = _StubWindow(None)
        del window.runtime_manager.launch_notice
        session = GameSession(window)
        session._toast_now = lambda title, timeout: window.toasts.append(title)
        session._announce_launch_notice()
        self.assertEqual(window.toasts, [])


class EveryLanguageSaysItTests(unittest.TestCase):
    def test_the_keys_are_translated_everywhere(self):
        for locale in SUPPORTED_LOCALES:
            for key in NOTICE_KEYS:
                with self.subTest(locale=locale, key=key):
                    text = tr(locale, key, shader="Dot", driver="d3d11")
                    self.assertNotEqual(text, key, f"{key} is untranslated in {locale}")
                    self.assertIn("d3d11", text)
                    self.assertIn("Dot", text)


if __name__ == "__main__":
    unittest.main()
