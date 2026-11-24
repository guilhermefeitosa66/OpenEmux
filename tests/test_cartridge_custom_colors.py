"""Custom cartridge colors: any shell color, per game (issue 983)."""

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import cairo

from openemux.core import cartridge_colors, cartridge_render
from openemux.core.cartridge_colors import CartridgeColorStore
from openemux.core.cartridge_render import (
    CartridgeFrameError,
    custom_frame_for,
    load_frame,
    mix_shell,
    rsvg_available,
)

ASSETS = cartridge_render.CARTRIDGE_ASSETS_DIR
NEEDS_RSVG = unittest.skipUnless(rsvg_available(), "librsvg typelib (gir1.2-rsvg-2.0) not installed")

# A frame in the shape the shipped ones have: the label marker below the art,
# inside a group, and a second color of the same art for the other shell.
FIXTURE = """<?xml version="1.0"?>
<svg xmlns="http://www.w3.org/2000/svg"
     xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"
     width="40" height="20" {box}>
  <defs id="defs1"/>
  <g id="layer1" transform="translate(0 0)">
    <rect id="marker" inkscape:label="label-clip" x="10" y="5" width="20" height="10" fill="#00ff00"/>
    <rect id="art" x="0" y="0" width="40" height="5" fill="{fill}"/>
  </g>
  <rect id="foot" x="0" y="15" width="40" height="5" fill="{fill}"/>
</svg>
"""


def _write_fixture(directory, console="X", box='viewBox="0 0 40 20"'):
    directory = Path(directory)
    (directory / f"{console}.svg").write_text(FIXTURE.format(fill="#808080", box=box))
    (directory / f"{console}-black.svg").write_text(FIXTURE.format(fill="#26262a", box=box))
    (directory / f"{console}-white.svg").write_text(FIXTURE.format(fill="#e8e4da", box=box))
    return directory


def _surface(width, height, pixel):
    """An ARGB32 surface filled with one native-endian (b, g, r, a) pixel."""
    data = bytearray(bytes(pixel) * (width * height))
    return cairo.ImageSurface.create_for_data(data, cairo.FORMAT_ARGB32, width, height, width * 4)


class HexHelpersTests(unittest.TestCase):
    def test_a_custom_color_is_a_lowercase_six_digit_hex(self):
        self.assertTrue(cartridge_colors.is_custom_color("#d23c2a"))
        self.assertTrue(cartridge_colors.is_custom_color(" #D23C2A "))
        for value in ("red", "default", "", None, "#d23c2", "d23c2a", "#zzzzzz"):
            self.assertFalse(cartridge_colors.is_custom_color(value), value)

    def test_parse_hex_takes_what_a_person_types(self):
        self.assertEqual(cartridge_colors.parse_hex("#D23C2A"), "#d23c2a")
        self.assertEqual(cartridge_colors.parse_hex("d23c2a"), "#d23c2a")
        self.assertEqual(cartridge_colors.parse_hex(" #fa0 "), "#ffaa00")
        for value in ("", None, "#12", "#1234", "#ggg", "red"):
            self.assertIsNone(cartridge_colors.parse_hex(value), value)

    def test_hex_to_rgb_refuses_junk(self):
        self.assertEqual(cartridge_colors.hex_to_rgb("#ff8000"), (255, 128, 0))
        with self.assertRaises(ValueError):
            cartridge_colors.hex_to_rgb("blue")

    def test_hsv_round_trip_and_clamping(self):
        hue, saturation, value = cartridge_colors.hex_to_hsv("#d23c2a")
        self.assertEqual(cartridge_colors.hsv_to_hex(hue, saturation, value), "#d23c2a")
        self.assertEqual(cartridge_colors.hsv_to_hex(360, 1, 1), "#ff0000")
        self.assertEqual(cartridge_colors.hsv_to_hex(120, 2, -1), "#000000")
        self.assertEqual(cartridge_colors.hsv_to_hex(0, -1, 5), "#ffffff")

    def test_names_swatches_and_order_know_custom_ids(self):
        self.assertEqual(cartridge_colors.color_name_key("#d23c2a"), cartridge_colors.CUSTOM_COLOR_KEY)
        self.assertIsNone(cartridge_colors.color_name_key("zebra"))
        self.assertEqual(cartridge_colors.color_swatch("#D23C2A"), "#d23c2a")
        self.assertEqual(cartridge_colors.color_swatch("zebra"), cartridge_colors.UNKNOWN_SWATCH)
        self.assertEqual(
            cartridge_colors.order_color_ids(["#d23c2a", "red", "default"]),
            ["default", "red", "#d23c2a"],
        )


class StoringACustomColorTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.path = Path(self._tmp.name) / "cartridge_colors.config"
        self.store = CartridgeColorStore(self.path)

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_custom_color_survives_the_file(self):
        self.store.set_rom_color("/roms/GB/Red.gb", "GB", "#D23C2A")
        self.store.set_console_color("GBC", "#2e7dd1")
        fresh = CartridgeColorStore(self.path)
        self.assertEqual(fresh.get_rom_color("/roms/GB/Red.gb"), "#d23c2a")
        self.assertEqual(fresh.get_effective_color("/roms/GB/Red.gb", "GB"), "#d23c2a")
        self.assertEqual(fresh.get_console_color("GBC"), "#2e7dd1")

    def test_a_malformed_hex_in_the_file_is_dropped(self):
        self.path.write_text(
            "version: 1\n"
            "console_defaults: {GB: '#zz', GBC: '#2e7dd1', GBA: default}\n"
            "rom_overrides: {/roms/a.gb: '#12345', /roms/b.gb: red, /roms/c.gb: '#ABCDEF'}\n"
        )
        data = CartridgeColorStore(self.path).load()
        self.assertEqual(data["console_defaults"], {"GBC": "#2e7dd1"})
        self.assertEqual(data["rom_overrides"], {"/roms/b.gb": "red", "/roms/c.gb": "#abcdef"})


class MixShellTests(unittest.TestCase):
    """C = A + k (B - A) per channel, clamped to the pixel's alpha."""

    def _mix(self, width, height, a, b, color, byteorder="little"):
        out = mix_shell(_surface(width, height, a), _surface(width, height, b), color, byteorder=byteorder)
        return bytes(out.get_data())[:4]

    def test_the_two_sources_come_back_for_their_own_colors(self):
        a, b = (0x2A, 0x26, 0x26, 0xFF), (0xDA, 0xE4, 0xE8, 0xFF)
        self.assertEqual(self._mix(2, 2, a, b, "#26262a"), bytes(a))
        self.assertEqual(self._mix(2, 2, a, b, "#e8e4da"), bytes(b))

    def test_a_kept_pixel_is_the_same_in_every_color(self):
        kept = (10, 200, 30, 255)
        self.assertEqual(self._mix(2, 2, kept, kept, "#ff00ff"), bytes(kept))

    def test_the_lookup_table_path_gives_the_same_values(self):
        a, b = (40, 50, 60, 255), (200, 210, 220, 255)
        small = self._mix(2, 2, a, b, "#3167b0")
        large = self._mix(256, 256, a, b, "#3167b0")
        self.assertEqual(small, large)

    def test_values_stay_within_alpha(self):
        # Half transparent, and a color far outside the black-white span.
        pixel = self._mix(2, 2, (20, 20, 20, 128), (120, 120, 120, 128), "#ff0000")
        self.assertTrue(all(channel <= 128 for channel in pixel[:3]))
        self.assertEqual(pixel[3], 128)

    def test_big_endian_layout(self):
        # (a, r, g, b) in memory: the alpha is the first byte.
        a, b = (0xFF, 0x26, 0x26, 0x2A), (0xFF, 0xE8, 0xE4, 0xDA)
        self.assertEqual(self._mix(2, 2, a, b, "#e8e4da", byteorder="big"), bytes(b))

    def test_sizes_must_match(self):
        with self.assertRaises(ValueError):
            mix_shell(_surface(2, 2, (0, 0, 0, 0)), _surface(3, 2, (0, 0, 0, 0)), "#ffffff")


