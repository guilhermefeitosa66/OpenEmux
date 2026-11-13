import unittest
import unittest.mock
from pathlib import Path
from tempfile import TemporaryDirectory

from openemux.core import cartridge_render
from openemux.core.cartridge_render import (
    CartridgeFrame,
    CartridgeFrameError,
    load_frame,
    render_cartridge,
    rsvg_available,
)

FRAME = (
    Path(__file__).resolve().parents[1]
    / "src" / "openemux" / "ui" / "assets" / "images" / "cartridges" / "GB.svg"
)

# A frame whose label object is a rotated rect named only by inkscape:label,
# so both the label lookup and non-axis-aligned shapes are exercised.
FIXTURE_SVG = """<?xml version="1.0"?>
<svg xmlns="http://www.w3.org/2000/svg"
     xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"
     width="100" height="50" viewBox="0 0 100 50">
  <rect id="marker" inkscape:label="label-clip" x="20" y="10" width="40" height="20"
        transform="rotate(10 40 20)" fill="#00ff00"/>
  <rect id="art" x="0" y="40" width="100" height="10" fill="#112233"/>
</svg>
"""


def _write_cover(path, size=(64, 64), color=(255, 0, 0)):
    """Minimal solid-colour PNG, written with the same stack the app uses."""
    import gi

    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf

    pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, *size)
    r, g, b = color
    pixbuf.fill((r << 24) | (g << 16) | (b << 8) | 0xFF)
    pixbuf.savev(str(path), "png", [], [])
    return path


@unittest.skipUnless(rsvg_available(), "librsvg typelib (gir1.2-rsvg-2.0) not installed")
class CartridgeFrameTests(unittest.TestCase):
    def test_ships_frame_exposes_intrinsic_size_and_clip(self):
        frame = CartridgeFrame(FRAME)
        self.assertEqual((frame.width, frame.height), (177.0, 200.0))
        self.assertEqual(frame.size_for_width(200), (200, 226))

    def test_label_object_found_by_inkscape_label(self):
        with TemporaryDirectory() as tmp:
            svg = Path(tmp) / "X.svg"
            svg.write_text(FIXTURE_SVG)
            frame = CartridgeFrame(svg)
            self.assertEqual(frame.clip_id, "marker")

    def test_label_bbox_scales_with_output_size(self):
        with TemporaryDirectory() as tmp:
            svg = Path(tmp) / "X.svg"
            svg.write_text(FIXTURE_SVG)
            frame = CartridgeFrame(svg)
            x1, y1, w1, h1 = frame._label_bbox(100, 50)
            x2, y2, w2, h2 = frame._label_bbox(200, 100)
            self.assertAlmostEqual(w2, w1 * 2, places=3)
            self.assertAlmostEqual(x2, x1 * 2, places=3)
            # Rotated, so the bbox is wider than the rect's own 40x20.
            self.assertGreater(w1, 40)

    def test_the_marker_is_found_by_id_before_the_inkscape_label(self):
        # Authoring tools set one or the other; the id is the stable one.
        with TemporaryDirectory() as tmp:
            svg = Path(tmp) / "X.svg"
            svg.write_text(
                '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="50">'
                '<rect id="label-clip" x="10" y="10" width="40" height="20"/>'
                "</svg>"
            )
            self.assertEqual(CartridgeFrame(svg).clip_id, "label-clip")

    def test_a_marker_with_no_id_at_all_is_rejected(self):
        # The id is what the second render pass hides the marker by.
        with TemporaryDirectory() as tmp:
            svg = Path(tmp) / "X.svg"
            svg.write_text(
                '<svg xmlns="http://www.w3.org/2000/svg"'
                ' xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"'
                ' width="100" height="50">'
                '<rect inkscape:label="label-clip" x="10" y="10" width="40" height="20"/>'
                "</svg>"
            )
            with self.assertRaises(CartridgeFrameError):
                CartridgeFrame(svg)

    def test_a_frame_with_no_size_of_its_own_is_rejected(self):
        # Everything downstream scales from it, so there is nothing to do.
        with TemporaryDirectory() as tmp:
            svg = Path(tmp) / "X.svg"
            svg.write_text(
                '<svg xmlns="http://www.w3.org/2000/svg">'
                '<rect id="label-clip" x="10" y="10" width="40" height="20"/>'
                "</svg>"
            )
            with self.assertRaises(CartridgeFrameError):
                CartridgeFrame(svg)

    def test_missing_marker_is_rejected(self):
        with TemporaryDirectory() as tmp:
            svg = Path(tmp) / "X.svg"
            svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"/>')
            with self.assertRaises(CartridgeFrameError):
                CartridgeFrame(svg)

    def test_cover_lands_inside_the_label_and_never_outside(self):
        with TemporaryDirectory() as tmp:
            cover = _write_cover(Path(tmp) / "c.png", color=(255, 0, 0))
            frame = CartridgeFrame(FRAME)
            surface = frame.render(str(cover), width=177)
            self.assertEqual((surface.get_width(), surface.get_height()), (177, 200))

            data = surface.get_data()
            stride = surface.get_stride()

            def pixel(x, y):
                offset = y * stride + x * 4
                b, g, r, a = data[offset:offset + 4]
                return r, g, b, a

            bx, by, bw, bh = frame._label_bbox(177, 200)
            centre = pixel(int(bx + bw / 2), int(by + bh / 2))
            self.assertGreater(centre[0], 200)  # red cover shows through
            self.assertLess(centre[1], 60)
            # A point well outside the label is cartridge art, not cover.
            self.assertLess(pixel(int(bx + bw / 2), 5)[0] - pixel(int(bx + bw / 2), 5)[2], 40)


