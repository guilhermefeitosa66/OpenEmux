import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from openemux.core.config import ConfigManager


class ConfigBootstrapDefaultsTests(unittest.TestCase):
    def test_bootstrap_defaults_are_present(self):
        with TemporaryDirectory() as tmp_dir:
            cfg_path = Path(tmp_dir) / "config.yaml"
            manager = ConfigManager(config_file=cfg_path)
            state = manager.get_bootstrap_state()
            updater = manager.get_retroarch_updater_settings()

        self.assertEqual(state.get("status"), "pending")
        self.assertEqual(state.get("version"), 1)
        self.assertIn("completed_steps", state)
        self.assertTrue(updater["enabled"])
        self.assertEqual(updater["mode"], "buildbot_all_cores")
        self.assertIn("cores_base_url", updater)

    def test_bootstrap_need_run_transitions(self):
        with TemporaryDirectory() as tmp_dir:
            cfg_path = Path(tmp_dir) / "config.yaml"
            manager = ConfigManager(config_file=cfg_path)
            self.assertTrue(manager.bootstrap_needs_run())

            manager.start_bootstrap_run()
            self.assertTrue(manager.bootstrap_needs_run())

            manager.finish_bootstrap_success()
            self.assertFalse(manager.bootstrap_needs_run())

            manager.request_bootstrap_retry()
            self.assertTrue(manager.bootstrap_needs_run())

    def test_locale_setter_normalizes_invalid_values(self):
        with TemporaryDirectory() as tmp_dir:
            cfg_path = Path(tmp_dir) / "config.yaml"
            manager = ConfigManager(config_file=cfg_path)

            manager.set_locale("de")
            self.assertEqual(manager.get_locale(), "de")

            manager.set_locale("invalid-locale")
            self.assertEqual(manager.get_locale(), "en")

    def test_cartridge_frame_is_on_by_default(self):
        with TemporaryDirectory() as tmp_dir:
            manager = ConfigManager(config_file=Path(tmp_dir) / "config.yaml")
            self.assertTrue(manager.get_ui_settings()["render_cartridge_overlay"])

    def test_view_mode_defaults_to_the_cartridge_shelf(self):
        with TemporaryDirectory() as tmp_dir:
            manager = ConfigManager(config_file=Path(tmp_dir) / "config.yaml")
            self.assertEqual(manager.get_view_mode(), "cartridge")

    def test_view_mode_round_trips_and_keeps_the_legacy_key_in_step(self):
        with TemporaryDirectory() as tmp_dir:
            cfg_path = Path(tmp_dir) / "config.yaml"
            manager = ConfigManager(config_file=cfg_path)

            manager.set_view_mode("list")
            settings = manager.get_ui_settings()
            self.assertEqual(settings["view_mode"], "list")
            self.assertFalse(settings["render_cartridge_overlay"])

            self.assertEqual(ConfigManager(config_file=cfg_path).get_view_mode(), "list")

    def test_zoom_defaults_to_100_percent_and_round_trips(self):
        with TemporaryDirectory() as tmp_dir:
            cfg_path = Path(tmp_dir) / "config.yaml"
            manager = ConfigManager(config_file=cfg_path)
            self.assertEqual(manager.get_zoom(), 1.0)

            manager.set_zoom(1.5)
            self.assertEqual(ConfigManager(config_file=cfg_path).get_zoom(), 1.5)

    def test_a_junk_zoom_does_not_break_the_library(self):
        with TemporaryDirectory() as tmp_dir:
            cfg_path = Path(tmp_dir) / "config.yaml"
            cfg_path.write_text("ui:\n  zoom: enormous\n", encoding="utf-8")
            self.assertEqual(ConfigManager(config_file=cfg_path).get_zoom(), 1.0)

    def test_an_unknown_view_mode_falls_back_instead_of_breaking_the_library(self):
        with TemporaryDirectory() as tmp_dir:
            cfg_path = Path(tmp_dir) / "config.yaml"
            cfg_path.write_text("ui:\n  view_mode: mosaic\n", encoding="utf-8")
            self.assertEqual(ConfigManager(config_file=cfg_path).get_view_mode(), "cartridge")

    def test_a_config_from_before_view_modes_carries_its_choice_over(self):
        """The cartridge switch was the only layout control there was."""
        with TemporaryDirectory() as tmp_dir:
            cfg_path = Path(tmp_dir) / "config.yaml"
            cfg_path.write_text(
                "ui:\n  version: 1\n  render_cartridge_overlay: false\n", encoding="utf-8"
            )
            self.assertEqual(ConfigManager(config_file=cfg_path).get_view_mode(), "cover")

    def test_config_written_before_the_new_default_switches_over_once(self):
        with TemporaryDirectory() as tmp_dir:
            cfg_path = Path(tmp_dir) / "config.yaml"
            cfg_path.write_text("ui:\n  render_cartridge_overlay: false\n", encoding="utf-8")

            manager = ConfigManager(config_file=cfg_path)
            self.assertTrue(manager.get_ui_settings()["render_cartridge_overlay"])

            # Turning it back off has to stick: the flip happens only once.
            manager.set_render_cartridge_overlay(False)
            reopened = ConfigManager(config_file=cfg_path)
            self.assertFalse(reopened.get_ui_settings()["render_cartridge_overlay"])


if __name__ == "__main__":
    unittest.main()
