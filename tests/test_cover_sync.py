import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from opemux.core.cover_sync import (
    _build_cover_url,
    _candidate_names,
    _normalize_rom_name,
    _sync_covers,
)


class CoverSyncTests(unittest.TestCase):
    def test_cover_name_normalization_basic(self):
        self.assertEqual(
            _normalize_rom_name("Chrono Trigger (Rev 1) [!].sfc"),
            "Chrono Trigger",
        )

    def test_cover_candidate_generation_order(self):
        candidates = _candidate_names(
            rom_name="Chrono Trigger",
            matching_mode="normalized_region_priority",
            region_priority=["USA", "World", "Europe", "Japan"],
            name_cleanup=True,
        )
        self.assertEqual(candidates[0], "Chrono Trigger")
        self.assertEqual(candidates[1], "Chrono Trigger (USA)")
        self.assertEqual(candidates[2], "Chrono Trigger (World)")
        self.assertEqual(candidates[3], "Chrono Trigger (Europe)")
        self.assertEqual(candidates[4], "Chrono Trigger (Japan)")
        self.assertEqual(candidates[5], "Chrono Trigger (En,Fr,De,Es,It)")

    def test_cover_url_build_uses_thumbnails_libretro_domain(self):
        url = _build_cover_url(
            "Nintendo - Super Nintendo Entertainment System",
            "Chrono Trigger (USA)",
        )
        self.assertEqual(
            url,
            "https://thumbnails.libretro.com/"
            "Nintendo%20-%20Super%20Nintendo%20Entertainment%20System/"
            "Named_Boxarts/Chrono%20Trigger%20%28USA%29.png",
        )

    def test_cover_sync_stops_on_first_success(self):
        library = {"snes": [{"name": "Chrono Trigger", "path": "/tmp/Chrono Trigger.sfc", "console": "snes"}]}
        with TemporaryDirectory() as tmp_dir:
            with (
                patch("opemux.core.cover_sync.find_local_cover", return_value=None),
                patch(
                    "opemux.core.cover_sync._remote_cover_candidates",
                    return_value=["u1", "u2", "u3"],
                ),
                patch(
                    "opemux.core.cover_sync._download_cover",
                    side_effect=[False, False, True],
                ) as download_mock,
            ):
                summary = _sync_covers(
                    library_by_console=library,
                    covers_dir=tmp_dir,
                    scope="console",
                    selected_console="snes",
                    sync_settings={},
                )
        self.assertEqual(summary["downloaded"], 1)
        self.assertEqual(summary["errors"], 0)
        self.assertEqual(download_mock.call_count, 3)

    def test_cover_sync_existing_local_is_skipped(self):
        library = {"gba": [{"name": "Castlevania", "path": "/tmp/Castlevania.gba", "console": "gba"}]}
        with TemporaryDirectory() as tmp_dir:
            with (
                patch("opemux.core.cover_sync.find_local_cover", return_value=Path(tmp_dir) / "cover.png"),
                patch("opemux.core.cover_sync._download_cover") as download_mock,
            ):
                summary = _sync_covers(
                    library_by_console=library,
                    covers_dir=tmp_dir,
                    scope="console",
                    selected_console="gba",
                    sync_settings={},
                )
        self.assertEqual(summary["skipped"], 1)
        self.assertEqual(summary["downloaded"], 0)
        self.assertEqual(download_mock.call_count, 0)

    def test_cover_sync_reports_progress(self):
        library = {
            "PS": [
                {"name": "Game A", "path": "/tmp/Game A.cue", "console": "PS"},
                {"name": "Game B", "path": "/tmp/Game B.cue", "console": "PS"},
            ]
        }
        events = []
        with TemporaryDirectory() as tmp_dir:
            with (
                patch("opemux.core.cover_sync.find_local_cover", return_value=None),
                patch("opemux.core.cover_sync._remote_cover_candidates", return_value=["u1"]),
                patch("opemux.core.cover_sync._download_cover", side_effect=[True, False]),
            ):
                _sync_covers(
                    library_by_console=library,
                    covers_dir=tmp_dir,
                    scope="console",
                    selected_console="PS",
                    sync_settings={},
                    on_progress=events.append,
                )
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["processed"], 1)
        self.assertEqual(events[0]["total"], 2)
        self.assertEqual(events[1]["processed"], 2)
        self.assertEqual(events[1]["total"], 2)


if __name__ == "__main__":
    unittest.main()
