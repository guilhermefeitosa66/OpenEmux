"""No build may bake the ScreenScraper credential into the working tree (#250).

Every packaging target injects the project's developer credential with
``packaging/embed_screenscraper_credentials.py``. The rule is that the
injection happens in that target's *staging copy* -- the .deb/.rpm's
``$DESTDIR``, the AppImage's ``AppDir``, the Windows bundle, the Flatpak's
staging tree -- and never in ``src/openemux/core/embedded_credentials.py``,
which is tracked.

The Flatpak build broke that rule: it rewrote the tracked file in place and
restored it from an ``EXIT`` trap, so any ``SIGKILL`` (``docker kill``, an OOM,
a reboot) left the obfuscated credential in a tracked source file, one
``git commit -a`` away from being published.

These are static checks over the packaging inputs, which is all a unit test can
reach -- the builds themselves run in containers.
"""

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Path of the tracked module, relative to the repository root. An injection
#: target that resolves to this is an injection into the working tree.
TRACKED_CREDENTIAL_FILE = "src/openemux/core/embedded_credentials.py"

#: Shell and recipe files that run the injector.
INJECTION_SITES = (
    "packaging/common/stage_tree.sh",
    "packaging/flatpak/build.sh",
    "packaging/appimage/AppImageBuilder.yml",
)

_CONTINUATION = re.compile(r"\\\n\s*")
_INJECTION = re.compile(r'embed_screenscraper_credentials\.py"?\s+"?([^\s"\']+)')
_ASSIGNMENT = re.compile(r'^\s*([A-Z_][A-Z0-9_]*)="?([^"\n]*?)"?\s*$', re.MULTILINE)


def _resolve(target, text):
    """Expand the file's own shell assignments into an injection target.

    Only what is needed to see through ``CRED_FILE="src/..."`` -- the exact
    shape the Flatpak build used to hide the tracked path behind.
    """
    variables = dict(_ASSIGNMENT.findall(text))
    for name, value in variables.items():
        target = target.replace("${%s}" % name, value).replace("$%s" % name, value)
    return target


class InjectionAlwaysTargetsAStagingCopyTests(unittest.TestCase):
    def test_every_injection_site_writes_outside_the_working_tree(self):
        for relative_path in INJECTION_SITES:
            text = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
            joined = _CONTINUATION.sub(" ", text)
            targets = _INJECTION.findall(joined)
            with self.subTest(file=relative_path):
                self.assertTrue(
                    targets, f"{relative_path} no longer runs the injector at all"
                )
                for target in targets:
                    resolved = _resolve(target, text).lstrip("./")
                    self.assertNotEqual(
                        resolved,
                        TRACKED_CREDENTIAL_FILE,
                        f"{relative_path} bakes the credential into the tracked "
                        f"{TRACKED_CREDENTIAL_FILE}",
                    )
                    self.assertFalse(
                        resolved.startswith("src/"),
                        f"{relative_path} injects into the working tree ({resolved})",
                    )

    def test_the_flatpak_build_stages_the_tree_before_injecting(self):
        text = (REPO_ROOT / "packaging/flatpak/build.sh").read_text(encoding="utf-8")
        self.assertIn("mktemp -d", text, "the flatpak build no longer stages its inputs")
        # The old shape, kept out by name: a copy of the tracked file restored
        # by a trap is what this issue is about.
        self.assertNotIn(
            'cp "$CRED_FILE" "${CRED_FILE}.orig"',
            text,
            "the flatpak build is back to editing the tracked file under a trap",
        )


class PoisonedTreeAbortsTheBuildTests(unittest.TestCase):
    """A tree that already carries a blob must not be built from."""

    def setUp(self):
        self.text = (REPO_ROOT / "packaging/build.sh").read_text(encoding="utf-8")

    def test_the_entry_point_checks_the_blob_is_empty(self):
        self.assertIn('_EMBEDDED_BLOB = ""', self.text)
        self.assertIn("exit 1", self.text)

    def test_the_entry_point_refuses_a_leftover_orig(self):
        self.assertIn(".orig", self.text)


class TheWorkingTreeNeverLeaksIntoTheFlatpakTests(unittest.TestCase):
    """`type: dir` copies everything beside the manifest, `.env` included."""

    MANIFEST = "packaging/flatpak/io.github.guilhermefeitosa66.OpenEmux.yaml"

    def test_the_dir_source_skips_the_env_file_and_the_build_artifacts(self):
        text = (REPO_ROOT / self.MANIFEST).read_text(encoding="utf-8")
        skip_block = text.split("skip:", 1)
        self.assertEqual(len(skip_block), 2, "the dir source declares no skip list")
        skipped = {
            line.strip().lstrip("- ").strip()
            for line in skip_block[1].splitlines()
            if line.strip().startswith("- ")
        }
        for entry in (".env", ".git", ".venv", "dist"):
            self.assertIn(entry, skipped, f"the flatpak source still copies {entry}")


class OrphanBackupsStayUncommittableTests(unittest.TestCase):
    def test_gitignore_covers_orig_files(self):
        text = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("*.orig", text.splitlines())


if __name__ == "__main__":
    unittest.main()
