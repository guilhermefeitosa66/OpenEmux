"""scripts/run_tests.py: the test run that stays off the developer's screen (issue #528)."""

import importlib.util
import io
import unittest
from pathlib import Path
import unittest.mock
from unittest.mock import Mock

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "run_tests.py"


def load_launcher():
    """scripts/run_tests.py, which is not importable as a package."""
    spec = importlib.util.spec_from_file_location("run_tests", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


launcher = load_launcher()
DESKTOP = {"WAYLAND_DISPLAY": "wayland-0", "XDG_SESSION_TYPE": "wayland",
           "PYTHONPATH": "src"}


def found(name):
    return f"/usr/bin/{name}"


def not_found(name):
    return None


class DecideTests(unittest.TestCase):
    def test_other_platforms_run_as_they_are(self):
        self.assertEqual(launcher.decide(DESKTOP, "win32", found), "direct")
        self.assertEqual(launcher.decide(DESKTOP, "darwin", found), "direct")

    def test_the_opt_in_runs_on_the_desktop(self):
        env = dict(DESKTOP, OPENEMUX_TESTS_ON_DESKTOP="1")
        self.assertEqual(launcher.decide(env, "linux", found), "direct")

    def test_an_already_private_display_is_used_as_it_is(self):
        env = dict(DESKTOP, OPENEMUX_TESTS_PRIVATE_DISPLAY="1")
        self.assertEqual(launcher.decide(env, "linux", found), "direct")

    def test_linux_goes_to_xvfb_when_it_is_installed(self):
        which = Mock(side_effect=found)
        self.assertEqual(launcher.decide(DESKTOP, "linux", which), "xvfb")
        which.assert_called_once_with("xvfb-run")

    def test_linux_without_xvfb_is_missing(self):
        self.assertEqual(launcher.decide(DESKTOP, "linux", not_found), "missing")

    def test_an_opt_in_other_than_1_is_not_an_opt_in(self):
        env = dict(DESKTOP, OPENEMUX_TESTS_ON_DESKTOP="0")
        self.assertEqual(launcher.decide(env, "linux", found), "xvfb")


class HeadlessEnvTests(unittest.TestCase):
    def test_every_route_to_the_session_is_closed(self):
        env = launcher.headless_env(DESKTOP)
        self.assertNotIn("WAYLAND_DISPLAY", env)
        self.assertEqual(env["GDK_BACKEND"], "x11")
        self.assertEqual(env["OPENEMUX_TESTS_PRIVATE_DISPLAY"], "1")
        self.assertEqual(env["GDK_DEBUG"], "no-portals")
        self.assertEqual(env["GTK_USE_PORTAL"], "0")
        self.assertEqual(env["PYTHONPATH"], "src")

    def test_the_caller_environment_is_not_touched(self):
        original = dict(DESKTOP)
        launcher.headless_env(original)
        self.assertEqual(original, DESKTOP)

    def test_existing_gdk_debug_flags_are_kept(self):
        env = launcher.headless_env({"GDK_DEBUG": "events,,misc"})
        self.assertEqual(env["GDK_DEBUG"], "events,misc,no-portals")

    def test_no_portals_is_not_added_twice(self):
        env = launcher.headless_env({"GDK_DEBUG": "no-portals"})
        self.assertEqual(env["GDK_DEBUG"], "no-portals")

    def test_works_without_a_wayland_display(self):
        self.assertNotIn("WAYLAND_DISPLAY", launcher.headless_env({}))


class MainTests(unittest.TestCase):
    CMD = ["python", "-m", "unittest", "discover", "-s", "tests"]

    def run_main(self, env, platform="linux", which=found, argv=None):
        self.execvpe = Mock(return_value=0)
        self.call = Mock(return_value=5)
        self.stderr = io.StringIO()
        return launcher.main(
            argv=self.CMD if argv is None else argv, env=env, platform=platform,
            which=which, execvpe=self.execvpe, call=self.call, stderr=self.stderr,
        )

    def test_xvfb_replaces_the_process_under_xvfb_run(self):
        self.run_main(DESKTOP)
        self.execvpe.assert_called_once()
        file, argv, env = self.execvpe.call_args.args
        self.assertEqual(file, "xvfb-run")
        self.assertEqual(argv, ["xvfb-run", "-a", *self.CMD])
        self.assertEqual(env, launcher.headless_env(DESKTOP))
        self.call.assert_not_called()
        self.assertEqual(self.stderr.getvalue(), "")

    def test_missing_xvfb_says_so_once_and_runs_the_command(self):
        code = self.run_main(DESKTOP, which=not_found)
        self.assertEqual(code, 5)
        self.call.assert_called_once_with(self.CMD, env=DESKTOP)
        self.execvpe.assert_not_called()
        message = self.stderr.getvalue()
        self.assertEqual(message.count("Xvfb not found"), 1)
        for install in ("make install-sys-deps", "xorg-x11-server-Xvfb",
                        "xorg-server-xvfb", "OPENEMUX_TESTS_ON_DESKTOP=1"):
            self.assertIn(install, message)

    def test_direct_runs_the_command_unchanged(self):
        code = self.run_main(DESKTOP, platform="win32")
        self.assertEqual(code, 5)
        self.call.assert_called_once_with(self.CMD, env=DESKTOP)
        self.assertEqual(self.stderr.getvalue(), "")

    def test_no_command_is_a_usage_error(self):
        self.assertEqual(self.run_main(DESKTOP, argv=[]), 2)
        self.assertIn("usage:", self.stderr.getvalue())
        self.call.assert_not_called()
        self.execvpe.assert_not_called()

    def test_defaults_come_from_the_process(self):
        call = Mock(return_value=0)
        with unittest.mock.patch.object(launcher.sys, "argv", ["run_tests.py", "true"]), \
                unittest.mock.patch.object(launcher.sys, "platform", "win32"), \
                unittest.mock.patch.dict(launcher.os.environ, {"MARK": "x"}):
            self.assertEqual(launcher.main(call=call), 0)
        argv, = call.call_args.args
        self.assertEqual(argv, ["true"])
        self.assertEqual(call.call_args.kwargs["env"]["MARK"], "x")


if __name__ == "__main__":
    unittest.main()
