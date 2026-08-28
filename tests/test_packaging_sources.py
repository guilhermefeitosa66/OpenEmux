"""Packages carry the sources, not the maintainer's build state (#254).

``stage_tree.sh`` staged with ``cp -r "$ROOT_DIR/src"``, so whatever happened to
be in the working tree ended up in the package. Measured on the shipped
artifacts: ``opt/openemux/src/opemux.egg-info/`` -- a stale directory from a
typo'd project name that no longer exists in the repository at all -- plus
``openemux.egg-info/`` in both the .deb and the .rpm. Both are gitignored and
untracked; ``top_level.txt`` registers a phantom distribution on
``PYTHONPATH=/opt/openemux/src`` that ``importlib.metadata`` reports, and
``SOURCES.txt`` publishes the development tree's file inventory.

These tests run the two shell helpers for real against a fixture tree: what
they exclude is behaviour, not a string in a file.
"""

import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
COPY_TREE = REPO_ROOT / "packaging/common/copy_tree.sh"
ASSERT_SOURCES_ONLY = REPO_ROOT / "packaging/common/assert_sources_only.sh"

#: What a working tree accumulates, and what a package must never carry.
BUILD_STATE = (
    "opemux.egg-info/PKG-INFO",
    "openemux.egg-info/top_level.txt",
    "openemux/__pycache__/main.cpython-312.pyc",
    "openemux/core/__pycache__/config.cpython-312.pyc",
    ".pytest_cache/CACHEDIR.TAG",
    "openemux.egg-link",
)

#: What has to survive.
SOURCES = (
    "openemux/main.py",
    "openemux/ui/style.css",
    "openemux/ui/assets/icons/symbolic/LICENSE",
    "openemux/data/games.db.zip",
)


def _fixture_tree(root):
    for relative in BUILD_STATE + SOURCES:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(relative, encoding="utf-8")
    return root


class CopyTreeLeavesTheBuildStateBehindTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.source = _fixture_tree(self.tmp / "src")
        self.staged = self.tmp / "stage"
        subprocess.run(
            ["sh", str(COPY_TREE), str(self.source), str(self.staged)], check=True
        )

    def tearDown(self):
        self._tmp.cleanup()

    def test_every_source_file_arrives(self):
        for relative in SOURCES:
            with self.subTest(path=relative):
                self.assertTrue((self.staged / "src" / relative).is_file())

    def test_no_build_artifact_arrives(self):
        for relative in BUILD_STATE:
            with self.subTest(path=relative):
                self.assertFalse(
                    (self.staged / "src" / relative).exists(),
                    f"{relative} was copied into the package",
                )

    def test_the_windows_retroarch_is_not_dragged_into_a_linux_package(self):
        # 556 MiB unpacked, gitignored, fetched on demand for the Windows build
        # alone -- and the .7z both of them come out of is bigger still.
        vendors = self.tmp / "vendors"
        (vendors / "RetroArch-Win64").mkdir(parents=True)
        (vendors / "RetroArch-Win64" / "retroarch.exe").write_text("x")
        (vendors / "RetroArch-Linux-x86_64" / "usr" / "bin").mkdir(parents=True)
        (vendors / "RetroArch-Linux-x86_64" / "usr" / "bin" / "retroarch").write_text("x")
        (vendors / ".cache").mkdir()
        (vendors / ".cache" / "win64-RetroArch.7z").write_text("x")
        destination = self.tmp / "vendors-stage"
        subprocess.run(
            ["sh", str(COPY_TREE), str(vendors), str(destination)], check=True
        )
        self.assertTrue(
            (
                destination
                / "vendors"
                / "RetroArch-Linux-x86_64"
                / "usr"
                / "bin"
                / "retroarch"
            ).is_file()
        )
        self.assertFalse((destination / "vendors" / "RetroArch-Win64").exists())
        self.assertFalse((destination / "vendors" / ".cache").exists())

    def test_a_missing_source_directory_is_an_error_not_an_empty_package(self):
        result = subprocess.run(
            ["sh", str(COPY_TREE), str(self.tmp / "nope"), str(self.tmp / "out")],
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)


class AssertSourcesOnlyFailsTheBuildTests(unittest.TestCase):
    """The exclude list is a claim; this is the check on it."""

    def _run(self, *paths):
        return subprocess.run(
            ["sh", str(ASSERT_SOURCES_ONLY), *[str(p) for p in paths]],
            capture_output=True,
            text=True,
        )

    def test_a_clean_tree_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for relative in SOURCES:
                (root / relative).parent.mkdir(parents=True, exist_ok=True)
                (root / relative).write_text("x")
            self.assertEqual(self._run(root).returncode, 0)

    def test_an_egg_info_fails_and_says_which(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "opemux.egg-info").mkdir()
            (root / "opemux.egg-info" / "top_level.txt").write_text("opemux")
            result = self._run(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("opemux.egg-info", result.stderr)

    def test_bytecode_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "__pycache__").mkdir()
            (root / "__pycache__" / "main.cpython-312.pyc").write_text("x")
            self.assertNotEqual(self._run(root).returncode, 0)

    def test_it_refuses_to_pass_when_given_nothing_to_check(self):
        self.assertNotEqual(self._run().returncode, 0)


class EveryFormatStagesTheSameWayTests(unittest.TestCase):
    """One copy helper, so a fix here reaches every package."""

    STAGERS = (
        "packaging/common/stage_tree.sh",
        "packaging/appimage/AppImageBuilder.yml",
        "packaging/flatpak/build.sh",
    )

    def test_none_of_them_copies_the_tree_wholesale(self):
        for relative_path in self.STAGERS:
            text = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
            with self.subTest(file=relative_path):
                self.assertIn(
                    "copy_tree.sh",
                    text,
                    f"{relative_path} does not stage through copy_tree.sh",
                )
                for wholesale in ("cp -r src", "cp -r vendors", 'cp -r "$ROOT_DIR/src"'):
                    self.assertNotIn(
                        wholesale,
                        text,
                        f"{relative_path} still copies the working tree wholesale",
                    )

    def test_the_native_and_appimage_stages_are_checked_afterwards(self):
        for relative_path in self.STAGERS:
            text = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
            with self.subTest(file=relative_path):
                self.assertIn("assert_sources_only.sh", text)

    def test_the_rpm_source_tarball_excludes_the_same_artifacts(self):
        # The tarball is the SRPM's input, so it has to be as clean as the
        # staged tree that comes out of it.
        text = (REPO_ROOT / "packaging/rpm/build.sh").read_text(encoding="utf-8")
        for pattern in ("__pycache__", "*.pyc", "*.egg-info"):
            with self.subTest(pattern=pattern):
                self.assertIn(f"--exclude='{pattern}'", text)


if __name__ == "__main__":
    unittest.main()
