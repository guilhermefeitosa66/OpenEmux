"""The AUR's openemux-git recipe, read off the files rather than built.

`make aur-git` builds it from a clone of the checkout, installs it in the Arch
image and removes it again (issue #986). What these guard is what a user only
finds out by installing it from the AUR:

* it replaces the release package rather than colliding with it;
* it clones this repository's default branch, and the version comes from
  src/openemux/__init__.py plus the clone, so it is never a second place to
  bump;
* the emulator is the distribution's -- a clone carries no vendored RetroArch;
* the runtime dependencies are the release package's (the WebP loader among
  them, issue #251), so the two cannot drift apart unnoticed;
* the test build is not a release artifact and never lands in dist/.
"""

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RECIPE = "packaging/aur/openemux-git/PKGBUILD"


def _read(relative):
    return (REPO_ROOT / relative).read_text(encoding="utf-8")


def _array(pkgbuild, name):
    """The quoted entries of a top-level bash array, comments left out."""
    match = re.search(rf"(?ms)^{name}=\((.*?)\)$", pkgbuild)
    if match is None:
        return None
    body = "\n".join(line.split("#", 1)[0] for line in match.group(1).splitlines())
    return re.findall(r"'([^']*)'|\"([^\"]*)\"", body)


def _names(entries):
    return [next(part for part in entry if part) for entry in entries]


class OpenemuxGitPkgbuildTests(unittest.TestCase):
    def setUp(self):
        self.pkgbuild = _read(RECIPE)

    def test_it_is_the_git_package_and_replaces_the_release_one(self):
        self.assertRegex(self.pkgbuild, r"(?m)^pkgname=openemux-git$")
        self.assertRegex(self.pkgbuild, r"(?m)^_pkgname=openemux$")
        self.assertRegex(self.pkgbuild, r'(?m)^provides=\("\$_pkgname"\)$')
        self.assertRegex(self.pkgbuild, r'(?m)^conflicts=\("\$_pkgname"\)$')

    def test_it_clones_this_repository_on_the_default_branch(self):
        self.assertRegex(self.pkgbuild, r"(?m)^_branch=develop$")
        self.assertIn(
            'source=("$_pkgname::git+https://github.com/guilhermefeitosa66/'
            'OpenEmux.git#branch=$_branch")',
            self.pkgbuild,
        )
        # A git source has no fixed bytes to pin.
        self.assertRegex(self.pkgbuild, r"(?m)^sha256sums=\('SKIP'\)$")
        self.assertIn("git", _names(_array(self.pkgbuild, "makedepends")))

    def test_the_version_is_computed_from_the_clone(self):
        self.assertRegex(self.pkgbuild, r"(?m)^pkgver=0\.0\.0$")
        pkgver = re.search(r"(?ms)^pkgver\(\) \{(.*?)^\}", self.pkgbuild)
        self.assertIsNotNone(pkgver, "PKGBUILD has no pkgver()")
        body = pkgver.group(1)
        self.assertIn("src/openemux/__init__.py", body)
        self.assertIn("git rev-list --count HEAD", body)
        self.assertIn("git rev-parse --short=7 HEAD", body)
        self.assertIn("'%s.r%s.g%s'", body)

    def test_the_emulator_is_the_distributions(self):
        self.assertIn("retroarch", _names(_array(self.pkgbuild, "depends")))
        # Nothing compiled and nothing vendored: one package for every arch.
        self.assertRegex(self.pkgbuild, r"(?m)^arch=\('any'\)$")

    def test_the_runtime_dependencies_are_the_release_packages(self):
        release = _read("packaging/arch/PKGBUILD")
        ours = set(_names(_array(self.pkgbuild, "depends")))
        theirs = set(_names(_array(release, "depends")))
        self.assertTrue(theirs, "the release PKGBUILD declares no depends")
        self.assertEqual(theirs, ours - {"retroarch"})
        self.assertIn("webp-pixbuf-loader", ours)
        self.assertEqual(
            _names(_array(self.pkgbuild, "optdepends")),
            ["python-segno: QR code of the address in Share Nearby"],
        )

    def test_the_install_layout_is_the_shared_one(self):
        self.assertIn('DESTDIR="$pkgdir" ROOT_DIR="$PWD" sh packaging/common/stage_tree.sh',
                      self.pkgbuild)

    def test_the_licence_lands_where_arch_keeps_it(self):
        self.assertIn('"$pkgdir/usr/share/licenses/$pkgname/LICENSE"', self.pkgbuild)
        self.assertIn('"$pkgdir/usr/share/licenses/$pkgname/copyright"', self.pkgbuild)
        self.assertIn('rm -rf "$pkgdir/usr/share/doc/openemux"', self.pkgbuild)
        self.assertIn('rmdir --ignore-fail-on-non-empty "$pkgdir/usr/share/doc"',
                      self.pkgbuild)


class AurBuildScriptTests(unittest.TestCase):
    def setUp(self):
        self.script = _read("packaging/aur/build.sh")

    def test_the_code_under_test_is_the_checkout_not_github(self):
        self.assertIn("git+file://${BUILDDIR}/openemux.git#commit=${COMMIT}", self.script)
        # The substitution must fail loudly if the recipe's source line moves.
        self.assertIn('grep -qF "$GITHUB_SOURCE" "$RECIPE"', self.script)

    def test_makepkg_does_not_run_as_root(self):
        self.assertIn("runuser -u builder", self.script)

    def test_the_package_is_installed_and_removed_again(self):
        self.assertIn('pacman -U --noconfirm "$PKG_PATH"', self.script)
        self.assertIn("pacman -Rns --noconfirm openemux-git", self.script)

    def test_the_published_files_come_from_the_tracked_recipe(self):
        self.assertIn('sed "s/^pkgver=.*/pkgver=${PKGVER}/" "$RECIPE" > "$OUT/PKGBUILD"',
                      self.script)
        self.assertIn("makepkg --printsrcinfo > .SRCINFO", self.script)
        self.assertIn("FAIL: .SRCINFO points at the local clone", self.script)

    def test_the_output_is_never_in_dist(self):
        self.assertRegex(self.script, r"(?m)^OUT=build/aur/openemux-git$")
        self.assertNotIn("dist/", self.script)


class WiringTests(unittest.TestCase):
    def test_the_dispatcher_accepts_the_target_and_builds_in_the_arch_image(self):
        dispatcher = _read("packaging/build.sh")
        self.assertIn("appimage|deb|rpm|arch|flatpak|windows|aur|aur-release)", dispatcher)
        self.assertIn('[ "$TARGET" = "aur" ] && IMAGE_TARGET=arch', dispatcher)
        self.assertIn('DOCKER_ARGS+=(-v "$AUR_SRC:/src:ro")', dispatcher)

    def test_make_aur_git_exists_and_is_not_a_release_artifact(self):
        makefile = _read("Makefile")
        self.assertRegex(makefile, r"(?m)^aur-git:\n\t\./packaging/build\.sh aur$")
        packages = re.search(r"(?m)^packages: (.*)$", makefile)
        self.assertIsNotNone(packages)
        self.assertNotIn("aur", packages.group(1))
        self.assertRegex(makefile, r"(?m)^\trm -rf dist/.* build/aur$")


if __name__ == "__main__":
    unittest.main()
