import io
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from opemux.core.retroarch_buildbot_updater import RetroArchBuildbotUpdater


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
                "opemux.core.retroarch_buildbot_updater.urllib.request.urlopen",
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

            with patch("opemux.core.retroarch_buildbot_updater.urllib.request.urlopen", side_effect=_fake_urlopen):
                summary = updater.download_all()

            core_path = updater.core_dir / "mgba_libretro.so"
            self.assertEqual(summary["downloaded"], 1)
            self.assertEqual(summary["failed"], 0)
            self.assertTrue(core_path.exists())
            self.assertEqual(core_path.read_bytes(), b"core-binary")


if __name__ == "__main__":
    unittest.main()
