"""Every build hands the working tree back to the developer who started it.

The packaging builds run as root inside a container that bind-mounts the
repository, so everything they write lands as root:root -- and `chown` needs
root, so the host cannot undo it afterwards. Each script used to name the paths
it thought it had created, and each list forgot something different: the
Flatpak build left 2154 root-owned files under .flatpak-builder/ and
.flatpak-build-dir/ that the developer could not even delete, and every format
that embeds the ScreenScraper credential left the *tracked*
src/openemux/core/embedded_credentials.py owned by root.

These run the helper for real against a temporary tree. What they cannot cover
here is the chown itself -- that needs root, and the suite does not have it --
so they check the parts that decide *whether* it happens, which is where the
bugs were.
"""

import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.platform_marks import posix_only

REPO_ROOT = Path(__file__).resolve().parents[1]
HAND_BACK = REPO_ROOT / "packaging/common/hand_back.sh"
BUILD_SCRIPTS = (
    "packaging/appimage/build.sh",
    "packaging/deb/build.sh",
    "packaging/flatpak/build.sh",
    "packaging/rpm/build.sh",
    "packaging/windows/build.sh",
)


def _run(cwd, env=None):
    environment = dict(os.environ)
    environment.pop("HOST_UID", None)
    environment.pop("HOST_GID", None)
    environment.update(env or {})
    return subprocess.run(
        ["sh", str(HAND_BACK)],
        cwd=str(cwd),
        env=environment,
        capture_output=True,
        text=True,
    )


class EveryBuildHandsBackTests(unittest.TestCase):
    """A list of paths is what kept missing things; a trap is what runs."""

    def test_every_build_script_calls_it(self):
        for relative in BUILD_SCRIPTS:
            text = (REPO_ROOT / relative).read_text(encoding="utf-8")
            with self.subTest(script=relative):
                self.assertIn("packaging/common/hand_back.sh", text)

    def test_it_runs_on_every_exit_not_only_a_successful_one(self):
        # As a trailing line it was skipped by exactly the runs that need it
        # most: a build that fails halfway has still written root-owned files.
        for relative in BUILD_SCRIPTS:
            text = (REPO_ROOT / relative).read_text(encoding="utf-8")
            with self.subTest(script=relative):
                trap = next(
                    (
                        line
                        for line in text.splitlines()
                        if line.startswith("trap ") and "hand_back.sh" in line
                    ),
                    None,
                )
                self.assertIsNotNone(trap, f"{relative} calls it outside an EXIT trap")
                self.assertTrue(trap.rstrip().endswith("EXIT"), trap)

    def test_no_script_still_names_paths_by_hand(self):
        # The old `chown -R ... dist AppDir appimage-build` shape. Each copy
        # drifted from what its build actually wrote.
        for relative in BUILD_SCRIPTS:
            text = (REPO_ROOT / relative).read_text(encoding="utf-8")
            with self.subTest(script=relative):
                for line in text.splitlines():
                    if line.lstrip().startswith("#"):
                        continue
                    self.assertNotIn("chown", line, f"{relative}: {line}")


@posix_only(
    "uid/gid ownership and mode bits; the helper only ever runs as root inside "
    "the Linux build container, and there is no Windows build container"
)
class HandBackBehaviourTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tree = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_without_the_host_ids_it_changes_nothing(self):
        # Chowning to a guessed 0:0 would be the very bug this prevents, and
        # `${HOST_UID:-0}` is what the five old copies all did.
        (self.tree / "dist").mkdir()
        artifact = self.tree / "dist" / "openemux.deb"
        artifact.write_text("x")
        artifact.chmod(0o600)

        result = _run(self.tree)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("HOST_UID", result.stderr)
        self.assertEqual(stat.S_IMODE(artifact.stat().st_mode), 0o600)

    def test_the_artifacts_end_up_755(self):
        (self.tree / "dist").mkdir()
        artifact = self.tree / "dist" / "OpenEmux.AppImage"
        artifact.write_text("x")
        artifact.chmod(0o600)

        result = _run(
            self.tree, {"HOST_UID": str(os.getuid()), "HOST_GID": str(os.getgid())}
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(stat.S_IMODE(artifact.stat().st_mode), 0o755)

    def test_nothing_outside_dist_is_made_executable(self):
        # A blanket chmod over the tree would mark every source file
        # executable, which is a different bug from the one being fixed.
        source = self.tree / "app.py"
        source.write_text("x")
        source.chmod(0o644)

        result = _run(
            self.tree, {"HOST_UID": str(os.getuid()), "HOST_GID": str(os.getgid())}
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(stat.S_IMODE(source.stat().st_mode), 0o644)

    def test_a_tree_with_no_dist_yet_is_not_an_error(self):
        # A build that dies before producing anything still runs the trap.
        result = _run(
            self.tree, {"HOST_UID": str(os.getuid()), "HOST_GID": str(os.getgid())}
        )

        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
