import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import yaml

from openemux.core.cartridge_colors import CartridgeColorStore
from openemux.core.collections import CollectionManager
from openemux.core.config import ConfigManager
from openemux.core.core_options import CoreOptionsStore
from openemux.core.cores import CoreConfigStore
from openemux.core.input_profiles import InputProfileManager
from openemux.core.play_history import PlayHistory
from openemux.core.retroachievements import AchievementsStore
from openemux.core.shaders import ShaderConfigStore
from openemux.core.state_recovery import (
    quarantine_state_file,
    quarantined_files,
    reset_quarantine_log,
)


def _broken_copies(path):
    """The ``<name>.broken-<stamp>`` files kept beside ``path``."""
    path = Path(path)
    return sorted(p for p in path.parent.glob(f"{path.name}.broken-*"))


class QuarantineTests(unittest.TestCase):
    def setUp(self):
        reset_quarantine_log()

    def tearDown(self):
        reset_quarantine_log()

    def test_the_file_is_kept_under_a_timestamped_name(self):
        with TemporaryDirectory() as tmp_dir:
            target = Path(tmp_dir) / "config.yaml"
            target.write_text("roms_path: /games\n", encoding="utf-8")

            kept = quarantine_state_file(target, "boom")

            self.assertFalse(target.exists())
            self.assertEqual(kept.read_text(encoding="utf-8"), "roms_path: /games\n")
            self.assertTrue(kept.name.startswith("config.yaml.broken-"))

    def test_a_second_failure_in_the_same_second_keeps_both(self):
        with TemporaryDirectory() as tmp_dir:
            target = Path(tmp_dir) / "config.yaml"
            frozen = lambda: 1_700_000_000.0

            target.write_text("first\n", encoding="utf-8")
            first = quarantine_state_file(target, "boom", clock=frozen)
            target.write_text("second\n", encoding="utf-8")
            second = quarantine_state_file(target, "boom", clock=frozen)

            self.assertNotEqual(first, second)
            self.assertEqual(first.read_text(encoding="utf-8"), "first\n")
            self.assertEqual(second.read_text(encoding="utf-8"), "second\n")

    def test_a_missing_file_is_not_reported(self):
        with TemporaryDirectory() as tmp_dir:
            self.assertIsNone(
                quarantine_state_file(Path(tmp_dir) / "gone.yaml", "boom")
            )
            self.assertEqual(quarantined_files(), [])

    def test_what_was_set_aside_is_recorded_for_the_ui(self):
        with TemporaryDirectory() as tmp_dir:
            target = Path(tmp_dir) / "cores.config"
            target.write_text("{{{", encoding="utf-8")

            quarantine_state_file(target, "bad yaml")

            recorded = quarantined_files()
            self.assertEqual(len(recorded), 1)
            self.assertEqual(recorded[0]["original"], target)
            self.assertEqual(recorded[0]["error"], "bad yaml")


class ConfigRecoveryTests(unittest.TestCase):
    def setUp(self):
        reset_quarantine_log()

    def tearDown(self):
        reset_quarantine_log()

    def test_a_broken_config_is_kept_instead_of_overwritten(self):
        with TemporaryDirectory() as tmp_dir:
            config_file = Path(tmp_dir) / "config.yaml"
            config_file.write_text("roms_path: [unclosed\n", encoding="utf-8")

            manager = ConfigManager(config_file=config_file)

            kept = _broken_copies(config_file)
            self.assertEqual(len(kept), 1)
            self.assertEqual(kept[0].read_text(encoding="utf-8"), "roms_path: [unclosed\n")
            # The app still comes up, on defaults.
            self.assertTrue(manager.get_roms_path())
            self.assertEqual(len(quarantined_files()), 1)

    def test_a_config_that_is_not_a_mapping_is_treated_as_corrupt(self):
        # _merge_defaults would raise AttributeError on a scalar; the old code
        # caught it and wrote defaults over the file.
        with TemporaryDirectory() as tmp_dir:
            config_file = Path(tmp_dir) / "config.yaml"
            config_file.write_text("just a string\n", encoding="utf-8")

            ConfigManager(config_file=config_file)

            self.assertEqual(len(_broken_copies(config_file)), 1)

    def test_an_empty_config_is_not_corrupt(self):
        with TemporaryDirectory() as tmp_dir:
            config_file = Path(tmp_dir) / "config.yaml"
            config_file.write_text("# nothing here\n", encoding="utf-8")

            manager = ConfigManager(config_file=config_file)

            self.assertEqual(_broken_copies(config_file), [])
            self.assertEqual(quarantined_files(), [])
            self.assertTrue(manager.get_roms_path())


