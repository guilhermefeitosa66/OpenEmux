"""Per-ROM artwork search (issue #77): provider fan-out, download, dedup."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from openemux.core import artwork_search
from openemux.core.config import COVER_ART_TYPE_BOXART, COVER_ART_TYPE_CARTRIDGE_LABEL

PROVIDERS_ALL = [
    {"id": "libretro", "enabled": True, "kinds": [COVER_ART_TYPE_BOXART]},
    {
        "id": "screenscraper",
        "enabled": True,
        "kinds": [COVER_ART_TYPE_BOXART, COVER_ART_TYPE_CARTRIDGE_LABEL],
    },
    {"id": "openemux", "enabled": True, "kinds": [COVER_ART_TYPE_BOXART]},
]


class ProviderCandidateTests(unittest.TestCase):
    def test_pairs_follow_the_configured_chain_order(self):
        with (
            patch("openemux.core.cover_sync._libretro_candidates", return_value=["l1", "l2"]),
            patch("openemux.core.cover_sync._screenscraper_candidates", return_value=["s1"]),
            patch("openemux.core.cover_sync._openemux_candidates", return_value=["o1"]),
        ):
            pairs = artwork_search.provider_candidates(
                "SFC", "Chrono Trigger", {"providers": PROVIDERS_ALL}, COVER_ART_TYPE_BOXART
            )
        self.assertEqual(
            pairs,
            [("libretro", "l1"), ("libretro", "l2"), ("screenscraper", "s1"), ("openemux", "o1")],
        )

    def test_label_search_only_asks_label_capable_providers(self):
        with (
            patch("openemux.core.cover_sync._libretro_candidates") as libretro_mock,
            patch("openemux.core.cover_sync._screenscraper_candidates", return_value=["s1"]),
        ):
            pairs = artwork_search.provider_candidates(
                "SFC",
                "Chrono Trigger",
                {"providers": PROVIDERS_ALL},
                COVER_ART_TYPE_CARTRIDGE_LABEL,
            )
        libretro_mock.assert_not_called()
        self.assertEqual(pairs, [("screenscraper", "s1")])

    def test_a_broken_provider_does_not_kill_the_search(self):
        with (
            patch(
                "openemux.core.cover_sync._libretro_candidates",
                side_effect=RuntimeError("boom"),
            ),
            patch("openemux.core.cover_sync._screenscraper_candidates", return_value=["s1"]),
            patch("openemux.core.cover_sync._openemux_candidates", return_value=[]),
        ):
            pairs = artwork_search.provider_candidates(
                "SFC", "Chrono Trigger", {"providers": PROVIDERS_ALL}, COVER_ART_TYPE_BOXART
            )
        self.assertEqual(pairs, [("screenscraper", "s1")])


class SearchDownloadTests(unittest.TestCase):
    def _search(self, tmp_dir, pair_list, payloads):
        """Run search_artwork with canned candidate pairs and download bodies."""

        def fake_download(url, dest_dir, index):
            data = payloads.get(url)
            if data is None:
                return None, None
            target = Path(dest_dir) / f"candidate-{index:03d}.png"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            import hashlib

            return target, hashlib.sha1(data).hexdigest()

        with (
            patch("openemux.core.artwork_search.provider_candidates", return_value=pair_list),
            patch("openemux.core.artwork_search._download", side_effect=fake_download),
        ):
            return artwork_search.search_artwork(
                console="SFC",
                rom_name="Chrono Trigger",
                sync_settings={},
                art_kind=COVER_ART_TYPE_BOXART,
                dest_dir=Path(tmp_dir),
            )

    def test_failed_urls_are_skipped_and_hits_are_kept(self):
        pairs = [("libretro", "u1"), ("libretro", "u2"), ("screenscraper", "u3")]
        with TemporaryDirectory() as tmp_dir:
            results = self._search(
                tmp_dir, pairs, {"u2": b"image-a", "u3": b"image-b"}
            )
            for candidate in results:
                self.assertTrue(candidate.path.exists())
        self.assertEqual([c.url for c in results], ["u2", "u3"])
        self.assertEqual([c.provider for c in results], ["libretro", "screenscraper"])

    def test_identical_images_from_different_urls_are_deduplicated(self):
        pairs = [("libretro", "u1"), ("libretro", "u2"), ("screenscraper", "u3")]
        with TemporaryDirectory() as tmp_dir:
            results = self._search(
                tmp_dir, pairs, {"u1": b"same", "u2": b"same", "u3": b"same"}
            )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].url, "u1")

    def test_per_provider_result_cap(self):
        pairs = [("libretro", f"u{i}") for i in range(10)]
        payloads = {f"u{i}": f"img-{i}".encode() for i in range(10)}
        with TemporaryDirectory() as tmp_dir:
            results = self._search(tmp_dir, pairs, payloads)
        self.assertEqual(len(results), artwork_search.MAX_RESULTS_PER_PROVIDER)


if __name__ == "__main__":
    unittest.main()
