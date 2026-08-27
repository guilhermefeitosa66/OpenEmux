"""No sandbox permission is added to the Flatpak without somebody noticing (#257).

`--talk-name=org.freedesktop.Flatpak` allows ``flatpak-spawn --host`` with
arbitrary commands -- unrestricted code execution outside the sandbox -- and
combined with ``--filesystem=home`` the sandbox provides essentially no
confinement. Both are architecturally required by the current launch design:
OpenEmux drives an emulator that lives in its own Flatpak, on the host.

The defect was never that they are there. It was that they were unremarked
lines in a manifest, on an app heading for Flathub, whose linter asks for a
justification in the submission. This file is the thing that keeps them
remarked: the permission set is written down here, so adding one fails until
the manifest explains it and this list is updated deliberately.
"""

import unittest
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ID = "io.github.guilhermefeitosa66.OpenEmux"
MANIFEST = REPO_ROOT / f"packaging/flatpak/{APP_ID}.yaml"

#: Exactly what the sandbox is allowed to ask for. Changing this list is the
#: point: a new permission is a deliberate edit here plus a rationale in the
#: manifest, not a line that slips through review.
EXPECTED_FINISH_ARGS = [
    "--socket=wayland",
    "--socket=fallback-x11",
    "--share=ipc",
    "--device=dri",
    "--share=network",
    "--filesystem=home",
    "--filesystem=~/.var/app/org.libretro.RetroArch:ro",
    "--talk-name=org.freedesktop.Flatpak",
]

#: The two Flathub calls out, and what the manifest has to say about each.
WIDEST_PERMISSIONS = {
    "--talk-name=org.freedesktop.Flatpak": (
        "flatpak-spawn",
        "retroarch_launcher.py",
    ),
    "--filesystem=home": (
        "Gtk.FileChooserDialog",
        "issue #235",
        "DEFAULT_CONFIG_DIR",
        "--appendconfig",
    ),
}


def _manifest():
    return yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))


class ThePermissionSetIsWrittenDownTests(unittest.TestCase):
    def test_the_sandbox_asks_for_exactly_these(self):
        self.assertEqual(_manifest()["finish-args"], EXPECTED_FINISH_ARGS)

    def test_nothing_wider_has_crept_in(self):
        # The ones that would make the rest of this file pointless.
        for permission in ("--filesystem=host", "--socket=session-bus",
                           "--socket=system-bus", "--share=all",
                           "--talk-name=org.freedesktop.systemd1"):
            with self.subTest(permission=permission):
                self.assertNotIn(permission, _manifest()["finish-args"])


class EveryWidePermissionCarriesItsRationaleTests(unittest.TestCase):
    """Flathub asks for the justification; it lives beside the line."""

    def setUp(self):
        self.text = MANIFEST.read_text(encoding="utf-8")

    def test_the_manifest_explains_the_two_widest(self):
        for permission, expected_terms in WIDEST_PERMISSIONS.items():
            for term in expected_terms:
                with self.subTest(permission=permission, term=term):
                    self.assertIn(
                        term,
                        self.text,
                        f"the rationale for {permission} no longer mentions {term}",
                    )

    def test_it_says_plainly_what_the_combination_means(self):
        self.assertIn("no confinement", self.text)

    def test_the_packaging_readme_says_the_same(self):
        readme = (REPO_ROOT / "packaging/README.md").read_text(encoding="utf-8")
        self.assertIn("--talk-name=org.freedesktop.Flatpak", readme)
        self.assertIn("--filesystem=home", readme)


class TheStatedPrerequisiteForNarrowingIsStillTrueTests(unittest.TestCase):
    """The rationale claims things about the code; they have to hold."""

    def test_the_permission_is_used_where_the_manifest_says_it_is(self):
        launcher = (
            REPO_ROOT / "src/openemux/core/retroarch_launcher.py"
        ).read_text(encoding="utf-8")
        self.assertIn("flatpak-spawn", launcher)
        self.assertIn("org.libretro.RetroArch", launcher)

    def test_the_file_choosers_that_make_home_load_bearing_are_still_there(self):
        # Three Gtk.FileChooserDialog uses -- the in-process widget, which does
        # not go through the portal. When issue #235 ports them to
        # Gtk.FileDialog this fails, which is the moment to revisit
        # --filesystem=home rather than leave it granted out of habit.
        sources = [
            REPO_ROOT / "src/openemux/ui/window.py",
            REPO_ROOT / "src/openemux/ui/artwork_manager.py",
        ]
        total = sum(
            source.read_text(encoding="utf-8").count("Gtk.FileChooserDialog(")
            for source in sources
        )
        self.assertEqual(
            total,
            3,
            "the non-portal file choosers changed; --filesystem=home and the "
            "rationale in the Flatpak manifest need revisiting (issue #257)",
        )

    def test_the_app_still_keeps_its_data_under_the_real_home(self):
        config = (REPO_ROOT / "src/openemux/core/config.py").read_text(encoding="utf-8")
        self.assertIn('DEFAULT_CONFIG_DIR = Path.home() / ".openemux"', config)


if __name__ == "__main__":
    unittest.main()
