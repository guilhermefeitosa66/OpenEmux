"""Importing the app's modules must not touch the developer's home directory.

`tests/test_desktop_integration.py` imports one helper out of `openemux.main`,
which used to be enough to run five bare module-level calls: the legacy config
directory was **migrated** -- real user data, moved by running the tests -- the
real config was read, the root logger was pointed at a FileHandler on
`~/.openemux/runtime/openemux_startup.log` (a file that had passed 260,000
lines, interleaving test output with genuine diagnostics), and `sys.excepthook`
and `threading.excepthook` were replaced for the whole process (issue #244).

The check runs in a subprocess with HOME redirected, so it fails on the
symptom -- a file written where none should be -- rather than on the shape of
the code.
"""

import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

PROBE = textwrap.dedent(
    """
    import json, logging, sys, threading
    before_hook = sys.excepthook
    before_thread_hook = threading.excepthook

    import openemux.main  # noqa: F401

    print(json.dumps({
        "root_handlers": len(logging.getLogger().handlers),
        "excepthook_replaced": sys.excepthook is not before_hook,
        "thread_excepthook_replaced": threading.excepthook is not before_thread_hook,
    }))
    """
)


def _import_main_under_a_throwaway_home(home):
    env = {
        "HOME": str(home),
        "PATH": "/usr/bin:/bin",
        "PYTHONPATH": str(REPO_ROOT / "src"),
        # No display: importing main must not need one either.
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    return subprocess.run(
        [sys.executable, "-c", PROBE],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
        check=False,
    )


class ImportingMainWritesNothingTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.result = _import_main_under_a_throwaway_home(self.home)
        if self.result.returncode != 0:
            self.fail(f"importing openemux.main failed:\n{self.result.stderr}")
        self.report = __import__("json").loads(self.result.stdout.strip().splitlines()[-1])

    def test_no_config_directory_is_created(self):
        # migrate_legacy_config_dir() ran at import; on a machine with a legacy
        # ~/.opemux it moved real user data as a side effect of `make test`.
        self.assertEqual(
            sorted(p.name for p in self.home.iterdir()),
            [],
            "importing openemux.main wrote into HOME",
        )

    def test_the_root_logger_is_left_alone(self):
        # configure_startup_logging() used logging.basicConfig(force=True), so
        # every INFO line the app logs -- hundreds per suite run -- went to the
        # test output and to the real startup log.
        self.assertEqual(self.report["root_handlers"], 0)

    def test_the_crash_handlers_are_left_alone(self):
        self.assertFalse(self.report["excepthook_replaced"])
        self.assertFalse(self.report["thread_excepthook_replaced"])


class TheGtkStackIsNotImportedEitherTests(unittest.TestCase):
    """main imports no GTK: `from gi.repository import Gtk` opens the display."""

    def test_importing_main_does_not_bring_up_gtk(self):
        probe = textwrap.dedent(
            """
            import sys
            import openemux.main  # noqa: F401
            print("gi.repository.Gtk" in sys.modules)
            """
        )
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [sys.executable, "-c", probe],
                capture_output=True,
                text=True,
                env={
                    "HOME": tmp,
                    "PATH": "/usr/bin:/bin",
                    "PYTHONPATH": str(REPO_ROOT / "src"),
                    "PYTHONDONTWRITEBYTECODE": "1",
                },
                timeout=120,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip().splitlines()[-1], "False")


class PrepareProcessRunsOnceTests(unittest.TestCase):
    """configure_startup_logging() uses force=True, so a second call re-does it."""

    def test_a_second_call_is_a_no_op(self):
        import openemux.main as main

        calls = []
        original = {
            name: getattr(main, name)
            for name in (
                "_configure_gtk_renderer",
                "migrate_legacy_config_dir",
                "_configure_game_window_backend",
                "configure_startup_logging",
                "_ensure_gtk_typelibs",
            )
        }
        was_prepared = main._prepared
        try:
            for name in original:
                setattr(main, name, lambda _n=name: calls.append(_n))
            main._prepared = False
            main.prepare_process()
            main.prepare_process()
        finally:
            for name, func in original.items():
                setattr(main, name, func)
            main._prepared = was_prepared
        self.assertEqual(len(calls), len(original))


if __name__ == "__main__":
    unittest.main()
