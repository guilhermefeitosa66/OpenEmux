"""Architecture is a parameter, not a constant (issue #119).

Every Linux artifact was x86_64 by assumption: the buildbot URL, the vendored
RetroArch's filename, the Debian multiarch core directory, the AppImage recipe.
Each of those is now derived, and each of them is a place where getting it
wrong is *silent* -- an ARM install downloads x86_64 cores that fetch perfectly
and then refuse to load, with nothing in the UI to say why.

These run on x86_64 with the architecture faked, which is the only way to cover
the ARM side from the machine this project is developed on.
"""

import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from openemux.core import platform as pf

REPO_ROOT = Path(__file__).resolve().parents[1]


class MachineNamesTests(unittest.TestCase):
    """One spelling, whatever the OS calls it."""

    def test_the_x86_64_spellings_all_normalise(self):
        for raw in ("x86_64", "AMD64", "amd64", "x64", " X86_64 "):
            with self.subTest(raw=raw):
                self.assertEqual(pf._machine(raw), "x86_64")

    def test_the_arm_spellings_all_normalise(self):
        for raw in ("aarch64", "arm64", "ARM64", "armv8l"):
            with self.subTest(raw=raw):
                self.assertEqual(pf._machine(raw), "aarch64")

    def test_an_unknown_architecture_is_passed_through(self):
        # riscv64 is out of scope, but reporting it truthfully beats claiming
        # the machine is an x86_64 it is not.
        self.assertEqual(pf._machine("riscv64"), "riscv64")

    def test_no_answer_at_all_falls_back_to_x86_64(self):
        self.assertEqual(pf._machine(""), "x86_64")


class VendoredRetroArchTests(unittest.TestCase):
    def test_the_linux_appimage_is_named_for_the_architecture(self):
        # An x86_64 AppImage on an ARM machine is not a RetroArch that failed
        # to start; it is a file the kernel refuses to execute.
        self.assertIn(pf.MACHINE, pf.VENDORED_RETROARCH)
        self.assertTrue(pf.VENDORED_RETROARCH.endswith(".AppImage"))


class CoresUrlTests(unittest.TestCase):
    def test_the_default_names_this_platform_and_this_architecture(self):
        from openemux.core.config import DEFAULT_CORES_BASE_URL

        self.assertIn(f"/{pf.BUILDBOT_OS}/{pf.BUILDBOT_ARCH}/", DEFAULT_CORES_BASE_URL)

    def test_every_combination_is_recognised_as_a_default(self):
        from openemux.core.config import BUILDBOT_CORES_URL, KNOWN_CORES_BASE_URLS

        self.assertEqual(len(KNOWN_CORES_BASE_URLS), 4)
        for os_name in pf.BUILDBOT_OSES:
            for arch in pf.BUILDBOT_ARCHES:
                with self.subTest(os=os_name, arch=arch):
                    self.assertIn(
                        BUILDBOT_CORES_URL.format(os=os_name, arch=arch),
                        KNOWN_CORES_BASE_URLS,
                    )

    def test_another_architectures_default_is_corrected(self):
        # The library copied from an x86_64 desktop onto a Pi. Cores from the
        # x86_64 tree download perfectly and then never load.
        from openemux.core.config import DEFAULT_CORES_BASE_URL, migrate_cores_base_url

        other = "https://buildbot.libretro.com/nightly/linux/aarch64/latest/"
        if other == DEFAULT_CORES_BASE_URL:
            other = "https://buildbot.libretro.com/nightly/linux/x86_64/latest/"
        self.assertEqual(migrate_cores_base_url(other), DEFAULT_CORES_BASE_URL)

    def test_another_platforms_default_is_corrected_too(self):
        from openemux.core.config import DEFAULT_CORES_BASE_URL, migrate_cores_base_url

        windows = "https://buildbot.libretro.com/nightly/windows/x86_64/latest/"
        self.assertEqual(migrate_cores_base_url(windows), DEFAULT_CORES_BASE_URL)

    def test_a_url_the_user_chose_is_left_alone(self):
        # Silently overwriting somebody's own mirror would be the worse bug.
        from openemux.core.config import migrate_cores_base_url

        mine = "https://mirror.example.invalid/libretro/cores/"
        self.assertEqual(migrate_cores_base_url(mine), mine)

    def test_this_machines_own_default_is_left_alone(self):
        from openemux.core.config import DEFAULT_CORES_BASE_URL, migrate_cores_base_url

        self.assertEqual(
            migrate_cores_base_url(DEFAULT_CORES_BASE_URL), DEFAULT_CORES_BASE_URL
        )

    def test_nothing_stored_gets_this_machines_default(self):
        from openemux.core.config import DEFAULT_CORES_BASE_URL, migrate_cores_base_url

        for empty in (None, ""):
            with self.subTest(stored=empty):
                self.assertEqual(migrate_cores_base_url(empty), DEFAULT_CORES_BASE_URL)


