"""The demo-library generator (issues #523 and #551): tools/demo_library.py.

Loaded by file path -- tools/ is not a package. The pure parts (catalogue,
palettes, scenes, geometry, title layout, file layout) are checked directly;
each era renderer for what makes it that era; the rendering for what the
published images depend on: every file lands where the app looks, and two
runs write the same bytes.
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

#: Words of real franchises a parody title must not borrow (#551).
_FRANCHISES = [
    "mario", "luigi", "sonic", "zelda", "link", "kirby", "pokemon", "pokémon", "pikachu",
    "metroid", "mega man", "megaman", "street fighter", "mortal kombat", "tetris", "pac",
    "donkey kong", "final fantasy", "dragon quest", "castlevania", "contra", "yoshi",
    "star fox", "starwing", "chrono", "earthbound", "golden axe", "streets of rage",
    "crash", "spyro", "tekken", "resident evil", "silent hill", "metal gear", "parappa",
    "banjo", "goldeneye", "bomberman", "frogger", "galaga", "wario", "ace attorney",
]

#: The counts the published frames are built around.
_COUNTS = {"FC": 12, "SFC": 30, "GB": 12, "GBC": 12, "GBA": 30, "N64": 12,
           "NDS": 12, "MD": 12, "SMS": 1, "PS": 12}


def _webp_writable():
    """Whether this GdkPixbuf can save WebP; the CI runners' cannot."""
    return any(f.get_name() == "webp" and f.is_writable()
               for f in demo_library.GdkPixbuf.Pixbuf.get_formats())


#: A library small enough to render in a blink, for the CLI and wall tests.
_SMALL = {"GBA": ["Cosmic Fox Pilot", "Knight Of Hearts"], "PS": ["Eternal Crystal Saga"]}


def _all_titles():
    return [title for titles in demo_library.TITLES.values() for title in titles]


def _fills(svg):
    return set(re.findall(r'fill="(#[0-9a-f]{6})"', svg))


class TitlesTest(unittest.TestCase):
    def test_every_console_is_a_canonical_system_id(self):
        for console in demo_library.TITLES:
            self.assertIn(console, SYSTEM_IDS)
            self.assertIn(console, demo_library.ERA)
            self.assertIn(console, demo_library.ERA_STYLE)

    def test_titles_are_unique_and_non_empty(self):
        titles = _all_titles()
        self.assertTrue(all(t.strip() for t in titles))
        lowered = [t.lower() for t in titles]
        self.assertEqual(len(lowered), len(set(lowered)))

    def test_titles_are_one_to_four_words_and_fit(self):
        for title in _all_titles():
            self.assertIn(len(title.split()), (1, 2, 3, 4), title)
            self.assertLessEqual(len(title), 22, title)

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
        self.assertEqual(counts, _COUNTS)
        for console in demo_library.WALL:
            self.assertGreaterEqual(counts[console], 9, console)

    def test_every_title_has_a_genre_and_every_genre_a_title(self):
        self.assertEqual(set(demo_library.GENRE), set(_all_titles()))
        self.assertEqual(set(demo_library.GENRE.values()), set(demo_library.SCENES))

    def test_no_console_leans_on_one_genre(self):
        for console, titles in demo_library.TITLES.items():
            genres = [demo_library.GENRE[t] for t in titles]
            self.assertLessEqual(max(genres.count(g) for g in genres), 4, console)

    def test_titles_borrow_no_brand_or_franchise(self):
        for title in _all_titles():
            words = f" {title.lower()} "
            for name in _BRANDS + _FRANCHISES:
                self.assertNotIn(f" {name} ", words, title)

    def test_pixel_titles_have_every_glyph(self):
        for console, titles in demo_library.TITLES.items():
            if demo_library.ERA_STYLE[console][0] == "pixel":
                for title in titles:
                    self.assertTrue(set(title.upper()) <= set(demo_library.FONT_5X7), title)

    def test_era_never_names_a_console_or_a_company(self):
        for era in demo_library.ERA.values():
            for brand in _BRANDS:
                self.assertNotIn(brand, era.lower())

    def test_favorites_are_demo_titles(self):
        for console, title in demo_library.FAVORITES:
            self.assertIn(title, demo_library.TITLES[console])

    def test_slug(self):
        self.assertEqual(demo_library.slug("Robot Man X"), "robot-man-x")
        self.assertEqual(demo_library.slug("Super Plumber Man 3D"), "super-plumber-man-3d")

    def test_rom_filename_uses_the_first_extension(self):
        for console in demo_library.TITLES:
            name = demo_library.rom_filename("Robot Man X", console)
            self.assertEqual(name, f"Robot Man X (World){get_supported_extensions(console)[0]}")
        self.assertEqual(demo_library.rom_filename("Super Plumber Man", "FC"), "Super Plumber Man (World).nes")


