import re
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock
from unittest.mock import patch

from openemux.core import cover_sync
from openemux.core.cover_sync import (
    _build_cover_url,
    _candidate_names,
    _libretro_candidates,
    _normalize_rom_name,
    _ordered_providers,
    _remote_cover_candidates,
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
        # Bare name first, then the configured single regions, then the common
        # combined-region tags, then the multi-language tag.
        self.assertEqual(candidates[0], "Chrono Trigger")
        self.assertEqual(candidates[1], "Chrono Trigger (USA)")
        self.assertEqual(candidates[2], "Chrono Trigger (World)")
        self.assertEqual(candidates[3], "Chrono Trigger (Europe)")
        self.assertEqual(candidates[4], "Chrono Trigger (Japan)")
        self.assertEqual(candidates[5], "Chrono Trigger (USA, Europe)")
        self.assertIn("Chrono Trigger (En,Fr,De,Es,It)", candidates)

    def test_cover_candidates_bridge_common_naming_quirks(self):
        def bases(rom_name):
            # Strip region/lang tags to inspect the underlying name variants.
            names = _candidate_names(
                rom_name=rom_name,
                matching_mode="normalized_region_priority",
                region_priority=["USA"],
                name_cleanup=True,
            )
            return {re.sub(r"\s*\(.*\)$", "", n) for n in names}

        # Trailing sequence number dropped: "Donkey Kong 1" -> "Donkey Kong".
        self.assertIn("Donkey Kong", bases("Donkey Kong 1"))
        # Connector word lower-cased to match No-Intro casing.
        self.assertIn(
            "Castlevania - Harmony of Dissonance",
            bases("Castlevania - Harmony Of Dissonance"),
        )
        # Accents stripped: "Pokémon ..." -> "Pokemon ...".
        self.assertTrue(any(b.startswith("Pokemon") for b in bases("Pokémon 2.1 - Gold Version")))
        # Embedded ordering marker removed.
        self.assertIn("Pokemon Gold Version", bases("Pokémon 2.1 - Gold Version"))
        # Combined-region tag offered.
        combos = _candidate_names(
            rom_name="Sonic The Hedgehog",
            matching_mode="normalized_region_priority",
            region_priority=["USA"],
            name_cleanup=True,
        )
        self.assertIn("Sonic The Hedgehog (USA, Europe)", combos)

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
                patch("openemux.core.cover_sync.find_local_cover", return_value=None),
                patch(
                    "openemux.core.cover_sync._remote_cover_candidates",
                    return_value=["u1", "u2", "u3"],
                ),
                patch(
                    "openemux.core.cover_sync._download_cover",
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
                patch("openemux.core.cover_sync.find_local_cover", return_value=Path(tmp_dir) / "cover.png"),
                patch("openemux.core.cover_sync._download_cover") as download_mock,
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
                patch("openemux.core.cover_sync.find_local_cover", return_value=None),
                patch("openemux.core.cover_sync._remote_cover_candidates", return_value=["u1"]),
                patch("openemux.core.cover_sync._download_cover", side_effect=[True, False]),
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


class CoverSourceProviderTests(unittest.TestCase):
    """The libretro-only default must remain byte-for-byte what it always was."""

    def test_default_source_uses_libretro_provider_only(self):
        for settings in ({}, {"cover_source": "libretro"}):
            names = [name for name, _fn in _ordered_providers(settings)]
            self.assertEqual(names, ["libretro"], settings)

    def test_default_source_never_calls_screenscraper(self):
        with patch("openemux.core.cover_sync._screenscraper_candidates") as ss_mock:
            urls = _remote_cover_candidates("SFC", "Chrono Trigger", {})
        ss_mock.assert_not_called()
        self.assertTrue(urls)
        self.assertTrue(all(u.startswith("https://thumbnails.libretro.com/") for u in urls))

    def test_default_candidates_match_the_libretro_provider_exactly(self):
        settings = {"region_priority": ["USA", "World"], "name_cleanup": True}
        self.assertEqual(
            _remote_cover_candidates("SFC", "Chrono Trigger", settings),
            _libretro_candidates("SFC", "Chrono Trigger", settings),
        )

    def test_libretro_then_screenscraper_appends_screenscraper_candidates(self):
        settings = {"cover_source": "libretro_then_screenscraper"}
        with patch(
            "openemux.core.cover_sync._screenscraper_candidates", return_value=["ss1", "ss2"]
        ):
            urls = _remote_cover_candidates("SFC", "Chrono Trigger", settings)
        libretro_urls = _libretro_candidates("SFC", "Chrono Trigger", settings)
        self.assertEqual(urls[: len(libretro_urls)], libretro_urls)
        self.assertEqual(urls[len(libretro_urls) :], ["ss1", "ss2"])

    def test_screenscraper_only_source_skips_libretro(self):
        settings = {"cover_source": "screenscraper"}
        with patch(
            "openemux.core.cover_sync._screenscraper_candidates", return_value=["ss1"]
        ):
            urls = _remote_cover_candidates("SFC", "Chrono Trigger", settings)
        self.assertEqual(urls, ["ss1"])

    def test_unknown_source_value_falls_back_to_libretro(self):
        names = [name for name, _fn in _ordered_providers({"cover_source": "bogus"})]
        self.assertEqual(names, ["libretro"])

    def test_screenscraper_provider_swallows_errors(self):
        with patch(
            "openemux.core.cover_sync.screenscraper.lookup_media_urls",
            side_effect=RuntimeError("boom"),
        ):
            from openemux.core.cover_sync import _screenscraper_candidates

            self.assertEqual(_screenscraper_candidates("SFC", "Game", {}), [])


if __name__ == "__main__":
    unittest.main()


class CancellationTests(unittest.TestCase):
    """A long cover sync must be interruptible, and must keep what it fetched."""

    def _library(self, count):
        return {"SFC": [{"name": f"Game {i}", "path": f"/roms/SFC/Game {i}.sfc"} for i in range(count)]}

    def test_cancel_stops_early_and_reports_it(self):
        attempted = []

        def fake_download(url, dest):
            attempted.append(url)
            return True  # every ROM "finds" a cover on its first candidate

        # Cancel once three ROMs have been handled.
        def should_cancel():
            return len(attempted) >= 3

        with TemporaryDirectory() as tmp_dir:
            with mock.patch.object(cover_sync, "_download_cover", fake_download):
                summary = cover_sync._sync_covers(
                    library_by_console=self._library(50),
                    covers_dir=tmp_dir,
                    scope="all",
                    selected_console=None,
                    should_cancel=should_cancel,
                )

        self.assertTrue(summary["cancelled"])
        self.assertEqual(summary["downloaded"], 3)
        # Stopped well before the 50 ROMs the library actually holds.
        self.assertLess(summary["total"], 50)

    def test_cancelled_rom_is_not_counted_as_an_error(self):
        # Cancelling must not look like 47 failed lookups in the summary.
        calls = {"n": 0}

        def fake_download(url, dest):
            calls["n"] += 1
            return True

        with TemporaryDirectory() as tmp_dir:
            with mock.patch.object(cover_sync, "_download_cover", fake_download):
                summary = cover_sync._sync_covers(
                    library_by_console=self._library(50),
                    covers_dir=tmp_dir,
                    scope="all",
                    selected_console=None,
                    should_cancel=lambda: calls["n"] >= 2,
                )

        self.assertEqual(summary["errors"], 0)

    def test_not_cancelled_runs_to_completion(self):
        with TemporaryDirectory() as tmp_dir:
            with mock.patch.object(cover_sync, "_download_cover", lambda url, dest: True):
                summary = cover_sync._sync_covers(
                    library_by_console=self._library(5),
                    covers_dir=tmp_dir,
                    scope="all",
                    selected_console=None,
                    should_cancel=lambda: False,
                )

        self.assertFalse(summary["cancelled"])
        self.assertEqual(summary["downloaded"], 5)
        self.assertEqual(summary["total"], 5)
