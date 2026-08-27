import logging
import os
import re
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from openemux.core.paths import get_project_root
from openemux.core.platform import CORE_SUFFIX
# Aliased: this class already has a ``bundled_core_dir`` attribute meaning the
# retroarch-assets directory, and the two must not be confused.
from openemux.core.platform import bundled_core_dir as platform_bundled_core_dir

logger = logging.getLogger(__name__)

HREF_PATTERN = re.compile(r'href=["\']?([^"\'>\s]+)', re.IGNORECASE)
# The buildbot serves "<core>_libretro.so.zip" for Linux and
# "<core>_libretro.dll.zip" for Windows, from platform-specific directories, so
# the extension is built from the running platform rather than hardcoded.
_CORE_SUFFIX_RE = re.escape(CORE_SUFFIX)
CORE_ARCHIVE_PATTERN = re.compile(r".+_libretro" + _CORE_SUFFIX_RE + r"\.zip$", re.IGNORECASE)
CORE_SO_PATTERN = re.compile(r".+_libretro" + _CORE_SUFFIX_RE + r"$", re.IGNORECASE)

#: Retry pacing for a failed artifact. Three immediate retries against a host
#: that just refused is a burst, not a retry (issue #240); the delay doubles
#: and stops growing at the cap.
RETRY_BASE_DELAY_SECONDS = 1.0
MAX_RETRY_DELAY_SECONDS = 10.0

#: Statuses worth another attempt. Anything else the host said on purpose --
#: a 404 is not going to become a file, and waiting seven seconds to hear it
#: three more times costs a first boot real time.
RETRYABLE_STATUSES = (408, 425, 429, 500, 502, 503, 504)

#: Ceiling on ``parallel_downloads``: the buildbot is somebody else's server.
MAX_PARALLEL_DOWNLOADS = 8

