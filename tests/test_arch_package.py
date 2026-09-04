"""The Arch package recipe, read off the files rather than built.

Building it means an archlinux container, a 171 MiB emulator download and a
full pacman install -- a check the packaging build already runs on every
`make arch`. What these guard is the handful of decisions that are invisible
until a user installs the result:

* the version is *derived* from src/openemux/__init__.py, not written down a
  fifth time (the AppImage recipe is the one place it is duplicated, and a
  forgotten bump there shipped a mislabelled artifact -- issue #255);
* ``!strip`` survives, because makepkg strips and rewrites every ELF it finds
  by default and the vendored RetroArch is 57 of them, held together by a
  RUNPATH of ``$ORIGIN/../lib`` (issue #328);
* the install layout is the shared one, not a fourth hand-written copy;
* the WebP loader is a hard dependency, not somebody else's optdepends
  (issue #251);
* the architecture is derived, and ARM -- which bundles no emulator, because
  libretro publishes no ARM build -- depends on the distribution's RetroArch
  instead (issue #119).
"""

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _read(relative):
    return (REPO_ROOT / relative).read_text(encoding="utf-8")


class PkgbuildTests(unittest.TestCase):
    def setUp(self):
        self.pkgbuild = _read("packaging/arch/PKGBUILD")

    def test_the_version_is_a_placeholder_the_build_fills_in(self):
        # A real version here is a second place to bump and forget.
        self.assertRegex(self.pkgbuild, r"(?m)^pkgver=0\.0\.0$")

    def test_both_architectures_are_declared(self):
        self.assertRegex(self.pkgbuild, r"(?m)^arch=\('x86_64' 'aarch64'\)$")

    def test_the_vendored_emulator_is_not_stripped(self):
        # makepkg's default is to strip and rewrite every ELF, which would
        # take the RUNPATH the portable RetroArch tree needs with it.
        options = re.search(r"(?m)^options=\((.*)\)$", self.pkgbuild)
        self.assertIsNotNone(options, "PKGBUILD declares no options")
        self.assertIn("!strip", options.group(1))

    def test_the_install_layout_is_the_shared_one(self):
        self.assertIn("packaging/common/stage_tree.sh", self.pkgbuild)
        self.assertIn('DESTDIR="$pkgdir"', self.pkgbuild)

    def test_the_licence_lands_where_arch_keeps_it(self):
        self.assertIn('"$pkgdir/usr/share/licenses/$pkgname/LICENSE"', self.pkgbuild)
        # Not a duplicate of LICENSE: a third of what ships is third-party
        # and the DEP-5 copyright is where those terms are recorded (#233).
        self.assertIn('"$pkgdir/usr/share/licenses/$pkgname/copyright"', self.pkgbuild)
        # stage_tree.sh writes the Debian location; leaving it behind orphans
        # /usr/share/doc/openemux, which no package would own.
        self.assertIn('rm -rf "$pkgdir/usr/share/doc/openemux"', self.pkgbuild)

    def test_the_webp_loader_is_a_hard_dependency(self):
        depends = re.search(r"(?s)^depends=\((.*?)\n\)", self.pkgbuild, re.MULTILINE)
        self.assertIsNotNone(depends, "PKGBUILD declares no depends")
        for required in (
            "python-gobject",
            "python-cairo",
            "gtk4",
            "libadwaita",
            "python-yaml",
            "python-xlib",
            "librsvg",
            "webp-pixbuf-loader",
            "adwaita-icon-theme",
        ):
            with self.subTest(package=required):
                self.assertIn(required, depends.group(1))

    def test_arm_depends_on_a_retroarch_it_does_not_bundle(self):
        self.assertRegex(
            self.pkgbuild,
            r"""(?s)if \[ "\$CARCH" = 'aarch64' \].*?depends\+=\('retroarch'\)""",
        )


class ArchBuildScriptTests(unittest.TestCase):
    def setUp(self):
        self.script = _read("packaging/arch/build.sh")

    def test_the_version_comes_from_the_single_source_of_truth(self):
        self.assertIn("src/openemux/__init__.py", self.script)
        self.assertIn("s/^pkgver=.*/pkgver=${VERSION}/", self.script)

    def test_the_architecture_is_derived_not_written_down(self):
        self.assertIn('CARCH="$(uname -m)"', self.script)
        self.assertNotIn("CARCH=x86_64", self.script)

    def test_makepkg_does_not_run_as_root(self):
        # makepkg refuses to, and the container is root by default.
        self.assertIn("runuser -u builder", self.script)

    def test_the_built_package_is_installed_and_removed_again(self):
        self.assertIn("pacman -U --noconfirm", self.script)
        self.assertIn("pacman -Rns --noconfirm openemux", self.script)

    def test_the_vendored_retroarch_still_resolves_its_own_libraries(self):
        # The one thing !strip protects, checked on the installed tree.
        self.assertIn("$ORIGIN", self.script)
        self.assertIn('usr/bin/../lib/', self.script)


class WiringTests(unittest.TestCase):
    def test_the_dispatcher_accepts_the_target(self):
        dispatcher = _read("packaging/build.sh")
        self.assertIn("appimage|deb|rpm|arch|flatpak|windows)", dispatcher)
        # x86_64 bundles the emulator, so the missing-vendors message has to
        # fire for this target too rather than 20 minutes into a container.
        self.assertIn("arch:x86_64", dispatcher)

    def test_make_arch_exists_and_is_part_of_make_packages(self):
        makefile = _read("Makefile")
        self.assertRegex(makefile, r"(?m)^arch: vendor-retroarch$")
        self.assertRegex(makefile, r"(?m)^packages: .*\barch\b.*")

    def test_packages_clean_removes_the_artifact(self):
        self.assertIn("dist/*.pkg.tar.*", _read("Makefile"))

    def test_the_build_image_is_pinned_by_digest(self):
        # A rolling base with a floating tag makes a regression from an
        # upstream image indistinguishable from a code regression (#255).
        dockerfile = _read("packaging/docker/arch.Dockerfile")
        self.assertRegex(dockerfile, r"(?m)^FROM archlinux:base-devel@sha256:[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main()
