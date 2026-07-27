"""Every runtime asset must be declared in pyproject's package-data.

Only the pip-installed builds (the Flatpak) honor that list; the deb, rpm and
AppImage copy ``src/`` wholesale. So an asset missing from package-data is
invisible everywhere except the sandbox, where the feature just silently stops
working -- which is exactly how the cartridge frames went missing after the
art moved from PNG to SVG and the pattern kept saying ``*.png``.
"""

import fnmatch
import re
import unittest
from pathlib import Path

try:  # tomllib landed in 3.11; the venv may still be older
    import tomllib
except ModuleNotFoundError:
    tomllib = None

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = PROJECT_ROOT / "src" / "openemux"

#: Files that live in the package tree but are not read at runtime.
NOT_RUNTIME_ASSETS = {".md"}


def declared_patterns():
    """The ``openemux`` entry of pyproject's package-data table."""
    pyproject = PROJECT_ROOT / "pyproject.toml"
    if tomllib is not None:
        with open(pyproject, "rb") as handle:
            config = tomllib.load(handle)
        return config["tool"]["setuptools"]["package-data"]["openemux"]

    # Python 3.10 has no toml parser in the stdlib and the project declares no
    # test dependencies; the table is a plain list of quoted strings, so read
    # just that one block rather than pulling in tomli for a single test.
    text = pyproject.read_text(encoding="utf-8")
    block = re.search(
        r"^\[tool\.setuptools\.package-data\]\s*$(.*?)(?=^\[|\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    assert block, "package-data table not found in pyproject.toml"
    entry = re.search(r"openemux\s*=\s*\[(.*?)\]", block.group(1), re.DOTALL)
    assert entry, "no openemux entry in package-data"
    return re.findall(r'"([^"]+)"', entry.group(1))


def runtime_assets():
    for path in PACKAGE_ROOT.rglob("*"):
        if not path.is_file() or path.suffix == ".py":
            continue
        if "__pycache__" in path.parts or path.suffix in NOT_RUNTIME_ASSETS:
            continue
        yield path.relative_to(PACKAGE_ROOT)


def covered(relative_path, patterns):
    text = relative_path.as_posix()
    for pattern in patterns:
        # setuptools globs package-data with recursive=True, so "**" spans
        # directories; fnmatch's "*" already crosses "/", which makes it a
        # faithful-enough stand-in for this check.
        if fnmatch.fnmatch(text, pattern.replace("**/", "*")):
            return True
    return False


class PackageDataTests(unittest.TestCase):
    def test_every_runtime_asset_is_declared(self):
        patterns = declared_patterns()
        missing = sorted(
            str(asset) for asset in runtime_assets() if not covered(asset, patterns)
        )
        self.assertEqual(
            missing,
            [],
            "these files ship in src/ but pip would not install them "
            f"(add a pattern to pyproject package-data): {missing}",
        )

    def test_the_cartridge_frames_are_covered(self):
        # The specific regression: 117 SVG frames (9 consoles plus the colour
        # variants) that a "*.png" pattern silently dropped.
        patterns = declared_patterns()
        frames = sorted(
            (PACKAGE_ROOT / "ui/assets/images/cartridges").glob("*.svg")
        )
        self.assertTrue(frames, "no cartridge frames found to check")
        for frame in frames:
            self.assertTrue(
                covered(frame.relative_to(PACKAGE_ROOT), patterns), frame.name
            )

    def test_the_flatpak_build_discards_stale_build_trees(self):
        # The manifest's dir source copies the whole working tree, gitignored
        # build artifacts included, and setuptools reuses build/lib when it is
        # there -- which installed a pre-SVG snapshot of the cartridge art
        # over the real one. The manifest has to clear it first.
        manifest = (
            PROJECT_ROOT
            / "packaging/flatpak/io.github.guilhermefeitosa66.OpenEmux.yaml"
        ).read_text(encoding="utf-8")
        commands = manifest.split("build-commands:", 1)[1].split("sources:", 1)[0]
        rm_line = next(
            (line for line in commands.splitlines() if "rm -rf" in line), ""
        )
        self.assertIn("build", rm_line, "the flatpak build must remove build/ first")
        self.assertLess(
            commands.index("rm -rf"),
            commands.index("pip3 install"),
            "the cleanup must run before pip installs the package",
        )


if __name__ == "__main__":
    unittest.main()
