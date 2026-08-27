"""The one place that talks to Adw.StyleManager (issue #245).

`ui/theming.py` had no test file. It is ten lines, and all of them are the
mapping between the stored setting and what libadwaita is told -- get it
wrong and the app either ignores the user's choice or stops following the
desktop. `tests/test_theme.py` covers the vocabulary in `core/theme.py`;
this covers the translation.
"""

import unittest

from openemux.core.theme import (
    DEFAULT_THEME,
    THEME_DARK,
    THEME_LIGHT,
    THEME_SYSTEM,
    THEMES,
)
from tests.gtk_display import needs_display


class _FakeStyleManager:
    def __init__(self, dark=False):
        self.scheme = None
        self._dark = dark

    def set_color_scheme(self, scheme):
        self.scheme = scheme

    def get_dark(self):
        return self._dark


class _StyleManagerStub:
    def __init__(self, manager):
        self._manager = manager

    def get_default(self):
        return self._manager


def _apply(theme, manager):
    from unittest.mock import patch

    from openemux.ui import theming

    with patch.object(theming.Adw, "StyleManager", _StyleManagerStub(manager)):
        theming.apply_theme(theme)
    return manager.scheme


@needs_display
class ApplyThemeTests(unittest.TestCase):
    """Importing theming imports Adw, which needs a display to come up."""

    def _schemes(self):
        from gi.repository import Adw

        return Adw.ColorScheme

    def test_light_is_forced_not_merely_preferred(self):
        # PREFER_LIGHT still yields to a dark desktop; the setting exists to
        # override it.
        manager = _FakeStyleManager()
        self.assertEqual(_apply(THEME_LIGHT, manager), self._schemes().FORCE_LIGHT)

    def test_dark_is_forced_too(self):
        manager = _FakeStyleManager()
        self.assertEqual(_apply(THEME_DARK, manager), self._schemes().FORCE_DARK)

    def test_system_hands_the_choice_back_to_the_desktop(self):
        manager = _FakeStyleManager()
        self.assertEqual(_apply(THEME_SYSTEM, manager), self._schemes().DEFAULT)

    def test_an_unknown_value_lands_on_the_default_rather_than_raising(self):
        # A hand-edited config.yaml, or one written by an older version.
        manager = _FakeStyleManager()
        self.assertEqual(_apply("chartreuse", manager), self._schemes().DEFAULT)
        self.assertEqual(_apply(None, manager), self._schemes().DEFAULT)

    def test_the_default_theme_maps_to_the_default_scheme(self):
        manager = _FakeStyleManager()
        self.assertEqual(_apply(DEFAULT_THEME, manager), self._schemes().DEFAULT)

    def test_every_supported_theme_maps_to_something(self):
        for theme in THEMES:
            with self.subTest(theme=theme):
                manager = _FakeStyleManager()
                self.assertIsNotNone(_apply(theme, manager))

    def test_case_and_space_are_forgiven_the_same_way_the_config_forgives_them(self):
        manager = _FakeStyleManager()
        self.assertEqual(_apply("  DARK ", manager), self._schemes().FORCE_DARK)


@needs_display
class IsDarkTests(unittest.TestCase):
    """What is on screen now -- not the stored value, which may be `system`."""

    def _is_dark_with(self, manager):
        from unittest.mock import patch

        from openemux.ui import theming

        with patch.object(theming.Adw, "StyleManager", _StyleManagerStub(manager)):
            return theming.is_dark()

    def test_it_reports_what_libadwaita_is_painting(self):
        self.assertTrue(self._is_dark_with(_FakeStyleManager(dark=True)))
        self.assertFalse(self._is_dark_with(_FakeStyleManager(dark=False)))

    def test_the_answer_is_a_bool_the_toggle_can_use_directly(self):
        # toggled_theme() branches on it, so a GObject truthy value would work
        # by accident and compare wrongly.
        self.assertIsInstance(self._is_dark_with(_FakeStyleManager(dark=True)), bool)


if __name__ == "__main__":
    unittest.main()
