import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

from openemux.core.archives import archive_rom_name, rename_archive_rom_entry
from openemux.core.rom_actions import (
    RomActionError,
    delete_rom,
    rename_rom,
    sanitize_rom_name,
)
from openemux.core.scraper import find_local_art, COVER_ART, LABEL_ART


def _rom(roms_dir, console="GB", name="Kirby", suffix=".gb"):
    path = Path(roms_dir) / console / f"{name}{suffix}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"rom")
    return {"name": name, "path": str(path), "console": console}


def _art(roms_dir, console, name, kind=COVER_ART, ext="png"):
    path = Path(roms_dir) / console / kind / f"{name}.{ext}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"art")
    return path


class SanitizeTests(unittest.TestCase):
    def test_rejects_empty_and_path_escapes(self):
        for value in ("", "   ", "..", "a/b", "a\\b"):
            with self.assertRaises(RomActionError):
                sanitize_rom_name(value)

    def test_trims_surrounding_space(self):
        self.assertEqual(sanitize_rom_name("  Super Mario Land "), "Super Mario Land")


class DeleteRomTests(unittest.TestCase):
    def test_trashes_the_file_and_drops_the_composite(self):
        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            rom = _rom(base / "roms")
            cache = base / "cache" / "GB"
            cache.mkdir(parents=True)
            (cache / "Kirby.abc123.png").write_bytes(b"png")
            (cache / "Other.abc123.png").write_bytes(b"png")

            trashed = []

            def fake_trash(path):
                trashed.append(Path(path))
                Path(path).unlink()
                return True

            self.assertTrue(
                delete_rom(base / "roms", rom, trash=fake_trash, cache_dir=base / "cache")
            )

            self.assertEqual(trashed, [Path(rom["path"])])
            self.assertFalse((cache / "Kirby.abc123.png").exists())
            self.assertTrue((cache / "Other.abc123.png").exists())

    def test_reports_when_the_trash_refuses(self):
        with TemporaryDirectory() as tmp:
            rom = _rom(Path(tmp))
            with self.assertRaises(RomActionError):
                delete_rom(Path(tmp), rom, trash=lambda path: False)
            self.assertTrue(Path(rom["path"]).exists())

    def test_missing_file_is_an_error_not_a_silent_success(self):
        with TemporaryDirectory() as tmp:
            rom = _rom(Path(tmp))
            Path(rom["path"]).unlink()
            with self.assertRaises(RomActionError):
                delete_rom(Path(tmp), rom, trash=lambda path: True)


