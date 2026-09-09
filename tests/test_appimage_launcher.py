"""The AppImage entry point, run for real against a stand-in AppDir.

Two bugs, one shape: the bundle's environment reached something that is not
part of the bundle.

*The host's shell.* ``openemux-run`` is a ``#!/bin/sh`` script inside the
AppDir, so the kernel loads the *host's* ``/bin/sh`` under whatever
``LD_LIBRARY_PATH`` the exec carries -- and AppRun points that at Ubuntu
noble's libraries. On Arch, whose ``/bin/sh`` is a bash built against
readline 8.3, the bundled readline 8.2 was resolved instead and every launch
died before a single line of the script ran::

    /bin/sh: symbol lookup error: /bin/sh: undefined symbol: rl_print_keybinding

*The TLS trust store.* The bundled OpenSSL is Ubuntu's, compiled with
``OPENSSLDIR=/usr/lib/ssl`` -- a path that exists only on Debian and its
derivatives. Everywhere else the store loaded zero certificates, so every
HTTPS request failed with ``CERTIFICATE_VERIFY_FAILED``: first boot could not
download a single core and stopped at *"Initial setup incomplete (step:
retroarch_download_all_cores)"*, and cover sync, ScreenScraper and the update
check were dead with it.

Run rather than read: both fixes are about what one process hands the next,
which a grep over the source cannot see.
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.platform_marks import linux_only

REPO_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER_C = REPO_ROOT / "packaging" / "appimage" / "openemux-launcher.c"
RUN_SH = REPO_ROOT / "packaging" / "appimage" / "openemux-run.sh"

#: appimage-builder's exec hook, named in LD_PRELOAD with no directory, so the
#: loader resolves it through LD_LIBRARY_PATH. It is the reason the launcher
#: narrows that path instead of clearing it.
HOOKS_SO = "libapprun_hooks.so"

#: Where the CA bundles the run script looks for actually live on this
#: machine. Empty on a host that keeps its trust store somewhere else, which
#: is a real answer rather than a broken test.
HOST_CA_BUNDLES = [
    path
    for path in (
        "/etc/ssl/certs/ca-certificates.crt",
        "/etc/pki/tls/certs/ca-bundle.crt",
        "/etc/ssl/ca-bundle.pem",
        "/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem",
        "/etc/ssl/cert.pem",
    )
    if os.access(path, os.R_OK)
]


def _env_dump_script(marker):
    """A stand-in executable that prints its environment and stops."""
    return f"#!/bin/sh\necho '{marker}'\nenv\n"


def _write_exec(path, contents):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8")
    path.chmod(0o755)


def _parse_env(output):
    seen = {}
    for line in output.splitlines():
        name, sep, value = line.partition("=")
        if sep:
            seen[name] = value
    return seen


@linux_only("the AppImage entry point and its ELF loader environment")
@unittest.skipUnless(shutil.which("gcc"), "gcc is needed to build the launcher")
class LauncherNarrowsTheLibraryPathTests(unittest.TestCase):
    """``openemux-launcher`` hands the shell a path that cannot poison it."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.binary = Path(cls._tmp.name) / "openemux-launcher"
        subprocess.run(
            ["gcc", "-Wall", "-Werror", str(LAUNCHER_C), "-O1", "-o", str(cls.binary)],
            check=True,
            capture_output=True,
        )

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def _run(self, library_path_dirs, hooks_in):
        """Run the launcher over a stand-in AppDir; return the child's env."""
        appdir = Path(tempfile.mkdtemp(dir=self._tmp.name))
        self.addCleanup(shutil.rmtree, appdir, True)
        for name in library_path_dirs:
            (appdir / name).mkdir(parents=True, exist_ok=True)
        for name in hooks_in:
            (appdir / name / HOOKS_SO).write_bytes(b"")
        _write_exec(appdir / "usr" / "bin" / "openemux-run", _env_dump_script("ran"))

        library_path = ":".join(str(appdir / name) for name in library_path_dirs)
        result = subprocess.run(
            [str(self.binary)],
            check=True,
            capture_output=True,
            text=True,
            env={
                "APPDIR": str(appdir),
                "PATH": "/usr/bin:/bin",
                "LD_LIBRARY_PATH": library_path,
                "LD_PRELOAD": HOOKS_SO,
            },
        )
        self.assertIn("ran", result.stdout)
        return appdir, _parse_env(result.stdout)

    def test_the_shell_keeps_only_the_directory_holding_the_hook(self):
        # The bundle's own library directory -- the one with the readline that
        # kills the host shell -- must not survive; the hook's must, or
        # LD_PRELOAD resolves to nothing and the *next* exec gets the host's
        # libc ("__pointer_chk_guard, version GLIBC_PRIVATE").
        appdir, env = self._run(
            ["usr/lib/x86_64-linux-gnu", "lib/x86_64"], hooks_in=["lib/x86_64"]
        )

        self.assertEqual(env["LD_LIBRARY_PATH"], str(appdir / "lib/x86_64"))
        self.assertEqual(env["LD_PRELOAD"], HOOKS_SO)

    def test_the_full_path_is_parked_for_the_script_to_restore(self):
        appdir, env = self._run(
            ["usr/lib/x86_64-linux-gnu", "lib/x86_64"], hooks_in=["lib/x86_64"]
        )

        self.assertEqual(
            env["APPDIR_SHELL_LD_LIBRARY_PATH"],
            f"{appdir / 'usr/lib/x86_64-linux-gnu'}:{appdir / 'lib/x86_64'}",
        )

    def test_a_path_with_no_hook_at_all_is_dropped_entirely(self):
        _, env = self._run(["usr/lib/x86_64-linux-gnu"], hooks_in=[])

        self.assertNotIn("LD_LIBRARY_PATH", env)


