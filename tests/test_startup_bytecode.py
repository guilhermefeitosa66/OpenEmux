"""A packaged install must not recompile itself on every launch.

The app is installed somewhere the user cannot write -- ``/opt/openemux`` for
the .deb and .rpm -- so CPython's attempt to put ``__pycache__`` beside the
sources fails and it falls back, silently, to compiling all ~36k lines in
memory. Every launch. ``main._redirect_bytecode_cache`` gives that work a
writable home; the formats that pin their interpreter ship the bytecode
instead, and must therefore *not* be redirected (issue #364).

The second half of the file guards the other side of the same launch: modules
that cost real time to import and that starting the app does not need.
"""

import importlib.util
import os
import subprocess
import sys
import tempfile
import textwrap
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


PROBE = textwrap.dedent(
    """
    import json, sys
    import openemux.app  # noqa: F401
    print(json.dumps(sorted(m for m in sys.modules if m in {
        "urllib.request", "http.client", "Xlib.display",
    })))
    """
)


class StartupImportsTests(unittest.TestCase):
    """Modules the app pays for at import time and does not use to start.

    ``urllib.request`` brings ``http.client`` and ``ssl`` with it and is only
    ever needed by a sync, an update check or a sign-in; ``Xlib.display``
    brings the X protocol machinery and is only needed by a launch that embeds
    a game window. Between them they cost ~18 ms of a ~167 ms start-up, on
    every launch, for work the overwhelming majority of launches never do.

    ``asyncio`` and ``ssl`` are deliberately not on the list: PyGObject's own
    ``gi/overrides/Gio.py`` imports asyncio at module scope, and it arrives
    with ``Gio`` no matter what this app does.
    """

    def test_starting_the_app_imports_no_network_or_x_protocol_stack(self):
        env = dict(os.environ)
        env["PYTHONPATH"] = str(REPO_ROOT / "src")
        result = subprocess.run(
            [sys.executable, "-c", PROBE],
            capture_output=True, text=True, env=env, timeout=180, check=False,
        )
        if result.returncode != 0:
            self.skipTest(f"openemux.app is not importable here: {result.stderr.strip()[-300:]}")
        self.assertEqual(
            result.stdout.strip(),
            "[]",
            "these are imported at start-up and should be deferred to their first use",
        )


if __name__ == "__main__":
    unittest.main()
