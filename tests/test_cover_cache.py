"""The cover decode pool and its LRU (issue #128)."""

import threading
import time
from contextlib import contextmanager
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import gi

gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf

from openemux.core import cover_cache


@contextmanager
def _budget(limit):
    """Run with a small cache bound, and put the real one back."""
    original = cover_cache.MAX_CACHE_BYTES
    cover_cache.MAX_CACHE_BYTES = limit
    cover_cache.cache_clear()
    try:
        yield
    finally:
        cover_cache.MAX_CACHE_BYTES = original
        cover_cache.cache_clear()


def _bytes_of(width, height):
    """What a decoded RGBA cover of this size occupies."""
    pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, width, height)
    return pixbuf.get_byte_length()


def _write_png(path, width=64, height=48, colour=0xFF0000FF):
    pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, width, height)
    pixbuf.fill(colour)
    pixbuf.savev(str(path), "png", [], [])
    return path


class LoadCoverTests(unittest.TestCase):
    def setUp(self):
        cover_cache.cache_clear()

    def test_decodes_at_full_resolution_without_a_target(self):
        with TemporaryDirectory() as tmp_dir:
            cover = _write_png(Path(tmp_dir) / "cover.png", 64, 48)
            pixbuf = cover_cache.load_cover(cover)
            self.assertEqual((pixbuf.get_width(), pixbuf.get_height()), (64, 48))

    def test_scales_to_fit_the_target_preserving_aspect(self):
        with TemporaryDirectory() as tmp_dir:
            cover = _write_png(Path(tmp_dir) / "cover.png", 100, 50)
            pixbuf = cover_cache.load_cover(cover, 40, 40)
            self.assertEqual(pixbuf.get_width(), 40)
            self.assertEqual(pixbuf.get_height(), 20)

    def test_a_missing_file_returns_none_quietly(self):
        # The ordinary "no artwork" case: the placeholder already says so, and
        # logging it would drown the corrupt-file warning below.
        with self.assertNoLogs("openemux.core.cover_cache", level="WARNING"):
            self.assertIsNone(cover_cache.load_cover("/nope/missing.png"))
            self.assertIsNone(cover_cache.load_cover(None))

    def test_a_corrupt_file_returns_none_and_is_logged(self):
        # A corrupt cover used to be indistinguishable from a missing one.
        with TemporaryDirectory() as tmp_dir:
            broken = Path(tmp_dir) / "broken.png"
            broken.write_bytes(b"this is not an image")
            with self.assertLogs("openemux.core.cover_cache", level="WARNING") as logs:
                self.assertIsNone(cover_cache.load_cover(broken))
            self.assertTrue(any("decode failed" in line for line in logs.output))


