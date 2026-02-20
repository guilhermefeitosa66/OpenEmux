import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from opemux.core.playlist_manager import PlaylistManager
from opemux.core.scanner import RomScanner


class _DummyConfig:
    def __init__(self, playlists_dir):
        self._playlists_dir = Path(playlists_dir)

    def get_playlists_dir(self):
        return self._playlists_dir


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


if __name__ == "__main__":
    unittest.main()
