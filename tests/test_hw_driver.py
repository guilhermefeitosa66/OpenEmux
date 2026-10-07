"""Which video driver a core makes RetroArch end up on (issue #471)."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from openemux.core import hw_driver
from openemux.core.hw_driver import HwDriverMemory, forced_driver, predicted_driver


class ReadingTheSwitchTests(unittest.TestCase):
    def test_each_switch_retroarch_logs_is_named_by_its_driver(self):
        self.assertEqual(forced_driver("[INFO] [Video] Using HW render, glcore driver forced."), "glcore")
        self.assertEqual(forced_driver("[INFO] [Video] Using HW render, OpenGL driver forced."), "gl")
        self.assertEqual(forced_driver("[INFO] [Video] Using HW render, vulkan driver forced."), "vulkan")

    def test_no_switch_or_an_unknown_driver_is_none(self):
        self.assertIsNone(forced_driver("[INFO] [Video] Set video size to: 1280x720."))
        self.assertIsNone(forced_driver("Using HW render, d3d11 driver forced."))
        self.assertIsNone(forced_driver(None))


class _CoreDir(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def core(self, name, required_hw_api=None):
        path = self.dir / f"{name}_libretro.so"
        path.write_bytes(b"")
        if required_hw_api is not None:
            path.with_suffix(".info").write_text(
                f'corename = "{name}"\nrequired_hw_api = "{required_hw_api}"\n', encoding="utf-8"
            )
        return path


class TheInfoFileTests(_CoreDir):
    def test_a_core_profile_only_core_asks_for_glcore(self):
        # mupen64plus_next's own line.
        core = self.core("mupen", "OpenGL Core >= 3.3 | OpenGL ES >= 2.0")
        self.assertEqual(hw_driver.driver_from_info(core), "glcore")

    def test_core_profile_or_vulkan_is_still_glcore_under_opengl(self):
        core = self.core("hw", "OpenGL Core >= 3.3 | Vulkan >= 1.0")
        self.assertEqual(hw_driver.driver_from_info(core), "glcore")

    def test_a_vulkan_only_core_asks_for_vulkan(self):
        self.assertEqual(hw_driver.driver_from_info(self.core("vk", "Vulkan >= 1.1")), "vulkan")

    def test_a_core_that_also_takes_legacy_opengl_is_not_guessed(self):
        # Which context it asks for depends on its options and RetroArch's
        # preference: ppsspp asked for legacy OpenGL here, parallel_n64 for
        # the core profile, and both list legacy OpenGL.
        core = self.core("ppsspp", "OpenGL >= 3.0 | OpenGL Core >= 3.1 | Vulkan >= 1.0")
        self.assertIsNone(hw_driver.driver_from_info(core))

    def test_software_cores_and_unreadable_files_say_nothing(self):
        self.assertIsNone(hw_driver.driver_from_info(self.core("snes9x")))
        self.assertIsNone(hw_driver.driver_from_info(self.core("es", "OpenGL ES >= 2.0")))
        self.assertIsNone(hw_driver.driver_from_info(self.core("empty", "")))
        bare = self.dir / "bare_libretro.so"
        bare.with_suffix(".info").write_text('corename = "bare"\n', encoding="utf-8")
        self.assertIsNone(hw_driver.driver_from_info(bare))


class TheMemoryTests(_CoreDir):
    def test_what_a_launch_logged_is_where_the_next_one_starts(self):
        memory = HwDriverMemory(self.dir / "runtime")
        core = self.core("parallel_n64")
        log = self.dir / "launch.log"
        log.write_text("[INFO] [Video] Using HW render, glcore driver forced.\n", encoding="utf-8")
        self.assertEqual(memory.remember_from_log(core, log), "glcore")
        self.assertEqual(HwDriverMemory(self.dir / "runtime").get(core), "glcore")

    def test_a_launch_that_did_not_switch_records_nothing(self):
        memory = HwDriverMemory(self.dir)
        log = self.dir / "launch.log"
        log.write_text("[INFO] nothing to see\n", encoding="utf-8")
        self.assertIsNone(memory.remember_from_log(self.core("snes9x"), log))
        self.assertFalse(memory.path.exists())

    def test_missing_pieces_and_unreadable_logs_are_shrugged_off(self):
        memory = HwDriverMemory(self.dir)
        self.assertIsNone(memory.remember_from_log(None, self.dir / "x.log"))
        self.assertIsNone(memory.remember_from_log(self.core("a"), None))
        self.assertIsNone(memory.remember_from_log(self.core("a"), self.dir / "missing.log"))

    def test_the_same_answer_is_not_written_again(self):
        memory = HwDriverMemory(self.dir)
        core = self.core("a")
        memory.remember(core, "gl")
        with mock.patch.object(Path, "write_text") as write:
            memory.remember(core, "gl")
        write.assert_not_called()

    def test_a_file_that_cannot_be_written_is_reported_not_raised(self):
        memory = HwDriverMemory(self.dir)
        with mock.patch.object(Path, "write_text", side_effect=OSError("read-only")):
            with self.assertLogs("openemux.core.hw_driver", level="WARNING"):
                memory.remember(self.core("a"), "gl")

    def test_a_broken_or_odd_file_reads_as_empty(self):
        memory = HwDriverMemory(self.dir)
        core = self.core("a")
        memory.path.write_text("not json", encoding="utf-8")
        self.assertIsNone(memory.get(core))
        memory.path.write_text("[1, 2]", encoding="utf-8")
        self.assertIsNone(memory.get(core))
        memory.path.write_text('{"a": "d3d11"}', encoding="utf-8")
        self.assertIsNone(memory.get(core))


class ThePredictionTests(_CoreDir):
    def test_memory_wins_over_the_table_and_the_info(self):
        memory = HwDriverMemory(self.dir)
        core = self.core("parallel_n64", "OpenGL Core >= 3.3")
        memory.remember(core, "vulkan")
        self.assertEqual(predicted_driver(core, memory), "vulkan")

    def test_parallel_n64_is_known_to_ask_for_glcore(self):
        # Its .info lists legacy OpenGL first; measured asking for 4.3 core.
        core = self.core("parallel_n64", "OpenGL >= 3.0 | OpenGL ES >= 2.0 | Vulkan >= 1.0")
        self.assertEqual(predicted_driver(core, HwDriverMemory(self.dir)), "glcore")

    def test_the_info_is_the_last_word_and_software_is_none(self):
        memory = HwDriverMemory(self.dir)
        self.assertEqual(predicted_driver(self.core("m", "OpenGL Core >= 3.3"), memory), "glcore")
        self.assertIsNone(predicted_driver(self.core("snes9x"), memory))
        self.assertIsNone(predicted_driver(None, memory))


if __name__ == "__main__":
    unittest.main()
