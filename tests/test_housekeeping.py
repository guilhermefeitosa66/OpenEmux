import os
import time
import unittest
from unittest import mock
from pathlib import Path
from tempfile import TemporaryDirectory

from openemux.core.artwork_search import artwork_temp_root
from openemux.core.housekeeping import (
    RUNTIME_KEEP_LAUNCHES,
    prune_buildbot_cache,
    prune_runtime_files,
    run_startup_housekeeping,
    sweep_artwork_temp_dirs,
)


DAY = 86400


def _touch(path, age_days=0, now=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x", encoding="utf-8")
    stamp = (now if now is not None else time.time()) - age_days * DAY
    os.utime(path, (stamp, stamp))
    return path


def _launch_files(runtime_dir, console, timestamp):
    return [
        runtime_dir / f"runtime_{console}_{timestamp}.cfg",
        runtime_dir / f"coreopts_{console}_{timestamp}.cfg",
        runtime_dir / f"retroarch_{console}_{timestamp}.log",
        runtime_dir / f"retroarch_{console}_{timestamp}.cmd",
    ]


class PruneRuntimeFilesTests(unittest.TestCase):
    def test_removes_old_launches_beyond_the_keep_floor(self):
        with TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            old = _launch_files(runtime, "sfc", "20200101120000")
            recent = _launch_files(runtime, "sfc", "20200201120000")
            for path in old:
                _touch(path, age_days=90)
            for path in recent:
                _touch(path, age_days=90)

            removed = prune_runtime_files(runtime, max_age_days=7, keep_launches=1)

            self.assertEqual(removed, 4)
            self.assertFalse(any(path.exists() for path in old))
            self.assertTrue(all(path.exists() for path in recent))

    def test_keeps_recent_files_even_past_the_launch_floor(self):
        with TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            paths = []
            for index in range(5):
                paths += _launch_files(runtime, "gba", f"2020010112000{index}")
            for path in paths:
                _touch(path, age_days=0)

            removed = prune_runtime_files(runtime, max_age_days=7, keep_launches=1)

            self.assertEqual(removed, 0)
            self.assertTrue(all(path.exists() for path in paths))

    def test_a_kept_launch_keeps_every_file_it_wrote(self):
        with TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            kept = _launch_files(runtime, "md", "20990101120000")
            for path in kept:
                _touch(path, age_days=400)
            for index in range(3):
                for path in _launch_files(runtime, "md", f"2019010112000{index}"):
                    _touch(path, age_days=400)

            prune_runtime_files(runtime, max_age_days=7, keep_launches=1)

            self.assertEqual(sorted(p.name for p in runtime.iterdir()),
                             sorted(p.name for p in kept))

    def test_leaves_files_it_does_not_own_alone(self):
        with TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            keep = [
                _touch(runtime / "openemux_startup.log", age_days=400),
                _touch(runtime / "openemux_startup.log.1", age_days=400),
                _touch(runtime / "shaders_glsl" / "crt.glslp", age_days=400),
                _touch(runtime / "notes.txt", age_days=400),
            ]

            removed = prune_runtime_files(runtime, max_age_days=1, keep_launches=0)

            self.assertEqual(removed, 0)
            self.assertTrue(all(path.exists() for path in keep))

    def test_missing_directory_is_not_an_error(self):
        with TemporaryDirectory() as tmp:
            self.assertEqual(prune_runtime_files(Path(tmp) / "nope"), 0)


class PruneBuildbotCacheTests(unittest.TestCase):
    def test_removes_every_leftover_archive(self):
        with TemporaryDirectory() as tmp:
            cache = Path(tmp)
            _touch(cache / "snes9x_libretro.so.zip")
            _touch(cache / "shaders_glsl.zip")

            removed = prune_buildbot_cache(cache)

            self.assertEqual(removed, 2)
            self.assertEqual(list(cache.iterdir()), [])

    def test_missing_directory_is_not_an_error(self):
        with TemporaryDirectory() as tmp:
            self.assertEqual(prune_buildbot_cache(Path(tmp) / "nope"), 0)


class SweepArtworkTempDirsTests(unittest.TestCase):
    def test_removes_stale_session_directories(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            stale = root / "deadbeef"
            _touch(stale / "candidate-001.png")
            stamp = time.time() - 3 * DAY
            os.utime(stale, (stamp, stamp))

            removed = sweep_artwork_temp_dirs(root, max_age_hours=24)

            self.assertEqual(removed, 1)
            self.assertFalse(stale.exists())

    def test_keeps_a_directory_a_live_session_may_own(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            fresh = root / "cafebabe"
            _touch(fresh / "candidate-001.png")

            removed = sweep_artwork_temp_dirs(root, max_age_hours=24)

            self.assertEqual(removed, 0)
            self.assertTrue(fresh.exists())

    def test_missing_root_is_not_an_error(self):
        with TemporaryDirectory() as tmp:
            self.assertEqual(sweep_artwork_temp_dirs(Path(tmp) / "nope"), 0)


class ArtworkTempRootTests(unittest.TestCase):
    def test_follows_xdg_cache_home(self):
        previous = os.environ.get("XDG_CACHE_HOME")
        os.environ["XDG_CACHE_HOME"] = "/tmp/openemux-cache-test"
        try:
            self.assertEqual(
                artwork_temp_root(),
                Path("/tmp/openemux-cache-test/openemux/artwork-manager"),
            )
        finally:
            if previous is None:
                del os.environ["XDG_CACHE_HOME"]
            else:
                os.environ["XDG_CACHE_HOME"] = previous

    def test_falls_back_to_dot_cache(self):
        previous = os.environ.get("XDG_CACHE_HOME")
        os.environ["XDG_CACHE_HOME"] = ""
        try:
            self.assertEqual(
                artwork_temp_root(),
                Path.home() / ".cache" / "openemux" / "artwork-manager",
            )
        finally:
            if previous is None:
                del os.environ["XDG_CACHE_HOME"]
            else:
                os.environ["XDG_CACHE_HOME"] = previous


class RunStartupHousekeepingTests(unittest.TestCase):
    class _Config:
        def __init__(self, runtime_dir):
            self._runtime_dir = runtime_dir

        def get_runtime_dir(self):
            return self._runtime_dir

    def test_sweeps_all_three_places(self):
        with TemporaryDirectory() as tmp:
            runtime = Path(tmp) / "runtime"
            artwork = Path(tmp) / "artwork-manager"
            # One past the default keep-the-last-N floor, so exactly the
            # oldest launch's four files are the ones eligible to go.
            for index in range(RUNTIME_KEEP_LAUNCHES + 1):
                for path in _launch_files(runtime, "ps", f"202001011200{index:02d}"):
                    _touch(path, age_days=90)
            _touch(runtime / "buildbot_cache" / "snes9x_libretro.so.zip")
            stale = artwork / "deadbeef"
            _touch(stale / "candidate-001.png")
            stamp = time.time() - 3 * DAY
            os.utime(stale, (stamp, stamp))

            summary = run_startup_housekeeping(
                self._Config(runtime), artwork_temp_root=artwork
            )

            self.assertEqual(summary["runtime_files"], 4)
            self.assertEqual(summary["buildbot_cache"], 1)
            self.assertEqual(summary["artwork_temp_dirs"], 1)

    def test_a_broken_config_manager_does_not_raise(self):
        class Broken:
            def get_runtime_dir(self):
                raise RuntimeError("no config")

        with self.assertLogs("openemux.core.housekeeping", level="ERROR"):
            summary = run_startup_housekeeping(Broken())
        self.assertEqual(summary["runtime_files"], 0)


class WhatHousekeepingLeavesAloneTests(unittest.TestCase):
    """It runs at every launch, over directories other things are using."""

    def _two_launches(self, runtime):
        for stamp in ("20200101120000", "20200201120000"):
            for path in _launch_files(runtime, "sfc", stamp):
                _touch(path, age_days=90)

    def test_a_file_that_will_not_delete_is_not_counted_as_removed(self):
        with TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            self._two_launches(runtime)
            with mock.patch.object(
                Path, "unlink", side_effect=OSError("read-only")
            ):
                self.assertEqual(
                    prune_runtime_files(runtime, max_age_days=7, keep_launches=1), 0
                )

    def test_a_launch_file_that_vanishes_mid_sweep_is_skipped(self):
        # RetroArch writes into this directory while the sweep walks it.
        with TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            self._two_launches(runtime)
            with mock.patch.object(Path, "stat", side_effect=OSError("gone")):
                self.assertEqual(
                    prune_runtime_files(runtime, max_age_days=7, keep_launches=1), 0
                )

    def test_a_directory_inside_the_buildbot_cache_is_left_where_it_is(self):
        with TemporaryDirectory() as tmp:
            cache = Path(tmp) / "cache"
            (cache / "a-directory").mkdir(parents=True)
            _touch(cache / "core.zip")

            self.assertEqual(prune_buildbot_cache(cache), 1)
            self.assertTrue((cache / "a-directory").is_dir())

    def test_a_file_beside_the_artwork_session_directories_is_not_swept(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _touch(root / "stray.png", age_days=30)

            self.assertEqual(sweep_artwork_temp_dirs(root, now=time.time()), 0)
            self.assertTrue((root / "stray.png").exists())

    def test_a_session_directory_that_vanishes_mid_sweep_is_skipped(self):
        # Another OpenEmux closing its artwork window between the listing and
        # the age check. Staged rather than raced: a directory that answers
        # is_dir() and then refuses to be stat()ed.
        class _Vanishing:
            def is_dir(self):
                return True

            def stat(self):
                raise OSError("gone")

        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "session-1").mkdir()
            with mock.patch.object(Path, "iterdir", lambda _self: [_Vanishing()]):
                self.assertEqual(sweep_artwork_temp_dirs(root), 0)
            self.assertTrue((root / "session-1").is_dir())

    def test_a_session_directory_that_will_not_go_is_not_counted(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            stale = root / "session-1"
            stale.mkdir()
            stamp = time.time() - 30 * DAY
            os.utime(stale, (stamp, stamp))
            with mock.patch(
                "openemux.core.housekeeping.shutil.rmtree",
                side_effect=OSError("in use"),
            ):
                self.assertEqual(sweep_artwork_temp_dirs(root), 0)
            self.assertTrue(stale.is_dir())


if __name__ == "__main__":
    unittest.main()
