"""The listing behind Big Picture's pad file browser (issue 957)."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from openemux.core import pad_browser


class TheListing(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = self.root = Path(self.tmp.name)
        (root / "b-folder").mkdir()
        (root / "A-folder").mkdir()
        (root / ".hidden").mkdir()
        (root / "game.SFC").write_text("x")
        (root / "alpha.zip").write_text("x")
        (root / "notes.txt").write_text("x")
        (root / ".secret.sfc").write_text("x")
        os.symlink(root / "missing", root / "broken.sfc")

    def names(self, **kwargs):
        return [(e.name, e.is_dir) for e in pad_browser.list_dir(self.root, ["sfc", ".zip"], **kwargs)]

    def test_folders_first_then_importable_files(self):
        self.assertEqual(
            self.names(),
            [("A-folder", True), ("b-folder", True), ("alpha.zip", False), ("game.SFC", False)],
        )

    def test_hidden_entries_on_request(self):
        names = [name for name, _d in self.names(show_hidden=True)]
        self.assertIn(".hidden", names)
        self.assertIn(".secret.sfc", names)

    def test_an_unreadable_folder_is_empty(self):
        self.assertEqual(pad_browser.list_dir(self.root / "nope", ["sfc"]), [])

    def test_an_entry_that_cannot_be_stat_is_skipped(self):
        real = os.scandir

        class Bad:
            name = "bad.sfc"
            path = "/x/bad.sfc"

            def is_dir(self):
                raise OSError("gone")

        class Wrapper:
            def __init__(self, path):
                self.inner = real(path)

            def __enter__(self):
                return self

            def __iter__(self):
                return iter(list(self.inner) + [Bad()])

            def __exit__(self, *args):
                self.inner.close()

        with mock.patch("openemux.core.pad_browser.os.scandir", Wrapper):
            names = [e.name for e in pad_browser.list_dir(self.root, ["sfc"])]
        self.assertNotIn("bad.sfc", names)

    def test_parent_and_start(self):
        self.assertEqual(pad_browser.parent(self.root / "A-folder"), self.root)
        self.assertIsNone(pad_browser.parent(Path("/")))
        self.assertEqual(pad_browser.start_folder(str(self.root)), self.root)
        self.assertEqual(pad_browser.start_folder(str(self.root / "nope")), Path.home())
        self.assertEqual(pad_browser.start_folder(None), Path.home())


if __name__ == "__main__":
    unittest.main()
