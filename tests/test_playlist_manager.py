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


if __name__ == "__main__":
    unittest.main()

