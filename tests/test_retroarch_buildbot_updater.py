import io
import threading
import time
import unittest
import urllib.error
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from openemux.core import retroarch_buildbot_updater
from openemux.core.platform import CORE_SUFFIX
from openemux.core.retroarch_buildbot_updater import RetroArchBuildbotUpdater


class _FakeConfigManager:
    def __init__(self, base_dir, parallel_downloads=1, retries=1):
        self._runtime_dir = Path(base_dir) / "runtime"
        self._core_dir = Path(base_dir) / "cores"
        self._parallel_downloads = parallel_downloads
        self._retries = retries

    def get_retroarch_updater_settings(self):
        return {
            "mode": "buildbot_all_cores",
            "enabled": True,
            "core_dir": str(self._core_dir),
            "cores_base_url": "https://example.invalid/buildbot/",
            "core_info_base_url": "https://example.invalid/info.zip",
            "shader_glsl_url": "https://example.invalid/shaders_glsl.zip",
            "shader_slang_url": "https://example.invalid/shaders_slang.zip",
            "request_timeout_sec": 5,
            "retries": self._retries,
            "parallel_downloads": self._parallel_downloads,
        }

    def get_runtime_dir(self):
        return self._runtime_dir


class _FakeResponse(io.BytesIO):
    """A response that behaves like the stream the updater now copies from.

    Artifacts are streamed into place rather than read into a bytes object
    (issue #240), so ``read`` has to take a size the way a real one does.
    """

    def __init__(self, payload):
        super().__init__(payload)
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class RetroArchBuildbotUpdaterTests(unittest.TestCase):
    def test_fetch_manifest_filters_core_files(self):
        with TemporaryDirectory() as tmp_dir:
            updater = RetroArchBuildbotUpdater(_FakeConfigManager(tmp_dir))
            listing = (
                f'<a href="mgba_libretro{CORE_SUFFIX}.zip">mgba</a>'
                '<a href="README.txt">readme</a>'
                f'<a href="snes9x_libretro{CORE_SUFFIX}.zip">snes9x</a>'
            ).encode("utf-8")
            with patch(
                "urllib.request.urlopen",
                return_value=_FakeResponse(listing),
            ):
                manifest = updater.fetch_manifest()

        self.assertEqual(len(manifest), 2)
        self.assertEqual(manifest[0]["filename"], f"mgba_libretro{CORE_SUFFIX}.zip")
        self.assertEqual(manifest[1]["filename"], f"snes9x_libretro{CORE_SUFFIX}.zip")

    def test_download_all_extracts_core_archive(self):
        with TemporaryDirectory() as tmp_dir:
            updater = RetroArchBuildbotUpdater(_FakeConfigManager(tmp_dir))
            updater.ensure_environment()

            manifest_html = f'<a href="mgba_libretro{CORE_SUFFIX}.zip">mgba</a>'.encode("utf-8")
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr(f"mgba_libretro{CORE_SUFFIX}", b"core-binary")
            zip_bytes = zip_buffer.getvalue()

            def _fake_urlopen(url, timeout=5):
                if str(url).endswith("/buildbot/"):
                    return _FakeResponse(manifest_html)
                if str(url).endswith(f"mgba_libretro{CORE_SUFFIX}.zip"):
                    return _FakeResponse(zip_bytes)
                raise AssertionError(f"unexpected url: {url}")

            with patch("urllib.request.urlopen", side_effect=_fake_urlopen):
                summary = updater.download_all()

            core_path = updater.core_dir / f"mgba_libretro{CORE_SUFFIX}"
            self.assertEqual(summary["downloaded"], 1)
            self.assertEqual(summary["failed"], 0)
            self.assertTrue(core_path.exists())
            self.assertEqual(core_path.read_bytes(), b"core-binary")
            # The download is thrown away once extracted: nothing reads the
            # cache back, and a full sweep left hundreds of megabytes of core
            # archives behind forever (issue #221).
            self.assertEqual(list(updater.cache_dir.iterdir()), [])

    def test_a_failed_core_download_leaves_no_archive_behind(self):
        with TemporaryDirectory() as tmp_dir:
            updater = RetroArchBuildbotUpdater(_FakeConfigManager(tmp_dir))
            updater.ensure_environment()

            manifest_html = '<a href="mgba_libretro.so.zip">mgba</a>'.encode("utf-8")

            def _fake_urlopen(url, timeout=5):
                if str(url).endswith("/buildbot/"):
                    return _FakeResponse(manifest_html)
                # Not a zip: extraction raises after the bytes hit the cache.
                return _FakeResponse(b"not-a-zip")

            with patch("urllib.request.urlopen", side_effect=_fake_urlopen):
                summary = updater.download_all()

            self.assertEqual(summary["failed"], 1)
            self.assertEqual(list(updater.cache_dir.iterdir()), [])

    def test_an_offline_manifest_is_a_counted_failure_not_a_crash(self):
        # The whole point: the bootstrap step above decides whether to fall
        # back to the bundled cores, and it only gets to decide if this
        # returns instead of raising (issue #211).
        with TemporaryDirectory() as tmp_dir:
            updater = RetroArchBuildbotUpdater(_FakeConfigManager(tmp_dir))
            with patch(
                "urllib.request.urlopen",
                side_effect=urllib.error.URLError("Network is unreachable"),
            ):
                summary = updater.download_all()

        self.assertEqual(summary["failed"], 1)
        self.assertEqual(summary["total"], 0)
        self.assertEqual(summary["downloaded"], 0)
        self.assertEqual(summary["failures"][0]["artifact"], "manifest")
        self.assertIn("unreachable", summary["failures"][0]["error"])

    def test_an_empty_core_listing_is_a_failure(self):
        # A page whose layout changed under the scraper reads as "no cores to
        # download", which used to be recorded as a completed step -- and a
        # completed step is never re-run.
        with TemporaryDirectory() as tmp_dir:
            updater = RetroArchBuildbotUpdater(_FakeConfigManager(tmp_dir))
            with patch(
                "urllib.request.urlopen",
                return_value=_FakeResponse(b"<html><body>nothing here</body></html>"),
            ):
                summary = updater.download_all()

        self.assertEqual(summary["failed"], 1)
        self.assertEqual(summary["failures"][0]["artifact"], "listing")

    def test_no_configured_url_is_a_failure_too(self):
        with TemporaryDirectory() as tmp_dir:
            config = _FakeConfigManager(tmp_dir)
            settings = config.get_retroarch_updater_settings()
            settings["cores_base_url"] = ""
            config.get_retroarch_updater_settings = lambda: settings
            updater = RetroArchBuildbotUpdater(config)

            summary = updater.download_all()

        self.assertEqual(summary["failed"], 1)
        self.assertIn("cores_base_url", summary["failures"][0]["error"])

    def test_a_disabled_updater_is_still_not_a_failure(self):
        with TemporaryDirectory() as tmp_dir:
            config = _FakeConfigManager(tmp_dir)
            settings = config.get_retroarch_updater_settings()
            settings["enabled"] = False
            config.get_retroarch_updater_settings = lambda: settings
            updater = RetroArchBuildbotUpdater(config)

            summary = updater.download_all()

        self.assertEqual(summary["failed"], 0)
        self.assertTrue(summary["skipped"])

    def test_download_shader_packs_extracts_presets(self):
        with TemporaryDirectory() as tmp_dir:
            updater = RetroArchBuildbotUpdater(_FakeConfigManager(tmp_dir))
            updater.ensure_environment()

            glsl_zip_buffer = io.BytesIO()
            with zipfile.ZipFile(glsl_zip_buffer, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("shaders_glsl/handheld/dot.glslp", b"dot")
            glsl_zip_bytes = glsl_zip_buffer.getvalue()

            slang_zip_buffer = io.BytesIO()
            with zipfile.ZipFile(slang_zip_buffer, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("shaders_slang/crt/geom.slangp", b"geom")
            slang_zip_bytes = slang_zip_buffer.getvalue()

            def _fake_urlopen(url, timeout=5):
                url_str = str(url)
                if url_str.endswith("shaders_glsl.zip"):
                    return _FakeResponse(glsl_zip_bytes)
                if url_str.endswith("shaders_slang.zip"):
                    return _FakeResponse(slang_zip_bytes)
                raise AssertionError(f"unexpected url: {url}")

            with patch("urllib.request.urlopen", side_effect=_fake_urlopen):
                summary = updater.download_shader_packs_if_missing()

            self.assertEqual(summary["downloaded"], 2)
            self.assertEqual(summary["failed"], 0)
            self.assertTrue((updater.shader_glsl_dir / "handheld" / "dot.glslp").exists())
            self.assertTrue((updater.shader_slang_dir / "crt" / "geom.slangp").exists())
            # Two shader packs, tens of megabytes each, and neither zip is
            # ever read again (issue #221).
            self.assertEqual(list(updater.cache_dir.iterdir()), [])

    def test_shader_archive_refuses_members_that_escape_the_target(self):
        # Zip-slip: a member name is attacker-controlled data, and the three
        # shapes below all used to land outside the shader directory (issue
        # #222).
        with TemporaryDirectory() as tmp_dir:
            updater = RetroArchBuildbotUpdater(_FakeConfigManager(tmp_dir))
            updater.ensure_environment()
            outside = Path(tmp_dir) / "outside.txt"
            absolute_member = str(Path(tmp_dir) / "absolute.txt").lstrip("/")

            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("shaders_glsl/handheld/dot.glslp", b"dot")
                archive.writestr("shaders_glsl/../outside.txt", b"leading")
                archive.writestr("shaders_glsl/nested/../../../outside.txt", b"embedded")
                archive.writestr(f"/{absolute_member}", b"absolute")
            glsl_zip_bytes = zip_buffer.getvalue()

            slang_zip_buffer = io.BytesIO()
            with zipfile.ZipFile(slang_zip_buffer, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("shaders_slang/crt/geom.slangp", b"geom")
            slang_zip_bytes = slang_zip_buffer.getvalue()

            def _fake_urlopen(url, timeout=5):
                if str(url).endswith("shaders_slang.zip"):
                    return _FakeResponse(slang_zip_bytes)
                return _FakeResponse(glsl_zip_bytes)

            with patch(
                "urllib.request.urlopen",
                side_effect=_fake_urlopen,
            ):
                summary = updater.download_shader_packs_if_missing()

            self.assertEqual(summary["failed"], 0)
            self.assertTrue((updater.shader_glsl_dir / "handheld" / "dot.glslp").exists())
            self.assertFalse(outside.exists())
            self.assertFalse((Path(tmp_dir) / "absolute.txt").exists())

    def test_safe_destination_accepts_only_paths_under_the_target(self):
        with TemporaryDirectory() as tmp_dir:
            target = Path(tmp_dir) / "shaders"
            safe = RetroArchBuildbotUpdater._safe_destination

            self.assertEqual(
                safe(target, "crt/geom.glslp"), target / "crt" / "geom.glslp"
            )
            self.assertEqual(
                safe(target, "crt/./geom.glslp"), target / "crt" / "geom.glslp"
            )
            for hostile in (
                "",
                ".",
                "..",
                "../evil.glslp",
                "a/../../evil.glslp",
                "a/b/../../../evil.glslp",
                str(Path(tmp_dir) / "evil.glslp"),
                "/etc/evil.glslp",
            ):
                with self.subTest(member=hostile):
                    self.assertIsNone(safe(target, hostile))

    def test_has_local_runtime_assets_uses_runtime_dirs(self):
        with TemporaryDirectory() as tmp_dir:
            updater = RetroArchBuildbotUpdater(_FakeConfigManager(tmp_dir))
            updater.ensure_environment()
            (updater.core_dir / f"mgba_libretro{CORE_SUFFIX}").write_bytes(b"core")
            (updater.shader_glsl_dir / "crt").mkdir(parents=True, exist_ok=True)
            (updater.shader_glsl_dir / "crt" / "geom.glslp").write_bytes(b"shader")

            self.assertTrue(updater.has_local_runtime_assets())


if __name__ == "__main__":
    unittest.main()


class DownloadPacingTests(unittest.TestCase):
    """Retries back off, and only happen when another try could differ (#240)."""

    def test_retries_wait_longer_each_time(self):
        with TemporaryDirectory() as tmp_dir:
            updater = RetroArchBuildbotUpdater(_FakeConfigManager(tmp_dir, retries=3))
            updater.ensure_environment()
            with (
                patch("openemux.core.retroarch_buildbot_updater.time.sleep") as sleep_mock,
                patch(
                    "urllib.request.urlopen",
                    side_effect=urllib.error.URLError("Connection reset"),
                ) as open_mock,
            ):
                with self.assertRaises(RuntimeError):
                    updater._download_file_with_retries(
                        "https://example.invalid/x.zip", updater.cache_dir / "x.zip"
                    )
        self.assertEqual(open_mock.call_count, 4)  # the first try plus three
        delays = [call.args[0] for call in sleep_mock.call_args_list]
        self.assertEqual(delays, [1.0, 2.0, 4.0])

    def test_the_backoff_stops_growing(self):
        with TemporaryDirectory() as tmp_dir:
            updater = RetroArchBuildbotUpdater(_FakeConfigManager(tmp_dir, retries=8))
            updater.ensure_environment()
            with (
                patch("openemux.core.retroarch_buildbot_updater.time.sleep") as sleep_mock,
                patch(
                    "urllib.request.urlopen",
                    side_effect=urllib.error.URLError("nope"),
                ),
            ):
                with self.assertRaises(RuntimeError):
                    updater._download_file_with_retries(
                        "https://example.invalid/x.zip", updater.cache_dir / "x.zip"
                    )
        delays = [call.args[0] for call in sleep_mock.call_args_list]
        self.assertTrue(
            all(d <= retroarch_buildbot_updater.MAX_RETRY_DELAY_SECONDS for d in delays),
            delays,
        )

    def test_an_artifact_the_buildbot_does_not_have_is_not_retried(self):
        """Waiting seven seconds to hear "404" three more times costs a boot."""
        error = urllib.error.HTTPError("https://example.invalid/x.zip", 404, "no", {}, None)
        with TemporaryDirectory() as tmp_dir:
            updater = RetroArchBuildbotUpdater(_FakeConfigManager(tmp_dir, retries=3))
            updater.ensure_environment()
            with (
                patch("openemux.core.retroarch_buildbot_updater.time.sleep") as sleep_mock,
                patch(
                    "urllib.request.urlopen",
                    side_effect=error,
                ) as open_mock,
            ):
                with self.assertRaises(RuntimeError):
                    updater._download_file_with_retries(
                        "https://example.invalid/x.zip", updater.cache_dir / "x.zip"
                    )
        self.assertEqual(open_mock.call_count, 1)
        self.assertEqual(sleep_mock.call_count, 0)

    def test_a_rate_limit_still_is_retried(self):
        error = urllib.error.HTTPError("https://example.invalid/x.zip", 503, "later", {}, None)
        with TemporaryDirectory() as tmp_dir:
            updater = RetroArchBuildbotUpdater(_FakeConfigManager(tmp_dir, retries=2))
            updater.ensure_environment()
            with (
                patch("openemux.core.retroarch_buildbot_updater.time.sleep"),
                patch(
                    "urllib.request.urlopen",
                    side_effect=error,
                ) as open_mock,
            ):
                with self.assertRaises(RuntimeError):
                    updater._download_file_with_retries(
                        "https://example.invalid/x.zip", updater.cache_dir / "x.zip"
                    )
        self.assertEqual(open_mock.call_count, 3)


class StreamingTests(unittest.TestCase):
    """Artifacts are copied, never held (#240).

    A MAME-class core is hundreds of megabytes; reading the archive into a
    bytes object and then the decompressed core into another one spiked peak
    memory by the size of the biggest artifact, twice.
    """

    class _RecordingResponse(io.BytesIO):
        def __init__(self, payload, sizes):
            super().__init__(payload)
            self._sizes = sizes

        def read(self, size=-1):
            self._sizes.append(size)
            return super().read(size)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def test_the_artifact_is_read_in_chunks(self):
        sizes = []
        payload = b"x" * (1024 * 1024)
        with TemporaryDirectory() as tmp_dir:
            updater = RetroArchBuildbotUpdater(_FakeConfigManager(tmp_dir))
            updater.ensure_environment()
            target = updater.cache_dir / "core.bin"
            with patch(
                "urllib.request.urlopen",
                side_effect=lambda url, timeout=5: self._RecordingResponse(payload, sizes),
            ):
                updater._download_file_with_retries("https://example.invalid/x", target)
            self.assertEqual(target.read_bytes(), payload)
        # Never "give me all of it": every read asked for a bounded chunk.
        self.assertTrue(sizes)
        self.assertTrue(all(0 < size <= retroarch_buildbot_updater.DOWNLOAD_CHUNK_BYTES
                            for size in sizes), sizes)

    def test_a_failed_copy_leaves_no_part_file(self):
        class _Exploding(io.BytesIO):
            def read(self, size=-1):
                raise OSError("connection reset")

        with TemporaryDirectory() as tmp_dir:
            updater = RetroArchBuildbotUpdater(_FakeConfigManager(tmp_dir))
            updater.ensure_environment()
            target = updater.core_dir / "core.bin"
            with self.assertRaises(OSError):
                updater._stream_to_file(_Exploding(b""), target)
            self.assertFalse(target.exists())
            self.assertEqual(list(updater.core_dir.iterdir()), [])


class ParallelDownloadTests(unittest.TestCase):
    """``parallel_downloads`` was a knob that changed nothing (#240)."""

    def _manifest(self, count):
        return "".join(
            f'<a href="core{i}_libretro{CORE_SUFFIX}.zip">c{i}</a>' for i in range(count)
        ).encode("utf-8")

    def _zip_bytes(self, name):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(f"{name}_libretro{CORE_SUFFIX}", b"core-binary")
        return buffer.getvalue()

    def _run(self, parallel, count=8, on_progress=None):
        peak = {"now": 0, "value": 0}
        lock = threading.Lock()

        def _fake_urlopen(url, timeout=5):
            if str(url).endswith("/buildbot/"):
                return _FakeResponse(self._manifest(count))
            name = Path(str(url)).name.split("_libretro")[0]
            with lock:
                peak["now"] += 1
                peak["value"] = max(peak["value"], peak["now"])
            time.sleep(0.05)
            with lock:
                peak["now"] -= 1
            return _FakeResponse(self._zip_bytes(name))

        with TemporaryDirectory() as tmp_dir:
            updater = RetroArchBuildbotUpdater(
                _FakeConfigManager(tmp_dir, parallel_downloads=parallel)
            )
            updater.ensure_environment()
            with patch(
                "urllib.request.urlopen",
                side_effect=_fake_urlopen,
            ):
                summary = updater.download_all(on_progress=on_progress)
        return summary, peak["value"]

    def test_the_setting_actually_downloads_in_parallel(self):
        summary, peak = self._run(parallel=4)
        self.assertEqual(summary["downloaded"], 8)
        self.assertEqual(summary["failed"], 0)
        self.assertGreater(peak, 1)

    def test_one_worker_is_still_one_at_a_time(self):
        summary, peak = self._run(parallel=1)
        self.assertEqual(summary["downloaded"], 8)
        self.assertEqual(peak, 1)

    def test_the_pool_is_capped(self):
        with TemporaryDirectory() as tmp_dir:
            updater = RetroArchBuildbotUpdater(
                _FakeConfigManager(tmp_dir, parallel_downloads=500)
            )
            self.assertEqual(
                updater._download_workers(),
                retroarch_buildbot_updater.MAX_PARALLEL_DOWNLOADS,
            )

    def test_a_nonsense_setting_falls_back_to_one_worker_at_least(self):
        with TemporaryDirectory() as tmp_dir:
            for value in (0, -3, "many", None):
                updater = RetroArchBuildbotUpdater(
                    _FakeConfigManager(tmp_dir, parallel_downloads=value)
                )
                self.assertGreaterEqual(updater._download_workers(), 1, value)

    def test_progress_only_ever_grows(self):
        """Out-of-order completions must not walk the counter backwards."""
        events = []
        summary, _peak = self._run(parallel=4, on_progress=events.append)
        self.assertEqual(summary["downloaded"], 8)
        self.assertEqual([e["current"] for e in events], list(range(1, 9)))
        self.assertTrue(all(e["total"] == 8 for e in events))
