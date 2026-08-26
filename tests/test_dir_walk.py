"""The symlink-aware walk and the base-relative comparison (issue #228)."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from openemux.core.dir_walk import relative_to_base, walk_files


class WalkFilesTests(unittest.TestCase):
    def _names(self, root):
        return sorted(path.name for path in walk_files(root))

    def test_plain_tree(self):
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "a").mkdir()
            (root / "a" / "one.nes").write_bytes(b"x")
            (root / "two.sfc").write_bytes(b"x")

            self.assertEqual(self._names(root), ["one.nes", "two.sfc"])

    def test_a_symlinked_directory_is_descended_into(self):
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "roms"
            root.mkdir()
            elsewhere = Path(tmp_dir) / "storage"
            elsewhere.mkdir()
            (elsewhere / "deep").mkdir()
            (elsewhere / "deep" / "hidden.iso").write_bytes(b"x")
            (root / "discs").symlink_to(elsewhere, target_is_directory=True)

            self.assertEqual(self._names(root), ["hidden.iso"])

    def test_a_loop_back_to_an_ancestor_terminates(self):
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "roms"
            (root / "sub").mkdir(parents=True)
            (root / "sub" / "game.nes").write_bytes(b"x")
            (root / "sub" / "loop").symlink_to(root, target_is_directory=True)

            self.assertEqual(self._names(root), ["game.nes"])

    def test_two_links_to_the_same_directory_yield_it_once(self):
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "roms"
            root.mkdir(parents=True)
            elsewhere = Path(tmp_dir) / "storage"
            elsewhere.mkdir()
            (elsewhere / "game.iso").write_bytes(b"x")
            (root / "one").symlink_to(elsewhere, target_is_directory=True)
            (root / "two").symlink_to(elsewhere, target_is_directory=True)

            self.assertEqual(self._names(root), ["game.iso"])

    def test_a_dangling_link_is_not_an_error(self):
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "game.nes").write_bytes(b"x")
            (root / "gone").symlink_to(root / "nowhere", target_is_directory=True)

            self.assertIn("game.nes", self._names(root))

    def test_an_unreadable_directory_is_skipped(self):
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "game.nes").write_bytes(b"x")
            locked = root / "locked"
            locked.mkdir()
            (locked / "inside.nes").write_bytes(b"x")
            locked.chmod(0o000)
            try:
                names = self._names(root)
            finally:
                locked.chmod(0o755)

            self.assertEqual(names, ["game.nes"])

    def test_a_missing_root_yields_nothing(self):
        with TemporaryDirectory() as tmp_dir:
            self.assertEqual(list(walk_files(Path(tmp_dir) / "nope")), [])

    def test_following_can_be_turned_off(self):
        with TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir) / "roms"
            root.mkdir()
            elsewhere = Path(tmp_dir) / "storage"
            elsewhere.mkdir()
            (elsewhere / "hidden.iso").write_bytes(b"x")
            (root / "discs").symlink_to(elsewhere, target_is_directory=True)

            names = sorted(p.name for p in walk_files(root, follow_symlinks=False))

        self.assertEqual(names, [])


class RelativeToBaseTests(unittest.TestCase):
    def test_a_plain_child(self):
        self.assertEqual(
            relative_to_base(Path("/roms/SFC/game.sfc"), Path("/roms")),
            Path("SFC/game.sfc"),
        )

    def test_a_symlinked_console_directory_keeps_its_console(self):
        with TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir) / "roms"
            base.mkdir()
            elsewhere = Path(tmp_dir) / "storage"
            elsewhere.mkdir()
            (elsewhere / "game.sfc").write_bytes(b"x")
            (base / "SFC").symlink_to(elsewhere, target_is_directory=True)

            self.assertEqual(
                relative_to_base(base / "SFC" / "game.sfc", base),
                Path("SFC/game.sfc"),
            )

    def test_a_base_reached_through_a_link_still_matches(self):
        """The library root itself can be the link."""
        with TemporaryDirectory() as tmp_dir:
            real = Path(tmp_dir) / "real"
            (real / "SFC").mkdir(parents=True)
            (real / "SFC" / "game.sfc").write_bytes(b"x")
            base = Path(tmp_dir) / "roms"
            base.symlink_to(real, target_is_directory=True)

            self.assertEqual(
                relative_to_base(real / "SFC" / "game.sfc", base),
                Path("SFC/game.sfc"),
            )

    def test_something_genuinely_outside_is_none(self):
        with TemporaryDirectory() as tmp_dir:
            base = Path(tmp_dir) / "roms"
            base.mkdir()
            outside = Path(tmp_dir) / "elsewhere" / "game.sfc"
            outside.parent.mkdir()
            outside.write_bytes(b"x")

            self.assertIsNone(relative_to_base(outside, base))

    def test_the_base_itself_is_the_empty_path(self):
        self.assertEqual(relative_to_base(Path("/roms"), Path("/roms")), Path("."))


if __name__ == "__main__":
    unittest.main()
