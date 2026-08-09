"""The picker suggestion pipeline (#185): artwork_search.suggest_artwork."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from openemux.core import artwork_search


class _Index:
    def __init__(self, fts=None, fuzzy=None):
        self._fts = fts or []
        self._fuzzy = fuzzy or []
        self.calls = []

    def suggest(self, system, query, limit=10, approximate=False):
        self.calls.append((system, query, approximate))
        return self._fuzzy if approximate else self._fts


class SuggestArtworkTests(unittest.TestCase):
    def test_fts_results_win_and_previews_come_from_the_mirror(self):
        index = _Index(fts=["Chrono Trigger (USA)"])
        downloaded = []

        def _fake_download(url, dest_dir, position):
            downloaded.append(url)
            target = Path(dest_dir) / f"candidate-{position:03d}.webp"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"img")
            return target, f"digest-{position}"

        with TemporaryDirectory() as tmp:
            with patch("openemux.core.artwork_search._download", side_effect=_fake_download):
                mode, results = artwork_search.suggest_artwork(
                    "SFC", "chrono", dest_dir=tmp, index=index
                )
        self.assertEqual(mode, artwork_search.SUGGESTION_MODE_FTS)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].title, "Chrono Trigger (USA)")
        # Preview fetched from the project mirror, where the stem exists.
        self.assertIn("raw.githubusercontent.com", downloaded[0])
        self.assertIn("Chrono%20Trigger%20%28USA%29.webp", downloaded[0])
        # Approximate mode never consulted when FTS answered.
        self.assertEqual([call[2] for call in index.calls], [False])

    def test_fuzzy_is_the_fallback_and_is_labeled_as_such(self):
        index = _Index(fts=[], fuzzy=["Chrono Trigger (USA)"])
        with TemporaryDirectory() as tmp:
            with patch(
                "openemux.core.artwork_search._download",
                side_effect=lambda url, d, i: (Path(d) / f"c{i}.webp", f"dg{i}")
                if Path(d).mkdir(parents=True, exist_ok=True) is None else None,
            ):
                mode, results = artwork_search.suggest_artwork(
                    "SFC", "chrno", dest_dir=tmp, index=index
                )
        self.assertEqual(mode, artwork_search.SUGGESTION_MODE_FUZZY)
        self.assertEqual([call[2] for call in index.calls], [False, True])
        self.assertEqual(results[0].provider, artwork_search.SUGGESTION_MODE_FUZZY)

    def test_duplicate_previews_are_collapsed(self):
        index = _Index(fts=["A (USA)", "A (Europe)"])

        def _same_digest(url, dest_dir, position):
            target = Path(dest_dir) / f"c{position}.webp"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"img")
            return target, "same"

        with TemporaryDirectory() as tmp:
            with patch("openemux.core.artwork_search._download", side_effect=_same_digest):
                _mode, results = artwork_search.suggest_artwork(
                    "SFC", "a", dest_dir=tmp, index=index
                )
        self.assertEqual(len(results), 1)

    def test_a_failing_index_yields_no_suggestions(self):
        class _Broken:
            def suggest(self, *args, **kwargs):
                raise RuntimeError("boom")

        with TemporaryDirectory() as tmp:
            mode, results = artwork_search.suggest_artwork(
                "SFC", "chrono", dest_dir=tmp, index=_Broken()
            )
        self.assertEqual(results, [])

    def test_an_unknown_console_yields_no_suggestions(self):
        with TemporaryDirectory() as tmp:
            _mode, results = artwork_search.suggest_artwork(
                "NOT_A_CONSOLE", "chrono", dest_dir=tmp, index=_Index()
            )
        self.assertEqual(results, [])


if __name__ == "__main__":
    unittest.main()
