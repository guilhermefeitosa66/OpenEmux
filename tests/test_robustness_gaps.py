"""The small robustness gaps from the stability audit (issue #234).

Each one is a couple of lines of production code; they are grouped here the
way the issue groups them, because they share a shape -- an unguarded
filesystem call, or an over-broad match, on a path a user can reach from the
UI.
"""

import struct
import unittest
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from openemux.core import bios_manager, save_states
from openemux.core.cartridge_render import _is_composite_of
from openemux.core.gamepad_reader import NATIVE_WORD_BITS, parse_bitmap
from openemux.core.rom_actions import RomActionError, sanitize_rom_name
from openemux.core.scraper import COVER_ART, save_local_art


class _ReadOnlyConfig:
    """A config whose BIOS directory lives somewhere unwritable."""

    def __init__(self, bios_root):
        self._bios_root = Path(bios_root)

    def get_console_bios_dir(self, console):
        return self._bios_root / console / "bios"


class UnwritableBiosDirTests(unittest.TestCase):
    """A read-only library must not break the BIOS pages.

    Both call sites only *read* the directory; creating it is a convenience.
    They used to ``mkdir`` unguarded, so a library on a read-only mount raised
    ``OSError`` out of the preferences page and out of the pre-launch check.
    """

    @contextmanager
    def _read_only_library(self):
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "roms"
            root.mkdir()
            root.chmod(0o555)
            try:
                yield _ReadOnlyConfig(root)
            finally:
                # Back before the temp dir is torn down; an unwritable
                # directory cannot be removed.
                root.chmod(0o755)

    def test_the_bios_page_still_reports_a_status(self):
        with self._read_only_library() as config:
            with self.assertLogs("openemux.core.bios_manager", level="WARNING"):
                status = bios_manager.scan_console_bios_status(config, "PS")

            self.assertEqual(status["console"], "PS")
            self.assertTrue(status["has_entries"])
            # Nothing is there and nothing can be written there, so every
            # required file reads as missing -- the honest answer.
            self.assertTrue(all(not entry["present"] for entry in status["required"]))
            self.assertFalse(status["bios_dir"].exists())

    def test_the_pre_launch_check_still_answers(self):
        with self._read_only_library() as config:
            with self.assertLogs("openemux.core.bios_manager", level="WARNING"):
                missing = bios_manager.find_missing_required_for_core(
                    config, "PS", "pcsx_rearmed_libretro.so"
                )

            self.assertIsInstance(missing, list)


class UnreadableStatesDirTests(unittest.TestCase):
    """An unreadable subdirectory must not raise out of the states menu."""

    def _states_dir(self, tmp_dir):
        directory = Path(tmp_dir) / "SFC"
        directory.mkdir(parents=True)
        (directory / "Super Metroid.state1").write_bytes(b"state")
        locked = directory / "Snes9x"
        locked.mkdir()
        locked.chmod(0o000)
        return directory, locked

    @contextmanager
    def _library(self):
        with TemporaryDirectory() as tmp_dir:
            directory, locked = self._states_dir(tmp_dir)
            try:
                yield directory
            finally:
                locked.chmod(0o755)

    def test_list_states_skips_what_it_cannot_read(self):
        with self._library() as directory:
            states = save_states.list_states(directory, "Super Metroid.sfc")

            self.assertEqual([state.slot for state in states], [1])

    def test_rename_states_skips_what_it_cannot_read(self):
        with self._library() as directory:
            moved = save_states.rename_states(directory, "Super Metroid", "Metroid")

            self.assertEqual(moved, 1)

    def test_a_directory_removed_mid_scan_is_not_an_error(self):
        with TemporaryDirectory() as tmp_dir:
            directory = Path(tmp_dir) / "SFC"
            directory.mkdir(parents=True)
            (directory / "Super Metroid.state1").write_bytes(b"state")
            ghost = directory / "Snes9x"
            ghost.mkdir()

            real_iterdir = Path.iterdir

            def _vanishing(self):
                if self.name == "Snes9x":
                    raise FileNotFoundError(2, "No such file or directory")
                return real_iterdir(self)

            with patch.object(Path, "iterdir", _vanishing):
                states = save_states.list_states(directory, "Super Metroid.sfc")

        self.assertEqual([state.slot for state in states], [1])


