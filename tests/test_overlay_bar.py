import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openemux.core import overlay_bar


class RuntimeOverridesTests(unittest.TestCase):
    def test_points_at_the_shipped_overlay(self):
        overrides = overlay_bar.runtime_overrides()
        self.assertEqual(overrides["input_overlay_enable"], '"true"')
        path = overrides["input_overlay"].strip('"')
        self.assertTrue(Path(path).is_file(), path)

    def test_turbo_fires_on_its_own_after_one_press(self):
        overrides = overlay_bar.runtime_overrides()
        self.assertEqual(overrides["input_turbo_enable"], '"true"')
        # Single Button (Toggle) in RetroArch 1.22's numbering.
        self.assertEqual(overrides["input_turbo_mode"], '"2"')

    def test_no_system_overlay_replaces_the_bar(self):
        # PlayStation and PSP have a "preferred" touch gamepad RetroArch would
        # load in its place.
        self.assertEqual(
            overlay_bar.runtime_overrides()["input_overlay_enable_autopreferred"], '"false"'
        )

    def test_keeps_the_overlay_clickable_in_fullscreen(self):
        overrides = overlay_bar.runtime_overrides()
        self.assertEqual(overrides["video_windowed_fullscreen"], '"true"')
        self.assertEqual(overrides["input_overlay_hide_when_gamepad_connected"], '"false"')


class ShippedAssetsTests(unittest.TestCase):
    def test_every_image_the_overlay_names_exists(self):
        text = overlay_bar.OVERLAY_CFG.read_text(encoding="utf-8")
        images = {line.split("=", 1)[1].strip()
                  for line in text.splitlines() if "_overlay = " in line}
        self.assertTrue(images)
        for image in images:
            self.assertTrue((overlay_bar.OVERLAY_DIR / image).is_file(), image)

    def test_every_toggle_target_is_a_page(self):
        text = overlay_bar.OVERLAY_CFG.read_text(encoding="utf-8")
        names = {line.split("=", 1)[1].strip().strip('"')
                 for line in text.splitlines() if line.split("=", 1)[0].strip().endswith("_name")}
        targets = {line.split("=", 1)[1].strip().strip('"')
                   for line in text.splitlines() if "_next_target" in line}
        self.assertEqual(len(names), 64)
        self.assertTrue(targets <= names, targets - names)

    def test_margin_shaders_exist_for_both_backends(self):
        for backend in ("glsl", "slang"):
            self.assertTrue(overlay_bar.MARGIN_SHADER[backend].is_file())

    def test_hide_and_show_also_swap_the_shader(self):
        text = overlay_bar.OVERLAY_CFG.read_text(encoding="utf-8")
        swaps = [line for line in text.splitlines() if "overlay_next|shader_next" in line]
        # One hide button per shown page, one show button per hidden page.
        self.assertEqual(len(swaps), 64)

    def test_the_margin_agrees_everywhere(self):
        # Three places say how tall the bar is: the overlay's background
        # strip, MARGIN here (the console shader's last pass is scaled by it)
        # and the margin shaders' own default. Any two disagreeing either
        # cuts the game or leaves a seam -- or resamples the image again.
        text = overlay_bar.OVERLAY_CFG.read_text(encoding="utf-8")
        strip = re.search(r'^overlay0_desc0 = "nul,[^,]+,([^,]+),rect,[^,]+,([^"]+)"', text, re.M)
        center, half_height = float(strip.group(1)), float(strip.group(2))
        self.assertAlmostEqual(2 * half_height, overlay_bar.MARGIN, places=4)
        self.assertAlmostEqual(1 - center, overlay_bar.MARGIN / 2, places=4)
        for shader in overlay_bar.MARGIN_SHADER.values():
            defaults = re.findall(r'#pragma parameter MARGIN "[^"]*" ([0-9.]+)', shader.read_text())
            self.assertEqual(len(defaults), 1, shader)
            self.assertAlmostEqual(float(defaults[0]), overlay_bar.MARGIN, places=5, msg=shader)
        glsl = overlay_bar.MARGIN_SHADER["glsl"].read_text()
        self.assertAlmostEqual(float(re.search(r"#define MARGIN ([0-9.]+)", glsl).group(1)),
                               overlay_bar.MARGIN, places=5)

    def test_turbo_is_a_toggle_on_every_page(self):
        text = overlay_bar.OVERLAY_CFG.read_text(encoding="utf-8")
        self.assertEqual(text.count('"turbo|overlay_next,'), 32)


