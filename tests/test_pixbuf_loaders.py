"""gdk-pixbuf's loader cache, written on the machine that runs the app (#118).

The cache names loader modules by absolute path and is produced by a tool that
has to dlopen them, so it can be written neither on the Linux host that
cross-builds the Windows bundle nor at any other point before first launch.
These tests drive that logic on Linux with the platform flag and the subprocess
both faked -- the decision-making is what can go wrong, and it is portable.
"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from openemux.core import pixbuf_loaders as pl


class _Result:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


CACHE_TEXT = '# GdkPixbuf Image Loader Modules file\n"C:/x/loaders/pixbufloader_svg.dll"\n"svg" 6 "gdk-pixbuf" "SVG"\n'


def _bundle(tmp, with_tool=True, loaders=("pixbufloader_svg.dll",)):
    root = Path(tmp)
    loaders_dir = root / pl.LOADERS_SUBDIR
    loaders_dir.mkdir(parents=True)
    for name in loaders:
        (loaders_dir / name).write_bytes(b"MZ")
    if with_tool:
        tool = root / pl.QUERY_TOOL
        tool.parent.mkdir(parents=True, exist_ok=True)
        tool.write_bytes(b"MZ")
    return root, loaders_dir


class NotOnLinuxTests(unittest.TestCase):
    def test_linux_is_left_entirely_alone(self):
        # The distribution packages get their cache from the distribution, and
        # the AppImage writes one at build time with a native binary.
        with TemporaryDirectory() as tmp:
            _bundle(tmp)
            env = {}
            self.assertIsNone(pl.ensure_loaders_cache(tmp, environ=env))
            self.assertEqual(env, {})


@patch.object(pl, "IS_WINDOWS", True)
class CacheWritingTests(unittest.TestCase):
    def test_the_cache_is_written_beside_the_loaders(self):
        with TemporaryDirectory() as tmp:
            root, loaders_dir = _bundle(tmp)
            env = {}
            written = pl.ensure_loaders_cache(
                root, environ=env, runner=lambda *a, **k: _Result(stdout=CACHE_TEXT)
            )
            self.assertEqual(written, loaders_dir.parent / "loaders.cache")
            self.assertEqual(written.read_text(encoding="utf-8"), CACHE_TEXT)
            self.assertEqual(env["GDK_PIXBUF_MODULE_FILE"], str(written))

    def test_an_unwritable_install_falls_back_to_the_user(self):
        # Program Files is read-only for a standard user, and a blank cover is
        # not the right answer to that.
        with TemporaryDirectory() as tmp, TemporaryDirectory() as home:
            root, loaders_dir = _bundle(tmp)
            env = {"LOCALAPPDATA": home}
            real_write = Path.write_text

            def _refuse(self, *args, **kwargs):
                if self.parent == loaders_dir.parent:
                    raise PermissionError("read-only")
                return real_write(self, *args, **kwargs)

            with patch.object(Path, "write_text", _refuse):
                written = pl.ensure_loaders_cache(
                    root, environ=env, runner=lambda *a, **k: _Result(stdout=CACHE_TEXT)
                )
            self.assertEqual(written, Path(home) / "OpenEmux" / "loaders.cache")
            self.assertEqual(env["GDK_PIXBUF_MODULE_FILE"], str(written))

    def test_a_current_cache_is_not_rebuilt(self):
        with TemporaryDirectory() as tmp:
            root, loaders_dir = _bundle(tmp)
            cache = loaders_dir.parent / "loaders.cache"
            cache.write_text(CACHE_TEXT, encoding="utf-8")
            calls = []
            env = {}
            written = pl.ensure_loaders_cache(
                root, environ=env, runner=lambda *a, **k: calls.append(a) or _Result()
            )
            self.assertEqual(written, cache)
            self.assertEqual(calls, [], "the tool ran for a cache that was already good")
            self.assertEqual(env["GDK_PIXBUF_MODULE_FILE"], str(cache))

    def test_a_cache_older_than_its_loaders_is_rebuilt(self):
        # A bundle updated in place keeps the old cache, which then names
        # modules that were replaced under it.
        import os

        with TemporaryDirectory() as tmp:
            root, loaders_dir = _bundle(tmp)
            cache = loaders_dir.parent / "loaders.cache"
            cache.write_text("stale", encoding="utf-8")
            os.utime(cache, (1_000_000, 1_000_000))
            written = pl.ensure_loaders_cache(
                root, environ={}, runner=lambda *a, **k: _Result(stdout=CACHE_TEXT)
            )
            self.assertEqual(written.read_text(encoding="utf-8"), CACHE_TEXT)

    def test_an_empty_cache_is_rebuilt(self):
        with TemporaryDirectory() as tmp:
            root, loaders_dir = _bundle(tmp)
            (loaders_dir.parent / "loaders.cache").write_text("", encoding="utf-8")
            written = pl.ensure_loaders_cache(
                root, environ={}, runner=lambda *a, **k: _Result(stdout=CACHE_TEXT)
            )
            self.assertEqual(written.read_text(encoding="utf-8"), CACHE_TEXT)


@patch.object(pl, "IS_WINDOWS", True)
class DegradationTests(unittest.TestCase):
    """Every failure here costs a WebP cover, not the launch."""

    def test_a_source_checkout_is_not_a_bundle(self):
        with TemporaryDirectory() as tmp:
            env = {}
            self.assertIsNone(pl.ensure_loaders_cache(tmp, environ=env))
            self.assertNotIn("GDK_PIXBUF_MODULE_FILE", env)

    def test_a_missing_tool_is_reported_not_raised(self):
        with TemporaryDirectory() as tmp:
            root, _ = _bundle(tmp, with_tool=False)
            with self.assertLogs("openemux.core.pixbuf_loaders", level="WARNING"):
                self.assertIsNone(pl.ensure_loaders_cache(root, environ={}))

    def test_a_tool_that_fails_is_reported_not_raised(self):
        with TemporaryDirectory() as tmp:
            root, _ = _bundle(tmp)
            with self.assertLogs("openemux.core.pixbuf_loaders", level="WARNING"):
                self.assertIsNone(pl.ensure_loaders_cache(
                    root, environ={},
                    runner=lambda *a, **k: _Result(returncode=1, stderr="boom"),
                ))

    def test_a_tool_that_cannot_be_started_is_reported_not_raised(self):
        with TemporaryDirectory() as tmp:
            root, _ = _bundle(tmp)

            def _explode(*args, **kwargs):
                raise OSError("not executable")

            with self.assertLogs("openemux.core.pixbuf_loaders", level="WARNING"):
                self.assertIsNone(
                    pl.ensure_loaders_cache(root, environ={}, runner=_explode)
                )

    def test_empty_output_is_not_written_as_a_cache(self):
        with TemporaryDirectory() as tmp:
            root, loaders_dir = _bundle(tmp)
            with self.assertLogs("openemux.core.pixbuf_loaders", level="WARNING"):
                self.assertIsNone(pl.ensure_loaders_cache(
                    root, environ={}, runner=lambda *a, **k: _Result(stdout="")
                ))
            self.assertFalse((loaders_dir.parent / "loaders.cache").exists())

    def test_nowhere_to_write_is_reported_not_raised(self):
        with TemporaryDirectory() as tmp:
            root, _ = _bundle(tmp)
            with patch.object(Path, "write_text",
                              side_effect=PermissionError("read-only")):
                with self.assertLogs("openemux.core.pixbuf_loaders", level="WARNING"):
                    self.assertIsNone(pl.ensure_loaders_cache(root, environ={}))


class QueryTests(unittest.TestCase):
    def test_the_tool_is_pointed_at_the_bundles_own_loaders(self):
        # Its built-in default is the MSYS2 prefix it was compiled for, which
        # is a path on the build machine and nowhere else.
        with TemporaryDirectory() as tmp:
            root, loaders_dir = _bundle(tmp)
            seen = {}

            def _runner(argv, **kwargs):
                seen["argv"] = argv
                seen["moduledir"] = kwargs["env"]["GDK_PIXBUF_MODULEDIR"]
                return _Result(stdout=CACHE_TEXT)

            with patch.object(pl, "IS_WINDOWS", True):
                pl.ensure_loaders_cache(root, environ={}, runner=_runner)
            self.assertEqual(seen["argv"], [str(root / pl.QUERY_TOOL)])
            self.assertEqual(seen["moduledir"], str(loaders_dir))


if __name__ == "__main__":
    unittest.main()
