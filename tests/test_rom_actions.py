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
    return {"name": name, "path": str(path), "console": console, "rom_id": None}


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
            rom = {"name": "Kirby", "path": str(archive), "console": "GB", "rom_id": None}

            renamed = rename_rom(roms_dir, rom, "Kirby 2")

            self.assertTrue(Path(renamed["path"]).name == "Kirby 2.zip")
            self.assertEqual(archive_rom_name(renamed["path"], (".gb",)), "Kirby 2")
            with zipfile.ZipFile(renamed["path"]) as zf:
                self.assertEqual(sorted(zf.namelist()), ["Kirby 2.gb", "readme.txt"])
                self.assertEqual(zf.read("Kirby 2.gb"), b"rom data")

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
