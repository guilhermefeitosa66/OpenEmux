import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

from openemux.core.playlist_manager import PlaylistManager
from openemux.core.scanner import RomScanner


class _DummyConfig:
    def __init__(self, playlists_dir, roms_path=None):
        self._playlists_dir = Path(playlists_dir)
        self._roms_path = Path(roms_path) if roms_path else Path(playlists_dir).parent / "roms"

    def get_playlists_dir(self):
        return self._playlists_dir

    def get_roms_path(self):
        return self._roms_path


class PlaylistManagerTests(unittest.TestCase):
    def test_scan_and_rebuild_all_playlists_rewrites_empty_and_non_empty(self):
        with TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            roms_dir = base / "roms"
            (roms_dir / "FC").mkdir(parents=True, exist_ok=True)
            (roms_dir / "FC" / "Mario.nes").write_bytes(b"rom-data")
            (roms_dir / "SFC").mkdir(parents=True, exist_ok=True)

            playlists_dir = base / "playlists"
            scanner = RomScanner(roms_dir)
            manager = PlaylistManager(_DummyConfig(playlists_dir), scanner)

            summary = manager.scan_and_rebuild_all_playlists(consoles=["FC", "SFC"])

            self.assertEqual(summary["total_consoles"], 2)
            self.assertEqual(summary["total_roms"], 1)
            self.assertEqual(summary["consoles"]["FC"], 1)
            self.assertEqual(summary["consoles"]["SFC"], 0)

            fc_playlist = playlists_dir / "FC.list"
            sfc_playlist = playlists_dir / "SFC.list"
            self.assertTrue(fc_playlist.exists())
            self.assertTrue(sfc_playlist.exists())
            self.assertIn("Mario.nes", fc_playlist.read_text(encoding="utf-8"))
            self.assertEqual(sfc_playlist.read_text(encoding="utf-8"), "")

    def test_scan_and_rebuild_all_playlists_reports_progress(self):
        with TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            roms_dir = base / "roms"
            (roms_dir / "FC").mkdir(parents=True, exist_ok=True)
            (roms_dir / "FC" / "Mario.nes").write_bytes(b"rom-data")
            (roms_dir / "SFC").mkdir(parents=True, exist_ok=True)
            (roms_dir / "SFC" / "Chrono.sfc").write_bytes(b"rom-data")

            manager = PlaylistManager(_DummyConfig(base / "playlists"), RomScanner(roms_dir))
            events = []

            summary = manager.scan_and_rebuild_all_playlists(consoles=["FC", "SFC"], on_progress=events.append)

        self.assertEqual(summary["total_roms"], 2)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["console"], "FC")
        self.assertEqual(events[0]["current"], 1)
        self.assertEqual(events[0]["total"], 2)
        self.assertEqual(events[1]["console"], "SFC")

    def test_scan_and_rebuild_playlist_ps_uses_cue_entry_only(self):
        with TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            roms_dir = base / "roms"
            ps_dir = roms_dir / "PS"
            ps_dir.mkdir(parents=True, exist_ok=True)
            (ps_dir / "Ridge Racer.cue").write_text(
                'FILE "Ridge Racer (Track 1).bin" BINARY\n',
                encoding="utf-8",
            )
            (ps_dir / "Ridge Racer (Track 1).bin").write_bytes(b"track")

            playlists_dir = base / "playlists"
            manager = PlaylistManager(_DummyConfig(playlists_dir), RomScanner(roms_dir))
            roms = manager.scan_and_rebuild_playlist("PS")
            playlist_path = playlists_dir / "PS.list"
            self.assertEqual(len(roms), 1)
            self.assertTrue(playlist_path.exists())
            content = playlist_path.read_text(encoding="utf-8")
            self.assertIn("Ridge Racer.cue", content)
            self.assertNotIn("Ridge Racer (Track 1).bin", content)

    def test_toggle_favorite_adds_and_removes(self):
        with TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            roms_dir = base / "roms"
            (roms_dir / "GBA").mkdir(parents=True, exist_ok=True)
            rom_path = roms_dir / "GBA" / "Golden Sun.gba"
            rom_path.write_bytes(b"rom-data")
            manager = PlaylistManager(_DummyConfig(base / "playlists", roms_path=roms_dir), RomScanner(roms_dir))
            rom = {"name": "Golden Sun", "path": str(rom_path), "console": "GBA"}

            added = manager.toggle_favorite(rom)
            self.assertTrue(added)
            self.assertTrue(manager.is_favorite(str(rom_path)))
            self.assertEqual(len(manager.load_favorites_playlist()), 1)

            removed = manager.toggle_favorite(rom)
            self.assertFalse(removed)
            self.assertFalse(manager.is_favorite(str(rom_path)))
            self.assertEqual(manager.load_favorites_playlist(), [])

    def test_load_favorites_ignores_missing_or_invalid_entries(self):
        with TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            roms_dir = base / "roms"
            (roms_dir / "PS").mkdir(parents=True, exist_ok=True)
            valid = roms_dir / "PS" / "Game.cue"
            valid.write_bytes(b"cue")
            invalid_ext = roms_dir / "PS" / "Readme.txt"
            invalid_ext.write_text("x", encoding="utf-8")

            manager = PlaylistManager(_DummyConfig(base / "playlists", roms_path=roms_dir), RomScanner(roms_dir))
            favorites_path = manager.get_favorites_playlist_path()
            favorites_path.parent.mkdir(parents=True, exist_ok=True)
            favorites_path.write_text(
                f"{valid}\n{invalid_ext}\n{base / 'missing.gba'}\n",
                encoding="utf-8",
            )

            loaded = manager.load_favorites_playlist()

        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["path"], str(valid))


