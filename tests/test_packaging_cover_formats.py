"""Every package must be able to decode the covers OpenEmux downloads (#251).

Cover art synced from libretro is WebP, and gdk-pixbuf has no built-in
decoder for it: the loader is a separate package everywhere OpenEmux ships.
Neither native package declared it, so on a stock Ubuntu 24.04 even
``apt install ./openemux_*.deb`` left the app unable to decode a single
synced cover -- every card rendered blank, with one ``cover decode failed``
line in the log to say why.

The packaging files cannot be unit-tested, but the contract between them and
``SUPPORTED_COVER_EXTS`` can: adding a format to that tuple has to fail here
until each package says where its loader comes from.
"""

import unittest
from pathlib import Path

from openemux.core.scraper import SUPPORTED_COVER_EXTS

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Formats gdk-pixbuf decodes with no extra package anywhere.
BUILT_IN_FORMATS = {"png", "jpg", "jpeg"}

#: For every other format: the file that declares the loader for each way
#: OpenEmux is packaged, and the package name it has to name. The Flatpak is
#: absent on purpose -- ``org.gnome.Platform`` carries the WebP loader, which
#: is checked separately below so the reason is written down rather than
#: assumed.
LOADER_PACKAGES = {
    "webp": {
        "packaging/deb/build.sh": "webp-pixbuf-loader",
        "packaging/rpm/openemux.spec": "webp-pixbuf-loader",
        "packaging/appimage/AppImageBuilder.yml": "webp-pixbuf-loader",
        "packaging/windows/msys2_packages.py": "webp-pixbuf-loader",
    },
}


class EveryFormatHasBeenAccountedForTests(unittest.TestCase):
    def test_no_supported_format_is_unaccounted_for(self):
        # The point of the whole file: a new cover format either decodes
        # everywhere out of the box or gets a row above. Silence is not an
        # option, because the symptom is a blank card and nothing else.
        needs_a_loader = set(SUPPORTED_COVER_EXTS) - BUILT_IN_FORMATS
        self.assertEqual(needs_a_loader, set(LOADER_PACKAGES))

    def test_webp_is_still_a_format_covers_arrive_in(self):
        # If this ever stops being true the rows above are dead weight.
        self.assertIn("webp", SUPPORTED_COVER_EXTS)


class EveryPackageDeclaresItsLoadersTests(unittest.TestCase):
    def test_each_packaging_file_names_the_loader_package(self):
        for fmt, declarations in LOADER_PACKAGES.items():
            for relative_path, package in declarations.items():
                with self.subTest(format=fmt, file=relative_path):
                    text = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
                    self.assertIn(
                        package,
                        text,
                        f"{relative_path} does not declare {package}, so a {fmt} "
                        "cover renders blank there",
                    )

    def test_the_deb_declares_it_as_a_dependency_not_a_suggestion(self):
        # A Recommends is not enough: dpkg -i and offline installs skip them,
        # and apt does not pull one for a format nothing else on the box uses.
        # The control field is assembled from DEPENDS= lines rather than
        # written out in one, so that an architecture with nothing extra to
        # declare does not leave a trailing comma behind (issue #328).
        text = (REPO_ROOT / "packaging/deb/build.sh").read_text(encoding="utf-8")
        depends = [line for line in text.splitlines() if line.startswith("DEPENDS=")]
        self.assertTrue(depends, "the .deb declares no Depends at all")
        self.assertIn("Depends: ${DEPENDS}", text)
        self.assertIn("webp-pixbuf-loader", "\n".join(depends))

    def test_the_rpm_declares_it_as_a_requires(self):
        text = (REPO_ROOT / "packaging/rpm/openemux.spec").read_text(encoding="utf-8")
        self.assertIn("Requires:       webp-pixbuf-loader", text)

    def test_the_flatpak_inherits_it_from_the_gnome_runtime(self):
        # org.gnome.Platform ships libpixbufloader-webp.so, so the manifest
        # declares nothing -- but it has to still be built on that runtime.
        text = (
            REPO_ROOT / "packaging/flatpak/io.github.guilhermefeitosa66.OpenEmux.yaml"
        ).read_text(encoding="utf-8")
        self.assertIn("runtime: org.gnome.Platform", text)


class EveryBuildProvesItRatherThanTrustingTheLineTests(unittest.TestCase):
    """A declared dependency that the build never exercises is a wish."""

    BUILDS_THAT_CHECK = (
        "packaging/deb/build.sh",
        "packaging/rpm/build.sh",
        "packaging/appimage/selftest.py",
    )

    def test_each_build_checks_the_loaders_against_the_formats(self):
        for relative_path in self.BUILDS_THAT_CHECK:
            with self.subTest(file=relative_path):
                text = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
                self.assertIn(
                    "SUPPORTED_COVER_EXTS",
                    text,
                    f"{relative_path} does not check its pixbuf loaders against "
                    "the formats a cover can actually be",
                )


if __name__ == "__main__":
    unittest.main()
