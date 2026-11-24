"""Issue 1012 in the theme model: palettes, image contrast, images on disk."""

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import gi

gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf

from openemux.core import custom_themes, theme_images
from openemux.core.cartridge_colors import PRESET_PALETTES
from openemux.core.contrast import WCAG_AA, contrast_ratio, relative_luminance
from openemux.core.custom_themes import (
    Theme,
    ThemeStore,
    contrast_problems,
    mix,
    readable_on,
    seed_from_palette,
)


def write_png(path, width=40, height=20, color=0x3366CCFF):
    pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, width, height)
    pixbuf.fill(color)
    pixbuf.savev(str(path), "png", [], [])
    return Path(path)


class ColorHelperTests(unittest.TestCase):
    def test_mix(self):
        self.assertEqual(mix("#000000", "#ffffff", 0), "#000000")
        self.assertEqual(mix("#000000", "#ffffff", 1), "#ffffff")
        self.assertEqual(mix("#000000", "#ffffff", 0.5), "#808080")

    def test_readable_on_keeps_a_color_that_already_reads(self):
        self.assertEqual(readable_on("#ffffff", "#000000"), "#ffffff")

    def test_readable_on_pushes_toward_the_far_end(self):
        dark = readable_on("#777777", "#ffffff")
        self.assertGreaterEqual(contrast_ratio(dark, "#ffffff"), WCAG_AA)
        light = readable_on("#777777", "#000000")
        self.assertGreaterEqual(contrast_ratio(light, "#000000"), WCAG_AA)

    def test_readable_on_unreachable_ends_at_black_or_white(self):
        self.assertEqual(readable_on("#808080", "#767676", target=30), "#000000")
        self.assertEqual(readable_on("#808080", "#101010", target=30), "#ffffff")


class SeedTests(unittest.TestCase):
    def test_every_preset_seeds_without_a_warning_on_both_bases(self):
        for palette_id, colors in PRESET_PALETTES:
            for base in ("light", "dark"):
                values = seed_from_palette(base, colors)
                self.assertTrue(values, palette_id)
                theme = Theme("x", "x", base, values)
                self.assertEqual(contrast_problems(theme), [], (palette_id, base))

    def test_a_dark_base_gets_dark_surfaces_and_a_light_base_light_ones(self):
        colors = ("#F472B6", "#FACC15", "#BFDBFE")  # all light
        dark = seed_from_palette("dark", colors)
        self.assertLess(relative_luminance(dark["window_bg"]), 0.05)
        light = seed_from_palette("light", ("#0D0221", "#282828", "#3E2C23"))  # all dark
        self.assertGreater(relative_luminance(light["window_bg"]), 0.75)

    def test_two_colors_are_enough(self):
        values = seed_from_palette("dark", ("#101010", "#e0e0e0"))
        self.assertEqual(values["window_bg"], "#101010")
        self.assertIn("accent", values)

    def test_too_few_usable_colors_seed_nothing(self):
        self.assertEqual(seed_from_palette("dark", ()), {})
        self.assertEqual(seed_from_palette("dark", None), {})
        self.assertEqual(seed_from_palette("dark", ("#111111", "#111111", "nope", 7)), {})

    def test_the_most_saturated_color_is_the_accent(self):
        values = seed_from_palette("dark", ("#202020", "#e0e0e0", "#ff0000"))
        self.assertEqual(values["accent_button_bg"][:3], "#ff")


