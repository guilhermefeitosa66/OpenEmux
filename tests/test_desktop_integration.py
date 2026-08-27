import unittest
from pathlib import Path

from openemux.main import _is_packaged_install
from tests.platform_marks import linux_only


class PackagedInstallDetectionTests(unittest.TestCase):
    """A packaged install must not write a user-level desktop entry.

    ~/.local/share/applications takes precedence over /usr/share/applications,
    so an entry written by the app shadows the one the .deb/.rpm installs.
    """

    @linux_only("/opt is an FHS path; the installer owns the Start Menu on Windows")
    def test_deb_rpm_install_root_is_packaged(self):
        self.assertTrue(_is_packaged_install("/opt/openemux"))

    @linux_only("/usr and /usr/local are FHS paths")
    def test_usr_prefix_is_packaged(self):
        self.assertTrue(_is_packaged_install("/usr/lib/openemux"))
        self.assertTrue(_is_packaged_install("/usr/local/lib/openemux"))

    def test_source_checkout_is_not_packaged(self):
        self.assertFalse(_is_packaged_install("/home/someone/projects/OpenEmux"))
        self.assertFalse(_is_packaged_install(Path.home() / "src" / "OpenEmux"))

    def test_prefix_match_is_on_path_boundaries(self):
        # /opting is not /opt: a bare startswith on "/opt" would misfire.
        self.assertFalse(_is_packaged_install("/opting/openemux"))
        self.assertFalse(_is_packaged_install("/usrlocal/openemux"))

    @linux_only("the paths it is given are FHS paths")
    def test_accepts_path_and_str(self):
        self.assertTrue(_is_packaged_install(Path("/opt/openemux")))
        self.assertTrue(_is_packaged_install("/opt/openemux"))


if __name__ == "__main__":
    unittest.main()
