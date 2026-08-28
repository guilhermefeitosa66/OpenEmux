"""Every package has to ship the AppStream metainfo, and it has to be right (#253).

The file existed but only the Flatpak module installed it, so a user who
installed the `.deb`, the `.rpm` or the AppImage got an app that GNOME Software
and KDE Discover knew only as a bare desktop entry: no summary, no screenshots,
no release notes, no update notification. Both rpmlint and lintian flag that.

Three data defects went with it, and all three are the kind that only show up
in a software centre months later: a five-release hole in the version history,
screenshot URLs pointed at a mutable branch, and a Flatpak-only copy of the
desktop entry that had drifted from the shared one.
"""

import re
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ID = "io.github.guilhermefeitosa66.OpenEmux"
METAINFO = REPO_ROOT / f"packaging/common/{APP_ID}.metainfo.xml"
DESKTOP = REPO_ROOT / "packaging/common/openemux.desktop"

#: Where each format installs it from. `stage_tree.sh` covers the .deb and the
#: .rpm; the other two install it themselves.
INSTALLERS = (
    "packaging/common/stage_tree.sh",
    "packaging/appimage/AppImageBuilder.yml",
    f"packaging/flatpak/{APP_ID}.yaml",
)


def _tree():
    return ET.parse(METAINFO).getroot()


class TheMetainfoIsSharedNotFlatpakOnlyTests(unittest.TestCase):
    def test_it_lives_beside_the_other_shared_packaging_inputs(self):
        self.assertTrue(METAINFO.is_file(), f"{METAINFO} is missing")
        self.assertFalse(
            (REPO_ROOT / f"packaging/flatpak/{APP_ID}.metainfo.xml").exists(),
            "the Flatpak still carries its own copy of the metainfo",
        )

    def test_every_format_installs_it(self):
        for relative_path in INSTALLERS:
            with self.subTest(file=relative_path):
                text = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
                self.assertIn(
                    "metainfo",
                    text,
                    f"{relative_path} installs no AppStream metainfo, so the app is "
                    "invisible in the software centre there",
                )

    def test_the_rpm_owns_the_installed_file(self):
        # stage_tree.sh writing it is not enough: an unpackaged file in the
        # buildroot fails the rpm build outright.
        spec = (REPO_ROOT / "packaging/rpm/openemux.spec").read_text(encoding="utf-8")
        files = spec.split("%files", 1)[1].split("\n%", 1)[0]
        self.assertIn(f"/usr/share/metainfo/{APP_ID}.metainfo.xml", files)


class TheReleaseHistoryHasNoHolesTests(unittest.TestCase):
    """A gap shows up as a missing entry in the software centre's "What's new"."""

    def setUp(self):
        self.declared = [
            release.get("version") for release in _tree().find("releases")
        ]

    def test_every_version_the_rpm_changelog_documents_is_declared(self):
        spec = (REPO_ROOT / "packaging/rpm/openemux.spec").read_text(encoding="utf-8")
        changelog = set(re.findall(r"^\* .* - (\S+)-\d+$", spec, re.MULTILINE))
        missing = sorted(changelog - set(self.declared))
        self.assertEqual(
            missing, [], f"shipped but absent from the metainfo: {missing}"
        )

    def test_releases_are_listed_newest_first(self):
        # AppStream takes the first entry as the current release.
        def key(version):
            return tuple(int(part) for part in version.split("."))

        self.assertEqual(
            self.declared,
            sorted(self.declared, key=key, reverse=True),
            "the release list is out of order",
        )

    def test_the_first_entry_is_the_version_being_built(self):
        from openemux import __version__

        self.assertEqual(self.declared[0], __version__)

    def test_every_release_carries_notes(self):
        for release in _tree().find("releases"):
            with self.subTest(version=release.get("version")):
                self.assertIsNotNone(
                    release.find("description"),
                    "a release with no description shows as a blank entry",
                )
                self.assertRegex(release.get("date", ""), r"^\d{4}-\d{2}-\d{2}$")


class ScreenshotsSurviveAScreenshotRefreshTests(unittest.TestCase):
    """AppStream re-indexes from the live URL, long after the install."""

    def setUp(self):
        self.images = [
            image
            for screenshot in _tree().find("screenshots")
            for image in screenshot.iter("image")
        ]

    def test_there_are_screenshots_at_all(self):
        self.assertTrue(self.images)

    def test_none_of_them_points_at_a_mutable_branch(self):
        for image in self.images:
            with self.subTest(url=image.text):
                self.assertNotIn(
                    "/main/",
                    image.text,
                    "a screenshot refresh that renames this file 404s the Flathub "
                    "linter and blanks the screenshots for existing users",
                )
                self.assertRegex(
                    image.text,
                    r"/OpenEmux/[0-9a-f]{40}/",
                    "the URL is not pinned to a commit",
                )

    def test_each_one_declares_its_type_and_size(self):
        for image in self.images:
            with self.subTest(url=image.text):
                self.assertEqual(image.get("type"), "source")
                self.assertTrue(image.get("width"))
                self.assertTrue(image.get("height"))

    def test_the_pinned_files_are_the_ones_in_the_repository(self):
        # A pinned URL that names a file the project no longer has is a 404
        # waiting for the next re-index.
        for image in self.images:
            name = image.text.rsplit("/", 1)[1]
            with self.subTest(name=name):
                self.assertTrue(
                    (REPO_ROOT / "docs/assets" / name).is_file(),
                    f"docs/assets/{name} does not exist",
                )

    def test_the_declared_size_matches_the_file(self):
        for image in self.images:
            name = image.text.rsplit("/", 1)[1]
            raw = (REPO_ROOT / "docs/assets" / name).read_bytes()
            # PNG IHDR: 8-byte signature, 4-byte length, "IHDR", then w/h.
            width = int.from_bytes(raw[16:20], "big")
            height = int.from_bytes(raw[20:24], "big")
            with self.subTest(name=name):
                self.assertEqual((str(width), str(height)),
                                 (image.get("width"), image.get("height")))


class OneDesktopEntryForEveryFormatTests(unittest.TestCase):
    """The Flatpak's copy had drifted from the shared one."""

    def test_the_flatpak_has_no_desktop_file_of_its_own(self):
        self.assertFalse(
            (REPO_ROOT / f"packaging/flatpak/{APP_ID}.desktop").exists(),
            "the Flatpak carries a second desktop entry that will drift again",
        )

    def test_the_flatpak_installs_the_shared_entry(self):
        manifest = (REPO_ROOT / f"packaging/flatpak/{APP_ID}.yaml").read_text(
            encoding="utf-8"
        )
        self.assertIn("packaging/common/openemux.desktop", manifest)

    def test_the_flatpak_strips_tryexec_from_it(self):
        # Flatpak exports the entry to the host, where TryExec is resolved
        # against the host PATH -- and no `openemux` binary lives there.
        manifest = (REPO_ROOT / f"packaging/flatpak/{APP_ID}.yaml").read_text(
            encoding="utf-8"
        )
        self.assertIn("/^TryExec=/d", manifest)

    def test_the_shared_entry_declares_what_a_software_centre_reads(self):
        text = DESKTOP.read_text(encoding="utf-8")
        for key in ("Name=", "Comment=", "Icon=", "Categories=", "Keywords="):
            with self.subTest(key=key):
                self.assertRegex(text, r"(?m)^%s" % re.escape(key))

    def test_the_metainfo_points_at_that_entry(self):
        launchable = _tree().find("launchable")
        self.assertEqual(launchable.text, f"{APP_ID}.desktop")


if __name__ == "__main__":
    unittest.main()
