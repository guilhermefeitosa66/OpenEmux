"""Every installed icon is exactly the size its directory claims.

Read off the staged files, not off the script: this is a bug that only exists
in the *output*. `stage_tree.sh` installed the source logo -- 735x776, neither
square nor 512 -- straight into `hicolor/512x512/apps`, and rendered the rest
with `-resize NxN`, which fits inside a box and preserves aspect ratio. So the
six icons the .deb, the .rpm and the Arch package shipped measured 30x32,
45x48, 61x64, 121x128, 242x256 and 735x776, each one filed under a size it was
not. Every assertion here passes on a script that reads perfectly and installs
the wrong thing, so the test measures the PNGs.

The small sizes are new. A Plasma menu asks for 22 or 24 pixels and GNOME's
overview for 32; the ladder started at 32 and everything below it was resolved
by scaling something much larger down.
"""

import os
import shutil
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.platform_marks import posix_only

REPO_ROOT = Path(__file__).resolve().parents[1]
STAGE_ICONS = REPO_ROOT / "packaging" / "common" / "stage_icons.sh"
LOGO = REPO_ROOT / "src" / "openemux" / "ui" / "assets" / "images" / "logo.png"
APP_ID = "io.github.guilhermefeitosa66.OpenEmux"

#: The sizes a desktop actually asks for, smallest first. 16-32 are menu and
#: list rows, 48-128 the launcher grid, 256-512 the software centre.
EXPECTED_SIZES = (16, 22, 24, 32, 48, 64, 128, 256, 512)

HAVE_IMAGEMAGICK = bool(shutil.which("magick") or shutil.which("convert"))


def png_dimensions(path):
    """(width, height) straight out of the PNG's IHDR -- no image library."""
    header = path.read_bytes()[:24]
    if header[:8] != b"\x89PNG\r\n\x1a\n":
        raise AssertionError(f"{path} is not a PNG")
    return struct.unpack(">II", header[16:24])


@posix_only("the FHS icon layout the Linux packages install into")
@unittest.skipUnless(HAVE_IMAGEMAGICK, "ImageMagick renders the icon sizes")
class StagedIconTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.destdir = Path(cls._tmp.name)
        subprocess.run(
            ["sh", str(STAGE_ICONS)],
            check=True,
            capture_output=True,
            env={
                **os.environ,
                "DESTDIR": str(cls.destdir),
                "APP_ID": APP_ID,
                "LOGO": str(LOGO),
            },
        )
        cls.icons = cls.destdir / "usr" / "share" / "icons" / "hicolor"

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_the_whole_ladder_is_installed(self):
        installed = sorted(
            int(entry.name.split("x")[0]) for entry in self.icons.iterdir()
        )
        self.assertEqual(installed, sorted(EXPECTED_SIZES))

    def test_each_icon_measures_what_its_directory_claims(self):
        for size in EXPECTED_SIZES:
            path = self.icons / f"{size}x{size}" / "apps" / f"{APP_ID}.png"
            with self.subTest(size=size):
                self.assertTrue(path.is_file(), f"{path} was not installed")
                self.assertEqual(png_dimensions(path), (size, size))

    def test_the_pixmaps_fallback_is_one_moderate_square(self):
        # Read by the menus that do no theme lookup at all, so it must not be
        # the raw 735x776 artwork.
        path = self.destdir / "usr" / "share" / "pixmaps" / f"{APP_ID}.png"
        self.assertTrue(path.is_file())
        self.assertEqual(png_dimensions(path), (48, 48))

    def test_every_icon_is_world_readable(self):
        # Installed by ImageMagick rather than `install -m`, so the mode comes
        # from the build's umask unless it is set explicitly -- and an icon
        # only root can read is an icon the session never draws.
        for path in self.destdir.rglob("*.png"):
            with self.subTest(path=path.name):
                self.assertEqual(path.stat().st_mode & 0o777, 0o644)


class TheSourceLogoIsStillTheOddShapeThisGuardsTests(unittest.TestCase):
    """If the logo is ever replaced with a square 512, say so out loud.

    The padding exists because the source is 735x776. Swapping in a square
    master would make every assertion above pass for a different reason, and
    the next person should be told rather than left to assume.
    """

    def test_the_logo_is_not_square(self):
        width, height = png_dimensions(LOGO)
        self.assertNotEqual(
            (width, height),
            (512, 512),
            "logo.png is now a square 512 -- stage_icons.sh's padding may be "
            "redundant; check before removing it",
        )


if __name__ == "__main__":
    unittest.main()
