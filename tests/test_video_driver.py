"""The video driver decides which shader presets exist (#366).

A game launched from the Windows bundle ran with no shader whatever the console
was configured with, and the launch log carried no shader line at all -- not a
load, not a failure. Two facts explain it: RetroArch's Windows default video
driver is ``d3d11``, and ``ShaderCatalog`` preferred ``.glslp`` unconditionally.
GLSL presets are loadable only by ``gl``, so RetroArch was handed a preset it
could not use and dropped it without a word.
"""

import unittest
from unittest.mock import patch

from openemux.core.video_driver import (
    AUTO,
    LINUX_DEFAULT,
    WINDOWS_DEFAULT,
    default_video_driver,
    effective_video_driver,
    preset_backends,
    resolve_video_driver,
)


class WhatGetsWrittenTests(unittest.TestCase):
    def test_auto_names_the_driver_on_windows(self):
        # Naming what RetroArch would have picked anyway is what makes it
        # knowable: the preset backend is chosen against a driver, so the
        # driver cannot be left to be discovered from a log after the fact.
        with patch("openemux.core.video_driver.IS_WINDOWS", True):
            self.assertEqual(resolve_video_driver(AUTO), WINDOWS_DEFAULT)

    def test_auto_writes_nothing_on_linux(self):
        # The vendored Linux build already runs gl -- restating a default would
        # be a line that reads as load-bearing and is not.
        with patch("openemux.core.video_driver.IS_WINDOWS", False):
            self.assertIsNone(resolve_video_driver(AUTO))

    def test_an_empty_setting_means_auto(self):
        with patch("openemux.core.video_driver.IS_WINDOWS", False):
            self.assertIsNone(resolve_video_driver(""))
            self.assertIsNone(resolve_video_driver(None))
            self.assertIsNone(resolve_video_driver("   "))

    def test_a_named_driver_is_passed_through(self):
        for setting in ("vulkan", " Vulkan ", "glcore"):
            with self.subTest(setting=setting):
                self.assertEqual(
                    resolve_video_driver(setting), setting.strip().lower()
                )


class WhatRetroarchWillRunTests(unittest.TestCase):
    def test_it_is_never_unknown(self):
        # "Nothing was written" means "RetroArch's own default", which is a
        # known value, not a missing one.
        with patch("openemux.core.video_driver.IS_WINDOWS", False):
            self.assertEqual(effective_video_driver(AUTO), LINUX_DEFAULT)
        with patch("openemux.core.video_driver.IS_WINDOWS", True):
            self.assertEqual(effective_video_driver(AUTO), WINDOWS_DEFAULT)

    def test_the_platform_default_matches_what_retroarch_picks(self):
        with patch("openemux.core.video_driver.IS_WINDOWS", True):
            self.assertEqual(default_video_driver(), "d3d11")
        with patch("openemux.core.video_driver.IS_WINDOWS", False):
            self.assertEqual(default_video_driver(), "gl")


class WhichPresetsADriverCanLoadTests(unittest.TestCase):
    def test_only_gl_reads_glsl(self):
        self.assertEqual(preset_backends("gl"), ("glsl",))

    def test_the_vulkan_era_drivers_read_slang(self):
        for driver in ("vulkan", "glcore", "metal", "d3d10", "d3d11", "d3d12"):
            with self.subTest(driver=driver):
                self.assertEqual(preset_backends(driver), ("slang",))

    def test_no_driver_gets_both(self):
        # The old order tried glsl and then slang for every driver, which reads
        # as a graceful fallback and is not one: the second format is just as
        # unloadable as the first for a driver that cannot read it.
        for driver in ("gl", "vulkan", "d3d11", "glcore"):
            with self.subTest(driver=driver):
                self.assertEqual(len(preset_backends(driver)), 1)

    def test_a_driver_with_no_shader_pipeline_gets_none(self):
        for driver in ("sdl2", "null", "d3d9", "gdi", "", None):
            with self.subTest(driver=driver):
                self.assertEqual(preset_backends(driver), ())

    def test_the_name_is_matched_case_insensitively(self):
        self.assertEqual(preset_backends("D3D11"), ("slang",))
        self.assertEqual(preset_backends(" GL "), ("glsl",))


if __name__ == "__main__":
    unittest.main()