class StageAssetsTests(unittest.TestCase):
    """RetroArch reads the bar from a copy in the runtime folder (issue #482).

    In the Flatpak the package sits under OpenEmux's own /app, which the
    RetroArch Flatpak cannot see: handed those paths, it drew no bar at all.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.runtime = Path(self._tmp.name) / "runtime"

    def tearDown(self):
        self._tmp.cleanup()

    def test_copies_every_file_into_the_runtime_folder(self):
        staged = overlay_bar.stage_assets(self.runtime)
        self.assertEqual(staged, self.runtime / overlay_bar.STAGED_DIR_NAME)
        shipped = sorted(p.name for p in overlay_bar.OVERLAY_DIR.iterdir() if p.is_file())
        self.assertEqual(sorted(p.name for p in staged.iterdir()), shipped)
        for name in shipped:
            self.assertEqual((staged / name).read_bytes(),
                             (overlay_bar.OVERLAY_DIR / name).read_bytes(), name)

    def test_the_overrides_and_the_margin_point_at_the_copy(self):
        staged = overlay_bar.stage_assets(self.runtime)
        overlay = overlay_bar.runtime_overrides(staged)["input_overlay"].strip('"')
        self.assertEqual(Path(overlay), staged / "openemux-bar.cfg")
        _, shader_dir = overlay_bar.prepare_shaders(None, "gl", self.runtime, staged)
        shown = (Path(shader_dir) / f"{overlay_bar.SHOWN_PRESET}.glslp").read_text()
        self.assertIn(f'shader0 = "{staged / "margin.glsl"}"', shown)
        self.assertNotIn(str(overlay_bar.OVERLAY_DIR), shown)

    def test_an_identical_copy_is_left_alone_and_a_stale_one_refreshed(self):
        staged = overlay_bar.stage_assets(self.runtime)
        same, stale = staged / "openemux-bar.cfg", staged / "margin.glsl"
        stale.write_text("old", encoding="utf-8")
        with patch("openemux.core.overlay_bar.shutil.copyfile") as copy:
            overlay_bar.stage_assets(self.runtime)
        copy.assert_called_once_with(overlay_bar.MARGIN_SHADER["glsl"], stale)
        self.assertTrue(same.is_file())

    def test_only_files_are_copied(self):
        shipped = Path(self._tmp.name) / "shipped"
        (shipped / "sub").mkdir(parents=True)
        (shipped / "bar.cfg").write_text("x", encoding="utf-8")
        with patch.object(overlay_bar, "OVERLAY_DIR", shipped):
            staged = overlay_bar.stage_assets(self.runtime)
        self.assertEqual([p.name for p in staged.iterdir()], ["bar.cfg"])

    def test_falls_back_to_the_package_when_the_copy_fails(self):
        self.runtime.parent.mkdir(parents=True, exist_ok=True)
        self.runtime.write_text("a file, not a folder", encoding="utf-8")
        with self.assertLogs("openemux.core.overlay_bar", "WARNING"):
            self.assertEqual(overlay_bar.stage_assets(self.runtime), overlay_bar.OVERLAY_DIR)


class PrepareShadersTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.runtime = self.tmp / "runtime"

    def tearDown(self):
        self._tmp.cleanup()

    def _preset(self, name, text):
        folder = self.tmp / "shaders" / "crt"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / name
        path.write_text(text, encoding="utf-8")
        return path

    def _pair(self, shader_dir, suffix=".glslp"):
        folder = Path(shader_dir)
        hidden = (folder / f"{overlay_bar.HIDDEN_PRESET}{suffix}").read_text()
        shown = (folder / f"{overlay_bar.SHOWN_PRESET}{suffix}").read_text()
        return hidden, shown

    def test_the_hidden_preset_sorts_first(self):
        # "Next shader" starts from the folder's first entry; the launch loads
        # "shown", so the first hide has to land on "hidden".
        self.assertLess(overlay_bar.HIDDEN_PRESET, overlay_bar.SHOWN_PRESET)

    def test_no_console_shader_gets_a_plain_pair(self):
        preset, shader_dir = overlay_bar.prepare_shaders(None, "gl", self.runtime)
        self.assertEqual(Path(preset).name, f"{overlay_bar.SHOWN_PRESET}.glslp")
        hidden, shown = self._pair(shader_dir)
        self.assertIn('MARGIN = "0.0"', hidden)
        self.assertNotIn("MARGIN", shown)
        self.assertIn(str(overlay_bar.MARGIN_SHADER["glsl"]), shown)

    def test_slang_drivers_get_slang_presets(self):
        preset, shader_dir = overlay_bar.prepare_shaders(None, "vulkan", self.runtime)
        self.assertTrue(preset.endswith(".slangp"))
        _, shown = self._pair(shader_dir, ".slangp")
        self.assertIn(str(overlay_bar.MARGIN_SHADER["slang"]), shown)

    def test_the_folder_holds_only_the_pair(self):
        folder = self.runtime / "in_game_bar"
        folder.mkdir(parents=True)
        (folder / "old.glslp").write_text("shaders = 1\n")
        _, shader_dir = overlay_bar.prepare_shaders(None, "gl", self.runtime)
        self.assertEqual(len(list(Path(shader_dir).iterdir())), 2)

    def test_a_driver_without_shaders_keeps_what_it_had(self):
        self.assertEqual(overlay_bar.prepare_shaders(None, "sdl2", self.runtime), (None, None))
        self.assertEqual(overlay_bar.prepare_shaders("x.glslp", "sdl2", self.runtime),
                         ("x.glslp", None))

    def test_a_console_shader_is_kept_in_both_with_absolute_paths(self):
        preset = self._preset("easy.glslp", (
            "shaders = 1\n"
            "shader0 = shaders/crt-easymode.glsl\n"
            "filter_linear0 = false\n"
            'textures = "LUT"\n'
            'LUT = "../luts/lut.png"\n'
            "# a comment stays\n"
        ))
        _, shader_dir = overlay_bar.prepare_shaders(str(preset), "gl", self.runtime)
        hidden, shown = self._pair(shader_dir)
        pass0 = f'shader0 = "{(preset.parent / "shaders/crt-easymode.glsl").resolve()}"'
        lut = f'LUT = "{(preset.parent / "../luts/lut.png").resolve()}"'
        for text in (hidden, shown):
            self.assertIn(pass0, text)
            self.assertIn(lut, text)
            self.assertIn("# a comment stays", text)
        self.assertIn('shaders = "1"', hidden)
        self.assertNotIn("shader1", hidden)
        self.assertIn('shaders = "2"', shown)
        self.assertIn(f'shader1 = "{overlay_bar.MARGIN_SHADER["glsl"]}"', shown)
        self.assertIn('scale_type1 = "viewport"', shown)
        # The console shader's last pass stops being the last one: it is told
        # to render at the shrunk viewport size, and the margin only places it.
        self.assertIn('scale_type0 = "viewport"', shown)
        self.assertIn(f'scale0 = "{1 - overlay_bar.MARGIN:.6f}"', shown)
        self.assertIn('filter_linear1 = "false"', shown)
        self.assertNotIn("scale_type0", hidden)

    def test_the_last_pass_own_scale_is_replaced_not_duplicated(self):
        preset = self._preset("two.glslp", (
            "shaders = 2\n"
            "shader0 = a.glsl\nscale_type0 = source\nscale0 = 2.0\n"
            "shader1 = b.glsl\nscale_type1 = source\nscale_x1 = 3.0\nscale1 = 1.0\n"
        ))
        _, shader_dir = overlay_bar.prepare_shaders(str(preset), "gl", self.runtime)
        hidden, shown = self._pair(shader_dir)
        # The first pass keeps its own scale; the last one gets the viewport.
        self.assertIn('scale_type0 = "source"', shown)
        self.assertIn('scale0 = "2.0"', shown)
        self.assertNotIn('scale_type1 = "source"', shown)
        self.assertNotIn("scale_x1", shown)
        self.assertEqual(shown.count("scale_type1 ="), 1)
        self.assertEqual(shown.count("scale1 ="), 1)
        self.assertIn('scale_type1 = "source"', hidden)

    def test_leaves_absolute_paths_alone(self):
        # Absolute on this platform: "/opt/s.glsl" is not, on Windows -- it
        # has no drive -- so it is (rightly) resolved like a relative path.
        absolute = (self.tmp / "elsewhere" / "s.glsl").as_posix()
        preset = self._preset("abs.glslp", f"shaders = 1\nshader0 = {absolute}\n")
        _, shader_dir = overlay_bar.prepare_shaders(str(preset), "gl", self.runtime)
        self.assertIn(f'shader0 = "{absolute}"', self._pair(shader_dir)[1])

    def test_presets_it_cannot_extend_are_returned_as_is(self):
        cases = {
            "other backend": self._preset("easy.slangp", "shaders = 1\n"),
            "missing": self.tmp / "missing.glslp",
            "reference": self._preset("ref.glslp", '#reference "base.glslp"\n'),
            "no pass count": self._preset("odd.glslp", "shader0 = a.glsl\n"),
        }
        for label, preset in cases.items():
            with self.subTest(label):
                self.assertEqual(overlay_bar.prepare_shaders(str(preset), "gl", self.runtime),
                                 (str(preset), None))


if __name__ == "__main__":
    unittest.main()
