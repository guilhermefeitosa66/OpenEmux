"""Per-console core options (issue #296).

Core options are not config keys, and a value the core does not recognise is
silently ignored -- which looks exactly like the setting doing nothing. So the
catalog is the contract, and anything outside it never reaches a file.
"""

import unittest
from unittest import mock
from pathlib import Path
from tempfile import TemporaryDirectory

from openemux.core import core_options
from openemux.core.core_options import CoreOptionsStore

BEETLE = "mednafen_psx_hw_libretro.so"
PPSSPP = "ppsspp_libretro.so"


class CatalogTests(unittest.TestCase):
    def test_the_core_stem_drops_the_libretro_suffix(self):
        self.assertEqual(core_options.core_stem(BEETLE), "mednafen_psx_hw")
        self.assertEqual(core_options.core_stem("/a/b/ppsspp_libretro.so"), "ppsspp")
        self.assertEqual(core_options.core_stem(""), "")

    def test_a_core_with_no_entry_has_no_options(self):
        self.assertEqual(core_options.options_for_core("snes9x_libretro.so"), [])

    def test_every_option_default_is_one_of_its_own_values(self):
        # A default outside the list would mean the UI opens on a value the
        # core never offered.
        for core, options in core_options.CORE_OPTIONS.items():
            for option in options:
                self.assertIn(option.default, option.values, f"{core}/{option.key}")

    def test_every_option_shares_its_core_prefix(self):
        # The launcher recognises a core's own options file by that prefix,
        # and it is not the file name: Beetle PSX HW ships as
        # mednafen_psx_hw_libretro.so and names its options beetle_psx_hw_*.
        for core, options in core_options.CORE_OPTIONS.items():
            prefix = core_options.option_prefix(f"{core}_libretro.so")
            self.assertTrue(prefix, core)
            for option in options:
                self.assertTrue(option.key.startswith(prefix), option.key)

    def test_the_option_prefix_is_the_cores_own_name(self):
        self.assertEqual(core_options.option_prefix(BEETLE), "beetle_psx_hw_")
        self.assertEqual(core_options.option_prefix(PPSSPP), "ppsspp_")
        self.assertEqual(core_options.option_prefix("snes9x_libretro.so"), "")


class SanitizeTests(unittest.TestCase):
    def test_a_known_value_survives(self):
        self.assertEqual(
            core_options.sanitize(PPSSPP, {"ppsspp_internal_resolution": "960x544"}),
            {"ppsspp_internal_resolution": "960x544"},
        )

    def test_an_option_the_core_does_not_have_is_dropped(self):
        self.assertEqual(core_options.sanitize(PPSSPP, {"beetle_psx_hw_filter": "xBR"}), {})

    def test_a_value_the_core_does_not_accept_is_dropped(self):
        self.assertEqual(
            core_options.sanitize(PPSSPP, {"ppsspp_texture_filtering": "Trilinear"}), {}
        )

    def test_the_default_is_not_written(self):
        self.assertEqual(
            core_options.sanitize(BEETLE, {"beetle_psx_hw_renderer": "hardware"}), {}
        )


class OptionsFileTests(unittest.TestCase):
    def test_the_file_is_retroarch_shaped(self):
        text = core_options.render_options_file({"beetle_psx_hw_filter": "xBR"})
        self.assertEqual(text, 'beetle_psx_hw_filter = "xBR"\n')

    def test_nothing_chosen_writes_nothing(self):
        self.assertEqual(core_options.render_options_file({}), "")

    def test_what_the_user_set_inside_retroarch_is_carried_over(self):
        text = core_options.render_options_file(
            {"beetle_psx_hw_filter": "xBR"},
            inherited={"beetle_psx_hw_dither_mode": "internal resolution"},
        )
        self.assertIn('beetle_psx_hw_dither_mode = "internal resolution"', text)
        self.assertIn('beetle_psx_hw_filter = "xBR"', text)

    def test_ours_wins_over_the_inherited_value(self):
        text = core_options.render_options_file(
            {"beetle_psx_hw_filter": "xBR"},
            inherited={"beetle_psx_hw_filter": "nearest"},
        )
        self.assertEqual(text, 'beetle_psx_hw_filter = "xBR"\n')

    def test_a_file_round_trips(self):
        with TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "core-options.cfg"
            path.write_text(
                core_options.render_options_file({"beetle_psx_hw_filter": "xBR"}),
                encoding="utf-8",
            )
            self.assertEqual(
                core_options.read_options_file(path), {"beetle_psx_hw_filter": "xBR"}
            )

    def test_a_missing_file_reads_as_nothing(self):
        self.assertEqual(core_options.read_options_file("/nowhere/at/all.cfg"), {})


