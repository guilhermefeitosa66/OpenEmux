"""Which gamepad backend gets built, and by whom (issue #118).

The UI must not know whether it is holding the evdev reader or the SDL one, so
the only thing that decides is ``gamepad_backend``. These tests pin the choice
and the two shapes it can return.
"""

import unittest
from unittest.mock import patch

from openemux.core import gamepad_backend as gb


class BackendChoiceTests(unittest.TestCase):
    def test_linux_reads_evdev(self):
        with patch.object(gb, "IS_WINDOWS", False):
            self.assertEqual(gb.backend_name({}), gb.EVDEV)

    def test_windows_reads_sdl2(self):
        with patch.object(gb, "IS_WINDOWS", True):
            self.assertEqual(gb.backend_name({}), gb.SDL2)

    def test_the_environment_overrides_the_platform(self):
        # How the SDL path gets exercised on the Linux desktop this project is
        # developed on -- the numbering in gamepad_sdl has to be checked
        # against a real controller somewhere, and it is not going to be a CI
        # runner.
        with patch.object(gb, "IS_WINDOWS", False):
            self.assertEqual(gb.backend_name({gb.BACKEND_ENV: "sdl2"}), gb.SDL2)
        with patch.object(gb, "IS_WINDOWS", True):
            self.assertEqual(gb.backend_name({gb.BACKEND_ENV: "evdev"}), gb.EVDEV)

    def test_the_override_is_case_and_space_insensitive(self):
        with patch.object(gb, "IS_WINDOWS", False):
            self.assertEqual(gb.backend_name({gb.BACKEND_ENV: " SDL2 "}), gb.SDL2)

    def test_an_unknown_override_warns_and_keeps_the_default(self):
        # Leaving the app with no gamepad at all because of a typo in an
        # environment variable would be the worse failure.
        with patch.object(gb, "IS_WINDOWS", False):
            with self.assertLogs("openemux.core.gamepad_backend", level="WARNING"):
                self.assertEqual(gb.backend_name({gb.BACKEND_ENV: "xinput"}), gb.EVDEV)

    def test_an_empty_override_is_not_an_error(self):
        with patch.object(gb, "IS_WINDOWS", False):
            self.assertEqual(gb.backend_name({gb.BACKEND_ENV: ""}), gb.EVDEV)


class FactoryTests(unittest.TestCase):
    def test_the_evdev_readers_are_built_on_linux(self):
        from openemux.core.gamepad_reader import GamepadCaptureReader
        from openemux.core.ui_gamepad import GamepadNavigator

        with patch.object(gb, "backend_name", lambda: gb.EVDEV):
            self.assertIsInstance(gb.make_navigator(lambda a: None), GamepadNavigator)
            self.assertIsInstance(
                gb.make_capture_reader(lambda t: None), GamepadCaptureReader
            )

    def test_the_sdl_readers_are_built_on_windows(self):
        from openemux.core.gamepad_sdl import SdlCaptureReader, SdlNavigator

        with patch.object(gb, "backend_name", lambda: gb.SDL2):
            navigator = gb.make_navigator(lambda a: None)
            capture = gb.make_capture_reader(lambda t: None)
        self.assertIsInstance(navigator, SdlNavigator)
        self.assertIsInstance(capture, SdlCaptureReader)

    def test_both_readers_answer_the_same_calls(self):
        # The UI calls start/stop on whichever it was handed, asks the capture
        # reader whether it was cancelled and whether it fell back to the
        # legacy API, and never branches on which backend it holds. Built, not
        # introspected: uses_legacy_api is set in __init__, so a class-level
        # hasattr would pass on a reader that never defines it.
        from openemux.core.gamepad_reader import GamepadCaptureReader
        from openemux.core.gamepad_sdl import SdlCaptureReader, SdlNavigator
        from openemux.core.ui_gamepad import GamepadNavigator

        for cls in (GamepadCaptureReader, SdlCaptureReader):
            with self.subTest(reader=cls.__name__):
                reader = cls(on_token=lambda token: None)
                self.assertTrue(callable(reader.start))
                self.assertTrue(callable(reader.stop))
                self.assertFalse(reader.cancelled)
                self.assertIs(reader.uses_legacy_api, False)
        for cls in (GamepadNavigator, SdlNavigator):
            with self.subTest(navigator=cls.__name__):
                navigator = cls(lambda action: None)
                self.assertTrue(callable(navigator.start))
                self.assertTrue(callable(navigator.stop))

    def test_listing_follows_the_backend(self):
        with patch.object(gb, "backend_name", lambda: gb.SDL2), \
             patch("openemux.core.gamepad_sdl.list_gamepads", lambda: ["sdl"]):
            self.assertEqual(gb.list_gamepads(), ["sdl"])
        with patch.object(gb, "backend_name", lambda: gb.EVDEV), \
             patch("openemux.core.gamepad_reader.list_gamepads", lambda: ["evdev"]):
            self.assertEqual(gb.list_gamepads(), ["evdev"])


if __name__ == "__main__":
    unittest.main()
