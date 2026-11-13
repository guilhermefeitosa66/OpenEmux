"""The symlink-aware walk and the base-relative comparison (issue #228)."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import os
import time
from unittest import mock

from openemux.core.dir_walk import (
    _identity,
    directory_stamps,
    relative_to_base,
    walk_entries,
    walk_files,
)
from tests.platform_marks import posix_only


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

    @posix_only("chmod 0o000 removes read permission from a directory")
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


class WalkEntriesTests(unittest.TestCase):
    """The scan's walk: one stat per file, taken from the directory entry (issue 901)."""

    def test_every_file_comes_with_its_stat(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.sfc").write_bytes(b"12345")
            (root / "sub").mkdir()
            (root / "sub" / "b.sfc").write_bytes(b"1")
            found = {path.name: info for path, info in walk_entries(root)}
        self.assertEqual(sorted(found), ["a.sfc", "b.sfc"])
        self.assertEqual(found["a.sfc"].st_size, 5)
        self.assertEqual(found["b.sfc"].st_size, 1)

    def test_it_finds_what_walk_files_finds_in_name_order(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("z.sfc", "a.sfc", "m/x.sfc", "b/y.sfc"):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"x")
            found = [path for path, _info in walk_entries(root)]
            self.assertEqual(set(found), set(walk_files(root)))
            # Files of a directory first, a-z, then its subdirectories a-z.
            self.assertEqual(
                [str(path.relative_to(root)) for path in found],
                ["a.sfc", "z.sfc", "b/y.sfc", "m/x.sfc"],
            )

    @posix_only("symlinks")
    def test_a_dangling_link_has_no_stat(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "gone.sfc").symlink_to(root / "nowhere.sfc")
            (root / "here.sfc").write_bytes(b"x")
            found = {path.name: info for path, info in walk_entries(root)}
        self.assertIsNone(found["gone.sfc"])
        self.assertIsNotNone(found["here.sfc"])

    @posix_only("symlinks")
    def test_a_link_to_a_directory_is_descended_into_once(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "real").mkdir()
            (root / "real" / "a.sfc").write_bytes(b"x")
            (root / "link").symlink_to(root / "real", target_is_directory=True)
            (root / "loop").symlink_to(root, target_is_directory=True)
            names = [path.name for path, _info in walk_entries(root)]
        self.assertEqual(names, ["a.sfc"])

    @posix_only("symlinks")
    def test_a_link_to_a_directory_is_a_file_when_links_are_not_followed(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "real").mkdir()
            (root / "link").symlink_to(root / "real", target_is_directory=True)
            found = {path.name: info for path, info in walk_entries(root, follow_symlinks=False)}
        self.assertIn("link", found)
        self.assertIsNone(found["link"])  # a link, not a regular file

    def test_a_socket_or_device_is_not_a_file(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.sfc").write_bytes(b"x")
            fake = mock.Mock(st_mode=0o020000, st_size=0)
            with mock.patch("os.DirEntry.stat", return_value=fake):
                found = dict(walk_entries(root))
        self.assertEqual(list(found.values()), [None])

    def test_an_entry_that_cannot_be_stat_ed_has_no_stat(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.sfc").write_bytes(b"x")
            with mock.patch("os.DirEntry.stat", side_effect=OSError("gone")):
                found = dict(walk_entries(root))
        self.assertEqual(list(found.values()), [None])

    def test_an_entry_whose_kind_cannot_be_read_counts_as_a_file(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "sub").mkdir()
            (root / "sub" / "a.sfc").write_bytes(b"x")
            with mock.patch("os.DirEntry.is_dir", side_effect=OSError("no")):
                found = [path.name for path, _info in walk_entries(root)]
        # The directory was taken for a file; nothing under it was reached.
        self.assertEqual(found, ["sub"])

    def test_an_unreadable_directory_is_skipped(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.sfc").write_bytes(b"x")
            real = os.scandir

            def failing(path):
                if str(path) == str(root):
                    raise PermissionError("no")
                return real(path)

            with mock.patch("os.scandir", failing):
                self.assertEqual(list(walk_entries(root)), [])


class DirectoryStampsTests(unittest.TestCase):
    """The fingerprint the start-up scan compares (issue 901)."""

    def test_every_directory_is_stamped_relative_to_the_root(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "disc" / "deeper").mkdir(parents=True)
            stamps = directory_stamps(root)
        self.assertEqual(sorted(stamps), [".", "disc", os.path.join("disc", "deeper")])
        self.assertTrue(all(isinstance(value, int) for value in stamps.values()))

    def test_adding_a_file_moves_its_folders_stamp_and_no_other(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "disc").mkdir()
            before = directory_stamps(root)
            old = time.time() - 100
            os.utime(root / "disc", (old, old))
            os.utime(root, (old, old))
            before = directory_stamps(root)
            (root / "disc" / "new.sfc").write_bytes(b"x")
            after = directory_stamps(root)
        self.assertNotEqual(before["disc"], after["disc"])
        self.assertEqual(before["."], after["."])

    def test_a_directory_that_vanishes_mid_walk_is_left_out(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "disc").mkdir()
            real = os.stat

            def vanished(path, *args, **kwargs):
                if str(path).endswith("disc"):
                    raise FileNotFoundError("gone")
                return real(path, *args, **kwargs)

            with mock.patch("os.stat", vanished):
                stamps = directory_stamps(root)
        self.assertEqual(list(stamps), ["."])


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


class ADirectoryThatCannotBeStattedTests(unittest.TestCase):
    def test_it_has_no_identity_and_so_never_prunes_the_walk(self):
        # A link into a directory that disappeared between the listing and the
        # stat: unreadable, but not a reason to stop walking the rest.
        with TemporaryDirectory() as tmp_dir:
            self.assertIsNone(_identity(Path(tmp_dir) / "gone"))


if __name__ == "__main__":
    unittest.main()