@unittest.skipUnless(rsvg_available(), "librsvg typelib (gir1.2-rsvg-2.0) not installed")
class CartridgeCacheTests(unittest.TestCase):
    def test_cold_render_then_cache_hit(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            cover = _write_cover(base / "c.png")
            first = render_cartridge(str(cover), FRAME, "GB", "Game", 100, cache_dir=base / "cache")
            self.assertIsNotNone(first)
            self.assertTrue(first.exists())
            stamp = first.stat().st_mtime_ns
            second = render_cartridge(str(cover), FRAME, "GB", "Game", 100, cache_dir=base / "cache")
            self.assertEqual(first, second)
            self.assertEqual(stamp, second.stat().st_mtime_ns)

    def test_replacing_the_cover_invalidates_the_composite(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            cover = _write_cover(base / "c.png", color=(255, 0, 0))
            first = render_cartridge(str(cover), FRAME, "GB", "Game", 100, cache_dir=base / "cache")
            _write_cover(cover, size=(32, 32), color=(0, 0, 255))
            second = render_cartridge(str(cover), FRAME, "GB", "Game", 100, cache_dir=base / "cache")
            self.assertNotEqual(first, second)
            self.assertTrue(second.exists())

    def test_a_zoom_round_trip_renders_nothing_twice(self):
        # Issue 902: the composite of the previous width used to be deleted
        # after every write, so stepping the zoom back re-rendered the shelf.
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            cover = _write_cover(base / "c.png")
            cache = base / "cache"
            small = render_cartridge(str(cover), FRAME, "GB", "Game", 100, cache_dir=cache)
            large = render_cartridge(str(cover), FRAME, "GB", "Game", 150, cache_dir=cache)
            self.assertNotEqual(small, large)
            self.assertTrue(small.exists())
            self.assertTrue(large.exists())
            stamp = small.stat().st_mtime_ns
            self.assertEqual(
                render_cartridge(str(cover), FRAME, "GB", "Game", 100, cache_dir=cache), small
            )
            self.assertEqual(small.stat().st_mtime_ns, stamp)

    def test_the_display_scale_sets_the_pixel_size_and_its_own_file(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            frame = load_frame(FRAME)
            at_1x = frame.render(None, width=100, scale=1)
            at_2x = frame.render(None, width=100, scale=2)
            self.assertEqual(at_1x.get_width(), 100)
            self.assertEqual(at_2x.get_width(), 200)
            one = render_cartridge(None, FRAME, "GB", "Game", 100, scale=1, cache_dir=base)
            two = render_cartridge(None, FRAME, "GB", "Game", 100, scale=2, cache_dir=base)
            self.assertNotEqual(one, two)
            self.assertTrue(one.exists() and two.exists())

    def test_blank_cartridge_without_cover(self):
        with TemporaryDirectory() as tmp:
            out = render_cartridge(None, FRAME, "GB", "Game", 100, cache_dir=Path(tmp))
            self.assertIsNotNone(out)
            self.assertTrue(out.exists())

    def test_parallel_renders_do_not_collide(self):
        """The grid fills cards from several threads at once.

        Two failures used to show up here: sharing one Rsvg handle across
        threads aborts the process with a Rust BorrowMutError panic, and every
        cover-less ROM raced on the same temporary file.
        """
        from concurrent.futures import ThreadPoolExecutor

        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            cover = _write_cover(base / "c.png")
            cache = base / "cache"
            cartridge_render._FRAMES.clear()

            def render(index):
                path = str(cover) if index % 2 else None
                return render_cartridge(path, FRAME, "GB", f"Game {index}", 120, cache_dir=cache)

            with ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(render, range(24)))

            self.assertTrue(all(r is not None and r.exists() for r in results))
            self.assertFalse(list(cache.glob("**/*.tmp")))

    def test_unusable_frame_degrades_to_none(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            svg = base / "Broken.svg"
            svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"/>')
            self.assertIsNone(load_frame(svg))
            self.assertIsNone(load_frame(base / "does-not-exist.svg"))
            self.assertIsNone(render_cartridge(None, svg, "GB", "Game", cache_dir=base / "cache"))


class TwoThreadsReplacingTheSameFileTests(unittest.TestCase):
    """Windows refuses a replace that races another one onto the same target."""

    def _refused(self, *_args):
        raise PermissionError(5, "Access is denied")

    def test_a_refused_replace_onto_a_written_target_keeps_that_target(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            target = base / "a.png"
            target.write_bytes(b"theirs")
            mine = base / "a.png.1.2.tmp"
            mine.write_bytes(b"mine")
            with unittest.mock.patch.object(Path, "replace", self._refused):
                cartridge_render._move_into_place(mine, target)
            self.assertEqual(target.read_bytes(), b"theirs")
            self.assertFalse(mine.exists())

    def test_a_temporary_file_that_will_not_go_is_left_behind(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            target = base / "a.png"
            target.write_bytes(b"theirs")
            with unittest.mock.patch.object(Path, "replace", self._refused), \
                    unittest.mock.patch.object(Path, "unlink", self._refused):
                cartridge_render._move_into_place(base / "a.png.1.2.tmp", target)
            self.assertEqual(target.read_bytes(), b"theirs")

    def test_a_refused_replace_with_no_target_is_a_failed_render(self):
        cartridge_render._FRAMES.clear()
        with TemporaryDirectory() as tmp:
            with unittest.mock.patch.object(Path, "replace", self._refused), \
                    self.assertLogs("openemux.core.cartridge_render", "WARNING"):
                result = render_cartridge(None, FRAME, "GB", "Game", 120,
                                          cache_dir=Path(tmp) / "cache")
            self.assertIsNone(result)


class RsvgUnavailableTests(unittest.TestCase):
    def test_frame_creation_reports_missing_typelib(self):
        original = cartridge_render.Rsvg
        cartridge_render.Rsvg = None
        cartridge_render._FRAMES.clear()
        try:
            self.assertFalse(cartridge_render.rsvg_available())
            with self.assertRaises(CartridgeFrameError):
                CartridgeFrame(FRAME)
            self.assertIsNone(load_frame(FRAME))
        finally:
            cartridge_render.Rsvg = original
            cartridge_render._FRAMES.clear()


class DroppingAGamesCompositesTests(unittest.TestCase):
    """A renamed or deleted ROM would otherwise leave its cartridge behind."""

    def test_a_console_with_no_cache_directory_has_nothing_to_drop(self):
        with TemporaryDirectory() as tmp_dir:
            self.assertEqual(
                cartridge_render.drop_cached("GB", "Kirby", cache_dir=Path(tmp_dir)), 0
            )

    def test_the_games_own_composites_go_and_the_rest_stay(self):
        with TemporaryDirectory() as tmp_dir:
            directory = Path(tmp_dir) / "GB"
            directory.mkdir(parents=True)
            mine = directory / "Kirby.0123456789ab.png"
            another = directory / "Zelda.0123456789ab.png"
            not_a_composite = directory / "Kirby.txt"
            for path in (mine, another, not_a_composite):
                path.write_bytes(b"png")

            dropped = cartridge_render.drop_cached(
                "GB", "Kirby", cache_dir=Path(tmp_dir)
            )

            self.assertEqual(dropped, 1)
            self.assertFalse(mine.exists())
            self.assertTrue(another.exists())
            self.assertTrue(not_a_composite.exists())

    def test_a_cover_that_left_the_disk_renders_nothing(self):
        # The key is content-addressed, so a cover that is gone has no key.
        with TemporaryDirectory() as tmp_dir:
            self.assertIsNone(
                render_cartridge(
                    Path(tmp_dir) / "gone.png",
                    FRAME,
                    "GB",
                    "Game",
                    cache_dir=Path(tmp_dir),
                )
            )

    def test_a_composite_that_will_not_delete_is_not_counted(self):
        with TemporaryDirectory() as tmp_dir:
            directory = Path(tmp_dir) / "GB"
            directory.mkdir(parents=True)
            (directory / "Kirby.0123456789ab.png").write_bytes(b"png")

            with unittest.mock.patch.object(
                Path, "unlink", side_effect=OSError("read-only")
            ):
                dropped = cartridge_render.drop_cached(
                    "GB", "Kirby", cache_dir=Path(tmp_dir)
                )

        self.assertEqual(dropped, 0)


@unittest.skipUnless(rsvg_available(), "librsvg typelib (gir1.2-rsvg-2.0) not installed")
class ARenderThatGoesWrongTests(unittest.TestCase):
    """It runs on the cover-fetch worker; an escape empties the card (#232)."""

    def test_a_frame_that_raises_mid_render_falls_back_to_no_cartridge(self):
        with TemporaryDirectory() as tmp_dir:
            frame = load_frame(FRAME)
            with unittest.mock.patch.object(
                cartridge_render, "load_frame", return_value=frame
            ), unittest.mock.patch.object(
                frame, "render", side_effect=RuntimeError("no cairo bridge")
            ):
                with self.assertLogs("openemux.core.cartridge_render", level="WARNING"):
                    self.assertIsNone(
                        render_cartridge(
                            None, FRAME, "GB", "Game", 100, cache_dir=Path(tmp_dir)
                        )
                    )


@unittest.skipUnless(rsvg_available(), "librsvg typelib (gir1.2-rsvg-2.0) not installed")
class TheFramesOwnGeometryTests(unittest.TestCase):
    def test_the_aspect_is_the_silhouettes_own(self):
        frame = CartridgeFrame(FRAME)
        self.assertAlmostEqual(frame.aspect, frame.width / frame.height)

    def test_a_label_that_cannot_be_measured_is_reported(self):
        frame = CartridgeFrame(FRAME)
        with unittest.mock.patch.object(
            frame._full, "get_geometry_for_layer", return_value=(False, None, None)
        ):
            with self.assertRaises(CartridgeFrameError):
                frame._label_bbox(200, 200)


@unittest.skipUnless(rsvg_available(), "librsvg typelib (gir1.2-rsvg-2.0) not installed")
class ACoverThatCannotBeScaledTests(unittest.TestCase):
    def test_a_file_that_is_not_an_image_is_not_drawn(self):
        with TemporaryDirectory() as tmp_dir:
            not_an_image = Path(tmp_dir) / "cover.png"
            not_an_image.write_bytes(b"not a png at all")
            with self.assertLogs("openemux.core.cartridge_render", level="WARNING"):
                self.assertIsNone(
                    CartridgeFrame._scaled_cover(not_an_image, 100, 100)
                )

    def test_an_image_with_no_pixels_is_not_drawn(self):
        with unittest.mock.patch.object(
            cartridge_render, "_image_size", return_value=(0, 0)
        ):
            self.assertIsNone(CartridgeFrame._scaled_cover(Path("cover.png"), 100, 100))

    def test_an_image_whose_header_reads_but_whose_pixels_do_not_is_not_drawn(self):
        with TemporaryDirectory() as tmp_dir:
            cover = _write_cover(Path(tmp_dir) / "c.png")
            with unittest.mock.patch.object(
                cartridge_render.GdkPixbuf.Pixbuf,
                "new_from_file_at_scale",
                side_effect=cartridge_render.GLib.Error("truncated"),
            ):
                with self.assertLogs("openemux.core.cartridge_render", level="WARNING"):
                    self.assertIsNone(CartridgeFrame._scaled_cover(cover, 100, 100))


class PixbufToSurfaceTests(unittest.TestCase):
    """The label reaches cairo straight from its pixels, with no PNG in between (issue 902)."""

    def _pixbuf(self, width, height, alpha=False, fill=0xFF000000):
        import gi

        gi.require_version("GdkPixbuf", "2.0")
        from gi.repository import GdkPixbuf

        pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, alpha, 8, width, height)
        pixbuf.fill(fill)
        return pixbuf

    def _pixel(self, surface, x=0, y=0):
        data = surface.get_data()
        offset = y * surface.get_stride() + x * 4
        return bytes(data[offset:offset + 4])

    def test_an_rgb_pixbuf_becomes_a_native_rgb24_surface(self):
        surface = cartridge_render._pixbuf_to_surface(self._pixbuf(3, 2, fill=0x1122_33FF))
        self.assertEqual((surface.get_width(), surface.get_height()), (3, 2))
        self.assertEqual(surface.get_format(), cartridge_render.cairo.FORMAT_RGB24)
        # Little-endian memory order is B, G, R, x.
        self.assertEqual(self._pixel(surface, 2, 1)[:3], bytes([0x33, 0x22, 0x11]))

    def test_a_pixbuf_with_alpha_is_flattened_onto_the_blank_sticker_tone(self):
        clear = self._pixbuf(2, 2, alpha=True, fill=0xFF000000)  # red, fully transparent
        surface = cartridge_render._pixbuf_to_surface(clear)
        expected = cartridge_render._rgb_pixel(cartridge_render.BLANK_LABEL_RGB)
        blue, green, red = expected >> 8 & 0xFF, expected >> 16 & 0xFF, expected >> 24 & 0xFF
        self.assertEqual(self._pixel(surface)[:3], bytes([blue, green, red]))

    def test_a_padded_rowstride_is_packed_row_by_row(self):
        import gi

        gi.require_version("GdkPixbuf", "2.0")
        from gi.repository import GdkPixbuf, GLib

        # Three bytes of pixel per row plus one byte of padding.
        rows = bytes([10, 20, 30, 0, 40, 50, 60, 0])
        padded = GdkPixbuf.Pixbuf.new_from_bytes(
            GLib.Bytes.new(rows), GdkPixbuf.Colorspace.RGB, False, 8, 1, 2, 4
        )
        surface = cartridge_render._pixbuf_to_surface(padded)
        self.assertEqual(self._pixel(surface, 0, 0)[:3], bytes([30, 20, 10]))
        self.assertEqual(self._pixel(surface, 0, 1)[:3], bytes([60, 50, 40]))

    def test_a_big_endian_host_packs_the_other_way_round(self):
        surface = cartridge_render._pixbuf_to_surface(
            self._pixbuf(1, 1, fill=0x1122_33FF), byteorder="big"
        )
        self.assertEqual(self._pixel(surface)[1:], bytes([0x11, 0x22, 0x33]))

    def test_the_fill_value_is_the_pixbuf_layout(self):
        self.assertEqual(cartridge_render._rgb_pixel((1.0, 0.0, 0.5)), 0xFF0080FF)


@unittest.skipUnless(rsvg_available(), "librsvg typelib (gir1.2-rsvg-2.0) not installed")
class TheFrameIsRasterizedOnceTests(unittest.TestCase):
    """librsvg draws the frame and the stencil once per size; the rest is cairo (issue 902)."""

    def test_a_second_cartridge_of_the_same_size_calls_librsvg_no_more(self):
        frame = load_frame(FRAME)
        frame._label_cache = {}
        with TemporaryDirectory() as tmp:
            cover = _write_cover(Path(tmp) / "c.png")
            frame.render(str(cover), width=100)
            with unittest.mock.patch.object(
                frame._frame, "render_document", side_effect=AssertionError("rasterized again")
            ), unittest.mock.patch.object(
                frame._full, "render_layer", side_effect=AssertionError("rasterized again")
            ):
                surface = frame.render(str(cover), width=100)
        self.assertEqual(surface.get_width(), 100)

    def test_a_new_size_replaces_the_cached_one(self):
        frame = load_frame(FRAME)
        frame.render(None, width=100)
        frame.render(None, width=150)
        self.assertEqual(list(frame._label_cache), [frame.size_for_width(150)])

    def test_two_threads_asking_at_once_rasterize_once(self):
        from concurrent.futures import ThreadPoolExecutor

        frame = load_frame(FRAME)
        frame._label_cache = {}
        calls = []
        real = frame._frame.render_document

        def counted(*args, **kwargs):
            calls.append(1)
            return real(*args, **kwargs)

        with unittest.mock.patch.object(frame._frame, "render_document", counted):
            with ThreadPoolExecutor(max_workers=4) as pool:
                list(pool.map(lambda _i: frame.render(None, width=120), range(8)))
        self.assertEqual(len(calls), 1)

    def test_the_cover_is_decoded_at_the_sticker_size_not_in_full(self):
        with TemporaryDirectory() as tmp:
            cover = _write_cover(Path(tmp) / "c.png", size=(400, 400))
            surface, dx, dy = CartridgeFrame._scaled_cover(cover, 50, 20)
            self.assertEqual((surface.get_width(), surface.get_height()), (50, 50))
            self.assertEqual((dx, dy), (0, -15))


class WithoutLibrsvgTests(unittest.TestCase):
    """The typelib is optional; SVG frames simply stop being available."""

    def test_the_module_still_imports_and_says_so(self):
        import importlib

        import gi

        real_require = gi.require_version

        def _refuse(namespace, version):
            if namespace == "Rsvg":
                raise ValueError("no typelib")
            return real_require(namespace, version)

        self.addCleanup(importlib.reload, cartridge_render)
        with unittest.mock.patch.object(gi, "require_version", _refuse):
            importlib.reload(cartridge_render)
            self.assertIsNone(cartridge_render.Rsvg)
            self.assertFalse(cartridge_render.rsvg_available())


if __name__ == "__main__":
    unittest.main()


# Every console a cartridge frame was authored for.
CARTRIDGE_CONSOLES = (
    "FC", "SFC", "GBA", "GB", "GBC", "MD", "N64", "NDS", "SMS",
    "A2600", "A5200", "A7800", "CV", "GG", "INTV", "LYNX", "NGP", "O2",
    "PCE", "S32X", "SG1000", "VB", "VECTREX", "WS",
)


@unittest.skipUnless(rsvg_available(), "librsvg typelib (gir1.2-rsvg-2.0) not installed")
class EveryShippedFrameTests(unittest.TestCase):
    """A frame that fails to load silently degrades its console to covers."""

    def test_every_shell_of_every_console_loads(self):
        for console in CARTRIDGE_CONSOLES:
            for color in cartridge_render.frame_colors_for(console):
                path = cartridge_render.frame_asset_for(console, color=color)
                with self.subTest(frame=path.name):
                    frame = CartridgeFrame(path)
                    bx, by, bw, bh = frame._label_bbox(frame.width, frame.height)
                    self.assertGreater(bw, 0)
                    self.assertGreater(bh, 0)
                    self.assertGreaterEqual(bx, -1)
                    self.assertGreaterEqual(by, -1)
                    self.assertLessEqual(bx + bw, frame.width + 1)
                    self.assertLessEqual(by + bh, frame.height + 1)

    def test_the_cover_shows_through_every_label_window(self):
        with TemporaryDirectory() as tmp:
            cover = _write_cover(Path(tmp) / "c.png", color=(255, 0, 0))
            for console in CARTRIDGE_CONSOLES:
                with self.subTest(console=console):
                    frame = CartridgeFrame(cartridge_render.frame_asset_for(console))
                    surface = frame.render(str(cover), width=200)
                    bx, by, bw, bh = frame._label_bbox(surface.get_width(), surface.get_height())
                    offset = int(by + bh / 2) * surface.get_stride() + int(bx + bw / 2) * 4
                    b, g, r, _a = surface.get_data()[offset:offset + 4]
                    self.assertGreater(r, 200)
                    self.assertLess(g, 60)


#: The frames redone with relief by the Android generator and imported by
#: tools/import_cartridge_frames.py (issues #703 and #724). SFC stays hand-drawn.
RELIEF_CONSOLES = (
    "FC", "GB", "GBC", "SMS", "GG", "SG1000", "S32X", "PCE", "A2600", "A5200",
    "A7800", "CV", "INTV", "LYNX", "NGP", "O2", "VB", "VECTREX", "WS", "N64",
    "GBA", "MD", "NDS",
)


class ReliefFrameTests(unittest.TestCase):
    """The relief frames embed WebP, which only an image-rs librsvg decodes."""

    def test_relief_frames_embed_webp_and_the_others_png(self):
        for console in CARTRIDGE_CONSOLES:
            expected = "webp" if console in RELIEF_CONSOLES else "png"
            for color in cartridge_render.frame_colors_for(console):
                path = cartridge_render.frame_asset_for(console, color=color)
                with self.subTest(frame=path.name):
                    self.assertIn(f'xlink:href="data:image/{expected};base64,', path.read_text())

    @unittest.skipUnless(rsvg_available(), "librsvg typelib (gir1.2-rsvg-2.0) not installed")
    def test_every_relief_shell_is_drawn(self):
        # A librsvg that cannot decode the WebP draws nothing where the shell
        # is: the cartridge would be a bare sticker. Outside the label window
        # only the shell can be opaque, so count there.
        for console in RELIEF_CONSOLES:
            for color in cartridge_render.frame_colors_for(console):
                with self.subTest(console=console, color=color):
                    frame = CartridgeFrame(cartridge_render.frame_asset_for(console, color=color))
                    surface = frame.render(None, width=200)
                    data, stride = surface.get_data(), surface.get_stride()
                    w, h = surface.get_width(), surface.get_height()
                    bx, by, bw, bh = frame._label_bbox(w, h)
                    outside = [
                        data[y * stride + x * 4 + 3]
                        for y in range(0, h, 4)
                        for x in range(0, w, 4)
                        if not (bx <= x < bx + bw and by <= y < by + bh)
                    ]
                    opaque = sum(1 for a in outside if a == 255)
                    self.assertGreater(opaque / len(outside), 0.3)


class FrameAssetLookupTests(unittest.TestCase):
    """Which consoles have a cartridge frame: the SVG assets are the list."""

    def test_shipped_assets_are_discovered(self):
        consoles = cartridge_render.consoles_with_frames()
        # The frames actually authored so far. A new SVG opts a console in with
        # no code change, so this asserts membership rather than an exact set.
        for console in CARTRIDGE_CONSOLES:
            self.assertIn(console, consoles)
        # Disc-based consoles have no cartridge to frame.
        for console in ("PS", "MCD", "PCECD"):
            self.assertNotIn(console, consoles)

    def test_has_frame_matches_the_asset_on_disk(self):
        self.assertTrue(cartridge_render.has_frame("SFC"))
        self.assertFalse(cartridge_render.has_frame("PS"))
        self.assertFalse(cartridge_render.has_frame("definitely-not-a-console"))

    def test_lookup_is_driven_by_the_given_directory(self):
        with TemporaryDirectory() as tmp_dir:
            directory = Path(tmp_dir)
            (directory / "XYZ.svg").write_text("<svg/>")
            (directory / "notes.txt").write_text("ignored")
            self.assertEqual(cartridge_render.consoles_with_frames(directory), ["XYZ"])
            self.assertTrue(cartridge_render.has_frame("XYZ", directory))
            self.assertFalse(cartridge_render.has_frame("SFC", directory))
            self.assertEqual(
                cartridge_render.frame_asset_for("XYZ", directory),
                directory / "XYZ.svg",
            )

    def test_cache_key_tells_shell_variants_apart(self):
        # A different shell file is a different composite: nothing to
        # invalidate by hand when the user picks a color.
        with TemporaryDirectory() as tmp_dir:
            directory = Path(tmp_dir)
            (directory / "XYZ.svg").write_text("<svg/>")
            (directory / "XYZ-red.svg").write_text("<svg/>")
            base = cartridge_render._cache_key(None, directory / "XYZ.svg", 200, 1)
            red = cartridge_render._cache_key(None, directory / "XYZ-red.svg", 200, 1)
            self.assertNotEqual(base, red)

    def test_color_variants_are_not_consoles(self):
        # SFC-red.svg is a shell for SFC, not a console called "SFC-red".
        with TemporaryDirectory() as tmp_dir:
            directory = Path(tmp_dir)
            (directory / "XYZ.svg").write_text("<svg/>")
            (directory / "XYZ-red.svg").write_text("<svg/>")
            (directory / "XYZ-gold.svg").write_text("<svg/>")
            self.assertEqual(cartridge_render.consoles_with_frames(directory), ["XYZ"])

    def test_frame_asset_resolution_by_color(self):
        with TemporaryDirectory() as tmp_dir:
            directory = Path(tmp_dir)
            (directory / "XYZ.svg").write_text("<svg/>")
            (directory / "XYZ-red.svg").write_text("<svg/>")
            # A set color resolves to its variant file.
            self.assertEqual(
                cartridge_render.frame_asset_for("XYZ", directory, color="red"),
                directory / "XYZ-red.svg",
            )
            # A color with no file falls back to the authored shell...
            self.assertEqual(
                cartridge_render.frame_asset_for("XYZ", directory, color="blue"),
                directory / "XYZ.svg",
            )
            # ...and so do "default"/None.
            self.assertEqual(
                cartridge_render.frame_asset_for("XYZ", directory, color="default"),
                directory / "XYZ.svg",
            )
            self.assertEqual(
                cartridge_render.frame_asset_for("XYZ", directory),
                directory / "XYZ.svg",
            )

    def test_frame_colors_come_from_the_files_on_disk(self):
        with TemporaryDirectory() as tmp_dir:
            directory = Path(tmp_dir)
            (directory / "XYZ.svg").write_text("<svg/>")
            (directory / "XYZ-red.svg").write_text("<svg/>")
            (directory / "XYZ-gold.svg").write_text("<svg/>")
            self.assertEqual(
                cartridge_render.frame_colors_for("XYZ", directory),
                ["default", "gold", "red"],
            )
            # No base frame, no colors -- variants alone do not opt a console in.
            (directory / "ABC-red.svg").write_text("<svg/>")
            self.assertEqual(cartridge_render.frame_colors_for("ABC", directory), [])

    def test_shipped_variants_resolve_for_every_console(self):
        # Every console with a frame got the full first batch of shells.
        for console in CARTRIDGE_CONSOLES:
            colors = cartridge_render.frame_colors_for(console)
            self.assertIn("red", colors, console)
            self.assertIn("white", colors, console)
            self.assertEqual(
                cartridge_render.frame_asset_for(console, color="red"),
                cartridge_render.CARTRIDGE_ASSETS_DIR / f"{console}-red.svg",
            )

    def test_missing_directory_yields_no_frames(self):
        with TemporaryDirectory() as tmp_dir:
            missing = Path(tmp_dir) / "nope"
            self.assertEqual(cartridge_render.consoles_with_frames(missing), [])
            self.assertFalse(cartridge_render.has_frame("SFC", missing))

    def test_frame_asset_lookup_does_not_require_librsvg(self):
        # Deciding whether a label is worth scraping must not depend on the
        # rendering stack being installed: the typelib can be added later.
        with unittest.mock.patch.object(cartridge_render, "Rsvg", None):
            self.assertFalse(cartridge_render.rsvg_available())
            self.assertTrue(cartridge_render.has_frame("SFC"))
            self.assertIsNone(cartridge_render.cartridge_frame("SFC"))


class WhatRenderReturnsTests(unittest.TestCase):
    def test_a_rendered_cartridge_still_exists_when_the_call_returns(self):
        # The user-visible invariant: a returned path that is not on disk shows
        # up as a missing cartridge, not as an error.
        with TemporaryDirectory() as tmp_dir:
            frame = cartridge_render.cartridge_frame("MD")
            if frame is None or not rsvg_available():
                self.skipTest("librsvg or the MD frame is unavailable")
            out = render_cartridge(None, frame, "MD", "Any", cache_dir=Path(tmp_dir))
            self.assertIsNotNone(out)
            self.assertTrue(out.exists(), f"render_cartridge returned a missing file: {out}")
            self.assertGreater(out.stat().st_size, 0)
