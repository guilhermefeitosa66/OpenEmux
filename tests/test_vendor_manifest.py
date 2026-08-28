"""What vendors/manifest.json promises about the emulator every package ships.

Nothing here downloads anything: these are the invariants that make a fetch
*verifiable*, and each of them has failed in a way that is quiet.

The manifest is the only record of what RetroArch is -- it is redistributed,
not built here -- and until issue #328 the Linux entry had neither a version nor
a URL, because the file was committed and nobody had to say where it came from.
`--verify` was broken in the other direction: it compared an extracted tree's
digest with the archive's sha256 and reported a MISMATCH on a perfectly good
vendors/RetroArch-Win64.
"""

import json
import unittest
import unittest.mock
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = REPO_ROOT / "vendors" / "manifest.json"
SCRIPT_PATH = REPO_ROOT / "scripts" / "vendor_retroarch.py"

#: Fields without which an artifact cannot be fetched, checked, or explained to
#: whoever has to bump it next.
REQUIRED_FIELDS = (
    "description",
    "kind",
    "version",
    "url",
    "size",
    "sha256",
    "dest",
    "entrypoint",
    "committed",
    "license",
    "source",
)


def _manifest():
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _artifacts():
    return _manifest()["artifacts"]


class ProvenanceTests(unittest.TestCase):
    def test_every_artifact_records_where_it_came_from(self):
        for name, entry in _artifacts().items():
            with self.subTest(artifact=name):
                for field in REQUIRED_FIELDS:
                    self.assertIn(field, entry)
                    self.assertIsNotNone(
                        entry[field], f"{name}.{field} is null; it cannot be fetched"
                    )

    def test_the_url_names_the_version_it_claims(self):
        # A recorded version that the URL does not serve is a version nobody
        # can reproduce -- which is what the Linux entry was until issue #328.
        for name, entry in _artifacts().items():
            with self.subTest(artifact=name):
                self.assertIn(entry["version"], entry["url"])

    def test_both_hashes_are_recorded_for_a_tree(self):
        # sha256 pins the download; tree_sha256 pins what unpacking it
        # produced, which is what ships and the only one --verify can still
        # check once the download cache is gone.
        for name, entry in _artifacts().items():
            with self.subTest(artifact=name):
                self.assertRegex(entry["sha256"], r"^[0-9a-f]{64}$")
                self.assertRegex(entry["tree_sha256"], r"^[0-9a-f]{64}$")
                self.assertNotEqual(entry["sha256"], entry["tree_sha256"])

    def test_nothing_is_committed_to_git(self):
        # Both are directory trees of loose binaries -- 29 MiB and 556 MiB --
        # and git history carries them forever, for every clone on every
        # platform (issues #118, #328).
        gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
        for name, entry in _artifacts().items():
            with self.subTest(artifact=name):
                self.assertFalse(entry["committed"])
                self.assertIn(f"{entry['dest']}/", gitignore)


class LinuxArtifactTests(unittest.TestCase):
    """The entry that replaced the committed AppImage (issue #328)."""

    def setUp(self):
        self.entry = _artifacts()["linux-x86_64"]

    def test_it_is_the_upstream_archive_unwrapped(self):
        self.assertEqual(self.entry["kind"], "appimage-in-7z")
        self.assertTrue(self.entry["url"].startswith("https://buildbot.libretro.com/"))
        self.assertIn("/linux/x86_64/", self.entry["url"])

    def test_the_entrypoint_is_the_binary_the_launcher_execs(self):
        from openemux.core.platform import VENDORED_RETROARCH

        vendored = f"{self.entry['dest']}/{self.entry['entrypoint']}"
        # Only meaningful on a Linux x86_64 checkout; elsewhere the app points
        # at that platform's own artifact and this entry is not the one it uses.
        if VENDORED_RETROARCH.startswith("vendors/RetroArch-Linux-x86_64/"):
            self.assertEqual(vendored, VENDORED_RETROARCH)
        self.assertEqual(self.entry["entrypoint"], "usr/bin/retroarch")

    def test_no_appimage_is_vendored_any_more(self):
        # The acceptance criterion of issue #328: no Linux artifact ships one.
        for name, entry in _artifacts().items():
            with self.subTest(artifact=name):
                self.assertFalse(entry["dest"].endswith(".AppImage"))


class ArchitectureTests(unittest.TestCase):
    def test_there_is_no_arm_artifact_to_fetch(self):
        # libretro publishes none, so `make vendor-retroarch` on a Pi must be a
        # no-op rather than a failure -- and must never fetch the x86_64 one
        # (issue #119).
        self.assertNotIn("linux-aarch64", _artifacts())

    def test_the_default_artifact_is_named_for_this_machine(self):
        # The whole suite runs on Windows and on ARM runners too, so the
        # machine is faked rather than read -- which is also the only way to
        # cover the ARM answer from an x86_64 desktop.
        script = _load_script()

        for machine, expected in (
            ("x86_64", "linux-x86_64"),
            ("aarch64", "linux-aarch64"),
        ):
            with self.subTest(machine=machine):
                with unittest.mock.patch.object(script.sys, "platform", "linux"), \
                        unittest.mock.patch.object(
                            script.platform, "machine", lambda m=machine: m
                        ):
                    self.assertEqual(script.default_artifact_name(), expected)

        with unittest.mock.patch.object(script.sys, "platform", "win32"):
            self.assertEqual(script.default_artifact_name(), "win64")


class CacheNamingTests(unittest.TestCase):
    def test_each_artifact_caches_its_download_under_its_own_name(self):
        # libretro publishes every platform's archive as RetroArch.7z, so keyed
        # on the URL's basename alone the Windows and Linux downloads are the
        # same file and each fetch overwrites the other.
        script = _load_script()
        paths = {
            name: script.cache_path(name, entry["url"])
            for name, entry in _artifacts().items()
        }
        self.assertEqual(len(set(paths.values())), len(paths))
        for name, path in paths.items():
            with self.subTest(artifact=name):
                self.assertIn(name, path.name)


class VerifyChecksTheRightHashTests(unittest.TestCase):
    """`make verify-vendors` failed on a tree that was exactly right."""

    def test_a_tree_is_checked_against_the_tree_hash(self):
        script = _load_script()
        entry = {"kind": "archive-7z", "sha256": "a" * 64, "tree_sha256": "b" * 64}
        self.assertTrue(script.unpacks_to_a_tree(entry))
        self.assertEqual(script.recorded_digest(entry), "b" * 64)

    def test_a_plain_file_is_still_checked_against_its_own_hash(self):
        script = _load_script()
        entry = {"kind": "file", "sha256": "a" * 64}
        self.assertFalse(script.unpacks_to_a_tree(entry))
        self.assertEqual(script.recorded_digest(entry), "a" * 64)


def _load_script():
    """scripts/vendor_retroarch.py, which is not importable as a package."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("vendor_retroarch", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


if __name__ == "__main__":
    unittest.main()
