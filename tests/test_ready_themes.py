"""The ready-made themes (issue 1012): ids, values, pictures, contrast."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import yaml

from openemux.core import ready_themes, theme_images
from openemux.core.custom_themes import (
    THEME_FILE,
    ThemeStore,
    contrast_problems,
    validate_values,
)
from openemux.core.theme import (
    READY_MADE,
    is_custom_theme_id,
    is_ready_made,
    normalize_theme,
)


class ReadyThemeTests(unittest.TestCase):
    def test_the_five_ids_shared_with_android(self):
        self.assertEqual(READY_MADE, ("pastel", "dracula", "kitty", "neon", "tokyo-night"))
        self.assertEqual([theme.id for theme in ready_themes.all_themes()], list(READY_MADE))

    def test_each_has_its_picture_and_a_valid_base(self):
        for theme in ready_themes.all_themes():
            self.assertIn(theme.base, ("light", "dark"))
            self.assertEqual(theme.folder, ready_themes.ASSETS_DIR / theme.id)
            # The value as Android writes it, with the desktop's PNG.
            self.assertEqual(theme.values["library_image"], "images/library.png")
            path = theme.image_path("library")
            self.assertIsNotNone(path, theme.id)
            self.assertEqual(path, theme.folder / "images" / "library.png")
            self.assertEqual(theme_images.sniff(path), "png")
            self.assertTrue((theme.folder / "library.svg").is_file())
            # Lightweight: the package should barely grow.
            self.assertLess(path.stat().st_size, 200_000)

    def test_loaded_from_the_shipped_yaml_with_nothing_dropped(self):
        for theme_id in READY_MADE:
            raw = yaml.safe_load(
                (ready_themes.ASSETS_DIR / theme_id / THEME_FILE).read_text(encoding="utf-8")
            )
            settings = {k: v for k, v in raw.items() if k not in ("version", "name", "base")}
            theme = ready_themes.get(theme_id)
            # Every key is one the desktop knows, every value in range.
            self.assertEqual(theme.values, validate_values(raw), theme_id)
            self.assertEqual(theme.values, settings, theme_id)
            self.assertEqual((theme.id, theme.name, theme.base),
                             (theme_id, raw["name"], raw["base"]))

    def test_the_names_shared_with_android(self):
        names = {theme.id: (theme.name, theme.base) for theme in ready_themes.all_themes()}
        self.assertEqual(names, {
            "pastel": ("Pastel", "light"), "dracula": ("Dracula", "dark"),
            "kitty": ("Kitty", "dark"), "neon": ("Neon", "dark"),
            "tokyo-night": ("Tokyo Night", "dark"),
        })

    def test_contrast_passes_with_the_picture_at_its_default_dim(self):
        with TemporaryDirectory() as cache:
            for theme in ready_themes.all_themes():
                # A fraction in the theme, a percentage for the renderer.
                dim = int(round(theme.effective("library_image_dim") * 100))
                blur = theme.effective("library_image_blur")
                out = theme_images.render(theme.image_path("library"), dim, blur,
                                          theme.effective("library_bg"), cache)
                average = theme_images.average_color(out)
                self.assertEqual(contrast_problems(theme, {"library": average}), [], theme.id)

    def test_a_fresh_copy_every_time(self):
        first = ready_themes.get("neon")
        first.values["card_bg"] = "#000000"
        self.assertNotEqual(ready_themes.get("neon").values["card_bg"], "#000000")

    def test_any_other_id_is_none(self):
        for theme_id in ("nope", "dark", "system", "../neon", ""):
            self.assertIsNone(ready_themes.get(theme_id), theme_id)


class ReservedIdTests(unittest.TestCase):
    def test_ready_ids_are_not_custom_but_are_valid_settings(self):
        for theme_id in READY_MADE:
            self.assertTrue(is_ready_made(theme_id))
            self.assertFalse(is_custom_theme_id(theme_id))
            self.assertEqual(normalize_theme(theme_id), theme_id)
        self.assertFalse(is_ready_made("midnight"))

    def test_the_store_serves_them_and_never_gives_their_ids_away(self):
        with TemporaryDirectory() as tmp:
            store = ThemeStore(Path(tmp))
            self.assertEqual(store.get("dracula").name, "Dracula")
            self.assertEqual(store.new_id("Dracula"), "dracula-2")
            self.assertEqual(store.new_id("Tokyo Night"), "tokyo-night-2")
            self.assertEqual(store.list(), [])

    def test_duplicating_one_gives_an_editable_copy_with_its_picture(self):
        with TemporaryDirectory() as tmp:
            store = ThemeStore(Path(tmp))
            copy = store.duplicate("kitty", "Kitty (copy)")
            self.assertTrue(is_custom_theme_id(copy.id))
            loaded = store.get(copy.id)
            self.assertEqual(loaded.values, ready_themes.get("kitty").values)
            self.assertTrue(loaded.image_path("library").is_file())


if __name__ == "__main__":
    unittest.main()
