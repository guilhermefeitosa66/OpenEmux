"""A ROM whose filename is not valid UTF-8 must not take the app with it.

Old dumps routinely carry cp437 or Shift-JIS names. Python hands those back
decoded with ``surrogateescape`` ('bad\\udcffname.nes'), and a strict UTF-8
write of that raises mid-file -- which used to kill the scan worker and leave
scanning disabled for the rest of the session (issue #214).
"""

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from openemux.core.collections import CollectionManager
from openemux.core.paths import display_text
from openemux.core.playlist_manager import PlaylistManager
from openemux.core.scanner import RomScanner

#: A byte no UTF-8 decoder accepts, which is exactly the point.
BAD_BYTE = b"\xff"


def _write_bad_name(directory, prefix=b"Contra ", suffix=b".nes"):
    """Create a file whose name is not valid UTF-8; return its decoded path."""
    raw = os.fsencode(str(directory)) + b"/" + prefix + BAD_BYTE + suffix
    with open(raw, "wb") as handle:
        handle.write(b"rom")
    return os.fsdecode(raw)


class _Config:
    def __init__(self, playlists_dir, roms_path):
        self._playlists_dir = Path(playlists_dir)
        self._roms_path = Path(roms_path)

    def get_playlists_dir(self):
        return self._playlists_dir

    def get_roms_path(self):
        return self._roms_path


class ScanningSurvivesTests(unittest.TestCase):
    def _manager(self, base):
        roms = base / "roms"
        (roms / "FC").mkdir(parents=True, exist_ok=True)
        return PlaylistManager(_Config(base / "playlists", roms), RomScanner(roms)), roms

    def test_a_non_utf8_rom_name_is_scanned_and_written(self):
        with TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            manager, roms = self._manager(base)
            bad_path = _write_bad_name(roms / "FC")
            (roms / "FC" / "Mario.nes").write_bytes(b"rom")

            found = manager.scan_and_rebuild_playlist("FC")

            self.assertEqual(len(found), 2)
            playlist = base / "playlists" / "FC.list"
            self.assertTrue(playlist.exists())
            lines = playlist.read_text(
                encoding="utf-8", errors="surrogateescape"
            ).splitlines()
            self.assertIn(bad_path, lines)

    def test_the_written_name_round_trips_back_to_the_real_file(self):
        # The point of surrogateescape: the line reloads as a path that opens.
        with TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            manager, roms = self._manager(base)
            bad_path = _write_bad_name(roms / "FC")

            manager.scan_and_rebuild_playlist("FC")
            entries = manager.load_playlist("FC")

            self.assertEqual([entry["path"] for entry in entries], [bad_path])
            self.assertEqual(Path(entries[0]["path"]).read_bytes(), b"rom")

    def test_one_bad_console_does_not_abort_the_whole_rescan(self):
        with TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            manager, roms = self._manager(base)
            (roms / "SFC").mkdir(parents=True, exist_ok=True)
            (roms / "SFC" / "Chrono.sfc").write_bytes(b"rom")

            original = manager.scan_and_rebuild_playlist

            def _explode_on_fc(console):
                if console == "FC":
                    raise OSError("Input/output error")
                return original(console)

            manager.scan_and_rebuild_playlist = _explode_on_fc
            summary = manager.scan_and_rebuild_all_playlists(consoles=["FC", "SFC"])

            self.assertEqual(summary["failed"], {"FC": "Input/output error"})
            self.assertEqual(summary["consoles"]["SFC"], 1)
            self.assertEqual(summary["total_roms"], 1)

    def test_a_clean_rescan_reports_nothing_failed(self):
        with TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            manager, roms = self._manager(base)
            (roms / "FC" / "Mario.nes").write_bytes(b"rom")

            summary = manager.scan_and_rebuild_all_playlists(consoles=["FC"])

            self.assertEqual(summary["failed"], {})


class FavoritesAndCollectionsTests(unittest.TestCase):
    def _manager(self, base):
        roms = base / "roms"
        (roms / "FC").mkdir(parents=True, exist_ok=True)
        return PlaylistManager(_Config(base / "playlists", roms), RomScanner(roms)), roms

    def test_a_non_utf8_rom_can_be_favorited(self):
        with TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            manager, roms = self._manager(base)
            bad_path = _write_bad_name(roms / "FC")

            self.assertTrue(manager.toggle_favorite({"path": bad_path}))
            self.assertIn(bad_path, manager.list_favorite_paths())
            self.assertTrue(manager.is_favorite(bad_path))

    def test_a_non_utf8_rom_can_go_into_a_collection(self):
        with TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir)
            roms = base / "roms" / "FC"
            roms.mkdir(parents=True)
            bad_path = _write_bad_name(roms)
            collections = CollectionManager(base / "collections")
            collections.create("Hard games")

            collections.add("hard-games", [bad_path])

            self.assertEqual(collections.paths("hard-games"), [bad_path])


class DisplayTextTests(unittest.TestCase):
    """What reaches GTK has to be text GTK can take (issue #214)."""

    def test_a_surrogate_becomes_an_escape(self):
        self.assertEqual(display_text("Contra \udcff (Japan)"), "Contra \\udcff (Japan)")

    def test_the_result_is_always_encodable(self):
        # The actual requirement: PyGObject encodes to UTF-8 on the way into
        # GTK, and a lone surrogate raises there and takes the render with it.
        for value in ("Contra \udcff", "\udcfe\udcff", "Chrono Trigger", "Pokémon"):
            display_text(value).encode("utf-8")  # must not raise

    def test_ordinary_names_are_untouched(self):
        for value in ("Chrono Trigger", "Pokémon Rojo", "ドラクエ", ""):
            self.assertEqual(display_text(value), value)

    def test_a_real_filename_survives_the_round_trip_to_the_screen(self):
        with TemporaryDirectory() as tmp_dir:
            bad_path = _write_bad_name(Path(tmp_dir))
            shown = display_text(Path(bad_path).stem)

            shown.encode("utf-8")  # renderable
            # ...and the path it came from still opens.
            self.assertEqual(Path(bad_path).read_bytes(), b"rom")


if __name__ == "__main__":
    unittest.main()
