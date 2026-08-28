"""The RPM spec has to be buildable by somebody who is not us (#252).

The spec used to have no ``Source0``, no ``%prep`` and no ``%build``: it was
driven with ``--define "repo_root /work"`` and ran the staging script straight
out of the project's Docker bind mount. That produces no SRPM, so ``mock``,
COPR and Fedora review had nothing to start from -- and any other invocation
got a literal ``%{repo_root}`` path.

Everything below is checked against the spec text, which is what a reviewer
reads; ``packaging/rpm/build.sh`` proves the rest at build time by rebuilding
its own SRPM in a different topdir and running rpmlint over the result.
"""

import datetime
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SPEC = REPO_ROOT / "packaging/rpm/openemux.spec"

_MONTHS = {
    name: number
    for number, name in enumerate(
        "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(), start=1
    )
}
_ENTRY = re.compile(r"^\* (\w{3}) (\w{3}) (\d{2}) (\d{4}) .* - (\S+)$")


def _spec_text():
    return SPEC.read_text(encoding="utf-8")


def _changelog_lines():
    lines = _spec_text().splitlines()
    return lines[lines.index("%changelog") + 1 :]


class TheSpecBuildsFromASourceTarballTests(unittest.TestCase):
    def setUp(self):
        self.text = _spec_text()

    def test_it_declares_a_source(self):
        self.assertRegex(self.text, r"(?m)^Source0:\s+%\{name\}-%\{version\}\.tar\.gz$")

    def test_it_has_the_sections_rpmbuild_needs_for_an_srpm(self):
        for section in ("%prep", "%build", "%install", "%check", "%files"):
            with self.subTest(section=section):
                self.assertRegex(self.text, r"(?m)^%s$" % re.escape(section))

    def test_it_unpacks_the_tarball(self):
        self.assertRegex(self.text, r"(?m)^%autosetup$")

    def test_it_declares_what_the_build_root_needs(self):
        # convert(1), desktop-file-validate and python3 are all used during the
        # build; a buildroot without them fails halfway through %install.
        for package in ("ImageMagick", "desktop-file-utils", "python3"):
            with self.subTest(package=package):
                self.assertRegex(
                    self.text, r"(?m)^BuildRequires:\s+%s$" % re.escape(package)
                )

    def test_nothing_reaches_outside_the_build_directory(self):
        # The whole point: no path into the project's own bind mount.
        self.assertNotIn("repo_root", self.text)
        self.assertNotIn("/work", self.text)

    def test_the_build_script_resolves_the_version_into_the_spec_it_builds(self):
        # A --define does not survive into the SRPM, so a templated Version:
        # would leave `rpmbuild --rebuild` with an undefined macro.
        build = (REPO_ROOT / "packaging/rpm/build.sh").read_text(encoding="utf-8")
        self.assertIn("s/^Version:.*/Version:", build)
        self.assertIn("rpmbuild -ba", build)
        self.assertIn("--rebuild", build)


class TheLicenceLandsWhereRpmPutsItTests(unittest.TestCase):
    """`%license /usr/share/doc/openemux/copyright` is the Debian layout.

    It also named a file in a directory the package did not own, so
    ``rpm -qf /usr/share/doc/openemux`` found no owner, ``dnf remove`` left the
    directory behind and rpmlint raised ``dir-or-file-in-usr-share-doc``.
    """

    def setUp(self):
        self.text = _spec_text()

    def test_the_licence_is_declared_by_name_not_by_path(self):
        self.assertRegex(self.text, r"(?m)^%license LICENSE$")

    def test_no_file_is_packaged_under_usr_share_doc(self):
        files = self.text.split("%files", 1)[1].split("\n%", 1)[0]
        self.assertNotIn("/usr/share/doc", files)

    def test_the_debian_copy_is_removed_from_the_buildroot(self):
        # stage_tree.sh is shared with the .deb and writes it unconditionally,
        # so the spec has to undo it or rpmbuild fails on an unpackaged file.
        self.assertIn("rm -rf %{buildroot}/usr/share/doc/openemux", self.text)


class ScriptletsRunAtTheRightMomentTests(unittest.TestCase):
    def setUp(self):
        text = _spec_text()
        self.post = text.split("\n%post\n", 1)[1].split("\n%postun\n", 1)[0]
        self.postun = text.split("\n%postun\n", 1)[1].split("\n%changelog", 1)[0]

    def test_both_caches_are_refreshed_on_install(self):
        self.assertIn("gtk-update-icon-cache", self.post)
        self.assertIn("update-desktop-database", self.post)

    def test_both_caches_are_refreshed_on_erase(self):
        # %postun used to rebuild only the icon cache, leaving a stale desktop
        # entry in the MIME/desktop database after `dnf remove`.
        self.assertIn("gtk-update-icon-cache", self.postun)
        self.assertIn("update-desktop-database", self.postun)

    def test_erase_only_runs_on_the_final_removal(self):
        # $1 == 0 is the last copy going away; during an upgrade the incoming
        # package's %post has already refreshed both caches.
        self.assertIn("if [ $1 -eq 0 ]; then", self.postun)


class TheChangelogIsWellFormedTests(unittest.TestCase):
    """rpmlint treats both of these as errors for Fedora review."""

    def test_every_entry_names_the_weekday_its_date_actually_falls_on(self):
        for line in _changelog_lines():
            match = _ENTRY.match(line)
            if not match:
                self.assertFalse(
                    line.startswith("*"), f"unparseable changelog header: {line}"
                )
                continue
            weekday, month, day, year, version = match.groups()
            date = datetime.date(int(year), _MONTHS[month], int(day))
            with self.subTest(version=version):
                self.assertEqual(
                    weekday,
                    date.strftime("%a"),
                    f"{version} is dated {date}, which is a {date.strftime('%a')}",
                )

    def test_entries_are_separated_by_a_blank_line(self):
        lines = _changelog_lines()
        for index, line in enumerate(lines):
            if index == 0 or not _ENTRY.match(line):
                continue
            with self.subTest(entry=line.split(" - ")[-1]):
                self.assertEqual(
                    lines[index - 1].strip(), "", f"no blank line before: {line}"
                )

    def test_entries_run_newest_first(self):
        dates = []
        for line in _changelog_lines():
            match = _ENTRY.match(line)
            if match:
                weekday, month, day, year, version = match.groups()
                dates.append((datetime.date(int(year), _MONTHS[month], int(day)), version))
        self.assertTrue(dates, "the spec has no changelog entries at all")
        for newer, older in zip(dates, dates[1:]):
            with self.subTest(entry=older[1]):
                self.assertGreaterEqual(
                    newer[0], older[0], f"{older[1]} is dated after the entry above it"
                )


if __name__ == "__main__":
    unittest.main()
