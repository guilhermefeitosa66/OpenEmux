"""The workflows in .github/ are release infrastructure, so the suite guards them.

Nothing here runs CI; these are cheap structural assertions about the workflow
files themselves, which no other check covers. The one they exist for: for a
year no job ever built a package, so a broken .deb/.rpm/AppImage/Flatpak was
only discovered on release day, with the release already half-done (issue #241).
"""

import re
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

    def test_every_format_the_release_ships_is_built(self):
        # Derived from the tree, not from a list kept here: a sixth format
        # added under packaging/ with no CI job should fail this.
        formats = {
            path.parent.name
            for path in (REPO_ROOT / "packaging").glob("*/build.sh")
        }
        self.assertEqual(formats, {"appimage", "deb", "rpm", "flatpak", "windows"})
        for fmt in sorted(formats):
            with self.subTest(format=fmt):
                self.assertIn(f'"{fmt}"', self.text)

    def test_pull_requests_build_the_two_cheap_formats(self):
        self.assertIn('targets=\'["deb","rpm"]\'', self.text)

    def test_the_scheduled_run_builds_all_five(self):
        self.assertIn('targets=\'["deb","rpm","appimage","flatpak","windows"]\'', self.text)
        self.assertIn("schedule", self.text)

    def test_the_windows_build_fetches_its_vendored_retroarch_first(self):
        # The Windows bundle ships RetroArch, and that binary is a gitignored
        # 193 MiB download rather than a committed vendor file -- so this is
        # the one format whose build needs a step before packaging/build.sh.
        # Without it the build stops at the guard in packaging/build.sh, 20
        # minutes of Docker later (issue #118).
        steps = self.data["jobs"]["build"]["steps"]
        names = [step.get("name", "") for step in steps]
        fetch = next(
            (step for step in steps if "vendor-retroarch" in str(step.get("run", ""))),
            None,
        )
        self.assertIsNotNone(fetch, "nothing fetches the vendored RetroArch")
        self.assertIn("windows", str(fetch.get("if", "")))
        build = next(
            index for index, step in enumerate(steps)
            if "./packaging/build.sh" in str(step.get("run", ""))
        )
        self.assertLess(names.index(fetch["name"]), build)

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

    def test_the_suite_also_runs_on_windows(self):
        # Path assumptions are invisible on Linux. Before this job the only way
        # to find one was to build the bundle and run the app by hand, which
        # happened on release day or not at all (issue #118).
        job = self.data["jobs"].get("windows")
        self.assertIsNotNone(job, "nothing runs the suite on Windows")
        self.assertEqual(job["runs-on"], "windows-latest")
        self.assertTrue(
            any("unittest discover" in str(step.get("run", "")) for step in job["steps"]),
            "the Windows job does not run the suite",
        )

    def test_the_windows_job_uses_the_stack_the_bundle_ships(self):
        # Running against some other Python would test a stack no user has:
        # the bundle is MSYS2's MINGW64 packages, and PyGObject cannot be
        # pip-built under it anyway.
        job = self.data["jobs"]["windows"]
        setup = next(
            step for step in job["steps"]
            if str(step.get("uses", "")).startswith("msys2/setup-msys2")
        )
        self.assertEqual(setup["with"]["msystem"], "MINGW64")
        installed = setup["with"]["install"].split()
        bundle = (REPO_ROOT / "packaging/windows/msys2_packages.py").read_text(
            encoding="utf-8"
        )
        for package in ("mingw-w64-x86_64-python-gobject",
                        "mingw-w64-x86_64-gtk4",
                        "mingw-w64-x86_64-libadwaita",
                        "mingw-w64-x86_64-SDL2"):
            with self.subTest(package=package):
                self.assertIn(package, installed)
                self.assertIn(package, bundle)

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
        self.assertGreaterEqual(floor, 53, "the floor is a ratchet; it does not go down")

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