class ImageContrastTests(unittest.TestCase):
    def test_warnings_for_with_problems_given(self):
        theme = Theme("x", "x", "dark", {"library_image": "images/library.png"})
        problems = contrast_problems(theme, {"library": "#f0f0f0"})
        found = custom_themes.warnings_for(theme, "library_image", problems)
        self.assertIn("text_primary", [other for other, _ratio in found])
        self.assertEqual(custom_themes.warnings_for(theme, "card_bg", problems), [])

    def test_toward_base_can_end_at_black_or_white(self):
        self.assertEqual(custom_themes._toward_base("#000000", "light", 1.0), "#ffffff")
        self.assertEqual(custom_themes._toward_base("#ffffff", "dark", 0.0), "#000000")

    def test_a_colorless_palette_still_reaches_its_base(self):
        # Mid grey on both ends: the surface is taken all the way to the end.
        values = seed_from_palette("light", ("#777777", "#787878", "#797979"))
        self.assertGreater(relative_luminance(values["window_bg"]), 0.75)

    def test_text_is_checked_against_the_dimmed_image_too(self):
        theme = Theme("x", "x", "dark", {"library_image": "images/library.png"})
        problems = contrast_problems(theme, {"library": "#f0f0f0"})
        self.assertIn(("text_primary", "library_image"),
                      [(fg, bg) for fg, bg, _ratio in problems])

    def test_no_image_value_no_image_check(self):
        theme = Theme("x", "x", "dark", {})
        self.assertEqual(contrast_problems(theme, {"library": "#f0f0f0"}), [])

    def test_unknown_areas_and_bad_colors_are_ignored(self):
        theme = Theme("x", "x", "dark", {"library_image": "images/library.png"})
        self.assertEqual(contrast_problems(theme, {"elsewhere": "#ffffff", "library": "x"}), [])

    def test_a_readable_image_warns_nothing(self):
        theme = Theme("x", "x", "dark", {"sidebar_image": "images/sidebar.png"})
        self.assertEqual(contrast_problems(theme, {"sidebar": "#202020"}), [])


class ThemeImagePathTests(unittest.TestCase):
    def test_image_path(self):
        with TemporaryDirectory() as tmp:
            # The values are relative to the theme's folder: images/<name>.
            (Path(tmp) / "images").mkdir()
            write_png(Path(tmp) / "images" / "library.png")
            theme = Theme("x", "x", "dark", {"library_image": "images/library.png",
                                              "sidebar_image": "images/sidebar.png"},
                          folder=Path(tmp))
            self.assertEqual(theme.image_path("library"), Path(tmp) / "images" / "library.png")
            self.assertIsNone(theme.image_path("sidebar"))  # named but missing
            self.assertIsNone(theme.copy(folder=None).image_path("library"))
            self.assertIsNone(Theme("x", "x", "dark", folder=Path(tmp)).image_path("library"))
            self.assertEqual(theme.copy().folder, Path(tmp))


