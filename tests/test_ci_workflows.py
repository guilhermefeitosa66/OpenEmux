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


class TestsWorkflowTests(unittest.TestCase):
    """One Python version and no smoke test let two failure classes pass green."""

    def setUp(self):
        self.data, self.text = _workflow("tests.yml")

    def test_the_matrix_covers_every_supported_python(self):
        # pyproject promises >= 3.10 and the .rpm requires python3 >= 3.10;
        # CI ran 3.12 alone, so the floor the project advertises was never
        # exercised and the maintainer's own 3.10 venv broke on code CI liked.
        pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('requires-python = ">=3.10"', pyproject)
        versions = self.data["jobs"]["unittest"]["strategy"]["matrix"]["python-version"]
        self.assertEqual(versions, ["3.10", "3.11", "3.12", "3.13"])

    def test_one_python_version_failing_does_not_cancel_the_rest(self):
        self.assertIs(self.data["jobs"]["unittest"]["strategy"]["fail-fast"], False)

    def test_only_one_version_publishes_the_badge(self):
        # Four jobs force-pushing the same branch would race for no gain.
        steps = self.data["jobs"]["unittest"]["steps"]
        badge = next(s for s in steps if "badge" in s["name"].lower())
        self.assertIn("matrix.python-version == '3.12'", badge["if"])

    def test_the_badge_has_a_band_that_reports_a_problem(self):
        # The ladder bottomed out at orange, so however far coverage fell the
        # badge could never say so.
        self.assertIn("color=red", self.text)

    def test_coverage_has_a_floor(self):
        pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn("[tool.coverage.report]", pyproject)
        floor = next(
            int(line.split("=")[1])
            for line in pyproject.splitlines()
            if line.startswith("fail_under")
        )
        self.assertGreaterEqual(floor, 50, "the floor is a ratchet; it does not go down")

    def test_something_actually_starts_the_app(self):
        smoke = self.data["jobs"]["smoke"]
        run = " ".join(str(step.get("run", "")) for step in smoke["steps"])
        self.assertIn("xvfb-run", run)
        self.assertIn("scripts/smoke_start.py", run)
        self.assertTrue((REPO_ROOT / "scripts/smoke_start.py").exists())


class SmokeScriptTests(unittest.TestCase):
    """The script is CI's only guard on start-up; a few properties are load-bearing."""

    def setUp(self):
        self.text = (REPO_ROOT / "scripts/smoke_start.py").read_text(encoding="utf-8")

    def test_it_never_writes_to_the_real_config_dir(self):
        # A smoke test that seeded a bootstrap into the developer's own
        # ~/.openemux would be worse than no smoke test.
        self.assertIn('os.environ["HOME"] = str(home)', self.text)
        self.assertIn("shutil.rmtree(home", self.text)

    def test_it_does_not_download_every_libretro_core(self):
        self.assertIn("finish_bootstrap_success", self.text)

    def test_it_says_the_check_could_not_be_made_rather_than_passing(self):
        # Exit 2 without a display: absence of evidence is not evidence that
        # the app starts.
        self.assertIn("return 2", self.text)


if __name__ == "__main__":
    unittest.main()
