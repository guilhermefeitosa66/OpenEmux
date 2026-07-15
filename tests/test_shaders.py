import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from openemux.core.shaders import ShaderCatalog, ShaderConfigStore


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


class ShaderCatalogTests(unittest.TestCase):
    def test_resolve_prefers_glsl_then_slang(self):
        with TemporaryDirectory() as tmp_dir:
            runtime_dir = Path(tmp_dir) / "runtime"
            shader_id = "openemux-dot-test"
            glsl_file = runtime_dir / "shaders_glsl" / "handheld" / f"{shader_id}.glslp"
            slang_file = runtime_dir / "shaders_slang" / "handheld" / f"{shader_id}.slangp"
            glsl_file.parent.mkdir(parents=True, exist_ok=True)
            slang_file.parent.mkdir(parents=True, exist_ok=True)
            glsl_file.write_text("glsl", encoding="utf-8")
            slang_file.write_text("slang", encoding="utf-8")

            catalog = ShaderCatalog(runtime_dir=runtime_dir)
            self.assertEqual(catalog.resolve_shader_path(shader_id), str(glsl_file))

            glsl_file.unlink()
            catalog = ShaderCatalog(runtime_dir=runtime_dir)
            self.assertEqual(catalog.resolve_shader_path(shader_id), str(slang_file))

    def test_get_options_short_list_includes_disabled(self):
        catalog = ShaderCatalog(runtime_dir=Path("/tmp/does-not-matter"))
        options = catalog.get_options(show_all=False)
        self.assertGreaterEqual(len(options), 2)
        self.assertEqual(options[0][0], "disabled")


if __name__ == "__main__":
    unittest.main()