class CompositeCacheMatchTests(unittest.TestCase):
    """The cache drop matched the ROM name as a bare prefix (issue #234).

    Cache files are ``<rom name>.<12-hex key>.png``, so a ROM called "Dr"
    matched -- and deleted -- "Dr. Mario.<key>.png".
    """

    KEY = "0123456789ab"

    def test_its_own_composite_matches(self):
        self.assertTrue(_is_composite_of(Path(f"Dr.{self.KEY}.png"), "Dr"))

    def test_another_roms_composite_does_not(self):
        self.assertFalse(
            _is_composite_of(Path(f"Dr. Mario.{self.KEY}.png"), "Dr")
        )

    def test_a_key_of_the_wrong_shape_does_not_match(self):
        for name in (
            "Dr.abc123.png",            # too short
            f"Dr.{self.KEY}0.png",      # too long
            "Dr.0123456789zz.png",      # not hex
            f"Dr.{self.KEY}.jpg",       # not a composite
            f"Dr.{self.KEY}.png.tmp",   # a render in flight
        ):
            with self.subTest(name=name):
                self.assertFalse(_is_composite_of(Path(name), "Dr"))

    def test_the_blank_composite_is_recognised(self):
        self.assertTrue(_is_composite_of(Path(f"_blank.{self.KEY}.png"), "_blank"))


class RomNameValidationTests(unittest.TestCase):
    """Playlists are newline-delimited path lists (issue #234).

    A name carrying an embedded newline serialized as two broken lines, and
    the game silently disappeared from the library.
    """

    def test_a_newline_is_rejected(self):
        with self.assertRaises(RomActionError):
            sanitize_rom_name("Super Mario\nWorld")

    def test_a_carriage_return_is_rejected(self):
        with self.assertRaises(RomActionError):
            sanitize_rom_name("Super Mario\rWorld")

    def test_every_control_character_is_rejected(self):
        for code in list(range(1, 32)) + [127]:
            with self.subTest(code=code):
                with self.assertRaises(RomActionError):
                    sanitize_rom_name(f"Mario{chr(code)}World")

    def test_a_nul_is_still_rejected(self):
        with self.assertRaises(RomActionError):
            sanitize_rom_name("Mario\0World")

    def test_an_ordinary_name_still_passes(self):
        self.assertEqual(
            sanitize_rom_name("  Pokémon - Red Version (USA) [!]  "),
            "Pokémon - Red Version (USA) [!]",
        )


class SaveLocalArtOrderTests(unittest.TestCase):
    """Copy first, clean up after (issue #234).

    Removing the old art before the copy meant a copy that failed left the ROM
    with no art at all, having had a good cover a moment earlier.
    """

    def _library(self, tmp_dir):
        roms = Path(tmp_dir) / "roms"
        art_dir = roms / "SFC" / COVER_ART
        art_dir.mkdir(parents=True)
        existing = art_dir / "Super Metroid.png"
        existing.write_bytes(b"the-old-cover")
        return roms, existing

    def test_a_failed_copy_leaves_the_previous_cover_in_place(self):
        with TemporaryDirectory() as tmp_dir:
            roms, existing = self._library(tmp_dir)
            source = Path(tmp_dir) / "new.jpg"
            source.write_bytes(b"the-new-cover")

            with patch(
                "openemux.core.scraper.shutil.copy2",
                side_effect=OSError(28, "No space left on device"),
            ):
                with self.assertRaises(OSError):
                    save_local_art(roms, "SFC", "Super Metroid", source)

            self.assertTrue(existing.exists())
            self.assertEqual(existing.read_bytes(), b"the-old-cover")

    def test_a_successful_copy_still_clears_the_other_extension(self):
        with TemporaryDirectory() as tmp_dir:
            roms, existing = self._library(tmp_dir)
            source = Path(tmp_dir) / "new.jpg"
            source.write_bytes(b"the-new-cover")

            target = save_local_art(roms, "SFC", "Super Metroid", source)

            self.assertFalse(existing.exists())
            self.assertEqual(target.name, "Super Metroid.jpg")
            self.assertEqual(target.read_bytes(), b"the-new-cover")

    def test_replacing_art_with_the_same_extension_keeps_the_new_file(self):
        with TemporaryDirectory() as tmp_dir:
            roms, existing = self._library(tmp_dir)
            source = Path(tmp_dir) / "new.png"
            source.write_bytes(b"the-new-cover")

            target = save_local_art(roms, "SFC", "Super Metroid", source)

            # Same path as the old one: the cleanup must not delete what the
            # copy just wrote there.
            self.assertEqual(target, existing)
            self.assertTrue(target.exists())
            self.assertEqual(target.read_bytes(), b"the-new-cover")


