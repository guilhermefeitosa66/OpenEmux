"""The MSYS2 environment the Windows bundle is assembled from (#527).

``packaging/windows/msys2_packages.py`` names the environment once, and the
staging step, the CI job and the developer setup all follow it. These tests run
offline: nothing here reaches ``repo.msys2.org``.
"""

import contextlib
import hashlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "packaging/windows/msys2_packages.py"


def load_msys2_packages():
    spec = importlib.util.spec_from_file_location("msys2_packages", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


msys2 = load_msys2_packages()


class EnvironmentTests(unittest.TestCase):
    def test_the_bundle_comes_from_ucrt64(self):
        # MSYS2 dropped GTK 4 and libadwaita from MINGW64; UCRT64 still ships
        # the whole set.
        self.assertEqual(msys2.ENVIRONMENT, "ucrt64")
        self.assertEqual(msys2.PACKAGE_PREFIX, "mingw-w64-ucrt-x86_64-")
        self.assertEqual(msys2.REPO_URL, "https://repo.msys2.org/mingw/ucrt64")
        self.assertEqual(msys2.DB_NAME, "ucrt64.db")

    def test_every_root_carries_the_environment_prefix(self):
        self.assertEqual(len(msys2.ROOT_PACKAGES), 15)
        for package in msys2.ROOT_PACKAGES:
            with self.subTest(package=package):
                self.assertTrue(package.startswith(msys2.PACKAGE_PREFIX))
        self.assertIn("mingw-w64-ucrt-x86_64-gtk4", msys2.ROOT_PACKAGES)
        self.assertIn("mingw-w64-ucrt-x86_64-libadwaita", msys2.ROOT_PACKAGES)


class CommittedLockTests(unittest.TestCase):
    def setUp(self):
        self.lock = json.loads(msys2.LOCK_PATH.read_text(encoding="utf-8"))

    def test_the_lock_was_generated_for_this_environment(self):
        self.assertEqual(self.lock["repository"], msys2.REPO_URL)
        self.assertEqual(self.lock["roots"], msys2.ROOT_PACKAGES)

    def test_every_locked_package_belongs_to_the_environment(self):
        for package in self.lock["packages"]:
            with self.subTest(package=package["name"]):
                self.assertTrue(package["name"].startswith(msys2.PACKAGE_PREFIX))
                self.assertTrue(package["filename"].startswith(msys2.PACKAGE_PREFIX))

    def test_every_root_is_in_the_closure(self):
        locked = {package["name"] for package in self.lock["packages"]}
        for root in msys2.ROOT_PACKAGES:
            with self.subTest(root=root):
                self.assertIn(root, locked)

    def test_load_lock_accepts_the_committed_lock(self):
        self.assertEqual(msys2.load_lock()["repository"], msys2.REPO_URL)


class StaleLockTests(unittest.TestCase):
    """A lock from another environment must fail before anything downloads."""

    STALE = {
        "repository": "https://repo.msys2.org/mingw/mingw64",
        "packages": [
            {
                "name": "mingw-w64-x86_64-gtk4",
                "filename": "mingw-w64-x86_64-gtk4-4.22.4-1-any.pkg.tar.zst",
                "sha256": "0" * 64,
            }
        ],
    }

    def test_download_refuses_a_lock_for_another_environment(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(msys2, "_fetch") as fetch:
            with self.assertRaises(SystemExit) as raised:
                msys2.download(self.STALE, Path(tmp) / "cache")
            self.assertFalse((Path(tmp) / "cache").exists())
        fetch.assert_not_called()
        message = str(raised.exception)
        self.assertIn("mingw/mingw64", message)
        self.assertIn(msys2.REPO_URL, message)
        self.assertIn("--update", message)

    def test_download_refuses_a_lock_with_no_repository(self):
        # The old fallback quietly used whatever REPO_URL said, which would
        # fetch an old environment's filenames from the new environment's
        # repository.
        document = {"packages": []}
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SystemExit):
                msys2.download(document, Path(tmp) / "cache")

    def test_load_lock_refuses_a_stale_lock_on_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            stale = Path(tmp) / "packages.lock"
            stale.write_text(json.dumps(self.STALE), encoding="utf-8")
            with mock.patch.object(msys2, "LOCK_PATH", stale):
                with self.assertRaises(SystemExit) as raised:
                    msys2.load_lock()
        self.assertIn("--update", str(raised.exception))

    def test_a_matching_lock_downloads_from_its_repository(self):
        blob = b"package bytes"
        document = {
            "repository": msys2.REPO_URL,
            "packages": [
                {
                    "name": "mingw-w64-ucrt-x86_64-gtk4",
                    "filename": "mingw-w64-ucrt-x86_64-gtk4-4.24.1-1-any.pkg.tar.zst",
                    "sha256": hashlib.sha256(blob).hexdigest(),
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(msys2, "_fetch", return_value=blob) as fetch, \
                contextlib.redirect_stdout(io.StringIO()):
            paths = msys2.download(document, Path(tmp) / "cache")
            self.assertEqual(paths[0].read_bytes(), blob)
        fetch.assert_called_once_with(
            f"{msys2.REPO_URL}/mingw-w64-ucrt-x86_64-gtk4-4.24.1-1-any.pkg.tar.zst"
        )


if __name__ == "__main__":
    unittest.main()
