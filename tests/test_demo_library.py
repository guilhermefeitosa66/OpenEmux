"""The demo-library generator (issue #523): tools/demo_library.py.

Loaded by file path -- tools/ is not a package. The pure parts (titles,
palette, file layout, label geometry) are checked directly; the rendering is
checked for what the published images depend on: every file lands where the
app looks, and two runs write the same bytes.
"""

import contextlib
import importlib.util
import io
import re
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from openemux.core.cartridge_render import has_frame, rsvg_available
from openemux.core.scraper import COVER_ART, LABEL_ART, get_art_path_candidates
from openemux.core.systems import SYSTEM_IDS, get_supported_extensions

from tests.isolated_home import IsolatedHome

_TOOL = Path(__file__).parent.parent / "tools" / "demo_library.py"
_spec = importlib.util.spec_from_file_location("demo_library", _TOOL)
demo_library = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(demo_library)

#: Words that would put a console maker or a console's name on a cover.
_BRANDS = [
    "nintendo", "sega", "sony", "playstation", "genesis", "famicom", "nes",
    "snes", "game boy", "gameboy", "advance", "master system", "mega drive",
]

#: A library small enough to render in a blink, for the CLI and wall tests.
_SMALL = {"GBA": ["Moss Knight", "Teacup Tempest"], "PS": ["Paper Pinwheels"]}


def _all_titles():
    return [title for titles in demo_library.TITLES.values() for title in titles]


class TitlesTest(unittest.TestCase):
    def test_every_console_is_a_canonical_system_id(self):
        for console in demo_library.TITLES:
            self.assertIn(console, SYSTEM_IDS)
            self.assertIn(console, demo_library.ERA)

    def test_titles_are_unique_and_non_empty(self):
        titles = _all_titles()
        self.assertTrue(all(t.strip() for t in titles))
        lowered = [t.lower() for t in titles]
        self.assertEqual(len(lowered), len(set(lowered)))

    def test_titles_are_two_or_three_words(self):
        for title in _all_titles():
            self.assertIn(len(title.split()), (2, 3), title)

    def test_titles_are_in_grid_order(self):
        # The grid sorts by name and the palette goes by position: an unsorted
        # list would put two same-coloured covers side by side on screen.
        for console, titles in demo_library.TITLES.items():
            self.assertEqual(titles, sorted(titles), console)

    def test_slugs_are_unique_per_console(self):
        for console, titles in demo_library.TITLES.items():
            slugs = [demo_library.slug(t) for t in titles]
            self.assertEqual(len(slugs), len(set(slugs)), console)
            for value in slugs:
                self.assertRegex(value, r"^[a-z0-9]+(-[a-z0-9]+)*$")

    def test_counts_fill_the_published_frames(self):
        counts = {c: len(t) for c, t in demo_library.TITLES.items()}
        self.assertGreaterEqual(counts["SFC"], 30)
        self.assertGreaterEqual(counts["GBA"], 30)
        self.assertEqual(counts["SMS"], 1)
        for console in demo_library.WALL:
            self.assertGreaterEqual(counts[console], 9, console)

    def test_era_never_names_a_console_or_a_company(self):
        for era in demo_library.ERA.values():
            for brand in _BRANDS:
                self.assertNotIn(brand, era.lower())

    def test_favorites_are_demo_titles(self):
        for console, title in demo_library.FAVORITES:
            self.assertIn(title, demo_library.TITLES[console])

    def test_slug(self):
        self.assertEqual(demo_library.slug("Comet Courier"), "comet-courier")
        self.assertEqual(demo_library.slug("Glacier Grand Prix"), "glacier-grand-prix")

    def test_rom_filename_uses_the_first_extension(self):
        for console in demo_library.TITLES:
            name = demo_library.rom_filename("Comet Courier", console)
            self.assertEqual(name, f"Comet Courier (World){get_supported_extensions(console)[0]}")
        self.assertEqual(demo_library.rom_filename("Comet Courier", "FC"), "Comet Courier (World).nes")


