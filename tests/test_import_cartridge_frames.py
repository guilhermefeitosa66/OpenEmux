"""tools/import_cartridge_frames.py: the Android relief frames into the desktop SVGs."""

import base64
import contextlib
import importlib.util
import io
import shutil
import struct
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

_TOOL = Path(__file__).resolve().parents[1] / "tools" / "import_cartridge_frames.py"
_spec = importlib.util.spec_from_file_location("import_cartridge_frames", _TOOL)
tool = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tool)

ASSETS = Path(__file__).resolve().parents[1] / "src" / "openemux" / "ui" / "assets" / "images" / "cartridges"


def _riff(chunk: bytes, body: bytes) -> bytes:
    payload = b"WEBP" + chunk + struct.pack("<I", len(body)) + body
    return b"RIFF" + struct.pack("<I", len(payload)) + payload


def vp8l(w, h):
    """A lossless WebP header: enough for the tool, which never decodes the image."""
    bits = (w - 1) | ((h - 1) << 14)
    return _riff(b"VP8L", b"\x2f" + bits.to_bytes(4, "little") + b"\0" * 8)


def vp8(w, h):
    return _riff(b"VP8 ", b"\0\0\0" + b"\x9d\x01\x2a" + struct.pack("<HH", w, h) + b"\0" * 8)


def vp8x(w, h):
    return _riff(b"VP8X", b"\x10\0\0\0" + (w - 1).to_bytes(3, "little") + (h - 1).to_bytes(3, "little") + b"\0" * 8)


# The shipped Game Boy frame is 177x200: 708x800 at the generator's 800 px.
GB_W, GB_H = 708, 800

SVG = """<svg viewBox="0 0 177 200"><defs
     id="defs1"><filter
       id="colorize-red"><feFlood flood-color="#B23A34" /></filter></defs><g><rect
       id="rect1" inkscape:label="label-clip" /><image
       style="filter:url(#colorize-red)"
       xlink:href="data:image/png;base64,AAAA"
       inkscape:label="frame" /></g></svg>"""


class WebpSizeTests(unittest.TestCase):
    def test_reads_every_webp_flavour(self):
        self.assertEqual(tool.webp_size(vp8l(708, 800)), (708, 800))
        self.assertEqual(tool.webp_size(vp8(800, 514)), (800, 514))
        self.assertEqual(tool.webp_size(vp8x(531, 800)), (531, 800))

    def test_refuses_what_is_not_a_webp(self):
        with self.assertRaisesRegex(tool.FrameImportError, "not a WebP"):
            tool.webp_size(b"\x89PNG\r\n\x1a\n" + b"\0" * 40)
        with self.assertRaisesRegex(tool.FrameImportError, "unknown WebP chunk"):
            tool.webp_size(_riff(b"ALPH", b"\0" * 20))


class NameTests(unittest.TestCase):
    def test_maps_drawables_to_frame_svgs(self):
        self.assertEqual(tool.svg_name("cart_gb.webp"), "GB.svg")
        self.assertEqual(tool.svg_name("cart_gb_red.webp"), "GB-red.svg")
        self.assertEqual(tool.svg_name("cart_sg1000_clear.webp"), "SG1000-clear.svg")
        self.assertIsNone(tool.svg_name("cart_gb.png"))
        self.assertIsNone(tool.svg_name("skin_gba.webp"))


class ImportFrameTests(unittest.TestCase):
    def test_swaps_the_art_and_drops_the_filter(self):
        webp = vp8l(GB_W, GB_H)
        out = tool.import_frame(SVG, webp, "GB-red.svg")
        self.assertIn(f'xlink:href="data:image/webp;base64,{base64.b64encode(webp).decode()}"', out)
        self.assertNotIn("colorize", out)
        self.assertNotIn("<filter", out)
        self.assertIn('<defs\n     id="defs1" />', out)
        # The marker and the frame label are left exactly as they were.
        self.assertIn('<rect\n       id="rect1" inkscape:label="label-clip" />', out)
        self.assertIn('inkscape:label="frame"', out)

    def test_reimporting_a_relief_frame_replaces_its_webp(self):
        first = tool.import_frame(SVG, vp8l(GB_W, GB_H), "GB-red.svg")
        second = tool.import_frame(first, vp8(GB_W, GB_H), "GB-red.svg")
        self.assertEqual(second.count("data:image/webp"), 1)
        self.assertIn(base64.b64encode(vp8(GB_W, GB_H)).decode(), second)

    def test_a_filter_that_is_not_colorize_is_kept(self):
        svg = SVG.replace('id="colorize-red"', 'id="shadow"').replace(
            'style="filter:url(#colorize-red)"', 'style="filter:url(#shadow)"'
        )
        out = tool.import_frame(svg, vp8l(GB_W, GB_H), "GB.svg")
        self.assertIn('id="shadow"', out)
        self.assertIn("filter:url(#shadow)", out)

    def test_a_base_frame_keeps_its_plain_defs(self):
        base = SVG.replace('<defs\n     id="defs1"><filter\n       id="colorize-red">'
                           '<feFlood flood-color="#B23A34" /></filter></defs>', '<defs\n     id="defs1" />')
        base = base.replace('\n       style="filter:url(#colorize-red)"', "")
        out = tool.import_frame(base, vp8l(GB_W, GB_H), "GB.svg")
        self.assertEqual(out.replace(base64.b64encode(vp8l(GB_W, GB_H)).decode(), "AAAA").replace("webp", "png"), base)

    def test_refuses_a_raster_of_another_shape(self):
        with self.assertRaisesRegex(tool.FrameImportError, "does not have the frame's 177x200 shape"):
            tool.import_frame(SVG, vp8l(800, 800), "GB.svg")

    def test_accepts_the_generators_rounding(self):
        tool.import_frame(SVG, vp8l(GB_W + 1, GB_H), "GB.svg")

    def test_refuses_an_svg_without_viewbox_or_image(self):
        with self.assertRaisesRegex(tool.FrameImportError, "no viewBox"):
            tool.import_frame("<svg></svg>", vp8l(GB_W, GB_H), "X.svg")
        with self.assertRaisesRegex(tool.FrameImportError, "found 0"):
            tool.import_frame('<svg viewBox="0 0 177 200"></svg>', vp8l(GB_W, GB_H), "X.svg")


class MainTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        root = Path(self._tmp.name)
        self.src, self.assets = root / "drawable-nodpi", root / "cartridges"
        self.src.mkdir()
        self.assets.mkdir()
        for name in ("GB.svg", "GB-red.svg", "SFC.svg"):
            shutil.copy(ASSETS / name, self.assets / name)
        (self.src / "cart_gb.webp").write_bytes(vp8l(GB_W, GB_H))
        (self.src / "cart_gb_red.webp").write_bytes(vp8x(GB_W, GB_H))
        (self.src / "cart_sfc.webp").write_bytes(vp8l(800, 510))   # never imported
        (self.src / "skin_gba.webp").write_bytes(vp8l(10, 10))     # not a frame
        self.sfc_before = (self.assets / "SFC.svg").read_bytes()

    def tearDown(self):
        self._tmp.cleanup()

    def run_tool(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = tool.main([*argv, "--from", str(self.src), "--assets", str(self.assets)])
        return code, out.getvalue(), err.getvalue()

    def test_imports_every_frame_it_has_and_leaves_sfc_alone(self):
        code, out, _err = self.run_tool()
        self.assertEqual(code, 0)
        self.assertIn("2 frames imported", out)
        for name in ("GB.svg", "GB-red.svg"):
            self.assertIn("data:image/webp", (self.assets / name).read_text())
        self.assertNotIn("colorize", (self.assets / "GB-red.svg").read_text())
        self.assertEqual((self.assets / "SFC.svg").read_bytes(), self.sfc_before)

    def test_a_subset_imports_only_those_consoles(self):
        shutil.copy(ASSETS / "FC.svg", self.assets / "FC.svg")
        (self.src / "cart_fc.webp").write_bytes(vp8l(713, 800))
        gb_before = (self.assets / "GB.svg").read_bytes()
        code, out, _err = self.run_tool("fc")
        self.assertEqual(code, 0)
        self.assertIn("1 frames imported", out)
        self.assertEqual((self.assets / "GB.svg").read_bytes(), gb_before)

    def test_refuses_the_hand_drawn_frames(self):
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            self.run_tool("SFC")

    def test_a_console_with_no_relief_frame_is_an_error(self):
        code, _out, err = self.run_tool("MD")
        self.assertEqual(code, 1)
        self.assertIn("no relief frame for MD", err)

    def test_an_empty_or_missing_source_is_an_error(self):
        for path in self.src.iterdir():
            path.unlink()
        code, _out, err = self.run_tool()
        self.assertEqual(code, 1)
        self.assertIn("no cart_*.webp", err)
        self.src.rmdir()
        code, _out, err = self.run_tool()
        self.assertEqual(code, 1)
        self.assertIn("no such directory", err)

    def test_a_webp_without_its_svg_is_an_error(self):
        (self.src / "cart_md.webp").write_bytes(vp8l(800, 542))
        code, _out, err = self.run_tool()
        self.assertEqual(code, 1)
        self.assertIn("no MD.svg to put it in", err)

    def test_a_relief_frame_with_no_webp_is_an_error(self):
        (self.src / "cart_gb_red.webp").unlink()
        gb_before = (self.assets / "GB.svg").read_bytes()
        code, _out, err = self.run_tool()
        self.assertEqual(code, 1)
        self.assertIn("for GB-red.svg", err)
        self.assertEqual((self.assets / "GB.svg").read_bytes(), gb_before)

    def test_nothing_is_written_when_one_frame_fails(self):
        (self.src / "cart_gb_red.webp").write_bytes(vp8l(800, 800))
        gb_before = (self.assets / "GB.svg").read_bytes()
        code, _out, err = self.run_tool()
        self.assertEqual(code, 1)
        self.assertIn("GB-red.svg", err)
        self.assertEqual((self.assets / "GB.svg").read_bytes(), gb_before)


class ShippedFramesTests(unittest.TestCase):
    """The frames in the repo are what the importer writes."""

    def test_every_relief_frame_is_a_clean_import(self):
        relief = [p for p in ASSETS.glob("*.svg") if "data:image/webp" in p.read_text()]
        self.assertEqual(len(relief), 22 * 13)
        for path in relief:
            text = path.read_text()
            with self.subTest(frame=path.name):
                self.assertNotIn("colorize", text)
                self.assertIn("label-clip", text)
                self.assertNotIn(path.stem.split("-")[0], tool.KEEP)


if __name__ == "__main__":
    unittest.main()
