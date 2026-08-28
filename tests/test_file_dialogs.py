"""The image filter every ``Gtk.FileDialog`` picker shares (issue #235).

Three pickers ask for an image: the cover and label choosers in
``ui/window.py`` and "Add image" in the artwork manager. Each used to build
the filter itself, which is how the cover chooser and the artwork manager
could come to disagree about what counts as an image. One helper builds it
now, and this is what says the helper admits every format the app can read
back -- and nothing else.
"""

import unittest

from openemux.core.scraper import SUPPORTED_COVER_EXTS
from tests.gtk_display import needs_display


def _file_named(name):
    """A ``Gio.FileInfo`` a ``Gtk.FileFilter`` can be asked about."""
    from gi.repository import Gio

    info = Gio.FileInfo()
    info.set_name(name)
    info.set_display_name(name)
    return info


@needs_display
class TheImageFilterCoversEverySupportedFormatTests(unittest.TestCase):
    def setUp(self):
        from openemux.ui.file_dialogs import image_filters

        self.image_filters = image_filters
        self.filters, self.default = image_filters("Images")

    def test_the_store_holds_exactly_the_default_filter(self):
        # Gtk.FileDialog wants the list to show and which entry starts
        # selected; handing it a store with the filter missing shows a picker
        # that filters nothing.
        self.assertEqual(self.filters.get_n_items(), 1)
        self.assertIs(self.filters.get_item(0), self.default)

    def test_every_supported_extension_matches_in_both_cases(self):
        # A cover saved as ".PNG" by another tool is a file the app reads
        # happily; a filter that hides it makes the picker look broken.
        for ext in SUPPORTED_COVER_EXTS:
            with self.subTest(ext=ext):
                self.assertTrue(self.default.match(_file_named(f"cover.{ext}")))
                self.assertTrue(
                    self.default.match(_file_named(f"cover.{ext.upper()}"))
                )

    def test_a_rom_is_not_offered_as_a_cover(self):
        for name in ("game.sfc", "notes.txt", "cover.bmp"):
            with self.subTest(name=name):
                self.assertFalse(self.default.match(_file_named(name)))

    def test_the_name_is_the_one_shown_in_the_picker(self):
        self.assertEqual(self.default.get_name(), "Images")
        _, named = self.image_filters("Artwork")
        self.assertEqual(named.get_name(), "Artwork")

    def test_the_name_has_no_default(self):
        # It used to default to the English literal "Images", and both callers
        # took the default -- one untranslated word beside an Open/Cancel pair
        # the portal had already translated (issue #232). Requiring the
        # argument is what stops a new picker inheriting that by omission.
        with self.assertRaises(TypeError):
            self.image_filters()


if __name__ == "__main__":
    unittest.main()
