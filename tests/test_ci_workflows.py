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

from tests.test_msys2_packages import load_msys2_packages

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = REPO_ROOT / ".github/workflows"

msys2 = load_msys2_packages()


def _workflow(name):
    text = (WORKFLOW_DIR / name).read_text(encoding="utf-8")
    # PyYAML reads the `on:` key as the boolean True (YAML 1.1); keep the raw
    # text around for the assertions that care about it.
    return yaml.safe_load(text), text


class PackagesWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.data, self.text = _workflow("packages.yml")

    def test_every_format_the_release_ships_is_built(self):
        # Derived from the tree, not from a list kept here: a seventh format
        # added under packaging/ with no CI job should fail this.
        formats = {
            path.parent.name
            for path in (REPO_ROOT / "packaging").glob("*/build.sh")
        }
        self.assertEqual(
            formats, {"appimage", "deb", "rpm", "arch", "flatpak", "windows"}
        )
        for fmt in sorted(formats):
            with self.subTest(format=fmt):
                self.assertIn(f'"{fmt}"', self.text)

    def _plan(self, event, choice=""):
        """Run the plan step's own script, the way the workflow runs it."""
        import json
        import subprocess
        import textwrap

        marker = 'python3 - "$EVENT" "$CHOICE" <<\'PY\' >> "$GITHUB_OUTPUT"\n'
        body = self.text.split(marker)[1].split("\n          PY\n")[0]
        result = subprocess.run(
            ["python3", "-c", textwrap.dedent(body), event, choice],
            capture_output=True, text=True, check=True,
        )
        line = next(l for l in result.stdout.splitlines() if l.startswith("jobs="))
        return [(j["target"], j["arch"]) for j in json.loads(line[len("jobs="):])]

    def test_pull_requests_build_the_two_cheap_formats_on_both_arches(self):
        # The ARM leg especially: nobody builds it by hand, so it is the one
        # that would regress in silence (issue #119).
        self.assertEqual(
            sorted(self._plan("pull_request")),
            [("deb", "aarch64"), ("deb", "x86_64"),
             ("rpm", "aarch64"), ("rpm", "x86_64")],
        )

    def test_the_scheduled_run_builds_every_format_for_every_architecture(self):
        planned = sorted(self._plan("schedule"))
        self.assertEqual(planned, sorted([
            ("appimage", "x86_64"), ("appimage", "aarch64"),
            ("deb", "x86_64"), ("deb", "aarch64"),
            ("flatpak", "x86_64"), ("flatpak", "aarch64"),
            ("rpm", "x86_64"), ("rpm", "aarch64"),
            # x86_64 only: the official archlinux image is amd64-only, and
            # nothing cross-builds a Windows bundle from ARM.
            ("arch", "x86_64"),
            ("windows", "x86_64"),
        ]))
        self.assertIn("schedule", self.text)

    def test_there_is_no_windows_bundle_for_arm(self):
        # Out of scope in the issue, and nothing cross-builds one from ARM.
        for event, choice in (("schedule", ""), ("workflow_dispatch", "all"),
                              ("workflow_dispatch", "aarch64")):
            with self.subTest(event=event, choice=choice):
                self.assertNotIn(("windows", "aarch64"), self._plan(event, choice))

    def test_there_is_no_arch_package_for_arm(self):
        # The PKGBUILD itself declares aarch64 and `makepkg` builds it on Arch
        # Linux ARM; what does not exist is a container to build it in --
        # the official `archlinux` image publishes amd64 only.
        for event, choice in (("schedule", ""), ("workflow_dispatch", "all"),
                              ("workflow_dispatch", "aarch64")):
            with self.subTest(event=event, choice=choice):
                self.assertNotIn(("arch", "aarch64"), self._plan(event, choice))

    def test_a_dispatch_can_ask_for_arm_alone(self):
        self.assertEqual(
            sorted(self._plan("workflow_dispatch", "aarch64")),
            [("appimage", "aarch64"), ("deb", "aarch64"),
             ("flatpak", "aarch64"), ("rpm", "aarch64")],
        )

    def test_the_arm_jobs_run_on_an_arm_runner(self):
        # A "build ARM on ARM" job scheduled onto an x86_64 runner produces an
        # x86_64 package with an ARM name, which is the worst of both.
        self.assertIn("ubuntu-24.04-arm", self.text)
        self.assertEqual(self.data["jobs"]["build"]["runs-on"],
                         "${{ matrix.runs-on }}")

    def test_every_bundled_emulator_is_fetched_first(self):
        # Nothing is committed to git: the Windows bundle needs a 193 MiB
        # download and the three x86_64 Linux formats a 171 MiB one, so each of
        # them needs a step before packaging/build.sh. Without it the build
        # stops at that script's guard, after the Docker image has been built
        # (issues #118, #328).
        steps = self.data["jobs"]["build"]["steps"]
        names = [step.get("name", "") for step in steps]
        fetch = next(
            (step for step in steps if "vendor-retroarch" in str(step.get("run", ""))),
            None,
        )
        self.assertIsNotNone(fetch, "nothing fetches the vendored RetroArch")
        # Named, not inferred. `make vendor-retroarch` takes the artifact for
        # the host it runs on, and every runner here is Linux -- so the Windows
        # leg has to ask for win64 by name or it fetches the Linux tree and
        # stops at its own guard twenty seconds later.
        self.assertIn("vendor-retroarch-win64", str(fetch["run"]))
        self.assertIn("make vendor-retroarch\n", str(fetch["run"]))
        build = next(
            index for index, step in enumerate(steps)
            if "./packaging/build.sh" in str(step.get("run", ""))
        )
        self.assertLess(names.index(fetch["name"]), build)

    def test_the_formats_that_bundle_nothing_skip_the_download(self):
        # The Flatpak launches the host's org.libretro.RetroArch, and libretro
        # publishes no ARM build at all -- so neither has anything to fetch,
        # and a 171 MiB download on those legs would be pure waste.
        steps = self.data["jobs"]["build"]["steps"]
        decide = next(
            step for step in steps if step.get("id") == "bundles"
        )
        run = str(decide["run"])
        self.assertIn("windows:*", run)
        self.assertIn("appimage:x86_64|deb:x86_64|rpm:x86_64", run)
        for step in steps:
            if "vendor-retroarch" in str(step.get("run", "")) or step.get("id") == "bundles":
                continue
            if "7zip" in str(step.get("run", "")) or "actions/cache" in str(step.get("uses", "")):
                self.assertEqual(
                    step.get("if"), "steps.bundles.outputs.artifact != ''",
                    f"{step.get('name')} runs on legs that bundle no emulator",
                )

    def test_make_windows_fetches_what_it_needs(self):
        # Same trap, on the maintainer's side: the docs said `make
        # vendor-retroarch` before `make windows`, which on Linux fetches the
        # wrong artifact. The dependency makes the build self-serve.
        makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
        self.assertIn("windows: vendor-retroarch-win64", makefile)
        self.assertIn("vendor_retroarch.py win64", makefile)

    def test_one_broken_format_does_not_hide_the_others(self):
        self.assertIs(self.data["jobs"]["build"]["strategy"]["fail-fast"], False)

    def test_the_artifacts_are_uploaded(self):
        steps = self.data["jobs"]["build"]["steps"]
        upload = [s for s in steps if str(s.get("uses", "")).startswith("actions/upload-artifact")]
        self.assertTrue(upload, "a CI build nobody can download is a build nobody tests")
        # A *successful* build that produced nothing is a broken job, and must
        # say so. A failed one legitimately has nothing to hand back, and
        # turning that into a second error would bury the first.
        self.assertIn("'error'", str(upload[0]["with"]["if-no-files-found"]))
        self.assertEqual(upload[0].get("if"), "always()",
                         "an artifact thrown away on failure is a diagnosis "
                         "nobody can make")

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

    def _windows_setup(self):
        job = self.data["jobs"]["windows"]
        return next(
            step for step in job["steps"]
            if str(step.get("uses", "")).startswith("msys2/setup-msys2")
        )

    def test_the_windows_job_uses_the_stack_the_bundle_ships(self):
        # Running against some other Python would test a stack no user has:
        # the bundle is MSYS2's UCRT64 packages, and PyGObject cannot be
        # pip-built under it anyway. Every bundle root is installed, not a
        # hand-picked few, so the WebP and SVG loaders the tests read are the
        # ones users get (issue #527).
        setup = self._windows_setup()
        self.assertEqual(setup["with"]["msystem"], msys2.ENVIRONMENT.upper())
        installed = setup["with"]["install"].split()
        for package in msys2.ROOT_PACKAGES:
            with self.subTest(package=package):
                self.assertIn(package, installed)

    def test_the_windows_job_installs_nothing_from_another_environment(self):
        installed = self._windows_setup()["with"]["install"].split()
        for package in installed:
            with self.subTest(package=package):
                self.assertTrue(
                    package == "make" or package.startswith(msys2.PACKAGE_PREFIX),
                    f"{package} is not a {msys2.ENVIRONMENT} package",
                )

    def test_the_windows_job_cannot_pass_with_a_failed_step(self):
        # A package that cannot be installed has to turn the job red: that is
        # the only reason the two-week MINGW64 outage was visible at all.
        job = self.data["jobs"]["windows"]
        self.assertNotIn("continue-on-error", job)
        for step in job["steps"]:
            with self.subTest(step=step.get("name")):
                self.assertNotIn("continue-on-error", step)

    def test_the_windows_job_installs_the_cairo_the_bundle_ships(self):
        # This job takes MSYS2's updates, and cairo 1.18.6-1 once aborted GTK 4
        # at the first window it presented -- exit code 3, no failing test, a
        # third of the way into the suite, on every branch at once. It installs
        # the cairo named by the bundle's lock instead: one version rather than
        # two that can drift, and it moves the day the lock moves.
        job = self.data["jobs"]["windows"]
        run = " ".join(str(step.get("run", "")) for step in job["steps"])
        self.assertIn("packaging/windows/packages.lock", run)
        self.assertIn(msys2.PACKAGE_PREFIX + "cairo", run)
        self.assertIn("pacman -U", run)

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
        # Four jobs computing and uploading the same payload would race for no
        # gain. Every badge step in the matrix job carries the condition, not
        # just the first one.
        steps = self.data["jobs"]["unittest"]["steps"]
        badge = [s for s in steps if "badge" in s["name"].lower()]
        self.assertTrue(badge, "nothing in the test job produces the badge data")
        for step in badge:
            with self.subTest(step=step["name"]):
                self.assertIn("matrix.python-version == '3.12'", step["if"])

    def test_the_workflow_is_read_only_by_default(self):
        # Stated in the file rather than inherited from a repository setting
        # somebody could flip without touching this workflow.
        self.assertEqual(self.data["permissions"], {"contents": "read"})

    def test_the_badge_push_does_not_share_a_job_with_the_test_run(self):
        # `contents: write` used to sit on the whole unittest job, so the token
        # that can force-push to this repository was held while that job
        # installed the pull request's dependencies and ran its test suite. A
        # fork gets a read-only token whatever the workflow asks for, but an
        # internal branch does not, and there is no reason to run anybody's
        # code next to a write token. The push now lives in a job that checks
        # nothing out and never runs on a pull request.
        jobs = self.data["jobs"]
        self.assertNotIn(
            "write",
            str(jobs["unittest"].get("permissions", "")),
            "the job that runs the suite must not hold a write token",
        )

        badge = jobs["badge"]
        self.assertEqual(badge["permissions"], {"contents": "write"})
        self.assertIn("github.event_name == 'push'", badge["if"])
        self.assertIn("refs/heads/develop", badge["if"])
        self.assertFalse(
            any("actions/checkout" in str(s.get("uses", "")) for s in badge["steps"]),
            "the badge job must not check the repository out",
        )

    def test_the_badge_data_reaches_the_job_that_pushes_it(self):
        # The two halves are joined by an artifact name; a rename on one side
        # alone would leave the badge silently frozen at its last value.
        upload = next(
            s for s in self.data["jobs"]["unittest"]["steps"]
            if str(s.get("uses", "")).startswith("actions/upload-artifact")
        )
        download = next(
            s for s in self.data["jobs"]["badge"]["steps"]
            if str(s.get("uses", "")).startswith("actions/download-artifact")
        )
        self.assertEqual(upload["with"]["name"], download["with"]["name"])
        # It may need more than the tests (the site-only gate, #487), but
        # never less: the artifact only exists once they ran.
        needs = self.data["jobs"]["badge"]["needs"]
        self.assertIn("unittest", [needs] if isinstance(needs, str) else needs)

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