class PaletteTest(unittest.TestCase):
    def test_contrast_ratio_extremes(self):
        self.assertAlmostEqual(demo_library.contrast_ratio("#000000", "#ffffff"), 21.0, places=2)
        self.assertAlmostEqual(demo_library.contrast_ratio("#777777", "#777777"), 1.0)
        # Symmetric: the argument order does not matter.
        self.assertEqual(
            demo_library.contrast_ratio("#1a5fb4", "#ffffff"),
            demo_library.contrast_ratio("#ffffff", "#1a5fb4"),
        )

    def test_every_title_colour_reads_on_its_ground(self):
        for bg, _band, _fg, _fg2, title in demo_library.PALETTE:
            self.assertGreaterEqual(demo_library.contrast_ratio(title, bg), 4.5, (bg, title))

    def test_neighbours_never_share_a_ground(self):
        for console, titles in demo_library.TITLES.items():
            grounds = [demo_library.palette_for(console, i)[0] for i in range(len(titles))]
            for left, right in zip(grounds, grounds[1:]):
                self.assertNotEqual(left, right, console)

    def test_neighbours_differ_in_lightness(self):
        # Hue alone is not enough for everyone to tell two cards apart.
        for console, titles in demo_library.TITLES.items():
            grounds = [demo_library.palette_for(console, i)[0] for i in range(len(titles))]
            for left, right in zip(grounds, grounds[1:]):
                self.assertGreater(demo_library.contrast_ratio(left, right), 1.5, (console, left, right))

    def test_consoles_open_on_different_colours(self):
        firsts = [demo_library.palette_for(c, 0) for c in demo_library.TITLES]
        self.assertGreater(len(set(firsts)), len(firsts) // 2)


class LayoutTest(unittest.TestCase):
    def test_wrap_keeps_a_short_title_on_one_line(self):
        self.assertEqual(demo_library.wrap("Tin Toad", 12), ["Tin Toad"])

    def test_wrap_balances_two_lines(self):
        self.assertEqual(demo_library.wrap("Marble Meadow Rally", 12), ["Marble", "Meadow Rally"])
        self.assertEqual(demo_library.wrap("Comet Courier", 12), ["Comet", "Courier"])

    def test_wrap_leaves_a_single_long_word_alone(self):
        self.assertEqual(demo_library.wrap("Supercalifragilistic", 5), ["Supercalifragilistic"])

    def test_label_size_keeps_the_long_side(self):
        self.assertEqual(demo_library.label_size(2.0), (512, 256))
        self.assertEqual(demo_library.label_size(0.5), (256, 512))

    def test_cover_svg_shape(self):
        svg = demo_library.cover_svg("SFC", 0, "Marble Meadow Rally")
        self.assertIn('width="512" height="768"', svg)
        self.assertIn(">16-BIT</text>", svg)
        self.assertEqual(svg.count("<text"), 3)  # era + two title lines
        self.assertIn(demo_library.palette_for("SFC", 0)[0], svg)

    def test_every_emblem_is_used(self):
        tags = {re.findall(r"<(circle|polygon|rect)", demo_library.cover_svg("GBA", i, "Moss Knight"))[2]
                for i in range(len(demo_library.EMBLEMS))}
        self.assertEqual(tags, {"circle", "polygon", "rect"})

    def test_titles_are_escaped(self):
        svg = demo_library.cover_svg("FC", 0, "Salt & Pepper")
        self.assertIn(">Salt &amp;</text>", svg)
        self.assertNotIn("& ", svg)

    def test_label_svg_wide_window_puts_the_disc_beside_the_title(self):
        svg = demo_library.label_svg("SFC", 0, "Lantern Keep", 2.2)
        self.assertIn('width="512" height="233"', svg)
        self.assertIn('text-anchor="start"', svg)

    def test_label_svg_strip_window_uses_its_height(self):
        wide = demo_library.label_svg("SFC", 0, "Cinder Dash", 2.2)
        strip = demo_library.label_svg("SMS", 0, "Cinder Dash", 6.6)
        size = lambda svg: int(re.search(r'font-size="(\d+)"', svg).group(1))  # noqa: E731
        self.assertIn('width="512" height="78"', strip)
        self.assertGreater(size(strip) / 78, size(wide) / 233)

    def test_label_svg_tall_window_stacks_the_disc_above(self):
        svg = demo_library.label_svg("FC", 0, "Comet Courier", 0.6)
        self.assertIn('width="307" height="512"', svg)
        self.assertIn('text-anchor="middle"', svg)


@unittest.skipUnless(rsvg_available(), "librsvg typelib not installed")
class FramesTest(unittest.TestCase):
    def test_label_aspect_matches_the_frame(self):
        expected = {"SFC": 2.2, "GBA": 1.94, "FC": 0.61, "SMS": 6.6}
        for console, aspect in expected.items():
            self.assertAlmostEqual(demo_library.label_aspect(console), aspect, delta=0.02)

    def test_plan_writes_where_the_app_looks(self):
        roms = Path("/library")
        entries = demo_library.plan(roms)
        by_kind = {}
        for path, kind, _svg in entries:
            by_kind.setdefault(kind, []).append(path)
        total = len(_all_titles())
        self.assertEqual(len(by_kind["rom"]), total)
        self.assertEqual(len(by_kind[COVER_ART]), total)
        framed = sum(len(t) for c, t in demo_library.TITLES.items() if has_frame(c))
        self.assertEqual(len(by_kind[LABEL_ART]), framed)
        stem = "Comet Courier (World)"
        self.assertIn(roms / "FC" / f"{stem}.nes", by_kind["rom"])
        self.assertIn(get_art_path_candidates(roms, "FC", stem, COVER_ART)[0], by_kind[COVER_ART])
        self.assertIn(get_art_path_candidates(roms, "FC", stem, LABEL_ART)[0], by_kind[LABEL_ART])
        # PS has no cartridge frame, so no labels.
        self.assertFalse([p for p in by_kind[LABEL_ART] if p.parts[2] == "PS"])
        for path in by_kind[COVER_ART] + by_kind[LABEL_ART]:
            self.assertEqual(path.suffix, ".png")

    def test_write_is_deterministic(self):
        with TemporaryDirectory() as first, TemporaryDirectory() as second:
            count = demo_library.write(Path(first))
            self.assertEqual(count, demo_library.write(Path(second)))
            files = sorted(p.relative_to(first) for p in Path(first).rglob("*") if p.is_file())
            self.assertEqual(len(files), count)
            for relative in files:
                self.assertEqual(
                    (Path(first) / relative).read_bytes(),
                    (Path(second) / relative).read_bytes(),
                    relative,
                )

    def test_written_art_is_a_bare_truecolor_png(self):
        with TemporaryDirectory() as tmp, mock.patch.dict(demo_library.TITLES, _SMALL, clear=True):
            demo_library.write(Path(tmp))
            rom = Path(tmp) / "GBA" / "Moss Knight (World).gba"
            self.assertEqual(rom.read_bytes(), b"")
            cover = get_art_path_candidates(Path(tmp), "GBA", rom.stem, COVER_ART)[0]
            data = cover.read_bytes()
            self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
            self.assertEqual(int.from_bytes(data[16:20], "big"), demo_library.COVER_W)
            self.assertEqual(int.from_bytes(data[20:24], "big"), demo_library.COVER_H)
            self.assertIn(data[25], (2, 6))  # RGB / RGBA, never a palette
            for chunk in (b"tEXt", b"tIME", b"zTXt", b"iTXt"):
                self.assertNotIn(chunk, data)

    def test_wall_composites_every_label(self):
        with TemporaryDirectory() as tmp, \
                mock.patch.dict(demo_library.TITLES, _SMALL, clear=True), \
                mock.patch.object(demo_library, "WALL", ["GBA"]):
            demo_library.write(Path(tmp) / "roms")
            games = demo_library.wall(Path(tmp) / "roms", Path(tmp) / "carts")
            self.assertEqual(games, {"GBA": ["moss-knight", "teacup-tempest"]})
            webp = Path(tmp) / "carts" / "gba-moss-knight.webp"
            data = webp.read_bytes()
            self.assertEqual((data[:4], data[8:12]), (b"RIFF", b"WEBP"))


class ConfigureTest(unittest.TestCase):
    def setUp(self):
        self.home = IsolatedHome()
        self.config = self.home.start()
        self.addCleanup(self.home.stop)

    def test_sets_roms_path_and_marks_favorites(self):
        from openemux.core.playlist_manager import PlaylistManager

        roms = self.home.root / "demo"
        demo_library.configure(roms, self.config)
        self.assertEqual(self.config.get_roms_path(), roms)
        playlists = PlaylistManager(self.config, None)
        self.assertEqual(len(playlists.list_favorite_paths()), len(demo_library.FAVORITES))
        self.assertTrue(playlists.is_favorite(roms / "FC" / "Comet Courier (World).nes"))

    def test_rerunning_keeps_the_favorites(self):
        from openemux.core.playlist_manager import PlaylistManager

        roms = self.home.root / "demo"
        demo_library.configure(roms, self.config)
        demo_library.configure(roms, self.config)
        favorites = PlaylistManager(self.config, None).list_favorite_paths()
        self.assertEqual(len(favorites), len(demo_library.FAVORITES))

    def test_defaults_to_the_users_config(self):
        with mock.patch("openemux.core.config.ConfigManager", return_value=self.config):
            self.assertIs(demo_library.configure(self.home.root / "demo"), self.config)


@unittest.skipUnless(rsvg_available(), "librsvg typelib not installed")
class MainTest(unittest.TestCase):
    def _run(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), \
                mock.patch.dict(demo_library.TITLES, _SMALL, clear=True), \
                mock.patch.object(demo_library, "WALL", ["GBA"]):
            self.assertEqual(demo_library.main(list(args)), 0)
        return out.getvalue()

    def test_writes_the_library(self):
        with TemporaryDirectory() as tmp:
            output = self._run(tmp)
            self.assertIn("files written", output)
            self.assertTrue((Path(tmp) / "PS" / "Paper Pinwheels (World).cue").is_file())

    def test_configure_and_wall(self):
        home = IsolatedHome()
        config = home.start()
        self.addCleanup(home.stop)
        roms = home.root / "demo"
        with mock.patch("openemux.core.config.ConfigManager", return_value=config):
            output = self._run(str(roms), "--configure", "--wall", str(home.root / "carts"))
        self.assertIn("roms_path set in", output)
        self.assertIn('gba: "moss-knight", "teacup-tempest"', output)
        self.assertEqual(config.get_roms_path(), roms)
        self.assertTrue((home.root / "carts" / "gba-teacup-tempest.webp").is_file())


if __name__ == "__main__":
    unittest.main()
