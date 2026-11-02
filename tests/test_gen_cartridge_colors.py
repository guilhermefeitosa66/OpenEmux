"""tools/gen_cartridge_colors.py: filter copies for hand-drawn frames, never for relief ones."""

import contextlib
import importlib.util
import io
import shutil
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

_TOOL = Path(__file__).resolve().parents[1] / "tools" / "gen_cartridge_colors.py"
_spec = importlib.util.spec_from_file_location("gen_cartridge_colors", _TOOL)
tool = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tool)

ASSETS = Path(__file__).resolve().parents[1] / "src" / "openemux" / "ui" / "assets" / "images" / "cartridges"


class ReliefFrameTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.assets = Path(self._tmp.name)
        for name in ("GB.svg", "GB-red.svg", "SFC.svg"):
            shutil.copy(ASSETS / name, self.assets / name)
        patcher = mock.patch.object(tool, "ASSETS", self.assets)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._tmp.cleanup)

    def run_tool(self, *consoles):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            tool.main(list(consoles))
        return out.getvalue()

    def test_detects_relief_frames(self):
        self.assertTrue(tool.is_relief_frame((ASSETS / "GB.svg").read_text()))
        self.assertFalse(tool.is_relief_frame((ASSETS / "SFC.svg").read_text()))

    def test_a_relief_frame_keeps_its_imported_colours(self):
        before = (self.assets / "GB-red.svg").read_bytes()
        out = self.run_tool("GB")
        self.assertIn("relief frame, skipped", out)
        self.assertIn("0 files written", out)
        self.assertEqual((self.assets / "GB-red.svg").read_bytes(), before)

    def test_a_hand_drawn_frame_still_gets_its_filter_copies(self):
        out = self.run_tool("SFC")
        self.assertIn("12 files written", out)
        red = (self.assets / "SFC-red.svg").read_text()
        self.assertIn('id="colorize-red"', red)
        self.assertEqual(red, (ASSETS / "SFC-red.svg").read_text())


if __name__ == "__main__":
    unittest.main()