class HeadlessHostRunTests(unittest.TestCase):
    """A host test run never draws on the developer's screen (issue #528)."""

    def setUp(self):
        self.makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")

    def recipe(self, target):
        match = re.search(rf"^{target}:\n((?:\t.*\n)+)", self.makefile, re.M)
        self.assertIsNotNone(match, f"no {target} target")
        return match.group(1)

    def test_test_and_coverage_go_through_the_launcher(self):
        self.assertIn("scripts/run_tests.py $(PYTHON) -m unittest discover",
                      self.recipe("test"))
        coverage = self.recipe("coverage")
        self.assertIn("scripts/run_tests.py $(PYTHON) -m coverage run", coverage)
        # The report reads a data file; it needs no display.
        self.assertIn("\t$(PYTHON) -m coverage report", coverage)
        self.assertTrue((REPO_ROOT / "scripts/run_tests.py").exists())

    def test_install_sys_deps_installs_xvfb(self):
        self.assertRegex(self.recipe("install-sys-deps"), r"\bxvfb\b")

    def test_the_devbox_marks_its_display_as_private(self):
        script = (REPO_ROOT / "devbox/bin/devbox-tests").read_text(encoding="utf-8")
        self.assertIn("export OPENEMUX_TESTS_PRIVATE_DISPLAY=1", script)
        driver = (REPO_ROOT / "devbox/devbox.sh").read_text(encoding="utf-8")
        self.assertIn("inside env OPENEMUX_TESTS_PRIVATE_DISPLAY=1 devbox-tests", driver)
        # Not on every command: `exec` keeps the host's DISPLAY.
        self.assertNotIn("-- env OPENEMUX_TESTS_PRIVATE_DISPLAY=1 \"$@\"", driver)