class CacheTests(unittest.TestCase):
    def setUp(self):
        cover_cache.cache_clear()

    def test_the_same_key_returns_the_very_same_object(self):
        with TemporaryDirectory() as tmp_dir:
            cover = _write_png(Path(tmp_dir) / "cover.png")
            first = cover_cache.load_cover(cover, 32, 32)
            second = cover_cache.load_cover(cover, 32, 32)
            self.assertIs(first, second)

    def test_a_different_target_size_is_a_different_entry(self):
        with TemporaryDirectory() as tmp_dir:
            cover = _write_png(Path(tmp_dir) / "cover.png")
            small = cover_cache.load_cover(cover, 16, 16)
            large = cover_cache.load_cover(cover, 48, 48)
            self.assertIsNot(small, large)
            self.assertEqual(cover_cache.cache_size(), 2)

    def test_replacing_the_file_invalidates_by_itself(self):
        # Content-addressed on mtime and size, the same self-invalidating
        # shape cartridge_render uses: no explicit invalidation hook to
        # forget to call when artwork is replaced on disk.
        with TemporaryDirectory() as tmp_dir:
            cover = Path(tmp_dir) / "cover.png"
            _write_png(cover, 64, 64)
            first = cover_cache.load_cover(cover)
            self.assertEqual(first.get_width(), 64)

            time.sleep(0.01)
            _write_png(cover, 32, 32)
            second = cover_cache.load_cover(cover)
            self.assertEqual(second.get_width(), 32)
            self.assertIsNot(first, second)

    def test_eviction_respects_the_byte_budget(self):
        """The bound is memory, not a headcount (issue #219).

        Counting entries said nothing about how much was held: the cartridge
        branch decodes at full resolution, where one entry is megabytes.
        """
        # Three of these fit; the fourth has to push the oldest out.
        budget = 3 * _bytes_of(16, 16)
        with _budget(budget):
            with TemporaryDirectory() as tmp_dir:
                for i in range(6):
                    cover_cache.load_cover(_write_png(Path(tmp_dir) / f"c{i}.png", 16, 16))
                self.assertLessEqual(cover_cache.cache_bytes(), budget)
                self.assertEqual(cover_cache.cache_size(), 3)

    def test_one_big_cover_evicts_several_small_ones(self):
        """What the entry count could not express: entries differ in size."""
        with _budget(_bytes_of(64, 64)):
            with TemporaryDirectory() as tmp_dir:
                for i in range(4):
                    cover_cache.load_cover(_write_png(Path(tmp_dir) / f"s{i}.png", 8, 8))
                self.assertEqual(cover_cache.cache_size(), 4)
                cover_cache.load_cover(_write_png(Path(tmp_dir) / "big.png", 64, 64))
                self.assertEqual(cover_cache.cache_size(), 1)
                self.assertLessEqual(cover_cache.cache_bytes(), _bytes_of(64, 64))

    def test_a_cover_bigger_than_the_whole_budget_is_still_kept(self):
        """Otherwise the one cover being looked at is the one never cached."""
        with _budget(_bytes_of(8, 8)):
            with TemporaryDirectory() as tmp_dir:
                cover = _write_png(Path(tmp_dir) / "huge.png", 64, 64)
                first = cover_cache.load_cover(cover)
                self.assertIs(cover_cache.load_cover(cover), first)

    def test_a_reused_entry_survives_eviction(self):
        with _budget(2 * _bytes_of(10, 10)):
            with TemporaryDirectory() as tmp_dir:
                a = _write_png(Path(tmp_dir) / "a.png", 8, 8)
                b = _write_png(Path(tmp_dir) / "b.png", 9, 9)
                c = _write_png(Path(tmp_dir) / "c.png", 10, 10)
                first_a = cover_cache.load_cover(a)
                cover_cache.load_cover(b)
                cover_cache.load_cover(a)  # touch: a is now the most recent
                cover_cache.load_cover(c)  # evicts b, not a
                self.assertIs(cover_cache.load_cover(a), first_a)

    def test_the_running_total_comes_back_to_zero(self):
        with TemporaryDirectory() as tmp_dir:
            cover_cache.load_cover(_write_png(Path(tmp_dir) / "a.png", 32, 32))
            self.assertGreater(cover_cache.cache_bytes(), 0)
            cover_cache.cache_clear()
            self.assertEqual(cover_cache.cache_bytes(), 0)


class PoolTests(unittest.TestCase):
    def test_the_pool_is_bounded(self):
        # The whole point: the old code span one OS thread per ROM, so a
        # 500-ROM console meant 500 threads.
        live = []
        peak = [0]
        lock = threading.Lock()
        release = threading.Event()

        def _task():
            with lock:
                live.append(1)
                peak[0] = max(peak[0], len(live))
            release.wait(5)
            with lock:
                live.pop()

        futures = [cover_cache.submit(_task) for _ in range(cover_cache.MAX_WORKERS * 4)]
        # Let the pool saturate before letting anything finish.
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            with lock:
                if len(live) >= cover_cache.MAX_WORKERS:
                    break
            time.sleep(0.01)
        release.set()
        for future in futures:
            future.result(5)

        self.assertLessEqual(peak[0], cover_cache.MAX_WORKERS)
        self.assertGreater(peak[0], 0)

    def test_submissions_all_run(self):
        results = []
        lock = threading.Lock()

        def _task(value):
            with lock:
                results.append(value)

        futures = [cover_cache.submit(_task, i) for i in range(50)]
        for future in futures:
            future.result(5)
        self.assertEqual(sorted(results), list(range(50)))

    def test_the_pool_is_shared(self):
        self.assertIs(cover_cache.pool(), cover_cache.pool())


if __name__ == "__main__":
    unittest.main()