class StoreRecoveryTests(unittest.TestCase):
    def setUp(self):
        reset_quarantine_log()

    def tearDown(self):
        reset_quarantine_log()

    def test_a_broken_cores_store_keeps_the_pinned_cores(self):
        with TemporaryDirectory() as tmp_dir:
            config_file = Path(tmp_dir) / "cores.config"
            config_file.write_text("rom_overrides: [oops\n", encoding="utf-8")
            store = CoreConfigStore(config_file=config_file)

            self.assertEqual(store.load()["rom_overrides"], {})
            kept = _broken_copies(config_file)
            self.assertEqual(len(kept), 1)
            self.assertIn("oops", kept[0].read_text(encoding="utf-8"))

    def test_a_cores_store_that_is_a_list_does_not_crash(self):
        with TemporaryDirectory() as tmp_dir:
            config_file = Path(tmp_dir) / "cores.config"
            config_file.write_text("- a\n- b\n", encoding="utf-8")
            store = CoreConfigStore(config_file=config_file)

            self.assertEqual(store.load()["rom_overrides"], {})
            self.assertEqual(len(_broken_copies(config_file)), 1)

    def test_a_broken_shader_store_is_kept(self):
        with TemporaryDirectory() as tmp_dir:
            config_file = Path(tmp_dir) / "shaders.config"
            config_file.write_text("console_overrides: [oops\n", encoding="utf-8")
            store = ShaderConfigStore(config_file=config_file)

            self.assertEqual(store.load()["console_overrides"], {})
            self.assertEqual(len(_broken_copies(config_file)), 1)

    def test_a_broken_cartridge_color_store_is_kept(self):
        with TemporaryDirectory() as tmp_dir:
            config_file = Path(tmp_dir) / "cartridge_colors.config"
            config_file.write_text("rom_overrides: [oops\n", encoding="utf-8")
            store = CartridgeColorStore(config_file=config_file)

            self.assertEqual(store.load()["rom_overrides"], {})
            self.assertEqual(len(_broken_copies(config_file)), 1)

    def test_a_broken_core_options_store_is_kept(self):
        with TemporaryDirectory() as tmp_dir:
            config_file = Path(tmp_dir) / "core_options.config"
            config_file.write_text("{not json", encoding="utf-8")
            store = CoreOptionsStore(config_file)

            self.assertEqual(store.load(), {})
            self.assertEqual(len(_broken_copies(config_file)), 1)

    def test_a_broken_achievements_store_is_kept(self):
        with TemporaryDirectory() as tmp_dir:
            config_file = Path(tmp_dir) / "cheevos.config"
            config_file.write_text("{not json", encoding="utf-8")
            store = AchievementsStore(config_file)

            self.assertEqual(store.load(), {})
            self.assertEqual(len(_broken_copies(config_file)), 1)

    def test_a_broken_play_history_is_kept(self):
        with TemporaryDirectory() as tmp_dir:
            history_file = Path(tmp_dir) / "play_history.json"
            history_file.write_text("{not json", encoding="utf-8")

            history = PlayHistory(history_file=history_file)

            self.assertFalse(history.has_history())
            self.assertEqual(len(_broken_copies(history_file)), 1)

    def test_a_broken_input_profile_is_kept_instead_of_reset(self):
        with TemporaryDirectory() as tmp_dir:
            manager = InputProfileManager(Path(tmp_dir))
            path = manager.profile_path("SFC")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('{"keyboard": {"a": ', encoding="utf-8")

            profile = manager.load_profile("SFC")

            self.assertTrue(profile)  # the console still works, on defaults
            kept = _broken_copies(path)
            self.assertEqual(len(kept), 1)
            self.assertIn('"keyboard"', kept[0].read_text(encoding="utf-8"))


class CollectionsRecoveryTests(unittest.TestCase):
    def setUp(self):
        reset_quarantine_log()

    def tearDown(self):
        reset_quarantine_log()

    def _manager(self, tmp_dir):
        return CollectionManager(Path(tmp_dir))

    def test_a_broken_index_is_rebuilt_from_the_list_files(self):
        with TemporaryDirectory() as tmp_dir:
            manager = self._manager(tmp_dir)
            manager.create("Best of SNES")
            manager.add("best-of-snes", ["/roms/a.sfc", "/roms/b.sfc"])
            manager.index_path.write_text("collections: [oops\n", encoding="utf-8")

            listed = manager.list_collections()

            self.assertEqual([entry["slug"] for entry in listed], ["best-of-snes"])
            self.assertEqual(listed[0]["name"], "Best Of Snes")
            self.assertEqual(manager.paths("best-of-snes"), ["/roms/a.sfc", "/roms/b.sfc"])

    def test_a_new_collection_after_a_broken_index_does_not_orphan_the_old_one(self):
        with TemporaryDirectory() as tmp_dir:
            manager = self._manager(tmp_dir)
            manager.create("Best of SNES")
            manager.add("best-of-snes", ["/roms/a.sfc"])
            manager.index_path.write_text("collections: [oops\n", encoding="utf-8")

            manager.create("Shooters")

            slugs = sorted(entry["slug"] for entry in manager.list_collections())
            self.assertEqual(slugs, ["best-of-snes", "shooters"])
            self.assertEqual(manager.paths("best-of-snes"), ["/roms/a.sfc"])

    def test_the_broken_index_is_kept_on_disk(self):
        with TemporaryDirectory() as tmp_dir:
            manager = self._manager(tmp_dir)
            manager.create("Best of SNES")
            manager.index_path.write_text("collections: [oops\n", encoding="utf-8")

            manager.list_collections()

            kept = _broken_copies(manager.index_path)
            self.assertEqual(len(kept), 1)
            self.assertIn("oops", kept[0].read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
