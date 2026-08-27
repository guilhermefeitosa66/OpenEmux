"""The icons that ship are the icons the UI uses, and their terms travel with them.

Two directions, both of which went wrong:

* Every symbolic icon the UI names must ship as a vendored SVG. The UI asks GTK
  for themed icons by name; hosts whose icon theme does not inherit Adwaita
  (Mint-Y, Papirus, Breeze, ...) or whose adwaita-icon-theme dropped legacy
  names render nothing for them. ``ui/assets/icons/symbolic/`` carries a
  fallback for every name and ``openemux.ui.icons`` registers the directory as
  an icon search path.
* Nothing may ship that the UI never displays. ~18 MB of vendored PNG artwork
  rode into every .deb, .rpm, AppImage and Flatpak without a code path that
  could ever read it -- 168 controller illustrations, six Preferences icons and
  37 console icons for consoles OpenEmux does not support (issue #233).

And what remains is third-party: the console icons are OpenEmu's, the symbolic
icons are Adwaita's, neither is covered by OpenEmux's MIT license, and the
notices have to be in the package rather than only in the repository.
"""

import re
import unittest
import xml.etree.ElementTree as ElementTree
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = PROJECT_ROOT / "src" / "openemux"
ICONS_DIR = PACKAGE_ROOT / "ui" / "assets" / "icons"
SYMBOLIC_DIR = ICONS_DIR / "symbolic"
SYSTEMS_DIR = ICONS_DIR / "systems"
ATTRIBUTION = ICONS_DIR / "ATTRIBUTION.md"
COPYRIGHT = PROJECT_ROOT / "packaging" / "common" / "copyright"


def console_icon_files():
    """The filenames ui/window.py can ask for, @2x fallbacks included."""
    text = (PACKAGE_ROOT / "ui" / "window.py").read_text(encoding="utf-8")
    block = text.split("CONSOLE_ICON_FILES = {", 1)[1].split("}", 1)[0]
    names = set(re.findall(r'"([^"]+\.png)"', block))
    return names | {
        name.replace("@2x.png", ".png") for name in names if name.endswith("@2x.png")
    }

#: Matches themed symbolic icon names as they appear in string literals and
#: CSS (e.g. ``folder-symbolic``, ``applications-games-symbolic``).
ICON_NAME = re.compile(r"[a-z0-9][a-z0-9-]*-symbolic")


def referenced_icon_names():
    names = set()
    sources = list(PACKAGE_ROOT.rglob("*.py")) + [PACKAGE_ROOT / "ui" / "style.css"]
    for source in sources:
        if "__pycache__" in source.parts:
            continue
        names.update(ICON_NAME.findall(source.read_text(encoding="utf-8")))
    return names


class IconAssetTests(unittest.TestCase):
    def test_every_referenced_symbolic_icon_is_bundled(self):
        referenced = referenced_icon_names()
        self.assertTrue(referenced, "no symbolic icon references found in src/")
        missing = sorted(
            name for name in referenced
            if not (SYMBOLIC_DIR / f"{name}.svg").is_file()
        )
        self.assertEqual(
            missing,
            [],
            "these icon names are used by the UI but have no vendored SVG in "
            f"ui/assets/icons/symbolic/: {missing}",
        )

    def test_bundled_icons_are_valid_svg(self):
        svgs = sorted(SYMBOLIC_DIR.glob("*.svg"))
        self.assertTrue(svgs, "no vendored symbolic icons found")
        for svg in svgs:
            root = ElementTree.parse(svg).getroot()
            self.assertTrue(
                root.tag.endswith("svg"), f"{svg.name} is not an SVG document"
            )

    def test_the_license_notice_ships_with_the_icons(self):
        # The icons are Adwaita's (LGPL-3 / CC-BY-SA), not MIT; the notice has
        # to travel with them in every package.
        self.assertTrue((SYMBOLIC_DIR / "LICENSE").is_file())



