"""The packaging scripts must not assume x86_64 (issue #119).

Every one of these was a hardcoded literal, and each fails in its own quiet
way: a `.deb` stamped `amd64` is one apt refuses to install on an ARM machine,
an `.rpm` with `ExclusiveArch: x86_64` cannot be built there at all, and a
package that bundles no emulator and declares no dependency on one installs
cleanly and then cannot launch a game.

Read off the scripts rather than run them: building four packages twice over
under emulation is a twenty-minute check, and what these guard is that a value
is *derived* rather than written down.
"""

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _read(relative):
    return (REPO_ROOT / relative).read_text(encoding="utf-8")


class DebArchitectureTests(unittest.TestCase):
    def setUp(self):
        self.script = _read("packaging/deb/build.sh")

    def test_the_architecture_is_asked_of_dpkg(self):
        self.assertIn("dpkg --print-architecture", self.script)

    def test_neither_the_control_field_nor_the_filename_is_hardcoded(self):
        self.assertIn("Architecture: ${DEB_ARCH}", self.script)
        self.assertNotIn("Architecture: amd64", self.script)
        self.assertNotIn("_amd64.deb", self.script)

    def test_arm_depends_on_a_retroarch_it_does_not_bundle(self):
        # libretro publishes no ARM build, so nothing is vendored there.
        self.assertRegex(self.script, r'arm64\)\s*RUNTIME_DEPENDS="retroarch"')

    def test_arm_does_not_require_libfuse(self):
        # It is there to mount the vendored AppImage; with no AppImage it is a
        # dependency on nothing.
        self.assertRegex(self.script, r'\*\)\s*RUNTIME_DEPENDS="libfuse2t64 \| libfuse2"')

    def test_the_install_test_checks_the_right_thing_per_architecture(self):
        self.assertIn('if [ "$VENDOR_ARCH" = "x86_64" ]', self.script)


class RpmArchitectureTests(unittest.TestCase):
    def setUp(self):
        self.spec = _read("packaging/rpm/openemux.spec")
        self.script = _read("packaging/rpm/build.sh")

    def test_both_architectures_are_buildable(self):
        self.assertIn("\nExclusiveArch:  x86_64 aarch64\n", self.spec)

    def test_the_bundled_appimage_dependency_is_per_architecture(self):
        self.assertIn("%ifarch x86_64", self.spec)
        self.assertIn("Requires:       fuse-libs", self.spec)
        # Weak on purpose: RetroArch is in RPM Fusion, not in Fedora, so a hard
        # Requires would make the package refuse to install on a stock system.
        self.assertIn("Recommends:     retroarch", self.spec)
        self.assertNotIn("Requires:       retroarch", self.spec)

    def test_the_install_test_checks_the_right_thing_per_architecture(self):
        self.assertIn('if [ "$(uname -m)" = "x86_64" ]', self.script)
        self.assertIn('RECOMMENDS="$(rpm -q --recommends openemux)"', self.script)


class StagingTests(unittest.TestCase):
    def test_only_this_architectures_retroarch_is_staged(self):
        # An x86_64 AppImage inside an ARM package is not a RetroArch that
        # failed to start; it is a file the kernel refuses to execute.
        stage = _read("packaging/common/stage_tree.sh")
        self.assertIn("FOREIGN_RETROARCH", stage)
        self.assertIn("RetroArch-Linux-aarch64.AppImage", stage)
        self.assertIn("RetroArch-Linux-x86_64.AppImage", stage)

    def test_copy_tree_takes_the_extra_exclusions(self):
        copy_tree = _read("packaging/common/copy_tree.sh")
        self.assertIn("[extra-exclude ...]", copy_tree)
        self.assertIn("$EXTRA", copy_tree)


class EntryPointTests(unittest.TestCase):
    def setUp(self):
        self.script = _read("packaging/build.sh")

    def test_the_gate_is_on_supported_architectures_not_on_x86_64(self):
        self.assertNotIn("AppImage builds require an x86_64 host", self.script)
        self.assertIn("x86_64|amd64|aarch64|arm64", self.script)

    def test_emulation_is_available_and_named(self):
        # The documented way to try an ARM packaging change without ARM
        # hardware. Not for release artifacts -- those are built ARM on ARM.
        self.assertIn("PLATFORM", self.script)
        self.assertIn("--platform", self.script)


class AppImageArchitectureTests(unittest.TestCase):
    def test_the_build_script_derives_everything_from_the_host(self):
        script = _read("packaging/appimage/build.sh")
        self.assertIn('ARCH="$(uname -m)"', script)
        self.assertIn("arch_recipe.py", script)
        self.assertIn('BUNDLE_NAME="OpenEmux-${VERSION}-${ARCH}.AppImage"', script)
        # The only x86_64 left should be the case arm that defines the triplet
        # and prose in comments -- never a path built from it.
        for literal in ('APPDIR_LIB="$PWD/AppDir/usr/lib/x86_64-linux-gnu"',
                        "RUNTIME_SRC=/opt/appimage-runtime-x86_64"):
            with self.subTest(literal=literal):
                self.assertNotIn(literal, script)

    def test_the_elf_loader_path_is_derived_not_written_down(self):
        # The recipe's lib64 symlinks are the x86_64 answer to a relative
        # PT_INTERP; there is no lib64 on ARM, and appimage-builder does not
        # fill the gap there because its glibc file list has no aarch64 loader
        # pattern. So the build reads the interpreter the bundled python asks
        # for and places exactly that path.
        script = _read("packaging/appimage/build.sh")
        self.assertIn("program interpreter", script)
        self.assertIn("AppDir/runtime/compat", script)
        self.assertIn("realpath --relative-to", script)

    def test_a_bundle_whose_loader_is_missing_is_not_packaged(self):
        # Shipping an AppImage that builds and cannot start is worse than
        # failing the build, and it is what happened.
        script = _read("packaging/appimage/build.sh")
        self.assertIn("still does not resolve", script)

    def test_a_runtime_is_pinned_for_each_architecture(self):
        # It is the first thing every user of an AppImage executes, so each one
        # is checksummed rather than trusted.
        dockerfile = _read("packaging/docker/appimage.Dockerfile")
        self.assertIn("APPIMAGE_RUNTIME_SHA256_X86_64", dockerfile)
        self.assertIn("APPIMAGE_RUNTIME_SHA256_AARCH64", dockerfile)
        digests = re.findall(r"APPIMAGE_RUNTIME_SHA256_\w+=([0-9a-f]{64})", dockerfile)
        self.assertEqual(len(digests), 2)
        self.assertEqual(len(set(digests)), 2, "both architectures share a checksum")


class FlatpakTests(unittest.TestCase):
    def test_the_x86_64_bundle_keeps_its_published_name(self):
        # It is a release asset with links pointing at it; only the other
        # architecture is suffixed, so the two do not overwrite each other.
        script = _read("packaging/flatpak/build.sh")
        self.assertIn('x86_64) BUNDLE="dist/OpenEmux-${VERSION}.flatpak"', script)
        self.assertIn('BUNDLE="dist/OpenEmux-${VERSION}-$(uname -m).flatpak"', script)


if __name__ == "__main__":
    unittest.main()