class StoreTests(unittest.TestCase):
    def _store(self, tmp_dir):
        return CoreOptionsStore(Path(tmp_dir) / "core_options.config")

    def test_a_choice_round_trips(self):
        with TemporaryDirectory() as tmp_dir:
            store = self._store(tmp_dir)
            store.set_for_console("PS", BEETLE, "beetle_psx_hw_internal_resolution", "4x")
            self.assertEqual(
                store.get_for_console("PS", BEETLE),
                {"beetle_psx_hw_internal_resolution": "4x"},
            )

    def test_each_console_keeps_its_own(self):
        # The same core serves more than one console.
        with TemporaryDirectory() as tmp_dir:
            store = self._store(tmp_dir)
            store.set_for_console("PS", BEETLE, "beetle_psx_hw_filter", "xBR")
            self.assertEqual(store.get_for_console("PSP", PPSSPP), {})

    def test_choosing_the_default_clears_the_entry(self):
        with TemporaryDirectory() as tmp_dir:
            store = self._store(tmp_dir)
            store.set_for_console("PS", BEETLE, "beetle_psx_hw_filter", "xBR")
            store.set_for_console("PS", BEETLE, "beetle_psx_hw_filter", "nearest")
            self.assertEqual(store.get_for_console("PS", BEETLE), {})

    def test_clearing_the_last_option_drops_the_console(self):
        with TemporaryDirectory() as tmp_dir:
            store = self._store(tmp_dir)
            store.set_for_console("PS", BEETLE, "beetle_psx_hw_filter", "xBR")
            store.set_for_console("PS", BEETLE, "beetle_psx_hw_filter", None)
            self.assertEqual(store.load(), {})

    def test_a_value_the_core_rejects_never_lands(self):
        with TemporaryDirectory() as tmp_dir:
            store = self._store(tmp_dir)
            store.set_for_console("PS", BEETLE, "beetle_psx_hw_filter", "Trilinear")
            self.assertEqual(store.get_for_console("PS", BEETLE), {})

    def test_a_corrupt_store_reads_as_empty(self):
        with TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "core_options.config"
            path.write_text("{not json", encoding="utf-8")
            self.assertEqual(CoreOptionsStore(path).load(), {})

    def test_a_stale_entry_for_another_core_is_ignored(self):
        # The console's core can change under the store.
        with TemporaryDirectory() as tmp_dir:
            store = self._store(tmp_dir)
            store.set_for_console("PS", BEETLE, "beetle_psx_hw_filter", "xBR")
            self.assertEqual(store.get_for_console("PS", "swanstation_libretro.so"), {})


class HowValuesAndCoresAreNamedTests(unittest.TestCase):
    def test_a_value_with_no_friendly_name_is_shown_as_it_is(self):
        # The tables cover the shared vocabulary; a core's own value passes
        # through rather than being hidden behind a guess.
        self.assertEqual(core_options.value_label("2x"), "2x")

    def test_a_core_filename_with_no_known_suffix_keeps_its_name(self):
        self.assertEqual(core_options.core_stem("mednafen_psx_hw"), "mednafen_psx_hw")


class ReadingAnOptionsFileTests(unittest.TestCase):
    def test_a_line_that_is_not_an_assignment_is_skipped(self):
        with TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "Beetle.opt"
            path.write_text(
                "# written by RetroArch\n\nbeetle_psx_hw_filter = \"xBR\"\n",
                encoding="utf-8",
            )
            self.assertEqual(
                core_options.read_options_file(path), {"beetle_psx_hw_filter": "xBR"}
            )

    def test_a_file_that_cannot_be_read_yields_nothing(self):
        with TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "Beetle.opt"
            path.write_text("a = b\n", encoding="utf-8")
            with mock.patch.object(
                Path, "read_text", side_effect=OSError("permission denied")
            ):
                with self.assertLogs("openemux.core.core_options", level="WARNING"):
                    self.assertEqual(core_options.read_options_file(path), {})


class WhatTheStoreRefusesTests(unittest.TestCase):
    def _store(self, tmp_dir):
        return CoreOptionsStore(Path(tmp_dir) / "core_options.json")

    def test_a_file_that_is_not_an_object_is_set_aside(self):
        with TemporaryDirectory() as tmp_dir:
            store = self._store(tmp_dir)
            store.config_file.write_text("[1, 2]", encoding="utf-8")
            self.assertEqual(store.load(), {})
            self.assertEqual(
                len(list(Path(tmp_dir).glob("core_options.json.broken-*"))), 1
            )

    def test_an_option_the_core_does_not_have_is_not_stored(self):
        with TemporaryDirectory() as tmp_dir:
            store = self._store(tmp_dir)
            self.assertEqual(
                store.set_for_console("PS", BEETLE, "not_an_option", "x"), {}
            )
            self.assertFalse(store.config_file.exists())


if __name__ == "__main__":
    unittest.main()