class NothingShipsThatTheUiNeverDisplaysTests(unittest.TestCase):
    """Every byte here is copied into all four packages."""

    def test_every_console_icon_on_disk_is_one_the_ui_can_ask_for(self):
        wanted = console_icon_files()
        present = {path.name for path in SYSTEMS_DIR.iterdir() if path.is_file()}
        unreferenced = sorted(present - wanted)
        self.assertEqual(
            unreferenced,
            [],
            "these console icons ship in every package and no code path reads "
            f"them: {unreferenced}",
        )

    def test_every_console_icon_the_ui_asks_for_is_on_disk(self):
        present = {path.name for path in SYSTEMS_DIR.iterdir() if path.is_file()}
        # The @2x variant is the one window.py prefers; the plain name is only
        # a fallback, so a missing fallback is not a defect.
        preferred = {name for name in console_icon_files() if "@2x" in name}
        self.assertEqual(sorted(preferred - present), [])

    def test_no_symbolic_icon_ships_unreferenced(self):
        referenced = referenced_icon_names()
        present = {path.stem for path in SYMBOLIC_DIR.glob("*.svg")}
        self.assertEqual(sorted(present - referenced), [])

    def test_the_directories_the_ui_cannot_read_are_gone(self):
        # _asset_path(category, filename) is the only code path that reads an
        # icon by category, and it is called with "systems" and nothing else.
        for category in ("controllers", "settings"):
            with self.subTest(category=category):
                self.assertFalse(
                    (ICONS_DIR / category).exists(),
                    f"{category}/ is back and nothing displays it",
                )


class TheThirdPartyTermsShipWithTheArtworkTests(unittest.TestCase):
    """Installing the bare MIT LICENSE claimed MIT over ~18 MB that was not."""

    def test_every_vendored_directory_has_an_entry_in_the_attribution(self):
        text = ATTRIBUTION.read_text(encoding="utf-8")
        for directory in sorted(
            path.name for path in ICONS_DIR.iterdir() if path.is_dir()
        ):
            with self.subTest(directory=directory):
                self.assertIn(
                    f"`{directory}/`",
                    text,
                    f"{directory}/ ships with no entry in ATTRIBUTION.md",
                )

    def test_the_attribution_records_terms_not_only_provenance(self):
        # It used to name the source repository and commit and stop there,
        # which says where the artwork came from but nothing about what may be
        # done with it.
        text = " ".join(ATTRIBUTION.read_text(encoding="utf-8").split())
        self.assertIn("not covered by OpenEmux's MIT license", text)
        self.assertIn("Redistribution and use in source and binary forms", text)
        self.assertIn("1d205104640d8410659d321809889cbfd06b99a9", text)

    def test_the_attribution_ships_in_the_pip_installed_build(self):
        # The Flatpak installs from package-data rather than copying src/, so
        # a notice missing from that list ships nowhere but the repository.
        pyproject = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn("ui/assets/icons/ATTRIBUTION.md", pyproject)

    def test_the_packaged_copyright_is_not_a_copy_of_the_mit_licence(self):
        text = COPYRIGHT.read_text(encoding="utf-8")
        self.assertTrue(text.startswith("Format: https://www.debian.org/doc/"))
        for license_name in ("MIT", "BSD-3-clause-OpenEmu", "GPL-3+",
                             "LGPL-3 or CC-BY-SA-3.0"):
            with self.subTest(license=license_name):
                self.assertIn(f"License: {license_name}", text)

    def test_every_format_installs_that_copyright(self):
        for relative_path in (
            "packaging/common/stage_tree.sh",
            "packaging/appimage/AppImageBuilder.yml",
            "packaging/flatpak/io.github.guilhermefeitosa66.OpenEmux.yaml",
            "packaging/rpm/openemux.spec",
        ):
            with self.subTest(file=relative_path):
                self.assertIn(
                    "packaging/common/copyright",
                    (PROJECT_ROOT / relative_path).read_text(encoding="utf-8"),
                )


if __name__ == "__main__":
    unittest.main()
