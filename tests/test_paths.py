import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from opemux.core.paths import get_project_root, is_running_in_appimage, resolve_project_path


class PathsTests(unittest.TestCase):
    def test_get_project_root_prefers_environment_override(self):
        with TemporaryDirectory() as tmp_dir:
            with patch.dict(os.environ, {"OPEMUX_PROJECT_ROOT": tmp_dir}, clear=False):
                self.assertEqual(get_project_root(), Path(tmp_dir).resolve())

    def test_is_running_in_appimage_checks_standard_vars(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(is_running_in_appimage())
        with patch.dict(os.environ, {"APPDIR": "/tmp/AppDir"}, clear=True):
            self.assertTrue(is_running_in_appimage())

    def test_resolve_project_path_uses_project_root_for_relative_values(self):
        with TemporaryDirectory() as tmp_dir:
            with patch.dict(os.environ, {"OPEMUX_PROJECT_ROOT": tmp_dir}, clear=False):
                resolved = resolve_project_path("vendors/RetroArch-Linux-x86_64.AppImage")
        self.assertEqual(
            resolved,
            (Path(tmp_dir) / "vendors" / "RetroArch-Linux-x86_64.AppImage").resolve(),
        )


if __name__ == "__main__":
    unittest.main()