@linux_only("the AppImage entry point and the FHS CA-bundle locations")
class RunScriptTests(unittest.TestCase):
    """``openemux-run`` puts back what the launcher parked, and adds CAs."""

    def _run(self, **extra_env):
        appdir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, appdir, True)
        _write_exec(appdir / "usr" / "bin" / "openemux-run", RUN_SH.read_text())
        # The script execs this as the interpreter; a stand-in that prints its
        # environment is what makes the hand-over observable.
        _write_exec(appdir / "usr" / "bin" / "python3", _env_dump_script("python"))
        (appdir / "usr" / "lib" / "openemux" / "src" / "openemux").mkdir(parents=True)
        (appdir / "usr" / "lib" / "openemux" / "src" / "openemux" / "main.py").touch()

        env = {"APPDIR": str(appdir), "PATH": "/usr/bin:/bin"}
        env.update(extra_env)
        result = subprocess.run(
            [str(appdir / "usr" / "bin" / "openemux-run")],
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )
        self.assertIn("python", result.stdout)
        return appdir, _parse_env(result.stdout)

    def test_the_parked_library_path_is_restored_before_python(self):
        # Restored, and the parking variable cleared: the interpreter is the
        # one process in the chain that does need the bundle's libraries.
        _, env = self._run(
            APPDIR_SHELL_LD_LIBRARY_PATH="/bundle/lib:/bundle/usr/lib",
            LD_LIBRARY_PATH="/only/the/hook",
        )

        self.assertEqual(env["LD_LIBRARY_PATH"], "/bundle/lib:/bundle/usr/lib")
        self.assertNotIn("APPDIR_SHELL_LD_LIBRARY_PATH", env)

    def test_nothing_parked_leaves_the_library_path_alone(self):
        # The script also runs when the launcher did not (a hand-run bundle,
        # an older AppRun): it must not invent a value.
        _, env = self._run(LD_LIBRARY_PATH="/whatever/the/session/had")

        self.assertEqual(env["LD_LIBRARY_PATH"], "/whatever/the/session/had")

    @unittest.skipUnless(HOST_CA_BUNDLES, "this host keeps no CA bundle we look for")
    def test_the_host_ca_bundle_is_handed_to_the_bundled_openssl(self):
        _, env = self._run()

        self.assertEqual(env.get("SSL_CERT_FILE"), HOST_CA_BUNDLES[0])

    def test_a_ca_bundle_the_user_chose_wins(self):
        _, env = self._run(SSL_CERT_FILE="/home/me/corporate-roots.pem")

        self.assertEqual(env["SSL_CERT_FILE"], "/home/me/corporate-roots.pem")

    def test_a_ca_directory_the_user_chose_is_not_overridden_either(self):
        # SSL_CERT_DIR alone is a complete answer to OpenSSL, so setting
        # SSL_CERT_FILE beside it would silently take precedence over it.
        _, env = self._run(SSL_CERT_DIR="/home/me/roots.d")

        self.assertEqual(env["SSL_CERT_DIR"], "/home/me/roots.d")
        self.assertNotIn("SSL_CERT_FILE", env)


if __name__ == "__main__":
    unittest.main()
