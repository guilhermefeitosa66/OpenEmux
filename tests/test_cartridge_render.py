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
            self.assertFalse(first.exists())  # stale composite is dropped
            self.assertTrue(second.exists())

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
        pixbuf = unittest.mock.Mock()
        pixbuf.get_width.return_value = 0
        pixbuf.get_height.return_value = 0
        with unittest.mock.patch.object(
            cartridge_render.GdkPixbuf.Pixbuf, "new_from_file", return_value=pixbuf
        ):
            self.assertIsNone(CartridgeFrame._scaled_cover(Path("cover.png"), 100, 100))


class TheBytesReaderTests(unittest.TestCase):
    """cairo's PNG loader wants a file object; this is the whole of one."""

    def test_a_read_with_no_size_returns_the_rest(self):
        reader = cartridge_render._BytesReader(b"abcdef")
        self.assertEqual(reader.read(2), b"ab")
        self.assertEqual(reader.read(-1), b"cdef")
        self.assertEqual(reader.read(None), b"")


@unittest.skipUnless(rsvg_available(), "librsvg typelib (gir1.2-rsvg-2.0) not installed")
class ACoverThatWillNotConvertTests(unittest.TestCase):
    def test_a_pixbuf_that_cannot_be_encoded_is_reported(self):
        pixbuf = unittest.mock.Mock()
        pixbuf.save_to_bufferv.return_value = (False, None)
        with self.assertRaises(CartridgeFrameError):
            cartridge_render._pixbuf_to_surface(pixbuf)


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


class FrameAssetLookupTests(unittest.TestCase):
    """Which consoles have a cartridge frame: the SVG assets are the list."""

    def test_shipped_assets_are_discovered(self):
        consoles = cartridge_render.consoles_with_frames()
        # The frames actually authored so far. A new SVG opts a console in with
        # no code change, so this asserts membership rather than an exact set.
        for console in ("FC", "SFC", "GBA", "GB", "GBC", "MD", "N64", "NDS", "SMS"):
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
        for console in ("FC", "SFC", "GBA", "GB", "GBC", "MD", "N64", "NDS", "SMS"):
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


class DropStaleTests(unittest.TestCase):
    """``_drop_stale`` must never delete the composite it was told to keep.

    It did, on Windows, for every render: ``keep`` is built by joining with
    "/" while ``iterdir()`` appends with the OS separator, so the two spell the
    same file differently ("MD/a.png" vs "MD\a.png") and ``Path.__eq__`` --
    which compares the normalised *string* -- answered False. Every cartridge
    was written and then immediately deleted, so the grid received a path to a
    file that no longer existed and silently fell back to the bare cover art.

    The lesson generalises: ``Path.__eq__`` is not a same-file test on Windows.
    """

    # A composite is named "<rom name>.<12-hex key>.png" -- _cache_key() returns
    # the first 12 characters of a sha1. The fixtures spell real keys because
    # _is_composite_of() checks that shape (issue #234): a made-up suffix is
    # simply not recognised as a composite, and the test would pass while
    # exercising nothing.
    NEW_KEY = "0123456789ab"
    OLD_KEY = "ba9876543210"

    def _populate(self, directory):
        keep = directory / f"_blank.{self.NEW_KEY}.png"
        stale = directory / f"_blank.{self.OLD_KEY}.png"
        unrelated = directory / f"Zelda.{self.NEW_KEY}.png"
        other_suffix = directory / f"_blank.{self.NEW_KEY}.png.1234.tmp"
        for path in (keep, stale, unrelated, other_suffix):
            path.write_bytes(b"png")
        return keep, stale, unrelated, other_suffix

    def test_keeps_the_target_and_drops_only_its_own_stale_siblings(self):
        with TemporaryDirectory() as tmp_dir:
            directory = Path(tmp_dir)
            keep, stale, unrelated, other_suffix = self._populate(directory)

            cartridge_render._drop_stale(directory, "_blank", keep)

            self.assertTrue(keep.exists(), "the composite just rendered was deleted")
            self.assertFalse(stale.exists(), "an outdated composite was left behind")
            # A different ROM's composite shares the directory, not the stem.
            self.assertTrue(unrelated.exists())
            # In-flight temporaries from parallel renders are not .png.
            self.assertTrue(other_suffix.exists())

    def test_a_stale_composite_that_will_not_delete_is_left_behind(self):
        # Sweeping the cache is housekeeping; a file that will not go must not
        # take the render that just succeeded down with it.
        with TemporaryDirectory() as tmp_dir:
            directory = Path(tmp_dir)
            keep, stale, _, _ = self._populate(directory)

            with unittest.mock.patch.object(
                Path, "unlink", side_effect=OSError("read-only")
            ):
                cartridge_render._drop_stale(directory, "_blank", keep)

            self.assertTrue(stale.exists())
            self.assertTrue(keep.exists())

    def test_keeps_the_target_when_it_is_spelled_with_a_different_separator(self):
        # The exact Windows shape of the bug, reproduced explicitly so it is
        # covered even where "/" and os.sep happen to be the same character.
        with TemporaryDirectory() as tmp_dir:
            directory = Path(tmp_dir)
            keep, stale, _, _ = self._populate(directory)

            # Same file, spelled the way render_cartridge builds it.
            respelled = Path(f"{directory.as_posix()}/{keep.name}")
            self.assertTrue(respelled.samefile(keep))

            cartridge_render._drop_stale(directory, "_blank", respelled)

            self.assertTrue(keep.exists())
            self.assertFalse(stale.exists())

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
