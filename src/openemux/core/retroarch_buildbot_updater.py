import logging
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

from openemux.core.paths import get_project_root

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
        self.shader_glsl_dir = self.runtime_dir / "shaders_glsl"
        self.shader_slang_dir = self.runtime_dir / "shaders_slang"
        self.project_root = get_project_root()
        self.bundled_core_dir = self.project_root / "vendors" / "retroarch-assets" / "cores"
        self.bundled_shader_glsl_dir = self.project_root / "vendors" / "retroarch-assets" / "shaders_glsl"
        self.bundled_shader_slang_dir = self.project_root / "vendors" / "retroarch-assets" / "shaders_slang"

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
        self.shader_glsl_dir.mkdir(parents=True, exist_ok=True)
        self.shader_slang_dir.mkdir(parents=True, exist_ok=True)
        return {
            "core_dir": str(self.core_dir),
            "cache_dir": str(self.cache_dir),
            "shader_glsl_dir": str(self.shader_glsl_dir),
            "shader_slang_dir": str(self.shader_slang_dir),
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
        """Download every core the buildbot lists, and report what happened.

        Never raises for a network problem. The bootstrap step above this one
        decides what a failure means -- on a package that bundles cores it
        falls back to those and carries on -- and it can only decide if it is
        told (issue #211). An exception escaping here skipped that decision
        entirely and marked the whole first boot as failed, so installing
        offline from a .deb that already ships the cores ended at "bootstrap
        failed" instead of a working app.
        """
        if not self.settings.get("enabled", True):
            return {"total": 0, "downloaded": 0, "failed": 0, "failures": [], "skipped": True}

        self.ensure_environment()
        try:
            artifacts = self.fetch_manifest()
        except Exception as exc:
            logger.warning("buildbot manifest unavailable: error=%s", exc)
            return self._core_download_failure("manifest", str(exc))

        total = len(artifacts)
        if total == 0:
            # Not "nothing to do": the updater is on, so either the listing
            # page changed shape under the scraper, the URL is wrong, or there
            # is no URL at all. Reporting success here recorded the step as
            # completed -- and a completed step is never re-run, so the user
            # was left with no cores and no way for the bootstrap to fix it.
            reason = (
                "no cores_base_url configured"
                if not self.settings.get("cores_base_url", "")
                else "the core listing was empty"
            )
            logger.warning("buildbot core listing yielded nothing: reason=%s", reason)
            return self._core_download_failure("listing", reason)

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

    def _core_download_failure(self, artifact, error):
        """A summary shaped like a real one, carrying a single failure.

        ``failed >= 1`` is the signal the bootstrap step reads to consult the
        bundled assets, so a whole-phase failure has to arrive counted.
        """
        return {
            "total": 0,
            "downloaded": 0,
            "failed": 1,
            "failures": [{"artifact": artifact, "error": error}],
            "core_dir": str(self.core_dir),
        }

    def _fetch_text(self, url):
        timeout = max(5, int(self.settings.get("request_timeout_sec", 30)))
        # url is the configured https RetroArch buildbot base
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # nosec B310
            return resp.read().decode("utf-8", errors="replace")

    def _download_and_install(self, artifact):
        temp_file = self.cache_dir / artifact["filename"]
        try:
            self._download_file_with_retries(artifact["url"], temp_file)
            if artifact["type"] == "zip":
                self._extract_zip_core(temp_file, artifact["core_name"])
            else:
                target_path = self.core_dir / artifact["core_name"]
                self._atomic_write_bytes(target_path, temp_file.read_bytes())
        finally:
            # The name says temp but nothing ever removed it, and nothing ever
            # read it back either -- the next run re-downloads regardless. A
            # full core sweep left hundreds of megabytes here, and the same
            # again after every update (issue #221).
            self._discard(temp_file)

    @staticmethod
    def _discard(path):
        """Remove a finished download; never the reason an install fails."""
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            logger.debug("buildbot cache file not removed: path=%s error=%s", path, exc)

    def _download_file_with_retries(self, url, destination):
        retries = max(0, int(self.settings.get("retries", 3)))
        timeout = max(5, int(self.settings.get("request_timeout_sec", 30)))
        last_error = None
        for attempt in range(retries + 1):
            try:
                # url is an https artifact link from the RetroArch buildbot listing
                with urllib.request.urlopen(url, timeout=timeout) as resp:  # nosec B310
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

    def download_shader_packs_if_missing(self, on_progress=None):
        if not self.settings.get("enabled", True):
            return {
                "total": 0,
                "downloaded": 0,
                "skipped": 0,
                "failed": 0,
                "failures": [],
                "targets": [str(self.shader_glsl_dir), str(self.shader_slang_dir)],
                "disabled": True,
            }

        self.ensure_environment()
        packs = [
            ("shaders_glsl", self.settings.get("shader_glsl_url", ""), self.shader_glsl_dir, ".glslp"),
            ("shaders_slang", self.settings.get("shader_slang_url", ""), self.shader_slang_dir, ".slangp"),
        ]
        summary = {
            "total": len(packs),
            "downloaded": 0,
            "skipped": 0,
            "failed": 0,
            "failures": [],
            "targets": [str(self.shader_glsl_dir), str(self.shader_slang_dir)],
        }

        for index, (pack_name, url, target_dir, extension) in enumerate(packs, start=1):
            if on_progress:
                on_progress(
                    {
                        "type": "download_progress",
                        "current": index,
                        "total": len(packs),
                        "core_name": pack_name,
                    }
                )
            if not url:
                summary["failed"] += 1
                summary["failures"].append({"artifact": pack_name, "error": "missing url"})
                continue
            if self._directory_has_files_with_extension(target_dir, extension):
                summary["skipped"] += 1
                continue
            archive_path = self.cache_dir / f"{pack_name}.zip"
            try:
                self._download_file_with_retries(url, archive_path)
                self._extract_shader_archive(archive_path, pack_name, target_dir)
                if self._directory_has_files_with_extension(target_dir, extension):
                    summary["downloaded"] += 1
                else:
                    raise RuntimeError(f"pack extracted with no {extension} presets")
            except Exception as exc:
                summary["failed"] += 1
                summary["failures"].append({"artifact": pack_name, "error": str(exc)})
                logger.warning("buildbot shader download failed: pack=%s error=%s", pack_name, exc)
            finally:
                # Extracted or not, the zip has served its purpose: the shader
                # packs are tens of megabytes each (issue #221).
                self._discard(archive_path)
        return summary

    def _directory_has_files_with_extension(self, directory, extension):
        if not directory.exists():
            return False
        for candidate in directory.rglob(f"*{extension}"):
            if candidate.is_file():
                return True
        return False

    def _directory_has_cores(self, directory):
        if not directory.exists():
            return False
        for candidate in directory.rglob("*_libretro.so"):
            if candidate.is_file():
                return True
        return False

    def has_local_core_assets(self):
        return any(
            self._directory_has_cores(directory)
            for directory in (self.core_dir, self.bundled_core_dir)
        )

    def has_local_shader_assets(self):
        glsl_ok = any(
            self._directory_has_files_with_extension(directory, ".glslp")
            for directory in (self.shader_glsl_dir, self.bundled_shader_glsl_dir)
        )
        slang_ok = any(
            self._directory_has_files_with_extension(directory, ".slangp")
            for directory in (self.shader_slang_dir, self.bundled_shader_slang_dir)
        )
        return glsl_ok or slang_ok

    def has_local_runtime_assets(self):
        return self.has_local_core_assets() and self.has_local_shader_assets()

    def _extract_shader_archive(self, archive_path, pack_name, target_dir):
        target_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive_path, "r") as archive:
            members = [member for member in archive.namelist() if member and not member.endswith("/")]
            preferred_prefix = f"{pack_name}/"
            preferred = [member for member in members if member.startswith(preferred_prefix)]
            selected = preferred if preferred else members

            if not selected:
                raise RuntimeError(f"empty shader archive: {archive_path}")

            for member in selected:
                data = archive.read(member)
                relative = member
                if member.startswith(preferred_prefix):
                    relative = member[len(preferred_prefix):]
                relative_path = Path(relative)
                if not str(relative_path) or str(relative_path).startswith("../"):
                    continue
                destination = target_dir / relative_path
                destination.parent.mkdir(parents=True, exist_ok=True)
                self._atomic_write_bytes(destination, data)

    def _atomic_write_bytes(self, target_path, data):
        target_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = target_path.with_suffix(target_path.suffix + ".part")
        tmp_path.write_bytes(data)
        tmp_path.replace(target_path)
