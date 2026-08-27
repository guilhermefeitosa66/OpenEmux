"""The workflows in .github/ are release infrastructure, so the suite guards them.

Nothing here runs CI; these are cheap structural assertions about the workflow
files themselves, which no other check covers. The one they exist for: for a
year no job ever built a package, so a broken .deb/.rpm/AppImage/Flatpak was
only discovered on release day, with the release already half-done (issue #241).
"""

import unittest
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = REPO_ROOT / ".github/workflows"


def _workflow(name):
    text = (WORKFLOW_DIR / name).read_text(encoding="utf-8")
    # PyYAML reads the `on:` key as the boolean True (YAML 1.1); keep the raw
    # text around for the assertions that care about it.
    return yaml.safe_load(text), text


class PackagesWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.data, self.text = _workflow("packages.yml")

    def test_every_linux_format_the_release_ships_is_built(self):
        # Derived from the tree, not from a list kept here: a fifth format
        # added under packaging/ with no CI job should fail this.
        formats = {
            path.parent.name
            for path in (REPO_ROOT / "packaging").glob("*/build.sh")
        } - {"windows"}  # needs a 193 MiB vendored RetroArch that is gitignored
        self.assertEqual(formats, {"appimage", "deb", "rpm", "flatpak"})
        for fmt in sorted(formats):
            with self.subTest(format=fmt):
                self.assertIn(f'"{fmt}"', self.text)

    def test_pull_requests_build_the_two_cheap_formats(self):
        self.assertIn('targets=\'["deb","rpm"]\'', self.text)

    def test_the_scheduled_run_builds_all_four(self):
        self.assertIn('targets=\'["deb","rpm","appimage","flatpak"]\'', self.text)
        self.assertIn("schedule", self.text)

    def test_one_broken_format_does_not_hide_the_others(self):
        self.assertIs(self.data["jobs"]["build"]["strategy"]["fail-fast"], False)

    def test_the_artifacts_are_uploaded(self):
        steps = self.data["jobs"]["build"]["steps"]
        upload = [s for s in steps if str(s.get("uses", "")).startswith("actions/upload-artifact")]
        self.assertTrue(upload, "a CI build nobody can download is a build nobody tests")
        self.assertEqual(upload[0]["with"]["if-no-files-found"], "error")

    def test_the_build_goes_through_the_shared_entry_point(self):
        # packaging/build.sh is what a maintainer runs locally, so CI running
        # anything else would test a path no release ever takes.
        steps = self.data["jobs"]["build"]["steps"]
        self.assertTrue(
            any("./packaging/build.sh" in str(step.get("run", "")) for step in steps)
        )


if __name__ == "__main__":
    unittest.main()
