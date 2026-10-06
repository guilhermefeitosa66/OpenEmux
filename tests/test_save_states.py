"""Save-state browsing over the managed states directory (issue #73)."""

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from openemux.core import save_states

ROM = "/roms/SFC/Chrono Trigger (USA).sfc"


class ListStatesTests(unittest.TestCase):
    def _touch(self, directory, name):
        path = Path(directory) / name
        path.write_bytes(b"state")
        return path

    def test_slots_are_parsed_and_sorted(self):
        with TemporaryDirectory() as tmp_dir:
            self._touch(tmp_dir, "Chrono Trigger (USA).state3")
            self._touch(tmp_dir, "Chrono Trigger (USA).state")
            self._touch(tmp_dir, "Chrono Trigger (USA).state1")
            states = save_states.list_states(tmp_dir, ROM)
            self.assertEqual([s.slot for s in states], [0, 1, 3])

    def test_other_roms_and_junk_are_ignored(self):
        with TemporaryDirectory() as tmp_dir:
            self._touch(tmp_dir, "Chrono Trigger (USA).state")
            self._touch(tmp_dir, "Terranigma.state")           # another ROM
            self._touch(tmp_dir, "Chrono Trigger (USA).state.auto")  # auto state
            self._touch(tmp_dir, "Chrono Trigger (USA).state.png")   # screenshot
            self._touch(tmp_dir, "notes.txt")
            states = save_states.list_states(tmp_dir, ROM)
            self.assertEqual([s.slot for s in states], [0])

    def test_companion_thumbnail_is_attached_when_present(self):
        with TemporaryDirectory() as tmp_dir:
            self._touch(tmp_dir, "Chrono Trigger (USA).state2")
            thumb = self._touch(tmp_dir, "Chrono Trigger (USA).state2.png")
            no_thumb = save_states.list_states(tmp_dir, ROM)
            self.assertEqual(no_thumb[0].thumbnail, thumb)
            thumb.unlink()
            self.assertIsNone(save_states.list_states(tmp_dir, ROM)[0].thumbnail)

    def test_missing_directory_is_empty(self):
        self.assertEqual(save_states.list_states("/nope/nothing", ROM), [])

    def test_states_sorted_into_core_subdirectories_are_found(self):
        # RetroArch with sort_savestates_enable files states under
        # <console>/<Core Name>/ -- the layout that hid the user's saves.
        with TemporaryDirectory() as tmp_dir:
            core_dir = Path(tmp_dir) / "Snes9x"
            core_dir.mkdir()
            (core_dir / "Chrono Trigger (USA).state").write_bytes(b"s")
            thumb = core_dir / "Chrono Trigger (USA).state.png"
            thumb.write_bytes(b"p")
            states = save_states.list_states(tmp_dir, ROM)
            self.assertEqual([s.slot for s in states], [0])
            self.assertEqual(states[0].thumbnail, thumb)

    def test_same_slot_in_two_places_keeps_the_newest(self):
        import os

        with TemporaryDirectory() as tmp_dir:
            flat = Path(tmp_dir) / "Chrono Trigger (USA).state"
            flat.write_bytes(b"old")
            os.utime(flat, (1000, 1000))
            core_dir = Path(tmp_dir) / "bsnes"
            core_dir.mkdir()
            newer = core_dir / "Chrono Trigger (USA).state"
            newer.write_bytes(b"new")
            os.utime(newer, (2000, 2000))
            states = save_states.list_states(tmp_dir, ROM)
            self.assertEqual(len(states), 1)
            self.assertEqual(states[0].path, newer)


class SlotEntriesTests(unittest.TestCase):
    """The context menu's slot list: full range, empties visible (issue #73)."""

    def test_full_range_with_empties_as_none(self):
        with TemporaryDirectory() as tmp_dir:
            (Path(tmp_dir) / "Chrono Trigger (USA).state").write_bytes(b"s")
            (Path(tmp_dir) / "Chrono Trigger (USA).state4").write_bytes(b"s")
            entries = save_states.slot_entries(tmp_dir, ROM)
        self.assertEqual(len(entries), 10)
        self.assertEqual([slot for slot, _ in entries], list(range(10)))
        filled = {slot for slot, mtime in entries if mtime is not None}
        self.assertEqual(filled, {0, 4})

    def test_missing_directory_is_all_empty(self):
        entries = save_states.slot_entries("/nope/nothing", ROM)
        self.assertTrue(all(mtime is None for _slot, mtime in entries))
        self.assertEqual(len(entries), 10)


