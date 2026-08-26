import io
import unittest
import urllib.error
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from openemux.core.retroarch_buildbot_updater import RetroArchBuildbotUpdater


class _FakeConfigManager:
    def __init__(self, base_dir):
        self._runtime_dir = Path(base_dir) / "runtime"
        self._core_dir = Path(base_dir) / "cores"

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
            "retries": 1,
            "parallel_downloads": 1,
        }

    def get_runtime_dir(self):
        return self._runtime_dir


class _FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self.payload


class RetroArchBuildbotUpdaterTests(unittest.TestCase):
    def test_fetch_manifest_filters_core_files(self):
        with TemporaryDirectory() as tmp_dir:
            updater = RetroArchBuildbotUpdater(_FakeConfigManager(tmp_dir))
            listing = (
                '<a href="mgba_libretro.so.zip">mgba</a>'
                '<a href="README.txt">readme</a>'
                '<a href="snes9x_libretro.so.zip">snes9x</a>'
            ).encode("utf-8")
            with patch(
                "openemux.core.retroarch_buildbot_updater.urllib.request.urlopen",
                return_value=_FakeResponse(listing),
            ):
                manifest = updater.fetch_manifest()

        self.assertEqual(len(manifest), 2)
        self.assertEqual(manifest[0]["filename"], "mgba_libretro.so.zip")
        self.assertEqual(manifest[1]["filename"], "snes9x_libretro.so.zip")

    def test_download_all_extracts_core_archive(self):
        with TemporaryDirectory() as tmp_dir:
            updater = RetroArchBuildbotUpdater(_FakeConfigManager(tmp_dir))
            updater.ensure_environment()

            manifest_html = '<a href="mgba_libretro.so.zip">mgba</a>'.encode("utf-8")
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("mgba_libretro.so", b"core-binary")
            zip_bytes = zip_buffer.getvalue()

            def _fake_urlopen(url, timeout=5):
                if str(url).endswith("/buildbot/"):
                    return _FakeResponse(manifest_html)
                if str(url).endswith("mgba_libretro.so.zip"):
                    return _FakeResponse(zip_bytes)
                raise AssertionError(f"unexpected url: {url}")

            with patch("openemux.core.retroarch_buildbot_updater.urllib.request.urlopen", side_effect=_fake_urlopen):
                summary = updater.download_all()

            core_path = updater.core_dir / "mgba_libretro.so"
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

            with patch("openemux.core.retroarch_buildbot_updater.urllib.request.urlopen", side_effect=_fake_urlopen):
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
                "openemux.core.retroarch_buildbot_updater.urllib.request.urlopen",
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
                "openemux.core.retroarch_buildbot_updater.urllib.request.urlopen",
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

            with patch("openemux.core.retroarch_buildbot_updater.urllib.request.urlopen", side_effect=_fake_urlopen):
                summary = updater.download_shader_packs_if_missing()

            self.assertEqual(summary["downloaded"], 2)
            self.assertEqual(summary["failed"], 0)
            self.assertTrue((updater.shader_glsl_dir / "handheld" / "dot.glslp").exists())
            self.assertTrue((updater.shader_slang_dir / "crt" / "geom.slangp").exists())
            # Two shader packs, tens of megabytes each, and neither zip is
            # ever read again (issue #221).
            self.assertEqual(list(updater.cache_dir.iterdir()), [])

    def test_has_local_runtime_assets_uses_runtime_dirs(self):
        with TemporaryDirectory() as tmp_dir:
            updater = RetroArchBuildbotUpdater(_FakeConfigManager(tmp_dir))
            updater.ensure_environment()
            (updater.core_dir / "mgba_libretro.so").write_bytes(b"core")
            (updater.shader_glsl_dir / "crt").mkdir(parents=True, exist_ok=True)
            (updater.shader_glsl_dir / "crt" / "geom.glslp").write_bytes(b"shader")

            self.assertTrue(updater.has_local_runtime_assets())


if __name__ == "__main__":
    unittest.main()
