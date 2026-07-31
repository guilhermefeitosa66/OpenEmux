"""Every symbolic icon the UI names must ship as a vendored SVG.

The UI asks GTK for themed icons by name; hosts whose icon theme does not
inherit Adwaita (Mint-Y, Papirus, Breeze, ...) or whose adwaita-icon-theme
dropped legacy names render nothing for them. ``ui/assets/icons/symbolic/``
carries a fallback SVG for every name and ``openemux.ui.icons`` registers the
directory as an icon search path, so no build can lose an icon just because
the host theme lacks it. This test fails when code starts referencing a
symbolic name that has no bundled SVG.
"""

import re
import unittest
import xml.etree.ElementTree as ElementTree
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = PROJECT_ROOT / "src" / "openemux"
SYMBOLIC_DIR = PACKAGE_ROOT / "ui" / "assets" / "icons" / "symbolic"

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


if __name__ == "__main__":
    unittest.main()