class DeleteStateTests(unittest.TestCase):
    def test_delete_removes_state_and_screenshot(self):
        with TemporaryDirectory() as tmp_dir:
            state_file = Path(tmp_dir) / "Chrono Trigger (USA).state1"
            state_file.write_bytes(b"s")
            thumb = Path(tmp_dir) / "Chrono Trigger (USA).state1.png"
            thumb.write_bytes(b"p")
            state = save_states.list_states(tmp_dir, ROM)[0]
            self.assertTrue(save_states.delete_state(state))
            self.assertFalse(state_file.exists())
            self.assertFalse(thumb.exists())

    def test_delete_of_a_gone_file_reports_failure(self):
        state = save_states.SaveState("/nope/x.state", 0, 0)
        self.assertFalse(save_states.delete_state(state))


class WhatIsNotAStateTests(unittest.TestCase):
    """The states directory holds companions and unrelated files too."""

    def _states(self, tmp_dir, *names):
        console = Path(tmp_dir) / "SFC"
        console.mkdir(parents=True)
        for name in names:
            (console / name).write_bytes(b"state")
        return console

    def test_the_automatic_state_and_the_thumbnails_are_not_slots(self):
        self.assertIsNone(save_states._slot_for(Path("Game.state.auto")))
        self.assertIsNone(save_states._slot_for(Path("Game.png")))
        self.assertEqual(save_states._slot_for(Path("Game.state")), 0)
        self.assertEqual(save_states._slot_for(Path("Game.state3")), 3)

    def test_a_companion_file_is_not_listed_as_a_state(self):
        with TemporaryDirectory() as tmp_dir:
            self._states(
                tmp_dir, "Chrono Trigger (USA).state1", "Chrono Trigger (USA).srm"
            )
            states = save_states.list_states(tmp_dir, ROM)
        self.assertEqual([state.slot for state in states], [1])

    def test_a_file_that_vanishes_mid_scan_is_skipped(self):
        # RetroArch writes into this directory while OpenEmux reads it, so an
        # entry that was listed a moment ago may be gone by the stat.
        class _Vanishing:
            stem = "Chrono Trigger (USA)"
            suffix = ".state2"

            def is_file(self):
                return True

            def is_dir(self):
                return False

            def stat(self):
                raise OSError("gone")

        with TemporaryDirectory() as tmp_dir:
            self._states(tmp_dir, "Chrono Trigger (USA).state1")
            real_entries = save_states._entries

            def _entries(directory):
                return list(real_entries(directory)) + [_Vanishing()]

            with mock.patch.object(save_states, "_entries", _entries):
                states = save_states.list_states(tmp_dir, ROM)

        self.assertEqual([state.slot for state in states], [1])

    def test_the_newest_copy_of_a_slot_is_the_one_that_counts(self):
        # Two cores saved slot 1 and only one of them is what the user just
        # made; the console directory is scanned before its per-core ones, so
        # this is the case where the second copy found is the older.
        with TemporaryDirectory() as tmp_dir:
            console = self._states(tmp_dir, "Chrono Trigger (USA).state1")
            nested = console / "snes9x"
            nested.mkdir()
            older = nested / "Chrono Trigger (USA).state1"
            older.write_bytes(b"older")
            os.utime(older, (1_000_000, 1_000_000))

            states = save_states.list_states(console, ROM)

        self.assertEqual(len(states), 1)
        self.assertEqual(states[0].path.parent.name, "SFC")


class WhenAStateWillNotBudgeTests(unittest.TestCase):
    def test_a_state_that_cannot_be_renamed_does_not_stop_the_rest(self):
        with TemporaryDirectory() as tmp_dir:
            console = Path(tmp_dir) / "SFC"
            console.mkdir(parents=True)
            stuck = console / "Chrono Trigger (USA).state1"
            stuck.write_bytes(b"state")
            (console / "Chrono Trigger (USA).state2").write_bytes(b"state")
            real_rename = Path.rename

            def _refuse(self, target):
                if self == stuck:
                    raise OSError("read-only")
                return real_rename(self, target)

            with mock.patch.object(Path, "rename", _refuse):
                with self.assertLogs("openemux.core.save_states", level="WARNING"):
                    moved = save_states.rename_states(
                        tmp_dir, "Chrono Trigger (USA)", "Chrono Trigger"
                    )

        self.assertEqual(moved, 1)

    def test_a_screenshot_that_will_not_delete_is_not_an_error(self):
        # The state itself is gone, which is what the user asked for.
        with TemporaryDirectory() as tmp_dir:
            console = Path(tmp_dir) / "SFC"
            console.mkdir(parents=True)
            state = console / "Chrono Trigger (USA).state1"
            state.write_bytes(b"state")
            thumbnail = console / "Chrono Trigger (USA).state1.png"
            thumbnail.write_bytes(b"png")

            entry = save_states.list_states(tmp_dir, ROM)[0]
            thumbnail.unlink()
            self.assertTrue(save_states.delete_state(entry))
            self.assertFalse(state.exists())


if __name__ == "__main__":
    unittest.main()
