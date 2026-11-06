"""tools/export_controller_art.py: the Android bundled skins into desktop controller art."""

import hashlib
import importlib.util
import io
import json
import shutil
import tempfile
import unittest
import zipfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

try:
    from PIL import Image
except ImportError:  # pragma: no cover - Pillow is a dev dependency; the tool needs it
    Image = None

_TOOL = Path(__file__).resolve().parents[1] / "tools" / "export_controller_art.py"


def load_tool():
    spec = importlib.util.spec_from_file_location("export_controller_art", _TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def png(size, color, fmt="PNG"):
    buffer = io.BytesIO()
    Image.new("RGBA", size, color).save(buffer, fmt)
    return buffer.getvalue()


def skin_json(**overrides):
    layout = {
        "size": {"width": 200, "height": 400},
        "screens": [{"x": 0, "y": 20, "width": 200, "height": 100}],
        "frame": {"x": 0, "y": 10, "width": 200, "height": 130},
        "elements": [
            {"id": "save", "type": "action", "bind": "quickSave", "x": 10, "y": 120, "width": 20, "height": 20},
            {"id": "dpad", "type": "dpad", "x": 10, "y": 200, "width": 60, "height": 60},
            {"id": "a", "type": "button", "bind": "a", "x": 140, "y": 201, "width": 41, "height": 41},
            {"id": "stick", "type": "stick", "bind": "analogStick", "x": 80, "y": 300, "width": 60, "height": 60},
            {"id": "start", "type": "button", "bind": "start", "image": "pill", "x": 90, "y": 380, "width": 30,
             "height": 10},
        ],
    }
    skin = {"format": 1, "console": "N64", "name": "Test", "layouts": {"phone-portrait": layout}}
    skin.update(overrides)
    return skin


def default_images():
    return {
        "background.png": png((200, 400), (40, 40, 40, 255)),
        "dpad.png": png((60, 60), (200, 0, 0, 255)),
        "dpad-ball.png": png((44, 44), (0, 0, 0, 255)),
        "a.webp": png((41, 41), (0, 200, 0, 255), "WEBP"),
        "stick-base.png": png((60, 60), (0, 0, 200, 255)),
        "stick-knob.png": png((30, 30), (255, 255, 255, 255)),
        "pill.png": png((30, 10), (90, 90, 90, 255)),
        "save.png": png((20, 20), (1, 2, 3, 255)),
        "frame.png": png((200, 130), (9, 9, 9, 255)),
    }


@unittest.skipIf(Image is None, "Pillow is not installed")
class ExportControllerArtTests(unittest.TestCase):
    def setUp(self):
        self.tool = load_tool()
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.skins = self.tmp / "skins"
        self.skins.mkdir()
        self.out = self.tmp / "out"

    def make_zip(self, name="N64.zip", skin=None, images=None, folder=""):
        path = self.skins / name
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(folder + "skin.json", json.dumps(skin or skin_json()))
            for image_name, data in (default_images() if images is None else images).items():
                archive.writestr(f"{folder}phone-portrait/{image_name}", data)
        return path

    def run_tool(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = self.tool.main([*args, "--skins", str(self.skins), "--out", str(self.out)])
        return code, out.getvalue(), err.getvalue()

    def digest(self):
        return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((self.out / "N64").iterdir())}

    def test_export_crops_scales_and_leaves_quick_actions_out(self):
        self.make_zip()
        code, out, _ = self.run_tool()
        self.assertEqual(code, 0, out)
        folder = self.out / "N64"
        layout = json.loads((folder / "layout.json").read_text())
        # Crop at frame bottom (140) + 8; the layout is 400 high, scaled by 0.5.
        self.assertEqual(layout["size"], {"width": 100, "height": 200 - 74})
        self.assertEqual(layout["console"], "N64")
        self.assertEqual([e["id"] for e in layout["elements"]], ["dpad", "a", "stick", "start"])
        dpad, a, stick, start = layout["elements"]
        self.assertEqual((dpad["x"], dpad["y"], dpad["width"], dpad["height"]), (5, 26, 30, 30))
        self.assertEqual(dpad["bind"], "dpad")
        self.assertEqual(dpad["images"], {"pad": "dpad.png"})
        self.assertEqual(a["images"], {"button": "a.png"})
        self.assertEqual(stick["images"], {"base": "stick-base.png", "knob": "stick-knob.png"})
        self.assertEqual(start["images"], {"button": "pill.png"})
        self.assertEqual(sorted(p.name for p in folder.iterdir()), [
            "a.png", "background.png", "dpad.png", "layout.json", "pill.png", "stick-base.png", "stick-knob.png",
        ])
        with Image.open(folder / "background.png") as background:
            self.assertEqual(background.mode, "RGBA")
            self.assertEqual(background.size, (100, 126))
        with Image.open(folder / "stick-knob.png") as knob:
            self.assertEqual(knob.size, (15, 15))
        with Image.open(folder / "a.png") as button:
            self.assertEqual(button.size, (a["width"], a["height"]))

    def test_rerun_is_byte_identical_and_drops_stale_files(self):
        self.make_zip()
        self.run_tool()
        first = self.digest()
        (self.out / "N64" / "old.png").write_bytes(b"stale")
        self.run_tool("N64")
        self.assertEqual(self.digest(), first)

    def test_skin_inside_a_folder_and_background_image_key(self):
        skin = skin_json()
        skin["layouts"]["phone-portrait"]["background"] = {"image": "body"}
        del skin["layouts"]["phone-portrait"]["frame"]
        images = default_images()
        images["body.png"] = png((100, 200), (1, 1, 1, 255))  # resized to the layout first
        del images["background.png"]
        self.make_zip(skin=skin, images=images, folder="My skin/")
        code, _, err = self.run_tool()
        self.assertEqual(code, 0, err)
        layout = json.loads((self.out / "N64" / "layout.json").read_text())
        # Crop at the screen bottom (120) + 8.
        self.assertEqual(layout["size"]["height"], 200 - 64)

    def test_crop_never_passes_a_control(self):
        skin = skin_json()
        skin["layouts"]["phone-portrait"]["elements"][2]["y"] = 142
        self.assertEqual(self.tool.crop_top(skin["layouts"]["phone-portrait"]), 142)

    def test_errors(self):
        cases = {
            "no layout": dict(skin=skin_json(layouts={"phone-landscape": {}})),
            "wrong format": dict(skin=skin_json(format=2)),
            "no background": dict(images={k: v for k, v in default_images().items() if k != "background.png"}),
            "no element image": dict(images={k: v for k, v in default_images().items() if k != "pill.png"}),
        }
        for label, kwargs in cases.items():
            with self.subTest(label):
                self.make_zip(**kwargs)
                code, _, err = self.run_tool()
                self.assertEqual(code, 1)
                self.assertIn("N64.zip", err)

    def test_bad_packages(self):
        (self.skins / "N64.zip").write_bytes(b"not a zip")
        self.assertIn("not a readable zip", self.run_tool()[2])
        with zipfile.ZipFile(self.skins / "N64.zip", "w") as archive:
            archive.writestr("readme.txt", "x")
        self.assertIn("no skin.json", self.run_tool()[2])
        with zipfile.ZipFile(self.skins / "N64.zip", "w") as archive:
            archive.writestr("skin.json", "{oops")
        self.assertIn("not JSON", self.run_tool()[2])

    def test_console_selection(self):
        self.make_zip()
        self.make_zip("dark.zip")  # not a <CONSOLE>.zip: ignored
        code, _, err = self.run_tool("GBA")
        self.assertEqual(code, 1)
        self.assertIn("no bundled skin for: GBA", err)
        self.assertEqual(self.tool.skins_to_export(self.skins), [self.skins / "N64.zip"])

    def test_missing_skins_folder(self):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = self.tool.main(["--android", str(self.tmp / "nowhere"), "--out", str(self.out)])
        self.assertEqual(code, 1)
        self.assertIn("no skins folder", err.getvalue())


if __name__ == "__main__":
    unittest.main()