if __name__ == "__main__":
    unittest.main()


class ZippedRomPlaylistTests(unittest.TestCase):
    """Regression: a zipped ROM was indexed but dropped when the playlist was read.

    scan_and_rebuild_playlist wrote the archive path correctly, then load_playlist
    re-filtered every line by the console's extensions -- and ".zip" is not one of
    them -- so the game never reached the library. See issue reported after 1.2.0.
    """

    def _build(self, tmp_dir):
        base = Path(tmp_dir)
        roms_dir = base / "roms"
        playlists_dir = base / "playlists"
        playlists_dir.mkdir(parents=True, exist_ok=True)
        manager = PlaylistManager(_DummyConfig(playlists_dir, roms_dir), RomScanner(roms_dir))
        return roms_dir, manager

    def test_zipped_rom_is_listed_with_its_inner_name(self):
        with TemporaryDirectory() as tmp_dir:
            roms_dir, manager = self._build(tmp_dir)
            (roms_dir / "SFC").mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(roms_dir / "SFC" / "Aladdin.zip", "w") as archive:
                archive.writestr("Aladdin (USA).sfc", b"rom-data")

            manager.scan_and_rebuild_playlist("SFC")
            entries = manager.load_playlist("SFC")

            self.assertEqual(len(entries), 1)
            # Inner name, not the archive stem -- this is what cover lookups match.
            self.assertEqual(entries[0]["name"], "Aladdin (USA)")
            self.assertTrue(entries[0]["path"].endswith("Aladdin.zip"))

    def test_zip_without_a_matching_rom_is_not_listed(self):
        with TemporaryDirectory() as tmp_dir:
            roms_dir, manager = self._build(tmp_dir)
            (roms_dir / "SFC").mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(roms_dir / "SFC" / "Docs.zip", "w") as archive:
                archive.writestr("readme.txt", b"nothing playable here")

            manager.scan_and_rebuild_playlist("SFC")
            self.assertEqual(manager.load_playlist("SFC"), [])

    def test_zipped_rom_can_be_favorited(self):
        with TemporaryDirectory() as tmp_dir:
            roms_dir, manager = self._build(tmp_dir)
            (roms_dir / "SFC").mkdir(parents=True, exist_ok=True)
            archive_path = roms_dir / "SFC" / "Aladdin.zip"
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("Aladdin (USA).sfc", b"rom-data")

            manager.toggle_favorite({"path": str(archive_path)})
            favorites = manager.load_favorites_playlist()

            self.assertEqual([entry["name"] for entry in favorites], ["Aladdin (USA)"])

    def test_stale_archive_for_a_fullpath_core_is_not_listed(self):
        # PS cores need a real file; the importer extracts these, so an archive
        # left in the folder by hand is not playable and must not be offered.
        with TemporaryDirectory() as tmp_dir:
            roms_dir, manager = self._build(tmp_dir)
            (roms_dir / "PS").mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(roms_dir / "PS" / "Disc.zip", "w") as archive:
                archive.writestr("Disc.cue", b'FILE "Disc.bin" BINARY\n')

            manager.scan_and_rebuild_playlist("PS")
            self.assertEqual(manager.load_playlist("PS"), [])

    def test_forget_rom_drops_it_from_playlist_and_favorites(self):
        with TemporaryDirectory() as tmp_dir:
            roms_dir, manager = self._build(tmp_dir)
            (roms_dir / "GB").mkdir(parents=True, exist_ok=True)
            kept = roms_dir / "GB" / "Kirby.gb"
            gone = roms_dir / "GB" / "Pokemon.gb"
            for path in (kept, gone):
                path.write_bytes(b"rom")
            manager.scan_and_rebuild_playlist("GB")
            manager.toggle_favorite({"path": str(gone), "console": "GB", "name": "Pokemon"})

            gone.unlink()
            manager.forget_rom("GB", gone)

            self.assertEqual([rom["name"] for rom in manager.load_playlist("GB")], ["Kirby"])
            self.assertEqual(manager.list_favorite_paths(), set())

    def test_repath_rom_follows_a_rename_in_playlist_and_favorites(self):
        with TemporaryDirectory() as tmp_dir:
            roms_dir, manager = self._build(tmp_dir)
            (roms_dir / "GB").mkdir(parents=True, exist_ok=True)
            old = roms_dir / "GB" / "Kirby.gb"
            old.write_bytes(b"rom")
            manager.scan_and_rebuild_playlist("GB")
            manager.toggle_favorite({"path": str(old), "console": "GB", "name": "Kirby"})

            new = roms_dir / "GB" / "Kirby's Dream Land 2.gb"
            old.rename(new)
            manager.repath_rom("GB", old, new)

            self.assertEqual(
                [rom["name"] for rom in manager.load_playlist("GB")], ["Kirby's Dream Land 2"]
            )
            self.assertEqual(manager.list_favorite_paths(), {str(new)})
