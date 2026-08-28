"""A packaged install must not recompile itself on every launch.

The app is installed somewhere the user cannot write -- ``/opt/openemux`` for
the .deb and .rpm -- so CPython's attempt to put ``__pycache__`` beside the
sources fails and it falls back, silently, to compiling all ~36k lines in
memory. Every launch. ``main._redirect_bytecode_cache`` gives that work a
writable home; the formats that pin their interpreter ship the bytecode
instead, and must therefore *not* be redirected (issue #364).
"""

import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from openemux import main
from openemux.core import paths

REPO_ROOT = Path(__file__).resolve().parents[1]


class BytecodeCacheDirTests(unittest.TestCase):
    def test_it_follows_xdg_cache_home(self):
        with mock.patch.dict(os.environ, {"XDG_CACHE_HOME": "/somewhere/cache"}):
            with mock.patch.object(paths, "IS_WINDOWS", False):
                self.assertEqual(
                    paths.bytecode_cache_dir(), Path("/somewhere/cache/openemux/bytecode")
                )

    def test_without_xdg_it_is_under_dot_cache(self):
        env = {k: v for k, v in os.environ.items() if k != "XDG_CACHE_HOME"}
        with mock.patch.dict(os.environ, env, clear=True):
            with mock.patch.object(paths, "IS_WINDOWS", False):
                self.assertEqual(
                    paths.bytecode_cache_dir(), Path.home() / ".cache/openemux/bytecode"
                )

    def test_on_windows_it_is_under_local_appdata(self):
        with mock.patch.object(paths, "IS_WINDOWS", True):
            with mock.patch.dict(os.environ, {"LOCALAPPDATA": r"C:\Users\p\AppData\Local"}):
                self.assertEqual(
                    paths.bytecode_cache_dir(),
                    Path(r"C:\Users\p\AppData\Local") / "openemux" / "bytecode",
                )

    def test_it_is_never_the_config_dir(self):
        # Derived data, safe to delete, and not something to back up next to
        # the user's library and input profiles.
        self.assertNotIn(paths.default_config_dir(), paths.bytecode_cache_dir().parents)


class RedirectBytecodeCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.package = Path(self.tmp.name) / "openemux"
        self.package.mkdir()
        (self.package / "main.py").write_text("", encoding="utf-8")
        self.cache = Path(self.tmp.name) / "cache"

        # Restore whatever the interpreter running the tests had.
        before_prefix = sys.pycache_prefix
        before_flag = sys.dont_write_bytecode
        self.addCleanup(lambda: setattr(sys, "pycache_prefix", before_prefix))
        self.addCleanup(lambda: setattr(sys, "dont_write_bytecode", before_flag))
        sys.pycache_prefix = None
        sys.dont_write_bytecode = False

        patcher = mock.patch.object(main, "bytecode_cache_dir", lambda: self.cache)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _make_read_only(self):
        os.chmod(self.package, 0o500)
        self.addCleanup(os.chmod, self.package, 0o700)

    def test_a_read_only_install_gets_a_writable_cache(self):
        self._make_read_only()
        main._redirect_bytecode_cache(self.package)
        self.assertEqual(sys.pycache_prefix, str(self.cache))
        self.assertTrue(self.cache.is_dir())

    def test_a_writable_checkout_is_left_alone(self):
        # A source checkout, `make run` and the devbox cache beside the
        # sources, the way every Python developer expects.
        main._redirect_bytecode_cache(self.package)
        self.assertIsNone(sys.pycache_prefix)
        self.assertFalse(self.cache.exists())

    def test_an_install_that_ships_its_own_bytecode_is_left_alone(self):
        # The AppImage, the Flatpak and the Windows bundle pin their
        # interpreter and compile ahead of time. Redirecting would hide it.
        cached = Path(importlib.util.cache_from_source(str(self.package / "main.py")))
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_bytes(b"")
        self._make_read_only()
        main._redirect_bytecode_cache(self.package)
        self.assertIsNone(sys.pycache_prefix)

    def test_the_users_own_choice_wins(self):
        self._make_read_only()
        sys.pycache_prefix = "/somewhere/the/user/picked"
        main._redirect_bytecode_cache(self.package)
        self.assertEqual(sys.pycache_prefix, "/somewhere/the/user/picked")

    def test_dont_write_bytecode_is_honoured(self):
        self._make_read_only()
        sys.dont_write_bytecode = True
        main._redirect_bytecode_cache(self.package)
        self.assertIsNone(sys.pycache_prefix)

    def test_a_cache_dir_that_cannot_be_created_is_not_fatal(self):
        # A read-only home or a full disk. Recompiling every launch is slow;
        # refusing to start over a *cache* would be worse.
        self._make_read_only()
        with mock.patch.object(Path, "mkdir", side_effect=OSError("read-only")):
            main._redirect_bytecode_cache(self.package)
        self.assertIsNone(sys.pycache_prefix)

    def test_prepare_process_redirects_before_anything_imports(self):
        # Every import that lands before the redirect is one more module the
        # packaged install recompiles on every launch, so this call has to be
        # first in prepare_process.
        source = Path(main.__file__).read_text(encoding="utf-8")
        body = source.split("    _prepared = True", 1)[1]
        calls = [line.strip() for line in body.splitlines() if line.startswith("    _")]
        self.assertEqual(calls[0], "_redirect_bytecode_cache()")


if __name__ == "__main__":
    unittest.main()
