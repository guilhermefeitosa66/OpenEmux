"""Per-ROM artwork search (issue #77): provider fan-out, download, dedup."""

import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock
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


class CandidateDownloadTests(unittest.TestCase):
    """A picker tile has to be a real image too (issue #213)."""

    PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 96

    def _response(self, payload, content_type="image/png"):
        response = mock.MagicMock()
        response.read.return_value = payload
        response.headers.get_content_type.return_value = content_type
        response.__enter__ = lambda s: s
        response.__exit__ = lambda s, *a: False
        return response

    def test_an_image_candidate_is_saved_under_its_real_extension(self):
        with TemporaryDirectory() as tmp_dir:
            with patch(
                "openemux.core.artwork_search.urllib.request.urlopen",
                return_value=self._response(self.PNG, "image/jpeg"),
            ):
                target, digest = artwork_search._download(
                    "https://cdn.example/a.jpg", Path(tmp_dir), 1
                )

            self.assertEqual(target.name, "candidate-001.png")
            self.assertEqual(target.read_bytes(), self.PNG)
            self.assertTrue(digest)

    def test_an_error_page_is_not_offered_as_a_candidate(self):
        with TemporaryDirectory() as tmp_dir:
            with patch(
                "openemux.core.artwork_search.urllib.request.urlopen",
                return_value=self._response(b"<html>quota exceeded</html>" * 4),
            ):
                target, digest = artwork_search._download(
                    "https://cdn.example/a.png", Path(tmp_dir), 1
                )

            self.assertIsNone(target)
            self.assertIsNone(digest)
            self.assertEqual(list(Path(tmp_dir).glob("*")), [])


class CrashedWorkerTests(unittest.TestCase):
    """on_done takes the dialog off its spinner, so it always fires (#214)."""

    def test_a_crashed_search_still_calls_back(self):
        done = threading.Event()
        received = []

        def _on_done(results):
            received.append(results)
            done.set()

        with patch(
            "openemux.core.artwork_search.search_artwork", side_effect=RuntimeError("boom")
        ):
            artwork_search.search_artwork_async(on_done=_on_done)

        self.assertTrue(done.wait(5), "on_done never fired")
        self.assertEqual(received, [[]])

    def test_a_crashed_suggestion_run_still_calls_back(self):
        done = threading.Event()
        received = []

        def _on_done(mode, results):
            received.append((mode, results))
            done.set()

        with patch(
            "openemux.core.artwork_search.suggest_artwork", side_effect=RuntimeError("boom")
        ):
            artwork_search.suggest_artwork_async(on_done=_on_done)

        self.assertTrue(done.wait(5), "on_done never fired")
        self.assertEqual(received, [(None, [])])


if __name__ == "__main__":
    unittest.main()