class SecurityWorkflowTests(unittest.TestCase):
    """Scanning main only meant develop -- where all the work lands -- was unaudited."""

    def setUp(self):
        self.data, self.text = _workflow("security.yml")

    def test_it_runs_for_develop_too(self):
        # PyYAML reads the `on:` key as the boolean True (YAML 1.1).
        triggers = self.data[True]
        self.assertIn("develop", triggers["push"]["branches"])
        self.assertIn("develop", triggers["pull_request"]["branches"])
        self.assertIn("main", triggers["push"]["branches"])

    def test_it_audits_both_what_ships_and_what_is_installed(self):
        runs = " ".join(str(s.get("run", "")) for s in self.data["jobs"]["scan"]["steps"])
        self.assertIn("pip-audit -r requirements.lock", runs)
        self.assertIn("pip-audit -r requirements-dev.lock", runs)


class SupplyChainTests(unittest.TestCase):
    """A mutable tag and an un-audited install are the same class of hole."""

    ACTION_REF = re.compile(r"uses:\s*(?P<action>[^@\s]+)@(?P<ref>\S+)")

    def _all_uses(self):
        for path in sorted(WORKFLOW_DIR.glob("*.yml")):
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            ):
                match = self.ACTION_REF.search(line)
                if match:
                    yield f"{path.name}:{number}", match.group("action"), match.group("ref")

    def test_there_are_actions_to_check(self):
        self.assertTrue(list(self._all_uses()))

    def test_every_action_is_pinned_to_a_commit(self):
        # A tag is mutable: whoever can move `v4` runs their own code in the
        # test job, which holds `contents: write` for the badge push.
        for where, action, ref in self._all_uses():
            with self.subTest(action=action, where=where):
                self.assertRegex(
                    ref, r"^[0-9a-f]{40}$", f"{action} is pinned to a mutable ref"
                )

    def test_dependabot_watches_both_ecosystems(self):
        config = yaml.safe_load((REPO_ROOT / ".github/dependabot.yml").read_text())
        ecosystems = {entry["package-ecosystem"] for entry in config["updates"]}
        self.assertEqual(ecosystems, {"github-actions", "pip"})

    def test_the_dev_lock_is_a_superset_of_the_runtime_lock(self):
        # It is generated *from* the runtime lock, so the shipped pins and the
        # installed pins can never drift apart.
        def pins(name):
            return {
                line.strip()
                for line in (REPO_ROOT / name).read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.startswith("#")
            }

        runtime = pins("requirements.lock")
        self.assertTrue(runtime)
        self.assertLessEqual(runtime, pins("requirements-dev.lock"))

    def test_the_makefile_never_calls_the_venv_pip_script(self):
        # A console script bakes the absolute path of the interpreter it was
        # installed against into its shebang, so moving the checkout breaks it
        # -- which is the state this repo was in: .venv/bin/pip still pointed
        # at .../pessoal/opemux/.venv and every recipe using it failed with
        # "bad interpreter".
        makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
        self.assertIn("PIP := $(PYTHON) -m pip", makefile)
        self.assertNotIn("$(VENV)/bin/pip", makefile)

    def test_setup_installs_what_the_audit_reads(self):
        makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
        self.assertIn("$(PIP) install -r requirements.lock", makefile)
        self.assertIn("$(PIP) install -r requirements-dev.lock", makefile)


class LintGateTests(unittest.TestCase):
    """Correctness rules only -- this project has no formatter and keeps none."""

    def setUp(self):
        self.pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")

    def test_ruff_is_configured_for_correctness_not_style(self):
        self.assertIn("[tool.ruff.lint]", self.pyproject)
        selected = next(
            line for line in self.pyproject.splitlines() if line.startswith("select =")
        )
        for rule in ("F", "E9", "PLE"):
            self.assertIn(f'"{rule}"', selected)
        # The formatting families, none of which belong here.
        for style in ("E1", "E2", "E3", "W", "I", "Q", "COM", "ANN", "D"):
            self.assertNotIn(f'"{style}"', selected)

    def test_ci_gates_on_it(self):
        data, _ = _workflow("tests.yml")
        runs = " ".join(str(s.get("run", "")) for s in data["jobs"]["lint"]["steps"])
        self.assertIn("ruff check", runs)


if __name__ == "__main__":
    unittest.main()