if __name__ == "__main__":
    unittest.main()


class WindowsPackageSetTests(unittest.TestCase):
    """CI, the bundle and the developer setup install one MSYS2 set (#527).

    The bundle's roots in ``msys2_packages.py`` are the reference. The CI job
    is checked above; the two developer entry points are checked here. Each
    may install more (make, git, coverage, 7zip), never less.
    """

    def test_make_install_sys_deps_windows_holds_every_bundle_root(self):
        makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
        recipe = makefile.split("install-sys-deps-windows:\n", 1)[1].split("\n\n", 1)[0]
        installed = recipe.replace("\\", " ").split()
        for package in msys2.ROOT_PACKAGES:
            with self.subTest(package=package):
                self.assertIn(package, installed)

    def test_setup_dev_ps1_holds_every_bundle_root(self):
        script = (REPO_ROOT / "scripts/windows/setup-dev.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn(f'"{msys2.PACKAGE_PREFIX}$_"', script)
        self.assertIn(f"$Msystem = '{msys2.ENVIRONMENT.upper()}'", script)
        listed = script.split("$MingwPackages = @(", 1)[1].split("\n)", 1)[0]
        names = {msys2.PACKAGE_PREFIX + name for name in re.findall(r"'([^']+)'", listed)}
        for package in msys2.ROOT_PACKAGES:
            with self.subTest(package=package):
                self.assertIn(package, names)

    def test_dev_shell_opens_the_same_environment(self):
        script = (REPO_ROOT / "scripts/windows/dev-shell.cmd").read_text(
            encoding="utf-8"
        )
        self.assertIn(f"msys2_shell.cmd\" -{msys2.ENVIRONMENT} ", script)

    def test_nothing_left_points_at_mingw64(self):
        # MSYS2 no longer ships GTK 4 or libadwaita for MINGW64, so any
        # reference left in the build, CI or the setup scripts is a step that
        # will fail -- or, worse, install a stack nothing else tests.
        roots = [
            REPO_ROOT / ".github/workflows",
            REPO_ROOT / "packaging/windows",
            REPO_ROOT / "packaging/docker/windows.Dockerfile",
            REPO_ROOT / "scripts/windows",
            REPO_ROOT / "scripts/vendor_retroarch.py",
            REPO_ROOT / "Makefile",
            REPO_ROOT / "THIRD_PARTY_NOTICES.md",
        ]
        stale = re.compile(r"mingw64|mingw-w64-x86_64-", re.IGNORECASE)
        for root in roots:
            files = [root] if root.is_file() else sorted(
                path for path in root.rglob("*")
                if path.is_file() and path.suffix != ".pyc"
            )
            for path in files:
                text = path.read_text(encoding="utf-8", errors="replace")
                with self.subTest(path=str(path.relative_to(REPO_ROOT))):
                    self.assertIsNone(stale.search(text))