class StoreImageTests(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.store = ThemeStore(self.tmp / "themes")

    def staged(self, *names):
        """A folder as ``stage()`` makes one: the pictures in its ``images/``."""
        folder = self.tmp / "staged"
        (folder / "images").mkdir(parents=True, exist_ok=True)
        for name in names:
            write_png(folder / "images" / name)
        return folder

    def test_create_copies_the_named_images_only(self):
        source = self.staged("library.png", "stray.png")
        theme = self.store.create("Pics", "dark", {"library_image": "images/library.png"},
                                  images_from=source)
        images = self.store.images_dir(theme.id)
        self.assertEqual(sorted(p.name for p in images.iterdir()), ["library.png"])
        self.assertEqual(theme.folder, images.parent)
        self.assertEqual(self.store.get(theme.id).image_path("library"), images / "library.png")

    def test_a_named_image_that_is_missing_is_logged_and_skipped(self):
        source = self.staged()
        with self.assertLogs("openemux.core.custom_themes", level="WARNING"):
            theme = self.store.create("Pics", "dark", {"library_image": "images/library.png"},
                                      images_from=source)
        self.assertFalse(any(self.store.images_dir(theme.id).iterdir()))

    def test_saving_without_images_keeps_them_and_dropping_one_removes_it(self):
        source = self.staged("library.png", "sidebar.png")
        theme = self.store.create("Pics", "dark", {"library_image": "images/library.png",
                                                    "sidebar_image": "images/sidebar.png"},
                                  images_from=source)
        theme.values["card_bg"] = "#123456"
        self.store.save(theme)
        images = self.store.images_dir(theme.id)
        self.assertEqual(sorted(p.name for p in images.iterdir()), ["library.png", "sidebar.png"])
        del theme.values["sidebar_image"]
        self.store.save(theme)
        self.assertEqual([p.name for p in images.iterdir()], ["library.png"])
        del theme.values["library_image"]
        self.store.save(theme)
        self.assertFalse(images.exists())
        self.store.save(theme)  # nothing to remove either

    def test_a_leftover_temp_folder_is_replaced(self):
        source = self.staged("library.png")
        theme = self.store.create("Pics", "dark", {}, images_from=source)
        leftover = self.store._folder(theme.id) / ".images.tmp"
        leftover.mkdir()
        (leftover / "junk").write_text("x")
        theme.values["library_image"] = "images/library.png"
        self.store.save(theme, images_from=source)
        self.assertFalse(leftover.exists())
        self.assertTrue((self.store.images_dir(theme.id) / "library.png").is_file())

    def test_a_failed_image_swap_leaves_the_old_images(self):
        source = self.staged("library.png")
        theme = self.store.create("Pics", "dark", {"library_image": "images/library.png"},
                                  images_from=source)
        with mock.patch.object(custom_themes.os, "replace", side_effect=OSError("disk")):
            with self.assertRaises(OSError):
                self.store.save(theme, images_from=source)
        self.assertFalse((self.store._folder(theme.id) / ".images.tmp").exists())

    def test_duplicate_copies_the_images(self):
        source = self.staged("library.png")
        theme = self.store.create("Pics", "dark", {"library_image": "images/library.png"},
                                  images_from=source)
        copy = self.store.duplicate(theme.id, "Pics copy")
        self.assertTrue((self.store.images_dir(copy.id) / "library.png").is_file())
        self.store.delete(theme.id)
        self.assertTrue(self.store.get(copy.id).image_path("library"))

    def test_unique_name(self):
        self.store.create("Midnight", "dark")
        self.assertEqual(self.store.unique_name("Dawn"), "Dawn")
        self.assertEqual(self.store.unique_name("midnight"), "midnight (2)")
        self.store.create("Midnight (2)", "dark")
        self.assertEqual(self.store.unique_name("Midnight"), "Midnight (3)")
        long = "x" * custom_themes.MAX_NAME_LENGTH
        self.store.create(long, "dark")
        named = self.store.unique_name(long)
        self.assertEqual(len(named), custom_themes.MAX_NAME_LENGTH)
        self.assertTrue(named.endswith(" (2)"))

    def test_staging_copies_images_and_discard_removes_only_staging(self):
        source = self.staged("library.png")
        (source / "images" / "notes.txt").write_text("not an image")
        theme = self.store.create("Pics", "dark", {"library_image": "images/library.png"},
                                  images_from=source)
        staging = self.store.stage(self.store.get(theme.id))
        self.assertEqual(staging.parent, self.store.root)
        self.assertTrue(staging.name.startswith(ThemeStore.STAGING_PREFIX))
        self.assertEqual([p.name for p in staging.iterdir()], ["images"])
        self.assertEqual([p.name for p in (staging / "images").iterdir()], ["library.png"])
        # The staging folder is what save() takes, and what the values are relative to.
        self.assertTrue(theme.copy(folder=staging).image_path("library").is_file())
        self.store.discard(self.tmp / "staged")  # not a staging folder: kept
        self.assertTrue((self.tmp / "staged").is_dir())
        self.store.discard(self.store._folder(theme.id))  # a theme: kept
        self.assertTrue(self.store._folder(theme.id).is_dir())
        self.store.discard(staging)
        self.assertFalse(staging.exists())

    def test_staging_a_new_theme_is_empty(self):
        staging = self.store.stage(Theme("", "New", "dark"))
        self.assertEqual(list((staging / "images").iterdir()), [])
        staging2 = self.store.stage(Theme("", "New", "dark", folder=self.tmp / "nowhere"))
        self.assertEqual(list((staging2 / "images").iterdir()), [])

    def test_staging_skips_what_is_not_an_image_file(self):
        folder = self.tmp / "odd"
        (folder / "images" / "sub.png").mkdir(parents=True)
        write_png(folder / "images" / "ok.png")
        write_png(folder / "images" / "Upper.PNG")
        write_png(folder / "outside.png")
        staging = self.store.stage(Theme("", "New", "dark", folder=folder))
        self.assertEqual([p.name for p in (staging / "images").iterdir()], ["ok.png"])

    def test_a_user_theme_on_a_reserved_id_is_moved_aside(self):
        self.assertEqual(self.store.move_reserved_ids(), {})  # no folder yet
        folder = self.store.root / "neon"
        folder.mkdir(parents=True)
        (folder / "theme.yaml").write_text("version: 1\nname: Neon\nbase: dark\n")
        moved = self.store.move_reserved_ids()
        self.assertEqual(moved, {"neon": "neon-2"})
        self.assertEqual(self.store.get("neon-2").name, "Neon")
        self.assertEqual(self.store.get("neon").name, "Neon")  # the ready-made one

    def test_a_reserved_folder_that_cannot_move_is_left_and_logged(self):
        (self.store.root / "kitty").mkdir(parents=True)
        with mock.patch.object(Path, "rename", side_effect=OSError("busy")), \
             self.assertLogs("openemux.core.custom_themes", level="WARNING"):
            self.assertEqual(self.store.move_reserved_ids(), {})

    def test_purge_leftovers(self):
        self.store.purge_leftovers()  # no folder yet: nothing to do
        theme = self.store.create("Keep", "dark")
        staging = self.store.stage(theme)
        imported = self.store.root / (ThemeStore.IMPORT_PREFIX + "abc")
        imported.mkdir()
        stray_file = self.store.root / ".staging-file"
        stray_file.write_text("a file, not a folder")
        self.store.purge_leftovers()
        self.assertFalse(staging.exists())
        self.assertFalse(imported.exists())
        self.assertTrue(stray_file.exists())
        self.assertIsNotNone(self.store.get(theme.id))


class ImportImageTests(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)

    def test_sniff(self):
        png = write_png(self.tmp / "a.png")
        self.assertEqual(theme_images.sniff(png), "png")
        (self.tmp / "a.jpg").write_bytes(b"\xff\xd8\xff\xe0" + b"0" * 20)
        self.assertEqual(theme_images.sniff(self.tmp / "a.jpg"), "jpeg")
        (self.tmp / "a.webp").write_bytes(b"RIFF\x00\x00\x00\x00WEBPVP8 ")
        self.assertEqual(theme_images.sniff(self.tmp / "a.webp"), "webp")
        (self.tmp / "a.txt").write_text("hello there")
        self.assertIsNone(theme_images.sniff(self.tmp / "a.txt"))
        self.assertIsNone(theme_images.sniff(self.tmp / "missing"))

    def test_a_small_picture_is_copied_as_png(self):
        source = write_png(self.tmp / "in.png", 30, 10)
        out = theme_images.import_image(source, self.tmp / "out.png")
        self.assertEqual(theme_images.image_size(out), (30, 10))
        self.assertEqual(theme_images.sniff(out), "png")

    def test_the_stored_copy_is_at_most_2048_px(self):
        self.assertEqual(theme_images.MAX_SIDE, 2048)

    def test_a_large_picture_is_scaled_down(self):
        with mock.patch.object(theme_images, "MAX_SIDE", 20):
            out = theme_images.import_image(write_png(self.tmp / "in.png", 80, 40),
                                            self.tmp / "out.png")
        self.assertEqual(theme_images.image_size(out), (20, 10))

    def test_refusals_write_nothing(self):
        text = self.tmp / "fake.png"
        text.write_text("not a picture at all")
        cases = [text, self.tmp / "missing.png", self.tmp]
        for source in cases:
            with self.assertRaises(theme_images.ThemeImageError, msg=str(source)):
                theme_images.import_image(source, self.tmp / "out.png")
        self.assertFalse((self.tmp / "out.png").exists())

    def test_too_many_bytes_or_pixels(self):
        source = write_png(self.tmp / "in.png", 40, 20)
        with mock.patch.object(theme_images, "MAX_FILE_BYTES", 10):
            with self.assertRaises(theme_images.ThemeImageError):
                theme_images.import_image(source, self.tmp / "out.png")
        with mock.patch.object(theme_images, "MAX_PIXELS_SIDE", 30):
            with self.assertRaises(theme_images.ThemeImageError):
                theme_images.import_image(source, self.tmp / "out.png")

    def test_a_signature_no_loader_knows(self):
        fake = self.tmp / "fake.webp"
        fake.write_bytes(b"RIFF\x00\x00\x00\x00WEBPjunkjunkjunk")
        with mock.patch.object(theme_images.GdkPixbuf.Pixbuf, "get_file_info", return_value=None):
            with self.assertRaises(theme_images.ThemeImageError):
                theme_images.import_image(fake, self.tmp / "out.png")

    def test_a_truncated_picture_fails_to_decode(self):
        good = write_png(self.tmp / "good.png", 200, 200).read_bytes()
        broken = self.tmp / "broken.png"
        broken.write_bytes(good[:120])
        with self.assertRaises(theme_images.ThemeImageError):
            theme_images.import_image(broken, self.tmp / "out.png")
        self.assertFalse((self.tmp / ".out.png.tmp").exists())

    def test_a_write_failure_cleans_up_and_raises(self):
        source = write_png(self.tmp / "in.png")
        with mock.patch.object(theme_images.os, "replace", side_effect=OSError("full")):
            with self.assertRaises(OSError):
                theme_images.import_image(source, self.tmp / "out.png")
        self.assertFalse((self.tmp / ".out.png.tmp").exists())

    def test_image_size_of_nothing(self):
        (self.tmp / "x.txt").write_text("no")
        self.assertIsNone(theme_images.image_size(self.tmp / "x.txt"))


class ProcessTests(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.cache = self.tmp / "cache"
        self.source = write_png(self.tmp / "in.png", 60, 30, 0xFFFFFFFF)

    def test_the_path_changes_with_every_setting_and_the_file(self):
        first = theme_images.processed_path(self.source, 40, 0, "#000000", self.cache)
        self.assertEqual(first, theme_images.processed_path(self.source, 40, 0, "#000000", self.cache))
        self.assertNotEqual(first, theme_images.processed_path(self.source, 41, 0, "#000000", self.cache))
        self.assertNotEqual(first, theme_images.processed_path(self.source, 40, 2, "#000000", self.cache))
        self.assertNotEqual(first, theme_images.processed_path(self.source, 40, 0, "#000001", self.cache))
        os.utime(self.source, ns=(1, 1))
        self.assertNotEqual(first, theme_images.processed_path(self.source, 40, 0, "#000000", self.cache))
        missing = theme_images.processed_path(self.tmp / "gone.png", 40, 0, "#000000", self.cache)
        self.assertEqual(missing.parent, self.cache)

    def test_render_dims_toward_the_surface(self):
        out = theme_images.render(self.source, 50, 0, "#000000", self.cache)
        self.assertTrue(out.is_file())
        average = theme_images.average_color(out)
        self.assertIn(average, ("#7f7f7f", "#808080"))
        # Rendered once: the second call reuses the file.
        with mock.patch.object(theme_images.GdkPixbuf.Pixbuf, "new_from_file") as load:
            self.assertEqual(theme_images.render(self.source, 50, 0, "#000000", self.cache), out)
        load.assert_not_called()

    def test_render_blurs_and_survives_no_dim(self):
        out = theme_images.render(self.source, 0, 10, "not a color", self.cache)
        self.assertEqual(theme_images.average_color(out), "#ffffff")

    def test_render_failure_returns_none(self):
        bad = self.tmp / "bad.png"
        bad.write_text("x")
        with self.assertLogs("openemux.core.theme_images", level="WARNING"):
            self.assertIsNone(theme_images.render(bad, 10, 0, "#000000", self.cache))

    def test_the_cache_is_pruned(self):
        with mock.patch.object(theme_images, "CACHE_KEEP", 2):
            outs = [theme_images.render(self.source, dim, 0, "#000000", self.cache)
                    for dim in (10, 20, 30)]
        remaining = sorted(self.cache.glob("*.png"))
        self.assertEqual(len(remaining), 2)
        self.assertIn(outs[-1], remaining)

    def test_a_failed_write_leaves_no_temp_file(self):
        with mock.patch.object(theme_images.os, "replace", side_effect=OSError("full")), \
             self.assertLogs("openemux.core.theme_images", level="WARNING"):
            self.assertIsNone(theme_images.render(self.source, 10, 0, "#000000", self.cache))
        self.assertEqual(list(self.cache.glob(".*")), [])

    def test_protected_files_survive_pruning(self):
        with mock.patch.object(theme_images, "CACHE_KEEP", 1):
            first = theme_images.render(self.source, 10, 0, "#000000", self.cache)
            theme_images.render(self.source, 20, 0, "#000000", self.cache, protect=[first])
        self.assertTrue(first.is_file())

    def test_prune_of_a_missing_folder(self):
        theme_images._prune(self.tmp / "nowhere", keep=None)

    def test_prune_survives_a_listing_error(self):
        with mock.patch.object(theme_images.Path, "glob", side_effect=OSError("gone")):
            theme_images._prune(self.cache, keep=None)

    def test_average_of_nothing(self):
        self.assertIsNone(theme_images.average_color(self.tmp / "missing.png"))


if __name__ == "__main__":
    unittest.main()