class RenameRomTests(unittest.TestCase):
    def test_renames_file_keeping_extension_and_carries_art_over(self):
        with TemporaryDirectory() as tmp:
            roms_dir = Path(tmp) / "roms"
            rom = _rom(roms_dir, name="Kirby", suffix=".gb")
            _art(roms_dir, "GB", "Kirby", COVER_ART, "png")
            _art(roms_dir, "GB", "Kirby", LABEL_ART, "jpg")

            renamed = rename_rom(roms_dir, rom, "Kirby's Dream Land 2")

            self.assertEqual(renamed["name"], "Kirby's Dream Land 2")
            self.assertTrue(Path(renamed["path"]).exists())
            self.assertTrue(Path(renamed["path"]).name.endswith(".gb"))
            self.assertFalse(Path(rom["path"]).exists())
            self.assertIsNotNone(find_local_art(roms_dir, "GB", "Kirby's Dream Land 2", COVER_ART))
            self.assertIsNotNone(find_local_art(roms_dir, "GB", "Kirby's Dream Land 2", LABEL_ART))
            self.assertIsNone(find_local_art(roms_dir, "GB", "Kirby", COVER_ART))

    def test_refuses_to_overwrite_an_existing_rom(self):
        with TemporaryDirectory() as tmp:
            roms_dir = Path(tmp) / "roms"
            rom = _rom(roms_dir, name="Kirby")
            _rom(roms_dir, name="Pokemon")
            with self.assertRaises(RomActionError):
                rename_rom(roms_dir, rom, "Pokemon")
            self.assertTrue(Path(rom["path"]).exists())

    def test_archive_entry_is_renamed_so_the_card_follows(self):
        with TemporaryDirectory() as tmp:
            roms_dir = Path(tmp) / "roms"
            archive = roms_dir / "GB" / "Kirby.zip"
            archive.parent.mkdir(parents=True)
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("Kirby.gb", b"rom data")
                zf.writestr("readme.txt", b"notes")
            rom = {"name": "Kirby", "path": str(archive), "console": "GB"}

            renamed = rename_rom(roms_dir, rom, "Kirby 2")

            self.assertTrue(Path(renamed["path"]).name == "Kirby 2.zip")
            self.assertEqual(archive_rom_name(renamed["path"], (".gb",)), "Kirby 2")
            with zipfile.ZipFile(renamed["path"]) as zf:
                self.assertEqual(sorted(zf.namelist()), ["Kirby 2.gb", "readme.txt"])
                self.assertEqual(zf.read("Kirby 2.gb"), b"rom data")

    def test_states_follow_the_rename(self):
        # #134 cause 1: states are keyed on the file stem; slot files, the
        # auto state and thumbnails in the console dir and the per-core
        # subdirectory all move.
        with TemporaryDirectory() as tmp:
            roms_dir = Path(tmp) / "roms"
            states_dir = Path(tmp) / "states" / "GB"
            rom = _rom(roms_dir, name="Kirby", suffix=".gb")
            core_dir = states_dir / "Gambatte"
            core_dir.mkdir(parents=True)
            (states_dir / "Kirby.state").write_bytes(b"s0")
            (states_dir / "Kirby.state1").write_bytes(b"s1")
            (states_dir / "Kirby.state1.png").write_bytes(b"thumb")
            (states_dir / "Kirby.state.auto").write_bytes(b"auto")
            (core_dir / "Kirby.state2").write_bytes(b"s2")
            # A different game sharing the prefix must not be dragged along.
            (states_dir / "Kirby 2.state").write_bytes(b"other")

            rename_rom(roms_dir, rom, "Kirby DX", states_dir=states_dir)

            self.assertTrue((states_dir / "Kirby DX.state").exists())
            self.assertTrue((states_dir / "Kirby DX.state1").exists())
            self.assertTrue((states_dir / "Kirby DX.state1.png").exists())
            self.assertTrue((states_dir / "Kirby DX.state.auto").exists())
            self.assertTrue((core_dir / "Kirby DX.state2").exists())
            self.assertTrue((states_dir / "Kirby 2.state").exists())
            self.assertFalse((states_dir / "Kirby.state").exists())

    def test_state_rename_refuses_to_overwrite(self):
        with TemporaryDirectory() as tmp:
            roms_dir = Path(tmp) / "roms"
            states_dir = Path(tmp) / "states" / "GB"
            states_dir.mkdir(parents=True)
            rom = _rom(roms_dir, name="Kirby", suffix=".gb")
            (states_dir / "Kirby.state").write_bytes(b"mine")
            (states_dir / "Kirby DX.state").write_bytes(b"theirs")

            rename_rom(roms_dir, rom, "Kirby DX", states_dir=states_dir)

            # Both survive: refuse rather than overwrite.
            self.assertEqual((states_dir / "Kirby.state").read_bytes(), b"mine")
            self.assertEqual((states_dir / "Kirby DX.state").read_bytes(), b"theirs")

    def test_battery_saves_follow_the_rename(self):
        # #134 cause 2: the .srm and core-specific companions live next to
        # the ROM under the same stem.
        with TemporaryDirectory() as tmp:
            roms_dir = Path(tmp) / "roms"
            rom = _rom(roms_dir, console="SFC", name="Chrono Trigger", suffix=".smc")
            rom_dir = Path(rom["path"]).parent
            (rom_dir / "Chrono Trigger.srm").write_bytes(b"battery")
            (rom_dir / "Chrono Trigger.data.szsnes").write_bytes(b"core data")
            # Another ROM sharing the stem is its own game and stays put...
            (rom_dir / "Chrono Trigger.sfc").write_bytes(b"other rom")
            # ...and loose artwork next to the ROM is not a save either.
            (rom_dir / "Chrono Trigger.png").write_bytes(b"shot")

            renamed = rename_rom(roms_dir, rom, "CT")

            new_dir = Path(renamed["path"]).parent
            self.assertEqual((new_dir / "CT.srm").read_bytes(), b"battery")
            self.assertEqual((new_dir / "CT.data.szsnes").read_bytes(), b"core data")
            self.assertTrue((rom_dir / "Chrono Trigger.sfc").exists())
            self.assertTrue((rom_dir / "Chrono Trigger.png").exists())
            self.assertFalse((rom_dir / "Chrono Trigger.srm").exists())

    def test_multi_rom_archive_keeps_its_artwork_and_display_name(self):
        # #134 cause 3: the card is named after the entry inside, which the
        # rename cannot touch -- so the artwork must keep that name too.
        with TemporaryDirectory() as tmp:
            roms_dir = Path(tmp) / "roms"
            archive = roms_dir / "GB" / "Pack.zip"
            archive.parent.mkdir(parents=True)
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("One.gb", b"a")
                zf.writestr("Two.gb", b"b")
            # The card shows the inner entry's name; art is keyed on it.
            _art(roms_dir, "GB", "One", COVER_ART, "png")
            rom = {"name": "One", "path": str(archive), "console": "GB"}

            renamed = rename_rom(roms_dir, rom, "Best Pack")

            self.assertTrue(Path(renamed["path"]).name == "Best Pack.zip")
            # Display name unchanged, artwork still reachable under it.
            self.assertEqual(renamed["name"], "One")
            self.assertIsNotNone(find_local_art(roms_dir, "GB", "One", COVER_ART))

    def test_multi_rom_archive_keeps_its_entries(self):
        with TemporaryDirectory() as tmp:
            roms_dir = Path(tmp) / "roms"
            archive = roms_dir / "GB" / "Pack.zip"
            archive.parent.mkdir(parents=True)
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("One.gb", b"a")
                zf.writestr("Two.gb", b"b")

            self.assertFalse(rename_archive_rom_entry(archive, "Whatever", (".gb",)))
            with zipfile.ZipFile(archive) as zf:
                self.assertEqual(sorted(zf.namelist()), ["One.gb", "Two.gb"])


if __name__ == "__main__":
    unittest.main()
