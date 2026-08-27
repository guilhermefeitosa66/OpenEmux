"""The desktop entry, and the metadata a `.deb` is expected to carry (#256).

Three defects, grouped because they are all "the package is almost right":

* ``TryExec=openemux`` in the shared entry. It is resolved against the user's
  ``PATH``, and AppImage integrators (appimaged, AppImageLauncher, GearLever)
  rewrite ``Exec`` to the bundle path and leave ``TryExec`` alone -- so the
  integrated entry named a binary that does not exist and was silently hidden
  from the menu. Native packages were unaffected: they do install
  ``/usr/bin/openemux``.
* ``shared-mime-info`` declared as a hard dependency by both native packages,
  with no ``MimeType=`` anywhere for it to index.
* No ``md5sums``, so ``debsums openemux`` could not verify a single one of the
  600+ installed files of a package that ships an executable AppImage, and no
  changelog at all.
"""

import re
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DESKTOP = REPO_ROOT / "packaging/common/openemux.desktop"
STAGE_TREE = REPO_ROOT / "packaging/common/stage_tree.sh"


def _entries():
    return dict(
        line.split("=", 1)
        for line in DESKTOP.read_text(encoding="utf-8").splitlines()
        if "=" in line and not line.startswith("[")
    )


class TheSharedEntryPromisesNothingItCannotKeepTests(unittest.TestCase):
    def test_it_carries_no_tryexec(self):
        self.assertNotIn(
            "TryExec",
            _entries(),
            "TryExec is resolved against PATH; an integrated AppImage has no "
            "`openemux` there and the menu entry is hidden",
        )

    def test_the_native_packages_add_an_absolute_one(self):
        # They install /usr/bin/openemux, so they can promise it resolves --
        # and an absolute TryExec is also what stops a ~/.local/bin shadow.
        text = STAGE_TREE.read_text(encoding="utf-8")
        self.assertIn("TryExec=/usr/bin/openemux", text)

    def test_the_appimage_build_refuses_an_entry_with_tryexec(self):
        build = (REPO_ROOT / "packaging/appimage/build.sh").read_text(encoding="utf-8")
        self.assertIn("carries TryExec", build)

    def test_the_entry_still_says_everything_a_menu_needs(self):
        entries = _entries()
        for key in ("Type", "Name", "GenericName", "Comment", "Exec", "Icon",
                    "Categories", "Keywords", "StartupNotify", "StartupWMClass"):
            with self.subTest(key=key):
                self.assertIn(key, entries)


class NoDependencyIndexesNothingTests(unittest.TestCase):
    """`shared-mime-info` was declared for an association that never existed."""

    def test_the_entry_declares_no_mimetype_and_no_field_code(self):
        # If one of these ever changes, the dependency has to come back with
        # it -- which is what the next test checks.
        entries = _entries()
        self.assertNotIn("MimeType", entries)
        self.assertNotRegex(entries["Exec"], r"%[fFuU]")

    def test_neither_native_package_requires_shared_mime_info(self):
        deb = (REPO_ROOT / "packaging/deb/build.sh").read_text(encoding="utf-8")
        depends = next(
            line for line in deb.splitlines() if line.startswith("Depends:")
        )
        self.assertNotIn("shared-mime-info", depends)

        spec = (REPO_ROOT / "packaging/rpm/openemux.spec").read_text(encoding="utf-8")
        self.assertNotRegex(spec, r"(?m)^Requires:\s+shared-mime-info$")

    def test_the_appimage_still_bundles_it(self):
        # A different reason there: XDG_DATA_DIRS leads into the AppDir, so GTK
        # looks for the shared MIME database inside the bundle.
        recipe = (REPO_ROOT / "packaging/appimage/AppImageBuilder.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("- shared-mime-info", recipe)


class TheDebCarriesItsOwnMetadataTests(unittest.TestCase):
    def setUp(self):
        self.build = (REPO_ROOT / "packaging/deb/build.sh").read_text(encoding="utf-8")

    def test_md5sums_is_generated_before_the_package_is_built(self):
        self.assertIn("DEBIAN/md5sums", self.build)
        self.assertLess(
            self.build.index("DEBIAN/md5sums"),
            self.build.index("dpkg-deb --root-owner-group"),
            "md5sums is written after the package is built",
        )

    def test_the_build_proves_debsums_can_verify_the_install(self):
        self.assertIn("debsums -s openemux", self.build)

    def test_a_changelog_is_installed_where_dpkg_looks_for_it(self):
        self.assertIn("usr/share/doc/openemux/changelog.Debian.gz", self.build)
        # -n so the gzip header carries no timestamp: a package built twice
        # from the same source should be the same bytes.
        self.assertIn("gzip -9n", self.build)


class TheChangelogComesFromTheSpecTests(unittest.TestCase):
    """One release history, rendered into the format each package wants."""

    HEADER = re.compile(r"^openemux \((?P<version>[^)]+)\) \S+; urgency=\w+$")
    SIGNOFF = re.compile(
        r"^ -- .+ <.+>  \w{3}, \d{2} \w{3} \d{4} \d{2}:\d{2}:\d{2} [+-]\d{4}$"
    )

    @classmethod
    def setUpClass(cls):
        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "packaging/deb/changelog_from_spec.py")],
            capture_output=True,
            text=True,
            check=True,
        )
        cls.text = result.stdout

    def test_it_renders_every_version_the_spec_documents(self):
        spec = (REPO_ROOT / "packaging/rpm/openemux.spec").read_text(encoding="utf-8")
        documented = set(re.findall(r"^\* .* - (\S+)-\d+$", spec, re.MULTILINE))
        rendered = set(re.findall(r"(?m)^openemux \(([^)]+)\)", self.text))
        self.assertEqual(rendered, documented)

    def test_the_newest_entry_is_the_version_being_built(self):
        from openemux import __version__

        first = self.HEADER.match(self.text.splitlines()[0])
        self.assertIsNotNone(first, self.text.splitlines()[0])
        self.assertEqual(first.group("version"), __version__)

    def test_every_entry_is_shaped_the_way_dpkg_expects(self):
        blocks = [block for block in self.text.split("\n\n") if block.strip()]
        self.assertTrue(blocks)
        headers = [line for line in self.text.splitlines() if self.HEADER.match(line)]
        signoffs = [line for line in self.text.splitlines() if self.SIGNOFF.match(line)]
        self.assertEqual(
            len(headers),
            len(signoffs),
            "every entry needs a header and a maintainer sign-off",
        )

    def test_every_bullet_is_indented_two_spaces_with_an_asterisk(self):
        bullets = [
            line
            for line in self.text.splitlines()
            if line.strip() and not self.HEADER.match(line)
            and not self.SIGNOFF.match(line)
        ]
        self.assertTrue(bullets)
        for line in bullets:
            with self.subTest(line=line):
                self.assertTrue(line.startswith("  * "), line)


if __name__ == "__main__":
    unittest.main()
