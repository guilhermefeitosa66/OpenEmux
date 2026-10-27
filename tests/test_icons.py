"""Registering the vendored symbolic icons (issue #245).

`ui/icons.py` had no test file and sat at 0% coverage, while it is what stops
users on Mint-Y, Papirus or Breeze from seeing blank buttons where the UI asked
for a themed icon. The module is small, but every branch in it is a way for
that fallback to silently not happen.

`tests/test_icon_assets.py` already checks the SVG set is complete; this
checks the registration.
"""

import unittest
from unittest.mock import patch

from openemux.ui import icons
from tests.gtk_display import needs_display


class _FakeIconTheme:
    def __init__(self):
        self.paths = []

    def add_search_path(self, path):
        self.paths.append(path)


def _register_with(display, theme, icon_dir=None):
    """Run register_bundled_icons() against stand-ins for Gdk and Gtk."""
    import types

    gdk = types.SimpleNamespace(
        Display=types.SimpleNamespace(get_default=lambda: display)
    )
    gtk = types.SimpleNamespace(
        IconTheme=types.SimpleNamespace(get_for_display=lambda _d: theme)
    )
    repository = types.SimpleNamespace(Gdk=gdk, Gtk=gtk)
    with patch.dict("sys.modules", {"gi.repository": repository}):
        if icon_dir is not None:
            with patch.object(icons, "SYMBOLIC_ICON_DIR", icon_dir):
                icons.register_bundled_icons()
        else:
            icons.register_bundled_icons()


class RegistrationTests(unittest.TestCase):
    def setUp(self):
        # Module state: the guard is what makes the call cheap to repeat.
        self._was_registered = icons._registered
        icons._registered = False
        self.addCleanup(setattr, icons, "_registered", self._was_registered)

    def test_the_bundled_directory_is_added_to_the_icon_theme(self):
        theme = _FakeIconTheme()
        _register_with(display=object(), theme=theme)
        self.assertEqual(theme.paths, [str(icons.ICON_SEARCH_DIR)])

    def test_a_second_call_does_nothing(self):
        # It is called from do_activate(), which runs again on every
        # re-activation of the single-instance app.
        theme = _FakeIconTheme()
        _register_with(display=object(), theme=theme)
        _register_with(display=object(), theme=theme)
        self.assertEqual(len(theme.paths), 1)

    def test_no_display_leaves_the_flag_unset_so_a_later_call_can_retry(self):
        # Registering before GTK has a display must not consume the one shot.
        theme = _FakeIconTheme()
        _register_with(display=None, theme=theme)
        self.assertEqual(theme.paths, [])
        self.assertFalse(icons._registered)

        _register_with(display=object(), theme=theme)
        self.assertEqual(theme.paths, [str(icons.ICON_SEARCH_DIR)])

    def test_a_missing_icon_directory_is_reported_not_registered(self):
        from pathlib import Path

        theme = _FakeIconTheme()
        with self.assertLogs(icons.logger, level="WARNING") as captured:
            _register_with(
                display=object(), theme=theme, icon_dir=Path("/nonexistent/icons")
            )
        self.assertEqual(theme.paths, [])
        self.assertFalse(icons._registered)
        self.assertIn("bundled symbolic icons missing", captured.output[0])


class TheVendoredDirectoryTests(unittest.TestCase):
    def test_the_directory_ships_and_holds_svgs(self):
        self.assertTrue(icons.SYMBOLIC_ICON_DIR.is_dir())
        self.assertTrue(list(icons.SYMBOLIC_ICON_DIR.glob("*.svg")))

    def test_no_icon_sits_loose_in_the_search_path(self):
        # GTK 4.14 draws a loose ("unthemed") SVG in its literal fill rather
        # than recoloring it, which left the Share glyph dark on dark (issue
        # #626). Only the hicolor theme layout gets a symbolic recolor there.
        self.assertEqual(sorted(icons.ICON_SEARCH_DIR.glob("*.svg")), [])
        self.assertEqual(icons.SYMBOLIC_ICON_DIR.parent.parent.parent, icons.ICON_SEARCH_DIR)
        self.assertEqual(icons.SYMBOLIC_ICON_DIR.parent.parent.name, "hicolor")

    def test_the_bundled_index_declares_the_icons_directory(self):
        # Read only on a host with no hicolor theme of its own; the directory
        # the SVGs live in has to be one it lists, or nothing is found there.
        import configparser

        index = configparser.ConfigParser()
        index.optionxform = str
        index.read(icons.ICON_SEARCH_DIR / "hicolor" / "index.theme", encoding="utf-8")
        subdir = icons.SYMBOLIC_ICON_DIR.relative_to(
            icons.ICON_SEARCH_DIR / "hicolor"
        ).as_posix()
        self.assertIn(subdir, index["Icon Theme"]["Directories"].split(","))
        self.assertEqual(index[subdir]["Type"], "Scalable")
        # A 16 px request has to fall inside the scalable range.
        self.assertLessEqual(int(index[subdir]["MinSize"]), 16)
        self.assertGreaterEqual(int(index[subdir]["MaxSize"]), 16)

    def test_every_bundled_icon_is_named_symbolic(self):
        # GTK resolves "<name>-symbolic"; a file named otherwise is never
        # looked up, so it is dead weight in every package.
        for svg in icons.SYMBOLIC_ICON_DIR.glob("*.svg"):
            with self.subTest(icon=svg.name):
                self.assertTrue(svg.stem.endswith("-symbolic"))


@needs_display
class AgainstRealGtkTests(unittest.TestCase):
    """The same call against the real GTK, where there is a display to use."""

    def test_registering_makes_a_bundled_only_icon_resolvable(self):
        import gi

        gi.require_version("Gtk", "4.0")
        from gi.repository import Gdk, Gtk

        was_registered = icons._registered
        icons._registered = False
        self.addCleanup(setattr, icons, "_registered", was_registered)

        icons.register_bundled_icons()

        theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
        self.assertIn(str(icons.ICON_SEARCH_DIR), list(theme.get_search_path() or []))
        self.assertTrue(theme.has_icon(icons.SHARE_ICON))

    def test_the_share_glyph_is_recolored_with_the_theme(self):
        # Issue #626: on GTK 4.14 the glyph resolved, but as a regular icon,
        # so it kept its dark fill on the dark theme's dark header bar.
        import gi

        gi.require_version("Gtk", "4.0")
        from gi.repository import Gtk

        for search_path in (
            # As registered: after the host's own icon directories.
            None,
            # A host with no hicolor theme: the bundled index.theme is read.
            [str(icons.ICON_SEARCH_DIR)],
        ):
            with self.subTest(search_path=search_path):
                theme = Gtk.IconTheme.new()
                if search_path is None:
                    theme.add_search_path(str(icons.ICON_SEARCH_DIR))
                else:
                    theme.set_search_path(search_path)
                paintable = theme.lookup_icon(
                    icons.SHARE_ICON, None, 16, 1, Gtk.TextDirection.LTR, 0
                )
                self.assertEqual(
                    paintable.get_file().get_path(),
                    str(icons.SYMBOLIC_ICON_DIR / f"{icons.SHARE_ICON}.svg"),
                )
                self.assertTrue(paintable.is_symbolic())


if __name__ == "__main__":
    unittest.main()
