import logging
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

logger = logging.getLogger(__name__)

HREF_PATTERN = re.compile(r'href=["\']?([^"\'>\s]+)', re.IGNORECASE)
CORE_ARCHIVE_PATTERN = re.compile(r".+_libretro\.so\.zip$", re.IGNORECASE)
CORE_SO_PATTERN = re.compile(r".+_libretro\.so$", re.IGNORECASE)


class RetroArchBuildbotUpdater:
    def __init__(self, config_manager):
        self.config_manager = config_manager
        self.settings = self.config_manager.get_retroarch_updater_settings()
        self.runtime_dir = self.config_manager.get_runtime_dir()
        self.cache_dir = self.runtime_dir / "buildbot_cache"
        self.core_dir = self._resolve_core_dir()

    def _resolve_core_dir(self):
        configured = self.settings.get("core_dir")
        if configured:
            return Path(configured).expanduser()
        candidates = [
            Path.home() / ".config" / "retroarch" / "cores",
            Path.home() / ".var" / "app" / "org.libretro.RetroArch" / "config" / "retroarch" / "cores",
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate
        return candidates[0]

    def ensure_environment(self):
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.core_dir.mkdir(parents=True, exist_ok=True)
        return {
            "core_dir": str(self.core_dir),
            "cache_dir": str(self.cache_dir),
        }

    def fetch_manifest(self):
        base_url = self.settings.get("cores_base_url", "")
        if not base_url:
            return []
        html = self._fetch_text(base_url)
        artifacts = []
        seen = set()
        for href in HREF_PATTERN.findall(html):
            href = href.strip()
            if not href:
                continue
            parsed_href = urllib.parse.unquote(href)
            filename = os.path.basename(parsed_href)
            if not filename:
                continue
            if not (CORE_ARCHIVE_PATTERN.match(filename) or CORE_SO_PATTERN.match(filename)):
                continue
            if filename in seen:
                continue
            seen.add(filename)
            url = urllib.parse.urljoin(base_url, href)
            if filename.endswith(".zip"):
                core_name = filename[:-4]
                artifact_type = "zip"
            else:
                core_name = filename
                artifact_type = "raw"
            artifacts.append(
                {
                    "filename": filename,
                    "url": url,
                    "type": artifact_type,
                    "core_name": core_name,
                }
            )
        artifacts.sort(key=lambda item: item["filename"].lower())
        logger.info("buildbot manifest loaded: total=%d", len(artifacts))
        return artifacts

    def download_all(self, on_progress=None):
        if not self.settings.get("enabled", True):
            return {"total": 0, "downloaded": 0, "failed": 0, "failures": [], "skipped": True}

        self.ensure_environment()
        artifacts = self.fetch_manifest()
        total = len(artifacts)
        downloaded = 0
        failed = 0
        failures = []

        for index, artifact in enumerate(artifacts, start=1):
            if on_progress:
                on_progress(
                    {
                        "type": "download_progress",
                        "current": index,
                        "total": total,
                        "core_name": artifact["core_name"],
                    }
                )
            try:
                self._download_and_install(artifact)
                downloaded += 1
            except Exception as exc:
                failed += 1
                failures.append({"artifact": artifact["filename"], "error": str(exc)})
                logger.warning("buildbot core download failed: core=%s error=%s", artifact["filename"], exc)

        summary = {
            "total": total,
            "downloaded": downloaded,
            "failed": failed,
            "failures": failures,
            "core_dir": str(self.core_dir),
        }
        logger.info(
            "buildbot core download finished: total=%d downloaded=%d failed=%d",
            total,
            downloaded,
            failed,
        )
        return summary

    def _fetch_text(self, url):
        timeout = max(5, int(self.settings.get("request_timeout_sec", 30)))
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")

    def _download_and_install(self, artifact):
        temp_file = self.cache_dir / artifact["filename"]
        self._download_file_with_retries(artifact["url"], temp_file)
        if artifact["type"] == "zip":
            self._extract_zip_core(temp_file, artifact["core_name"])
        else:
            target_path = self.core_dir / artifact["core_name"]
            self._atomic_write_bytes(target_path, temp_file.read_bytes())

    def _download_file_with_retries(self, url, destination):
        retries = max(0, int(self.settings.get("retries", 3)))
        timeout = max(5, int(self.settings.get("request_timeout_sec", 30)))
        last_error = None
        for attempt in range(retries + 1):
            try:
                with urllib.request.urlopen(url, timeout=timeout) as resp:
                    data = resp.read()
                self._atomic_write_bytes(destination, data)
                return
            except urllib.error.URLError as exc:
                last_error = exc
            except Exception as exc:
                last_error = exc
        raise RuntimeError(f"download failed for {url}: {last_error}")

    def _extract_zip_core(self, archive_path, fallback_core_name):
        with zipfile.ZipFile(archive_path, "r") as archive:
            members = archive.namelist()
            selected = None
            for member in members:
                if member.endswith("/") or "__MACOSX" in member:
                    continue
                basename = os.path.basename(member)
                if CORE_SO_PATTERN.match(basename):
                    selected = member
                    break
            if not selected:
                raise RuntimeError(f"zip has no core .so file: {archive_path}")

            core_bytes = archive.read(selected)
            target_name = os.path.basename(selected) or fallback_core_name
            target_path = self.core_dir / target_name
            self._atomic_write_bytes(target_path, core_bytes)

    def _atomic_write_bytes(self, target_path, data):
        target_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = target_path.with_suffix(target_path.suffix + ".part")
        tmp_path.write_bytes(data)
        tmp_path.replace(target_path)