class BitmapWordSizeTests(unittest.TestCase):
    """The kernel prints ``%lx``, so the default is this machine's long.

    The default was a hardcoded 64 and the heuristic only ever corrects
    *upwards*, so on a 32-bit kernel every bit past the first word landed in
    the wrong place and captured bindings did not match RetroArch's numbering.
    """

    def test_the_default_is_the_native_word(self):
        self.assertEqual(NATIVE_WORD_BITS, struct.calcsize("l") * 8)

    def test_a_32_bit_bitmap_is_read_with_32_bit_words(self):
        # Two words of 8 hex digits: bit 0 of the high word is bit 32.
        self.assertEqual(parse_bitmap("1 0", word_bits=32), {32})
        self.assertEqual(parse_bitmap("1 0", word_bits=64), {64})

    def test_a_wide_word_still_forces_64(self):
        # Nine hex digits cannot come from a 32-bit kernel, whatever we guess.
        self.assertEqual(parse_bitmap("100000000", word_bits=32), {32})

    def test_the_low_word_is_unaffected_either_way(self):
        self.assertEqual(parse_bitmap("9", word_bits=32), {0, 3})
        self.assertEqual(parse_bitmap("9", word_bits=64), {0, 3})


class EnsureRomDirectoriesTests(unittest.TestCase):
    """An unwritable ROMs folder is reported, not raised (issue #234).

    ``ui/window.py`` calls this from the "change ROMs folder" handler, where
    the exception escaped into the GTK main loop and took the rest of the
    handler with it.
    """

    def _config(self, tmp_dir, roms_path):
        from openemux.core.config import ConfigManager

        with patch.object(ConfigManager, "load_config", lambda self: {}), \
             patch.object(ConfigManager, "save_config", lambda self: None):
            config = ConfigManager()
        config.config = {"roms_path": str(roms_path)}
        config.save_config = lambda: None
        return config

    def test_a_read_only_parent_is_reported_rather_than_raised(self):
        with TemporaryDirectory() as tmp_dir:
            parent = Path(tmp_dir) / "mount"
            parent.mkdir()
            parent.chmod(0o555)
            try:
                config = self._config(tmp_dir, parent / "roms")
                with self.assertLogs("openemux.core.config", level="WARNING"):
                    failed = config.ensure_rom_directories()
            finally:
                parent.chmod(0o755)

            self.assertTrue(failed)

    def test_a_writable_path_reports_nothing_and_lays_out_the_library(self):
        with TemporaryDirectory() as tmp_dir:
            roms = Path(tmp_dir) / "roms"
            config = self._config(tmp_dir, roms)

            failed = config.ensure_rom_directories()

            self.assertEqual(failed, [])
            self.assertTrue((roms / "SFC").is_dir())
            self.assertTrue((roms / "SFC" / "covers").is_dir())
            self.assertTrue((roms / "SFC" / "bios").is_dir())

    def test_the_console_directories_are_created_once_not_twice(self):
        """The loop ran before *and* after the migration; once is enough."""
        with TemporaryDirectory() as tmp_dir:
            config = self._config(tmp_dir, Path(tmp_dir) / "roms")
            made = []
            real_mkdir = Path.mkdir

            def _counting(self, *args, **kwargs):
                made.append(self)
                return real_mkdir(self, *args, **kwargs)

            with patch.object(Path, "mkdir", _counting):
                config.ensure_rom_directories()

            console_dirs = [p for p in made if p.name == "SFC"]
            self.assertEqual(len(console_dirs), 1, console_dirs)


if __name__ == "__main__":
    unittest.main()
