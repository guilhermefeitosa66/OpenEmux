"""A release has to be reproducible, and its build no more exposed than it needs (#255).

Five independent gaps, none of which a user could see: the AppImage's version
was hard-coded and never checked, the Docker bases were floating tags, the
AppImage fetched Ubuntu packages *and their signing key* over plain HTTP, its
Python dependencies were version-pinned but hash-free, and two of the builds
ran the container ``--privileged`` with the repository bind-mounted and the
ScreenScraper credential in the environment.

What can be checked from here is checked from here; the rest is asserted by the
builds themselves, which is noted per test.
"""

import re
import unittest
from pathlib import Path

from openemux import __version__

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCKERFILES = sorted((REPO_ROOT / "packaging/docker").glob("*.Dockerfile"))


class TheVersionIsTheSameEverywhereTests(unittest.TestCase):
    """src/openemux/__init__.py is the source of truth for all four bumps."""

    def test_the_appimage_recipe_carries_the_version_being_built(self):
        # The one place the version is duplicated: the .deb, .rpm and Flatpak
        # all read __init__.py at build time. A forgotten bump produced
        # OpenEmux-<old>-x86_64.AppImage beside correctly versioned siblings,
        # and it reached dist/, SHA256SUMS and the GitHub release with every
        # check passing.
        recipe = (REPO_ROOT / "packaging/appimage/AppImageBuilder.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn(f'version: "{__version__}"', recipe)

    def test_the_appimage_build_refuses_to_proceed_on_a_mismatch(self):
        build = (REPO_ROOT / "packaging/appimage/build.sh").read_text(encoding="utf-8")
        self.assertIn("src/openemux/__init__.py", build)
        self.assertIn("does not carry version", build)

    def test_the_rpm_changelog_documents_the_version_being_built(self):
        spec = (REPO_ROOT / "packaging/rpm/openemux.spec").read_text(encoding="utf-8")
        head = next(
            line for line in spec.splitlines()[spec.splitlines().index("%changelog") :]
            if line.startswith("*")
        )
        self.assertTrue(
            head.endswith(f" - {__version__}-1"),
            f"the newest %changelog entry is not {__version__}: {head}",
        )

    def test_the_metainfo_declares_the_version_being_built(self):
        # Also covered from the AppStream side in test_appstream_metainfo.py;
        # kept here so one run of this file answers "are all four in step?".
        metainfo = (
            REPO_ROOT
            / "packaging/common/io.github.guilhermefeitosa66.OpenEmux.metainfo.xml"
        ).read_text(encoding="utf-8")
        first = re.search(r'<release version="([^"]+)"', metainfo).group(1)
        self.assertEqual(first, __version__)


class TheBuildImagesArePinnedTests(unittest.TestCase):
    """A floating tag makes a base-image regression look like a code one."""

    def test_there_are_dockerfiles_to_check(self):
        self.assertTrue(DOCKERFILES)

    def test_every_base_image_is_pinned_by_digest(self):
        for dockerfile in DOCKERFILES:
            for line in dockerfile.read_text(encoding="utf-8").splitlines():
                if not line.startswith("FROM "):
                    continue
                with self.subTest(file=dockerfile.name, line=line):
                    self.assertRegex(
                        line,
                        r"^FROM \S+:\S+@sha256:[0-9a-f]{64}$",
                        "the base image is a floating tag",
                    )

    def test_the_image_build_always_refetches_its_base(self):
        # Without --pull a stale local image is reused silently -- possibly one
        # cached before a security update.
        build = (REPO_ROOT / "packaging/build.sh").read_text(encoding="utf-8")
        self.assertIn("docker build --pull", build)


class NothingIsFetchedOverPlainHttpTests(unittest.TestCase):
    """Whatever the AppImage downloads ends up inside a signed artifact."""

    RECIPE = REPO_ROOT / "packaging/appimage/AppImageBuilder.yml"

    def test_the_apt_sources_and_their_key_use_https(self):
        text = self.RECIPE.read_text(encoding="utf-8")
        offenders = [
            line.strip()
            for line in text.splitlines()
            if "http://" in line and not line.strip().startswith("#")
        ]
        self.assertEqual(
            offenders, [], f"plain HTTP in the AppImage recipe: {offenders}"
        )

    def test_the_build_images_fetch_nothing_over_plain_http(self):
        for dockerfile in DOCKERFILES:
            text = dockerfile.read_text(encoding="utf-8")
            offenders = [
                line.strip()
                for line in text.splitlines()
                if "http://" in line and not line.strip().startswith("#")
            ]
            with self.subTest(file=dockerfile.name):
                self.assertEqual(offenders, [], f"plain HTTP: {offenders}")


class ThePythonDependenciesAreHashPinnedTests(unittest.TestCase):
    """Version-pinned is not the same as content-pinned."""

    HASHED = REPO_ROOT / "packaging/appimage/requirements.hashed.txt"

    def setUp(self):
        self.text = self.HASHED.read_text(encoding="utf-8")

    def test_the_recipe_installs_with_require_hashes(self):
        recipe = (REPO_ROOT / "packaging/appimage/AppImageBuilder.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("--require-hashes", recipe)
        self.assertIn("packaging/appimage/requirements.hashed.txt", recipe)

    def test_every_requirement_carries_at_least_one_hash(self):
        requirements = re.findall(r"(?m)^(\S+)==(\S+) \\$", self.text)
        self.assertTrue(requirements, "the hashed file pins nothing")
        for name, _ in requirements:
            with self.subTest(package=name):
                block = self.text.split(f"{name}==", 1)[1]
                self.assertIn("--hash=sha256:", block.split("\n\n", 1)[0])

    def test_it_agrees_with_the_lock_on_versions(self):
        # The lock is what `make lock-deps` writes and what pip-audit reads;
        # this file is generated from it. A bump to one and not the other would
        # bundle a version nobody audited.
        lock = dict(
            entry.split("==", 1)
            for entry in (REPO_ROOT / "requirements.lock")
            .read_text(encoding="utf-8")
            .split()
            if "==" in entry
        )
        hashed = dict(re.findall(r"(?m)^(\S+)==(\S+) \\$", self.text))
        for name, version in hashed.items():
            with self.subTest(package=name):
                self.assertEqual(
                    lock.get(name),
                    version,
                    f"{name} is {version} here and {lock.get(name)} in "
                    "requirements.lock; rerun packaging/appimage/hash_lock.py",
                )

    def test_the_two_packages_the_bundle_takes_from_apt_are_absent(self):
        # PyGObject and pycairo come from python3-gi / python3-cairo; a PyPI
        # copy in the bundle would shadow them.
        for name in ("PyGObject", "pycairo"):
            with self.subTest(package=name):
                self.assertNotIn(f"{name}==", self.text)


class TheBuildsDoNotRunAsHostRootTests(unittest.TestCase):
    """--privileged, a bind-mounted repository and a credential in the env."""

    def setUp(self):
        self.text = (REPO_ROOT / "packaging/build.sh").read_text(encoding="utf-8")

    def test_no_build_asks_for_privileged(self):
        offenders = [
            line.strip()
            for line in self.text.splitlines()
            if "--privileged" in line and not line.strip().startswith("#")
        ]
        self.assertEqual(offenders, [], f"still privileged: {offenders}")

    def test_the_fuse_builds_ask_for_exactly_what_they_need(self):
        # Both builds mount a filesystem. appimage-builder needs mount(2) and
        # /dev/fuse; flatpak-builder's bubblewrap additionally brings up
        # loopback in a network namespace and calls pivot_root, which Docker's
        # default seccomp profile blocks. Probed against the real failures.
        for argument in ("--cap-add SYS_ADMIN", "--device /dev/fuse",
                         "--security-opt apparmor:unconfined",
                         "--cap-add NET_ADMIN", "--security-opt seccomp=unconfined"):
            with self.subTest(argument=argument):
                self.assertIn(argument, self.text)

    def test_the_appimage_build_is_not_given_the_flatpak_exceptions(self):
        # Narrowing is only narrowing if each build gets its own set: the
        # AppImage needs neither NET_ADMIN nor a seccomp exception.
        appimage_branch = self.text.split('if [ "$TARGET" = "appimage" ]', 1)[1]
        appimage_branch = appimage_branch.split("elif", 1)[0]
        self.assertNotIn("NET_ADMIN", appimage_branch)
        self.assertNotIn("seccomp", appimage_branch)


if __name__ == "__main__":
    unittest.main()