@NEEDS_RSVG
class CustomFrameTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        root = Path(self._tmp.name)
        self.assets = _write_fixture(root)
        self.frames = root / "frames"

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_custom_shell_is_a_usable_frame(self):
        path = custom_frame_for("X", "#D23C2A", assets_dir=self.assets, frames_dir=self.frames)
        self.assertEqual(path, self.frames / "X-d23c2a.svg")
        frame = load_frame(path)
        self.assertIsNotNone(frame)
        self.assertEqual((frame.width, frame.height), (40, 20))
        # The label window stays where the source frame has it.
        source = load_frame(self.assets / "X-black.svg")
        self.assertEqual(frame._label_bbox(40, 20), source._label_bbox(40, 20))

    def test_the_shell_is_made_once_and_remade_for_newer_art(self):
        with mock.patch.object(cartridge_render, "mix_shell", wraps=mix_shell) as mixer:
            first = custom_frame_for("X", "#123456", assets_dir=self.assets, frames_dir=self.frames)
            custom_frame_for("X", "#123456", assets_dir=self.assets, frames_dir=self.frames)
            self.assertEqual(mixer.call_count, 1)
            later = first.stat().st_mtime_ns + 10_000_000_000
            os.utime(self.assets / "X-white.svg", ns=(later, later))
            custom_frame_for("X", "#123456", assets_dir=self.assets, frames_dir=self.frames)
            self.assertEqual(mixer.call_count, 2)

    def test_nothing_without_a_custom_color_or_the_two_sources(self):
        self.assertIsNone(custom_frame_for("X", "red", assets_dir=self.assets, frames_dir=self.frames))
        (self.assets / "X-white.svg").unlink()
        self.assertIsNone(custom_frame_for("X", "#123456", assets_dir=self.assets, frames_dir=self.frames))
        self.assertFalse(cartridge_render.supports_custom_color("X", self.assets))

    def test_a_frame_with_no_size_or_a_failed_render_gives_none(self):
        handle = mock.Mock()
        handle.get_intrinsic_size_in_pixels.return_value = (False, 0, 0)
        with mock.patch.object(cartridge_render.Rsvg.Handle, "new_from_file", return_value=handle):
            self.assertIsNone(
                custom_frame_for("X", "#123456", assets_dir=self.assets, frames_dir=self.frames)
            )
        with mock.patch.object(cartridge_render, "_shell_raster", side_effect=OSError("disk")):
            self.assertIsNone(
                custom_frame_for("X", "#654321", assets_dir=self.assets, frames_dir=self.frames)
            )

    def test_a_root_without_a_viewbox_uses_its_size(self):
        _write_fixture(self.assets, console="Y", box="")
        for name in ("Y-black.svg", "Y-white.svg"):
            path = self.assets / name
            path.write_text(path.read_text().replace('width="40" height="20"', 'width="40px" height="20px"'))
        path = custom_frame_for("Y", "#123456", assets_dir=self.assets, frames_dir=self.frames)
        self.assertIn('width="40"', path.read_text())
        self.assertIsNotNone(load_frame(path))

    def test_a_source_without_the_label_marker_is_refused(self):
        bare = self.assets / "bare.svg"
        bare.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="4" height="4"/>')
        with self.assertRaises(CartridgeFrameError):
            cartridge_render._custom_frame_svg(bare, b"png")
        self.assertEqual(cartridge_render._svg_length("auto"), "0")
        self.assertEqual(cartridge_render._svg_length(None), "0")
        # Rasterizing it is fine: there is simply no marker to leave out.
        self.assertEqual(cartridge_render._shell_raster(bare, 4, 4).get_width(), 4)

    def test_frame_asset_for_resolves_a_custom_color(self):
        with mock.patch.object(cartridge_render, "CUSTOM_FRAMES_DIR", self.frames):
            path = cartridge_render.frame_asset_for("X", self.assets, color="#abcdef")
            self.assertEqual(path, self.frames / "X-abcdef.svg")
            with mock.patch.object(cartridge_render, "custom_frame_for", return_value=None):
                # A shell that cannot be made falls back to the authored one.
                self.assertEqual(
                    cartridge_render.frame_asset_for("X", self.assets, color="#abcdef"),
                    self.assets / "X.svg",
                )

    def test_preview_sources_are_the_two_composites(self):
        cache = Path(self._tmp.name) / "cache"
        with mock.patch.object(cartridge_render, "CARTRIDGE_ASSETS_DIR", self.assets):
            sources = cartridge_render.custom_preview_sources(None, "X", "Game", 40, cache_dir=cache)
            self.assertEqual(len(sources), 2)
            self.assertEqual(sources[0].get_width(), sources[1].get_width())
            with mock.patch.object(cartridge_render, "render_cartridge", return_value=None):
                self.assertIsNone(cartridge_render.custom_preview_sources(None, "X", "Game", 40))
            self.assertIsNone(cartridge_render.custom_preview_sources(None, "NOPE", "Game", 40))

    def test_the_shipped_red_is_rebuilt_from_black_and_white(self):
        """The premise of the whole feature, on a real relief frame."""
        frame = load_frame(ASSETS / "GB.svg")
        width, height = 177, 200
        black = cartridge_render._shell_raster(ASSETS / "GB-black.svg", width, height)
        white = cartridge_render._shell_raster(ASSETS / "GB-white.svg", width, height)
        red = cartridge_render._shell_raster(ASSETS / "GB-red.svg", width, height)
        mixed = bytes(mix_shell(black, white, cartridge_colors.color_swatch("red")).get_data())
        shipped = bytes(red.get_data())
        mean = sum(abs(x - y) for x, y in zip(mixed, shipped)) / len(shipped)
        self.assertIsNotNone(frame)
        self.assertLess(mean, 2.0)


class WithoutLibrsvgTests(unittest.TestCase):
    def test_no_custom_shell_without_librsvg(self):
        with mock.patch.object(cartridge_render, "Rsvg", None):
            self.assertIsNone(custom_frame_for("GB", "#123456"))
            self.assertFalse(cartridge_render.supports_custom_color("GB"))
            self.assertIsNone(cartridge_render.custom_preview_sources(None, "GB", "Game", 40))


if __name__ == "__main__":
    unittest.main()
