import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from openemux.core.shaders import ShaderCatalog, ShaderConfigStore
from tests.platform_marks import IS_WINDOWS


class ShaderConfigStoreTests(unittest.TestCase):
    def test_defaults_follow_console_rules(self):
        with TemporaryDirectory() as tmp_dir:
            store = ShaderConfigStore(config_file=Path(tmp_dir) / "shaders.config")
            self.assertEqual(store.get_console_shader("GBA"), "dot")
            self.assertEqual(store.get_console_shader("FC"), "geom-crt")

    def test_override_persists_and_reset_restores(self):
        with TemporaryDirectory() as tmp_dir:
            cfg_path = Path(tmp_dir) / "shaders.config"
            store = ShaderConfigStore(config_file=cfg_path)
            store.set_console_shader("FC", "zfast-crt")
            reloaded = ShaderConfigStore(config_file=cfg_path)
            self.assertEqual(reloaded.get_console_shader("FC"), "zfast-crt")
            reloaded.reset_defaults()
            self.assertEqual(reloaded.get_console_shader("FC"), "geom-crt")

    def test_show_all_flag_persists(self):
        with TemporaryDirectory() as tmp_dir:
            cfg_path = Path(tmp_dir) / "shaders.config"
            store = ShaderConfigStore(config_file=cfg_path)
            store.set_show_all_shaders(True)
            self.assertTrue(ShaderConfigStore(config_file=cfg_path).get_show_all_shaders())

    def test_rom_override_wins_over_console_and_persists(self):
        with TemporaryDirectory() as tmp_dir:
            cfg_path = Path(tmp_dir) / "shaders.config"
            store = ShaderConfigStore(config_file=cfg_path)
            store.set_console_shader("SFC", "geom-crt")
            rom = "/games/SFC/Chrono Trigger.sfc"
            store.set_rom_shader(rom, "SFC", "disabled")

            reloaded = ShaderConfigStore(config_file=cfg_path)
            self.assertEqual(reloaded.get_rom_shader(rom), "disabled")
            self.assertEqual(reloaded.get_effective_shader(rom, "SFC"), "disabled")
            # A different game on the same console still follows the console.
            self.assertEqual(
                reloaded.get_effective_shader("/games/SFC/Other.sfc", "SFC"), "geom-crt"
            )

    def test_use_console_setting_clears_rom_override(self):
        with TemporaryDirectory() as tmp_dir:
            cfg_path = Path(tmp_dir) / "shaders.config"
            store = ShaderConfigStore(config_file=cfg_path)
            rom = "/games/GBA/Metroid.gba"
            store.set_rom_shader(rom, "GBA", "zfast-crt")
            store.set_rom_shader(rom, "GBA", None)
            self.assertIsNone(store.get_rom_shader(rom))
            self.assertEqual(store.get_effective_shader(rom, "GBA"), "dot")

    def test_rom_override_equal_to_console_is_not_stored(self):
        with TemporaryDirectory() as tmp_dir:
            store = ShaderConfigStore(config_file=Path(tmp_dir) / "shaders.config")
            rom = "/games/FC/Contra.nes"
            # geom-crt is FC's default -- storing it as a ROM override is a no-op.
            store.set_rom_shader(rom, "FC", "geom-crt")
            self.assertIsNone(store.get_rom_shader(rom))

    def test_rom_override_follows_rename_and_drops_on_delete(self):
        with TemporaryDirectory() as tmp_dir:
            store = ShaderConfigStore(config_file=Path(tmp_dir) / "shaders.config")
            old, new = "/games/MD/Sonic.md", "/games/MD/Sonic 1.md"
            store.set_rom_shader(old, "MD", "disabled")
            store.repath_rom(old, new)
            self.assertIsNone(store.get_rom_shader(old))
            self.assertEqual(store.get_rom_shader(new), "disabled")
            store.forget_rom(new)
            self.assertIsNone(store.get_rom_shader(new))


