"""What a bug report says about the machine (issue #461)."""

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from openemux.core import sysinfo


def _run_returning(stdout="", stderr=""):
    return mock.Mock(return_value=mock.Mock(stdout=stdout, stderr=stderr))


class TheDistributionTests(unittest.TestCase):
    def _release(self, text):
        handle = tempfile.NamedTemporaryFile("w", suffix="os-release", delete=False)
        handle.write(text)
        handle.close()
        self.addCleanup(Path(handle.name).unlink)
        return Path(handle.name)

    def test_the_pretty_name_wins(self):
        path = self._release('NAME="Linux Mint"\nPRETTY_NAME="Linux Mint 22.3"\n')
        self.assertEqual(sysinfo.distribution(paths=(path,)), "Linux Mint 22.3")

    def test_name_and_version_stand_in_for_a_missing_pretty_name(self):
        path = self._release("NAME=Fedora\nVERSION='42 (Workstation)'\nnot a field\n")
        self.assertEqual(sysinfo.distribution(paths=(path,)), "Fedora 42 (Workstation)")

    def test_lsb_release_is_the_fallback(self):
        run = _run_returning('"Some Distro 1.0"\n')
        with mock.patch.object(sysinfo.shutil, "which", return_value="/usr/bin/lsb_release"):
            name = sysinfo.distribution(paths=(Path("/nonexistent"),), run=run)
        self.assertEqual(name, "Some Distro 1.0")

    def test_a_failing_lsb_release_leaves_it_unknown(self):
        run = mock.Mock(side_effect=OSError("gone"))
        with mock.patch.object(sysinfo.shutil, "which", return_value="/usr/bin/lsb_release"):
            self.assertEqual(sysinfo.distribution(paths=(), run=run), sysinfo.UNKNOWN)

    def test_an_empty_answer_leaves_it_unknown(self):
        path = self._release("ID=thing\n")
        with mock.patch.object(sysinfo.shutil, "which", return_value="/usr/bin/lsb_release"):
            name = sysinfo.distribution(paths=(path,), run=_run_returning(""))
        self.assertEqual(name, sysinfo.UNKNOWN)

    def test_without_any_source_it_is_unknown(self):
        with mock.patch.object(sysinfo.shutil, "which", return_value=None):
            self.assertEqual(sysinfo.distribution(paths=()), sysinfo.UNKNOWN)

    def test_windows_names_itself(self):
        with mock.patch.object(sysinfo.sys, "platform", "win32"):
            self.assertTrue(sysinfo.distribution().startswith("Windows"))


class TheDesktopTests(unittest.TestCase):
    def test_desktop_and_session_as_announced(self):
        env = {"XDG_CURRENT_DESKTOP": "GNOME", "XDG_SESSION_TYPE": "wayland"}
        self.assertEqual(sysinfo.desktop(env), "GNOME · Wayland")

    def test_the_session_is_inferred_from_the_display_variables(self):
        self.assertEqual(sysinfo.desktop({"WAYLAND_DISPLAY": "wayland-0"}), "unknown · Wayland")
        self.assertEqual(sysinfo.desktop({"DISPLAY": ":0"}), "unknown · X11")
        self.assertEqual(sysinfo.desktop({}), "unknown · unknown")

    def test_windows_is_just_windows(self):
        with mock.patch.object(sysinfo.sys, "platform", "win32"):
            self.assertEqual(sysinfo.desktop({}), "Windows")


class TheInstallFormatTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(sysinfo, "is_running_in_flatpak", return_value=False)
        self.flatpak = patcher.start()
        self.addCleanup(patcher.stop)

    def test_each_format_is_told_apart(self):
        self.assertEqual(sysinfo.install_format({"APPIMAGE": "/x.AppImage"}), "AppImage")
        self.assertEqual(
            sysinfo.install_format({}, project_root="/opt/openemux/lib"), "Package (.deb / .rpm)"
        )
        self.assertEqual(
            sysinfo.install_format({}, project_root="/usr/share/openemux"), "Distribution package"
        )
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(sysinfo.install_format({}, project_root=root), sysinfo.UNKNOWN)
            (Path(root) / ".git").mkdir()
            self.assertEqual(sysinfo.install_format({}, project_root=root), "Built from source")

    def test_the_project_root_is_looked_up_when_not_given(self):
        with mock.patch.object(sysinfo, "get_project_root", return_value=Path("/opt/openemux")):
            self.assertEqual(sysinfo.install_format({}), "Package (.deb / .rpm)")

    def test_flatpak_and_windows(self):
        self.flatpak.return_value = True
        self.assertEqual(sysinfo.install_format({}), "Flatpak")
        with mock.patch.object(sysinfo.sys, "platform", "win32"):
            self.assertEqual(sysinfo.install_format({}), "Windows")


class TheRetroArchLineTests(unittest.TestCase):
    def test_the_version_is_found_on_any_line(self):
        run = _run_returning(stderr="Frontend for libretro -- v1.19.1 -- abc\n")
        self.assertEqual(sysinfo.retroarch("/bin/ra", run=run), "1.19.1 · /bin/ra")

    def test_no_version_in_the_output(self):
        self.assertEqual(
            sysinfo.retroarch("/bin/ra", run=_run_returning("nothing")), "version unknown · /bin/ra"
        )

    def test_a_binary_that_will_not_run(self):
        run = mock.Mock(side_effect=subprocess.TimeoutExpired("ra", 5))
        self.assertEqual(sysinfo.retroarch("/bin/ra", run=run), "version unknown · /bin/ra")

    def test_none_on_the_path(self):
        with mock.patch.object(sysinfo.shutil, "which", return_value=None):
            self.assertEqual(sysinfo.retroarch(), "not found on PATH")


class TheRestTests(unittest.TestCase):
    def test_toolkit_line(self):
        self.assertTrue(sysinfo.toolkit_versions("4.14", "1.5").startswith("GTK 4.14 · libadwaita 1.5 · Python"))
        self.assertTrue(sysinfo.toolkit_versions().startswith("Python"))

    def test_language_falls_back_to_lang(self):
        with mock.patch.object(sysinfo.locale, "getlocale", side_effect=ValueError), \
                mock.patch.dict(sysinfo.os.environ, {"LANG": "pt_BR.UTF-8"}):
            self.assertEqual(sysinfo.language(), "pt_BR.UTF-8")
        with mock.patch.object(sysinfo.locale, "getlocale", return_value=(None, None)), \
                mock.patch.dict(sysinfo.os.environ, {}, clear=True):
            self.assertEqual(sysinfo.language(), sysinfo.UNKNOWN)

    def test_collect_and_render(self):
        with mock.patch.object(sysinfo, "retroarch", return_value="1.0 · /ra"):
            facts = sysinfo.collect(gtk="4", adwaita="1")
        labels = [label for label, _ in facts]
        self.assertEqual(labels[:2], ["OpenEmux", "System"])
        text = sysinfo.as_text(facts)
        self.assertIn("RetroArch  1.0 · /ra", text)


if __name__ == "__main__":
    unittest.main()