class PaletteTest(unittest.TestCase):
    def _variants(self):
        return [(name, i, pal) for name, variants in demo_library.PALETTES.items()
                for i, pal in enumerate(variants)]

    def test_contrast_ratio_extremes(self):
        self.assertAlmostEqual(demo_library.contrast_ratio("#000000", "#ffffff"), 21.0, places=2)
        self.assertAlmostEqual(demo_library.contrast_ratio("#777777", "#777777"), 1.0)
        # Symmetric: the argument order does not matter.
        self.assertEqual(
            demo_library.contrast_ratio("#1a5fb4", "#ffffff"),
            demo_library.contrast_ratio("#ffffff", "#1a5fb4"),
        )

    def test_mix_and_shade(self):
        self.assertEqual(demo_library.mix("#000000", "#ffffff", 0.5), "#808080")
        self.assertEqual(demo_library.mix("#102030", "#ffffff", 0), "#102030")
        self.assertEqual(demo_library.shade("#808080", 1), "#ffffff")
        self.assertEqual(demo_library.shade("#808080", -1), "#000000")
        self.assertEqual(demo_library.shade("#808080", 0), "#808080")

    def test_every_variant_paints_every_role(self):
        for name, i, pal in self._variants():
            self.assertEqual(set(pal), set(demo_library.ROLES), (name, i))
            for colour in pal.values():
                self.assertRegex(colour, r"^#[0-9a-f]{6}$")

    def test_every_title_reads_on_its_plate(self):
        for name, i, pal in self._variants():
            self.assertGreaterEqual(demo_library.contrast_ratio(pal["ink"], pal["plate"]), 4.5, (name, i))

    def test_era_reads_on_its_band(self):
        # The era word is 26 px bold: large text, so WCAG asks 3:1.
        for name, i, pal in self._variants():
            self.assertGreaterEqual(demo_library.contrast_ratio(pal["era"], pal["band"]), 3.0, (name, i))

    def test_pixel_sets_keep_to_their_hardware_colours(self):
        for name, allowed in demo_library.PIXEL_COLOURS.items():
            used = {c for pal in demo_library.PALETTES[name] for c in pal.values()}
            self.assertLessEqual(used, allowed, name)
        self.assertEqual(demo_library.PIXEL_COLOURS["dmg"], {"#0f380f", "#306230", "#8bac0f", "#9bbc0f"})
        self.assertLessEqual(len(demo_library.PIXEL_COLOURS["gbc"]), 16)

    def test_neighbours_never_share_a_ground(self):
        for console, titles in demo_library.TITLES.items():
            grounds = [demo_library.palette_for(console, i)["sky"] for i in range(len(titles))]
            for left, right in zip(grounds, grounds[1:]):
                self.assertNotEqual(left, right, console)

    def test_neighbours_differ_in_lightness(self):
        # Hue alone is not enough for everyone to tell two cards apart.
        for console, titles in demo_library.TITLES.items():
            grounds = [demo_library.palette_for(console, i)["sky"] for i in range(len(titles))]
            for left, right in zip(grounds, grounds[1:]):
                self.assertGreater(demo_library.contrast_ratio(left, right), 1.5, (console, left, right))

    def test_consoles_open_on_different_colours(self):
        firsts = [demo_library.palette_for(c, 0)["sky"] for c in demo_library.TITLES]
        self.assertGreater(len(set(firsts)), len(firsts) // 2)


class GeometryTest(unittest.TestCase):
    def test_bbox_of_each_kind(self):
        self.assertEqual(demo_library.bbox(demo_library.R(1, 2, 3, 4, "sky")), (1, 2, 4, 6))
        self.assertEqual(demo_library.bbox(demo_library.E(5, 5, 2, 1, "sky")), (3, 4, 7, 6))
        self.assertEqual(demo_library.bbox(demo_library.P([(0, 1), (4, 0), (2, 3)], "sky")), (0, 0, 4, 3))

    def test_contains_rect_is_half_open(self):
        rect = demo_library.R(0, 0, 10, 10, "sky")
        self.assertTrue(demo_library.contains(rect, 0, 0))
        self.assertTrue(demo_library.contains(rect, 5, 9.9))
        self.assertFalse(demo_library.contains(rect, 10, 5))
        self.assertFalse(demo_library.contains(rect, -1, 5))

    def test_contains_ellipse(self):
        ellipse = demo_library.E(0, 0, 4, 2, "sky")
        self.assertTrue(demo_library.contains(ellipse, 0, 0))
        self.assertTrue(demo_library.contains(ellipse, 4, 0))  # on the edge
        self.assertFalse(demo_library.contains(ellipse, 3, 1.9))

    def test_contains_polygon(self):
        triangle = demo_library.P([(0, 0), (10, 0), (0, 10)], "sky")
        self.assertTrue(demo_library.contains(triangle, 2, 2))
        self.assertFalse(demo_library.contains(triangle, 8, 8))
        self.assertFalse(demo_library.contains(triangle, -1, 5))
        # Even-odd: a concave "U" leaves its notch outside.
        u = demo_library.P([(0, 0), (3, 0), (3, 5), (7, 5), (7, 0), (10, 0), (10, 10), (0, 10)], "sky")
        self.assertFalse(demo_library.contains(u, 5, 2))
        self.assertTrue(demo_library.contains(u, 5, 8))

    def test_mirror_flips_each_kind(self):
        w = demo_library.SCENE_W
        self.assertEqual(demo_library.mirror(demo_library.R(10, 2, 5, 4, "sky")).geom, (w - 15, 2, 5, 4))
        self.assertEqual(demo_library.mirror(demo_library.E(10, 2, 5, 4, "sky")).geom, (w - 10, 2, 5, 4))
        self.assertEqual(demo_library.mirror(demo_library.P([(10, 2)], "sky")).geom, ((w - 10, 2),))

    def test_runs_merge_equal_neighbours(self):
        self.assertEqual(demo_library.runs("aaa"), [(0, 3, "a")])
        self.assertEqual(demo_library.runs("abab"), [(0, 1, "a"), (1, 1, "b"), (2, 1, "a"), (3, 1, "b")])
        self.assertEqual(demo_library.runs("aabbb"), [(0, 2, "a"), (2, 3, "b")])
        self.assertEqual(demo_library.runs(""), [])

    def test_polygon_of_each_kind(self):
        self.assertEqual(len(demo_library.polygon_of(demo_library.R(0, 0, 2, 2, "sky"))), 4)
        self.assertEqual(len(demo_library.polygon_of(demo_library.E(0, 0, 10, 5, "sky"))), 8)
        self.assertEqual(len(demo_library.polygon_of(demo_library.E(0, 0, 2, 2, "sky"))), 6)
        points = [(0, 0), (1, 0), (0, 1)]
        self.assertEqual(demo_library.polygon_of(demo_library.P(points, "sky")), points)

    def test_facets_face_the_light(self):
        square = demo_library.polygon_of(demo_library.R(0, 0, 10, 10, "sky"))
        lights = {tuple(sorted({p for p in tri[1:]})): light for tri, light in demo_library.facets(square)}
        top, bottom = lights[((0, 0), (10, 0))], lights[((0, 10), (10, 10))]
        left, right = lights[((0, 0), (0, 10))], lights[((10, 0), (10, 10))]
        self.assertGreater(top, bottom)   # the light comes from above...
        self.assertGreater(left, right)   # ...and from the left
        for _tri, light in demo_library.facets(square):
            self.assertLessEqual(abs(light), 1)

    def test_facets_survive_a_degenerate_polygon(self):
        self.assertEqual([light for _t, light in demo_library.facets([(1, 1), (1, 1)])], [0, 0])


class SceneTest(unittest.TestCase):
    def test_every_scene_has_a_backdrop_and_a_focal_point(self):
        for genre, builder in demo_library.SCENES.items():
            for index in range(3):
                shapes = builder(index)
                self.assertEqual(shapes[0], demo_library.R(0, 0, demo_library.SCENE_W, demo_library.SCENE_H, "sky"))
                self.assertTrue(any(s.focal for s in shapes), genre)
                for shape in shapes:
                    self.assertIn(shape.role, demo_library.ROLES, genre)
                    self.assertIn(shape.kind, ("rect", "ellipse", "poly"))

    def test_scenes_vary_by_index(self):
        for genre, builder in demo_library.SCENES.items():
            self.assertNotEqual(builder(0), builder(1), genre)

    def test_odd_titles_are_mirrored(self):
        title = "Robot Man X"
        even, odd = demo_library.scene(title, 0), demo_library.scene(title, 1)
        self.assertEqual(odd, [demo_library.mirror(s) for s in demo_library.SCENES["action"](1)])
        self.assertEqual(even, demo_library.SCENES["action"](0))

    def test_figures_take_every_pose(self):
        for pose in (0, 1, 2):
            right = demo_library._figure(50, 100, 30, pose=pose)
            left = demo_library._figure(50, 100, 30, pose=pose, facing=-1)
            self.assertTrue(all(s.focal for s in right))
            self.assertNotEqual(right, left)
        self.assertFalse(any(s.focal for s in demo_library._figure(50, 100, 30, focal=False)))

    def test_crop_keeps_the_focal_shapes_in_view(self):
        shapes = demo_library.scene("Robot Man X", 0)
        for aspect in (0.5, 1.0, 1.4, 2.2, 6.6):
            x, y, w, h = demo_library.crop_view(shapes, aspect)
            self.assertAlmostEqual(w / h, aspect, places=6)
            self.assertGreaterEqual(x, 0)
            self.assertGreaterEqual(y, 0)
            self.assertLessEqual(x + w, demo_library.SCENE_W + 1e-9)
            self.assertLessEqual(y + h, demo_library.SCENE_H + 1e-9)

    def test_crop_widens_a_tall_focus_and_heightens_a_wide_one(self):
        tall = [demo_library.R(45, 40, 10, 40, "hero", True)]
        wide = [demo_library.R(30, 60, 40, 5, "hero", True)]
        self.assertAlmostEqual(demo_library.crop_view(tall, 1)[2], 52)
        self.assertAlmostEqual(demo_library.crop_view(wide, 1)[3], 52)

    def test_crop_never_leaves_the_scene(self):
        huge = [demo_library.R(0, 0, demo_library.SCENE_W, demo_library.SCENE_H, "hero", True)]
        x, y, w, h = demo_library.crop_view(huge, 10)
        self.assertEqual(w, demo_library.SCENE_W)
        x, y, w, h = demo_library.crop_view(huge, 0.1)
        self.assertEqual(h, demo_library.SCENE_H)
        corner = [demo_library.R(0, 0, 4, 4, "hero", True)]
        self.assertEqual(demo_library.crop_view(corner, 1)[:2], (0, 0))

    def test_crop_without_a_focal_point_takes_the_whole_scene(self):
        x, y, w, h = demo_library.crop_view([demo_library.R(0, 0, 1, 1, "sky")], 1)
        self.assertEqual(w, demo_library.SCENE_W)


class RendererTest(unittest.TestCase):
    def _cover(self, console, index=0):
        title = demo_library.TITLES[console][index]
        return demo_library.cover_svg(console, index, title)

    def test_every_title_draws_a_cover(self):
        for console, titles in demo_library.TITLES.items():
            for index, title in enumerate(titles):
                svg = demo_library.cover_svg(console, index, title)
                self.assertIn('width="512" height="768"', svg)
                self.assertIn(f">{demo_library.ERA[console]}</text>", svg)

    def test_no_svg_reaches_outside(self):
        for console in demo_library.TITLES:
            svg = self._cover(console)
            for forbidden in ("<filter", "<image", "href="):
                self.assertNotIn(forbidden, svg, console)

    def test_pixel_covers_are_cells_of_the_hardware_palette(self):
        for console in ("FC", "SMS", "GB", "GBC"):
            svg = self._cover(console)
            self.assertIn('shape-rendering="crispEdges"', svg)
            self.assertNotIn("<polygon", svg)
            self.assertNotIn("<ellipse", svg)
            self.assertNotIn("Gradient", svg)
            palette_set = demo_library.ERA_STYLE[console][1]
            self.assertLessEqual(_fills(svg), demo_library.PIXEL_COLOURS[palette_set], console)
        self.assertEqual(_fills(self._cover("GB")) | _fills(self._cover("GB", 1)),
                         {"#0f380f", "#306230", "#8bac0f", "#9bbc0f"})

    def test_pixel_cells_keep_their_size_on_labels(self):
        svg = demo_library.label_svg("FC", 0, "Super Plumber Man", 0.61)
        heights = set(re.findall(r'<rect x="\d+" y="\d+" width="\d+" height="(\d+)"', svg))
        self.assertIn(str(demo_library.CELL["nes"]), heights)

    def test_painted_covers_use_gradients_and_a_rim_light(self):
        for console in ("SFC", "MD"):
            svg = self._cover(console)
            self.assertIn("<linearGradient", svg)
            self.assertIn('fill="url(#sky)"', svg)
            self.assertIn('fill="url(#ground)"', svg)
            self.assertIn(f'stroke="{demo_library.palette_for(console, 0)["light"]}"', svg)
        self.assertIn('stroke-opacity="0.8"', self._cover("SFC"))
        self.assertNotIn('stroke-opacity="0.8"', self._cover("MD"))

    def test_cartoon_shapes_are_outlined(self):
        for console in ("GBA", "NDS"):
            svg = self._cover(console)
            dark = demo_library.palette_for(console, 0)["dark"]
            self.assertGreater(svg.count(f'stroke="{dark}"'), 10)
            self.assertIn(' rx="', svg)  # the rounded plate

    def test_lowpoly_covers_are_facets_only(self):
        for console in ("N64", "PS"):
            svg = self._cover(console)
            self.assertNotIn("<ellipse", svg)
            self.assertIn("<polygon", svg)
            self.assertIn('fill="url(#sky)"', svg)
        self.assertIn("fill-opacity", self._cover("PS"))       # the fog
        self.assertNotIn("fill-opacity", self._cover("N64"))

    def test_render_scene_dispatches_on_the_era(self):
        shapes = demo_library.SCENES["horror"](0)
        view, box = (0, 0, 100, 130), (0, 0, 100, 130)
        for console, marker in [("FC", "crispEdges"), ("SFC", "url(#ground)"), ("GBA", "stroke-linejoin"),
                                ("N64", "<polygon")]:
            pal = demo_library.palette_for(console, 0)
            self.assertIn(marker, demo_library.render_scene(console, shapes, pal, view, box), console)

    def test_pixel_cells_outside_every_shape_take_the_sky(self):
        pal = demo_library.palette_for("FC", 0)
        svg = demo_library.render_pixel([demo_library.R(0, 0, 1, 1, "hero")], pal, (0, 0, 100, 100), (0, 0, 16, 16), 8)
        self.assertIn(f'fill="{pal["sky"]}"', svg)
        self.assertNotIn(f'fill="{pal["hero"]}"', svg)


class TitleTest(unittest.TestCase):
    def test_wrap_keeps_a_short_title_on_one_line(self):
        self.assertEqual(demo_library.wrap("Robot Man X", 12), ["Robot Man X"])

    def test_wrap_balances_two_lines(self):
        self.assertEqual(demo_library.wrap("The Car Racing Game", 12), ["The Car", "Racing Game"])
        self.assertEqual(demo_library.wrap("Hip Hop Step", 8), ["Hip Hop", "Step"])

    def test_wrap_leaves_a_single_long_word_alone(self):
        self.assertEqual(demo_library.wrap("Supercalifragilistic", 5), ["Supercalifragilistic"])

    def test_pixel_text_measures_six_cells_a_glyph(self):
        self.assertEqual(demo_library.pixel_text_width("A", 4), 20)
        self.assertEqual(demo_library.pixel_text_width("AB", 4), 44)

    def test_pixel_text_draws_capitals(self):
        self.assertEqual(demo_library.pixel_text(["i"], 0, 0, 2, "#000000"),
                         demo_library.pixel_text(["I"], 0, 0, 2, "#000000"))
        # "I": a three-cell bar on top, one cell for five rows, a bar again.
        self.assertEqual(demo_library.pixel_text(["I"], 0, 0, 1, "#000000").count("<rect"), 7)

    def test_pixel_text_refuses_a_missing_glyph(self):
        with self.assertRaises(ValueError):
            demo_library.pixel_text(["Salt & Pepper"], 0, 0, 2, "#000000")

    def test_every_glyph_is_five_by_seven(self):
        for char, rows in demo_library.FONT_5X7.items():
            self.assertEqual(len(rows), 7, char)
            self.assertTrue(all(len(r) == 5 and set(r) <= {"0", "1"} for r in rows), char)

    def test_layout_prefers_the_larger_title(self):
        lines, size, _w, _h = demo_library.title_layout("The Car Racing Game", "painted", 464, 170, 46)
        self.assertEqual(lines, ["The Car", "Racing Game"])
        lines, _size, _w, _h = demo_library.title_layout("Robot Man X", "painted", 464, 170, 46)
        self.assertEqual(lines, ["Robot Man X"])
        lines, cell, w, h = demo_library.title_layout("Super Plumber Man", "pixel", 464, 170, 6)
        self.assertEqual(len(lines), 2)
        self.assertLessEqual(cell, 6)
        self.assertLessEqual(w, 464)
        self.assertLessEqual(h, 170)

    def test_layout_fits_its_box(self):
        for renderer in ("pixel", "painted"):
            for title in _all_titles():
                _lines, size, w, h = demo_library.title_layout(title, renderer, 280, 120, 46)
                self.assertGreater(size, 0, title)
                self.assertLessEqual(w, 281, (renderer, title))
                self.assertLessEqual(h, 121, (renderer, title))

    def test_titles_are_escaped(self):
        with mock.patch.dict(demo_library.GENRE, {"Salt & Pepper": "puzzle"}):
            svg = demo_library.cover_svg("SFC", 0, "Salt & Pepper")
        self.assertIn(">Salt &amp; Pepper</text>", svg)
        self.assertNotIn("& ", svg)

    def test_cover_title_sits_bottom_left_on_a_plate(self):
        svg = demo_library.cover_svg("SFC", 0, "Robot Man X")
        pal = demo_library.palette_for("SFC", 0)
        plate = re.search(rf'<rect x="(\d+)" y="(\d+)" width="(\d+)" height="(\d+)" fill="{pal["plate"]}"/>', svg)
        x, y, _w, h = map(int, plate.groups())
        self.assertEqual(x, 24)
        self.assertEqual(y + h, demo_library.COVER_H - 28)

    def test_lowpoly_plate_has_a_bevel(self):
        pal = demo_library.palette_for("N64", 0)
        svg = demo_library.title_svg("N64", pal, "Robot Man X", (0, 0, 300, 100))
        self.assertIn(demo_library.shade(pal["plate"], 0.25), svg)
        self.assertIn(demo_library.shade(pal["plate"], -0.25), svg)

    def test_label_size_keeps_the_long_side(self):
        self.assertEqual(demo_library.label_size(2.0), (512, 256))
        self.assertEqual(demo_library.label_size(0.5), (256, 512))

    def test_label_regions(self):
        scene_box, title_box = demo_library.label_regions(512, 233, 2.2)
        self.assertEqual(scene_box[:2], (0, 0))
        self.assertGreater(title_box[0], scene_box[2])  # the title right of the scene
        strip_scene, strip_title = demo_library.label_regions(512, 78, 6.6)
        self.assertLess(strip_scene[2], scene_box[2])
        self.assertGreater(strip_title[2], title_box[2])
        tall_scene, tall_title = demo_library.label_regions(307, 512, 0.6)
        self.assertEqual(tall_scene[2], 307)
        self.assertGreater(tall_title[1], tall_scene[3])  # the title below the scene

    def test_label_svg_shapes(self):
        self.assertIn('width="512" height="233"', demo_library.label_svg("SFC", 0, "Robot Man X", 2.2))
        self.assertIn('width="512" height="78"', demo_library.label_svg("SMS", 0, "Island Kid Hop", 6.6))
        tall = demo_library.label_svg("FC", 0, "Super Plumber Man", 0.6)
        self.assertIn('width="307" height="512"', tall)
        self.assertIn('text-anchor="middle"', demo_library.label_svg("N64", 0, "Super Plumber Man 3D", 0.87))


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
        stem = "Super Plumber Man (World)"
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
            rom = Path(tmp) / "GBA" / "Cosmic Fox Pilot (World).gba"
            self.assertEqual(rom.read_bytes(), b"")
            cover = get_art_path_candidates(Path(tmp), "GBA", rom.stem, COVER_ART)[0]
            data = cover.read_bytes()
            self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
            self.assertEqual(int.from_bytes(data[16:20], "big"), demo_library.COVER_W)
            self.assertEqual(int.from_bytes(data[20:24], "big"), demo_library.COVER_H)
            self.assertIn(data[25], (2, 6))  # RGB / RGBA, never a palette
            for chunk in (b"tEXt", b"tIME", b"zTXt", b"iTXt"):
                self.assertNotIn(chunk, data)

    @unittest.skipUnless(_webp_writable(), "no WebP saver for GdkPixbuf")
    def test_wall_composites_every_label(self):
        with TemporaryDirectory() as tmp, \
                mock.patch.dict(demo_library.TITLES, _SMALL, clear=True), \
                mock.patch.object(demo_library, "WALL", ["GBA"]):
            demo_library.write(Path(tmp) / "roms")
            games = demo_library.wall(Path(tmp) / "roms", Path(tmp) / "carts")
            self.assertEqual(games, {"GBA": ["cosmic-fox-pilot", "knight-of-hearts"]})
            webp = Path(tmp) / "carts" / "gba-cosmic-fox-pilot.webp"
            data = webp.read_bytes()
            self.assertEqual((data[:4], data[8:12]), (b"RIFF", b"WEBP"))

    def test_wall_refuses_a_library_without_labels(self):
        # A wrong roms_dir must not publish a wall of blank cartridges.
        with TemporaryDirectory() as tmp, \
                mock.patch.dict(demo_library.TITLES, _SMALL, clear=True), \
                mock.patch.object(demo_library, "WALL", ["GBA"]):
            with self.assertRaises(FileNotFoundError):
                demo_library.wall(Path(tmp) / "empty", Path(tmp) / "carts")
            self.assertEqual(list((Path(tmp) / "carts").iterdir()), [])


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
        self.assertTrue(playlists.is_favorite(roms / "FC" / "Super Plumber Man (World).nes"))

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
            self.assertTrue((Path(tmp) / "PS" / "Eternal Crystal Saga (World).cue").is_file())

    def test_configure(self):
        home = IsolatedHome()
        config = home.start()
        self.addCleanup(home.stop)
        roms = home.root / "demo"
        with mock.patch("openemux.core.config.ConfigManager", return_value=config):
            output = self._run(str(roms), "--configure")
        self.assertIn("roms_path set in", output)
        self.assertEqual(config.get_roms_path(), roms)

    def test_wall_and_configure_are_exclusive(self):
        with TemporaryDirectory() as tmp, contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                demo_library.main([tmp, "--wall", str(Path(tmp) / "carts"), "--configure"])

    @unittest.skipUnless(_webp_writable(), "no WebP saver for GdkPixbuf")
    def test_wall_reads_the_labels_and_writes_nothing_else(self):
        with TemporaryDirectory() as tmp:
            roms = Path(tmp) / "demo"
            self._run(str(roms))
            label = roms / "GBA" / "labels" / "Cosmic Fox Pilot (World).png"
            before = label.read_bytes()
            output = self._run(str(roms), "--wall", str(Path(tmp) / "carts"))
            self.assertIn('gba: "cosmic-fox-pilot", "knight-of-hearts"', output)
            self.assertNotIn("files written", output)
            self.assertTrue((Path(tmp) / "carts" / "gba-knight-of-hearts.webp").is_file())
            # The wall reads the labels; it never redraws them.
            self.assertEqual(label.read_bytes(), before)

if __name__ == "__main__":
    unittest.main()