class ShaderCatalogTests(unittest.TestCase):
    """Which preset a driver gets. The backend is not a preference (issue #366).

    ``.glslp`` is loadable only by ``gl`` and ``.slangp`` only by the
    Vulkan-era drivers, so "prefer glsl, fall back to slang" was right on Linux
    by accident and wrong on every Windows install, where RetroArch runs
    ``d3d11`` and quietly dropped the ``.glslp`` it was handed.
    """

    def _catalog_with_both_presets(self, tmp_dir, shader_id):
        runtime_dir = Path(tmp_dir) / "runtime"
        glsl_file = runtime_dir / "shaders_glsl" / "handheld" / f"{shader_id}.glslp"
        slang_file = runtime_dir / "shaders_slang" / "handheld" / f"{shader_id}.slangp"
        glsl_file.parent.mkdir(parents=True, exist_ok=True)
        slang_file.parent.mkdir(parents=True, exist_ok=True)
        glsl_file.write_text("glsl", encoding="utf-8")
        slang_file.write_text("slang", encoding="utf-8")
        return runtime_dir, glsl_file, slang_file

    def test_the_gl_driver_gets_the_glsl_preset(self):
        with TemporaryDirectory() as tmp_dir:
            shader_id = "openemux-dot-test"
            runtime_dir, glsl_file, _ = self._catalog_with_both_presets(tmp_dir, shader_id)
            catalog = ShaderCatalog(runtime_dir=runtime_dir)
            self.assertEqual(
                catalog.resolve_shader_path(shader_id, video_driver="gl"),
                str(glsl_file),
            )

    def test_a_d3d11_host_gets_the_slang_preset(self):
        with TemporaryDirectory() as tmp_dir:
            shader_id = "openemux-dot-test"
            runtime_dir, _, slang_file = self._catalog_with_both_presets(tmp_dir, shader_id)
            catalog = ShaderCatalog(runtime_dir=runtime_dir)
            for driver in ("d3d11", "d3d12", "vulkan", "glcore"):
                with self.subTest(driver=driver):
                    self.assertEqual(
                        catalog.resolve_shader_path(shader_id, video_driver=driver),
                        str(slang_file),
                    )

    def test_a_driver_never_gets_the_other_backend_as_a_fallback(self):
        # The old glsl-then-slang order made this look like a graceful
        # fallback. It is not: RetroArch discards the preset without a word,
        # which is the whole of issue #366.
        with TemporaryDirectory() as tmp_dir:
            shader_id = "openemux-dot-test"
            runtime_dir, glsl_file, slang_file = self._catalog_with_both_presets(
                tmp_dir, shader_id
            )
            slang_file.unlink()
            catalog = ShaderCatalog(runtime_dir=runtime_dir)
            self.assertIsNone(
                catalog.resolve_shader_path(shader_id, video_driver="d3d11")
            )

            slang_file.write_text("slang", encoding="utf-8")
            glsl_file.unlink()
            catalog = ShaderCatalog(runtime_dir=runtime_dir)
            self.assertIsNone(catalog.resolve_shader_path(shader_id, video_driver="gl"))

    def test_a_driver_with_no_shader_pipeline_gets_nothing(self):
        with TemporaryDirectory() as tmp_dir:
            shader_id = "openemux-dot-test"
            runtime_dir, _, _ = self._catalog_with_both_presets(tmp_dir, shader_id)
            catalog = ShaderCatalog(runtime_dir=runtime_dir)
            # An empty string is "nobody said", not "a driver with no
            # pipeline": that case is the next test.
            for driver in ("sdl2", "null", "d3d9"):
                with self.subTest(driver=driver):
                    self.assertIsNone(
                        catalog.resolve_shader_path(shader_id, video_driver=driver)
                    )

    def test_no_driver_named_means_the_one_this_platform_runs(self):
        with TemporaryDirectory() as tmp_dir:
            shader_id = "openemux-dot-test"
            runtime_dir, glsl_file, slang_file = self._catalog_with_both_presets(
                tmp_dir, shader_id
            )
            catalog = ShaderCatalog(runtime_dir=runtime_dir)
            expected = slang_file if IS_WINDOWS else glsl_file
            self.assertEqual(catalog.resolve_shader_path(shader_id), str(expected))

    def test_get_options_short_list_includes_disabled(self):
        catalog = ShaderCatalog(runtime_dir=Path("/tmp/does-not-matter"))
        options = catalog.get_options(show_all=False)
        self.assertGreaterEqual(len(options), 2)
        self.assertEqual(options[0][0], "disabled")


if __name__ == "__main__":
    unittest.main()
