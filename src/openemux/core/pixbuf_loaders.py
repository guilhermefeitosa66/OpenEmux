"""Build gdk-pixbuf's loader cache on the machine that runs the app.

gdk-pixbuf decodes PNG, JPEG and a few others itself; everything else is a
loader module it discovers through ``loaders.cache``, a text file listing each
module and the formats it handles. For OpenEmux the two that matter are SVG
(librsvg -- the cartridge frames and the app's own artwork) and WebP, which is
what libretro serves cover art as. Without the cache those images decode to
nothing and the card renders blank.

**Why this cannot be a build step.** The cache holds *absolute* paths to the
loader DLLs, so one written where the bundle was built points at a directory
that does not exist on the user's machine. The tool that writes it,
``gdk-pixbuf-query-loaders``, has to dlopen each module, so it is a Windows
binary that cannot run on the Linux host the bundle is cross-built on. Both
roads lead here: it is generated once, on first launch, by the copy of the tool
that ships inside the bundle.

Windows only. The Linux packages get their cache from the distribution, and the
AppImage writes one at build time with a native binary against
``GDK_PIXBUF_MODULEDIR``.
"""

import logging
import os
import subprocess
from pathlib import Path

from openemux.core.platform import IS_WINDOWS, popen_kwargs

logger = logging.getLogger(__name__)

#: Where the bundle keeps its loaders and the cache that indexes them.
LOADERS_SUBDIR = Path("lib") / "gdk-pixbuf-2.0" / "2.10.0" / "loaders"
CACHE_NAME = "loaders.cache"

#: The query tool, inside the bundle.
QUERY_TOOL = Path("bin") / "gdk-pixbuf-query-loaders.exe"

#: How long to let the tool run. It dlopens a dozen small DLLs; if it has not
#: finished by now it is hung, and a hung launcher is worse than a missing
#: format.
TIMEOUT = 30


def ensure_loaders_cache(project_root, environ=None, runner=None):
    """Make ``GDK_PIXBUF_MODULE_FILE`` point at a usable cache.

    Returns the path written, or ``None`` when there was nothing to do or
    nothing that could be done. Never raises: a missing WebP decoder is a
    blank cover, and refusing to start over it would be worse.
    """
    if not IS_WINDOWS:
        return None
    environ = os.environ if environ is None else environ
    root = Path(project_root)
    loaders_dir = root / LOADERS_SUBDIR
    if not loaders_dir.is_dir():
        # Not a bundle -- a source checkout under MSYS2, where the prefix's own
        # cache is already in place and correct.
        return None

    cache_path = loaders_dir.parent / CACHE_NAME
    if _is_current(cache_path, loaders_dir):
        environ["GDK_PIXBUF_MODULE_FILE"] = str(cache_path)
        return cache_path

    tool = root / QUERY_TOOL
    if not tool.is_file():
        logger.warning("gdk-pixbuf: %s is missing; only the built-in image "
                       "formats will decode", tool)
        return None

    contents = _query(tool, loaders_dir, runner)
    if not contents:
        return None

    for target in _candidate_paths(cache_path, environ):
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(contents, encoding="utf-8")
        except OSError as exc:
            # An install the user cannot write to is the ordinary case under
            # Program Files, so try the per-user location before giving up.
            logger.info("gdk-pixbuf: could not write %s (%s)", target, exc)
            continue
        environ["GDK_PIXBUF_MODULE_FILE"] = str(target)
        logger.info("gdk-pixbuf: loader cache written to %s", target)
        return target

    logger.warning("gdk-pixbuf: nowhere to write the loader cache; only the "
                   "built-in image formats will decode")
    return None


def _is_current(cache_path, loaders_dir):
    """Is an existing cache newer than every loader it indexes?

    A bundle updated in place keeps the old cache, which then names modules
    that may have been replaced -- so the mtime comparison, not mere existence.
    """
    try:
        if not cache_path.is_file() or cache_path.stat().st_size == 0:
            return False
        cache_mtime = cache_path.stat().st_mtime
        newest = max(
            (entry.stat().st_mtime for entry in loaders_dir.iterdir()),
            default=0,
        )
    except OSError:
        return False
    return cache_mtime >= newest


def _query(tool, loaders_dir, runner=None):
    """Run the query tool over the bundle's loaders; its stdout is the cache."""
    runner = runner or subprocess.run
    try:
        # GDK_PIXBUF_MODULEDIR is what the tool scans. Passed rather than
        # relying on its built-in default, which is the MSYS2 prefix the
        # package was compiled for.
        env = dict(os.environ, GDK_PIXBUF_MODULEDIR=str(loaders_dir))
        result = runner(
            [str(tool)],
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
            env=env,
            **popen_kwargs(),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("gdk-pixbuf: %s failed to run: %s", tool, exc)
        return None
    if result.returncode != 0:
        logger.warning("gdk-pixbuf: %s exited %s: %s",
                       tool, result.returncode, (result.stderr or "").strip()[:400])
        return None
    contents = result.stdout or ""
    if "LoaderDir" not in contents and '"' not in contents:
        logger.warning("gdk-pixbuf: %s produced nothing usable", tool)
        return None
    return contents


def _candidate_paths(cache_path, environ):
    """Where to try writing, best first: beside the loaders, then per-user."""
    yield cache_path
    local = environ.get("LOCALAPPDATA")
    if local:
        yield Path(local) / "OpenEmux" / CACHE_NAME
