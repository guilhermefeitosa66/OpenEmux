"""Custom themes on screen: the provider, restore, the window (issue 1011)."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from tests.gtk_display import HAVE_DISPLAY, needs_display
from tests.window_harness import WindowCase

if HAVE_DISPLAY:
    from gi.repository import Adw, Gdk, Gtk

    from openemux.core.custom_themes import ThemeStore
    from openemux.ui import theming


def _reset_theming():
    if theming._provider is not None:
        display = Gdk.Display.get_default()
        Gtk.StyleContext.remove_provider_for_display(display, theming._provider)
    theming._provider = None
    theming._suspended = False
    theming._applied = ("system", None, {}, None)
    theming._paint = theming.Paint()
    theming._rendering.clear()
    theming._waiting.clear()
    Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.DEFAULT)


@needs_display
class _ThemingCase(unittest.TestCase):
    def setUp(self):
        _reset_theming()
        self.addCleanup(_reset_theming)
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = ThemeStore(Path(self._tmp.name) / "themes")
        self.manager = Adw.StyleManager.get_default()

    def css(self):
        return theming._provider.to_string() if theming._provider is not None else ""


@needs_display
class BuiltInThemeTests(_ThemingCase):
    def test_light_and_dark_force_the_scheme_and_system_follows_the_desktop(self):
        self.assertEqual(theming.apply_theme("dark"), "dark")
        self.assertEqual(self.manager.get_color_scheme(), Adw.ColorScheme.FORCE_DARK)
        self.assertEqual(theming.apply_theme("light"), "light")
        self.assertEqual(self.manager.get_color_scheme(), Adw.ColorScheme.FORCE_LIGHT)
        self.assertEqual(theming.apply_theme("system"), "system")
        self.assertEqual(self.manager.get_color_scheme(), Adw.ColorScheme.DEFAULT)
        # Nothing custom was ever painted, so no provider was made.
        self.assertIsNone(theming._provider)

    def test_is_dark_reads_what_is_on_screen(self):
        theming.apply_theme("dark")
        self.assertTrue(theming.is_dark())


@needs_display
class CustomThemeTests(_ThemingCase):
    def test_a_custom_theme_forces_its_base_and_loads_its_css(self):
        theme = self.store.create("Night", "dark", {"card_bg": "#2f3549"})
        self.assertEqual(theming.apply_theme(theme.id, store=self.store), "night")
        self.assertEqual(self.manager.get_color_scheme(), Adw.ColorScheme.FORCE_DARK)
        self.assertIn("2f3549", self.css())
        self.assertEqual(theming.applied_theme(), "night")

    def test_going_back_to_a_built_in_empties_the_provider(self):
        theme = self.store.create("Paper", "light", {"window_bg": "#fbf7f0"})
        theming.apply_theme(theme.id, store=self.store)
        theming.apply_theme("dark")
        self.assertNotIn("fbf7f0", self.css())
        self.assertEqual(self.manager.get_color_scheme(), Adw.ColorScheme.FORCE_DARK)

    def test_a_missing_theme_paints_system(self):
        with self.assertLogs("openemux.ui.theming", level="INFO"):
            self.assertEqual(theming.apply_theme("gone", store=self.store), "system")
        with self.assertLogs("openemux.ui.theming", level="INFO"):
            self.assertEqual(theming.apply_theme("gone"), "system")
        self.assertEqual(self.manager.get_color_scheme(), Adw.ColorScheme.DEFAULT)

    def test_restore_puts_back_what_apply_painted(self):
        theme = self.store.create("Night", "dark", {"card_bg": "#2f3549"})
        theming.apply_theme(theme.id, store=self.store)
        theming.paint("light", {"card_bg": "#ffeedd"})
        self.assertIn("ffeedd", self.css())
        theming.restore()
        self.assertIn("2f3549", self.css())
        self.assertEqual(self.manager.get_color_scheme(), Adw.ColorScheme.FORCE_DARK)

    def test_restore_after_a_built_in(self):
        theming.apply_theme("light")
        theming.paint("dark", {"card_bg": "#ffeedd"})
        theming.restore()
        self.assertEqual(self.css(), "")
        self.assertEqual(self.manager.get_color_scheme(), Adw.ColorScheme.FORCE_LIGHT)

    def test_restore_before_anything_custom_needs_no_provider(self):
        theming.apply_theme("dark")
        theming.restore()
        self.assertIsNone(theming._provider)

    def test_css_variables_follow_the_libadwaita_version(self):
        expected = (Adw.get_major_version(), Adw.get_minor_version()) >= (1, 6)
        self.assertEqual(theming.uses_css_variables(), expected)
        theming.paint("dark", {"card_bg": "#2f3549"})
        self.assertEqual("--card-bg-color" in self.css(), expected)

    def test_big_picture_suspends_the_custom_colors(self):
        theme = self.store.create("Night", "dark", {"card_bg": "#2f3549"})
        theming.apply_theme(theme.id, store=self.store)
        theming.set_suspended(True)
        theming.set_suspended(True)
        self.assertEqual(self.css(), "")
        # Applied while suspended: remembered, painted on the way out.
        other = self.store.create("Paper", "light", {"card_bg": "#ffeedd"})
        theming.apply_theme(other.id, store=self.store)
        self.assertEqual(self.css(), "")
        theming.set_suspended(False)
        self.assertIn("ffeedd", self.css())
        theming.set_suspended(False)

    def test_suspending_before_any_custom_theme_needs_no_provider(self):
        theming.set_suspended(True)
        theming.set_suspended(False)
        self.assertIsNone(theming._provider)

    def test_no_display_no_provider(self):
        with mock.patch.object(theming.Gdk.Display, "get_default", return_value=None):
            theming.paint("dark", {"card_bg": "#2f3549"})
        self.assertIsNone(theming._provider)


@needs_display
class WindowThemeTests(WindowCase):
    def setUp(self):
        super().setUp()
        _reset_theming()
        self.addCleanup(_reset_theming)

    def test_the_themed_surfaces_carry_their_classes(self):
        self.assertTrue(self.win.content_stack.has_css_class("library-area"))
        from openemux.ui.game_details import GameDetailsDialog
        dialog = GameDetailsDialog(self.win, self.rom("SFC"))
        self.addCleanup(dialog.force_close)
        self.assertTrue(dialog.get_child().has_css_class("game-details-view"))

    def test_the_header_toggle_leaves_a_custom_theme_for_a_built_in(self):
        store = self.config.themes
        theme = store.create("Night", "dark", {"card_bg": "#2f3549"})
        self.config.set_theme(theme.id)
        theming.apply_theme(theme.id, store=store)
        self.win._on_theme_toggle_clicked(None)
        self.assertEqual(self.config.get_ui_settings()["theme"], "light")
        self.assertEqual(theming.applied_theme(), "light")


if __name__ == "__main__":
    unittest.main()