class CoreSearchDirTests(unittest.TestCase):
    def test_the_multiarch_directory_follows_the_architecture(self):
        # /usr/lib/<triplet>/libretro is where Debian and Ubuntu put the
        # packaged cores, and the triplet is the one thing in that list that
        # changes with the machine.
        from openemux.core.retroarch_launcher import DEFAULT_CORE_DIRS

        self.assertIn(f"/usr/lib/{pf.MACHINE}-linux-gnu/libretro", DEFAULT_CORE_DIRS)


class AppImageRecipeTests(unittest.TestCase):
    """One recipe, rendered per architecture."""

    RENDER = REPO_ROOT / "packaging/appimage/arch_recipe.py"
    RECIPE = REPO_ROOT / "packaging/appimage/AppImageBuilder.yml"

    def _render(self, arch):
        result = subprocess.run(
            ["python3", str(self.RENDER), str(self.RECIPE), "--arch", arch],
            capture_output=True, text=True, check=True,
        )
        return result.stdout

    def test_x86_64_is_byte_identical_to_the_file_in_git(self):
        # The issue's own requirement: phase 1 is mechanical and must not move
        # the x86_64 artifacts at all.
        self.assertEqual(self._render("x86_64"),
                         self.RECIPE.read_text(encoding="utf-8"))

    def test_aarch64_changes_exactly_the_four_values_that_vary(self):
        rendered = self._render("aarch64")
        self.assertIn("  arch: aarch64\n", rendered)
        self.assertIn("    arch: arm64\n", rendered)
        self.assertIn("aarch64-linux-gnu", rendered)
        self.assertNotIn("x86_64", rendered)
        self.assertNotIn("amd64", rendered)

    def test_arm_packages_come_from_the_ports_archive(self):
        # ARM builds are not on archive.ubuntu.com at all -- pointing apt there
        # fails to find a single package.
        rendered = self._render("aarch64")
        self.assertIn("ports.ubuntu.com/ubuntu-ports", rendered)
        self.assertNotIn("archive.ubuntu.com", rendered)

    def test_the_package_list_is_not_duplicated(self):
        rendered = self._render("aarch64")
        original = self.RECIPE.read_text(encoding="utf-8")
        for package in ("libgtk-4-1", "libadwaita-1-0", "webp-pixbuf-loader",
                        "gir1.2-rsvg-2.0", "python3-gi-cairo"):
            with self.subTest(package=package):
                self.assertIn(package, rendered)
                self.assertIn(package, original)

    def test_a_moved_anchor_fails_loudly(self):
        # The whole risk of a textual render: a recipe edit that silently stops
        # matching would produce an x86_64 recipe on an ARM machine, which
        # builds and then does not run.
        import importlib.util

        spec = importlib.util.spec_from_file_location("arch_recipe", self.RENDER)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with self.assertRaises(module.RecipeError):
            module.render("nothing that looks like the recipe", "aarch64")

    def test_an_unknown_architecture_is_refused(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location("arch_recipe", self.RENDER)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with self.assertRaises(module.RecipeError):
            module.render(self.RECIPE.read_text(encoding="utf-8"), "riscv64")


class MissingCoreMessageTests(unittest.TestCase):
    """What the user is told when no core resolves."""

    def _message(self, machine):
        from tempfile import TemporaryDirectory

        from tests.test_retroarch_launcher import _DummyConfig
        from openemux.core.retroarch_launcher import RetroArchLauncher

        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            cfg = _DummyConfig(base, base / "retroarch", base / "nope.so")
            launcher = RetroArchLauncher(base, cfg)
            with patch("openemux.core.retroarch_launcher.MACHINE", machine), \
                 patch.object(launcher, "_find_core_path", lambda *a, **k: None), \
                 patch.object(launcher, "_launch_prefix", lambda **k: (["ra"], None)):
                _process, error = launcher.launch_process(
                    str(base / "g.gba"), "GBA"
                )
        return error

    def test_on_x86_64_it_points_at_the_configuration(self):
        message = self._message("x86_64")
        self.assertIn("No RetroArch core found", message)
        self.assertIn("config.yaml", message)

    def test_on_arm_it_says_the_core_may_not_exist_at_all(self):
        # 153 of the buildbot's 217 cores are built for aarch64. Telling
        # somebody to configure a core that was never built for their machine
        # sends them looking for a file they cannot get.
        message = self._message("aarch64")
        self.assertIn("No RetroArch core found", message)
        self.assertIn("fewer cores for aarch64", message)
        self.assertNotIn("config.yaml", message)


if __name__ == "__main__":
    unittest.main()


class LauncherFallbackChainTests(unittest.TestCase):
    """With no vendored RetroArch, resolution degrades instead of dead-ending.

    libretro publishes no ARM build, so on aarch64 "nothing vendored" is the
    normal case rather than an anomaly, and stopping there would ship an
    install that can never launch a game (issue #119).
    """

    def _launcher(self, tmp):
        from tests.test_retroarch_launcher import _DummyConfig
        from openemux.core.retroarch_launcher import RetroArchLauncher

        base = Path(tmp)
        cfg = _DummyConfig(base, base / "no-such-retroarch", base / "core.so")
        return RetroArchLauncher(base, cfg)

    def test_a_packaged_retroarch_on_path_is_used(self):
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tmp:
            launcher = self._launcher(tmp)
            with patch("openemux.core.retroarch_launcher.shutil.which",
                       lambda name: "/usr/bin/retroarch" if name == "retroarch" else None):
                self.assertEqual(launcher._resolve_retroarch_binary(),
                                 "/usr/bin/retroarch")

    def test_a_retroarch_flatpak_is_the_next_resort(self):
        from tempfile import TemporaryDirectory

        class _Installed:
            returncode = 0

        with TemporaryDirectory() as tmp:
            launcher = self._launcher(tmp)
            with patch("openemux.core.retroarch_launcher.shutil.which",
                       lambda name: "/usr/bin/flatpak" if name == "flatpak" else None), \
                 patch("openemux.core.retroarch_launcher.subprocess.run",
                       lambda *a, **k: _Installed()):
                prefix, error = launcher._launch_prefix()
            self.assertIsNone(error)
            self.assertEqual(prefix[:2], ["flatpak", "run"])
            self.assertIn("org.libretro.RetroArch", prefix)

    def test_a_flatpak_that_is_not_installed_is_not_offered(self):
        from tempfile import TemporaryDirectory

        class _Absent:
            returncode = 1

        with TemporaryDirectory() as tmp:
            launcher = self._launcher(tmp)
            with patch("openemux.core.retroarch_launcher.shutil.which",
                       lambda name: "/usr/bin/flatpak" if name == "flatpak" else None), \
                 patch("openemux.core.retroarch_launcher.subprocess.run",
                       lambda *a, **k: _Absent()):
                prefix, error = launcher._launch_prefix()
            self.assertIsNone(prefix)
            self.assertIn("RetroArch was not found", error)

    def test_the_final_message_names_every_way_out(self):
        # It is the last thing the user sees, so it has to be the one that
        # tells them what to do -- especially on ARM, where nothing is bundled.
        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tmp:
            launcher = self._launcher(tmp)
            with patch("openemux.core.retroarch_launcher.shutil.which",
                       lambda name: None):
                prefix, error = launcher._launch_prefix()
        self.assertIsNone(prefix)
        self.assertIn("distribution", error)
        self.assertIn("flatpak install", error)
        self.assertIn("runtime.retroarch.binary", error)