#: Copy buffer. Artifacts are streamed rather than buffered whole, so this is
#: the memory a download costs regardless of the core's size.
DOWNLOAD_CHUNK_BYTES = 256 * 1024


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
        # Windows downloads into the bundled RetroArch's own cores directory.
        # It runs portable, and writing to %APPDATA%\RetroArch instead would
        # modify a RetroArch the user installed themselves -- which issue #118
        # requires us to leave alone.
        bundled = platform_bundled_core_dir(get_project_root())
        if bundled:
            return bundled
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
        workers = self._download_workers()
        completed = 0

        logger.info("buildbot core download starting: total=%d workers=%d", total, workers)
        with ThreadPoolExecutor(
            max_workers=workers, thread_name_prefix="openemux-core-dl"
        ) as pool:
            pending = {
                pool.submit(self._install_artifact, artifact): artifact
                for artifact in artifacts
            }
            # Progress is reported from here, on completion, so the counter
            # only ever grows even though the downloads finish out of order.
            for future in as_completed(pending):
                artifact = pending[future]
                completed += 1
                error = future.result()
                if error is None:
                    downloaded += 1
                else:
                    failed += 1
                    failures.append({"artifact": artifact["filename"], "error": error})
                if on_progress:
                    on_progress(
                        {
                            "type": "download_progress",
                            "current": completed,
                            "total": total,
                            "core_name": artifact["core_name"],
                        }
                    )

        # Arrival order is not meaningful with a pool; report them by name.
        failures.sort(key=lambda entry: entry["artifact"])

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

    def _install_artifact(self, artifact):
        """Fetch and install one artifact. Returns an error string, or None.

        Never raises: it runs on a pool, and one core the buildbot is missing
        must not take the sweep down with it.
        """
        try:
            self._download_and_install(artifact)
            return None
        except Exception as exc:  # noqa: BLE001 - reported, not raised
            logger.warning(
                "buildbot core download failed: core=%s error=%s", artifact["filename"], exc
            )
            return str(exc)

    def _download_workers(self):
        """How many artifacts to fetch at once.

        ``parallel_downloads`` has sat in the config -- and in the settings the
        user can edit -- since the updater was written, and nothing ever read
        it: the sweep ran one artifact at a time on one thread, so a first boot
        took as long as the sum of every download in a manifest of a hundred
        and more (issue #240). Capped, because the buildbot is somebody else's
        server.
        """
        try:
            configured = int(self.settings.get("parallel_downloads", 4))
        except (TypeError, ValueError):
            configured = 4
        return max(1, min(configured, MAX_PARALLEL_DOWNLOADS))

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
                with open(temp_file, "rb") as handle:
                    self._stream_to_file(handle, target_path)
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
        """Fetch ``url`` into ``destination``, streamed, with a backoff.

        Two things this used to get wrong (issue #240): the retries fired back
        to back, so a host that had just failed got three more requests inside
        a millisecond; and the whole artifact was read into a bytes object
        before anything was written, which for a MAME-class core is hundreds of
        megabytes of resident memory per download.
        """
        retries = max(0, int(self.settings.get("retries", 3)))
        timeout = max(5, int(self.settings.get("request_timeout_sec", 30)))
        last_error = None
        for attempt in range(retries + 1):
            if attempt:
                delay = min(
                    RETRY_BASE_DELAY_SECONDS * (2 ** (attempt - 1)),
                    MAX_RETRY_DELAY_SECONDS,
                )
                logger.info(
                    "buildbot retrying: url=%s attempt=%d/%d in=%.1fs error=%s",
                    url, attempt + 1, retries + 1, delay, last_error,
                )
                time.sleep(delay)
            try:
                # url is an https artifact link from the RetroArch buildbot listing
                with urllib.request.urlopen(url, timeout=timeout) as resp:  # nosec B310
                    self._stream_to_file(resp, destination)
                return
            except Exception as exc:  # noqa: BLE001 - retried or re-raised below
                last_error = exc
                if not self._is_retryable(exc):
                    break
        raise RuntimeError(f"download failed for {url}: {last_error}")

    @staticmethod
    def _is_retryable(exc):
        """Whether another attempt could plausibly go differently."""
        if isinstance(exc, urllib.error.HTTPError):
            return exc.code in RETRYABLE_STATUSES
        # A transport error -- unreachable, reset, timed out -- is exactly what
        # a retry is for.
        return True

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
                raise RuntimeError(f"zip has no core {CORE_SUFFIX} file: {archive_path}")

            target_name = os.path.basename(selected) or fallback_core_name
            target_path = self.core_dir / target_name
            # Streamed out of the archive: reading the decompressed core into
            # memory first doubled the spike the download already caused, and
            # the biggest cores are the ones that can least afford it (#240).
            with archive.open(selected, "r") as member:
                self._stream_to_file(member, target_path)

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
        for candidate in directory.rglob(f"*_libretro{CORE_SUFFIX}"):
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
                relative = member
                if member.startswith(preferred_prefix):
                    relative = member[len(preferred_prefix):]
                destination = self._safe_destination(target_dir, relative)
                if destination is None:
                    logger.warning(
                        "buildbot shader archive: skipping unsafe member: pack=%s member=%s",
                        pack_name,
                        member,
                    )
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member, "r") as source:
                    self._stream_to_file(source, destination)

    @staticmethod
    def _safe_destination(target_dir, member_name):
        """Resolve an archive member under target_dir, or None if it escapes.

        Archive member names are attacker-controlled data, so three shapes have
        to be refused before anything is written (issue #222): an absolute name,
        which `Path.__truediv__` would let win over `target_dir` entirely; a name
        with `..` anywhere in it, embedded ones included; and an empty name.
        """
        if not member_name:
            return None
        relative_path = Path(member_name)
        if relative_path.is_absolute():
            return None
        root = Path(os.path.abspath(target_dir))
        destination = Path(os.path.abspath(root / relative_path))
        if destination == root or root not in destination.parents:
            return None
        return destination

    def _stream_to_file(self, source, target_path):
        """Copy a readable stream into ``target_path``, whole or not at all.

        Replaces the read-it-all-then-write pair this module used everywhere:
        the peak memory of an install is now one buffer rather than the size of
        the artifact (issue #240). Still atomic -- a half-written core under
        the final name would be loaded by RetroArch and fail at dlopen.
        """
        target_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = target_path.with_suffix(target_path.suffix + ".part")
        try:
            with open(tmp_path, "wb") as handle:
                shutil.copyfileobj(source, handle, DOWNLOAD_CHUNK_BYTES)
            tmp_path.replace(target_path)
        finally:
            # A copy that failed part-way must not leave its .part behind for
            # the next run to trip over.
            self._discard(tmp_path)
